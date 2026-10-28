"""Configurable tapered evaluation; features are inspectable and evolvable.

Weights are (middlegame, endgame). No term contains a tactical move prescription.
"""
import json
import math
from pathlib import Path
import chess

DEFAULT_WEIGHTS = {
    'pawn': (100, 120), 'knight': (320, 300), 'bishop': (335, 330),
    'rook': (500, 520), 'queen': (900, 900), 'bishop_pair': (28, 42),
    'minor_imbalance': (8, 12), 'pawn_pst': (6, 11), 'minor_center': (9, 6),
    'rook_activity': (2, 4), 'queen_center': (2, 3), 'king_center': (-8, 14),
    'doubled': (-15, -20), 'isolated': (-12, -16), 'backward': (-10, -12),
    'connected': (5, 8), 'chain': (4, 6), 'passed': (15, 28), 'candidate': (6, 12),
    'mobility': (3, 4), 'development': (12, 0), 'center_control': (4, 2),
    'outpost': (16, 10), 'rook_open': (18, 12), 'rook_semiopen': (9, 6),
    'seventh': (12, 20), 'trapped': (-20, -10), 'shelter': (10, 0),
    'king_open': (-14, 0), 'king_pressure': (-3, -1), 'king_attackers': (-7, 0),
    'loose_piece': (-10, -6), 'weak_square': (-3, -1), 'weak_complex': (-2, 0),
    'space': (2, 0), 'coordination': (3, 2), 'blockade': (8, 14),
    'king_pawn_distance': (0, -3), 'tempo': (10, 10),
}
SCHEMA = 'tapered-features-v1'
CENTER = chess.BB_D4 | chess.BB_E4 | chess.BB_D5 | chess.BB_E5


def ahead_mask(color, rank):
    return (chess.BB_ALL << (8 * (rank + 1))) & chess.BB_ALL if color else (1 << (8 * rank)) - 1


def pawn_attacks(board, color):
    mask = 0
    for square in board.pieces(chess.PAWN, color):
        mask |= chess.BB_PAWN_ATTACKS[color][square]
    return mask


def features(board):
    result = {name: 0.0 for name in DEFAULT_WEIGHTS}
    phase = min(24, sum(len(board.pieces(pt, c)) * w for pt, w in ((2, 1), (3, 1), (4, 2), (5, 4)) for c in chess.COLORS)) / 24
    pawn_control = {c: pawn_attacks(board, c) for c in chess.COLORS}
    attacks = {c: 0 for c in chess.COLORS}
    for square, piece in board.piece_map().items():
        attacks[piece.color] |= board.attacks_mask(square)
    for color in chess.COLORS:
        side = {name: 0.0 for name in DEFAULT_WEIGHTS}
        own = board.occupied_co[color]
        pawns = board.pieces_mask(chess.PAWN, color)
        enemy_pawns = board.pieces_mask(chess.PAWN, not color)
        files = [chess.popcount(pawns & f) for f in chess.BB_FILES]
        passed_squares = []
        for pt, name in ((1, 'pawn'), (2, 'knight'), (3, 'bishop'), (4, 'rook'), (5, 'queen')):
            side[name] = len(board.pieces(pt, color))
        side['bishop_pair'] = int(side['bishop'] >= 2)
        # Context beyond linear material: minor surplus paired with a rook deficit.
        minor_delta = side['knight'] + side['bishop'] - len(board.pieces(chess.KNIGHT, not color)) - len(board.pieces(chess.BISHOP, not color))
        side['minor_imbalance'] = max(0, minor_delta) if side['rook'] < len(board.pieces(chess.ROOK, not color)) else 0
        side['doubled'] = sum(max(0, n - 1) for n in files)
        for square in board.pieces(chess.PAWN, color):
            f, r = chess.square_file(square), chess.square_rank(square)
            rr = r if color else 7 - r
            adjacent = (chess.BB_FILES[f - 1] if f else 0) | (chess.BB_FILES[f + 1] if f < 7 else 0)
            forward = ahead_mask(color, r)
            isolated = not (pawns & adjacent)
            passed = not (enemy_pawns & (adjacent | chess.BB_FILES[f]) & forward)
            side['isolated'] += int(isolated)
            side['pawn_pst'] += rr - 1
            # Connected means adjacent on the same rank; chain means pawn-defended.
            side['connected'] += int(bool(pawns & adjacent & chess.BB_RANKS[r]))
            side['chain'] += int(bool(pawn_control[color] & chess.BB_SQUARES[square]))
            if passed:
                side['passed'] += (rr + 1) ** 2 / 16
                passed_squares.append(square)
            elif not (enemy_pawns & chess.BB_FILES[f] & forward):
                support = chess.popcount(pawns & adjacent & ~forward)
                opposition = chess.popcount(enemy_pawns & adjacent & forward)
                side['candidate'] += int(support >= opposition and support > 0)
            advance = square + (8 if color else -8)
            if (not isolated and not passed and 0 <= advance < 64
                    and not (pawns & adjacent & ~forward)
                    and pawn_control[not color] & chess.BB_SQUARES[advance]):
                side['backward'] += 1
        for square in chess.scan_forward(own):
            pt = board.piece_type_at(square)
            f, r = chess.square_file(square), chess.square_rank(square)
            rr = r if color else 7 - r
            center = 3.5 - (abs(f - 3.5) + abs(r - 3.5)) / 2
            control = board.attacks_mask(square)
            mobility = chess.popcount(control & ~own & ~pawn_control[not color])
            if pt not in (chess.PAWN, chess.KING):
                side['mobility'] += mobility
                side['trapped'] += int(mobility <= 1)
                defended = board.attackers_mask(color, square)
                side['coordination'] += int(chess.popcount(defended) >= 2)
                side['loose_piece'] += int(not defended and bool(board.attackers_mask(not color, square)))
            if pt in (chess.KNIGHT, chess.BISHOP):
                side['minor_center'] += center
                side['development'] += int(rr > 0)
                front = square + (8 if color else -8)
                # A minor blocking an enemy pawn's forward square.
                if 0 <= front < 64 and board.piece_at(front) == chess.Piece(chess.PAWN, not color):
                    side['blockade'] += 1
            if pt == chess.KNIGHT and rr >= 3 and pawn_control[color] & chess.BB_SQUARES[square]:
                adjacent = (chess.BB_FILES[f - 1] if f else 0) | (chess.BB_FILES[f + 1] if f < 7 else 0)
                side['outpost'] += int(not (enemy_pawns & adjacent & ahead_mask(color, r)))
            if pt == chess.ROOK:
                side['rook_activity'] += rr
                side['seventh'] += int(rr == 6)
                if not files[f]:
                    side['rook_semiopen' if enemy_pawns & chess.BB_FILES[f] else 'rook_open'] += 1
            if pt == chess.QUEEN:
                side['queen_center'] += center
            if pt == chess.KING:
                side['king_center'] += center
        king = board.king(color)
        if king is not None:
            kf, kr = chess.square_file(king), chess.square_rank(king)
            ring = chess.BB_KING_ATTACKS[king]
            shelter_rank = kr + (1 if color else -1)
            for f in range(max(0, kf - 1), min(8, kf + 2)):
                side['king_open'] += int(not files[f])
                if 0 <= shelter_rank < 8:
                    side['shelter'] += int(bool(pawns & chess.BB_SQUARES[chess.square(f, shelter_rank)]))
            for sq in chess.scan_forward(board.occupied_co[not color]):
                attacked = board.attacks_mask(sq) & ring
                if attacked:
                    side['king_attackers'] += 1
                    side['king_pressure'] += chess.popcount(attacked)
            # Color-complex weakness is confined to the king ring; weak_square excludes it.
            for sq in chess.scan_forward(ring & attacks[not color] & ~pawn_control[color]):
                same_color = chess.BB_LIGHT_SQUARES if chess.BB_LIGHT_SQUARES & chess.BB_SQUARES[sq] else chess.BB_DARK_SQUARES
                side['weak_complex'] += int(bool(board.pieces_mask(chess.BISHOP, not color) & same_color))
            home_half = (chess.BB_RANK_2 | chess.BB_RANK_3 | chess.BB_RANK_4) if color else (chess.BB_RANK_5 | chess.BB_RANK_6 | chess.BB_RANK_7)
            side['weak_square'] = chess.popcount(attacks[not color] & home_half & ~pawn_control[color] & ~ring & ~board.occupied)
            targets = passed_squares or list(board.pieces(chess.PAWN, color))
            if targets:
                side['king_pawn_distance'] = min(chess.square_distance(king, sq) for sq in targets)
        enemy_half = (chess.BB_RANK_5 | chess.BB_RANK_6) if color else (chess.BB_RANK_3 | chess.BB_RANK_4)
        side['space'] = chess.popcount(attacks[color] & enemy_half & ~pawn_control[not color] & ~board.occupied)
        side['center_control'] = chess.popcount(attacks[color] & CENTER)
        for name, value in side.items():
            result[name] += value if color else -value
    result['tempo'] = 1 if board.turn else -1
    return result, phase


