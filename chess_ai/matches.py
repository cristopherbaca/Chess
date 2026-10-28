"""Color-paired matches, resumable games and conservative promotion evidence."""
from dataclasses import dataclass, asdict
from functools import lru_cache
import hashlib
import json
import math
import os
from pathlib import Path
import random
import sys
import time
import chess
import chess.pgn
import chess.engine
import numpy as np


class UciOpponent:
    """Optional external benchmark opponent; never used by the production Engine."""
    def __init__(self, command):
        self.engine = chess.engine.SimpleEngine.popen_uci(command, timeout=10)

    def choose(self, board, seconds, nodes, depth):
        from .search import SearchResult
        answer = self.engine.play(board, chess.engine.Limit(time=seconds, nodes=nodes, depth=depth),
                                  info=chess.engine.INFO_ALL)
        score = answer.info.get('score')
        score = score.pov(board.turn).score(mate_score=30000) if score is not None else 0
        return SearchResult(answer.move, float(score), answer.info.get('depth', 0),
                            answer.info.get('pv', []), {'nodes': answer.info.get('nodes', 0)})

    def close(self):
        self.engine.quit()


def atomic_json(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + '.tmp')
    with temporary.open('w') as handle:
        json.dump(data, handle, indent=2, allow_nan=False)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, path)


def fingerprint(data):
    return hashlib.sha256(json.dumps(data, sort_keys=True).encode()).hexdigest()


@lru_cache(maxsize=1)
def implementation_id():
    package = sys.modules[__package__]
    if hasattr(package, 'source_sha256'):
        return package.source_sha256
    names = ('board', 'evaluation', 'search', 'neural', 'runtime', 'matches', 'training', 'notebook_bridge',
             'datasets', 'validation_cases', 'full_pipeline')
    sources = {name: Path(__file__).with_name(name + '.py').read_text() for name in names}
    return hashlib.sha256(json.dumps(sources, sort_keys=True).encode()).hexdigest()


@dataclass
class MatchConfig:
    pairs: int = 32
    seed: int = 42
    move_seconds: float = .05
    nodes: int = 3000
    depth: int = 64
    base_seconds: float = 30
    increment: float = .1
    max_plies: int = 256
    opening_plies: int = 6
    opening_file: str = ''


def openings(config):
    if config.opening_file:
        book = json.loads(Path(config.opening_file).read_text())['openings']
        if config.pairs > len(book):
            raise ValueError('Not enough distinct opening pairs in the supplied book')
        selected = random.Random(config.seed).sample(book, config.pairs)
        result = []
        for item in selected:
            board = chess.Board()
            for move in item['moves']:
                board.push_uci(move)
            if board.is_game_over(claim_draw=True):
                raise ValueError('Terminal opening in match book')
            result.append(list(item['moves']))
        return result
    result = []
    for pair in range(config.pairs):
        rng = random.Random(config.seed + pair * 1009)
        board = chess.Board()
        for _ in range(config.opening_plies):
            legal = sorted(board.legal_moves, key=lambda m: m.uci())
            rng.shuffle(legal)
            for move in legal:
                board.push(move)
                if not board.is_game_over(claim_draw=True):
                    break
                board.pop()
            else:
                break
        result.append([m.uci() for m in board.move_stack])
    return result


def evidence(rows, expected_pairs, min_pairs=32, alpha=.05, attempt=1):
    if not 0 < alpha < 1 or attempt < 1:
        raise ValueError('Invalid statistical test settings')
    # Alpha spending bounds the total nominal false-positive budget over attempts.
    spent_alpha = alpha / (attempt * (attempt + 1))
    groups = {}
    for row in rows:
        groups.setdefault(row['pair'], []).append(row)
    pair_scores = []
    for group in groups.values():
        if (len(group) == 2 and {r['candidate_white'] for r in group} == {True, False}
                and all(not r.get('truncated') and not r.get('error') for r in group)):
            pair_scores.append(sum(r['score'] for r in group) / 2)
    n = len(pair_scores)
    mean = float(np.mean(pair_scores)) if n else None
    radius = math.sqrt(math.log(1 / spent_alpha) / (2 * n)) if n else 1
    lower = max(0., mean - radius) if mean is not None else 0.
    complete = n == expected_pairs and len(rows) == expected_pairs * 2
    accepted = complete and n >= min_pairs and lower > .5
    interval = None
    elo = None
    if n >= 10:
        two_sided = math.sqrt(math.log(2 / .05) / (2 * n))
        interval = [max(0., mean - two_sided), min(1., mean + two_sided)]
        elo = 400 * math.log10(mean / (1 - mean)) if 0 < mean < 1 else None

    def elo_bound(p):
        return 400 * math.log10(p / (1 - p)) if 0 < p < 1 else None
    return {'accepted': accepted, 'complete': complete, 'pairs': n, 'mean_score': mean,
            'score_lower_bound': lower, 'test_alpha': spent_alpha, 'attempt': attempt,
            'method': 'one-sided Hoeffding bound on independent opening-pair scores; alpha spending',
            'wins': sum(r['score'] == 1 for r in rows if not r.get('truncated')),
            'draws': sum(r['score'] == .5 for r in rows if not r.get('truncated')),
            'losses': sum(r['score'] == 0 for r in rows if not r.get('truncated')),
            'unfinished': sum(bool(r.get('truncated')) for r in rows),
            'errors': sum(bool(r.get('error')) for r in rows),
            'score_interval_95': interval, 'elo_difference': elo,
            'elo_interval_95': [elo_bound(x) for x in interval] if interval else None,
            'elo_note': 'Relative to this opponent/control only; null endpoints are unbounded. Not an absolute rating.'}


