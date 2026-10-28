"""Run a bounded, resumable family of equal-budget matches and independent suites.

Each subprocess owns both sides of its match. Parallelism uses separate matches,
not shared search state; use --jobs 1 for isolated wall-time measurements.
"""
import argparse
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import json
from pathlib import Path
import platform
import subprocess
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from chess_ai.matches import atomic_json, implementation_id


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--output', type=Path, required=True)
    p.add_argument('--fixtures', default='tests/validation')
    p.add_argument('--seconds', type=float, default=.1)
    p.add_argument('--pairs', type=int, default=32)
    p.add_argument('--jobs', type=int, default=1)
    p.add_argument('--model')
    p.add_argument('--reference-engine')
    args = p.parse_args()
    if args.jobs < 1 or args.pairs < 32 or args.seconds <= 0:
        p.error('Use positive time/jobs and at least 32 opening pairs')
    args.output.mkdir(parents=True, exist_ok=True)
    tasks = []
    for name in ('pvs', 'aspiration', 'see', 'countermove', 'null_move', 'lmr', 'futility', 'check_extensions', 'default'):
        command = [sys.executable, 'tools/validation_campaign.py', 'matches', '--output', str(args.output / name),
                   '--fixtures', args.fixtures, '--variants', name, '--seconds', str(args.seconds), '--pairs', str(args.pairs)]
        tasks.append((name, command))
    if args.model:
        tasks.append(('neural', [sys.executable, 'tools/validation_campaign.py', 'matches', '--output', str(args.output / 'neural'),
                     '--fixtures', args.fixtures, '--model', args.model, '--seconds', str(args.seconds), '--pairs', str(args.pairs)]))
    if args.reference_engine:
        tasks.append(('external', [sys.executable, 'tools/run_match.py', '--output', str(args.output / 'external'),
                     '--incumbent-uci', args.reference_engine, '--seconds', str(args.seconds), '--pairs', str(args.pairs),
                     '--nodes', '100000', '--max-plies', '1024', '--openings', str(Path(args.fixtures) / 'openings.json'),
                     '--seed', '20261027']))
    atomic_json(args.output / 'campaign.json', {'utc': datetime.now(timezone.utc).isoformat(),
                'implementation_sha256': implementation_id(), 'jobs': args.jobs, 'seconds': args.seconds,
                'pairs': args.pairs, 'platform': platform.platform(), 'commands': tasks,
                'note': 'Fixed wall-time and node ceilings. Concurrent matches share CPU resources; not an isolated NPS benchmark.'})

    def run(task):
        name, command = task
        log = args.output / (name + '.log')
        print('Starting', name, flush=True)
        with log.open('w') as handle:
            result = subprocess.run(command, stdout=handle, stderr=subprocess.STDOUT)
        print('Finished', name, 'exit', result.returncode, flush=True)
        return {'name': name, 'exit_code': result.returncode, 'log': str(log)}

    with ThreadPoolExecutor(max_workers=args.jobs) as pool:
        results = list(pool.map(run, tasks))
    atomic_json(args.output / 'completion.json', results)
    if any(row['exit_code'] for row in results):
        raise SystemExit('A campaign job failed; inspect its log and resume with the same settings')


if __name__ == '__main__':
    main()
