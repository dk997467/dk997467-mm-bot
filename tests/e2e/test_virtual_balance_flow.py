import subprocess
import sys
from pathlib import Path


def run_cli(out_dir: Path):
    root = Path(__file__).resolve().parents[2]
    cmd = [
        sys.executable, '-m', 'tools.sim.virtual_balance',
        '--trades', str(root / 'tests' / 'fixtures' / 'ledger' / 'trades_case1.jsonl'),
        '--prices', str(root / 'tests' / 'fixtures' / 'ledger' / 'prices_case1.jsonl'),
    ]
    subprocess.check_call(cmd, cwd=str(out_dir))


def test_virtual_balance_e2e(tmp_path):
    out1 = tmp_path / 'run1'
    out1.mkdir()
    out2 = tmp_path / 'run2'
    out2.mkdir()
    run_cli(out1)
    run_cli(out2)

    b1 = (out1 / 'artifacts' / 'LEDGER_DAILY.json').read_bytes()
    b2 = (out2 / 'artifacts' / 'LEDGER_DAILY.json').read_bytes()
    assert b1 == b2 and b1.endswith(b'\n')

    e1 = (out1 / 'artifacts' / 'LEDGER_EQUITY.json').read_bytes()
    e2 = (out2 / 'artifacts' / 'LEDGER_EQUITY.json').read_bytes()
    assert e1 == e2 and e1.endswith(b'\n')

    root = Path(__file__).resolve().parents[2]
    g = root / 'tests' / 'golden'
    assert b1 == (g / 'LEDGER_DAILY_case1.json').read_bytes()
    assert e1 == (g / 'LEDGER_EQUITY_case1.json').read_bytes()


