"""Notebook persistence and Run-all boundaries, using tiny CPU test weights.
Run: python -m unittest discover -s tests -p 'test_notebooks.py' -v
Requires the API test dependencies plus torch and nbformat.
"""
import ast
import contextlib
import copy
import importlib.util
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

import chess
import nbformat
import torch

ROOT = Path(__file__).resolve().parents[1]
TRAIN = json.loads((ROOT / 'vendor/train.ipynb').read_text())
DEPLOY = json.loads((ROOT / 'vendor/deploy.ipynb').read_text())

def source(book, identifier):
    return ''.join(next(c['source'] for c in book['cells'] if c['id'] == identifier))

def embedded(name):
    return next(ast.literal_eval(node.value) for node in ast.parse(source(TRAIN, 'train-engine')).body
                if isinstance(node, ast.Assign) and isinstance(node.targets[0], ast.Name)
                and node.targets[0].id == name)

def fixture(folder):
    scope = {}
    exec(compile(source(TRAIN, 'train-config'), '<train-config>', 'exec'), scope)
    cfg = scope['CFG']
    cfg.update(root=str(folder), run_name='persistence_test', workers=1, gpu_hidden=[8, 4],
               gpu_population=2, gpu_pairs_per_opponent=1, gpu_max_plies=12,
               gpu_parallel_games=16, gpu_batch_rows=128, gpu_require_cuda=False,
               gpu_native_prepare=False, gpu_native_path='', gpu_anchor_enabled=False,
               gpu_generations=1, gpu_checkpoint_seconds=.001, max_hours=.01)
    path = folder / 'models' / 'test_gpu_worker.py'
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text('\n\n'.join(embedded(name) for name in
                               ('CORE_SOURCE', 'EVAL_SOURCE', 'REPORT_SOURCE', 'GPU_SOURCE')))
    spec = importlib.util.spec_from_file_location('test_saved_champion_worker', path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return cfg, module

class NotebookTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.output = io.StringIO()
        self.capture = contextlib.redirect_stdout(self.output)
        self.capture.__enter__()
        self.addCleanup(self.capture.__exit__, None, None, None)
        self.cfg, self.module = fixture(self.root)
        self.state = self.module.gpu_load(self.cfg, create=True)

    def pointer(self):
        return self.root / 'models/latest_champion.json'

    def bundle(self):
        return self.root / 'models' / json.loads(self.pointer().read_text())['folder']

    def test_notebooks_are_compact_hidden_and_separate(self):
        for book in (TRAIN, DEPLOY):
            nbformat.validate(nbformat.from_dict(book))
            for cell in book['cells']:
                if cell['cell_type'] == 'code':
                    self.assertTrue(cell['metadata']['jupyter']['source_hidden'])
                    self.assertEqual(cell['metadata']['cellView'], 'form')
                    # Executed user notebooks legitimately contain outputs;
                    # nbformat validation above checks their schema.
                    ast.parse(''.join(cell['source']))
        self.assertLessEqual(len(TRAIN['cells']), 10)
        self.assertLessEqual(len(DEPLOY['cells']), 8)
        self.assertNotIn('FastAPI(', '\n'.join(''.join(c['source']) for c in TRAIN['cells']))
        self.assertNotIn('gpu_evolve(', '\n'.join(''.join(c['source']) for c in DEPLOY['cells']))
        self.assertEqual(DEPLOY['cells'][-1]['id'], 'phase3-tunnel')
        self.assertNotIn('while True:', source(DEPLOY, 'phase3-tunnel'))
        self.assertIn('def shutdown_api():', source(DEPLOY, 'phase3-server'))
        self.assertNotIn('\nshutdown_api()', source(DEPLOY, 'phase3-server'))

    def test_initial_champion_and_changed_champion_load_without_training(self):
        first = self.bundle()
        self.assertEqual(json.loads((first / 'cristopher_genome.json').read_text())['champion_generation'], -1)
        self.assertEqual(json.loads((first / 'cristopher_genome.json').read_text())['search_version'],
                         'shared-alpha-beta-v2')
        self.state['champion'] = self.state['champion'] + .01
        self.state['champion_generation'] = 0
        self.module.gpu_save(self.cfg, self.state)
        self.assertNotEqual(self.bundle(), first)
        self.assertTrue(first.is_dir())
        spec = importlib.util.spec_from_file_location('deployed_test_champion', self.bundle() / 'cristopher_engine.py')
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        engine = module.CristopherEngine(self.bundle() / 'cristopher_genome.json')
        result = engine.get_move(chess.STARTING_FEN, [], 'easy')
        self.assertIn(chess.Move.from_uci(result['move']), chess.Board().legal_moves)
        self.assertEqual(engine.bank.layers[0][0].shape[0], 1)
        self.assertIsNone(engine.bank.scale)
        result = engine.get_move(chess.STARTING_FEN, [], 'medium')
        self.assertEqual(result['info']['search_version'], 'shared-alpha-beta-v2')
        self.assertIn(chess.Move.from_uci(result['move']), chess.Board().legal_moves)
        # The standalone published module carries the fix, not just the notebook.
        board = chess.Board('5r1k/6pp/7N/8/8/8/8/KQ6 b - - 0 1')
        moves, scores, depth, _ = engine.lookahead(board, 2, 4, module.time.monotonic() + 10)
        self.assertEqual(depth, 2)
        self.assertLessEqual(scores[moves.index(chess.Move.from_uci('f8g8'))], -module.MATE + 100)

    def test_classic_generation_winner_is_published(self):
        path = self.root / 'models/classic_worker.py'
        path.write_text('\n\n'.join(embedded(name) for name in (
            'CORE_SOURCE', 'EVAL_SOURCE', 'SEARCH_SOURCE', 'CPP_WRAPPER_SOURCE',
            'GA_SOURCE', 'REPORT_SOURCE', 'STAGE2_SOURCE')))
        spec = importlib.util.spec_from_file_location('classic_persistence_fixture', path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        cfg = {**self.cfg, 'training_mode': 'classic', 'run_name': 'classic_test'}
        state = {'generation': 1, 'champion': {'genome': module.genome_default().tolist(),
                 'generation': 0}, 'hall': []}
        module.save_state(cfg, state)
        metadata = json.loads((self.bundle() / 'cristopher_genome.json').read_text())
        self.assertEqual(metadata['version'], module.VERSION)
        self.assertEqual(metadata['generation'], 0)
        self.assertTrue((self.root / 'checkpoints/classic_test/best_champion.json').is_file())
        engine = module.CristopherEngine(self.bundle() / 'cristopher_genome.json')
        result = engine.get_move(chess.STARTING_FEN, [], 'easy')
        self.assertIn(chess.Move.from_uci(result['move']), chess.Board().legal_moves)

    def test_unchanged_champion_does_not_duplicate_bundles(self):
        before = self.pointer().read_bytes()
        for _ in range(5):
            self.module.gpu_save(self.cfg, self.state)
        self.assertEqual(self.pointer().read_bytes(), before)
        self.assertEqual(len(list((self.root / 'models/deployments').iterdir())), 1)
        self.assertEqual(len(list((self.root / 'checkpoints/persistence_test').glob('gpu_*.pt'))), 3)

    def test_failed_publication_keeps_previous_champion_and_recovers_from_checkpoint(self):
        previous = self.pointer().read_bytes()
        self.state['champion'] = self.state['champion'] + .02
        self.state['champion_generation'] = 1
        replace = self.module.os.replace
        def fail_pointer(src, dst):
            if Path(dst) == self.pointer():
                raise OSError('simulated disconnect before publishing pointer')
            return replace(src, dst)
        with patch.object(self.module.os, 'replace', side_effect=fail_pointer):
            with self.assertRaises(OSError):
                self.module.gpu_save(self.cfg, self.state)
        self.assertEqual(self.pointer().read_bytes(), previous)
        loaded = self.module.gpu_load(self.cfg)
        self.assertEqual(loaded['champion_generation'], 1)
        self.module.gpu_export(self.cfg, loaded, Path(self.module.__file__).read_text())
        self.assertEqual(json.loads(self.pointer().read_text())['champion_generation'], 1)

    def test_interrupted_checkpoint_and_corrupt_latest_recover_previous(self):
        self.module.gpu_save(self.cfg, self.state)
        previous = self.pointer().read_bytes()
        def broken_save(obj, handle):
            handle.write(b'interrupted checkpoint')
            raise OSError('simulated runtime failure')
        with patch('torch.save', side_effect=broken_save):
            with self.assertRaises(OSError):
                self.module.gpu_save(self.cfg, self.state)
        recovered = self.module.gpu_load(self.cfg)
        self.assertTrue(torch.equal(recovered['champion'], self.state['champion']))
        self.assertEqual(self.pointer().read_bytes(), previous)
        paths = sorted((self.root / 'checkpoints/persistence_test').glob('gpu_*.pt'))
        paths[-1].write_bytes(b'corrupt latest completed checkpoint')
        recovered = self.module.gpu_load(self.cfg)
        self.assertTrue(torch.equal(recovered['champion'], self.state['champion']))

    def test_real_cpu_evolution_saves_and_resumes(self):
        result = self.module.gpu_evolve(self.cfg)
        self.assertEqual(result['generation'], 1)
        self.assertGreater(result['positions'], 0)
        self.assertTrue(self.pointer().is_file())
        restored = self.module.gpu_load(self.cfg)
        self.assertEqual(restored['generation'], 1)
        self.assertTrue(torch.equal(result['champion'], restored['champion']))
        again = self.module.gpu_evolve(self.cfg)
        self.assertEqual(again['generation'], 1)
        self.assertTrue(self.bundle().is_dir())

    def test_recoverable_exception_saves_in_progress_state(self):
        with patch.object(self.module, 'gpu_prepare_chunk', side_effect=RuntimeError('simulated training failure')):
            with self.assertRaisesRegex(RuntimeError, 'simulated training failure'):
                self.module.gpu_evolve(self.cfg)
        restored = self.module.gpu_load(self.cfg)
        self.assertTrue(restored['jobs'])
        self.assertTrue(self.bundle().is_dir())

    def test_bad_snapshot_republished_before_reuse(self):
        previous = self.bundle()
        (previous / 'weights.pt').write_bytes(b'incomplete')
        self.module.gpu_save(self.cfg, self.state)
        self.assertNotEqual(self.bundle(), previous)
        self.assertGreater((self.bundle() / 'weights.pt').stat().st_size, 100)

    def test_parameter_mode_export_is_standalone_and_legal(self):
        from chess_ai.training import GeneticConfig, load_state
        cfg = {**self.cfg, 'training_mode': 'parameter_evolution', 'run_name': 'parameters_test'}
        state, _ = load_state(self.root / 'parameters', GeneticConfig())
        folder = self.module._CHESS_ENGINE_PACKAGE.notebook_bridge.parameter_export(self.module, cfg, state)
        metadata = json.loads((folder / 'cristopher_genome.json').read_text())
        self.assertEqual(metadata['version'], 'chess-parameters-1')
        spec = importlib.util.spec_from_file_location('parameter_export_test', folder / 'cristopher_engine.py')
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        result = module.CristopherEngine(folder / 'cristopher_genome.json').get_move(chess.STARTING_FEN, [], 'medium')
        self.assertIn(chess.Move.from_uci(result['move']), chess.Board().legal_moves)

    def test_new_search_options_do_not_change_old_gpu_checkpoint_identity(self):
        cfg = copy.deepcopy(self.cfg)
        cfg.pop('gpu_search_backend', None)
        cfg.pop('gpu_search_options', None)
        for key in ('gpu_validation_pairs', 'gpu_validation_seconds', 'gpu_validation_nodes'):
            cfg.pop(key, None)
        self.assertEqual(self.module.gpu_signature(cfg), self.module.gpu_signature(self.cfg))

    def test_saved_champion_comparison_checkpoints_without_publication(self):
        pointer = self.pointer().read_bytes()
        bridge = self.module._CHESS_ENGINE_PACKAGE.notebook_bridge
        report = bridge.validate_saved_dense_search(self.module, self.cfg, self.bundle(), pairs=1, seconds=.001, hours=.000001)
        self.assertFalse(report['accepted'])
        self.assertEqual(self.pointer().read_bytes(), pointer)
        self.assertTrue(list((self.root / 'logs').rglob('runtime.json')))

if __name__ == '__main__':
    unittest.main()
