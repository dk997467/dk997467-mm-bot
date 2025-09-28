"""
Audit contains overlay keys placeholders.
"""
from types import SimpleNamespace


def test_rollout_audit_overlay_keys(monkeypatch):
    from src.deploy.rollout import monitor_metrics
    metrics_text = """
rollout_traffic_split_pct 30
rollout_orders_total{color="blue"} 10
rollout_orders_total{color="green"} 5
rollout_fills_total{color="blue"} 7
rollout_fills_total{color="green"} 3
rollout_rejects_total{color="blue"} 1
rollout_rejects_total{color="green"} 2
rollout_avg_latency_ms{color="blue"} 100
rollout_avg_latency_ms{color="green"} 110
""".strip()

    def fake_get_text(url: str, timeout: int = 5) -> str:
        return metrics_text

    monkeypatch.setattr('src.deploy.rollout._http_get_text', fake_get_text)
    ok, reasons, stats = monitor_metrics(metrics_url="http://x/metrics", minutes=0.0, thresholds=SimpleNamespace(), poll_sec=0)
    r = stats.get('rollout', {})
    assert 'overlay_keys_blue' in r and isinstance(r['overlay_keys_blue'], list)
    assert 'overlay_keys_green' in r and isinstance(r['overlay_keys_green'], list)


