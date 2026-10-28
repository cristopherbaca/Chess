"""Resumable genetic optimization of explicit evaluation weights.

Training fitness selects parents. Only independent holdout matches can replace
the deployment champion. The existing notebook GA/ES backends remain available.
"""
from dataclasses import dataclass, asdict
import json
import math
from pathlib import Path
import random
import time
import numpy as np
from .evaluation import ClassicalEvaluator, DEFAULT_WEIGHTS
from .runtime import Engine
from .matches import MatchConfig, atomic_json, fingerprint, run_match, implementation_id

GENES = sorted(DEFAULT_WEIGHTS)


@dataclass
class GeneticConfig:
    population: int = 8
    elite: int = 2
    tournament: int = 3
    mutation_rate: float = .15
    mutation_sigma: float = .2
    seed: int = 42
    generations: int = 100
    training_pairs: int = 2
    validation_pairs: int = 32
    move_seconds: float = .03
    nodes: int = 1000
    max_plies: int = 256


def vector(weights):
    return [float(v) for key in GENES for v in weights[key]]


def weights(values):
    return {key: list(values[2 * i:2 * i + 2]) for i, key in enumerate(GENES)}


def scale():
    return [max(5, abs(v) * .15) for v in vector(DEFAULT_WEIGHTS)]


def bounded(values):
    result = list(values)
    for i, key in enumerate(GENES):
        for j in (0, 1):
            default = DEFAULT_WEIGHTS[key][j]
            lo, hi = (.5 * default, 1.8 * default) if key in ('pawn', 'knight', 'bishop', 'rook', 'queen') else (-150, 150)
            result[2 * i + j] = min(hi, max(lo, result[2 * i + j]))
    return result


def diversity(population):
    return float(np.mean(np.std(np.asarray([vector(w) for w in population]) / np.asarray(scale()), axis=0)))


def next_generation(population, fitness, cfg, rng):
    order = sorted(range(len(population)), key=lambda i: fitness[i], reverse=True)
    result = [json.loads(json.dumps(population[i])) for i in order[:cfg.elite]]
    scales = scale()

    def select():
        return population[max(rng.sample(range(len(population)), min(cfg.tournament, len(population))), key=lambda i: fitness[i])]
    sigma = cfg.mutation_sigma * (1.5 if diversity(population) < .05 else 1)
    while len(result) < cfg.population:
        a, b = vector(select()), vector(select())
        child = []
        for x, y, step in zip(a, b, scales):
            lo, hi = min(x, y), max(x, y)
            value = rng.uniform(lo - .25 * (hi - lo), hi + .25 * (hi - lo))
            if rng.random() < cfg.mutation_rate:
                value += rng.gauss(0, sigma * step)
            child.append(value)
        result.append(weights(bounded(child)))
    return result


def save_state(directory, state, signature):
    directory = Path(directory)
    sequence = state.get('sequence', 0) + 1
    state['sequence'] = sequence
    atomic_json(directory / f'checkpoint_{sequence:08d}.json', {'signature': signature, 'state': state})
    for old in sorted(directory.glob('checkpoint_*.json'))[:-3]:
        old.unlink()


def load_state(directory, cfg):
    signature = fingerprint({'schema': 'parameters-ga-v1', **asdict(cfg)})
    paths = sorted(Path(directory).glob('checkpoint_*.json'), reverse=True)
    for path in paths:
        try:
            pack = json.loads(path.read_text())
        except (ValueError, OSError):
            continue
        if pack['signature'] != signature:
            raise ValueError('Genetic configuration changed; use a different run name')
        return pack['state'], signature
    if paths:
        raise ValueError('No readable genetic checkpoint; restore a backup')
    rng = random.Random(cfg.seed)
    initial = vector(DEFAULT_WEIGHTS)
    population = [weights(initial)]
    for _ in range(cfg.population - 1):
        population.append(weights(bounded([x + rng.gauss(0, cfg.mutation_sigma * s) for x, s in zip(initial, scale())])))
    state = {'generation': 0, 'population': population, 'champion': weights(initial),
             'champion_generation': -1, 'verified': False, 'attempts': 0, 'history': [],
             'rng': rng.getstate(), 'hall': []}
    save_state(directory, state, signature)
    return state, signature


def evolve(config, directory, hours=3, publish=None):
    if config.population < 4 or not 0 < config.elite < config.population or hours <= 0:
        raise ValueError('Invalid genetic configuration')
    directory = Path(directory)
    state, signature = load_state(directory, config)
    if publish:
        publish(state)
    deadline = time.monotonic() + hours * 3600
    rng = random.Random()

    def tuples(value):
        return tuple(tuples(x) for x in value) if isinstance(value, list) else value
    rng.setstate(tuples(state['rng']))
    try:
        while state['generation'] < config.generations and time.monotonic() < deadline:
            generation = state['generation']
            fitness = []
            for index, candidate in enumerate(state['population']):
                opponents = [('default', weights(vector(DEFAULT_WEIGHTS))), ('champion', state['champion']),
                             ('peer', state['population'][(index + 1 + generation % (config.population - 1)) % config.population])]
                scores = []
                for label, opponent in opponents:
                    match = MatchConfig(pairs=config.training_pairs, seed=config.seed + generation * 10007,
                                        move_seconds=config.move_seconds, nodes=config.nodes, max_plies=config.max_plies)
                    report = run_match(lambda w=candidate: Engine(ClassicalEvaluator(w)),
                                       lambda w=opponent: Engine(ClassicalEvaluator(w)), match,
                                       directory / 'matches' / implementation_id()[:16] / f'g{generation}_c{index}_{label}',
                                       fingerprint(candidate), fingerprint(opponent), deadline,
                                       min_pairs=config.validation_pairs)
                    if report['finished_games'] != 2 * match.pairs:
                        return state
                    scores.append(report['mean_score'] if report['mean_score'] is not None else .5)
                fitness.append(sum(scores) / len(scores))
                save_state(directory, state, signature)
            best = max(range(len(fitness)), key=lambda i: fitness[i])
            candidate = state['population'][best]
            validation = MatchConfig(pairs=config.validation_pairs, seed=config.seed + 100000000 + generation * 10007,
                                     move_seconds=config.move_seconds, nodes=config.nodes, max_plies=config.max_plies,
                                     opening_plies=8)
            report = run_match(lambda: Engine(ClassicalEvaluator(candidate)),
                               lambda: Engine(ClassicalEvaluator(state['champion'])), validation,
                               directory / 'validation' / implementation_id()[:16] / f'g{generation}', fingerprint(candidate),
                               fingerprint(state['champion']), deadline, min_pairs=config.validation_pairs,
                               attempt=state['attempts'] + 1)
            if report['finished_games'] != 2 * validation.pairs:
                return state
            state['attempts'] += 1
            if report['accepted']:
                state['hall'] = (state['hall'] + [state['champion']])[-4:]
                state['champion'] = json.loads(json.dumps(candidate))
                state['champion_generation'] = generation
                state['verified'] = True
                state['promotion_report'] = report
            state['history'].append({'generation': generation, 'fitness': fitness,
                                     'diversity': diversity(state['population']), 'promotion': report})
            state['population'] = next_generation(state['population'], fitness, config, rng)
            state['rng'] = rng.getstate()
            state['generation'] += 1
            save_state(directory, state, signature)
            if publish:
                publish(state)
            atomic_json(directory / 'history.json', state['history'])
    finally:
        save_state(directory, state, signature)
        if publish:
            publish(state)
    return state
