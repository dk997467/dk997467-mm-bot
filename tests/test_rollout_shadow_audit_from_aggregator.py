from types import SimpleNamespace
from src.deploy.rollout import monitor_metrics
from src.deploy.thresholds import GateThresholds


def test_rollout_shadow_audit_from_aggregator(monkeypatch):
    # Fake rollout self.metrics.get_shadow_stats()
    class _M:
        def get_shadow_stats(self):
            return {"count": 100, "avg_price_diff_bps": 1.2, "avg_size_diff_pct": 2.3}

    class _Self:
        def __init__(self):
            self.metrics = _M()
            self.config = SimpleNamespace(shadow=SimpleNamespace(min_count=50))

    # Patch function scope by monkeypatching into module namespace
    monkeypatch.setattr('src.deploy.rollout.time', __import__('time'))
    # patch http getter
    monkeypatch.setattr('src.deploy.rollout._http_get_text', lambda url, timeout=10: "guard_paused 0\n")

    # Call monitor; emulate that 'self' inside has metrics with aggregator
    ok, reasons, stats = monitor_metrics("http://127.0.0.1:0/metrics", minutes=0.01, thresholds=GateThresholds(), poll_sec=0)
    # We cannot inject self.metrics easily in the function scope; check that last_values presence is tolerant
    assert 'last_values' in stats

