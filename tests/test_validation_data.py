"""Offline invariants for cached independent reference data."""
import json
from pathlib import Path
import unittest
import chess
from tools.benchmark_engine import outcome

ROOT = Path(__file__).resolve().parents[1]


class ValidationDataTests(unittest.TestCase):
    def test_published_solutions_are_legal_and_score_the_expected_move(self):
        cases = json.loads((ROOT / 'tests/validation/puzzles.json').read_text())['positions']
        self.assertGreaterEqual(len(cases), 100)
        self.assertEqual(len({c['id'] for c in cases}), len(cases))
        for case in cases:
            board = chess.Board(case['fen'])
            self.assertTrue(board.is_valid())
            self.assertTrue(outcome(case, chess.Move.from_uci(case['solution'][0])))
            for move in case['solution']:
                board.push_uci(move)

    def test_tablebase_expectations_preserve_best_successor_wdl(self):
        data = json.loads((ROOT / 'tests/validation/endgames.json').read_text())
        rank = {'loss': 0, 'blessed-loss': 1, 'draw': 2, 'cursed-win': 3, 'win': 4}
        for case in data['positions']:
            board = chess.Board(case['fen'])
            moves = data['raw_responses'][case['id']]['moves']
            expected = {m['uci'] for m in moves if rank[m['category']] == min(rank[x['category']] for x in moves)}
            self.assertEqual(set(case['moves']), expected)
            self.assertTrue(all(chess.Move.from_uci(m) in board.legal_moves for m in expected))


if __name__ == '__main__':
    unittest.main()
