"""Add seeded tablebase positions where legal moves have different WDL outcomes."""
import json
from pathlib import Path
import random
import time
import chess
import requests


def extend(path, count=24, seed=20261027):
    data = json.loads(path.read_text())
    rank = {'loss': 0, 'blessed-loss': 1, 'draw': 2, 'cursed-win': 3, 'win': 4}
    for case in data['positions']:
        board = chess.Board(case['fen'])
        if len(case['moves']) == board.legal_moves.count():
            case['goal'] = 'diagnostic'
            case['note'] = 'All legal moves have the same WDL: control only, excluded from best-move accuracy.'
    rng = random.Random(seed)
    seen = {c['fen'] for c in data['positions']}
    accepted = sum(c['id'].startswith('wdl-choice-') for c in data['positions'])
    scanned = 0
    while accepted < count and scanned < 200:
        scanned += 1
        board = chess.Board(None)
        pawn = chess.square(rng.randrange(8), rng.randrange(2, 7))
        squares = rng.sample([s for s in chess.SQUARES if s != pawn], 2)
        board.set_piece_at(pawn, chess.Piece(chess.PAWN, True))
        board.set_piece_at(squares[0], chess.Piece(chess.KING, True))
        board.set_piece_at(squares[1], chess.Piece(chess.KING, False))
        board.turn = rng.choice([True, False])
        if not board.is_valid() or board.is_game_over() or board.fen() in seen:
            continue
        response = requests.get('https://tablebase.lichess.ovh/standard', params={'fen': board.fen()}, timeout=30)
        response.raise_for_status(); result = response.json()
        if not result['moves'] or any(m['category'] not in rank for m in result['moves']):
            continue
        categories = {rank[m['category']] for m in result['moves']}
        time.sleep(.2)
        if len(categories) < 2:
            continue
        case_id = f'wdl-choice-{accepted:03d}'
        case = {'id': case_id, 'fen': board.fen(), 'theme': 'king-pawn WDL preservation', 'goal': 'bestmove',
                'moves': [m['uci'] for m in result['moves'] if rank[m['category']] == min(categories)],
                'category': result['category'], 'oracle': 'Syzygy WDL via Lichess', 'source': response.url}
        data['positions'].append(case); data['raw_responses'][case_id] = result
        seen.add(board.fen()); accepted += 1
        path.write_text(json.dumps(data, indent=2)+'\n')
        print('Discriminating endgames:', accepted, flush=True)
    data['seeded_choice_selection'] = {'seed': seed, 'scanned': scanned, 'accepted': accepted,
                                     'note': 'Select by tablebase outcome diversity only; engine answers were not used.'}
    path.write_text(json.dumps(data, indent=2)+'\n')
    if accepted < count:
        raise RuntimeError('Not enough discriminating positions')


if __name__ == '__main__':
    extend(Path('tests/validation/endgames.json'))
