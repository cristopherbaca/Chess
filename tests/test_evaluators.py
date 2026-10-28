import json
from pathlib import Path
import random
import tempfile
import unittest
import chess
import numpy as np
from chess_ai.board import Position
from chess_ai.evaluation import ClassicalEvaluator, DEFAULT_WEIGHTS, HybridEvaluator
from chess_ai.neural import SparseEvaluator, train_labels


class EvaluationTests(unittest.TestCase):
    def test_mirror_symmetry_and_material(self):
        evaluator = ClassicalEvaluator()
        board = chess.Board()
        rng = random.Random(11)
        for _ in range(30):
            self.assertAlmostEqual(evaluator(board), evaluator(board.mirror()))
            moves = list(board.legal_moves)
            if not moves:
                break
            board.push(rng.choice(moves))
        self.assertGreater(evaluator(chess.Board('7k/8/8/8/8/8/Q7/7K w - - 0 1')), 700)

    def test_pawn_terms_have_sensible_direction(self):
        weights = {k: (0, 0) for k in DEFAULT_WEIGHTS}
        weights.update(isolated=(-10, -10), doubled=(-20, -20), passed=(20, 20))
        evaluator = ClassicalEvaluator(weights)
        connected = chess.Board('7k/8/8/8/3PP3/8/8/7K w - - 0 1')
        doubled = chess.Board('7k/8/8/3P4/3P4/8/8/7K w - - 0 1')
        self.assertGreater(evaluator(connected), evaluator(doubled))
        advanced = chess.Board('7k/3P4/8/8/8/8/8/7K w - - 0 1')
        low = chess.Board('7k/8/8/8/8/8/3P4/7K w - - 0 1')
        self.assertGreater(evaluator(advanced), evaluator(low))

    def test_tapered_king_activity(self):
        weights = {k: (0, 0) for k in DEFAULT_WEIGHTS}
        weights['king_center'] = (-8, 14)
        evaluator = ClassicalEvaluator(weights)
        center = chess.Board('7k/8/8/8/3K4/8/P7/8 w - - 0 1')
        corner = chess.Board('7k/8/8/8/8/8/P7/K7 w - - 0 1')
        self.assertGreater(evaluator(center), evaluator(corner))

    def test_serialization_and_hybrid(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'eval.json'
            evaluator = ClassicalEvaluator()
            evaluator.save(path)
            loaded = ClassicalEvaluator.load(path)
            self.assertEqual(loaded(chess.Board()), evaluator(chess.Board()))
        blend = HybridEvaluator(lambda b: 100, lambda b: 300, .25)
        self.assertEqual(blend(chess.Board()), 150)


class SparseNetworkTests(unittest.TestCase):
    def test_incremental_matches_full_refresh_and_unmake(self):
        neural = SparseEvaluator.initial(hidden=16)
        reference = SparseEvaluator(neural.w1.copy(), neural.b1.copy(), neural.output.copy())
        for fen in [chess.STARTING_FEN, 'r3k2r/8/8/8/8/8/8/R3K2R w KQkq - 0 1',
                    '4k3/8/8/3pP3/8/8/8/4K3 w - d6 0 1',
                    '1r5k/P7/8/8/8/8/8/7K w - - 0 1']:
            position = Position(chess.Board(fen), neural)
            original = neural(position.board)
            for move in list(position.board.legal_moves):
                position.push(move)
                reference.reset(position.board)
                self.assertAlmostEqual(neural(position.board), reference(position.board), places=5)
                position.pop()
                self.assertAlmostEqual(neural(position.board), original, places=5)
        self.assertGreater(neural.incremental_updates, 0)

    def test_quantization_and_model_roundtrip(self):
        neural = SparseEvaluator.initial(hidden=16)
        quantized = neural.quantized()
        board = chess.Board()
        self.assertLess(abs(neural(board) - quantized(board)), .01)
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'network.npz'
            quantized.save(path)
            loaded = SparseEvaluator.load(path)
            self.assertEqual(loaded(board), quantized(board))

    def test_labeled_training_checkpoint_and_resume(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            rows = [{'fen': chess.STARTING_FEN, 'game_id': str(i), 'cp_white': 0, 'result_white': .5} for i in range(5)]
            data = root / 'labels.jsonl'
            data.write_text('\n'.join(json.dumps(r) for r in rows))
            result = train_labels(data, root / 'model', epochs=1, hidden=8, batch_size=2)
            self.assertEqual(result['training_positions'], 4)
            self.assertEqual(result['validation_positions'], 1)
            resumed = train_labels(data, root / 'model', epochs=2, hidden=8, batch_size=2)
            self.assertEqual(len(resumed['history']), 2)
            self.assertTrue((root / 'model/best_validation.npz').exists())
            self.assertTrue(np.isfinite(SparseEvaluator.load(root / 'model/best_validation.npz')(chess.Board())))

    def test_explicit_test_labels_never_affect_training(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            boards = [chess.Board() for _ in range(3)]
            boards[1].push_uci('e2e4'); boards[2].push_uci('d2d4')
            rows = [{'fen': b.fen(), 'game_id': str(i), 'cp_white': 20, 'split': split}
                    for i, (b, split) in enumerate(zip(boards, ['train', 'validation', 'test']))]
            data = root / 'data.jsonl'
            data.write_text('\n'.join(json.dumps(r) for r in rows))
            result = train_labels(data, root / 'first', epochs=2, hidden=8)
            self.assertEqual(result['test_positions_excluded'], 1)
            rows[-1]['cp_white'] = -10000
            data.write_text('\n'.join(json.dumps(r) for r in rows))
            train_labels(data, root / 'second', epochs=2, hidden=8)
            a = SparseEvaluator.load(root / 'first/best_validation.npz')
            b = SparseEvaluator.load(root / 'second/best_validation.npz')
            np.testing.assert_array_equal(a.w1, b.w1)
            np.testing.assert_array_equal(a.output, b.output)
            rows[-1]['fen'] = boards[0].mirror().fen()
            data.write_text('\n'.join(json.dumps(r) for r in rows))
            with self.assertRaisesRegex(ValueError, 'crosses dataset splits'):
                train_labels(data, root / 'third', hidden=8)


if __name__ == '__main__':
    unittest.main()