class ClassicalEvaluator:
    def __init__(self, weights=None):
        self.weights = dict(DEFAULT_WEIGHTS)
        if weights:
            if set(weights) - set(self.weights):
                raise ValueError('Unknown evaluation genes')
            self.weights.update({k: tuple(map(float, v)) for k, v in weights.items()})
        if any(len(v) != 2 for v in self.weights.values()):
            raise ValueError('Each evaluation gene needs MG and EG weights')
        if any(not math.isfinite(x) for pair in self.weights.values() for x in pair):
            raise ValueError('Evaluation weights must be finite')

    def explain(self, board):
        values, phase = features(board)
        terms = {name: value * (phase * self.weights[name][0] + (1 - phase) * self.weights[name][1]) for name, value in values.items()}
        return {'phase': phase, 'features_white': values, 'terms_white': terms,
                'score': sum(terms.values()) * (1 if board.turn else -1)}

    def __call__(self, board):
        return self.explain(board)['score']

    def save(self, path):
        Path(path).write_text(json.dumps({'schema': SCHEMA, 'weights': self.weights}, indent=2) + '\n')

    @classmethod
    def load(cls, path):
        data = json.loads(Path(path).read_text())
        if data['schema'] != SCHEMA:
            raise ValueError('Incompatible evaluation schema')
        return cls(data['weights'])


class CallableEvaluator:
    def __init__(self, function):
        self.function = function

    def __call__(self, board):
        return float(self.function(board))


class HybridEvaluator:
    """Blend scores; do not add two complete evaluations and double-count material."""
    def __init__(self, classical, neural, neural_fraction=0.5):
        if not 0 <= neural_fraction <= 1:
            raise ValueError('neural_fraction must be between zero and one')
        self.classical, self.neural, self.fraction = classical, neural, neural_fraction

    def __call__(self, board):
        return (1 - self.fraction) * self.classical(board) + self.fraction * self.neural(board)

    def reset(self, board):
        for evaluator in (self.classical, self.neural):
            if hasattr(evaluator, 'reset'):
                evaluator.reset(board)

    def push(self, board, before, after):
        for evaluator in (self.classical, self.neural):
            if hasattr(evaluator, 'push'):
                evaluator.push(board, before, after)

    def pop(self):
        for evaluator in (self.classical, self.neural):
            if hasattr(evaluator, 'pop'):
                evaluator.pop()
