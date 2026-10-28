"""Fetch bounded CC0 research samples and cache independent position oracles.

Network access is confined to this explicit preparation tool. Production search
never consults Lichess, a tablebase server, or another engine.
"""
import argparse
import csv
from datetime import datetime, timezone
import hashlib
import io
import json
from pathlib import Path
import random
import sys
import time
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import chess
import chess.pgn
import requests
import zstandard
from chess_ai.matches import atomic_json

DATABASE = 'https://database.lichess.org/'
THEMES = ('pin', 'fork', 'skewer', 'discoveredAttack', 'doubleCheck', 'mate',
          'defensiveMove', 'sacrifice', 'intermezzo', 'quietMove', 'advancedPawn', 'zugzwang')


def canonical(board):
    return min(' '.join(board.fen().split()[:4]), ' '.join(board.mirror().fen().split()[:4]))


def stream(url):
    # Streaming intentionally reads only a prefix, never the multi-GB archive.
    with requests.get(url, stream=True, timeout=(15, 90)) as response:
        response.raise_for_status()
        with zstandard.ZstdDecompressor().stream_reader(response.raw) as decoded:
            with io.TextIOWrapper(decoded) as text:
                yield from text


def puzzles(path, per_theme=10, max_rows=100000):
    counts = dict.fromkeys(THEMES, 0)
    cases, seen = [], set()
    for index, row in enumerate(csv.DictReader(stream(DATABASE + 'lichess_db_puzzle.csv.zst'))):
        if index >= max_rows or all(n >= per_theme for n in counts.values()):
            break
        tags = row['Themes'].split()
        needed = [t for t in tags if t in counts and counts[t] < per_theme]
        if not needed or int(row['Popularity']) < 80 or int(row['NbPlays']) < 100 or int(row['RatingDeviation']) > 100:
            continue
        board = chess.Board(row['FEN'])
        moves = row['Moves'].split()
        board.push_uci(moves[0])  # Published FEN is BEFORE the opponent's move.
        key = canonical(board)
        if key in seen or not board.is_valid():
            continue
        trial = board.copy()
        for move in moves[1:]:
            trial.push_uci(move)
        cases.append({'id': 'lichess-' + row['PuzzleId'], 'fen': board.fen(), 'themes': tags,
                      'theme': needed[0], 'goal': 'mate' if 'mateIn1' in tags else 'bestmove',
                      'moves': [moves[1]], 'solution': moves[1:], 'rating': int(row['Rating']),
                      'source': 'https://lichess.org/training/' + row['PuzzleId'],
                      'game_url': row['GameUrl'], 'oracle': 'published Lichess solution'})
        seen.add(key)
        for tag in needed:
            counts[tag] += 1
    result = {'source': DATABASE + '#puzzles', 'license': 'CC0-1.0',
              'selection': {'per_theme': per_theme, 'max_rows': max_rows, 'rows_scanned': index + 1,
                            'note': 'Deterministic prefix sample with quality filters, not a random population sample.'},
              'theme_counts': counts, 'positions': cases}
    atomic_json(path, result)
    return result


def endgames(path):
    originals = json.loads(Path('tests/tactics.json').read_text())['positions']
    seeds = [(p['id'], p['fen']) for p in originals if p['goal'] == 'diagnostic']
    seeds += [('rook_pawn_corner', 'k7/P7/K7/8/8/8/8/8 w - - 0 1'),
              ('key_square', '8/4k3/8/4K3/4P3/8/8/8 w - - 0 1'),
              ('king_in_front', '8/8/3k4/8/3K4/3P4/8/8 w - - 0 1')]
    cases, raw = [], {}
    rank = {'loss': 0, 'blessed-loss': 1, 'draw': 2, 'cursed-win': 3, 'win': 4}
    for name, fen in seeds:
        for mirrored in (False, True):
            board = chess.Board(fen)
            if mirrored:
                board = board.mirror()
            case_id = name + ('_mirror' if mirrored else '')
            url = 'https://tablebase.lichess.ovh/standard'
            response = requests.get(url, params={'fen': board.fen()}, timeout=30)
            response.raise_for_status()
            data = response.json()
            # Move categories are from the successor's side-to-move perspective.
            if not data['moves'] or any(m['category'] not in rank for m in data['moves']):
                raise ValueError('Unknown tablebase outcome')
            best = min(rank[m['category']] for m in data['moves'])
            allowed = [m['uci'] for m in data['moves'] if rank[m['category']] == best]
            cases.append({'id': case_id, 'fen': board.fen(), 'theme': name, 'goal': 'bestmove',
                          'moves': allowed, 'category': data['category'], 'oracle': 'Syzygy WDL via Lichess',
                          'source': response.url})
            raw[case_id] = data
            time.sleep(.2)
    atomic_json(path, {'positions': cases, 'raw_responses': raw,
                      'retrieved_utc': datetime.now(timezone.utc).isoformat(),
                      'interpretation': 'Any move preserving optimal WDL is accepted; this does not test fastest conversion.'})
    return cases


