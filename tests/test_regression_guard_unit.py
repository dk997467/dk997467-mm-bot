import json
from tools.soak.regression_guard import check


def test_regression_guard_triggers(tmp_path):
    # build last7 and today
    import pathlib
    repo = pathlib.Path(__file__).resolve().parents[1]
    last7 = []
    for i in range(1, 8):
        p = repo / 'fixtures' / 'reg' / 'base_7days' / f'RePORT_SOAK_2025010{i}.json'
    
    # File names differ in case; load via glob
    import glob
    paths = sorted(glob.glob(str(repo / 'fixtures' / 'reg' / 'base_7days' / 'REPORT_SOAK_*.json')))
    for p in paths:
        # Use context manager to properly close files
        with open(p, 'r', encoding='ascii') as f:
            last7.append(json.loads(f.read()))
    today = json.loads((repo / 'fixtures' / 'reg' / 'today_worse.json').read_text(encoding='ascii'))
    res = check(today, last7)
    assert res['ok'] is False and res['reason'] in ('EDGE_REG','LAT_REG','TAKER_REG')


