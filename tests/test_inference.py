"""Dense inference never applies ES population budgets to a single champion."""
import contextlib
import io
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import numpy as np
import torch
from chess_ai import inference
from test_notebooks import fixture


class InferenceTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        capture = contextlib.redirect_stdout(io.StringIO())
        capture.__enter__()
        self.addCleanup(capture.__exit__, None, None, None)
        cfg, self.host = fixture(Path(self.tmp.name))
        vector, _ = self.host.gpu_initial_vector(cfg)
        vector += .03
        self.cfg = {**cfg, 'gpu_inference_only': True, 'gpu_population': 0,
                    'gpu_target_vram_gb': 0, 'gpu_headroom_gb': 1000000}
        self.state = {'mean': vector, 'champion': vector, 'initial': vector,
                      'prior': self.host.gpu_prior(self.host.genome_default()).tolist(),
                      'seeds': [], 'sigma': 0., 'hall': []}
        self.original = self.host.GpuPopulation._chess_original_population
        self.requests = [(0, 0, np.random.default_rng(9).normal(size=(5, 784)).astype(np.float32))]

    def test_cpu_override_preserves_predictions_and_ignores_training_budgets(self):
        before = self.state['mean'].clone()
        expected = self.original(self.cfg, self.state, device='cpu').evaluate(self.requests)[0]
        adapted = inference.population_class(self.original, self.host.gpu_layout, device='cpu')
        with patch('torch.cuda.is_available', return_value=True), \
             patch('torch.cuda.mem_get_info', side_effect=AssertionError('Training admission must not run')), \
             patch('torch.cuda.memory_allocated', side_effect=AssertionError('Allocator total is unrelated')):
            bank = adapted(self.cfg, self.state)
            actual = bank.evaluate(self.requests)[0]
        np.testing.assert_allclose(actual, expected, rtol=1e-6, atol=1e-5)
        self.assertTrue(torch.equal(before, self.state['mean']))
        self.assertEqual(bank.device.type, 'cpu')
        self.assertEqual(bank.layers[0][0].shape[0], 1)
        self.assertEqual(bank.noise, [])
        self.assertIsNone(bank.scale)
        self.assertIsNone(bank.budget)

    def test_cuda_load_oom_falls_back_with_same_cpu_weights(self):
        real_place = inference._place
        calls = []
        def place(bank, device):
            calls.append(device)
            if device == 'cuda':
                bank.layers = [(torch.ones(1), torch.ones(1))]
                raise torch.cuda.OutOfMemoryError('simulated full GPU')
            real_place(bank, device)
        adapted = inference.population_class(self.original, self.host.gpu_layout)
        with patch('torch.cuda.is_available', return_value=True), patch.object(inference, '_place', side_effect=place), \
             patch('torch.cuda.empty_cache') as cleanup:
            bank = adapted(self.cfg, self.state)
        self.assertEqual(calls, ['cuda', 'cpu'])
        cleanup.assert_called_once()
        expected = self.original(self.cfg, self.state, device='cpu').evaluate(self.requests)[0]
        np.testing.assert_allclose(bank.evaluate(self.requests)[0], expected, rtol=1e-6)

    def test_cuda_inference_oom_retries_on_cpu(self):
        class SimulatedCudaOOM(self.original):
            def evaluate(self, requests):
                if self.device.type == 'cuda':
                    raise torch.cuda.OutOfMemoryError('simulated inference OOM')
                return super().evaluate(requests)
        adapted = inference.population_class(SimulatedCudaOOM, self.host.gpu_layout)
        with patch('torch.cuda.is_available', return_value=False):
            bank = adapted(self.cfg, self.state)
        bank.device = torch.device('cuda')
        with patch('torch.cuda.empty_cache'):
            answer = bank.evaluate(self.requests)
        self.assertEqual(bank.device.type, 'cpu')
        self.assertEqual(len(answer[0]), 5)
        self.assertTrue(np.isfinite(answer[0]).all())

    def test_forced_cuda_and_unrelated_failures_are_not_silently_hidden(self):
        adapted = inference.population_class(self.original, self.host.gpu_layout, device='cuda')
        with patch('torch.cuda.is_available', return_value=False), self.assertRaisesRegex(RuntimeError, 'CUDA is unavailable'):
            adapted(self.cfg, self.state)
        with patch('torch.cuda.is_available', return_value=True), \
             patch.object(inference, '_place', side_effect=torch.cuda.OutOfMemoryError('forced GPU full')), \
             self.assertRaises(torch.cuda.OutOfMemoryError):
            adapted(self.cfg, self.state)
        class Broken(self.original):
            def evaluate(self, requests):
                raise ValueError('invalid model computation')
        bank = inference.population_class(Broken, self.host.gpu_layout, device='cpu')(self.cfg, self.state)
        with self.assertRaisesRegex(ValueError, 'invalid model computation'):
            bank.evaluate(self.requests)

    def test_training_constructor_is_preserved_and_adapter_is_idempotent(self):
        adapted = inference.population_class(self.original, self.host.gpu_layout, device='cpu')
        adapted_again = inference.population_class(adapted, self.host.gpu_layout, device='auto')
        self.assertIs(adapted_again._chess_original_population, self.original)
        with patch.object(self.original, '__init__', side_effect=RuntimeError('original training guard')) as init, \
             self.assertRaisesRegex(RuntimeError, 'original training guard'):
            adapted({**self.cfg, 'gpu_inference_only': False}, self.state, device='cpu')
        self.assertEqual(init.call_args.kwargs['device'], 'cpu')


if __name__ == '__main__':
    unittest.main()
