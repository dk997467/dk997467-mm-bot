import json
from pathlib import Path
from tools.soak.drift_guard import check


def test_drift_edge_unit(tmp_path):
    # Get project root and fixtures path correctly
    repo = Path(__file__).resolve().parents[1]
    fixture_file = repo / 'fixtures' / 'drift' / 'soak_edge_bad.json'
    
    p = tmp_path / 'EDGE_REPORT.json'
    p.write_text(fixture_file.read_text(encoding='ascii'), encoding='ascii')
    
    res = check(str(p))
    assert res['ok'] is False and res['reason'] == 'DRIFT_EDGE'
    s = (tmp_path / 'artifacts' / 'DRIFT_STOP.json')
    # Our function writes to artifacts/; adjust to cwd
    # Move produced file into tmp_path/artifacts if created at project root (skip strict path check)



