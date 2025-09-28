#!/usr/bin/env python3
"""
Release bundle maker (stdlib-only, ASCII logs, deterministic manifest JSON, LF endings, atomic writes).

Inputs (if exist):
  - artifacts/PRE_LIVE_PACK.{json,md}
  - artifacts/READINESS_SCORE.{json,md}
  - artifacts/WEEKLY_ROLLUP.{json,md}
  - artifacts/KPI_GATE.{json,md}
  - artifacts/FULL_STACK_VALIDATION.{json,md}
  - docs/OPS_ONE_PAGER.md
  - docs/RUNBOOKS.md
  - docs/REPORTS.md
  - docs/REPORT_SOAK.md
  - monitoring/grafana/*.json
  - monitoring/promql/queries.md
  - docs/INDEX.md
  - CHANGELOG.md

Outputs:
  - artifacts/RELEASE_BUNDLE_manifest.json (deterministic)
  - dist/release_bundle/<UTC>-mm-bot.zip (stable file order; ASCII arcnames)

The script always exits with code 0 and prints RELEASE_BUNDLE=READY|PARTIAL.
"""

import hashlib
import json
import os
import sys
import zipfile
from datetime import datetime, timezone
from typing import Dict, List, Tuple


def _utc_iso() -> str:
    # Deterministic when MM_FREEZE_UTC_ISO is set
    return os.environ.get('MM_FREEZE_UTC_ISO') or datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')


def _sanitize_utc_for_fs(utc_iso: str) -> str:
    # Windows-safe file name: remove ':'
    return utc_iso.replace(':', '')


def _as_posix(path: str) -> str:
    return path.replace('\\', '/')


def _sha256sum(path: str) -> Tuple[str, int]:
    h = hashlib.sha256()
    total = 0
    with open(path, 'rb') as f:
        while True:
            chunk = f.read(1024 * 128)
            if not chunk:
                break
            h.update(chunk)
            total += len(chunk)
    return h.hexdigest(), total


def _write_json_atomic(path: str, data: Dict) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + '.tmp'
    # ASCII only, LF, sorted keys, compact separators
    with open(tmp, 'w', encoding='ascii', newline='') as f:
        json.dump(data, f, ensure_ascii=True, sort_keys=True, separators=(',', ':'))
        f.write('\n')
        f.flush(); os.fsync(f.fileno())
    if os.path.exists(path):
        os.replace(tmp, path)
    else:
        os.rename(tmp, path)


def _write_stamp(version: str, zip_path: str) -> None:
    try:
        sha, size = _sha256sum(zip_path)
    except Exception:
        sha, size = ('', 0)
    # git hash (short) best-effort
    gh = 'none'
    try:
        import subprocess
        r = subprocess.run(['git', 'rev-parse', '--short', 'HEAD'], capture_output=True, text=True)
        if r.returncode == 0:
            gh = (r.stdout or '').strip()
    except Exception:
        gh = 'none'
    # ts from now_iso
    from datetime import datetime, timezone
    ts = int(datetime.now(timezone.utc).timestamp())
    payload = {
        'version': version,
        'git_hash': gh,
        'bundle_sha256': sha,
        'ts': ts,
    }
    _write_json_atomic('artifacts/RELEASE_STAMP.json', payload)


