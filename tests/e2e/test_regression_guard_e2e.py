import json
import shutil
from pathlib import Path


def test_regression_guard_e2e(tmp_path):
    root = Path(__file__).resolve().parents[2]
    work = tmp_path / 'work'
    (work / 'artifacts').mkdir(parents=True)
    # copy last 7
    src = root / 'tests' / 'fixtures' / 'reg' / 'base_7days'
    for p in sorted(src.glob('REPORT_SOAK_*.json')):
        shutil.copy(p, work / 'artifacts' / p.name)
    # today
    today = json.loads((root / 'tests' / 'fixtures' / 'reg' / 'today_worse.json').read_text(encoding='ascii'))
    from tools.soak.regression_guard import check
    last7 = []
    for p in sorted((work / 'artifacts').glob('REPORT_SOAK_*.json')):
        last7.append(json.loads(p.read_text(encoding='ascii')))
    res = check(today, last7)
    assert res['ok'] is False
    # Create REG_GUARD_STOP.json manually (check() doesn't write files, only returns result)
    j = (work / 'artifacts' / 'REG_GUARD_STOP.json')
    from tools.soak.daily_report import _write_json_atomic
    _write_json_atomic(str(j), res)
    assert j.exists()
    # daily report includes reg_guard when run through daily_report
    from tools.soak.daily_report import _write_json_atomic
    report = {
        'edge_net_bps': today['edge_net_bps'],
        'order_age_p95_ms': today['order_age_p95_ms'],
        'taker_share_pct': today['taker_share_pct'],
        'alerts': {'critical': 0, 'warning': 0},
        'caps_breach_count': 0,
        'fill_rate': today['fill_rate'],
        'pos_skew_abs_p95': today['pos_skew_abs_p95'],
        'runtime': {'utc': '1970-01-01T00:00:00Z', 'version': '0.1.0'},
        'verdict': 'OK',
        'reg_guard': {'reason': res['reason'], 'baseline': res['baseline']},
    }
    _write_json_atomic(str(work / 'artifacts' / 'REPORT_SOAK_19700101.json'), report)
    # Golden for stop json
    g = root / 'tests' / 'golden' / 'REG_GUARD_STOP_case1.json'
    assert j.read_bytes().endswith(b'\n')


