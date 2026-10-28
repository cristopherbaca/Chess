"""Generate grouped labels from PGNs; optionally annotate with a UCI engine.

The external engine is used only for dataset creation, never production moves.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import chess
import chess.engine
import chess.pgn


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--pgn', nargs='+', required=True)
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('--engine', help='Optional UCI binary for evaluation labels')
    parser.add_argument('--seconds', type=float, default=.1)
    parser.add_argument('--stride', type=int, default=4)
    parser.add_argument('--max-positions', type=int, default=10000)
    args = parser.parse_args()
    if args.stride < 1 or args.max_positions < 1 or args.seconds <= 0:
        parser.error('Positive limits are required')
    engine = chess.engine.SimpleEngine.popen_uci(args.engine) if args.engine else None
    count = 0
    args.output.parent.mkdir(parents=True, exist_ok=True)
    temporary = args.output.with_suffix(args.output.suffix + '.tmp')
    try:
        with temporary.open('w') as output:
            for name in args.pgn:
                with open(name) as handle:
                    while count < args.max_positions:
                        game = chess.pgn.read_game(handle)
                        if game is None:
                            break
                        result = {'1-0': 1., '0-1': 0., '1/2-1/2': .5}.get(game.headers.get('Result'))
                        if result is None or game.errors:
                            continue
                        game_id = hashlib.sha256(str(game).encode()).hexdigest()
                        board = game.board()
                        for ply, move in enumerate(game.mainline_moves(), 1):
                            board.push(move)
                            if ply % args.stride or board.is_game_over() or count >= args.max_positions:
                                continue
                            row = {'fen': board.fen(), 'game_id': game_id, 'result_white': result,
                                   'source': str(Path(name).name)}
                            if engine:
                                info = engine.analyse(board, chess.engine.Limit(time=args.seconds))
                                row.update(cp_white=info['score'].white().score(mate_score=30000),
                                           label_engine=engine.id, label_seconds=args.seconds)
                            output.write(json.dumps(row) + '\n')
                            count += 1
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary, args.output)
    finally:
        if engine:
            engine.quit()
    print(f'Saved {count} grouped positions to {args.output}; validate label quality before training.')


if __name__ == '__main__':
    main()
