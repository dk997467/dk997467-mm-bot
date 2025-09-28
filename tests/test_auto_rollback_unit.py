import json
import os
import shutil
import subprocess
import sys
from pathlib import Path


def test_auto_rollback_applies(tmp_path):
    (tmp_path / 'artifacts').mkdir()
    (tmp_path / 'tools' / 'tuning').mkdir(parents=True)
    # seed soak today
    from pathlib import Path as P
    repo = P(__file__).resolve().parents[1]
    (tmp_path / 'artifacts' / 'REPORT_SOAK_19700101.json').write_text((repo / 'fixtures' / 'rollback' / 'today_bad_reg.json').read_text(encoding='ascii'), encoding='ascii')
    # seed overlays
    (tmp_path / 'tools' / 'tuning' / 'overlay_profile.yaml').write_text('profiles:\n  overlay_tune:\n    allocator:\n      smoothing:\n        max_delta_ratio: 0.15\n', encoding='ascii')
    (tmp_path / 'tools' / 'tuning' / 'overlay_prev.yaml').write_text('profiles:\n  overlay_tune:\n    allocator:\n      smoothing:\n        max_delta_ratio: 0.12\n', encoding='ascii')
    r = subprocess.run([sys.executable, '-m', 'tools.tuning.auto_rollback'], cwd=str(tmp_path), capture_output=True, text=True)
    assert r.returncode == 0
    out = (tmp_path / 'artifacts' / 'AUTO_ROLLBACK.json').read_text(encoding='ascii')
    j = json.loads(out)
    assert j['reason'] in ('REG','DRIFT')
    # profile restored
    prof = (tmp_path / 'tools' / 'tuning' / 'overlay_profile.yaml').read_text(encoding='ascii')
    assert 'max_delta_ratio: 0.12' in prof


