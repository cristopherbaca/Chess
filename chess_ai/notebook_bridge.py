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


def validate_saved_dense_search(host, cfg, folder, pairs=32, seconds=.5, hours=3):
    """Compare this saved champion's old beam and current search in its runtime.

    Uses the same read-only weight bank for both sides, fresh search state per
    game, independent paired openings, and resumable logs. Never promotes a model.
    """
    import copy
    import hashlib
    import platform
    from .matches import atomic_json
    folder = Path(folder)
    saved = host.GpuCristopherEngine(folder / 'cristopher_genome.json')
    model_hash = hashlib.sha256((folder / 'weights.pt').read_bytes()).hexdigest()
    config = MatchConfig(pairs=pairs, seed=cfg['seed'] + 700000003, move_seconds=seconds,
                         nodes=180000, max_plies=1024, base_seconds=120, increment=seconds)

    class Player:
        def __init__(self, backend):
            self.engine = copy.copy(saved)
            self.engine.cfg = {**saved.cfg, 'gpu_search_backend': backend}
            self.engine.settings = copy.deepcopy(saved.settings)
            self.engine.__dict__.pop('_modern_search', None)

        def choose(self, board, seconds, nodes, depth):
            self.engine.settings['hard'].update(seconds=seconds, nodes=nodes, depth=depth)
            answer = self.engine.get_move(board.fen(), [m.uci() for m in board.move_stack], 'hard')
            info = answer['info']
            import chess
            return SearchResult(chess.Move.from_uci(answer['move']), info['eval'], info['depth'], [],
                                info.get('search_stats', {'nodes': info['nodes']}))

    identity = {'weights_sha256': model_hash, 'implementation': implementation_id()}
    directory = Path(cfg['root']) / 'logs' / cfg['run_name'] / 'saved_champion_validation' / fingerprint({**identity, 'pairs': pairs, 'seconds': seconds})[:20]
    atomic_json(directory / 'runtime.json', {'platform': platform.platform(), 'device': str(saved.bank.device),
                'torch': str(saved.torch.__version__), 'weights_sha256': model_hash,
                'note': 'Actual saved weights; fixed time, same evaluator. This validation never changes the published champion.'})
    return run_match(lambda: Player('alpha_beta'), lambda: Player('beam'), config, directory,
                     {**identity, 'backend': 'alpha_beta'}, {**identity, 'backend': 'beam'},
                     time.monotonic() + hours * 3600,
                     progress=lambda n, total: print(f'Saved-champion validation: {n}/{total} games', flush=True))


def search_training_games(host, cfg, state, bank, deadline, save):
    """Play existing ES jobs through the shared search, preserving GA updates."""
    import chess
    import chess.engine
    from .evaluation import HybridEvaluator
    last_save = time.monotonic()
    external = None
    try:
        for job in state['jobs']:
            if job['done']:
                continue
            board = chess.Board()
            for move in job['moves']:
                board.push_uci(move)
            players = {}
            for model in (job['white'], job['black']):
                if model < 0 or model in players:
                    continue
                def evaluate(position, model=model):
                    features = np.stack([host.gpu_features(position)]).astype(np.float16)
                    return float(bank.evaluate([(0, model, features)])[0][0])
                evaluator = CallableEvaluator(evaluate)
                if cfg.get('gpu_classical_weights'):
                    evaluator = HybridEvaluator(ClassicalEvaluator(cfg['gpu_classical_weights']), evaluator)
                players[model] = Engine(evaluator, SearchOptions(**cfg.get('gpu_search_options', {})))
            trace = host.gpu_result_path(cfg, state, job).with_suffix('.search.jsonl')
            trace.parent.mkdir(parents=True, exist_ok=True)
            while not job['done'] and time.monotonic() < deadline:
                terminal = host.gpu_terminal(board)
                if terminal is not None:
                    host.gpu_finish(cfg, state, job, terminal)
                    break
                if len(job['moves']) >= cfg['gpu_max_plies']:
                    host.gpu_finish(cfg, state, job, truncated=True)
                    break
                model = job['white'] if board.turn else job['black']
                if model >= 0:
                    before = bank.positions
                    result = players[model].choose(board, seconds=min(cfg.get('gpu_training_seconds', .25), deadline-time.monotonic()),
                               nodes=cfg.get('gpu_training_nodes', 10000), depth=cfg.get('gpu_training_depth', 64))
                    move = result.move
                    state['positions'] += bank.positions - before
                    with trace.open('a') as handle:
                        handle.write(json.dumps({'ply': board.ply(), 'fen': board.fen(), 'move': move.uci(),
                                                 'score_stm': result.score, 'depth': result.depth, 'stats': result.stats})+'\n')
                elif model == -2:
                    if external is None:
                        external = chess.engine.SimpleEngine.popen_uci(cfg['stockfish'], timeout=10)
                        option = external.options['UCI_Elo']
                        external.configure({'Threads': 1, 'Hash': 16, 'UCI_LimitStrength': True,
                                            'UCI_Elo': max(option.min, min(option.max, cfg['anchor_elo']))})
                    move = external.play(board, chess.engine.Limit(time=cfg['stockfish_seconds'])).move
                else:
                    rng = np.random.default_rng(np.random.SeedSequence([cfg['seed'], state['generation'], job['id'], board.ply()]))
                    legal = list(board.legal_moves)
                    move = legal[int(rng.integers(len(legal)))]
                if move not in board.legal_moves:
                    raise ValueError('Search training returned an illegal move')
                board.push(move); job['moves'].append(move.uci())
                if time.monotonic() - last_save >= cfg['gpu_checkpoint_seconds']:
                    save(); last_save = time.monotonic()
                    print(f"Search-based ES: generation {state['generation']}, game {job['id']}, ply {board.ply()}", flush=True)
            save()
            if time.monotonic() >= deadline:
                break
    finally:
        if external is not None:
            external.quit()
