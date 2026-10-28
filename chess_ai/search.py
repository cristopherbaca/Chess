"""Instrumented, bounded negamax; selective heuristics are individually switchable."""
from collections import Counter, OrderedDict
from dataclasses import dataclass, field
import math
import threading
import time
import chess
from .board import Position

MATE = 30000
MATE_BOUND = 29000
VALUES = (0, 100, 320, 335, 500, 900, 20000)


@dataclass
class SearchOptions:
    pvs: bool = True
    aspiration: bool = True
    see: bool = True
    countermove: bool = True
    null_move: bool = False
    lmr: bool = False
    futility: bool = False
    check_extensions: bool = False
    tt_capacity: int = 32768
    qdepth: int = 8
    max_ply: int = 96


@dataclass
class SearchResult:
    move: object
    score: float
    depth: int
    pv: list
    stats: dict


class Stopped(Exception):
    pass


def see(board, move):
    """Legal least-valuable-attacker exchange estimate, including EP/promotions.

    This is an ordering estimate, not a proof that a capture can be pruned.
    Legal recaptures exclude pinned attackers and illegal king captures.
    """
    position = board.copy(stack=False)
    target = move.to_square

    def gain(m):
        victim = position.piece_type_at(m.to_square)
        result = VALUES[victim or 0] + (100 if position.is_en_passant(m) else 0)
        return result + (VALUES[m.promotion] - 100 if m.promotion else 0)

    def recapture(depth):
        if depth >= 16:
            return 0
        captures = [m for m in position.generate_legal_captures() if m.to_square == target]
        if not captures:
            return 0
        m = min(captures, key=lambda m: (VALUES[position.piece_type_at(m.from_square)], m.uci()))
        score = gain(m)
        position.push(m)
        score -= recapture(depth + 1)
        position.pop()
        return max(0, score)

    first = gain(move)
    position.push(move)
    return first - recapture(0)


