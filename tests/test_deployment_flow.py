"""Local Run-all integration: real Uvicorn/HTTP; Colab, installs, tunnel provider mocked.
Run separately (binds localhost:8000): python tests/test_deployment_flow.py
"""
import contextlib
import hashlib
import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import types
import unittest
from unittest.mock import patch

import requests
from test_notebooks import DEPLOY, fixture, source

class DeploymentRunAllTest(unittest.TestCase):
    def test_run_all_returns_url_keeps_server_alive_and_can_rerun(self):
        self.run_flow()

    def test_full_pipeline_run_all_loads_selected_engine_and_returns_url(self):
        self.run_flow(full_pipeline=True)

    def run_flow(self, full_pipeline=False):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            cfg, worker = fixture(root)
            if full_pipeline:
                cfg.update(training_mode='full_pipeline', run_name='full_test', pipeline_source_run='')
                pipeline = worker._CHESS_ENGINE_PACKAGE.full_pipeline
                state = pipeline.load(worker, cfg, create=True)
                pipeline.publish(worker, cfg, state)
            else:
                worker.gpu_load(cfg, create=True)  # A complete baseline snapshot without a training run.
            mounted = []
            google = types.ModuleType('google')
            colab = types.ModuleType('google.colab')
            colab.drive = types.SimpleNamespace(mount=lambda path: mounted.append(path))
            google.colab = colab
            ipython = types.ModuleType('IPython')
            display_module = types.ModuleType('IPython.display')
            display_module.HTML = lambda text: text
            display_module.display = lambda value: None
            modules = {'google': google, 'google.colab': colab,
                       'IPython': ipython, 'IPython.display': display_module}
            real_popen = subprocess.Popen
            real_get, real_post = requests.get, requests.post
            children = []
            scope = {}
            output = io.StringIO()
            fake_url = 'https://local-notebook-test.trycloudflare.com'
            def process(args, **kwargs):
                self.assertEqual(args[1:], ['tunnel', '--url', 'http://localhost:8000'])
                child = real_popen([sys.executable, '-u', '-c',
                                   f"import time; print('{fake_url}', flush=True); time.sleep(120)"], **kwargs)
                children.append(child)
                return child
            def download(url, destination):
                Path(destination).write_text('local provider fixture')
            def local(url):
                return url.replace(fake_url, 'http://127.0.0.1:8000')
            try:
                with patch.dict(sys.modules, modules), patch('subprocess.check_call'), \
                     patch('urllib.request.urlretrieve', side_effect=download), \
                     patch('subprocess.Popen', side_effect=process), \
                     patch('requests.get', side_effect=lambda url, **kw: real_get(local(url), **kw)), \
                     patch('requests.post', side_effect=lambda url, **kw: real_post(local(url), **kw)), \
                     contextlib.redirect_stdout(output):
                    for run in range(2):
                        for cell in DEPLOY['cells']:
                            if cell['cell_type'] != 'code':
                                continue
                            code = ''.join(cell['source'])
                            code = code.replace('/content/drive/MyDrive/chess_30m/models', str(root / 'models'))
                            code = code.replace("Path('/content/cloudflared')", f'Path({str(root / "cloudflared")!r})')
                            # Pin the mocked binary's digest; production pin remains unchanged.
                            if cell['id'] == 'phase3-tunnel':
                                import re
                                code = re.sub(r"CLOUDFLARED_SHA256 = '[0-9a-f]+'",
                                    "CLOUDFLARED_SHA256 = '" + hashlib.sha256(b'local provider fixture').hexdigest() + "'", code)
                            exec(compile(code, cell['id'], 'exec'), scope)
                        self.assertEqual(scope['PUBLIC_URL'], fake_url)
                        self.assertTrue(scope['API_SERVER_THREAD'].is_alive())
                        self.assertIsNone(children[-1].poll())
                        self.assertEqual(real_get('http://127.0.0.1:8000/health', timeout=4).status_code, 200)
                        self.assertTrue(output.getvalue().rstrip().endswith(fake_url))
                        if run == 1:
                            self.assertIsNotNone(children[0].poll())
                    scope['shutdown_api']()
                    self.assertFalse(scope['API_SERVER_THREAD'].is_alive())
                    self.assertIsNotNone(children[-1].poll())
            finally:
                if 'stop_tunnel' in scope:
                    scope['stop_tunnel']()
                if 'stop_server' in scope:
                    scope['stop_server']()
                for child in children:
                    if child.poll() is None:
                        child.terminate(); child.wait(timeout=5)
            self.assertTrue(mounted)
            print('PASS: all deployment cells, local self-tests, simulated public checks, URL output, rerun and shutdown')

if __name__ == '__main__':
    unittest.main()
