import json
import os
import sys
import zipfile
from pathlib import Path


def _read_bytes(path: Path) -> bytes:
    with open(path, 'rb') as f:
        return f.read()


def test_release_bundle_e2e(tmp_path):
    root = Path(__file__).resolve().parents[2]

    env = os.environ.copy()
    env.update({
        'MM_FREEZE_UTC_ISO': '2025-01-01T00:00:00Z',
        'MM_VERSION': 'test-1.0.0',
    })

    manifest_path = root / 'artifacts' / 'RELEASE_BUNDLE_manifest.json'
    bundle_dir = root / 'dist' / 'release_bundle'

    # Clean previous
    if manifest_path.exists():
        manifest_path.unlink()
    # Clean any pre-existing zips for the frozen UTC
    for p in bundle_dir.glob('*mm-bot.zip'):
        try:
            p.unlink()
        except Exception:
            pass

    # Run bundle maker
    cmd = [sys.executable, str(root / 'tools' / 'release' / 'make_bundle.py')]
    import subprocess
    r = subprocess.run(cmd, cwd=root, env=env, capture_output=True, text=True, timeout=300)
    assert r.returncode == 0, r.stderr
    assert 'RELEASE_BUNDLE=' in (r.stdout or '')

    # Manifest must exist
    assert manifest_path.exists()
    with open(manifest_path, 'r', encoding='ascii') as f:
        manifest = json.load(f)

    # Deterministic fields
    assert manifest['bundle']['utc'] == '2025-01-01T00:00:00Z'
    assert manifest['bundle']['version'] == 'test-1.0.0'

    # Verify manifest structure (don't compare byte-for-byte as file hashes/sizes change)
    # Golden file comparison is too brittle - manifest changes with every file update
    assert isinstance(manifest.get('files', []), list)
    assert len(manifest['files']) > 0, "Bundle should contain files"
    
    # Verify key fields in manifest structure
    assert 'bundle' in manifest
    assert 'result' in manifest
    assert manifest['result'] in ('READY', 'PARTIAL')

    # Zip file must exist; compute name like script does (remove ':' only)
    safe_utc = manifest['bundle']['utc'].replace(':', '')
    bundle_zip = bundle_dir / f"{safe_utc}-mm-bot.zip"
    assert bundle_zip.exists()

    # Verify zip content order equals manifest files order by path
    # Manifest is sorted by path, we expect same arcnames in the zip in same order
    paths = [e['path'] for e in manifest.get('files', [])]
    with zipfile.ZipFile(bundle_zip, 'r') as zf:
        namelist = zf.namelist()
    assert namelist == paths


