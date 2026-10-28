"""python-chess rules with incremental Polyglot hashing and repetition context."""
from collections import Counter
import chess
import chess.polyglot

MASK = (1 << 64) - 1
HASHER = chess.polyglot.ZobristHasher(chess.polyglot.POLYGLOT_RANDOM_ARRAY)


def mix(value):
    value = (value ^ (value >> 30)) * 0xbf58476d1ce4e5b9 & MASK
    value = (value ^ (value >> 27)) * 0x94d049bb133111eb & MASK
    return value ^ (value >> 31)


def piece_hash(piece, square):
    if piece is None:
        return 0
    return HASHER.array[64 * ((piece.piece_type - 1) * 2 + int(piece.color)) + square]


def metadata_hash(board):
    return HASHER.hash_castling(board) ^ HASHER.hash_ep_square(board) ^ HASHER.hash_turn(board)


def repetition_hash(board, polyglot_hash):
    # Polyglot includes pseudo-legal EP; repetition depends on legal EP rights.
    if board.ep_square is not None and not board.has_legal_en_passant():
        return polyglot_hash ^ HASHER.hash_ep_square(board)
    return polyglot_hash


class Position:
    def __init__(self, board, evaluator=None):
        if board.chess960:
            raise ValueError('This search supports standard chess, not Chess960')
        self.board = board.copy(stack=True)
        self.hash = chess.polyglot.zobrist_hash(board)
        self.counts = Counter()
        history = board.copy(stack=True)
        while True:
            self.counts[repetition_hash(history, chess.polyglot.zobrist_hash(history))] += 1
            if not history.move_stack:
                break
            history.pop()
        self.context = 0
        for key, count in self.counts.items():
            self.context ^= mix(key ^ mix(count))
        self.stack = []
        self.null_depth = 0
        self.evaluator = evaluator
        if evaluator and hasattr(evaluator, 'reset'):
            evaluator.reset(self.board)

    def _count(self, key, delta):
        old = self.counts.get(key, 0)
        if old:
            self.context ^= mix(key ^ mix(old))
        count = old + delta
        if count:
            self.counts[key] = count
            self.context ^= mix(key ^ mix(count))
        else:
            del self.counts[key]

    def push(self, move):
        board = self.board
        affected = {move.from_square, move.to_square} if move else set()
        if move and board.is_en_passant(move):
            affected.add(move.to_square - 8 if board.turn else move.to_square + 8)
        if move and board.is_castling(move):
            rank = 0 if board.turn else 7
            affected.update((chess.square(7 if move.to_square > move.from_square else 0, rank),
                             chess.square(5 if move.to_square > move.from_square else 3, rank)))
        before = {sq: board.piece_at(sq) for sq in affected}
        previous = (self.hash, self.null_depth)
        key = self.hash ^ metadata_hash(board)
        for sq, piece in before.items():
            key ^= piece_hash(piece, sq)
        board.push(move)
        after = {sq: board.piece_at(sq) for sq in affected}
        for sq, piece in after.items():
            key ^= piece_hash(piece, sq)
        self.hash = key ^ metadata_hash(board)
        if not move:
            self.null_depth += 1
        if not self.null_depth:
            self._count(repetition_hash(board, self.hash), 1)
        self.stack.append(previous)
        if self.evaluator and hasattr(self.evaluator, 'push'):
            self.evaluator.push(board, before, after)

    def pop(self):
        if self.evaluator and hasattr(self.evaluator, 'pop'):
            self.evaluator.pop()
        if not self.null_depth:
            self._count(repetition_hash(self.board, self.hash), -1)
        self.hash, self.null_depth = self.stack.pop()
        self.board.pop()

    def drawn(self):
        return self.board.is_insufficient_material() or (not self.null_depth and (
            self.board.halfmove_clock >= 100 or self.counts.get(repetition_hash(self.board, self.hash), 0) >= 3))

    def key(self):
        return self.hash, self.board.halfmove_clock, self.context, self.null_depth
