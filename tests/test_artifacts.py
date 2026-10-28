"""Standalone export and deployment integration for modular evaluators."""
from dataclasses import asdict
import hashlib
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
import contextlib
import io
import types
from unittest.mock import patch

import chess
from chess_ai.artifacts import publish_model
from chess_ai.evaluation import ClassicalEvaluator
from chess_ai.matches import atomic_json, implementation_id, fingerprint, evidence
from chess_ai.neural import SparseEvaluator
from chess_ai.search import SearchOptions
from tools.sync_engine import bundle_source


class ArtifactTests(unittest.TestCase):
    def test_deployment_cells_serve_classical_and_sparse(self):
        from test_notebooks import DEPLOY, source
        from fastapi.testclient import TestClient
        with tempfile.TemporaryDirectory() as directory, contextlib.redirect_stdout(io.StringIO()):
            root = Path(directory)
            google = types.ModuleType('google')
            colab = types.ModuleType('google.colab')
            colab.drive = types.SimpleNamespace(mount=lambda path: None)
            google.colab = colab
            for kind in ('classical', 'sparse'):
                model = root / ('model.json' if kind == 'classical' else 'model.npz')
                (ClassicalEvaluator() if kind == 'classical' else SparseEvaluator.initial(hidden=8)).save(model)
                models = root / kind
                publish_model(model, models, bundle_source(), initial=True)
                scope = {}
                code = source(DEPLOY, 'phase3-load').replace('/content/drive/MyDrive/chess_30m/models', str(models))
                with patch.dict(sys.modules, {'google': google, 'google.colab': colab}), patch('subprocess.check_call'):
                    exec(compile(code, 'phase3-load', 'exec'), scope)
                    exec(compile(source(DEPLOY, 'phase3-app'), 'phase3-app', 'exec'), scope)
                    self.addCleanup(scope['API_EXECUTOR'].shutdown, wait=True, cancel_futures=True)
                with TestClient(scope['api']) as client:
                    self.assertEqual(client.get('/health').status_code, 200)
                    response = client.post('/move', json={'fen': chess.STARTING_FEN, 'history': [], 'difficulty': 'easy'})
                    self.assertEqual(response.status_code, 200, response.text)
                    self.assertIn(chess.Move.from_uci(response.json()['move']), chess.Board().legal_moves)

    def test_standalone_classical_and_sparse_exports(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for kind in ('classical', 'sparse'):
                model = root / ('model.json' if kind == 'classical' else 'model.npz')
                evaluator = ClassicalEvaluator() if kind == 'classical' else SparseEvaluator.initial(hidden=8)
                evaluator.save(model)
                models = root / kind
                folder = publish_model(model, models, bundle_source(), initial=True)
                manifest = json.loads((models / 'latest_champion.json').read_text())
                for name, digest in manifest['sha256'].items():
                    self.assertEqual(hashlib.sha256((folder / name).read_bytes()).hexdigest(), digest)
                code = """
import importlib.util, sys, chess
from pathlib import Path
p=Path(sys.argv[1]); spec=importlib.util.spec_from_file_location('saved',p/'cristopher_engine.py')
m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
engine=m.CristopherEngine(p/'cristopher_genome.json')
answer=engine.get_move(chess.STARTING_FEN, [], 'easy')
assert chess.Move.from_uci(answer['move']) in chess.Board().legal_moves
assert not any(n=='chess_ai' for n in sys.modules)
print('standalone OK')
"""
                result = subprocess.run([sys.executable, '-c', code, str(folder)], cwd=directory,
                                        capture_output=True, text=True, timeout=30, check=True)
                self.assertIn('standalone OK', result.stdout)
                before = (models / 'latest_champion.json').read_bytes()
                with self.assertRaises(ValueError):
                    publish_model(model, models, bundle_source(), initial=True)
                with self.assertRaises(ValueError):
                    publish_model(model, models, bundle_source())
                self.assertEqual((models / 'latest_champion.json').read_bytes(), before)

    def test_publication_requires_matching_current_validation(self):
        # Synthetic evidence tests publication mechanics, not actual chess strength.
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); model = root / 'model.json'
            ClassicalEvaluator().save(model)
            digest = hashlib.sha256(model.read_bytes()).hexdigest()
            publish_model(model, root / 'models', bundle_source(), initial=True)
            candidate = {'model_sha256': digest, 'search': asdict(SearchOptions()), 'evaluator': 'neural'}
            match = {'candidate': candidate, 'incumbent': candidate, 'implementation_sha256': implementation_id()}
            match['signature'] = fingerprint(match)
            report = evidence([{'pair': i, 'candidate_white': white, 'score': 1} for i in range(32) for white in (True, False)], 32)
            report['signature'] = match['signature']
            atomic_json(root / 'validation/match.json', match)
            atomic_json(root / 'validation/report.json', report)
            folder = publish_model(model, root / 'models', bundle_source(), validation=root / 'validation')
            self.assertTrue(json.loads((folder / 'cristopher_genome.json').read_text())['champion_verified'])
            with self.assertRaisesRegex(ValueError, 'settings'):
                publish_model(model, root / 'models', bundle_source(), validation=root / 'validation', hybrid=True)
            ClassicalEvaluator({'tempo': [11, 11]}).save(model)
            with self.assertRaisesRegex(ValueError, 'different candidate'):
                publish_model(model, root / 'models', bundle_source(), validation=root / 'validation')


if __name__ == '__main__':
    unittest.main()
