"""Adapters preserving notebook weights and checkpoint identities."""
from pathlib import Path
import json
import time
import numpy as np
from .evaluation import CallableEvaluator, ClassicalEvaluator
from .runtime import Engine
from .search import SearchOptions, SearchResult
from .matches import MatchConfig, run_match, fingerprint, implementation_id
from .training import GeneticConfig, evolve, load_state

SEARCH_VERSION = 'shared-alpha-beta-v2'
PROMOTION_VERSION = 'independent-pairs-v1'


def neural_move(engine, board, limits):
    if not hasattr(engine, '_modern_search'):
        options = SearchOptions(**engine.cfg.get('gpu_search_options', {}))
        engine._modern_search = Engine(CallableEvaluator(lambda b: engine.values([b])[0]), options)
    result = engine._modern_search.choose(board, seconds=limits['seconds'], nodes=limits.get('nodes', 30000), depth=limits.get('depth', 64))
    return {'move': result.move.uci(), 'info': {'eval': result.score, 'depth': result.depth,
            'nodes': int(result.stats['nodes']), 'time_ms': int(result.stats['elapsed_seconds'] * 1000),
            'pv': [m.uci() for m in result.pv], 'search_version': SEARCH_VERSION,
            'search_stats': result.stats}}


def validation_config(cfg, generation):
    return MatchConfig(pairs=cfg.get('gpu_validation_pairs', 32),
                       seed=cfg['seed'] + 900000000 + generation * 10007,
                       move_seconds=cfg.get('gpu_validation_seconds', .03),
                       nodes=cfg.get('gpu_validation_nodes', 256), depth=3,
                       max_plies=cfg.get('gpu_max_plies', cfg.get('max_plies', 256)), opening_plies=8)


def validate_neural(host, cfg, state, bank, winner, deadline):
    config = validation_config(cfg, state['generation'])
    attempt = state.get('promotion_attempts', 0) + 1
    directory = Path(cfg['root']) / 'logs' / cfg['run_name'] / 'validation' / implementation_id()[:16] / f"g{state['generation']:06d}_{SEARCH_VERSION}"

    def factory(model):
        def evaluate(board):
            features = np.stack([host.gpu_features(board)]).astype(np.float16)
            return float(bank.evaluate([(0, model, features)])[0][0])
        return Engine(CallableEvaluator(evaluate), SearchOptions(**cfg.get('gpu_search_options', {})))
    report = run_match(lambda: factory(winner), lambda: factory(bank.champion_id), config, directory,
                       f"{cfg['run_name']}:g{state['generation']}:candidate{winner}",
                       f"{cfg['run_name']}:champion{state['champion_generation']}", deadline,
                       min_pairs=32, attempt=attempt)
    state['last_validation'] = report
    state['promotion_protocol'] = PROMOTION_VERSION
    if report['finished_games'] != 2 * config.pairs:
        return None
    state['promotion_attempts'] = attempt
    if report['accepted']:
        state['champion_verified'] = True
        state['champion_validation'] = report
    return report['accepted']


def validate_classic(host, cfg, state, candidate, deadline):
    config = validation_config(cfg, state['generation'])
    # Classical GA uses wall-clock deadlines; the match runner uses monotonic time.
    remaining = max(0, deadline - time.time())
    incumbent = state.get('champion') or {'genome': host.genome_default().tolist(), 'generation': -1}

    class LegacyPlayer:
        def __init__(self, genome):
            self.genome = np.asarray(genome)

        def choose(self, board, seconds, nodes, depth):
            move, score, completed, visited = host.search(board, self.genome, depth, seconds, nodes)
            return SearchResult(move, score, completed, [], {'nodes': visited})
    report = run_match(lambda: LegacyPlayer(candidate), lambda: LegacyPlayer(incumbent['genome']), config,
                       Path(cfg['root']) / 'logs' / cfg['run_name'] / 'validation' / implementation_id()[:16] / f"classic_g{state['generation']:06d}",
                       fingerprint(candidate), fingerprint(incumbent['genome']), time.monotonic() + remaining,
                       min_pairs=32, attempt=state.get('promotion_attempts', 0) + 1)
    state['last_validation'] = report
    state['promotion_protocol'] = PROMOTION_VERSION
    if report['finished_games'] != 2 * config.pairs:
        return None
    state['promotion_attempts'] = state.get('promotion_attempts', 0) + 1
    if report['accepted']:
        state['champion_verified'] = True
        state['champion_validation'] = report
    return report['accepted']


def parameter_config(cfg):
    return GeneticConfig(population=4 if cfg['QUICK_TEST'] else 8, elite=1 if cfg['QUICK_TEST'] else 2,
                         generations=cfg['generations'], seed=cfg['seed'],
                         validation_pairs=cfg.get('gpu_validation_pairs', 32),
                         move_seconds=cfg.get('gpu_validation_seconds', .03),
                         nodes=cfg.get('gpu_validation_nodes', 1000), max_plies=cfg['max_plies'])


def parameter_export(host, cfg, state):
    source = Path(host.__file__).read_text()
    source += '''
class ParameterCristopherEngine(_CHESS_ENGINE_PACKAGE.runtime.Engine):
    def __init__(self, path, seed=42):
        data=json.loads(Path(path).read_text())
        super().__init__(_CHESS_ENGINE_PACKAGE.evaluation.ClassicalEvaluator(data['genome']), settings=data['difficulty'])
CristopherEngine = ParameterCristopherEngine
'''
    artifact = {'version': 'chess-parameters-1', 'genome': state['champion'], 'CFG': cfg,
                'difficulty': cfg['difficulty'], 'generation': state['generation'],
                'champion_generation': state['champion_generation'], 'opening_book': {},
                'search_version': SEARCH_VERSION, 'promotion_protocol': PROMOTION_VERSION,
                'champion_verified': state['verified'], 'champion_validation': state.get('promotion_report')}
    return host.publish_champion(cfg, artifact, source)


def run_parameters(host, cfg):
    folder = Path(cfg['root']) / 'checkpoints' / cfg['run_name']
    return evolve(parameter_config(cfg), folder, cfg['max_hours'], publish=lambda state: parameter_export(host, cfg, state))


def load_parameters(cfg):
    return load_state(Path(cfg['root']) / 'checkpoints' / cfg['run_name'], parameter_config(cfg))[0]
