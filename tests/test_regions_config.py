from pathlib import Path
import yaml


def test_regions_yaml_valid():
    root = Path(__file__).resolve().parents[1]
    y = (root / 'config' / 'regions.yaml').read_text(encoding='ascii')
    cfg = yaml.safe_load(y)

    regions = cfg.get('regions', [])
    names = [r.get('name') for r in regions]
    assert len(names) == len(set(names))
    for r in regions:
        assert isinstance(r.get('enabled'), bool)

    metrics = cfg.get('metrics', {})
    keys = metrics.get('keys', [])
    for k in ('net_bps','order_age_p95_ms','fill_rate','taker_share_pct'):
        assert k in keys

    switch = cfg.get('switch', {})
    assert 'cooldown_s' in switch


