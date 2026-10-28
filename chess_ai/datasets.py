"""Explicit, cached public labels for the optional Colab sparse-training stage."""
import hashlib
import io
import json
from pathlib import Path
import time
import chess
from .matches import atomic_json


def prepare_labels(path, count=20000, deadline=float('inf'), excluded=()):
    path = Path(path)
    if path.exists():
        return path
    import requests
    import zstandard
    path.parent.mkdir(parents=True, exist_ok=True)
    partial = path.with_suffix('.partial.jsonl')
    rows = [json.loads(line) for line in partial.read_text().splitlines() if line.strip()] if partial.exists() else []
    def key(board):
        return min(' '.join(board.fen().split()[:4]), ' '.join(board.mirror().fen().split()[:4]))
    seen = {key(chess.Board(row['fen'])) for row in rows} | set(excluded)
    url = 'https://database.lichess.org/lichess_db_eval.jsonl.zst'
    with requests.get(url, stream=True, timeout=(15, 60)) as response:
        response.raise_for_status()
        with zstandard.ZstdDecompressor().stream_reader(response.raw) as decoded, io.TextIOWrapper(decoded) as text:
            with partial.open('a') as handle:
                for line in text:
                    if len(rows) >= count or time.monotonic() >= deadline:
                        break
                    item = json.loads(line)
                    board = chess.Board(item['fen'] + ' 0 1')
                    position_key = key(board)
                    if not board.is_valid() or board.is_game_over() or position_key in seen:
                        continue
                    choices = [e for e in item['evals'] if e['depth'] >= 20 and e.get('knodes', 0) >= 100 and 'cp' in e['pvs'][0]]
                    if not choices:
                        continue
                    best = max(choices, key=lambda e: (e['depth'], e.get('knodes', 0)))
                    cp = best['pvs'][0]['cp']
                    if abs(cp) > 2000:
                        continue
                    digest = hashlib.sha256(position_key.encode()).hexdigest()
                    bucket = int(digest[:8], 16) % 100
                    row = {'fen': board.fen(), 'game_id': 'position-' + digest, 'cp_white': cp,
                           'split': 'train' if bucket < 70 else 'validation' if bucket < 85 else 'test',
                           'depth': best['depth'], 'knodes': best['knodes'], 'source': url}
                    handle.write(json.dumps(row)+'\n'); handle.flush()
                    rows.append(row); seen.add(position_key)
    if len(rows) < count:
        return None
    partial.replace(path)
    atomic_json(path.with_suffix('.manifest.json'), {'source': url, 'license': 'CC0-1.0', 'rows': len(rows),
                'sha256': hashlib.sha256(path.read_bytes()).hexdigest(),
                'note': 'Prefix sample, depth >=20, >=100k nodes. Exact/color-mirrored positions stay in one split; no source game IDs.'})
    return path
