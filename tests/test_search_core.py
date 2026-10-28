import dataclasses
import random
import threading
import unittest
import chess
import chess.polyglot
from chess_ai.board import Position
from chess_ai.search import SearchEngine, SearchOptions, MATE, see


def material(board):
    score = sum((len(board.pieces(pt, True)) - len(board.pieces(pt, False))) * value
                for pt, value in ((1, 100), (2, 320), (3, 335), (4, 500), (5, 900)))
    return score if board.turn else -score


class SearchCoreTests(unittest.TestCase):
    def test_incremental_hash_random_make_unmake(self):
        rng = random.Random(28)
        position = Position(chess.Board())
        original = position.key()
        for _ in range(120):
            legal = list(position.board.legal_moves)
            if not legal:
                break
            position.push(rng.choice(legal))
            self.assertEqual(position.hash, chess.polyglot.zobrist_hash(position.board))
        while position.stack:
            position.pop()
            self.assertEqual(position.hash, chess.polyglot.zobrist_hash(position.board))
        self.assertEqual(position.key(), original)

    def test_special_move_and_null_hash(self):
        for fen in ['r3k2r/8/8/8/8/8/8/R3K2R w KQkq - 0 1',
                    '4k3/8/8/3pP3/8/8/8/4K3 w - d6 0 1',
                    '1r5k/P7/8/8/8/8/8/7K w - - 0 1']:
            pos = Position(chess.Board(fen))
            initial = pos.key()
            for move in list(pos.board.legal_moves) + [chess.Move.null()]:
                pos.push(move)
                self.assertEqual(pos.hash, chess.polyglot.zobrist_hash(pos.board))
                pos.pop()
                self.assertEqual(pos.key(), initial)

    def test_history_changes_transposition_identity(self):
        board = chess.Board()
        for move in ['g1f3', 'g8f6', 'f3g1', 'f6g8'] * 2:
            board.push_uci(move)
        a, b = Position(board), Position(chess.Board(board.fen()))
        self.assertEqual(a.hash, b.hash)
        self.assertNotEqual(a.key(), b.key())
        self.assertTrue(a.drawn())
        self.assertFalse(b.drawn())

    def test_mate_stalemate_and_input_preservation(self):
        board = chess.Board('6rk/6pp/7N/8/8/8/8/KQ6 w - - 0 1')
        fen = board.fen()
        result = SearchEngine(material).search(board, depth=3, seconds=5)
        self.assertGreater(result.score, MATE - 10)
        self.assertEqual(board.fen(), fen)
        board.push(result.move)
        self.assertTrue(board.is_checkmate())
        result = SearchEngine(material).search(chess.Board('7k/5Q2/6K1/8/8/8/8/8 b - - 0 1'))
        self.assertIsNone(result.move)
        self.assertEqual(result.score, 0)

    def test_pinned_en_passant_does_not_prevent_repetition(self):
        board = chess.Board('4r1k1/8/8/3pP3/8/8/8/4K3 w - d6 0 2')
        position = Position(board)
        for move in ['e1f1', 'g8h8', 'f1e1', 'h8g8'] * 2:
            position.push(chess.Move.from_uci(move))
        self.assertTrue(position.board.is_repetition(3))
        self.assertTrue(position.drawn())

    def test_fifty_moves_and_insufficient_material(self):
        for fen in ['7k/8/6K1/8/8/8/R7/8 w - - 100 51', '7k/8/6K1/8/8/8/8/8 w - - 0 1']:
            result = SearchEngine(material).search(chess.Board(fen))
            self.assertEqual(result.score, 0)
            self.assertEqual(result.stats['nodes'], 0)

    def test_quiescence_rejects_poisoned_capture(self):
        board = chess.Board('3r2k1/8/8/3p4/8/8/8/3Q2K1 w - - 0 1')
        result = SearchEngine(material).search(board, depth=1, seconds=5)
        self.assertNotEqual(result.move.uci(), 'd1d5')
        self.assertGreater(result.stats['qnodes'], 0)

    def test_see_recapture_and_pinned_attacker(self):
        board = chess.Board('3r2k1/8/8/3p4/8/8/8/3Q2K1 w - - 0 1')
        self.assertEqual(see(board, chess.Move.from_uci('d1d5')), -800)
        board = chess.Board('4k3/4p3/3n4/2B5/8/8/8/4R1K1 w - - 0 1')
        self.assertEqual(see(board, chess.Move.from_uci('c5d6')), 320)

    def test_pvs_aspiration_and_ordering_match_plain_alpha_beta(self):
        for fen in [chess.STARTING_FEN, '3r2k1/8/8/3p4/8/8/8/3Q2K1 w - - 0 1']:
            board = chess.Board(fen)
            base = SearchOptions(pvs=False, aspiration=False, see=False, countermove=False)
            expected = SearchEngine(material, base).search(board, depth=3, seconds=20)
            for name in ['pvs', 'aspiration', 'see', 'countermove']:
                with self.subTest(feature=name, fen=fen):
                    options = dataclasses.replace(base, **{name: True})
                    result = SearchEngine(material, options).search(board, depth=3, seconds=20)
                    self.assertEqual(result.depth, expected.depth)
                    self.assertEqual(result.score, expected.score)

    def test_selective_features_individually_preserve_forced_mate(self):
        board = chess.Board('6rk/6pp/7N/8/8/8/8/KQ6 w - - 0 1')
        for name in ['null_move', 'lmr', 'futility', 'check_extensions']:
            with self.subTest(feature=name):
                options = SearchOptions(**{name: True})
                result = SearchEngine(material, options).search(board, depth=3, seconds=5)
                child = board.copy()
                child.push(result.move)
                self.assertTrue(child.is_checkmate())

    def test_null_disabled_in_pawn_endgame(self):
        board = chess.Board('8/8/8/3k4/3p4/3K4/3P4/8 w - - 0 1')
        result = SearchEngine(material, SearchOptions(null_move=True)).search(board, depth=4, seconds=5)
        self.assertEqual(result.stats.get('null_cutoffs', 0), 0)

    def test_selective_heuristics_actually_execute(self):
        for feature, metric in [('null_move', 'null_cutoffs'), ('lmr', 'reductions'), ('futility', 'futility_skips')]:
            with self.subTest(feature=feature):
                options = SearchOptions(see=False, aspiration=False, **{feature: True})
                engine = SearchEngine(material, options)
                result = engine.search(chess.Board(), depth=5, seconds=20, nodes=30000)
                self.assertGreater(result.stats.get(metric, 0), 0)
                self.assertIn(result.move, chess.Board().legal_moves)
                self.assertEqual(engine.position.board.fen(), chess.STARTING_FEN)

    def test_stop_and_node_limits_and_tt_capacity(self):
        stop = threading.Event()
        stop.set()
        engine = SearchEngine(material, SearchOptions(tt_capacity=8))
        result = engine.search(chess.Board(), stop=stop)
        self.assertEqual(result.depth, 0)
        self.assertIn(result.move, chess.Board().legal_moves)
        result = engine.search(chess.Board(), seconds=5, nodes=50)
        self.assertLessEqual(result.stats['nodes'], 50)
        self.assertLessEqual(len(engine.tt), 8)
        self.assertEqual(engine.position.board.fen(), chess.STARTING_FEN)


if __name__ == '__main__':
    unittest.main()
