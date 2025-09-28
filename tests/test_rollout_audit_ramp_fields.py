"""
Audit includes ramp fields.
"""
from types import SimpleNamespace


def test_rollout_audit_ramp_fields(monkeypatch):
    from src.deploy.rollout import monitor_metrics
    # Minimal metrics text with ramp gauges
    metrics_text = """
rollout_ramp_enabled 1
rollout_ramp_step_idx 2
rollout_traffic_split_pct 25
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
    assert r.get('ramp_enabled') == 1
    assert r.get('ramp_step_idx') == 2
    assert r.get('traffic_split_pct') == 25


