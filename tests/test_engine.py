"""Rule and search regressions; no Colab, Stockfish, PyTorch or learned weights.

python -m unittest discover -s tests -p 'test_engine.py' -v
"""
from collections import Counter
import json
from pathlib import Path
import sys
import time
import unittest
from unittest.mock import patch

import chess
import chess.polyglot
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
from notebook_engine import load_engine, perft, prior_engine

POSITIONS = json.loads(Path(__file__).with_name('engine_positions.json').read_text())


class EngineRulesTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.module = load_engine()

    def test_reference_perft_and_board_restoration(self):
        for case in POSITIONS['perft']:
            board = chess.Board(case['fen'])
            original_hash = chess.polyglot.zobrist_hash(board)
            for depth, expected in enumerate(case['counts'], 1):
                with self.subTest(position=case['name'], depth=depth):
                    self.assertEqual(perft(board, depth), expected)
                    self.assertEqual(board.fen(), case['fen'])
                    self.assertEqual(chess.polyglot.zobrist_hash(board), original_hash)
                    self.assertEqual(board.move_stack, [])

    def test_special_moves_make_unmake_hash_and_counts(self):
        cases = [
            ('r3k2r/8/8/8/8/8/8/R3K2R w KQkq - 0 1', ['e1g1', 'e1c1']),
            ('r3k2r/8/8/8/8/8/8/R3K2R b KQkq - 0 1', ['e8g8', 'e8c8']),
            ('4k3/8/8/3pP3/8/8/8/4K3 w - d6 0 2', ['e5d6']),
            ('4k3/P7/8/8/8/8/8/4K3 w - - 0 1', ['a7a8' + p for p in 'qrbn']),
        ]
        search = self.module.AlphaBeta(self.module.genome_default(), 30, 10000)
        for fen, moves in cases:
            board = chess.Board(fen)
            root = chess.polyglot.zobrist_hash(board)
            search.counts = Counter({root: 1})
            for uci in moves:
                with self.subTest(move=uci):
                    move = chess.Move.from_uci(uci)
                    self.assertIn(move, board.legal_moves)
                    key = search.push(board, move)
                    self.assertEqual(key, chess.polyglot.zobrist_hash(board))
                    self.assertNotEqual(key, root)
                    search.pop(board, key)
                    self.assertEqual(board.fen(), fen)
                    self.assertEqual(board.move_stack, [])
                    self.assertEqual(search.counts, Counter({root: 1}))

    def test_en_passant_cannot_expose_king(self):
        board = chess.Board('4r1k1/8/8/3pP3/8/8/8/4K3 w - d6 0 2')
        self.assertTrue(board.is_valid())
        self.assertNotIn(chess.Move.from_uci('e5d6'), board.legal_moves)

    def test_castling_through_check_is_illegal(self):
        board = chess.Board('4kr2/8/8/8/8/8/8/4K2R w K - 0 1')
        self.assertTrue(board.is_valid())
        self.assertNotIn(chess.Move.from_uci('e1g1'), board.legal_moves)

    def test_terminal_scores_and_repetition_history(self):
        for fen, expected in [
            ('7k/6Q1/5K2/8/8/8/8/8 b - - 0 1', -self.module.MATE),
            ('7k/5Q2/6K1/8/8/8/8/8 b - - 0 1', 0),
            ('7k/8/6K1/8/8/8/8/8 w - - 0 1', 0),
            ('7k/8/6K1/8/8/8/R7/8 w - - 100 51', 0),
        ]:
            board = chess.Board(fen)
            self.assertTrue(board.is_valid())
            self.assertEqual(self.module.gpu_terminal(board), expected)
        board = chess.Board()
        history = ['g1f3', 'g8f6', 'f3g1', 'f6g8'] * 2
        for uci in history:
            board.push_uci(uci)
        restored = self.module.board_from_history(board.fen(), history)
        self.assertEqual(self.module.gpu_terminal(restored), 0)
        self.assertIsNone(self.module.gpu_terminal(chess.Board(board.fen())))

    def test_classical_search_finds_mate_and_restores_input(self):
        board = chess.Board('6rk/6pp/7N/8/8/8/8/KQ6 w - - 0 1')
        original = board.fen()
        move, score, depth, _ = self.module.search(board, self.module.genome_default(), 2, 5, 100000)
        board.push(move)
        self.assertTrue(board.is_checkmate())
        self.assertGreater(score, self.module.MATE - 100)
        board.pop()
        self.assertEqual(board.fen(), original)
        self.assertEqual(board.move_stack, [])
        self.assertGreaterEqual(depth, 1)

    def test_classical_node_budget_returns_legal_move(self):
        board = chess.Board()
        move, _, _, nodes = self.module.search(board, self.module.genome_default(), 64, 5, 1)
        self.assertIn(move, board.legal_moves)
        self.assertLessEqual(nodes, 1)
        self.assertEqual(board.move_stack, [])


class NeuralSearchTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.module = load_engine()

    def setUp(self):
        self.engine = prior_engine(self.module)

    def test_forced_mate_replies_survive_beam_pruning_both_colors(self):
        for case in POSITIONS['search']:
            if 'mate_reply' not in case:
                continue
            root = chess.Board(case['fen'])
            for mirrored in (False, True):
                board = root.mirror() if mirrored else root.copy()
                branch = chess.Move.from_uci(case['branch'])
                reply = chess.Move.from_uci(case['mate_reply'])
                if mirrored:
                    branch = chess.Move(chess.square_mirror(branch.from_square), chess.square_mirror(branch.to_square))
                    reply = chess.Move(chess.square_mirror(reply.from_square), chess.square_mirror(reply.to_square))
                with self.subTest(case=case['name'], mirrored=mirrored):
                    probe = board.copy()
                    probe.push(branch)
                    probe.push(reply)
                    self.assertTrue(probe.is_checkmate())
                    moves, scores, depth, _ = self.engine.lookahead(board, case['depth'], case['beam'], time.monotonic() + 30)
                    self.assertEqual(depth, case['depth'])
                    self.assertLessEqual(scores[moves.index(branch)], -self.module.MATE + 100)
                    self.assertEqual(board.move_stack, [])

    def test_checked_position_keeps_every_legal_evasion(self):
        board = chess.Board('4r1k1/8/8/8/8/8/R7/4K3 w - - 0 1')
        self.assertTrue(board.is_check())
        self.assertGreater(board.legal_moves.count(), 4)
        children = self.engine.beam_children(board, 4, time.monotonic() + 30)
        self.assertEqual({c.peek() for c in children}, set(board.legal_moves))
        self.assertEqual(board.move_stack, [])

    def test_terminal_draws_and_mates_survive_narrow_beam(self):
        board = chess.Board('k7/8/1QK5/8/8/8/8/8 w - - 0 1')
        expected = set()
        stalemates = set()
        for move in board.legal_moves:
            child = board.copy()
            child.push(move)
            if self.module.gpu_terminal(child) is not None:
                expected.add(move)
            if child.is_stalemate():
                stalemates.add(move)
        self.assertTrue(stalemates)
        self.assertGreater(len(expected), 1)
        children = self.engine.beam_children(board, 1, time.monotonic() + 30)
        self.assertTrue(expected <= {c.peek() for c in children})

    def test_quiet_position_still_obeys_beam_limit(self):
        board = chess.Board()
        children = self.engine.beam_children(board, 4, time.monotonic() + 30)
        self.assertEqual(len(children), 4)
        self.assertEqual(len({c.peek() for c in children}), 4)

    def test_expired_budget_keeps_completed_iteration(self):
        board = chess.Board()
        expected = self.engine.lookahead(board, 1, 4, float('inf'))
        with patch.object(self.module.time, 'monotonic', return_value=2):
            actual = self.engine.lookahead(board, 3, 4, 1)
        self.assertEqual(actual[0], expected[0])
        np.testing.assert_array_equal(actual[1], expected[1])
        self.assertEqual(actual[2:], expected[2:])
        self.assertEqual(board.move_stack, [])

    def test_deadline_during_child_generation_does_not_mutate_board(self):
        board = chess.Board()
        with patch.object(self.module.time, 'monotonic', side_effect=[0, 0, 2]):
            children = self.engine.beam_children(board, 4, 1)
        self.assertIsNone(children)
        self.assertEqual(board.fen(), chess.STARTING_FEN)
        self.assertEqual(board.move_stack, [])


if __name__ == '__main__':
    unittest.main()
