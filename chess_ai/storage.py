"""Lossless, shared dense tensors and conservative retention for Colab/Drive."""
import hashlib
import json
import os
from pathlib import Path
import re
import shutil

FORMAT = 'dense-checkpoint-blobs-v1'


def tensor_digest(tensor):
    value = tensor.detach().cpu().contiguous()
    header = json.dumps([str(value.dtype), list(value.shape)]).encode()
    return hashlib.sha256(header + value.numpy().tobytes()).hexdigest()


def read_dense_checkpoint(path):
    import torch
    path = Path(path)
    pack = torch.load(path, map_location='cpu', weights_only=True)
    if pack.get('storage_format') != FORMAT:
        return pack  # Original self-contained checkpoints remain readable.
    state = dict(pack['state'])
    cache = {}
    def read(name):
        if not re.fullmatch(r'[0-9a-f]{64}\.pt', name):
            raise ValueError('Invalid checkpoint tensor reference')
        blob = path.parent / 'tensors' / name
        if blob.is_symlink():
            raise ValueError('Checkpoint tensors cannot be symlinks')
        if name not in cache:
            tensor = torch.load(blob, map_location='cpu', weights_only=True)
            if tensor_digest(tensor) != name[:-3]:
                raise ValueError('Damaged checkpoint tensor')
            cache[name] = tensor
        # Preserve independent mean/champion/initial semantics even when identical.
        return cache[name].clone()
    for key in ('mean', 'champion', 'initial'):
        state[key] = read(pack['tensor_blobs'][key])
    state['hall'] = [read(name) for name in pack['tensor_blobs']['hall']]
    return {**pack, 'state': state}


def save_dense_checkpoint(cfg, state, signature):
    import torch
    folder = Path(cfg['root']) / 'checkpoints' / cfg['run_name']
    blobs = folder / 'tensors'
    blobs.mkdir(parents=True, exist_ok=True)
    def write(tensor):
        name = tensor_digest(tensor) + '.pt'
        target = blobs / name
        if not target.exists():
            temporary = target.with_suffix('.tmp')
            with temporary.open('wb') as handle:
                # Clone so a tensor view cannot serialize a larger backing storage.
                torch.save(tensor.detach().cpu().contiguous().clone(), handle)
                handle.flush(); os.fsync(handle.fileno())
            os.replace(temporary, target)
        return name
    references = {key: write(state[key]) for key in ('mean', 'champion', 'initial')}
    references['hall'] = [write(tensor) for tensor in state['hall']]
    small = {key: value for key, value in state.items() if key not in references}
    state['sequence'] += 1
    small['sequence'] = state['sequence']
    target = folder / f"gpu_{state['sequence']:08d}.pt"
    temporary = target.with_suffix('.tmp')
    with temporary.open('wb') as handle:
        torch.save({'storage_format': FORMAT, 'signature': signature, 'CFG': cfg,
                    'state': small, 'tensor_blobs': references}, handle)
        handle.flush(); os.fsync(handle.fileno())
    os.replace(temporary, target)  # Commit only after all referenced blobs exist.
    # Keep recoverable state even if subsequent model publication fails.
    keep = max(3, int(cfg.get('storage_keep_checkpoints', 3)))
    paths = sorted(folder.glob('gpu_*.pt'))
    for old in paths[:-keep]:
        old.unlink()
    used = set()
    try:
        for path in paths[-keep:]:
            saved = torch.load(path, map_location='cpu', weights_only=True)
            if saved.get('storage_format') == FORMAT:
                refs = saved['tensor_blobs']
                used.update(refs[key] for key in ('mean', 'champion', 'initial'))
                used.update(refs['hall'])
    except Exception:
        return target  # An unreadable retained checkpoint makes GC unsafe.
    for blob in blobs.glob('*.pt'):
        if blob.name not in used and re.fullmatch(r'[0-9a-f]{64}\.pt', blob.name) and not blob.is_symlink():
            blob.unlink()
    return target


def pipeline_references(cfg):
    """Protect every model needed by current state and retained rollback states."""
    root = Path(cfg['root']) / 'experiments' / cfg['run_name']
    protected = set()
    for checkpoint in (root / 'state').glob('checkpoint_*.json'):
        state = json.loads(checkpoint.read_text())['state']
        specs = [state.get('champion', {}), state.get('dense_candidate', {}), *state.get('candidates', [])]
        for spec in specs:
            for key in ('dense', 'sparse'):
                if spec.get(key):
                    protected.add(Path(spec[key]).resolve())
    return protected


def prune_pipeline_exports(cfg):
    """Retain three recent exports plus all pointers and rollback references.

    Only completed bundles belonging to this run are eligible. Unknown folders,
    other experiments, symlinks and corrupt state are never removed.
    """
    root = Path(cfg['root'])
    experiment = root / 'experiments' / cfg['run_name']
    try:
        protected = pipeline_references(cfg)
    except (OSError, ValueError, KeyError, TypeError):
        return 0
    removed = 0
    keep = max(3, int(cfg.get('storage_keep_exports', 3)))
    for models, run in ((root/'models', cfg['run_name']), (experiment/'models', 'dense')):
        try:
            pointer = json.loads((models/'latest_champion.json').read_text())
            current = (models/pointer['folder']).resolve()
            if not current.is_relative_to((models/'deployments').resolve()) or not current.is_dir():
                continue
        except (OSError, ValueError, KeyError, TypeError):
            continue
        candidates = []
        for folder in (models/'deployments').glob('*'):
            if not folder.is_dir() or folder.is_symlink():
                continue
            try:
                manifest = json.loads((folder/'manifest.json').read_text())
                if manifest['run_name'] != run or not manifest.get('sha256'):
                    continue
                if not all((folder/name).is_file() for name in manifest['sha256']):
                    continue
                candidates.append(folder)
            except (OSError, ValueError, KeyError, TypeError):
                continue
        recent = set(sorted(candidates, key=lambda p: p.stat().st_mtime, reverse=True)[:keep])
        for folder in candidates:
            if folder in recent or folder.resolve() == current or any(folder.resolve() in p.parents for p in protected):
                continue
            shutil.rmtree(folder)
            removed += 1
    return removed


def usage(root):
    """Actual visible files only; Drive Trash/version storage is not mounted here."""
    root = Path(root)
    groups = {}
    for directory, children, files in os.walk(root, followlinks=False):
        children[:] = [name for name in children if not (Path(directory)/name).is_symlink()]
        for name in files:
            path = Path(directory)/name
            if path.is_symlink():
                continue
            relative = path.relative_to(root)
            group = '/'.join(relative.parts[:3]) if len(relative.parts) > 3 else relative.parts[0]
            try:
                groups[group] = groups.get(group, 0) + path.stat().st_size
            except FileNotFoundError:
                pass
    return {'root': str(root), 'bytes': sum(groups.values()),
            'largest_folders': sorted(groups.items(), key=lambda item: item[1], reverse=True)[:8],
            'note': 'Visible files only. Drive Trash and versions can consume additional quota.'}


def print_usage(root):
    report = usage(root)
    print(f"Training files on Drive: {report['bytes']/2**30:.3f} GiB (excludes Drive Trash/versions)", flush=True)
    for name, size in report['largest_folders'][:5]:
        print(f'  {name}: {size/2**30:.3f} GiB', flush=True)
    return report
