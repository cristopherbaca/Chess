"""Experimental king-bucket sparse evaluator with incremental CPU accumulators.

This is an original small NNUE-style experiment, not a Stockfish network or a
conversion of the existing 14.8M dense champion. Training requires labeled data.
"""
import hashlib
import json
import os
from pathlib import Path
import chess
import numpy as np

SCHEMA = 'king-buckets-16-v1'
FEATURES = 16 * 12 * 64


def bucket(board, perspective):
    square = board.king(perspective)
    if square is None:
        raise ValueError('A king is required for each perspective')
    square = square if perspective else square ^ 56
    return chess.square_file(square) // 2 + 4 * (chess.square_rank(square) // 2)


def feature(square, piece, perspective, king_bucket):
    oriented = square if perspective else square ^ 56
    plane = piece.piece_type - 1 + (0 if piece.color == perspective else 6)
    return king_bucket * 768 + plane * 64 + oriented


def active_features(board, perspective):
    group = bucket(board, perspective)
    return [feature(sq, piece, perspective, group) for sq, piece in board.piece_map().items()]


def identity(board):
    return (board.pawns, board.knights, board.bishops, board.rooks, board.queens,
            board.kings, board.occupied_co[0], board.occupied_co[1])


class SparseEvaluator:
    def __init__(self, w1, b1, output, bias=0.0, scale=1.0, metadata=None):
        self.w1, self.b1 = np.asarray(w1), np.asarray(b1)
        self.output = np.asarray(output, dtype=np.float32)
        self.bias, self.scale = float(bias), float(scale)
        self.metadata = metadata or {}
        if self.w1.ndim != 2 or self.w1.shape[0] != FEATURES or self.b1.shape != (self.w1.shape[1],) or self.output.shape != (2 * self.w1.shape[1],):
            raise ValueError('Invalid sparse-network dimensions')
        if self.scale <= 0 or not all(np.isfinite(x).all() for x in (self.w1, self.b1, self.output, self.scale, self.bias)):
            raise ValueError('Invalid sparse-network weights')
        self.acc = None
        self.stack = []
        self.refreshes = self.incremental_updates = 0

    @classmethod
    def initial(cls, hidden=64, seed=42):
        rng = np.random.default_rng(seed)
        return cls(rng.normal(0, .03, (FEATURES, hidden)).astype(np.float32),
                   np.zeros(hidden, np.float32), rng.normal(0, .1, 2 * hidden).astype(np.float32))

    def _refresh(self, board, perspective):
        self.refreshes += 1
        dtype = np.int32 if self.w1.dtype.kind in 'iu' else np.float32
        return self.b1.astype(dtype) + self.w1[active_features(board, perspective)].sum(axis=0, dtype=dtype)

    def reset(self, board):
        self.acc = [self._refresh(board, False), self._refresh(board, True)]
        self.buckets = [bucket(board, False), bucket(board, True)]
        self.key = identity(board)
        self.stack = []

    def push(self, board, before, after):
        self.stack.append(([a.copy() for a in self.acc], list(self.buckets), self.key))
        for perspective in chess.COLORS:
            group = bucket(board, perspective)
            if group != self.buckets[perspective]:
                self.acc[perspective] = self._refresh(board, perspective)
                self.buckets[perspective] = group
            else:
                for square, piece in before.items():
                    if piece:
                        self.acc[perspective] -= self.w1[feature(square, piece, perspective, group)]
                for square, piece in after.items():
                    if piece:
                        self.acc[perspective] += self.w1[feature(square, piece, perspective, group)]
                self.incremental_updates += 1
        self.key = identity(board)

    def pop(self):
        self.acc, self.buckets, self.key = self.stack.pop()

    def __call__(self, board):
        if self.acc is None or self.key != identity(board):
            self.reset(board)
        active = np.concatenate((self.acc[board.turn], self.acc[not board.turn])).astype(np.float32) * self.scale
        return float(np.clip(active, 0, 1) @ self.output + self.bias)

    def quantized(self):
        if self.w1.dtype.kind in 'iu':
            return self
        scale = max(float(np.max(np.abs(self.w1))), float(np.max(np.abs(self.b1))), 1e-6) / 32767
        return SparseEvaluator(np.rint(self.w1 / scale).astype(np.int16),
                               np.rint(self.b1 / scale).astype(np.int32), self.output.copy(),
                               self.bias, scale, {**self.metadata, 'quantization': 'int16 first layer; int32 accumulator; float output'})

    def save(self, path):
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(path.suffix + '.tmp')
        with temporary.open('wb') as handle:
            np.savez_compressed(handle, w1=self.w1, b1=self.b1, output=self.output,
                                bias=self.bias, scale=self.scale,
                                metadata=json.dumps({'schema': SCHEMA, **self.metadata}))
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)

    @classmethod
    def load(cls, path):
        with np.load(path, allow_pickle=False) as data:
            metadata = json.loads(str(data['metadata']))
            if metadata['schema'] != SCHEMA:
                raise ValueError('Incompatible neural feature schema')
            return cls(data['w1'], data['b1'], data['output'], float(data['bias']), float(data['scale']), metadata)