def opening_suite(path):
    choices, seen, sources = [], set(), {}
    for letter in 'abcde':
        url = f'https://raw.githubusercontent.com/lichess-org/chess-openings/master/{letter}.tsv'
        response = requests.get(url, timeout=30); response.raise_for_status()
        sources[url] = hashlib.sha256(response.content).hexdigest()
        for row in csv.DictReader(io.StringIO(response.text), delimiter='\t'):
            game = chess.pgn.read_game(io.StringIO(row['pgn']))
            if game is None or game.errors:
                continue
            moves = list(game.mainline_moves())
            if len(moves) < 8:
                continue
            board = chess.Board()
            for move in moves[:12]:
                board.push(move)
            key = canonical(board)
            if board.is_game_over() or key in seen:
                continue
            seen.add(key)
            choices.append({'eco': row['eco'], 'name': row['name'], 'moves': [m.uci() for m in board.move_stack]})
    random.Random(20261027).shuffle(choices)
    atomic_json(path, {'source': 'https://github.com/lichess-org/chess-openings', 'license': 'CC0-1.0',
                       'source_sha256': sources, 'openings': choices[:256]})


def labels(path, count, exclude):
    seen = set(exclude)
    rows, scanned = [], 0
    for line in stream(DATABASE + 'lichess_db_eval.jsonl.zst'):
        scanned += 1
        data = json.loads(line)
        board = chess.Board(data['fen'] + ' 0 1')
        key = canonical(board)
        if not board.is_valid() or board.is_game_over() or key in seen:
            continue
        candidates = [e for e in data['evals'] if e['depth'] >= 20 and e.get('knodes', 0) >= 100 and 'cp' in e['pvs'][0]]
        if not candidates:
            continue
        best = max(candidates, key=lambda e: (e['depth'], e.get('knodes', 0)))
        cp = best['pvs'][0]['cp']
        if abs(cp) > 2000:
            continue
        identity = hashlib.sha256(key.encode()).hexdigest()
        bucket = int(identity[:8], 16) % 100
        split = 'train' if bucket < 70 else 'validation' if bucket < 85 else 'test'
        rows.append({'game_id': 'position-' + identity, 'fen': board.fen(), 'cp_white': cp, 'split': split,
                     'depth': best['depth'], 'knodes': best['knodes'], 'source': DATABASE + '#evals'})
        seen.add(key)
        if len(rows) >= count:
            break
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(''.join(json.dumps(row) + '\n' for row in rows))
    atomic_json(path.with_suffix('.manifest.json'), {
        'source': DATABASE + '#evals', 'license': 'CC0-1.0', 'rows': len(rows), 'scanned': scanned,
        'sha256': hashlib.sha256(path.read_bytes()).hexdigest(),
        'splits': {s: sum(r['split'] == s for r in rows) for s in ('train', 'validation', 'test')},
        'selection': 'Prefix sample; depth >=20, knodes >=100, abs(cp)<=2000; deduplicated by canonical color-mirrored position.',
        'grouping': 'Source has no game IDs. Position IDs prevent exact/mirrored duplicates across splits; related positions may still occur.',
        'excluded_test_positions': len(exclude), 'retrieved_utc': datetime.now(timezone.utc).isoformat()})


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=Path('tests/validation'))
    parser.add_argument('--labels', type=Path)
    parser.add_argument('--positions', type=int, default=20000)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    p = args.output / 'puzzles.json'
    suite = json.loads(p.read_text()) if p.exists() else puzzles(p)
    print('Puzzles:', len(suite['positions']), suite['theme_counts'], flush=True)
    p = args.output / 'endgames.json'
    ends = json.loads(p.read_text())['positions'] if p.exists() else endgames(p)
    p = args.output / 'openings.json'
    if not p.exists():
        opening_suite(p)
    if args.labels and not args.labels.exists():
        excluded = {canonical(chess.Board(c['fen'])) for c in suite['positions'] + ends}
        labels(args.labels, args.positions, excluded)
        print('Labels:', args.labels, flush=True)
