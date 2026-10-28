"""Load engine definitions without executing notebook setup, training or deployment."""
import ast
import hashlib
import json
from pathlib import Path
import sys
import types

ROOT = Path(__file__).resolve().parents[1]


def engine_sources(notebook=None):
    book = json.loads(Path(notebook or ROOT / 'vendor/train.ipynb').read_text())
    code = ''.join(next(c['source'] for c in book['cells'] if c['id'] == 'train-engine'))
    return {
        node.targets[0].id: ast.literal_eval(node.value)
        for node in ast.parse(code).body
        if isinstance(node, ast.Assign) and isinstance(node.targets[0], ast.Name)
        and isinstance(node.value, ast.Constant) and isinstance(node.value.value, str)
        and node.targets[0].id.endswith('_SOURCE')
    }


def load_engine(notebook=None):
    sources = engine_sources(notebook)
    code = '\n\n'.join(sources[name] for name in
                       ('CORE_SOURCE', 'EVAL_SOURCE', 'SEARCH_SOURCE', 'GPU_SOURCE'))
    digest = hashlib.sha256(code.encode()).hexdigest()
    name = 'chess_notebook_' + digest[:16]
    module = types.ModuleType(name)
    sys.modules[name] = module
    exec(compile(code, '<notebook-engine>', 'exec'), module.__dict__)
    module.source_sha256 = digest
    return module


def prior_engine(module):
    """Deterministic search fixture; no learned weights or CUDA performance claim."""
    import numpy as np
    engine = module.GpuCristopherEngine.__new__(module.GpuCristopherEngine)
    engine.prior_cpu = module.gpu_prior(module.genome_default())

    def values(boards):
        result = []
        for board in boards:
            terminal = module.gpu_terminal(board)
            result.append(terminal if terminal is not None else
                          float(module.gpu_features(board) @ engine.prior_cpu + 10))
        return np.asarray(result, dtype=np.float32)

    engine.values = values
    return engine


def perft(board, depth):
    if depth == 0:
        return 1
    if depth == 1:
        return board.legal_moves.count()
    nodes = 0
    for move in list(board.legal_moves):
        board.push(move)
        try:
            nodes += perft(board, depth - 1)
        finally:
            board.pop()
    return nodes