def train_labels(data_path, output_dir, epochs=10, batch_size=64, hidden=64, seed=42, resume=True, progress=None):
    """Train from JSONL {fen, game_id, cp_white?, result_white?}; split by game.

    Saves resumable optimizer/RNG state and best held-out-loss network each epoch.
    Validation loss is not a match-based champion promotion decision.
    """
    import torch
    if epochs < 1 or batch_size < 1:
        raise ValueError('Positive epochs and batch size required')
    rows = [json.loads(line) for line in Path(data_path).read_text().splitlines() if line.strip()]
    games = sorted({str(row['game_id']) for row in rows})
    if len(games) < 2:
        raise ValueError('At least two independent game_id groups are required')
    rng = np.random.default_rng(seed)
    rng.shuffle(games)
    heldout = set(games[:max(1, len(games) // 5)])
    explicit = any('split' in row for row in rows)
    if explicit and any(row.get('split') not in ('train', 'validation', 'test') for row in rows):
        raise ValueError('Every row needs an explicit train/validation/test split')
    groups, positions = {}, {}
    encoded = []
    for row in rows:
        board = chess.Board(row['fen'])
        if not board.is_valid():
            raise ValueError('Invalid training FEN')
        split = row['split'] if explicit else ('validation' if str(row['game_id']) in heldout else 'train')
        group = str(row['game_id'])
        if group in groups and groups[group] != split:
            raise ValueError('A game_id cannot cross dataset splits')
        groups[group] = split
        if explicit:
            key = min(' '.join(board.fen().split()[:4]), ' '.join(board.mirror().fen().split()[:4]))
            if key in positions and positions[key] != split:
                raise ValueError('An identical or mirrored position crosses dataset splits')
            positions[key] = split
        targets = []
        if 'cp_white' in row:
            targets.append(float(np.tanh(float(row['cp_white']) / 400)))
        if 'result_white' in row:
            if not 0 <= float(row['result_white']) <= 1:
                raise ValueError('result_white must be between zero and one')
            targets.append(2 * float(row['result_white']) - 1)
        if not targets or not np.isfinite(targets).all():
            raise ValueError('Each row needs a finite label')
        target = sum(targets) / len(targets) * (1 if board.turn else -1)
        encoded.append((active_features(board, board.turn), active_features(board, not board.turn), target, split))
    training = [r for r in encoded if r[3] == 'train']
    validation = [r for r in encoded if r[3] == 'validation']
    if not training or not validation:
        raise ValueError('Nonempty training and validation splits are required')
    heldout = {g for g, split in groups.items() if split == 'validation'}
    torch.manual_seed(seed)
    initial = SparseEvaluator.initial(hidden, seed)
    w1 = torch.nn.Parameter(torch.from_numpy(initial.w1.copy()))
    b1 = torch.nn.Parameter(torch.from_numpy(initial.b1.copy()))
    output = torch.nn.Parameter(torch.from_numpy(initial.output.copy()))
    bias = torch.nn.Parameter(torch.tensor(0.0))
    params = [w1, b1, output, bias]
    optimizer = torch.optim.Adam(params, lr=.003)
    directory = Path(output_dir)
    directory.mkdir(parents=True, exist_ok=True)
    checkpoint = directory / 'training.pt'
    signature = hashlib.sha256(Path(data_path).read_bytes() + f'{SCHEMA}:batched-v2:{hidden}:{seed}:{batch_size}'.encode()).hexdigest()
    start, best, history = 0, float('inf'), []
    if resume and checkpoint.exists():
        pack = torch.load(checkpoint, map_location='cpu', weights_only=True)
        if pack['signature'] != signature:
            raise ValueError('Dataset or training configuration changed; use another output directory')
        for parameter, saved in zip(params, pack['params']):
            parameter.data.copy_(saved)
        optimizer.load_state_dict(pack['optimizer'])
        torch.set_rng_state(pack['torch_rng'])
        rng.bit_generator.state = json.loads(pack['numpy_rng'])
        start, best, history = pack['epoch'], pack['best'], pack['history']

    def loss(batch):
        indices, offsets = [], []
        for own, opponent, _, _ in batch:
            for features in (own, opponent):
                offsets.append(len(indices))
                indices.extend(features)
        accum = torch.nn.functional.embedding_bag(torch.tensor(indices, dtype=torch.long), w1,
                    torch.tensor(offsets, dtype=torch.long), mode='sum') + b1
        predictions = torch.clamp(accum, 0, 1).reshape(len(batch), 2 * hidden) @ output + bias
        target = torch.tensor([r[2] for r in batch], dtype=torch.float32)
        return torch.mean((torch.tanh(predictions / 400) - target) ** 2)

    for epoch in range(start, epochs):
        order = rng.permutation(len(training))
        for begin in range(0, len(order), batch_size):
            batch = [training[int(i)] for i in order[begin:begin + batch_size]]
            optimizer.zero_grad()
            value = loss(batch)
            value.backward()
            optimizer.step()
        with torch.no_grad():
            valid_loss = sum(float(loss(validation[i:i + batch_size])) * len(validation[i:i + batch_size])
                             for i in range(0, len(validation), batch_size)) / len(validation)
        history.append({'epoch': epoch + 1, 'validation_loss': valid_loss})
        if progress:
            progress(dict(history[-1]))
        if valid_loss < best:
            best = valid_loss
            SparseEvaluator(w1.detach().numpy().copy(), b1.detach().numpy().copy(), output.detach().numpy().copy(),
                            float(bias.detach()), metadata={'epoch': epoch + 1, 'validation_loss': best,
                            'dataset_sha256': hashlib.sha256(Path(data_path).read_bytes()).hexdigest()}).save(directory / 'best_validation.npz')
        temporary = checkpoint.with_suffix('.tmp')
        with temporary.open('wb') as handle:
            torch.save({'signature': signature, 'epoch': epoch + 1, 'best': best, 'history': history,
                        'params': [p.detach() for p in params], 'optimizer': optimizer.state_dict(),
                        'torch_rng': torch.get_rng_state(), 'numpy_rng': json.dumps(rng.bit_generator.state)}, handle)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, checkpoint)
        (directory / 'history.json').write_text(json.dumps(history, indent=2) + '\n')
    return {'epochs': epochs, 'best_validation_loss': best, 'training_positions': len(training),
            'validation_positions': len(validation), 'test_positions_excluded': sum(r[3] == 'test' for r in encoded),
            'heldout_game_ids': sorted(heldout), 'history': history}
