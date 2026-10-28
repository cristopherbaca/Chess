"""Full-workflow integration with real tiny models and local cached labels."""
import contextlib
import copy
import importlib.util
import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
import chess
import numpy as np
import torch
from test_notebooks import fixture, source, TRAIN, DEPLOY
from chess_ai.neural import SparseEvaluator
from chess_ai.runtime import load_engine


class FullPipelineTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.capture = contextlib.redirect_stdout(io.StringIO())
        self.capture.__enter__(); self.addCleanup(self.capture.__exit__, None, None, None)
        self.cfg, self.host = fixture(self.root)
        self.pipeline = self.host._CHESS_ENGINE_PACKAGE.full_pipeline
        self.cfg.update(training_mode='full_pipeline', run_name='pipeline_test', pipeline_source_run='',
                        pipeline_sparse=True, pipeline_sparse_epochs=1, pipeline_validation_pairs=1,
                        pipeline_move_seconds=.001, pipeline_nodes=1, gpu_generations=0, generations=0,
                        max_hours=.02)
        boards = [chess.Board() for _ in range(3)]
        boards[1].push_uci('e2e4'); boards[2].push_uci('d2d4')
        labels = self.root / 'labels.jsonl'
        labels.write_text('\n'.join(json.dumps({'fen': b.fen(), 'game_id': str(i), 'cp_white': 10,
                                 'split': split}) for i, (b, split) in enumerate(zip(boards, ['train', 'validation', 'test']))))
        self.cfg['pipeline_labels'] = str(labels)

    def test_all_stages_run_and_only_incumbent_is_published(self):
        state = self.pipeline.run(self.host, self.cfg)
        self.assertEqual(state['cycle'], 1)
        self.assertEqual(state['stage'], 0)
        self.assertEqual(state['champion']['kind'], 'dense')
        self.assertFalse(state['verified'])  # Tiny samples cannot qualify.
        self.assertEqual(len(state['history']), 12)  # Four evaluator challengers and eight search comparisons.
        self.assertTrue((self.pipeline.workspace(self.cfg) / 'sparse/best_validation.npz').exists())
        self.assertTrue(list((self.pipeline.workspace(self.cfg) / 'reports').glob('cycle_0000_*.json')))
        self.assertEqual(json.loads((self.pipeline.workspace(self.cfg) / 'sparse/test_report.json').read_text())['test_positions'], 1)
        self.assertEqual(self.pipeline.load(self.host, self.cfg)['champion'], state['champion'])
        self.assertLessEqual(len(list((self.pipeline.workspace(self.cfg) / 'state').glob('checkpoint_*.json'))), 3)
        folder = self.pipeline.publish(self.host, self.cfg, state)
        metadata = json.loads((folder / 'cristopher_genome.json').read_text())
        self.assertEqual(metadata['version'], 'chess-full-pipeline-1')
        engine = load_engine(folder / 'cristopher_genome.json')
        answer = engine.get_move(chess.STARTING_FEN, [], 'easy')
        self.assertIn(chess.Move.from_uci(answer['move']), chess.Board().legal_moves)
        # Export must work without any path to the source workspace.
        code = '''
import chess,importlib.util,sys
from pathlib import Path
p=Path(sys.argv[1]);s=importlib.util.spec_from_file_location('standalone',p/'cristopher_engine.py')
m=importlib.util.module_from_spec(s);s.loader.exec_module(m)
e=m.CristopherEngine(p/'cristopher_genome.json')
a=e.get_move(chess.STARTING_FEN, [], 'easy')
assert chess.Move.from_uci(a['move']) in chess.Board().legal_moves
'''
        subprocess.run([sys.executable, '-c', code, str(folder)], cwd=self.root, check=True, capture_output=True, timeout=30)

    def test_import_preserves_original_weights_and_checkpoints(self):
        original_cfg = {**self.cfg, 'run_name': 'old_dense', 'training_mode': 'gpu_neuroevolution'}
        original = self.host.gpu_load(original_cfg, create=True)
        original['champion'] += .125
        original['generation'] = 22
        self.host.gpu_save(original_cfg, original)
        folder = self.root / 'checkpoints/old_dense'
        (folder / 'gpu_99999999.pt').write_bytes(b'interrupted latest checkpoint')
        before = {p.name: p.read_bytes() for p in folder.iterdir()}
        self.cfg['pipeline_source_run'] = 'old_dense'
        state = self.pipeline.load(self.host, self.cfg, create=True)
        self.assertEqual(state['origin']['generation'], 22)
        imported = self.host.gpu_load(self.pipeline.dense_config(self.cfg))
        self.assertTrue(torch.equal(imported['champion'], original['champion']))
        self.assertTrue(torch.equal(imported['mean'], original['mean']))
        self.assertEqual(before, {p.name: p.read_bytes() for p in folder.iterdir()})
        self.assertEqual(imported['jobs'], [])

    def test_missing_source_never_silently_starts_from_scratch(self):
        self.cfg['pipeline_source_run'] = 'missing'
        with self.assertRaisesRegex(FileNotFoundError, 'SOURCE_RUN'):
            self.pipeline.load(self.host, self.cfg, create=True)
        self.assertFalse((self.root / 'models/latest_champion.json').exists())

    def test_widen_import_preserves_predictions_recovery_and_deployment(self):
        original_cfg = {**self.cfg, 'run_name': 'old_dense', 'training_mode': 'gpu_neuroevolution'}
        original = self.host.gpu_load(original_cfg, create=True)
        generator = torch.Generator().manual_seed(19)
        for key in ('mean', 'champion', 'initial'):
            original[key] = torch.randn(original[key].shape, generator=generator) * .1
        original['hall'] = [original['champion'] * .9]
        original['generation'] = 22
        original['champion_verified'] = True
        self.host.gpu_save(original_cfg, original)
        original_snapshot = self.pipeline.dense_snapshot(original_cfg)
        folder = self.root / 'checkpoints/old_dense'
        before = {p.name: p.read_bytes() for p in folder.iterdir()}
        self.cfg.update(gpu_hidden=[13, 9], gpu_population=4, pipeline_source_run='old_dense')
        state = self.pipeline.load(self.host, self.cfg, create=True)
        cfg = self.pipeline.dense_config(self.cfg)
        imported = self.host.gpu_load(cfg)
        self.assertEqual(state['origin']['widened_from'], [8, 4])
        self.assertEqual(state['origin']['widened_to'], [13, 9])
        self.assertEqual(imported['generation'], 22)
        self.assertEqual(len(imported['seeds']), 2)
        self.assertFalse(imported['champion_verified'])
        self.assertEqual(before, {p.name: p.read_bytes() for p in folder.iterdir()})

        def predict(vector, config, x):
            layout, _ = self.host.gpu_layout(config)
            for i, (offset, a, b) in enumerate(layout):
                x = x @ vector[offset:offset+a*b].reshape(a, b) + vector[offset+a*b:offset+a*b+b]
                if i < len(layout)-1:
                    x = torch.relu(x)
            return x

        x = torch.randn((24, 784), generator=generator)
        for old, new in [(original[k], imported[k]) for k in ('mean', 'champion', 'initial')] + list(zip(original['hall'], imported['hall'])):
            torch.testing.assert_close(predict(old, original_cfg, x), predict(new, cfg, x), rtol=1e-5, atol=1e-6)
        # The new units have independent coordinates for subsequent ES mutations.
        perturbed = imported['champion'].clone()
        perturbed[-2] += .1
        self.assertFalse(torch.allclose(predict(perturbed, cfg, x), predict(imported['champion'], cfg, x)))
        exported = self.pipeline.publish(self.host, self.cfg, state)
        engine = load_engine(exported / 'cristopher_genome.json')
        old_engine = self.host.GpuCristopherEngine(original_snapshot)
        for board in (chess.Board(), chess.Board('8/8/8/3k4/8/4P3/4K3/8 w - - 0 1')):
            self.assertAlmostEqual(engine.evaluator(board), float(old_engine.values([board])[0]), delta=.01)
        self.assertEqual(self.pipeline.load(self.host, self.cfg), state)

    def test_widen_rejects_shrinking_and_different_layer_counts(self):
        vector, _ = self.host.gpu_initial_vector(self.cfg)
        for widths in ([7, 4], [8, 3], [8, 4, 2]):
            with self.assertRaisesRegex(ValueError, 'only be widened'):
                self.pipeline.widen_dense_vector(self.host, vector, self.cfg, {**self.cfg, 'gpu_hidden': widths})

    def test_search_based_dense_evolution_uses_real_search_and_resumes(self):
        cfg = {**self.cfg, 'training_mode': 'gpu_neuroevolution', 'run_name': 'search_dense',
               'gpu_generations': 1, 'gpu_train_with_search': True, 'gpu_training_seconds': .01,
               'gpu_training_nodes': 64, 'gpu_training_depth': 2, 'gpu_max_plies': 10,
               'max_hours': .02}
        state = self.host.gpu_evolve(cfg)
        self.assertEqual(state['generation'], 1)
        traces = list((self.root / 'logs/search_dense').rglob('*.search.jsonl'))
        self.assertTrue(traces)
        rows = [json.loads(line) for p in traces for line in p.read_text().splitlines()]
        self.assertTrue(any(r['stats']['nodes'] > 0 for r in rows))
        self.assertTrue(all(chess.Move.from_uci(r['move']) in chess.Board(r['fen']).legal_moves for r in rows))
        self.assertEqual(self.host.gpu_evolve(cfg)['generation'], 1)

    def test_partial_validation_and_corrupt_checkpoint_recovery(self):
        state = self.pipeline.load(self.host, self.cfg, create=True)
        folder = self.pipeline.publish(self.host, self.cfg, state)
        before = (self.root / 'models/latest_champion.json').read_bytes()
        candidate = {'kind': 'classical', 'classical': self.host._CHESS_ENGINE_PACKAGE.evaluation.DEFAULT_WEIGHTS,
                     'options': state['champion']['options']}
        self.assertFalse(self.pipeline.challenge(self.host, self.cfg, state, candidate, 'test', deadline=0))
        self.assertEqual(state['attempts'], 0)
        self.assertEqual(before, (self.root / 'models/latest_champion.json').read_bytes())
        self.pipeline.save(self.cfg, state)
        last = sorted((self.pipeline.workspace(self.cfg) / 'state').glob('checkpoint_*.json'))[-1]
        last.write_text('interrupted')
        self.assertEqual(self.pipeline.load(self.host, self.cfg)['champion'], state['champion'])

    def test_each_export_backend_carries_its_weights_and_search_configuration(self):
        state = self.pipeline.load(self.host, self.cfg, create=True)
        dense = state['champion']['dense']
        sparse = self.root / 'sparse.npz'; SparseEvaluator.initial(hidden=8).save(sparse)
        classical = self.host._CHESS_ENGINE_PACKAGE.evaluation.DEFAULT_WEIGHTS
        for kind in ('classical', 'hybrid', 'sparse', 'sparse_hybrid'):
            spec = {'kind': kind, 'options': {**state['champion']['options'], 'lmr': True}}
            if kind in ('hybrid',): spec['dense'] = dense
            if kind in ('classical', 'hybrid', 'sparse_hybrid'): spec['classical'] = classical
            if kind in ('sparse', 'sparse_hybrid'): spec['sparse'] = str(sparse)
            state['champion'] = spec
            folder = self.pipeline.publish(self.host, self.cfg, state)
            engine = load_engine(folder / 'cristopher_genome.json')
            self.assertTrue(engine.searcher.options.lmr)
            result = engine.choose(chess.Board(), seconds=.02, nodes=64)
            self.assertIn(result.move, chess.Board().legal_moves)


if __name__ == '__main__':
    unittest.main()