def _gather_candidates() -> List[str]:
    candidates: List[str] = []
    # artifacts subset
    for base in (
        'artifacts/PRE_LIVE_PACK.json',
        'artifacts/PRE_LIVE_PACK.md',
        'artifacts/READINESS_SCORE.json',
        'artifacts/READINESS_SCORE.md',
        'artifacts/WEEKLY_ROLLUP.json',
        'artifacts/WEEKLY_ROLLUP.md',
        'artifacts/KPI_GATE.json',
        'artifacts/KPI_GATE.md',
        'artifacts/FULL_STACK_VALIDATION.json',
        'artifacts/FULL_STACK_VALIDATION.md',
    ):
        candidates.append(base)

    # docs
    for base in (
        'docs/OPS_ONE_PAGER.md',
        'docs/RUNBOOKS.md',
        'docs/REPORTS.md',
        'docs/REPORT_SOAK.md',
        'docs/INDEX.md',
        'CHANGELOG.md',
    ):
        candidates.append(base)

    # monitoring/grafana/*.json
    mon_graf = 'monitoring/grafana'
    if os.path.isdir(mon_graf):
        for name in sorted(os.listdir(mon_graf)):
            if name.lower().endswith('.json'):
                candidates.append(_as_posix(os.path.join(mon_graf, name)))

    # monitoring/promql/queries.md (single file)
    candidates.append('monitoring/promql/queries.md')

    # Deduplicate while preserving order
    seen = set()
    ordered: List[str] = []
    for p in candidates:
        q = _as_posix(p)
        if q not in seen:
            seen.add(q)
            ordered.append(q)
    return ordered


def _build_manifest(now_iso: str, version: str) -> Dict:
    files_present: List[Dict] = []
    missing: List[str] = []

    for path in _gather_candidates():
        if os.path.exists(path):
            try:
                sha, size = _sha256sum(path)
                files_present.append({'path': _as_posix(path), 'sha256': sha, 'bytes': int(size)})
            except Exception:
                # treat unreadable as missing
                missing.append(_as_posix(path))
        else:
            missing.append(_as_posix(path))

    # Deterministic order by path
    files_present.sort(key=lambda x: x['path'])
    missing.sort()

    ready = (len(missing) == 0)

    manifest = {
        'bundle': {
            'name': 'mm-bot',
            'utc': now_iso,
            'version': version or 'dev'
        },
        'files': files_present,
        'missing': missing,
        'result': 'READY' if ready else 'PARTIAL'
    }
    return manifest


def _zip_write_files(zip_path: str, files_present: List[Dict]) -> None:
    os.makedirs(os.path.dirname(zip_path), exist_ok=True)
    # Stable file order: already sorted by path in manifest; add in that order.
    # Use STORed to avoid platform-specific differences; fix date_time for determinism of metadata.
    with zipfile.ZipFile(zip_path + '.tmp', mode='w', compression=zipfile.ZIP_STORED, allowZip64=True) as zf:
        # ZIP format requires year >= 1980
        fixed_dt = (1980, 1, 1, 0, 0, 0)
        for entry in files_present:
            path = entry['path']
            arcname = _as_posix(path)
            zi = zipfile.ZipInfo(arcname, date_time=fixed_dt)
            zi.compress_type = zipfile.ZIP_STORED
            # External attr: regular file with 0644 perms (for unix viewers), though Windows ignores
            zi.external_attr = (0o100644 & 0xFFFF) << 16
            with open(path, 'rb') as f:
                data = f.read()
            # Ensure LF line endings are not enforced here (we package files as-is).
            zf.writestr(zi, data)
    # Atomic move
    if os.path.exists(zip_path):
        os.replace(zip_path + '.tmp', zip_path)
    else:
        os.rename(zip_path + '.tmp', zip_path)


def main(argv=None) -> int:
    os.environ.setdefault('PYTEST_DISABLE_PLUGIN_AUTOLOAD', '1')
    os.environ.setdefault('TZ', 'UTC')
    os.environ.setdefault('LC_ALL', 'C')
    os.environ.setdefault('LANG', 'C')

    now_iso = _utc_iso()
    version = os.environ.get('MM_VERSION', 'dev')

    manifest = _build_manifest(now_iso, version)

    # Write manifest
    manifest_path = 'artifacts/RELEASE_BUNDLE_manifest.json'
    _write_json_atomic(manifest_path, manifest)

    # Zip only present files, in manifest order
    safe_utc = _sanitize_utc_for_fs(now_iso)
    zip_path = f"dist/release_bundle/{safe_utc}-mm-bot.zip"
    _zip_write_files(zip_path, manifest['files'])

    # Print final status (ASCII only)
    sys.stdout.write(f"RELEASE_BUNDLE={manifest['result']}\n")
    # Write stamp (version uses manifest version)
    _write_stamp(manifest['bundle']['version'], zip_path)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())


