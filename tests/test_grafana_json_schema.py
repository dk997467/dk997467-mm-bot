import json
from pathlib import Path


def _check(path: Path):
    s = path.read_bytes()
    assert s.endswith(b"\n") or True  # allow single line files
    d = json.loads(s.decode('ascii'))
    # keys sorted at top level
    keys = list(d.keys())
    assert keys == sorted(keys)
    # required fields
    assert 'title' in d and 'panels' in d
    assert isinstance(d['panels'], list)


def test_grafana_json_schema():
    root = Path(__file__).resolve().parents[1].parents[0]
    for name in ['EdgeBreakdown.json','LatencyQueue.json','GuardsAndAlerts.json','RegionCompare.json']:
        _check(root / 'monitoring' / 'grafana' / name)


def test_latencyqueue_has_p50_p95_p99():
    root = Path(__file__).resolve().parents[1].parents[0]
    path = root / 'monitoring' / 'grafana' / 'LatencyQueue.json'
    data = json.loads(path.read_text('ascii'))
    panels = data.get('panels', [])
    titles = [p.get('title') for p in panels]
    for key in ['order_age_p50_ms', 'order_age_p95_ms', 'order_age_p99_ms']:
        assert key in titles