class SearchEngine:
    def __init__(self, evaluator, options=None):
        self.evaluator = evaluator
        self.options = options or SearchOptions()
        self.tt = OrderedDict()
        self.generation = 0

    def _tick(self, quiescent=False):
        if self.stats['nodes'] >= self.node_limit or self.stop.is_set() or time.monotonic() >= self.deadline:
            raise Stopped()
        self.stats['nodes'] += 1
        self.stats['qnodes'] += int(quiescent)

    def _moves(self):
        started = time.perf_counter()
        result = list(self.position.board.legal_moves)
        self.stats['movegen_seconds'] += time.perf_counter() - started
        return result

    def _evaluate(self):
        key = (self.position.hash, self.position.board.halfmove_clock)
        if key in self.cache:
            self.stats['eval_cache_hits'] += 1
            return self.cache[key]
        started = time.perf_counter()
        score = float(self.evaluator(self.position.board))
        if not math.isfinite(score):
            raise ValueError('Evaluator returned a nonfinite value')
        # Integer centipawns make unit-width PVS windows well defined.
        score = float(round(max(-MATE_BOUND + 1, min(MATE_BOUND - 1, score))))
        self.stats['eval_seconds'] += time.perf_counter() - started
        self.stats['eval_calls'] += 1
        if len(self.cache) >= 16384:
            self.cache.pop(next(iter(self.cache)))
        self.cache[key] = score
        return score

    def _order(self, moves, preferred, ply):
        board = self.position.board
        previous = board.peek() if board.move_stack else None
        counter = self.counters.get((previous.from_square, previous.to_square)) if previous else None

        def priority(move):
            if move == preferred:
                return 10**9
            if board.is_capture(move) or move.promotion:
                victim = board.piece_type_at(move.to_square) or (1 if board.is_en_passant(move) else 0)
                tactical = 16 * VALUES[victim] - VALUES[board.piece_type_at(move.from_square)]
                exchange = see(board, move) if self.options.see else 0
                return (10**6 if exchange >= 0 else -100000) + tactical + VALUES[move.promotion or 0]
            return (500000 if move in self.killers.get(ply, []) else 0) + (
                250000 if self.options.countermove and move == counter else 0) + self.history[(board.turn, move)]
        return sorted(moves, key=priority, reverse=True)

    def _store(self, key, depth, score, flag, move, ply):
        capacity = self.options.tt_capacity
        if capacity <= 0:
            return
        old = self.tt.get(key)
        if old and old[0] > depth and old[4] == self.generation and flag != 'exact':
            return
        if score > MATE_BOUND:
            score += ply
        elif score < -MATE_BOUND:
            score -= ply
        if key not in self.tt and len(self.tt) >= capacity:
            self.tt.popitem(last=False)
        self.tt[key] = (depth, score, flag, move, self.generation)
        self.tt.move_to_end(key)

    def _qsearch(self, alpha, beta, ply, qdepth=0):
        self._tick(True)
        board = self.position.board
        moves = self._moves()
        checked = board.is_check()
        if not moves:
            return -MATE + ply if checked else 0
        if self.position.drawn():
            return 0
        if ply >= self.options.max_ply:
            return 0 if checked else self._evaluate()
        if not checked:
            stand = self._evaluate()
            if stand >= beta:
                return stand
            alpha = max(alpha, stand)
            if qdepth >= self.options.qdepth:
                return alpha
            moves = [m for m in moves if board.is_capture(m) or m.promotion]
        for move in self._order(moves, None, ply):
            self.position.push(move)
            try:
                score = -self._qsearch(-beta, -alpha, ply + 1, qdepth + 1)
            finally:
                self.position.pop()
            if score >= beta:
                return score
            alpha = max(alpha, score)
        return alpha

    def _negamax(self, depth, alpha, beta, ply, allow_null=True, extensions=0):
        self.pv[ply] = []
        board = self.position.board
        checked = board.is_check()
        if self.options.check_extensions and checked and extensions < 2 and depth > 0:
            depth += 1
            extensions += 1
            self.stats['extensions'] += 1
        if depth <= 0:
            return self._qsearch(alpha, beta, ply)
        self._tick()
        moves = self._moves()
        if not moves:
            return -MATE + ply if checked else 0
        if self.position.drawn():
            return 0
        if ply >= self.options.max_ply:
            return 0 if checked else self._evaluate()
        original_alpha = alpha
        key = self.position.key()
        self.stats['tt_probes'] += 1
        entry = self.tt.get(key)
        preferred = entry[3] if entry else None
        if entry:
            self.stats['tt_hits'] += 1
            value = entry[1] - ply if entry[1] > MATE_BOUND else entry[1] + ply if entry[1] < -MATE_BOUND else entry[1]
            if ply and entry[0] >= depth and (entry[2] == 'exact' or entry[2] == 'lower' and value >= beta or entry[2] == 'upper' and value <= alpha):
                if preferred in moves:
                    self.pv[ply] = [preferred]
                return value
        pv_node = beta - alpha > 1
        static = None
        # Pawn/minor endgames, check and mate-score windows never use null pruning.
        phase = sum(len(board.pieces(pt, c)) * weight for pt, weight in ((2, 1), (3, 1), (4, 2), (5, 4)) for c in chess.COLORS)
        if (self.options.null_move and allow_null and ply and not pv_node and not checked and depth >= 3
                and phase > 12 and (board.pieces_mask(chess.ROOK, board.turn) | board.pieces_mask(chess.QUEEN, board.turn))
                and abs(beta) < MATE_BOUND):
            static = self._evaluate()
            if static >= beta:
                self.position.push(chess.Move.null())
                try:
                    value = -self._negamax(depth - 3, -beta, -beta + 1, ply + 1, False, extensions)
                finally:
                    self.position.pop()
                if value >= beta:
                    verified = depth < 6 or self._negamax(depth - 1, beta - 1, beta, ply, False, extensions) >= beta
                    if verified:
                        self.stats['null_cutoffs'] += 1
                        return beta
        best = -math.inf
        best_move = moves[0]
        for index, move in enumerate(self._order(moves, preferred, ply)):
            quiet = not board.is_capture(move) and not move.promotion
            gives_check = board.gives_check(move) if quiet and (self.options.lmr or self.options.futility) else False
            if (self.options.futility and index > 0 and depth == 1 and not pv_node and not checked
                    and quiet and not gives_check and abs(alpha) < MATE_BOUND):
                static = self._evaluate() if static is None else static
                if static + 150 <= alpha:
                    self.stats['futility_skips'] += 1
                    continue
            previous = board.peek() if board.move_stack else None
            self.position.push(move)
            try:
                reduced = self.options.lmr and index >= 4 and depth >= 3 and not pv_node and not checked and quiet and not gives_check and move != preferred
                if reduced:
                    self.stats['reductions'] += 1
                    score = -self._negamax(depth - 2, -alpha - 1, -alpha, ply + 1, True, extensions)
                else:
                    score = alpha + 1
                if not reduced or score > alpha:
                    if self.options.pvs and index > 0:
                        score = -self._negamax(depth - 1, -alpha - 1, -alpha, ply + 1, True, extensions)
                        if alpha < score < beta:
                            self.stats['pvs_researches'] += 1
                            score = -self._negamax(depth - 1, -beta, -alpha, ply + 1, True, extensions)
                    else:
                        score = -self._negamax(depth - 1, -beta, -alpha, ply + 1, True, extensions)
                child_pv = list(self.pv.get(ply + 1, []))
            finally:
                self.position.pop()
            if score > best:
                best, best_move = score, move
                self.pv[ply] = [move] + child_pv
            alpha = max(alpha, score)
            if alpha >= beta:
                self.stats['beta_cutoffs'] += 1
                if quiet:
                    self.killers[ply] = ([move] + [m for m in self.killers.get(ply, []) if m != move])[:2]
                    self.history[(board.turn, move)] += depth * depth
                    if previous:
                        self.counters[(previous.from_square, previous.to_square)] = move
                break
        flag = 'upper' if best <= original_alpha else 'lower' if best >= beta else 'exact'
        self._store(key, depth, best, flag, best_move, ply)
        return best

    def search(self, board, depth=64, seconds=1.0, nodes=1000000, stop=None, on_iteration=None):
        began = time.monotonic()
        self.deadline = began + max(0, float(seconds))
        self.node_limit = max(1, int(nodes))
        self.stop = stop if stop is not None else threading.Event()
        self.generation += 1
        self.stats = Counter(nodes=0, qnodes=0, eval_calls=0, eval_seconds=0., movegen_seconds=0.)
        self.cache = {}
        self.killers = {}
        self.history = Counter()
        self.counters = {}
        self.pv = {}
        self.position = Position(board, self.evaluator)
        legal = list(self.position.board.legal_moves)
        best = min(legal, key=lambda m: m.uci()) if legal else None
        score, completed, pv = 0.0, 0, []
        if not legal:
            score = -MATE if board.is_check() else 0
        elif not self.position.drawn():
            for current_depth in range(1, min(64, depth) + 1):
                delta = 35
                alpha, beta = (-MATE - 1, MATE + 1)
                if self.options.aspiration and current_depth > 1 and abs(score) < MATE_BOUND:
                    alpha, beta = score - delta, score + delta
                try:
                    while True:
                        value = self._negamax(current_depth, alpha, beta, 0)
                        if value <= alpha and alpha > -MATE - 1:
                            delta *= 2
                            alpha = max(-MATE - 1, value - delta)
                        elif value >= beta and beta < MATE + 1:
                            delta *= 2
                            beta = min(MATE + 1, value + delta)
                        else:
                            break
                        self.stats['aspiration_researches'] += 1
                    pv = self.pv[0]
                    best = pv[0] if pv else best
                    score, completed = value, current_depth
                    if on_iteration:
                        on_iteration(current_depth, score, list(pv), dict(self.stats))
                    if abs(score) > MATE_BOUND:
                        break
                except Stopped:
                    break
        self.stats['elapsed_seconds'] = time.monotonic() - began
        self.stats['tt_entries'] = len(self.tt)
        self.stats['nps'] = self.stats['nodes'] / max(1e-9, self.stats['elapsed_seconds'])
        self.stats['tt_hit_rate'] = self.stats['tt_hits'] / max(1, self.stats['tt_probes'])
        return SearchResult(best, float(score), completed, pv, dict(self.stats))
