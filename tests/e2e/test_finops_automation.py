import os
from pathlib import Path
import subprocess


def run_cli(out_dir: Path):
    root = Path(__file__).resolve().parents[2]
    env = os.environ.copy()
    env['MM_FREEZE_UTC'] = '1'
    cmd = [
        'python', '-m', 'tools.finops.cron_job',
        '--artifacts', str(root / 'tests' / 'fixtures' / 'artifacts_sample' / 'metrics.json'),
        '--exchange-dir', str(root / 'tests' / 'fixtures' / 'exchange_reports'),
        '--out-dir', str(out_dir),
    ]
    subprocess.check_call(cmd, env=env)


def test_finops_cron_determinism(tmp_path):
    out1 = tmp_path / 'out1'
    out2 = tmp_path / 'out2'
    run_cli(out1)
    run_cli(out2)

    names = ['pnl.csv','fees.csv','turnover.csv','latency.csv','edge.csv','reconcile_report.json','reconcile_diff.md']
    for n in names:
        b1 = (out1 / n).read_bytes()
        b2 = (out2 / n).read_bytes()
        assert b1 == b2
        assert b1.endswith(b'\n')

    # golden compare
    root = Path(__file__).resolve().parents[2]
    g = root / 'tests' / 'golden'
    assert (out1 / 'reconcile_report.json').read_bytes() == (g / 'reconcile_report.json').read_bytes()
    assert (out1 / 'reconcile_diff.md').read_bytes() == (g / 'reconcile_diff.md').read_bytes()