def play_game(players, opening, config, path, pair, candidate_white, deadline=float('inf')):
    path = Path(path)
    if path.exists():
        row = json.loads(path.read_text())
        if row.get('done'):
            return row
    else:
        row = {'pair': pair, 'candidate_white': candidate_white, 'moves': list(opening),
               'remaining': [config.base_seconds, config.base_seconds], 'evaluations': [], 'done': False}
    board = chess.Board()
    for move in row['moves']:
        board.push_uci(move)
    error = None
    winner = None
    truncated = False
    while not board.is_game_over() and not board.is_repetition(3) and not board.is_fifty_moves():
        if time.monotonic() >= deadline:
            atomic_json(path, row)
            return None
        if board.ply() >= config.max_plies:
            truncated = True
            break
        side = 0 if board.turn else 1
        began = time.monotonic()
        try:
            budget = min(config.move_seconds, max(.001, row['remaining'][side] / 20 + config.increment / 2), max(0, deadline - began))
            answer = players[side].choose(board.copy(stack=True), seconds=budget, nodes=config.nodes, depth=config.depth)
            elapsed = time.monotonic() - began
            row['remaining'][side] -= elapsed
            if row['remaining'][side] <= 0:
                error, winner = 'clock expired', not board.turn
                break
            if answer.move not in board.legal_moves:
                raise ValueError('illegal move')
            row['remaining'][side] += config.increment
            row['evaluations'].append({'fen': board.fen(), 'move': answer.move.uci(),
                                      'score_stm': answer.score, 'depth': answer.depth, 'seconds': elapsed,
                                      'nodes': answer.stats.get('nodes', 0),
                                      'search_stats': answer.stats})
            board.push(answer.move)
            row['moves'].append(answer.move.uci())
            atomic_json(path, row)
        except Exception as exc:
            error, winner = f'{type(exc).__name__}: {exc}', not board.turn
            break
    if not error and not truncated:
        outcome = board.outcome()
        winner = outcome.winner if outcome else None
    score = .5 if winner is None else float(winner == candidate_white)
    row.update(done=True, truncated=truncated, error=error, score=score)
    game = chess.pgn.Game.from_board(board)
    game.headers.update(Event='Chess controlled match', Result='*' if truncated else '1/2-1/2' if winner is None else '1-0' if winner else '0-1',
                        Termination=error or ('ply cap' if truncated else 'terminal rules'))
    path.with_suffix('.pgn').write_text(str(game) + '\n\n')
    atomic_json(path, row)
    return row


def run_match(candidate_factory, incumbent_factory, config, directory, candidate_id, incumbent_id,
              deadline=float('inf'), min_pairs=32, attempt=1, progress=None):
    if config.pairs < 1 or config.nodes < 1 or config.move_seconds <= 0 or config.base_seconds <= 0:
        raise ValueError('Invalid match budget')
    directory = Path(directory)
    identity = {'candidate': candidate_id, 'incumbent': incumbent_id, 'config': asdict(config),
                'implementation_sha256': implementation_id(), 'min_pairs': min_pairs, 'attempt': attempt}
    if config.opening_file:
        identity['opening_sha256'] = hashlib.sha256(Path(config.opening_file).read_bytes()).hexdigest()
    signature = fingerprint(identity)
    manifest = directory / 'match.json'
    if manifest.exists() and json.loads(manifest.read_text())['signature'] != signature:
        raise ValueError('Match configuration changed; use a new match directory')
    atomic_json(manifest, {'signature': signature, **identity})
    rows = []
    for pair, opening in enumerate(openings(config)):
        for white in (True, False):
            players = []
            try:
                players.append(candidate_factory())
                players.append(incumbent_factory())
                if not white:
                    players.reverse()
                row = play_game(players, opening, config, directory / f'pair_{pair:04d}_{int(white)}.json', pair, white, deadline)
            finally:
                for player in players:
                    if hasattr(player, 'close'):
                        player.close()
            if row is None:
                report = evidence(rows, config.pairs, min_pairs, attempt=attempt)
                report['finished_games'] = len(rows)
                report.update(signature=signature, candidate=candidate_id, incumbent=incumbent_id)
                atomic_json(directory / 'report.json', report)
                return report
            rows.append(row)
            if progress:
                progress(len(rows), 2 * config.pairs)
    report = evidence(rows, config.pairs, min_pairs, attempt=attempt)
    report['finished_games'] = len(rows)
    report.update(signature=signature, candidate=candidate_id, incumbent=incumbent_id)
    atomic_json(directory / 'report.json', report)
    return report
