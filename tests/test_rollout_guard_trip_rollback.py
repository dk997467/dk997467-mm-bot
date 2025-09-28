from src.deploy.rollout import monitor_metrics
from src.deploy.thresholds import GateThresholds


def test_rollout_guard_trip_rollback(monkeypatch):
    payloads = [
        "guard_paused 0\nguard_dry_run 0\n",
        "guard_paused 0\nguard_dry_run 0\n",
        "guard_paused 1\nguard_dry_run 0\n",
        "guard_paused 1\nguard_dry_run 0\n",
    ]
    idx = {'i': 0}

    def _fake_get_text(url, timeout=10):
        i = idx['i']
        idx['i'] = min(i + 1, len(payloads) - 1)
        return payloads[i]

    monkeypatch.setattr('src.deploy.rollout._http_get_text', _fake_get_text)

    ok, reasons, stats = monitor_metrics("http://x/metrics", minutes=0.01, thresholds=GateThresholds(), poll_sec=0)
    assert ok is False
    assert any(r.startswith('runtime_guard_paused') for r in reasons)
    assert stats['breach_counts'].get('runtime_guard_paused', 0) >= 2

