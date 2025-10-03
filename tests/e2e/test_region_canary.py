from pathlib import Path
import os
import json
import subprocess

# Default timeout for all subprocess calls
SUBPROCESS_TIMEOUT = 300  # 5 minutes


def test_region_canary_e2e(tmp_path):
    root = Path(__file__).resolve().parents[2]
    out_json = tmp_path / 'REGION_COMPARE.json'

    cmd = [
        'python','-m','tools.region.run_canary_compare',
        '--regions', str(root / 'config' / 'regions.yaml'),
        '--in', str(root / 'tests' / 'fixtures' / 'region_canary_metrics.jsonl'),
        '--out', str(out_json),
    ]
    env = os.environ.copy()
    env['MM_FREEZE_UTC'] = '1'
    subprocess.check_call(cmd, env=env, timeout=SUBPROCESS_TIMEOUT)

    # determinism: run again into another dir
    out_json2 = tmp_path / 'REGION_COMPARE_2.json'
    cmd[-1] = str(out_json2)
    subprocess.check_call(cmd, env=env, timeout=SUBPROCESS_TIMEOUT)

    b1 = out_json.read_bytes()
    b2 = out_json2.read_bytes()
    assert b1 == b2
    assert b1.endswith(b'\n')

    # compare with golden
    gdir = root / 'tests' / 'golden'
    assert b1 == (gdir / 'region_compare_case1.json').read_bytes()

    # md
    md1 = (tmp_path / 'REGION_COMPARE.md').read_bytes()
    md2 = (tmp_path / 'REGION_COMPARE_2.md').read_bytes()
    assert md1 == md2
    assert md1.endswith(b'\n')
    assert md1 == (gdir / 'region_compare_case1.md').read_bytes()

    # semantic checks
    rep = json.loads(b1.decode('ascii'))
    safe = {
        'net_bps_min': 2.50,
        'order_age_p95_ms_max': 350,
        'taker_share_pct_max': 15,
    }
    w = rep['winner']
    win_metrics = rep['windows'][w['window']]
    assert win_metrics['net_bps'] >= safe['net_bps_min']
    assert win_metrics['order_age_p95_ms'] <= safe['order_age_p95_ms_max']
    assert win_metrics['taker_share_pct'] <= safe['taker_share_pct_max']

    # tie-break by latency at equal net_bps: us-east over eu-west due to lower latency
    assert w['region'] == 'us-east'
    assert w['window'] == '00:00-02:00'
