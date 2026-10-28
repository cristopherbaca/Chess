"""Execute training preparation, generation, and export cells with tiny local settings."""
import contextlib
import io
import importlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
from test_notebooks import TRAIN, source


class TrainingFlowTests(unittest.TestCase):
    def test_gpu_and_parameter_cells_run_sequentially_and_resume(self):
        for mode in ('gpu_neuroevolution', 'parameter_evolution'):
            with self.subTest(mode=mode), tempfile.TemporaryDirectory() as directory, contextlib.redirect_stdout(io.StringIO()):
                scope = {'importlib': importlib, 'subprocess': subprocess}
                exec(compile(source(TRAIN, 'train-config'), 'train-config', 'exec'), scope)
                cfg = scope['CFG']
                cfg.update(root=directory, training_mode=mode, run_name='flow_test', workers=1,
                           QUICK_TEST=True, cpp_backend=False, generations=1, gpu_generations=1,
                           gpu_hidden=[8, 4], gpu_population=2, gpu_require_cuda=False,
                           gpu_native_prepare=False, gpu_anchor_enabled=False, gpu_max_plies=8,
                           gpu_pairs_per_opponent=1, gpu_parallel_games=16, gpu_batch_rows=128,
                           max_plies=8, max_hours=.01, gpu_validation_pairs=1,
                           gpu_validation_nodes=1, gpu_validation_seconds=.001)
                for settings in cfg['difficulty'].values():
                    settings.update(seconds=.02, nodes=64, depth=2)
                root = Path(directory)
                for name in ('models', 'logs', 'checkpoints', 'pgn'):
                    (root / name).mkdir()
                scope.update(ROOT=root, MODELS=root / 'models')
                old_path = sys.path[:]
                try:
                    with patch.dict(sys.modules):
                        for name in ('cristopher_evo_worker', 'cristopher_gpu_worker'):
                            sys.modules.pop(name, None)
                        for identifier in ('train-engine', 'train-run', 'train-export'):
                            exec(compile(source(TRAIN, identifier), identifier, 'exec'), scope)
                        self.assertEqual(scope['STATE']['generation'], 1)
                        before = (root / 'models/latest_champion.json').read_bytes()
                        exec(compile(source(TRAIN, 'train-run'), 'train-run', 'exec'), scope)
                        self.assertEqual(scope['STATE']['generation'], 1)
                        self.assertEqual((root / 'models/latest_champion.json').read_bytes(), before)
                finally:
                    sys.path[:] = old_path


if __name__ == '__main__':
    unittest.main()
