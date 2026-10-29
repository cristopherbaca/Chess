"""One resumable Colab workflow coordinating the PHASES engine components.

Training branches are private experiments. Only the incumbent or a challenger
with accepted independent evidence is exported to the application's pointer.
"""
from dataclasses import asdict
import copy
import hashlib
import json
import os
from pathlib import Path
import shutil
import time
import tracemalloc
import uuid
import chess
import numpy as np
from .evaluation import ClassicalEvaluator, CallableEvaluator, HybridEvaluator
from .neural import SparseEvaluator, train_labels
from .runtime import Engine
from .search import SearchOptions
from .matches import atomic_json, fingerprint, run_match, MatchConfig, implementation_id
from .training import evolve, GeneticConfig, load_state as load_parameters
from .datasets import prepare_labels
from .validation_cases import CASES
from .storage import read_dense_checkpoint, prune_pipeline_exports, print_usage
from .strength import measure as measure_strength

VERSION = 'chess-full-pipeline-1'
STAGES = ('dense', 'parameters', 'sparse', 'candidates', 'search', 'diagnostics')


def workspace(cfg):
    return Path(cfg['root']) / 'experiments' / cfg['run_name']


def dense_config(cfg):
    return {**cfg, 'root': str(workspace(cfg)), 'run_name': 'dense', 'training_mode': 'gpu_neuroevolution',
            'gpu_train_with_search': True, 'gpu_training_seconds': cfg.get('pipeline_move_seconds', .25),
            'gpu_training_nodes': cfg.get('pipeline_nodes', 10000),
            'gpu_validation_seconds': cfg.get('pipeline_move_seconds', .25),
            'gpu_validation_nodes': cfg.get('pipeline_nodes', 10000), 'gpu_max_plies': 1024,
            'workers': 1, 'gpu_native_prepare': False, 'gpu_native_path': ''}


def signature(cfg):
    return fingerprint({'version': VERSION, 'source_run': cfg.get('pipeline_source_run', ''),
                        'hidden': cfg['gpu_hidden'], 'population': cfg['gpu_population'], 'seed': cfg['seed'],
                        **{k: v for k, v in cfg.items() if k.startswith('pipeline_')}})


def save(cfg, state):
    state['sequence'] = state.get('sequence', 0) + 1
    folder = workspace(cfg) / 'state'
    atomic_json(folder / f"checkpoint_{state['sequence']:08d}.json", {'signature': signature(cfg), 'state': state})
    for old in sorted(folder.glob('checkpoint_*.json'))[:-3]:
        old.unlink()


def dense_snapshot(cfg):
    root = Path(cfg['root']) / 'models'
    pointer = json.loads((root / 'latest_champion.json').read_text())
    return root / pointer['folder'] / 'cristopher_genome.json'


def widen_dense_vector(host, vector, source_cfg, target_cfg):
    """Duplicate ReLU units and divide outgoing weights to preserve predictions.

    Evolution independently perturbs the new units after import. This only
    supports widening existing hidden layers, never shrinking or adding layers.
    """
    import torch
    old_hidden, new_hidden = source_cfg['gpu_hidden'], target_cfg['gpu_hidden']
    if len(old_hidden) != len(new_hidden) or any(b < a for a, b in zip(old_hidden, new_hidden)):
        raise ValueError('Source architecture can only be widened; choose matching or larger gpu_hidden widths')
    old_layout, old_count = host.gpu_layout(source_cfg)
    new_layout, new_count = host.gpu_layout(target_cfg)
    if vector.ndim != 1 or vector.numel() != old_count:
        raise ValueError('Dense checkpoint tensor does not match its source architecture')
    result = vector.new_empty(new_count)
    previous = torch.arange(old_layout[0][1], device=vector.device)
    for (offset, a, b), (new_offset, new_a, new_b) in zip(old_layout, new_layout):
        mapping = torch.arange(new_b, device=vector.device) % b
        counts = torch.bincount(previous, minlength=a).to(vector.dtype)
        weights = vector[offset:offset + a*b].reshape(a, b)
        widened = weights.index_select(0, previous).index_select(1, mapping)
        widened /= counts.index_select(0, previous).unsqueeze(1)
        result[new_offset:new_offset + new_a*new_b] = widened.reshape(-1)
        bias = vector[offset + a*b:offset + a*b + b]
        result[new_offset + new_a*new_b:new_offset + new_a*new_b + new_b] = bias[mapping]
        previous = mapping
    return result


