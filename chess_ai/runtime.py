"""Uniform engine/player interface for API, UCI and controlled matches."""
import importlib.util
import json
from pathlib import Path
import sys
import time
import chess
from .evaluation import ClassicalEvaluator, CallableEvaluator, HybridEvaluator
from .neural import SparseEvaluator
from .search import SearchEngine, SearchOptions

DEFAULT_LIMITS = {
    'easy': {'depth': 2, 'seconds': .15, 'nodes': 2000},
    'medium': {'depth': 6, 'seconds': .5, 'nodes': 30000},
    'hard': {'depth': 64, 'seconds': 2.5, 'nodes': 180000},
}


def reconstruct(fen, history=None):
    board = chess.Board(fen)
    if not board.is_valid():
        raise ValueError('Invalid chess position')
    if history:
        restored = chess.Board()
        for move in history:
            restored.push_uci(move)
        if restored.fen() != board.fen():
            raise ValueError('History does not match FEN')
        board = restored
    return board


class Engine:
    def __init__(self, evaluator=None, options=None, settings=None):
        self.evaluator = evaluator or ClassicalEvaluator()
        self.searcher = SearchEngine(self.evaluator, options)
        self.settings = settings or {k: dict(v) for k, v in DEFAULT_LIMITS.items()}

    def choose(self, board, seconds=.1, nodes=10000, depth=64, stop=None, on_iteration=None):
        return self.searcher.search(board, depth, seconds, nodes, stop, on_iteration)

    def values(self, boards):
        return [self.evaluator(board) for board in boards]

    def get_move(self, fen, history=None, difficulty='medium'):
        started = time.monotonic()
        board = reconstruct(fen, history)
        if board.is_game_over() or board.is_repetition(3) or board.is_fifty_moves():
            raise ValueError('Game over')
        limits = self.settings[difficulty]
        result = self.choose(board, limits['seconds'], limits['nodes'], limits['depth'])
        return {'move': result.move.uci(), 'info': {'eval': result.score, 'depth': result.depth,
                'nodes': result.stats['nodes'], 'time_ms': int((time.monotonic() - started) * 1000),
                'pv': [m.uci() for m in result.pv], 'search_stats': result.stats}}


def load_engine(path=None, evaluator='classical', options=None):
    if path is None:
        return Engine(options=options)
    path = Path(path)
    if path.suffix == '.npz':
        neural = SparseEvaluator.load(path)
        return Engine(HybridEvaluator(ClassicalEvaluator(), neural) if evaluator == 'hybrid' else neural, options)
    metadata = json.loads(path.read_text())
    if metadata.get('schema') == 'tapered-features-v1':
        return Engine(ClassicalEvaluator.load(path), options)
    # Existing saved champions retain their own feature definitions and weights.
    module_path = path.parent / 'cristopher_engine.py'
    spec = importlib.util.spec_from_file_location('chess_saved_' + str(abs(hash(str(path.resolve())))), module_path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    saved = module.CristopherEngine(path)
    if hasattr(saved, 'evaluator') and hasattr(saved, 'searcher'):
        # Preserve accumulator hooks and the validated configuration of modular
        # exports instead of reducing them to an opaque callable.
        return Engine(saved.evaluator, options or saved.searcher.options, saved.settings)
    if hasattr(saved, 'values'):
        neural = CallableEvaluator(lambda board: saved.values([board])[0])
        value = HybridEvaluator(ClassicalEvaluator(), neural) if evaluator == 'hybrid' else neural
    else:
        value = CallableEvaluator(lambda board: module.static_evaluate(board, saved.nn or saved.genome))
    return Engine(value, options)
