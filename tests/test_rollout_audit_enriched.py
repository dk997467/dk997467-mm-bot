"""
Test that rollout audit block is enriched with per-color counts and latency.
"""
from types import SimpleNamespace


def test_rollout_audit_block_enriched(monkeypatch, tmp_path):
    from src.deploy.rollout import monitor_metrics

    # Fake metrics endpoint returning minimal required metrics
    metrics_text = """
rollout_traffic_split_pct 30
rollout_orders_total{color="blue"} 10
rollout_orders_total{color="green"} 5
rollout_fills_total{color="blue"} 7
rollout_fills_total{color="green"} 3
rollout_rejects_total{color="blue"} 1
rollout_rejects_total{color="green"} 2
rollout_avg_latency_ms{color="blue"} 150
rollout_avg_latency_ms{color="green"} 220
""".strip()

    def fake_get_text(url: str, timeout: int = 5) -> str:
        return metrics_text

    monkeypatch.setattr('src.deploy.rollout._http_get_text', fake_get_text)

    ok, reasons, stats = monitor_metrics(metrics_url="http://x/metrics", minutes=0.0, thresholds=SimpleNamespace(), poll_sec=0)
    assert 'rollout' in stats
    r = stats['rollout']
    assert r['traffic_split_pct'] == 30
    assert r['orders_blue'] == 10
    assert r['orders_green'] == 5
    assert r['fills_blue'] == 7
    assert r['fills_green'] == 3
    assert r['rejects_blue'] == 1
    assert r['rejects_green'] == 2
    assert abs(r['latency_ms_avg_blue'] - 150.0) < 1e-6
    assert abs(r['latency_ms_avg_green'] - 220.0) < 1e-6


