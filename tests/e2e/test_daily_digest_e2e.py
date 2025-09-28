import subprocess
import sys
from pathlib import Path


def test_daily_digest_e2e(tmp_path):
    root = Path(__file__).resolve().parents[2]
    (tmp_path / 'artifacts').mkdir()
    for name in ['EDGE_REPORT.json','REPORT_SOAK.json','LEDGER_DAILY.json']:
        src = root / 'tests' / 'fixtures' / 'digest' / name
        dst = tmp_path / 'artifacts' / (name if name != 'REPORT_SOAK.json' else 'REPORT_SOAK_19700101.json')
        dst.write_text(src.read_text(encoding='ascii'), encoding='ascii')
    subprocess.check_call([sys.executable, '-m', 'tools.ops.daily_digest', '--out', 'artifacts/DAILY_DIGEST.md'], cwd=str(tmp_path))
    md = (tmp_path / 'artifacts' / 'DAILY_DIGEST.md').read_bytes()
    g = (root / 'tests' / 'golden' / 'DAILY_DIGEST_case1.md').read_bytes()
    assert md == g


