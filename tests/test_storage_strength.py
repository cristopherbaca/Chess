"""Checkpoint write amplification, safe rollback retention and honest Elo reports."""
import contextlib
import io
import json
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch
import torch
from chess_ai import storage, strength
from chess_ai.matches import evidence
from chess_ai.runtime import Engine
from test_notebooks import fixture


class StorageStrengthTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        capture = contextlib.redirect_stdout(io.StringIO())
        capture.__enter__(); self.addCleanup(capture.__exit__, None, None, None)
        self.cfg, self.host = fixture(self.root)

    def test_repeated_progress_saves_write_no_unchanged_weight_blobs(self):
        state = self.host.gpu_load(self.cfg, create=True)
        folder = self.root/'checkpoints'/self.cfg['run_name']
        original = {p.name: (p.stat().st_mtime_ns, p.read_bytes()) for p in (folder/'tensors').glob('*.pt')}
        self.assertEqual(len(original), 1)  # Initial, mean and champion are identical.
        for move in range(12):
            state['positions'] += 1
            self.host.gpu_save(self.cfg, state)
        self.assertEqual(original, {p.name: (p.stat().st_mtime_ns, p.read_bytes()) for p in (folder/'tensors').glob('*.pt')})
        self.assertEqual(len(list(folder.glob('gpu_*.pt'))), 3)
        restored = self.host.gpu_load(self.cfg)
        self.assertEqual(restored['positions'], 12)
        expected_mean = restored['mean'].clone()
        restored['champion'] += 1
        self.assertTrue(torch.equal(restored['mean'], expected_mean))

    def test_old_checkpoints_resume_and_corrupt_blob_falls_back(self):
        state = self.host.gpu_load(self.cfg, create=True)
        folder = self.root/'checkpoints'/self.cfg['run_name']
        legacy = folder/'gpu_00000002.pt'
        state['sequence'] = 2
        torch.save({'signature': self.host.gpu_signature(self.cfg), 'CFG': self.cfg, 'state': state}, legacy)
        self.assertTrue(torch.equal(self.host.gpu_load(self.cfg)['mean'], state['mean']))
        old = state['mean'].clone()
        state['mean'] += .1
        newest = self.host.gpu_save(self.cfg, state)
        pack = torch.load(newest, weights_only=True)
        blob = folder/'tensors'/pack['tensor_blobs']['mean']
        blob.write_bytes(b'corrupt')
        restored = self.host.gpu_load(self.cfg)
        self.assertTrue(torch.equal(restored['mean'], old))

    def test_gc_keeps_all_rollback_weights_and_removes_only_unreferenced_blobs(self):
        state = self.host.gpu_load(self.cfg, create=True)
        folder = self.root/'checkpoints'/self.cfg['run_name']
        for generation in range(6):
            state['generation'] = generation
            state['mean'] = state['mean'] + .01
            self.host.gpu_save(self.cfg, state)
        paths = sorted(folder.glob('gpu_*.pt'))
        self.assertEqual([storage.read_dense_checkpoint(p)['state']['generation'] for p in paths], [3, 4, 5])
        self.assertEqual(len(list((folder/'tensors').glob('*.pt'))), 4)  # Initial/champion + three means.

    def test_failed_new_weight_write_does_not_destroy_recovery_state(self):
        state = self.host.gpu_load(self.cfg, create=True)
        old = state['mean'].clone()
        state['mean'] += .2
        def interrupted(obj, handle):
            handle.write(b'incomplete tensor')
            raise OSError('Drive unavailable')
        with patch('torch.save', side_effect=interrupted), self.assertRaises(OSError):
            self.host.gpu_save(self.cfg, state)
        restored = self.host.gpu_load(self.cfg)
        self.assertTrue(torch.equal(restored['mean'], old))
        self.host.gpu_save(self.cfg, state)
        self.assertTrue(torch.equal(self.host.gpu_load(self.cfg)['mean'], state['mean']))

    def test_export_retention_protects_current_rollback_other_run_and_unknown_files(self):
        cfg = {**self.cfg, 'run_name': 'pipeline'}
        models = self.root/'models'; deployments = models/'deployments'
        deployments.mkdir(parents=True, exist_ok=True)
        for i in range(6):
            folder = deployments/f'model{i}'; folder.mkdir()
            (folder/'cristopher_genome.json').write_text('{}')
            (folder/'manifest.json').write_text(json.dumps({'run_name': 'pipeline', 'sha256': {'cristopher_genome.json': 'hash'}}))
            import os
            os.utime(folder, (100+i, 100+i))
        (models/'latest_champion.json').write_text(json.dumps({'folder':'deployments/model5'}))
        state_dir = self.root/'experiments/pipeline/state'; state_dir.mkdir(parents=True)
        checkpoint = state_dir/'checkpoint_00000001.json'
        checkpoint.write_text(json.dumps({'state':{'champion':{'dense':str(deployments/'model0/cristopher_genome.json')}}}))
        other = deployments/'other'; other.mkdir()
        (other/'manifest.json').write_text(json.dumps({'run_name':'another', 'sha256':{'model':'x'}}))
        unknown = deployments/'unknown'; unknown.mkdir()
        self.assertEqual(storage.prune_pipeline_exports(cfg), 2)
        for name in ('model0','model3','model4','model5','other','unknown'):
            self.assertTrue((deployments/name).is_dir())
        checkpoint.write_text('corrupt state')
        self.assertEqual(storage.prune_pipeline_exports(cfg), 0)

    def test_relative_elo_requires_valid_pairs_and_includes_uncertainty(self):
        self.assertIn('pending', strength.describe(evidence([], 32)))
        rows = [{'pair': i, 'candidate_white': white, 'score': 1 if i < 15 else 0}
                for i in range(20) for white in (True, False)]
        report = evidence(rows, 20)
        self.assertAlmostEqual(report['elo_difference'], 190.8485, places=3)
        message = strength.describe(report)
        self.assertIn('+191', message)
        self.assertIn('95% interval', message)
        self.assertIn('classical baseline', message)
        for row in rows:
            row['truncated'] = True
        self.assertIn('pending', strength.describe(evidence(rows, 20)))

    def test_rating_match_is_resumable_and_never_promotes_a_model(self):
        cfg = {**self.cfg, 'rating_pairs':10, 'rating_move_seconds':.001, 'rating_nodes':1}
        result = strength.measure(cfg, {'model':'test-champion'}, Engine, time.monotonic()-1)
        self.assertEqual(result['pairs'], 0)
        self.assertFalse(result['accepted'])
        latest = self.root/'experiments'/cfg['run_name']/'ratings/latest.json'
        saved = json.loads(latest.read_text())
        self.assertIn('not a FIDE', saved['note'])
        result = strength.measure(cfg, {'model':'test-champion'}, Engine, time.monotonic()-1)
        self.assertEqual(result['pairs'], 0)
        self.assertFalse((self.root/'models/latest_champion.json').exists())


if __name__ == '__main__':
    unittest.main()
