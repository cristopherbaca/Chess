"""Independent, resumable relative Elo reporting for the selected champion."""
from dataclasses import asdict
import json
from pathlib import Path
import time
from .evaluation import ClassicalEvaluator, DEFAULT_WEIGHTS
from .runtime import Engine
from .search import SearchOptions
from .matches import MatchConfig, run_match, evidence, atomic_json, fingerprint, implementation_id


def describe(report):
    pairs = report.get('pairs', 0)
    games = report.get('finished_games', 0)
    if pairs < 10:
        return f'Relative Elo: pending ({pairs}/10 valid opening pairs minimum; {games} finished games).'
    value = report.get('elo_difference')
    interval = report.get('elo_interval_95') or [None, None]
    low = '-infinity' if interval[0] is None else f'{interval[0]:+.0f}'
    high = '+infinity' if interval[1] is None else f'{interval[1]:+.0f}'
    estimate = f'{value:+.0f}' if value is not None else 'unbounded (all wins or all losses)'
    return (f'Relative Elo vs classical baseline: {estimate}; 95% interval [{low}, {high}]; '
            f'{pairs} valid pairs, W/D/L {report.get("wins", 0)}/{report.get("draws", 0)}/{report.get("losses", 0)}.')


def measure(cfg, candidate_id, candidate_factory, deadline):
    config = MatchConfig(pairs=max(10, int(cfg.get('rating_pairs', 32))), seed=cfg['seed'] + 192837465,
                         move_seconds=cfg.get('rating_move_seconds', .1), nodes=cfg.get('rating_nodes', 10000),
                         max_plies=1024, base_seconds=120, increment=cfg.get('rating_move_seconds', .1))
    reference = {'kind': 'fixed-classical-baseline', 'weights': DEFAULT_WEIGHTS,
                 'options': asdict(SearchOptions())}
    identity = {'candidate': candidate_id, 'reference': reference, 'config': asdict(config),
                'implementation': implementation_id()}
    folder = Path(cfg['root'])/'experiments'/cfg['run_name']/'ratings'/fingerprint(identity)[:24]
    latest = folder.parent/'latest.json'
    report_path = folder/'report.json'
    if report_path.exists():
        saved = json.loads(report_path.read_text())
        if saved.get('complete') or saved.get('finished_games', 0) >= 2*config.pairs:
            print(describe(saved), flush=True)
            atomic_json(latest, {**saved, 'identity': identity, 'directory': str(folder), 'note':
                        'Relative Elo at these controls only; not a FIDE, Chess.com or Lichess rating.'})
            return saved
    print('Measuring selected champion against a fixed classical baseline; no training games count toward this estimate.', flush=True)
    def progress(finished, total):
        if finished % 2:
            return
        rows = [json.loads(path.read_text()) for path in sorted(folder.glob('pair_*.json'))]
        rows = [row for row in rows if row.get('done')]
        result = evidence(rows, config.pairs)
        result['finished_games'] = len(rows)
        print(f'Rating games: {finished}/{total}. {describe(result)}', flush=True)
    report = run_match(candidate_factory, lambda: Engine(ClassicalEvaluator()), config, folder,
                       candidate_id, reference, deadline, progress=progress)
    atomic_json(latest, {**report, 'identity': identity, 'directory': str(folder),
                'note': 'Relative Elo at these controls only; not a FIDE, Chess.com or Lichess rating.'})
    print(describe(report), flush=True)
    return report
