from dataclasses import asdict
import json
from pathlib import Path
import random
import tempfile
import threading
import time
import unittest
import sys
import subprocess
import chess
from chess_ai.evaluation import DEFAULT_WEIGHTS
from chess_ai.matches import MatchConfig, evidence, openings, run_match, UciOpponent
from chess_ai.runtime import Engine
from chess_ai.training import GeneticConfig, evolve, next_generation, weights, vector, load_state
from chess_ai.uci import UCI


def rows(score, pairs=32):
    return [{'pair': i, 'candidate_white': color, 'score': score, 'truncated': False, 'error': None}
            for i in range(pairs) for color in (True, False)]


class EvidenceTests(unittest.TestCase):
    def test_opening_book_hash_prevents_stale_resume(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'openings.json'
            path.write_text(json.dumps({'openings': [{'moves': ['e2e4', 'e7e5']}, {'moves': ['d2d4', 'd7d5']}]}))
            cfg = MatchConfig(pairs=2, opening_file=str(path), nodes=1, max_plies=3)
            self.assertEqual(openings(cfg), openings(cfg))
            run_match(Engine, Engine, cfg, Path(folder) / 'match', 'a', 'b')
            path.write_text(json.dumps({'openings': [{'moves': ['e2e4', 'c7c5']}, {'moves': ['d2d4', 'd7d5']}]}))
            with self.assertRaisesRegex(ValueError, 'configuration changed'):
                run_match(Engine, Engine, cfg, Path(folder) / 'match', 'a', 'b')

    def test_draws_small_samples_and_missing_pairs_never_promote(self):
        self.assertFalse(evidence(rows(.5), 32)['accepted'])
        self.assertFalse(evidence(rows(1, 2), 2)['accepted'])
        self.assertFalse(evidence(rows(1)[:-1], 32)['accepted'])
        bad = rows(1)
        bad[0]['error'] = 'engine crash'
        self.assertFalse(evidence(bad, 32)['accepted'])

    def test_strong_complete_result_promotes_with_uncertainty(self):
        report = evidence(rows(1), 32)
        self.assertTrue(report['accepted'])
        self.assertIsNone(report['elo_difference'])
        self.assertIsNone(report['elo_interval_95'][1])
        self.assertLess(evidence(rows(1), 32, attempt=2)['test_alpha'], report['test_alpha'])

    def test_paired_openings_are_reproducible_and_legal(self):
        cfg = MatchConfig(pairs=8)
        self.assertEqual(openings(cfg), openings(cfg))
        self.assertGreater(len({tuple(x) for x in openings(cfg)}), 1)
        for moves in openings(cfg):
            board = chess.Board()
            for uci in moves:
                move = chess.Move.from_uci(uci)
                self.assertIn(move, board.legal_moves)
                board.push(move)

    def test_match_resume_and_config_guard(self):
        with tempfile.TemporaryDirectory() as folder:
            cfg = MatchConfig(pairs=1, max_plies=8, nodes=1, move_seconds=.01)
            report = run_match(Engine, Engine, cfg, folder, 'a', 'b', deadline=0)
            self.assertEqual(report['finished_games'], 0)
            report = run_match(Engine, Engine, cfg, folder, 'a', 'b')
            self.assertEqual(report['finished_games'], 2)
            self.assertFalse(report['accepted'])
            self.assertEqual(len(list(Path(folder).glob('*.pgn'))), 2)
            again = run_match(Engine, Engine, cfg, folder, 'a', 'b')
            self.assertEqual(report, again)
            with self.assertRaises(ValueError):
                run_match(Engine, Engine, cfg, folder, 'changed', 'b')


class GeneticsTests(unittest.TestCase):
    def test_reproducible_crossover_mutation_and_elitism(self):
        population = [weights([x + i for x in vector(DEFAULT_WEIGHTS)]) for i in range(4)]
        cfg = GeneticConfig(population=4, elite=1)
        first = next_generation(population, [0, .1, .2, .3], cfg, random.Random(42))
        second = next_generation(population, [0, .1, .2, .3], cfg, random.Random(42))
        self.assertEqual(first, second)
        self.assertEqual(first[0], population[3])
        self.assertNotEqual(first[1:], population[1:])

    def test_real_generation_checkpoint_and_incumbent_preservation(self):
        cfg = GeneticConfig(population=4, elite=1, generations=1, training_pairs=1,
                            validation_pairs=1, nodes=1, move_seconds=.001, max_plies=8)
        with tempfile.TemporaryDirectory() as folder:
            state = evolve(cfg, folder, hours=.02)
            self.assertEqual(state['generation'], 1)
            self.assertEqual(state['champion_generation'], -1)
            self.assertFalse(state['verified'])
            self.assertEqual(state['champion'], weights(vector(DEFAULT_WEIGHTS)))
            restored, _ = load_state(folder, cfg)
            self.assertEqual(restored['population'], state['population'])
            self.assertLessEqual(len(list(Path(folder).glob('checkpoint_*.json'))), 3)


class UciTests(unittest.TestCase):
    def test_real_uci_process_can_be_used_as_benchmark_opponent(self):
        # Colab deployment tests patch asyncio globally with nest_asyncio. Test
        # this command-line integration in its actual fresh-process environment.
        code = '''
import chess, sys
from chess_ai.matches import UciOpponent
opponent = UciOpponent([sys.executable, '-m', 'chess_ai'])
try:
    board = chess.Board()
    answer = opponent.choose(board, seconds=.05, nodes=128, depth=2)
    assert answer.move in board.legal_moves
finally:
    opponent.close()
'''
        subprocess.run([sys.executable, '-c', code], check=True, timeout=20, capture_output=True, text=True)

    def test_protocol_ready_position_go_stop_quit(self):
        output = []
        protocol = UCI(Engine(), output.append)
        protocol.command('uci')
        protocol.command('isready')
        protocol.command('position startpos moves e2e4 e7e5')
        expected = protocol.board.fen()
        protocol.command('go infinite')
        protocol.command('stop')
        self.assertIn('uciok', output)
        self.assertIn('readyok', output)
        best = next(x.split()[1] for x in output if x.startswith('bestmove '))
        self.assertIn(chess.Move.from_uci(best), protocol.board.legal_moves)
        self.assertEqual(protocol.board.fen(), expected)
        self.assertFalse(protocol.command('quit'))

    def test_invalid_position_keeps_previous_board(self):
        output = []
        protocol = UCI(Engine(), output.append)
        protocol.command('position startpos moves e2e5')
        self.assertEqual(protocol.board.fen(), chess.STARTING_FEN)
        self.assertTrue(any('info string' in x for x in output))
        protocol.command('setoption name LMR value true')
        self.assertTrue(protocol.engine.searcher.options.lmr)


if __name__ == '__main__':
    unittest.main()
