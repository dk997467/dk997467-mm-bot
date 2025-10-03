import json
from tools.soak.regression_guard import check


def test_regression_guard_triggers(tmp_path, test_paths):
    # Use universal fixture for paths
    last7 = []
    
    # File names differ in case; load via glob
    import glob
    paths = sorted(glob.glob(str(test_paths.fixtures_dir / 'reg' / 'base_7days' / 'REPORT_SOAK_*.json')))
    for p in paths:
        # Use context manager to properly close files
        with open(p, 'r', encoding='ascii') as f:
            last7.append(json.loads(f.read()))
    today = json.loads((test_paths.fixtures_dir / 'reg' / 'today_worse.json').read_text(encoding='ascii'))
    res = check(today, last7)
    assert res['ok'] is False and res['reason'] in ('EDGE_REG','LAT_REG','TAKER_REG')


