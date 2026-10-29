"""Single-model inference for dense exports, including older notebook bundles.

Training population budgets describe an entire ES population and allocator-wide
memory; neither is a suitable admission check for one inference model. Load only
its layer tensors and let allocation failure drive an explicit CPU fallback.
"""


def _place(bank, device):
    """One packed layer allocation; no perturbations, optimizer or GPU mean copy."""
    torch = bank.torch
    bank.device = torch.device(device)
    bank.dtype = torch.float16 if bank.device.type == 'cuda' else torch.float32
    bank.layers = []
    bank.prior = None
    with torch.inference_mode():
        packed = bank.mean.to(device=bank.device, dtype=bank.dtype).reshape(1, -1)
        for offset, inputs, outputs in bank.layout:
            bank.layers.append((packed[:, offset:offset + inputs*outputs].reshape(1, inputs, outputs),
                                packed[:, offset + inputs*outputs:offset + inputs*outputs + outputs].reshape(1, 1, outputs)))
        bank.prior = torch.as_tensor(bank._inference_prior, device=bank.device, dtype=bank.dtype)


def _release_cuda_layers(bank):
    bank.layers = []
    bank.prior = None
    # Call outside the OOM except block so its traceback no longer holds tensors.
    bank.torch.cuda.empty_cache()


def initialize(bank, cfg, state, layout_function, device=None):
    import torch
    bank.torch, bank.cfg = torch, dict(cfg)
    requested = device or cfg.get('gpu_inference_device', 'auto')
    if requested not in ('auto', 'cpu', 'cuda'):
        raise ValueError('Inference device must be auto, cpu, or cuda.')
    bank.inference_device_policy = requested
    bank.layout, bank.count = layout_function(cfg)
    # Keep the original CPU tensor for fallback; never modify saved weights.
    bank.mean = state['mean'].detach().cpu()
    if bank.mean.ndim != 1 or bank.mean.numel() != bank.count:
        raise ValueError('Dense model weights do not match the exported architecture.')
    bank._inference_prior = state['prior']
    bank.scale, bank.budget = None, None
    bank.seeds, bank.noise, bank.hall_ids = [], [], []
    bank.mean_id = bank.champion_id = bank.default_id = 0
    bank.pairs, bank.sigma = 0, 0.
    bank.batch_rows = cfg['gpu_batch_rows']
    bank.positions, bank.forward_seconds = 0, 0.
    target = 'cpu'
    if requested != 'cpu':
        if torch.cuda.is_available():
            target = 'cuda'
        elif requested == 'cuda':
            raise RuntimeError('CUDA is unavailable. Select API_DEVICE="cpu" or "auto", or use a GPU runtime.')
    fallback = False
    try:
        _place(bank, target)
    except torch.cuda.OutOfMemoryError:
        if target != 'cuda' or requested != 'auto':
            raise
        fallback = True
    if fallback:
        _release_cuda_layers(bank)
        _place(bank, 'cpu')
        print('GPU memory is insufficient for inference; using CPU with the same saved weights.', flush=True)
    print(f'Inference device: {bank.device} | 1 network | {bank.count:,} parameters', flush=True)


def population_class(original, layout_function, device=None):
    """Replace only inference initialization; preserve the export's math/search.

    Deployment can install this adapter in a verified old module in memory. No
    artifact rewrite, checksum bypass, checkpoint migration or retraining needed.
    """
    original = getattr(original, '_chess_original_population', original)
    default_device = device

    class InferenceAwarePopulation(original):
        _chess_original_population = original

        def __init__(self, cfg, state, device=None):
            if cfg.get('gpu_inference_only'):
                initialize(self, cfg, state, layout_function, device=device or default_device)
            else:
                super().__init__(cfg, state, device=device)

        def evaluate(self, requests):
            try:
                return super().evaluate(requests)
            except self.torch.cuda.OutOfMemoryError:
                if (not self.cfg.get('gpu_inference_only') or self.device.type != 'cuda'
                        or self.inference_device_policy != 'auto'):
                    raise
            # The original evaluator already tried smaller batches. An HTTP
            # deadline/error is not an OOM and must propagate without fallback.
            _release_cuda_layers(self)
            _place(self, 'cpu')
            print('GPU inference ran out of memory; continuing on CPU with the same saved weights.', flush=True)
            return super().evaluate(requests)

    return InferenceAwarePopulation
