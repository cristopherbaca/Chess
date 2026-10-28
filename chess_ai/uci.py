"""Standard-chess UCI adapter with asynchronous go/stop and clock allocation."""
import argparse
import contextlib
import sys
import threading
import time
import chess
from .runtime import load_engine
from .search import SearchOptions, MATE, MATE_BOUND


class UCI:
    def __init__(self, engine, output=print):
        self.engine = engine
        self.board = chess.Board()
        self.output = output
        self.lock = threading.Lock()
        self.thread = None
        self.stop_event = threading.Event()

    def emit(self, text):
        with self.lock:
            self.output(text)

    def stop(self):
        self.stop_event.set()
        if self.thread:
            self.thread.join(timeout=5)
            if self.thread.is_alive():
                raise RuntimeError('Search is still finishing a native evaluation')
        self.thread = None

    def go(self, tokens):
        self.stop()
        values = {}
        for i, token in enumerate(tokens):
            if token in ('depth', 'nodes', 'movetime', 'wtime', 'btime', 'winc', 'binc', 'movestogo') and i + 1 < len(tokens):
                values[token] = max(0, int(tokens[i + 1]))
        color = 'w' if self.board.turn else 'b'
        if 'movetime' in values:
            seconds = max(0, values['movetime'] / 1000 - .005)
        elif color + 'time' in values:
            remaining = values[color + 'time'] / 1000
            increment = values.get(color + 'inc', 0) / 1000
            seconds = max(0, min(remaining * .2, remaining / max(1, values.get('movestogo', 30)) + increment * .7) - .01)
        else:
            seconds = float('inf') if 'infinite' in tokens else 60 if 'depth' in values or 'nodes' in values else 1
        self.stop_event = threading.Event()
        board = self.board.copy(stack=True)
        started = time.monotonic()

        def iteration(depth, score, pv, stats):
            elapsed = time.monotonic() - started
            if abs(score) > MATE_BOUND:
                mate = max(1, (MATE - int(abs(score)) + 1) // 2) * (1 if score > 0 else -1)
                score_text = f'mate {mate}'
            else:
                score_text = f'cp {round(score)}'
            self.emit(f"info depth {depth} score {score_text} nodes {stats.get('nodes', 0)} time {int(elapsed * 1000)} nps {int(stats.get('nodes', 0) / max(elapsed, 1e-9))} pv {' '.join(m.uci() for m in pv)}")

        def work():
            try:
                result = self.engine.choose(board, seconds=seconds, nodes=values.get('nodes', 10**9),
                                            depth=values.get('depth', 64), stop=self.stop_event, on_iteration=iteration)
                self.emit('bestmove ' + (result.move.uci() if result.move else '0000'))
            except Exception as error:
                self.emit(f'info string search error: {type(error).__name__}: {error}')
                legal = list(board.legal_moves)
                self.emit('bestmove ' + (legal[0].uci() if legal else '0000'))
        self.thread = threading.Thread(target=work, daemon=True)
        self.thread.start()

    def command(self, line):
        tokens = line.strip().split()
        if not tokens:
            return True
        command = tokens[0]
        try:
            if command == 'uci':
                self.emit('id name Chess Independent Engine 2')
                self.emit('id author Chess project')
                for name in ('PVS', 'Aspiration', 'SEE', 'Countermove', 'NullMove', 'LMR', 'Futility', 'CheckExtensions'):
                    key = {'NullMove': 'null_move', 'CheckExtensions': 'check_extensions'}.get(name, name.lower())
                    self.emit(f'option name {name} type check default {str(getattr(self.engine.searcher.options, key)).lower()}')
                self.emit('uciok')
            elif command == 'isready':
                self.emit('readyok')
            elif command == 'ucinewgame':
                self.stop()
                self.engine.searcher.tt.clear()
                self.board = chess.Board()
            elif command == 'setoption':
                self.stop()
                if len(tokens) != 5 or tokens[1] != 'name' or tokens[3] != 'value':
                    raise ValueError('Expected setoption name OPTION value true|false')
                key = {'NullMove': 'null_move', 'CheckExtensions': 'check_extensions'}.get(tokens[2], tokens[2].lower())
                if key not in ('pvs', 'aspiration', 'see', 'countermove', 'null_move', 'lmr', 'futility', 'check_extensions') or tokens[4] not in ('true', 'false'):
                    raise ValueError('Unsupported option')
                setattr(self.engine.searcher.options, key, tokens[4] == 'true')
                self.engine.searcher.tt.clear()
            elif command == 'position':
                self.stop()
                if tokens[1] == 'startpos':
                    board, index = chess.Board(), 2
                elif tokens[1] == 'fen':
                    board, index = chess.Board(' '.join(tokens[2:8])), 8
                    if not board.is_valid():
                        raise ValueError('Invalid position')
                else:
                    raise ValueError('Expected startpos or fen')
                if len(tokens) > index:
                    if tokens[index] != 'moves':
                        raise ValueError('Expected moves')
                    for move in tokens[index + 1:]:
                        board.push_uci(move)
                self.board = board
            elif command == 'go':
                self.go(tokens[1:])
            elif command == 'stop':
                self.stop()
            elif command == 'quit':
                self.stop()
                return False
            else:
                self.emit('info string unsupported command ' + command)
        except (ValueError, IndexError, RuntimeError) as error:
            self.emit('info string ' + str(error))
        return True


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--model')
    parser.add_argument('--evaluator', choices=['classical', 'neural', 'hybrid'], default='classical')
    args = parser.parse_args()
    with contextlib.redirect_stdout(sys.stderr):
        engine = load_engine(args.model, args.evaluator)
    protocol = UCI(engine, lambda text: print(text, flush=True))
    try:
        for line in sys.stdin:
            if not protocol.command(line):
                break
    finally:
        protocol.stop()


if __name__ == '__main__':
    main()
