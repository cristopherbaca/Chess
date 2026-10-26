"""Run Phase 3 locally, using the unchanged classic engine with default test weights.

python -m pip install fastapi uvicorn nest_asyncio python-chess numpy httpx requests
python tests/test_api.py
python tests/test_api.py --serve  # local browser integration fixture, port 8000
No Colab, Drive, tunnel, or training run is required; these are not champion weights.
"""
import ast
import concurrent.futures
import json
from pathlib import Path
import sys
import tempfile
import threading
import time
import types
import unittest
from unittest.mock import patch

import chess
from fastapi.testclient import TestClient

NOTEBOOK = Path(__file__).resolve().parents[1] / 'vendor/cristopher.ipynb'
CELLS = json.loads(NOTEBOOK.read_text())['cells']

def cell(name):
    return ''.join(next(c['source'] for c in CELLS if c['id'] == 'phase3-' + name))

def environment():
    engine_module = types.ModuleType('phase3_test_engine')
    sys.modules[engine_module.__name__] = engine_module
    sources = []
    for variable in ('CORE_SOURCE', 'EVAL_SOURCE', 'SEARCH_SOURCE'):
        source = next(''.join(c['source']) for c in CELLS if ''.join(c['source']).startswith(variable + ' ='))
        assignment = ast.parse(source).body[0]
        sources.append(ast.literal_eval(assignment.value))
    exec(compile('\n\n'.join(sources), '<exported-engine>', 'exec'), engine_module.__dict__)
    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / 'cristopher_genome.json'
        path.write_text(json.dumps({'version': engine_module.VERSION,
                                   'genome': engine_module.genome_default().tolist()}))
        engine = engine_module.CristopherEngine(path)
    scope = {'API_ENGINE': engine, 'API_MODULE': engine_module, 'API_VERSION': 'phase3-test-default-weights',
             'API_ENGINE_LOCK': threading.Lock(), 'API_TIME_CAPS': {'easy': 3., 'medium': 10., 'hard': 25.},
             'threading': threading, 'time': time}
    exec(compile(cell('app'), '<phase3-app>', 'exec'), scope)
    return scope

class ApiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.scope = environment()
        cls.client = TestClient(cls.scope['api'])

    def post(self, **kwargs):
        return self.client.post('/move', json={'fen': chess.STARTING_FEN, 'difficulty': 'easy', **kwargs})

    def test_health_and_legal_moves_all_difficulties(self):
        health = self.client.get('/health').json()
        self.assertEqual(health['status'], 'ok')
        self.assertIsInstance(health['uptime_s'], int)
        for difficulty in ('easy', 'medium', 'hard'):
            reply = self.post(difficulty=difficulty)
            self.assertEqual(reply.status_code, 200, reply.text)
            result = reply.json()
            self.assertIn(chess.Move.from_uci(result['move']), chess.Board().legal_moves)
            self.assertTrue({'eval', 'depth', 'nodes', 'time_ms'} <= result['info'].keys())

    def test_errors(self):
        for body, status in [({'fen': 'bad'}, 400), ({'fen': '8/8/8/8/8/8/8/8 w - - 0 1'}, 400),
                             ({'difficulty': 'impossible'}, 422), ({'history': ['nope']}, 422),
                             ({'history': ['e2e4']}, 400), ({'history': ['e2e5']}, 400),
                             ({'fen': '7k/5Q2/6K1/8/8/8/8/8 b - - 0 1'}, 400),
                             ({'fen': '7k/6Q1/6K1/8/8/8/8/8 b - - 0 1'}, 400)]:
            response = self.post(**body)
            self.assertEqual(response.status_code, status, response.text)
            self.assertTrue(response.json()['error'])
        malformed = self.client.post('/move', content='{', headers={'Content-Type': 'application/json'})
        self.assertEqual(malformed.status_code, 422)
        self.assertTrue(malformed.json()['error'])

    def test_history_and_repetition(self):
        board = chess.Board()
        board.push_uci('e2e4')
        response = self.post(fen=board.fen(), history=['e2e4'])
        self.assertEqual(response.status_code, 200, response.text)
        self.assertIn(chess.Move.from_uci(response.json()['move']), board.legal_moves)
        board = chess.Board()
        history = ['g1f3', 'g8f6', 'f3g1', 'f6g8'] * 2
        for move in history:
            board.push_uci(move)
        self.assertEqual(self.post(fen=board.fen(), history=history).status_code, 400)

    def test_illegal_fallback_and_eval_perspective(self):
        engine = self.scope['API_ENGINE']
        with patch.object(engine, 'get_move', return_value={'move': 'e2e5'}):
            response = self.post()
        self.assertEqual(response.status_code, 200, response.text)
        result = response.json()
        self.assertTrue(result['info']['fallback'])
        self.assertEqual(result['info']['depth'], 1)
        expected = self.scope['depth_one_fallback'](chess.Board())
        self.assertEqual(result['move'], expected['move'])
        board = chess.Board(); board.push_uci('e2e4')
        with patch.object(engine, 'get_move', return_value={'move': 'e7e5', 'info': {'eval': 35}}):
            self.assertEqual(self.post(fen=board.fen()).json()['info']['eval'], -.35)
        with patch.object(engine, 'get_move', side_effect=AssertionError('illegal export reply')):
            self.assertTrue(self.post().json()['info']['fallback'])

    def test_cors_on_success_and_errors(self):
        headers = {'Origin': 'https://chess.example', 'Access-Control-Request-Method': 'POST',
                   'Access-Control-Request-Headers': 'content-type,ngrok-skip-browser-warning'}
        reply = self.client.options('/move', headers=headers)
        self.assertEqual(reply.status_code, 200)
        self.assertIn('ngrok-skip-browser-warning', reply.headers['access-control-allow-headers'])
        reply = self.client.post('/move', json={'fen': 'bad'}, headers={'Origin': 'https://chess.example'})
        self.assertEqual(reply.headers['access-control-allow-origin'], '*')

    def test_deadline_releases_lock_and_preserves_budget(self):
        engine = self.scope['API_ENGINE']
        seconds = engine.settings['easy']['seconds']
        def slow(*args):
            while True:
                sum(range(100))
        with patch.dict(self.scope['API_TIME_CAPS'], easy=.04), patch.object(engine, 'get_move', side_effect=slow):
            started = time.monotonic()
            self.assertEqual(self.post().status_code, 504)
            self.assertLess(time.monotonic() - started, .5)
        time.sleep(.05)
        self.assertFalse(self.scope['API_ENGINE_LOCK'].locked())
        self.assertEqual(engine.settings['easy']['seconds'], seconds)
        self.assertEqual(self.post().status_code, 200)

    def test_native_timeout_retains_lock_and_health_responds(self):
        engine = self.scope['API_ENGINE']
        entered = threading.Event()
        def slow_native(*args):
            entered.set(); time.sleep(.25)
            return {'move': 'e2e4', 'info': {}}
        with patch.dict(self.scope['API_TIME_CAPS'], easy=.05), patch.object(engine, 'get_move', side_effect=slow_native):
            with concurrent.futures.ThreadPoolExecutor() as pool:
                future = pool.submit(self.post)
                self.assertTrue(entered.wait(1))
                self.assertEqual(self.client.get('/health').status_code, 200)
                self.assertEqual(future.result().status_code, 504)
                self.assertTrue(self.scope['API_ENGINE_LOCK'].locked())
                self.assertEqual(self.post().status_code, 504)
                time.sleep(.3)
        self.assertFalse(self.scope['API_ENGINE_LOCK'].locked())

    def test_concurrent_calls_are_serialized(self):
        engine = self.scope['API_ENGINE']
        active = 0
        peak = 0
        def observe(*args):
            nonlocal active, peak
            active += 1; peak = max(peak, active)
            time.sleep(.02)
            active -= 1
            return {'move': 'e2e4', 'info': {}}
        with patch.object(engine, 'get_move', side_effect=observe):
            with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
                replies = list(pool.map(lambda _: self.post(), range(4)))
        self.assertEqual(peak, 1)
        self.assertTrue(all(r.status_code == 200 for r in replies))

    def test_ring_buffer_and_counters(self):
        for _ in range(51):
            self.post(fen='invalid')
        stats = self.client.get('/stats').json()
        self.assertEqual(len(stats['last_requests']), 50)
        self.assertGreaterEqual(stats['counters']['errors'], 51)
        self.assertTrue({'fen', 'difficulty', 'move', 'time_ms', 'at', 'status'} <= stats['last_requests'][-1].keys())

if __name__ == '__main__':
    if '--serve' in sys.argv:
        scope = environment()
        # Execute the actual notebook background-server and self-test cell.
        exec(compile(cell('server'), '<phase3-server>', 'exec'), scope)
        print('Local integration fixture running (default classic weights).', flush=True)
        try:
            while True: time.sleep(1)
        except KeyboardInterrupt:
            scope['stop_server']()
    else:
        unittest.main()
