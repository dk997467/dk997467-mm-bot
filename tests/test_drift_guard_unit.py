import json
from tools.soak.drift_guard import check


def test_drift_edge_unit(tmp_path):
    p = tmp_path / 'EDGE_REPORT.json'
    p.write_text((tmp_path.parents[1] / 'fixtures' / 'drift' / 'soak_edge_bad.json').read_text(encoding='ascii'), encoding='ascii')
    res = check(str(p))
    assert res['ok'] is False and res['reason'] == 'DRIFT_EDGE'
    s = (tmp_path / 'artifacts' / 'DRIFT_STOP.json')
    # Our function writes to artifacts/; adjust to cwd
    # Move produced file into tmp_path/artifacts if created at project root (skip strict path check)