def load(host, cfg, create=False):
    folder = workspace(cfg)
    checkpoints = sorted((folder / 'state').glob('checkpoint_*.json'), reverse=True)
    for path in checkpoints:
        try:
            pack = json.loads(path.read_text())
        except (OSError, ValueError):
            continue
        if pack['signature'] != signature(cfg):
            raise ValueError('Full-pipeline settings changed. Restore them or choose a new RUN_NAME.')
        return pack['state']
    if checkpoints:
        raise ValueError('No readable pipeline checkpoint; refusing to discard the incumbent')
    if not create:
        raise FileNotFoundError('Run the full training stage first')
    dcfg = dense_config(cfg)
    origin = None
    source_run = cfg.get('pipeline_source_run', '')
    if source_run:
        source = Path(cfg['root']) / 'checkpoints' / source_run
        import torch
        paths = sorted(source.glob('gpu_*.pt'), reverse=True)
        seed = None
        for path in paths:
            try:
                candidate = read_dense_checkpoint(path)
                if candidate['signature'] != host.gpu_signature(candidate['CFG']):
                    continue
                if not {'champion', 'mean', 'generation', 'rng'} <= set(candidate['state']):
                    continue
                seed = candidate
                break
            except Exception:
                continue
        if seed is None:
            raise FileNotFoundError(f'No readable dense checkpoint in {source}. Set SOURCE_RUN to your saved run; leave it blank only for a new network.')
        dense_state = seed['state']
        origin = {'run': source_run, 'generation': dense_state['generation'], 'checkpoint': str(path)}
        if seed['CFG']['gpu_hidden'] != cfg['gpu_hidden']:
            for key in ('mean', 'champion', 'initial'):
                dense_state[key] = widen_dense_vector(host, dense_state[key], seed['CFG'], dcfg)
            dense_state['hall'] = [widen_dense_vector(host, weights, seed['CFG'], dcfg)
                                   for weights in dense_state['hall']]
            origin['widened_from'] = seed['CFG']['gpu_hidden']
            origin['widened_to'] = cfg['gpu_hidden']
            # Old strength evidence belongs to the old numerical implementation.
            dense_state['champion_verified'] = False
            dense_state['champion_validation'] = None
            dense_state['promotion_protocol'] = 'widened-incumbent-unverified'
            print(f"Widened dense model: {origin['widened_from']} → {origin['widened_to']}; original checkpoints preserved", flush=True)
        # Keep learned tensors, incumbent, RNG and generation, but restart partial
        # fitness games because the new branch uses a different move selector.
        dense_state['jobs'] = []
        host.gpu_next_seeds(dense_state, dcfg)
        host.gpu_save(dcfg, dense_state)
    else:
        dense_state = host.gpu_load(dcfg, create=True)
    spec = {'kind': 'dense', 'dense': str(dense_snapshot(dcfg)), 'options': asdict(SearchOptions())}
    state = {'cycle': 0, 'stage': 0, 'attempts': 0, 'champion': spec, 'verified': False,
             'origin': origin, 'candidates': [], 'search_index': 0, 'history': [], 'sequence': 0}
    save(cfg, state)
    return state


def make_engine(host, spec):
    kind = spec['kind']
    if kind in ('dense', 'hybrid'):
        dense = host.GpuCristopherEngine(spec['dense'])
        evaluator = CallableEvaluator(lambda board: dense.values([board])[0])
        if kind == 'hybrid':
            evaluator = HybridEvaluator(ClassicalEvaluator(spec['classical']), evaluator)
    elif kind == 'classical':
        evaluator = ClassicalEvaluator(spec['classical'])
    elif kind in ('sparse', 'sparse_hybrid'):
        evaluator = SparseEvaluator.load(spec['sparse'])
        if kind == 'sparse_hybrid':
            evaluator = HybridEvaluator(ClassicalEvaluator(spec['classical']), evaluator)
    else:
        raise ValueError('Unknown pipeline evaluator')
    engine = Engine(evaluator, SearchOptions(**spec['options']))
    if kind in ('dense', 'hybrid'):
        engine.dense_model = dense
    return engine


def model_identity(spec):
    identity = dict(spec)
    if spec.get('dense'):
        path = Path(spec['dense'])
        metadata = json.loads(path.read_text())
        identity['dense_sha256'] = hashlib.sha256((path.parent / metadata['weights']).read_bytes()).hexdigest()
        identity['dense_metadata_sha256'] = hashlib.sha256(path.read_bytes()).hexdigest()
    if spec.get('sparse'):
        identity['sparse_sha256'] = hashlib.sha256(Path(spec['sparse']).read_bytes()).hexdigest()
    return identity


