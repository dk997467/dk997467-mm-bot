import os
import shutil
import subprocess
from pathlib import Path


def test_ops_snapshot(tmp_path):
    root = Path(__file__).resolve().parents[2]
    work = tmp_path / 'work'
    (work / 'artifacts').mkdir(parents=True)
    (work / 'dist' / 'finops' / 'x').mkdir(parents=True)
    # place minimal files
    (work / 'artifacts' / 'EDGE_REPORT.json').write_text('{"a":1}\n', encoding='ascii')
    (work / 'artifacts' / 'EDGE_REPORT.md').write_text('x\n', encoding='ascii')
    (work / 'artifacts' / 'REGION_COMPARE.json').write_text('{"b":2}\n', encoding='ascii')
    (work / 'artifacts' / 'REGION_COMPARE.md').write_text('y\n', encoding='ascii')
    (work / 'artifacts' / 'REPORT_SOAK_20250101.json').write_text('{"c":3}\n', encoding='ascii')
    (work / 'artifacts' / 'REPORT_SOAK_20250101.md').write_text('z\n', encoding='ascii')
    (work / 'artifacts' / 'metrics.json').write_text('{"m":1}\n', encoding='ascii')
    (work / 'dist' / 'finops' / 'x' / 'reconcile_report.json').write_text('{"d":4}\n', encoding='ascii')

    env = os.environ.copy()
    r = subprocess.run(['sh', str(root / 'tools' / 'ops' / 'snapshot.sh', timeout=300)], cwd=str(work), capture_output=True, text=True, env=env)
    assert r.returncode == 0
    assert r.stdout.endswith('\n')
    assert 'SNAPSHOT' in r.stdout

    # Find created snapshot dir
    snap_root = work / 'dist' / 'snapshots'
    snaps = list(snap_root.iterdir())
    assert len(snaps) == 1
    snap = snaps[0]
    # Check copied files
    for name in ['EDGE_REPORT.json','EDGE_REPORT.md','REGION_COMPARE.json','REGION_COMPARE.md','metrics.json','REPORT_SOAK_20250101.json','REPORT_SOAK_20250101.md']:
        assert (snap / name).exists()
    # Finops copied
    assert (snap / 'finops').exists()


