import subprocess
import sys
from pathlib import Path


def test_daily_digest_unit(tmp_path, test_paths):
    # Use universal fixture for paths
    (tmp_path / 'artifacts').mkdir()
    (tmp_path / 'artifacts' / 'EDGE_REPORT.json').write_text((test_paths.fixtures_dir / 'digest' / 'EDGE_REPORT.json').read_text(encoding='ascii'), encoding='ascii')
    (tmp_path / 'artifacts' / 'REPORT_SOAK_19700101.json').write_text((test_paths.fixtures_dir / 'digest' / 'REPORT_SOAK.json').read_text(encoding='ascii'), encoding='ascii')
    (tmp_path / 'artifacts' / 'LEDGER_DAILY.json').write_text((test_paths.fixtures_dir / 'digest' / 'LEDGER_DAILY.json').read_text(encoding='ascii'), encoding='ascii')
    # Run from project root
    import os
    project_root = test_paths.project_root
    env = os.environ.copy()
    env['WORK_DIR'] = str(tmp_path)
    r = subprocess.run([sys.executable, '-m', 'tools.ops.daily_digest', '--out', str(tmp_path / 'artifacts' / 'DAILY_DIGEST.md')], 
                      cwd=str(project_root), env=env, capture_output=True, text=True)
    assert r.returncode == 0, f"Command failed: {r.stderr}"
    md = (tmp_path / 'artifacts' / 'DAILY_DIGEST.md').read_bytes()
    assert md.endswith(b'\n')


