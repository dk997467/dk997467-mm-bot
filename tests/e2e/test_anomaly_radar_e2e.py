import json
import subprocess
import sys
from pathlib import Path


def test_anomaly_radar_e2e(tmp_path):
    src = Path('tests/fixtures/anomaly/EDGE_REPORT_DAY.json').read_text(encoding='ascii')
    inp = tmp_path / 'artifacts' / 'EDGE_REPORT_DAY.json'
    inp.parent.mkdir(parents=True, exist_ok=True)
    inp.write_text(src, encoding='ascii')
    out_json = tmp_path / 'artifacts' / 'ANOMALY_RADAR.json'
    r = subprocess.run([sys.executable, '-m', 'tools.soak.anomaly_radar', '--edge-report', str(inp), '--bucket-min', '15', '--out-json', str(out_json)], capture_output=True, text=True, timeout=300)
    assert r.returncode == 0
    # Normalize line endings for comparison
    got = out_json.read_bytes().replace(b'\r\n', b'\n')
    golden = Path('tests/golden/ANOMALY_RADAR_case1.json').read_bytes().replace(b'\r\n', b'\n')
    assert got == golden
    out_md = tmp_path / 'artifacts' / 'ANOMALY_RADAR.md'
    got_md = out_md.read_bytes().replace(b'\r\n', b'\n')
    golden_md = Path('tests/golden/ANOMALY_RADAR_case1.md').read_bytes().replace(b'\r\n', b'\n')
    assert got_md == golden_md


