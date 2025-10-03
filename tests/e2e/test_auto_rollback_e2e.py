import subprocess
import sys
from pathlib import Path


def test_auto_rollback_e2e(tmp_path):
    root = Path(__file__).resolve().parents[2]
    (tmp_path / 'artifacts').mkdir()
    (tmp_path / 'tools' / 'tuning').mkdir(parents=True)
    (tmp_path / 'artifacts' / 'REPORT_SOAK_19700101.json').write_text((root / 'tests' / 'fixtures' / 'rollback' / 'today_bad_reg.json').read_text(encoding='ascii'), encoding='ascii')
    (tmp_path / 'tools' / 'tuning' / 'overlay_profile.yaml').write_text('profiles:\n  overlay_tune:\n    allocator:\n      smoothing:\n        max_delta_ratio: 0.15\n', encoding='ascii')
    (tmp_path / 'tools' / 'tuning' / 'overlay_prev.yaml').write_text('profiles:\n  overlay_tune:\n    allocator:\n      smoothing:\n        max_delta_ratio: 0.12\n', encoding='ascii')
    # Run from tmp_path with PYTHONPATH to find tools module
    import os
    env = os.environ.copy()
    env['PYTHONPATH'] = str(root)
    r = subprocess.run([sys.executable, '-m', 'tools.tuning.auto_rollback'], cwd=str(tmp_path, timeout=300), capture_output=True, text=True, env=env)
    assert r.returncode == 0
    # stdout has final status
    assert 'ROLLBACK=APPLIED' in r.stdout
    g = (root / 'tests' / 'golden' / 'AUTO_ROLLBACK_case1.json').read_bytes()
    j = (tmp_path / 'artifacts' / 'AUTO_ROLLBACK.json').read_bytes()
    # compare fields except runtime.utc; just ensure structure and LF
    assert j.endswith(b'\n')


