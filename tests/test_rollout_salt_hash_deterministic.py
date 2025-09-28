def test_rollout_salt_hash_deterministic(monkeypatch):
    from src.deploy.rollout import monitor_metrics
    # metrics minimal
    metrics_text = "rollout_traffic_split_pct 0\n"

    def fake_get_text(url: str, timeout: int = 5) -> str:
        return metrics_text

    def fake_get_json(url: str, timeout: int = 5):
        if url.endswith('/admin/rollout'):
            return {"salt": "abc"}
        if url.endswith('/admin/config'):
            return {"rollout": {"blue": {}, "green": {}}}
        return {}

    import src.deploy.rollout as r
    r._http_get_text = fake_get_text
    r._http_get_json = fake_get_json
    ok, reasons, stats = monitor_metrics(metrics_url="http://x/metrics", minutes=0.0, thresholds=None, poll_sec=0, admin_url="http://x", drift_cap_pct=5.0, min_sample_orders=1)
    ro = stats.get('rollout', {})
    import hashlib
    expected = hashlib.sha1(b"abc").hexdigest()[:8]
    assert ro.get('salt_hash') == expected

