"""Adversarial public API inputs and isolation of the GitHub Pages artifact."""
import asyncio
import concurrent.futures
import contextlib
import io
import json
from pathlib import Path
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

import chess
from fastapi.testclient import TestClient
from chess_ai.api_security import PublicPolicy, SecurityBoundary, allowed_origins
from test_api import environment
from test_notebooks import TRAIN, source, fixture
from tools.build_site import build, public_api_url, ROOT


class PublicSecurityTests(unittest.TestCase):
    def setUp(self):
        with contextlib.redirect_stdout(io.StringIO()):
            self.scope = environment()
        self.addCleanup(self.scope['API_EXECUTOR'].shutdown, wait=True, cancel_futures=True)
        self.policy = self.scope['API_POLICY']
        self.client = TestClient(self.scope['api'])

    def post(self, **kwargs):
        return self.client.post('/move', json={'fen': chess.STARTING_FEN, 'difficulty': 'easy'}, **kwargs)

    def test_private_diagnostics_and_disabled_documentation(self):
        for auth in ('', 'Bearer wrong', 'Bearer test-only-admin-token-extra'):
            reply = self.client.get('/stats', headers={'Authorization': auth})
            self.assertEqual(reply.status_code, 401)
            self.assertNotIn('last_requests', reply.text)
            self.assertEqual(reply.headers['cache-control'], 'no-store')
        reply = self.client.get('/stats', headers={'Authorization': 'Bearer test-only-admin-token'})
        self.assertEqual(reply.status_code, 200)
        self.assertIn('security', reply.json())
        for path in ('/docs', '/redoc', '/openapi.json', '/cristopher_engine.py', '/.env'):
            self.assertEqual(self.client.get(path).status_code, 404)

    def test_origins_and_error_headers(self):
        with patch.object(self.scope['API_ENGINE'], 'get_move') as engine:
            for origin in ('https://evil.example', 'null', 'https://chess.example.evil.test'):
                reply = self.post(headers={'Origin': origin})
                self.assertEqual(reply.status_code, 403)
                self.assertNotIn('access-control-allow-origin', reply.headers)
            engine.assert_not_called()
        reply = self.client.post('/move', json={'fen': 'bad'}, headers={'Origin': 'https://chess.example'})
        self.assertEqual(reply.status_code, 400)
        self.assertEqual(reply.headers['access-control-allow-origin'], 'https://chess.example')
        self.assertEqual(reply.headers['x-content-type-options'], 'nosniff')
        self.assertEqual(reply.headers['x-frame-options'], 'DENY')
        preflight = self.client.options('/move', headers={'Origin': 'https://chess.example',
            'Access-Control-Request-Method': 'DELETE'})
        self.assertEqual(preflight.status_code, 400)

    def test_body_limits_content_type_and_bounded_validation(self):
        with patch.object(self.scope['API_ENGINE'], 'get_move') as engine:
            reply = self.client.post('/move', content=b'x'*16385, headers={'Content-Type': 'application/json'})
            self.assertEqual(reply.status_code, 413)
            for headers in ({'Content-Type': 'text/plain'}, {'Content-Type': 'application/json', 'Content-Encoding': 'gzip'}):
                self.assertEqual(self.client.post('/move', content='{}', headers=headers).status_code, 415)
            for extra in ({'history': ['e2e4']*1025}, {'history': ['x'*1000]}, {'run': 'os.system(...)'}):
                reply = self.client.post('/move', json={'fen': chess.STARTING_FEN, **extra})
                self.assertEqual(reply.status_code, 422)
                self.assertLess(len(reply.content), 250)
            engine.assert_not_called()

    def test_rate_limit_refill_and_no_forwarded_ip_bypass(self):
        self.policy.rates = ((100, 100), (1, 1))
        now = [100.]
        self.policy.clock = lambda: now[0]
        with patch.object(self.scope['API_ENGINE'], 'get_move', return_value={'move': 'e2e4', 'info': {}}):
            self.assertEqual(self.post().status_code, 200)
            for address in ('198.51.100.1', '203.0.113.2'):
                reply = self.post(headers={'X-Forwarded-For': address, 'CF-Connecting-IP': address})
                self.assertEqual(reply.status_code, 429)
                self.assertEqual(reply.headers['retry-after'], '1')
            now[0] += 1
            self.assertEqual(self.post().status_code, 200)

    def test_global_budget_bounded_client_map_and_cloudflare_trust(self):
        p = PublicPolicy(('https://chess.example',), trust_cloudflare=True, global_move_burst=1, max_clients=2)
        self.assertEqual(p.admit('a', True), 0)
        self.assertGreater(p.admit('b', True), 0)
        self.assertGreater(p.admit('c', False), 0)
        self.assertEqual(len(p.clients), 2)
        headers = {b'cf-connecting-ip': b'203.0.113.8', b'x-forwarded-for': b'203.0.113.9'}
        self.assertEqual(p.client_key({'client': ('127.0.0.1', 8000)}, headers), '203.0.113.8')
        self.assertEqual(p.client_key({'client': ('198.51.100.3', 8000)}, headers), '198.51.100.3')
        p.trust_cloudflare = False
        self.assertEqual(p.client_key({'client': ('127.0.0.1', 8000)}, headers), '127.0.0.1')
        self.assertEqual(p.client_key({'client': ('2001:db8::1', 80)}, {}),
                         p.client_key({'client': ('2001:db8::2', 80)}, {}))

    def test_native_timeout_keeps_search_admission_occupied(self):
        self.policy.search_slots = threading.BoundedSemaphore(1)
        entered = threading.Event()
        def delayed(*args):
            entered.set()
            time.sleep(.25)
            return {'move': 'e2e4', 'info': {}}
        with patch.dict(self.scope['API_TIME_CAPS'], easy=.04), patch.object(self.scope['API_ENGINE'], 'get_move', side_effect=delayed):
            with concurrent.futures.ThreadPoolExecutor() as pool:
                request = pool.submit(self.post)
                self.assertTrue(entered.wait(1))
                self.assertEqual(request.result().status_code, 504)
                busy = self.post()
                self.assertEqual(busy.status_code, 503)
                self.assertEqual(busy.headers['retry-after'], '2')
                self.assertEqual(self.client.get('/health').status_code, 200)
                time.sleep(.3)
        self.assertTrue(self.policy.search_slots.acquire(blocking=False))
        self.policy.search_slots.release()

    def test_streamed_oversize_and_slow_body_rejected_before_application(self):
        async def run(slow=False):
            calls, messages = [], []
            async def downstream(*args):
                calls.append(True)
            policy = PublicPolicy(('https://chess.example',), body_bytes=10, body_seconds=.01)
            boundary = SecurityBoundary(downstream, policy)
            parts = iter([b'123456', b'123456'])
            async def receive():
                if slow:
                    await asyncio.sleep(.1)
                return {'type': 'http.request', 'body': next(parts), 'more_body': True}
            async def send(message):
                messages.append(message)
            await boundary({'type': 'http', 'method': 'POST', 'path': '/move',
                'headers': [(b'content-type', b'application/json')], 'client': ('127.0.0.1', 1234)}, receive, send)
            self.assertFalse(calls)
            self.assertEqual(messages[0]['status'], 408 if slow else 413)
        asyncio.run(run())
        asyncio.run(run(slow=True))

    def test_origin_configuration_rejects_wildcards_paths_and_insecure_remote(self):
        self.assertEqual(allowed_origins('https://cristopherbaca.github.io/'), ('https://cristopherbaca.github.io',))
        for value in ('*', 'https://*.github.io', 'https://cristopherbaca.github.io/Chess', 'null',
                      'http://public.example', 'https://user:password@example.com'):
            with self.assertRaises(ValueError):
                allowed_origins(value)