class DeployedEngine(Engine):
    def __init__(self, model_path, dense_class):
        from types import SimpleNamespace
        path = Path(model_path)
        metadata = json.loads(path.read_text())
        spec = dict(metadata['pipeline_spec'])
        for key in ('dense', 'sparse'):
            if spec.get(key):
                spec[key] = str(path.parent / spec[key])
        built = make_engine(SimpleNamespace(GpuCristopherEngine=dense_class), spec)
        super().__init__(built.evaluator, built.searcher.options, metadata['difficulty'])


def publish(host, cfg, state):
    spec = copy.deepcopy(state['champion'])
    source = Path(host.__file__).read_text() + '''
class CristopherEngine(_CHESS_ENGINE_PACKAGE.full_pipeline.DeployedEngine):
    def __init__(self, model_path, seed=42):
        super().__init__(model_path, GpuCristopherEngine)
'''
    identity = fingerprint({'spec': model_identity(spec), 'source': hashlib.sha256(source.encode()).hexdigest(),
                            'difficulty': cfg['difficulty'], 'verified': state['verified']})
    models = Path(cfg['root']) / 'models'
    pointer = models / 'latest_champion.json'
    if pointer.exists():
        old = json.loads(pointer.read_text())
        if old.get('fingerprint') == identity and all(
                (models / old['folder'] / name).is_file() and hashlib.sha256((models / old['folder'] / name).read_bytes()).hexdigest() == digest
                for name, digest in old['sha256'].items()):
            return models / old['folder']
    target = models / 'deployments' / (identity[:16] + '-' + uuid.uuid4().hex[:8])
    target.mkdir(parents=True)
    if spec.get('dense'):
        dense = Path(spec['dense'])
        metadata = json.loads(dense.read_text())
        shutil.copyfile(dense.parent / metadata['weights'], target / 'weights.pt')
        metadata['weights'] = 'weights.pt'
        atomic_json(target / 'dense.json', metadata)
        spec['dense'] = 'dense.json'
    if spec.get('sparse'):
        shutil.copyfile(spec['sparse'], target / 'weights.npz')
        spec['sparse'] = 'weights.npz'
    metadata = {'version': VERSION, 'search_version': 'shared-alpha-beta-v2', 'pipeline_spec': spec,
                'difficulty': cfg['difficulty'], 'champion_verified': state['verified'],
                'champion_validation': state.get('champion_validation'), 'origin': state.get('origin'),
                'pipeline_cycle': state['cycle'], 'run_name': cfg['run_name']}
    if spec.get('dense') or spec.get('sparse'):
        metadata['weights'] = 'weights.pt' if spec.get('dense') else 'weights.npz'
    atomic_json(target / 'cristopher_genome.json', metadata)
    with (target / 'cristopher_engine.py').open('w') as handle:
        handle.write(source); handle.flush(); os.fsync(handle.fileno())
    manifest = {'folder': str(target.relative_to(models)), 'fingerprint': identity,
                'sha256': {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in target.iterdir()},
                'run_name': cfg['run_name'], 'champion_verified': state['verified']}
    atomic_json(target / 'manifest.json', manifest)
    atomic_json(pointer, manifest)
    return target


def challenge(host, cfg, state, candidate, label, deadline):
    identity = {'candidate': model_identity(candidate), 'incumbent': model_identity(state['champion']),
                'source': implementation_id(), 'cycle': state['cycle'], 'attempt': state['attempts'] + 1}
    for record in state['history']:
        report = record.get('report', {})
        if (record.get('source') == implementation_id() and report.get('complete')
                and fingerprint(report.get('candidate')) == fingerprint(identity['candidate'])
                and fingerprint(report.get('incumbent')) == fingerprint(identity['incumbent'])):
            return True  # Do not repeatedly test the same unchanged challenger.
    config = MatchConfig(pairs=cfg.get('pipeline_validation_pairs', 32),
                         seed=cfg['seed'] + 800000003 + 1009 * state['attempts'],
                         move_seconds=cfg.get('pipeline_move_seconds', .25), nodes=cfg.get('pipeline_nodes', 10000),
                         max_plies=1024, base_seconds=120, increment=cfg.get('pipeline_move_seconds', .25))
    folder = workspace(cfg) / 'validation' / fingerprint(identity)[:20]
    report = run_match(lambda: make_engine(host, candidate), lambda: make_engine(host, state['champion']),
                       config, folder, identity['candidate'], identity['incumbent'], deadline,
                       attempt=state['attempts'] + 1,
                       progress=lambda n, total: print(f'{label}: {n}/{total} validation games', flush=True))
    if report['finished_games'] != 2 * config.pairs:
        return False
    state['attempts'] += 1
    state['history'].append({'cycle': state['cycle'], 'stage': label, 'source': implementation_id(), 'report': report})
    if report['accepted']:
        state['champion'] = copy.deepcopy(candidate)
        state['champion_validation'] = report
        state['verified'] = True
    save(cfg, state)
    publish(host, cfg, state)
    return True


