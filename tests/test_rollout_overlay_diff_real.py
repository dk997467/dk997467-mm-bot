def test_rollout_overlay_diff_real(monkeypatch):
    from src.deploy.rollout import monitor_metrics
    metrics_text = "rollout_traffic_split_pct 0\n"

    def fake_get_text(url: str, timeout: int = 5) -> str:
        return metrics_text

    def fake_get_json(url: str, timeout: int = 5):
        if url.endswith('/admin/rollout'):
            return {"salt": "x"}
        if url.endswith('/admin/config'):
            return {
                "autopolicy": {"level_max": 6},
                "levels_per_side_max": 10,
                "replace_threshold_bps": 2.0,
                "rollout": {
                    "blue": {"levels_per_side_max": 10},
                    "green": {"autopolicy.level_max": 6, "replace_threshold_bps": 3.5},
                }
            }
        return {}

    import src.deploy.rollout as r
    r._http_get_text = fake_get_text
    r._http_get_json = fake_get_json
    ok, reasons, stats = monitor_metrics(metrics_url="http://x/metrics", minutes=0.0, thresholds=None, poll_sec=0, admin_url="http://x")
    ro = stats.get('rollout', {})
    diff = ro.get('overlay_diff_keys', [])
    assert diff == ["replace_threshold_bps"]