class FreshTrainingAndSiteTests(unittest.TestCase):
    def test_fresh_defaults_and_no_implicit_classical_import(self):
        with tempfile.TemporaryDirectory() as directory, contextlib.redirect_stdout(io.StringIO()):
            scope = {}
            exec(source(TRAIN, 'train-config'), scope)
            cfg = scope['CFG']
            self.assertEqual(cfg['pipeline_source_run'], '')
            self.assertEqual(cfg['gpu_seed_classic_run'], '')
            self.assertEqual(cfg['run_name'], 'fresh_30m_v1')
            self.assertEqual(cfg['root'], '/content/drive/MyDrive/chess_30m')
            self.assertEqual(cfg['gpu_hidden'], [6400, 3904])
            cfg, host = fixture(Path(directory))
            # A stray earlier champion at the blank-run path must not be read.
            prior = Path(directory) / 'checkpoints/best_champion.json'
            prior.parent.mkdir(parents=True)
            prior.write_text('not a valid champion')
            state = host.gpu_load(cfg, create=True)
            self.assertEqual(state['generation'], 0)
            self.assertEqual(state['prior_source'], 'handcrafted material/PST prior')

    def test_site_artifact_excludes_training_secrets_and_restricts_connections(self):
        import shutil
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for folder in ('js', 'css', 'assets', 'vendor'):
                shutil.copytree(ROOT / folder, root / folder)
            for name in ('index.html', 'LICENSES.md'):
                shutil.copyfile(ROOT / name, root / name)
            (root / '.env').write_text('secret')
            output = build(root, 'https://api.example.com')
            files = {str(p.relative_to(output)) for p in output.rglob('*') if p.is_file()}
            self.assertIn('vendor/chess.js', files)
            self.assertIn('assets/pieces/LICENSE', files)
            self.assertFalse(any(p.endswith(('.ipynb', '.py', '.pt', '.npz')) for p in files))
            self.assertNotIn('.env', files)
            html = (output / 'index.html').read_text()
            self.assertIn("connect-src 'self' https://api.example.com;", html)
            self.assertNotIn("'unsafe-inline'", html)
            self.assertIn('https://api.example.com', (output / 'js/public-config.js').read_text())
            self.assertEqual(build(root, 'https://api.example.com'), output)

    def test_public_api_url_cannot_inject_script_or_policy(self):
        for url in ('http://public.example', 'javascript:alert(1)', 'https://user:pass@example.com',
                    'https://example.com;evil', 'https://example.com/\";alert(1)', 'https://example.com/?token=secret'):
            with self.assertRaises(ValueError):
                public_api_url(url)


if __name__ == '__main__':
    unittest.main()
