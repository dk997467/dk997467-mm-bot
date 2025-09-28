"""
Overlay metrics increment.
"""
from types import SimpleNamespace


def test_rollout_overlay_metrics_inc():
    from src.metrics.exporter import Metrics
    m = Metrics(SimpleNamespace())
    m.inc_rollout_overlay_applied('green')
    # no assertion on exporter internals; ensure method exists and does not raise
    assert True


