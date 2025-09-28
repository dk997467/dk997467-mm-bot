"""
Artifacts helpers (stdlib-only).

Provides atomic JSON export for metrics/registry snapshots.
"""

from typing import Dict, Any
import json
import os
from pathlib import Path


def export_registry_snapshot(path: str, payload: Dict[str, Any]) -> None:
    """Atomically write a deterministic JSON snapshot to path.

    Rules:
    - ensure parent directory exists
    - json.dumps(..., ensure_ascii=True, sort_keys=True, separators=(",", ":")) and trailing \n
    - atomic write via tmp file + fsync + os.replace
    """
    sp = str(path)
    p = Path(sp)
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
    except Exception:
        # Best-effort; continue to attempt write
        pass

    data = json.dumps(payload or {}, ensure_ascii=True, sort_keys=True, separators=(",", ":")) + "\n"
    tmp = sp + ".tmp"

    # Write to temporary file with fsync
    with open(tmp, 'w', encoding='ascii', newline='\n') as f:
        f.write(data)
        f.flush()
        try:
            os.fsync(f.fileno())
        except Exception:
            pass

    # Replace atomically; fall back to rename if needed
    try:
        os.replace(tmp, sp)
    except Exception:
        os.rename(tmp, sp)

    # Best-effort fsync on directory to persist metadata
    try:
        dirfd = os.open(str(p.parent), os.O_DIRECTORY)
        try:
            os.fsync(dirfd)
        finally:
            os.close(dirfd)
    except Exception:
        pass


def write_json_atomic(path: str, payload: Dict[str, Any]) -> None:
    """Write deterministic JSON to path atomically with fsync.

    - ASCII only, sort_keys, compact separators, trailing \n
    - Create parent directories as needed
    - Write to tmp then os.replace; fsync file and directory
    """
    sp = str(path)
    p = Path(sp)
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
    except Exception:
        pass
    data = json.dumps(payload or {}, ensure_ascii=True, sort_keys=True, separators=(",", ":")) + "\n"
    tmp = sp + ".tmp"
    with open(tmp, 'w', encoding='ascii', newline='\n') as f:
        f.write(data)
        f.flush()
        try:
            os.fsync(f.fileno())
        except Exception:
            pass
    try:
        os.replace(tmp, sp)
    except Exception:
        os.rename(tmp, sp)
    try:
        dirfd = os.open(str(p.parent), os.O_DIRECTORY)
        try:
            os.fsync(dirfd)
        finally:
            os.close(dirfd)
    except Exception:
        pass

