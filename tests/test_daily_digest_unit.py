import subprocess
import sys
from pathlib import Path


def test_daily_digest_unit(tmp_path):
    root = Path(__file__).resolve().parents[1]
    (tmp_path / 'artifacts').mkdir()
    (tmp_path / 'artifacts' / 'EDGE_REPORT.json').write_text((root / 'fixtures' / 'digest' / 'EDGE_REPORT.json').read_text(encoding='ascii'), encoding='ascii')
    (tmp_path / 'artifacts' / 'REPORT_SOAK_19700101.json').write_text((root / 'fixtures' / 'digest' / 'REPORT_SOAK.json').read_text(encoding='ascii'), encoding='ascii')
    (tmp_path / 'artifacts' / 'LEDGER_DAILY.json').write_text((root / 'fixtures' / 'digest' / 'LEDGER_DAILY.json').read_text(encoding='ascii'), encoding='ascii')
    r = subprocess.run([sys.executable, '-m', 'tools.ops.daily_digest', '--out', 'artifacts/DAILY_DIGEST.md'], cwd=str(tmp_path), capture_output=True, text=True)
    assert r.returncode == 0
    md = (tmp_path / 'artifacts' / 'DAILY_DIGEST.md').read_bytes()
    assert md.endswith(b'\n')


