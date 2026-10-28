"""Compare neural beam traversal with a fixed prior evaluator, not learned weights.

python tools/benchmark_search.py --output /tmp/search.json
Use --notebook to compare an archived notebook under identical conditions.
"""
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import platform
import statistics
import time

import chess
import numpy as np

from notebook_engine import ROOT, load_engine, perft, prior_engine


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--notebook', type=Path, default=ROOT / 'vendor/train.ipynb')
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--repeats', type=int, default=3)
    args = parser.parse_args()
    if args.repeats < 1:
        parser.error('--repeats must be positive')
    fixture_path = ROOT / 'tests/engine_positions.json'
    fixture = json.loads(fixture_path.read_text())
    module = load_engine(args.notebook)
    engine = prior_engine(module)
    report = {
        'schema': 1, 'recorded_utc': datetime.now(timezone.utc).isoformat(),
        'engine_source_sha256': module.source_sha256,
        'fixture_sha256': hashlib.sha256(fixture_path.read_bytes()).hexdigest(),
        'python': platform.python_version(), 'platform': platform.platform(),
        'chess': chess.__version__, 'numpy': np.__version__, 'repeats': args.repeats,
        'evaluator': 'fixed material/PST prior + terminal rules; no neural weights',
        'limitations': 'CPU traversal microbenchmark; not CUDA throughput, match strength or Elo.',
        'search': [], 'perft': [],
    }
    for case in fixture['search']:
        elapsed = []
        for _ in range(args.repeats):
            board = chess.Board(case['fen'])
            assert board.is_valid()
            began = time.perf_counter()
            moves, scores, depth, nodes = engine.lookahead(
                board, case['depth'], case['beam'], time.monotonic() + 30)
            elapsed.append(time.perf_counter() - began)
            assert board.fen() == case['fen'] and not board.move_stack
            assert depth == case['depth'], 'Budget interrupted this fixed-depth benchmark'
        seconds = statistics.median(elapsed)
        row = {**case, 'best_move': moves[int(np.argmax(scores))].uci(),
               'completed_depth': depth, 'evaluated_positions': nodes,
               'median_ms': seconds * 1000, 'samples_ms': [s * 1000 for s in elapsed],
               'evaluated_positions_per_second': nodes / seconds}
        if 'branch' in case:
            board.push_uci(case['branch'])
            board.push_uci(case['mate_reply'])
            assert board.is_checkmate()
            row['branch_score'] = float(scores[[m.uci() for m in moves].index(case['branch'])])
            row['recognizes_forced_mate_reply'] = row['branch_score'] <= -module.MATE + 100
        report['search'].append(row)
    for case in fixture['perft']:
        depth = len(case['counts'])
        board = chess.Board(case['fen'])
        began = time.perf_counter()
        nodes = perft(board, depth)
        elapsed = time.perf_counter() - began
        assert nodes == case['counts'][-1]
        report['perft'].append({'name': case['name'], 'depth': depth, 'nodes': nodes,
                                'ms': elapsed * 1000, 'nodes_per_second': nodes / elapsed})
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()
