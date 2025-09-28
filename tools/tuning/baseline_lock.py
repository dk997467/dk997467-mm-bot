import argparse
import hashlib
import json
import os
import sys
from datetime import datetime, timezone
from glob import glob


def _read_ascii(path: str) -> str:
    try:
        with open(path, 'r', encoding='ascii') as f:
            return f.read()
    except Exception:
        return ''


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _sha256_text(s: str) -> str:
    return _sha256_bytes(s.encode('ascii', errors='ignore'))


def _atomic_write_json(path: str, obj: dict) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + '.tmp'
    with open(tmp, 'w', encoding='ascii', newline='') as f:
        json.dump(obj, f, ensure_ascii=True, sort_keys=True, separators=(',', ':'))
        f.write('\n')
        f.flush(); os.fsync(f.fileno())
    if os.path.exists(path):
        os.replace(tmp, path)
    else:
        os.rename(tmp, path)


def _cfg_describe_and_hash(config_path: str) -> tuple[str, str]:
    # Try to use AppConfig.describe() if available
    try:
        from src.common.config import ConfigLoader, cfg_hash_sanitized
        loader = ConfigLoader(config_path)
        app = loader.load()
        desc = app.describe()
        h = cfg_hash_sanitized(app)
        # normalize to ASCII and trailing \n
        if not desc.endswith('\n'):
            desc = desc + '\n'
        return desc, str(h)
    except Exception:
        # Fallback: use normalized config text
        txt = _read_ascii(config_path)
        # Normalize line endings and strip trailing spaces for determinism
        txt = txt.replace('\r\n', '\n').replace('\r', '\n')
        lines = [line.rstrip() for line in txt.split('\n')]
        desc = '\n'.join(lines) + ('\n' if lines else '\n')
        return desc, _sha256_text(desc)


def _head(text: str, max_lines: int = 20, max_chars: int = 2000) -> str:
    lines = text.split('\n')[:max_lines]
    head = '\n'.join(lines)
    if len(head) > max_chars:
        head = head[:max_chars]
    return head


def _list_tool_files() -> list[str]:
    files = []
    for path in sorted(glob('tools/**/*.py', recursive=True)):
        if '\\venv\\' in path or '/venv/' in path:
            continue
        files.append(path.replace('\\', '/'))
    return files


def _list_prom_rules() -> list[str]:
    paths = sorted(glob('monitoring/alerts/*.yml'))
    return [p.replace('\\', '/') for p in paths]


def _runtime_utc_iso() -> str:
    iso = os.environ.get('MM_FREEZE_UTC_ISO')
    if iso:
        return iso
    return '1970-01-01T00:00:00Z'


def build_lock(config_path: str = 'config.yaml') -> dict:
    cfg_desc, cfg_hash = _cfg_describe_and_hash(config_path)
    overlays = {}
    for name in ('tools/tuning/overlay_profile.yaml', 'tools/tuning/overlay_prev.yaml'):
        if os.path.exists(name):
            txt = _read_ascii(name)
            overlays[os.path.basename(name)] = {
                'sha256': _sha256_text(txt),
                'head': _head(txt),
            }
    tools_meta = {
        'git_sha': os.environ.get('GIT_SHA', 'unknown'),
        'runtime_version': '0.1.0',
        'files': [],
    }
    for p in _list_tool_files():
        try:
            b = open(p, 'rb').read()
        except Exception:
            b = b''
        tools_meta['files'].append({'path': p, 'sha256': _sha256_bytes(b)})
    # ensure stable order
    tools_meta['files'] = sorted(tools_meta['files'], key=lambda x: x['path'])

    prom = []
    for p in _list_prom_rules():
        try:
            b = open(p, 'rb').read()
        except Exception:
            b = b''
        prom.append({'path': p, 'sha256': _sha256_bytes(b)})

    lock = {
        'cfg': {
            'describe': cfg_desc,
            'sha256': cfg_hash,
        },
        'overlays': overlays,
        'tools': tools_meta,
        'prom_rules': prom,
        'runtime': {
            'utc': _runtime_utc_iso(),
            'version': '0.1.0',
        },
    }
    # compute lock hash deterministically (without the lock hash itself)
    payload = json.dumps(lock, ensure_ascii=True, sort_keys=True, separators=(',', ':')).encode('ascii')
    lock['lock_sha256'] = hashlib.sha256(payload).hexdigest()
    return lock


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument('--config', default='config.yaml')
    ap.add_argument('--out', default='artifacts/BASELINE_LOCK.json')
    args = ap.parse_args(argv)

    lock = build_lock(args.config)
    _atomic_write_json(args.out, lock)
    print('BASELINE_LOCK', args.out, lock.get('lock_sha256', ''))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())