def diagnostics(host, cfg, state, deadline):
    folder = workspace(cfg) / 'reports'
    report_id = fingerprint({'source': implementation_id(), 'champion': model_identity(state['champion'])})[:16]
    path = folder / f"cycle_{state['cycle']:04d}_{report_id}.json"
    rows = json.loads(path.read_text())['positions'] if path.exists() else []
    for case in CASES[len(rows):]:
        if time.monotonic() >= deadline:
            return False
        engine = make_engine(host, state['champion'])
        board = chess.Board(case['fen'])
        tracemalloc.start()
        try:
            result = engine.choose(board, seconds=min(.25, max(0, deadline-time.monotonic())), nodes=cfg.get('pipeline_nodes', 10000))
            _, peak = tracemalloc.get_traced_memory()
        finally:
            tracemalloc.stop()
        passed = None
        if case['goal'] == 'bestmove':
            passed = result.move.uci() in case['moves']
        elif case['goal'] == 'mate':
            board.push(result.move); passed = board.is_checkmate()
        row = {'id': case['id'], 'move': result.move.uci(), 'passed': passed, 'depth': result.depth,
               'stats': result.stats, 'python_peak_bytes': peak}
        if hasattr(engine, 'dense_model'):
            bank = engine.dense_model.bank
            row['device'] = str(bank.device)
            if bank.device.type == 'cuda':
                row['cuda_allocated_bytes'] = bank.torch.cuda.memory_allocated(bank.device)
        rows.append(row)
        atomic_json(path, {'source': implementation_id(), 'champion': model_identity(state['champion']), 'positions': rows,
                          'solved': sum(r['passed'] is True for r in rows), 'scored': sum(r['passed'] is not None for r in rows)})
    return True


def sparse_test_report(labels, model, path):
    identity = {'data': hashlib.sha256(Path(labels).read_bytes()).hexdigest(),
                'model': hashlib.sha256(Path(model).read_bytes()).hexdigest()}
    if path.exists() and json.loads(path.read_text()).get('identity') == identity:
        return
    neural, classical = SparseEvaluator.load(model), ClassicalEvaluator()
    errors = {'neural': [], 'classical': []}
    for line in Path(labels).read_text().splitlines():
        row = json.loads(line)
        if row.get('split') != 'test' or 'cp_white' not in row:
            continue
        board = chess.Board(row['fen'])
        target = np.tanh(row['cp_white']/400) * (1 if board.turn else -1)
        for name, evaluator in (('neural', neural), ('classical', classical)):
            errors[name].append(float((np.tanh(evaluator(board)/400)-target)**2))
    atomic_json(path, {'identity': identity, 'test_positions': len(errors['neural']),
                'mse_tanh_cp400': {k: float(np.mean(v)) if v else None for k, v in errors.items()},
                'note': 'Untouched test labels are reporting only, never a training or promotion criterion. Loss is not Elo.'})


