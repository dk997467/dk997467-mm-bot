import json
import os
import subprocess
import sys
from pathlib import Path


def test_pre_live_pack_dry(tmp_path):
    # Run pre_live_pack in repo root; artifacts will be created there
    # Skip bug_bash to prevent subprocess explosion (bug_bash runs pytest -n 2)
    env = os.environ.copy()
    env['PRE_LIVE_SKIP_BUG_BASH'] = '1'
    r = subprocess.run([sys.executable, '-m', 'tools.rehearsal.pre_live_pack'], capture_output=True, text=True, timeout=300, env=env)
    assert r.returncode == 0
    pack_json = Path('artifacts/PRE_LIVE_PACK.json')
    assert pack_json.exists()
    # Render MD
    r2 = subprocess.run([sys.executable, '-m', 'tools.rehearsal.report_pack', 'artifacts/PRE_LIVE_PACK.json'], capture_output=True, text=True, timeout=300)
    assert r2.returncode == 0
    md = Path('artifacts/PRE_LIVE_PACK.md').read_bytes()
    golden = Path('tests/golden/PRE_LIVE_PACK_case1.md').read_bytes()
    assert md == golden


