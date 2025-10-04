import os
import subprocess
import sys
from pathlib import Path


def test_daily_digest_e2e(tmp_path):
    root = Path(__file__).resolve().parents[2]
    
    # CRITICAL: daily_digest.py reads from 'artifacts/' relative to cwd
    # So we must create artifacts/ in project root with test fixtures
    artifacts_dir = root / 'artifacts'
    artifacts_dir.mkdir(exist_ok=True)
    
    # Copy all required fixtures for daily_digest
    fixtures = [
        'EDGE_REPORT.json',
        'REPORT_SOAK.json',
        'LEDGER_DAILY.json',
        'EDGE_SENTINEL.json',  # Required for 'Actionables' section
        'DRIFT_STOP.json',     # Required for 'Drift Guard' line
        'REG_GUARD_STOP.json'  # Required for 'Regression Guard' line
    ]
    
    # Backup existing artifacts if any
    backups = {}
    for name in fixtures:
        artifact_file = artifacts_dir / (name if name != 'REPORT_SOAK.json' else 'REPORT_SOAK_19700101.json')
        if artifact_file.exists():
            backups[name] = artifact_file.read_bytes()
    
    try:
        # Copy test fixtures to artifacts/
        for name in fixtures:
            src = root / 'tests' / 'fixtures' / 'digest' / name
            if not src.exists():
                continue
            dst = artifacts_dir / (name if name != 'REPORT_SOAK.json' else 'REPORT_SOAK_19700101.json')
            dst.write_text(src.read_text(encoding='ascii'), encoding='ascii')
        
        env = os.environ.copy()
        env['PYTHONPATH'] = str(root)
        env['MM_FREEZE_UTC_ISO'] = '1970-01-01T00:00:00Z'
        
        # Run from project root (daily_digest.py reads artifacts/ from cwd)
        output_file = artifacts_dir / 'DAILY_DIGEST.md'
        subprocess.check_call([sys.executable, '-m', 'tools.ops.daily_digest', '--out', str(output_file)], cwd=str(root), env=env)
        
        # Normalize line endings for comparison
        md = output_file.read_bytes().replace(b'\r\n', b'\n')
        g = (root / 'tests' / 'golden' / 'DAILY_DIGEST_case1.md').read_bytes().replace(b'\r\n', b'\n')
        assert md == g
    
    finally:
        # Cleanup: remove test fixtures from artifacts/
        for name in fixtures:
            artifact_file = artifacts_dir / (name if name != 'REPORT_SOAK.json' else 'REPORT_SOAK_19700101.json')
            if artifact_file.exists():
                artifact_file.unlink()
        
        # Restore backups if any
        for name, content in backups.items():
            artifact_file = artifacts_dir / (name if name != 'REPORT_SOAK.json' else 'REPORT_SOAK_19700101.json')
            artifact_file.write_bytes(content)


