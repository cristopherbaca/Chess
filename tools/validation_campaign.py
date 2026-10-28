"""Reproducible independent positions, paired matches and untouched-label evaluation."""
import argparse
from collections import Counter
from dataclasses import asdict, replace
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import platform
import sys
import time
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import chess
import numpy as np
from chess_ai.evaluation import ClassicalEvaluator
from chess_ai.neural import SparseEvaluator
from chess_ai.runtime import load_engine
from chess_ai.search import SearchOptions
from chess_ai.matches import MatchConfig, run_match, atomic_json, implementation_id
from tools.benchmark_engine import outcome


def configurations():
    base = SearchOptions(pvs=False, aspiration=False, see=False, countermove=False)
    result = {'baseline': (base, base)}
    for name in ('pvs', 'aspiration', 'see', 'countermove', 'null_move', 'lmr', 'futility', 'check_extensions'):
        reference = replace(base, pvs=True) if name in ('null_move', 'lmr', 'futility') else base
        result[name] = (replace(reference, **{name: True}), reference)
    result['default'] = (SearchOptions(), base)
    return result


def identity(path, options, evaluator='neural'):
    return {'model_sha256': hashlib.sha256(Path(path).read_bytes()).hexdigest() if path else 'default-classical',
            'search': asdict(options), 'evaluator': evaluator}


def positions(args):
    cases = []
    for name in ('puzzles', 'endgames'):
        data = json.loads((args.fixtures / (name + '.json')).read_text())
        cases.extend({**case, 'suite': name} for case in data['positions'])
    report = {'source_sha256': implementation_id(), 'limits': {'seconds': args.seconds, 'nodes': args.nodes},
              'platform': platform.platform(), 'python': platform.python_version(),
              'utc': datetime.now(timezone.utc).isoformat(), 'variants': []}
    for name in args.variants:
        options, _ = configurations()[name]
        rows = []
        for case in cases:
            engine = load_engine(args.model, options=options)
            board = chess.Board(case['fen'])
            answer = engine.choose(board, seconds=args.seconds, nodes=args.nodes, depth=64)
            rows.append({'id': case['id'], 'suite': case['suite'], 'themes': case.get('themes', [case['theme']]),
                         'move': answer.move.uci(), 'legal': answer.move in board.legal_moves,
                         'expected': case.get('moves'), 'passed': outcome(case, answer.move),
                         'depth': answer.depth, 'stats': answer.stats})
        item = {'name': name, 'options': asdict(options), 'model': identity(args.model, options), 'positions': rows,
                'summary': {s: {'solved': sum(r['passed'] is True for r in rows if r['suite'] == s),
                                'scored': sum(r['passed'] is not None for r in rows if r['suite'] == s),
                                'total': sum(r['suite'] == s for r in rows)} for s in ('puzzles', 'endgames')}}
        report['variants'].append(item)
        atomic_json(args.output / 'positions.json', report)
        print(name, item['summary'], flush=True)


def matches(args):
    cfg = MatchConfig(pairs=args.pairs, seed=args.seed, move_seconds=args.seconds, nodes=args.nodes,
                      max_plies=1024, base_seconds=60, increment=.1,
                      opening_file=str(args.fixtures / 'openings.json'))
    reports = []
    variants = args.variants if not args.model else ['model']
    for attempt, name in enumerate(variants, 1):
        if name == 'baseline':
            continue
        options, reference = configurations()[name] if name != 'model' else (SearchOptions(), SearchOptions())
        path = args.output / name
        report = run_match(lambda: load_engine(args.model, args.evaluator, options=options),
                           lambda: load_engine(args.incumbent, options=reference), cfg, path,
                           identity(args.model, options, args.evaluator), identity(args.incumbent, reference),
                           attempt=attempt,
                           progress=lambda n, total: print(f'{name}: {n}/{total} games', flush=True) if n % 8 == 0 else None)
        events = {'candidate': Counter(), 'incumbent': Counter()}
        depths = {'candidate': [], 'incumbent': []}
        for game in path.glob('pair_*.json'):
            data = json.loads(game.read_text())
            for row in data['evaluations']:
                side = 'candidate' if chess.Board(row['fen']).turn == data['candidate_white'] else 'incumbent'
                depths[side].append(row['depth'])
                for metric in ('nodes', 'qnodes', 'null_cutoffs', 'reductions', 'futility_skips', 'extensions', 'pvs_researches'):
                    events[side][metric] += row.get('search_stats', {}).get(metric, 0)
        report['search_events'] = events
        report['mean_depth'] = {k: float(np.mean(v)) if v else None for k, v in depths.items()}
        reports.append({'name': name, **report})
        atomic_json(args.output / 'summary.json', {'config': asdict(cfg), 'reports': reports,
                    'note': 'Fast local time control. No absolute Elo claim; capped/error pairs are ineligible. Source/config fingerprints prevent stale resume.'})
        print(name, report['wins'], report['draws'], report['losses'], 'accepted:', report['accepted'], flush=True)


def heldout(args):
    data = [json.loads(line) for line in Path(args.data).read_text().splitlines() if line.strip()]
    rows = [row for row in data if row.get('split') == 'test']
    if not rows:
        raise ValueError('No explicit untouched test rows')
    neural = SparseEvaluator.load(args.model)
    evaluators = {'zero': lambda b: 0., 'classical': ClassicalEvaluator(), 'neural': neural,
                  'quantized': neural.quantized()}
    scores = {k: [] for k in evaluators}
    prediction_errors = []
    for row in rows:
        board = chess.Board(row['fen'])
        target = np.tanh(row['cp_white'] / 400) * (1 if board.turn else -1)
        values = {k: float(v(board)) for k, v in evaluators.items()}
        for name, value in values.items():
            scores[name].append(float((np.tanh(value / 400) - target) ** 2))
        prediction_errors.append(abs(values['neural'] - values['quantized']))
    rng = np.random.default_rng(20261027)
    differences = np.asarray(scores['neural']) - np.asarray(scores['classical'])
    means = [float(np.mean(rng.choice(differences, len(differences), replace=True))) for _ in range(2000)]
    report = {'test_positions': len(rows), 'dataset_sha256': hashlib.sha256(Path(args.data).read_bytes()).hexdigest(),
              'model_sha256': hashlib.sha256(Path(args.model).read_bytes()).hexdigest(),
              'mse_tanh_cp400': {k: float(np.mean(v)) for k, v in scores.items()},
              'neural_minus_classical_mse_bootstrap95': np.quantile(means, [.025, .975]).tolist(),
              'quantization_max_abs_cp': max(prediction_errors),
              'note': 'Untouched test split used once after model selection. Bootstrap assumes independent sampled positions; source prefix and related-position bias remain. Prediction loss is not Elo.'}
    atomic_json(args.output / 'heldout.json', report)
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['positions', 'matches', 'heldout'])
    parser.add_argument('--fixtures', type=Path, default=Path('tests/validation'))
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--variants', nargs='+', choices=list(configurations()), default=list(configurations()))
    parser.add_argument('--model')
    parser.add_argument('--incumbent')
    parser.add_argument('--evaluator', choices=['neural', 'hybrid'], default='neural')
    parser.add_argument('--data')
    parser.add_argument('--pairs', type=int, default=32)
    parser.add_argument('--seconds', type=float, default=.01)
    parser.add_argument('--nodes', type=int, default=100000)
    parser.add_argument('--seed', type=int, default=20261027)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    globals()[args.action](args)
