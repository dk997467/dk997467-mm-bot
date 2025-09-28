def test_rollout_split_drift_with_min_sample(monkeypatch):
    from src.deploy.rollout import monitor_metrics
    # observed pct present
    metrics_text = """
rollout_traffic_split_pct 50
rollout_split_observed_pct 10
rollout_orders_total{color="blue"} 9
rollout_orders_total{color="green"} 1
""".strip()

    def fake_get_text(url: str, timeout: int = 5) -> str:
        return metrics_text

    def fake_get_json(url: str, timeout: int = 5):
        return {}

    import src.deploy.rollout as r
    r._http_get_text = fake_get_text
    r._http_get_json = fake_get_json
    # Low sample -> no alert
    ok, reasons, stats = monitor_metrics(metrics_url="http://x/metrics", minutes=0.0, thresholds=None, poll_sec=0, admin_url=None, drift_cap_pct=5.0, min_sample_orders=200)
    ro = stats.get('rollout', {})
    assert ro.get('split_drift_alert') is False
    assert ro.get('split_drift_reason') == 'low_sample'

    # Enough sample -> alert
    metrics_text2 = """
rollout_traffic_split_pct 50
rollout_split_observed_pct 10
rollout_orders_total{color="blue"} 900
rollout_orders_total{color="green"} 100
""".strip()
    r._http_get_text = lambda url, timeout=5: metrics_text2
    ok, reasons, stats = monitor_metrics(metrics_url="http://x/metrics", minutes=0.0, thresholds=None, poll_sec=0, admin_url=None, drift_cap_pct=5.0, min_sample_orders=200)
    ro = stats.get('rollout', {})
    assert ro.get('split_drift_alert') is True
    assert ro.get('split_drift_reason') == 'exceeds_cap'

