"""Versioned search profiles, tactical diagnostics and one-at-a-time ablations."""
import argparse
from dataclasses import asdict, replace
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import platform
import sys
import time
import tracemalloc
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import chess
from chess_ai.runtime import Engine, load_engine
from chess_ai.search import SearchOptions
from chess_ai.matches import MatchConfig, run_match, atomic_json

ROOT = Path(__file__).resolve().parents[1]


def outcome(case, move):
    if move is None:
        return False
    if case['goal'] == 'diagnostic':
        return None
    board = chess.Board(case['fen'])
    if case['goal'] == 'bestmove':
        return move.uci() in case['moves']
    board.push(move)
    if case['goal'] == 'mate':
        return board.is_checkmate()
    for reply in board.legal_moves:
        board.push(reply)
        mate = board.is_checkmate()
        board.pop()
        if mate:
            return False
    return True


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('--seconds', type=float, default=.25)
    parser.add_argument('--nodes', type=int, default=10000)
    parser.add_argument('--depth', type=int, default=4)
    parser.add_argument('--model')
    parser.add_argument('--ablations', action='store_true')
    parser.add_argument('--match-pairs', type=int, default=0)
    args = parser.parse_args()
    cases = json.loads((ROOT / 'tests/tactics.json').read_text())['positions']
    base = SearchOptions(pvs=False, aspiration=False, see=False, countermove=False)
    variants = [('baseline', base), ('default', SearchOptions())]
    if args.ablations:
        variants += [(name, replace(base, pvs=True, **{name: True}) if name in ('null_move', 'lmr', 'futility') else replace(base, **{name: True})) for name in
                     ('pvs', 'aspiration', 'see', 'countermove', 'null_move', 'lmr', 'futility', 'check_extensions')]
    source_hash = hashlib.sha256(b''.join(p.read_bytes() for p in sorted((ROOT / 'chess_ai').glob('*.py')))).hexdigest()
    report = {'schema': 1, 'utc': datetime.now(timezone.utc).isoformat(), 'source_sha256': source_hash,
              'platform': platform.platform(), 'python': platform.python_version(),
              'limits': {'seconds': args.seconds, 'nodes': args.nodes, 'depth': args.depth},
              'model': args.model or 'default tapered classical evaluator', 'variants': [],
              'note': 'tracemalloc measures Python allocations and adds overhead; these are diagnostics, not Elo evidence.'}
    for name, options in variants:
        reference = replace(base, pvs=True) if name in ('null_move', 'lmr', 'futility') else base
        reference_name = 'pvs' if name in ('null_move', 'lmr', 'futility') else 'baseline'
        rows = []
        for case in cases:
            board = chess.Board(case['fen'])
            if not board.is_valid():
                raise ValueError('Invalid fixture ' + case['id'])
            engine = load_engine(args.model, options=options)
            tracemalloc.start()
            answer = engine.choose(board, seconds=args.seconds, nodes=args.nodes, depth=args.depth)
            _, peak = tracemalloc.get_traced_memory()
            tracemalloc.stop()
            rows.append({'id': case['id'], 'theme': case['theme'], 'move': answer.move.uci() if answer.move else None,
                         'score': answer.score, 'depth': answer.depth, 'passed': outcome(case, answer.move),
                         'legal': answer.move in board.legal_moves, 'python_peak_bytes': peak, 'stats': answer.stats})
        item = {'name': name, 'baseline': reference_name, 'options': asdict(options), 'positions': rows,
                'solved': sum(r['passed'] is True for r in rows), 'scored': sum(r['passed'] is not None for r in rows)}
        if args.match_pairs and name != 'baseline':
            cfg = MatchConfig(pairs=args.match_pairs, seed=8021, move_seconds=.005, nodes=32, max_plies=100)
            item['match'] = run_match(lambda o=options: load_engine(args.model, options=o),
                                     lambda: load_engine(args.model, options=reference), cfg,
                                     args.output.parent / ('matches_' + name), source_hash + name, source_hash + reference_name)
        report['variants'].append(item)
        atomic_json(args.output, report)
        print(f"{name}: {item['solved']}/{item['scored']} tactical targets; {len(rows)} legal-position profiles", flush=True)
    print('Saved', args.output)


if __name__ == '__main__':
    main()
