def test_rollout_audit_overlay_diff_present():
    from src.deploy.rollout import monitor_metrics
    # Minimal metrics text with rollout counters
    metrics_text = """
rollout_traffic_split_pct 30
rollout_orders_total{color="blue"} 7
rollout_orders_total{color="green"} 3
rollout_fills_total{color="blue"} 5
rollout_fills_total{color="green"} 2
rollout_avg_latency_ms{color="blue"} 100
rollout_avg_latency_ms{color="green"} 120
""".strip()

    def fake_get_text(url: str, timeout: int = 5) -> str:
        return metrics_text

    import types
    import src.deploy.rollout as r
    r._http_get_text = fake_get_text  # monkeypatch-like
    ok, reasons, stats = monitor_metrics(metrics_url="http://x/metrics", minutes=0.0, thresholds=types.SimpleNamespace(), poll_sec=0)
    ro = stats.get('rollout', {})
    assert 'salt_hash' in ro
    assert 'overlay_diff_keys' in ro
    # observed split correct: 30%
    assert abs(float(ro.get('split_observed_pct', 0.0)) - 30.0) < 1e-6