def run(host, cfg):
    print_usage(cfg['root'])
    state = load(host, cfg, create=True)
    publish(host, cfg, state)
    deadline = time.monotonic() + cfg['max_hours'] * 3600
    root = workspace(cfg)
    rating_seconds = min(max(0., cfg.get('rating_minutes', 5.))*60, cfg['max_hours']*3600*.1) if cfg.get('rating_enabled', False) else 0
    training_deadline = deadline - rating_seconds
    prune_pipeline_exports(cfg)
    def rate(until):
        if rating_seconds and time.monotonic() < until:
            measure_strength(cfg, model_identity(state['champion']),
                             lambda: make_engine(host, state['champion']), until)
    def advance():
        state['stage'] += 1; save(cfg, state)
    try:
        rate(min(training_deadline, time.monotonic() + rating_seconds))
        while time.monotonic() < training_deadline and state['stage'] < len(STAGES):
            stage = STAGES[state['stage']]
            remaining = training_deadline - time.monotonic()
            print(f"Full pipeline: cycle {state['cycle']}, stage {stage}, {remaining/60:.1f} minutes left", flush=True)
            if stage == 'dense':
                dcfg = dense_config(cfg)
                dcfg['max_hours'] = remaining * .45 / 3600
                host.gpu_evolve(dcfg)
                state['dense_candidate'] = {'kind': 'dense', 'dense': str(dense_snapshot(dcfg)), 'options': state['champion']['options']}
                advance()
            elif stage == 'parameters':
                config = GeneticConfig(population=4 if cfg['QUICK_TEST'] else 8, elite=1 if cfg['QUICK_TEST'] else 2,
                         generations=cfg['generations'], seed=cfg['seed'],
                         move_seconds=cfg.get('pipeline_move_seconds', .25), nodes=cfg.get('pipeline_nodes', 10000),
                         validation_pairs=cfg.get('pipeline_validation_pairs', 32), max_plies=1024)
                parameters = evolve(config, root / 'parameters', hours=remaining*.35/3600)
                weights = parameters['champion']
                options = state['champion']['options']
                state['candidates'] = [state['dense_candidate'], {'kind': 'classical', 'classical': weights, 'options': options},
                    {**state['dense_candidate'], 'kind': 'hybrid', 'classical': weights}]
                advance()
            elif stage == 'sparse':
                if cfg.get('pipeline_sparse', True):
                    labels = Path(cfg.get('pipeline_labels') or root / 'data' / 'labels.jsonl')
                    excluded = {min(' '.join(chess.Board(c['fen']).fen().split()[:4]), ' '.join(chess.Board(c['fen']).mirror().fen().split()[:4])) for c in CASES}
                    labels = prepare_labels(labels, cfg.get('pipeline_label_positions', 20000), time.monotonic()+remaining*.25, excluded)
                    if labels is None:
                        state['sparse_status'] = 'Label download checkpointed; resume this stage'; save(cfg, state); break
                    trained = train_labels(labels, root/'sparse', epochs=cfg.get('pipeline_sparse_epochs', 100),
                                 batch_size=256, hidden=64, deadline=training_deadline,
                                 progress=lambda row: print('Sparse training:', row, flush=True))
                    if trained['epochs'] < trained['target_epochs']:
                        save(cfg, state); return state
                    best = str(root/'sparse'/'best_validation.npz')
                    digest = hashlib.sha256(Path(best).read_bytes()).hexdigest()
                    frozen = root/'sparse'/f"candidate_{digest}.npz"
                    if not frozen.exists():
                        shutil.copyfile(best, frozen)
                    sparse_test_report(labels, frozen, root/'sparse'/'test_report.json')
                    state['candidates'].extend([{'kind': 'sparse', 'sparse': str(frozen), 'options': state['champion']['options']},
                        {'kind': 'sparse_hybrid', 'sparse': str(frozen), 'classical': state['candidates'][1]['classical'],
                         'options': state['champion']['options']}])
                    state['sparse_status'] = 'trained; match validation required'
                advance()
            elif stage == 'candidates':
                while state['candidates']:
                    candidate = state['candidates'][0]
                    if model_identity(candidate) == model_identity(state['champion']):
                        state['candidates'].pop(0); save(cfg, state); continue
                    if not challenge(host, cfg, state, candidate, candidate['kind'], training_deadline):
                        return state
                    state['candidates'].pop(0); save(cfg, state)
                advance()
            elif stage == 'search':
                features = ('null_move', 'lmr', 'futility', 'check_extensions', 'see', 'countermove', 'pvs', 'aspiration')
                while state['search_index'] < len(features):
                    feature = features[state['search_index']]
                    candidate = copy.deepcopy(state['champion'])
                    candidate['options'][feature] = not candidate['options'][feature]
                    if not challenge(host, cfg, state, candidate, 'search:' + feature, training_deadline):
                        return state
                    state['search_index'] += 1; save(cfg, state)
                advance()
            elif stage == 'diagnostics':
                if not diagnostics(host, cfg, state, training_deadline):
                    return state
                state['cycle'] += 1; state['stage'] = 0; state['search_index'] = 0
                save(cfg, state)
                break  # One coordinated cycle per Run all; next session continues.
        rate(min(deadline, time.monotonic() + rating_seconds))
    finally:
        save(cfg, state)
        publish(host, cfg, state)
        prune_pipeline_exports(cfg)
        print_usage(cfg['root'])
    return state
