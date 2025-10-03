import subprocess
import sys
from pathlib import Path


def test_readiness_score_e2e(tmp_path):
    # Copy fixtures to artifacts/
    (tmp_path / 'artifacts').mkdir()
    src_dir = Path('tests/fixtures/readiness/soak_7days')
    for p in sorted(src_dir.glob('REPORT_SOAK_*.json')):
        (tmp_path / 'artifacts' / p.name).write_text(p.read_text(encoding='ascii'), encoding='ascii')
    out_json = tmp_path / 'artifacts' / 'READINESS_SCORE.json'
    r = subprocess.run([sys.executable, '-m', 'tools.release.readiness_score', '--dir', str(tmp_path / 'artifacts'), '--out-json', str(out_json)], capture_output=True, text=True, timeout=300)
    assert r.returncode == 0
    got = out_json.read_bytes()
    golden = Path('tests/golden/READINESS_SCORE_case1.json').read_bytes()
    assert got == golden
    md = (tmp_path / 'artifacts' / 'READINESS_SCORE.md').read_bytes()
    golden_md = Path('tests/golden/READINESS_SCORE_case1.md').read_bytes()
    assert md == golden_md


