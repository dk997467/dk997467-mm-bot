import json
import os
from typing import Any, Dict

from .schema import build_record, json_line


def _fsync_dir(path: str) -> None:
    d = os.path.dirname(path) or '.'
    try:
        fd = os.open(d, os.O_DIRECTORY)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)
    except Exception:
        pass


def append_record(path: str, ts: str, kind: str, symbol: str, fields: Dict[str, Any]) -> str:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    prev_sha = 'GENESIS'
    try:
        with open(path, 'rb') as f:
            last = b''
            for line in f:
                if line:
                    last = line
            if last:
                try:
                    rec = json.loads(last.decode('ascii', 'ignore'))
                    prev_sha = str(rec.get('sha256', prev_sha))
                except Exception:
                    prev_sha = 'GENESIS'
    except FileNotFoundError:
        pass

    rec = build_record(ts, kind, symbol, fields, prev_sha)
    line = json_line(rec)
    # Append-only with fsync
    with open(path, 'ab', buffering=0) as f:
        f.write(line.encode('ascii'))
        f.flush(); os.fsync(f.fileno())
    _fsync_dir(path)
    return rec['sha256']


