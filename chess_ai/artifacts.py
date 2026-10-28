"""Publish modular evaluator artifacts without silently replacing an incumbent."""
import hashlib
from dataclasses import asdict
import json
from pathlib import Path
import shutil
import uuid
from .evaluation import ClassicalEvaluator
from .neural import SparseEvaluator
from .matches import atomic_json, implementation_id
from .runtime import DEFAULT_LIMITS
from .search import SearchOptions


def publish_model(model, models, bundle_source, validation=None, initial=False, hybrid=False):
    model, models = Path(model), Path(models)
    pointer = models / 'latest_champion.json'
    model_hash = hashlib.sha256(model.read_bytes()).hexdigest()
    previous = json.loads(pointer.read_text()) if pointer.exists() else None
    if initial and previous:
        raise ValueError('An incumbent already exists; initial publication cannot replace it')
    verified = False
    report = None
    if validation:
        folder = Path(validation)
        report = json.loads((folder / 'report.json').read_text())
        match = json.loads((folder / 'match.json').read_text())
        candidate = match['candidate']
        incumbent = match['incumbent']
        if not isinstance(candidate, dict) or candidate.get('model_sha256') != model_hash:
            raise ValueError('Validation belongs to a different candidate file')
        if not report.get('accepted') or not report.get('complete') or report.get('signature') != match['signature']:
            raise ValueError('A complete accepted validation report is required')
        if (match.get('implementation_sha256') != implementation_id()
                or candidate.get('search') != asdict(SearchOptions())
                or (candidate.get('evaluator', 'neural') == 'hybrid') != hybrid):
            raise ValueError('Validation must use the current code and deployment search/evaluator settings')
        if previous and (not isinstance(incumbent, dict) or incumbent.get('model_sha256') != previous.get('model_sha256')):
            raise ValueError('Validation is stale or used a different incumbent')
        verified = True
    elif not initial:
        raise ValueError('Provide accepted validation, or explicitly initialize an empty model directory')
    metadata = {'version': 'chess-modular-2', 'search_version': 'shared-alpha-beta-v2',
                'difficulty': DEFAULT_LIMITS, 'champion_verified': verified,
                'validation': report, 'model_sha256': model_hash, 'hybrid': hybrid}
    if model.suffix == '.npz':
        SparseEvaluator.load(model)
        metadata.update(backend='sparse', weights='weights.npz')
    else:
        metadata.update(backend='classical', genome=ClassicalEvaluator.load(model).weights)
    source = 'import json\nfrom pathlib import Path\n' + bundle_source + '''
class CristopherEngine(_CHESS_ENGINE_PACKAGE.runtime.Engine):
    def __init__(self, path, seed=42):
        path=Path(path); data=json.loads(path.read_text())
        if data['backend']=='sparse':
            evaluator=_CHESS_ENGINE_PACKAGE.neural.SparseEvaluator.load(path.parent/data['weights'])
            if data.get('hybrid'):
                evaluator=_CHESS_ENGINE_PACKAGE.evaluation.HybridEvaluator(_CHESS_ENGINE_PACKAGE.evaluation.ClassicalEvaluator(),evaluator)
        else:
            evaluator=_CHESS_ENGINE_PACKAGE.evaluation.ClassicalEvaluator(data['genome'])
        super().__init__(evaluator, settings=data['difficulty'])
'''
    folder = models / 'deployments' / (model_hash[:16] + '-' + uuid.uuid4().hex[:8])
    folder.mkdir(parents=True)
    (folder / 'cristopher_engine.py').write_text(source)
    if metadata.get('weights'):
        shutil.copyfile(model, folder / metadata['weights'])
    atomic_json(folder / 'cristopher_genome.json', metadata)
    checksums = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in folder.iterdir()}
    manifest = {'folder': str(folder.relative_to(models)), 'sha256': checksums,
                'model_sha256': model_hash, 'champion_verified': verified}
    atomic_json(folder / 'manifest.json', manifest)
    atomic_json(pointer, manifest)
    return folder
