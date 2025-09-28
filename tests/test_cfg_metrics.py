import pytest

from src.common.config import AppConfig
from src.metrics.exporter import MetricsExporter


class DummyRecorder:
    async def record_custom_event(self, *args, **kwargs):
        return None


def test_export_cfg_gauges(monkeypatch):
    """Test that config gauges are exported correctly."""
    # Clear Prometheus registry
    from prometheus_client import REGISTRY
    REGISTRY._collector_to_names.clear()
    REGISTRY._names_to_collectors.clear()
    
    cfg = AppConfig()
    m = MetricsExporter(cfg, DummyRecorder())
    
    # Create Metrics instance and set it
    from src.common.di import AppContext
    from src.metrics.exporter import Metrics
    ctx = AppContext(cfg=cfg)
    metrics = Metrics(ctx)
    m.set_metrics(metrics)
    
    # Test that config gauges are exported
    m.export_cfg_gauges(cfg)
    
    # Basic sanity: Metrics instance should exist and config gauges should exist
    assert hasattr(m, 'metrics')
    assert m.metrics is not None
    assert hasattr(m.metrics, 'cfg_levels_per_side')
    assert hasattr(m.metrics, 'cfg_k_vola_spread')


def test_metrics_class_cfg_gauges():
    """Test that Metrics class exports config gauges correctly."""
    # Clear Prometheus registry
    from prometheus_client import REGISTRY
    REGISTRY._collector_to_names.clear()
    REGISTRY._names_to_collectors.clear()
    
    from src.common.di import AppContext
    from src.metrics.exporter import Metrics
    
    cfg = AppConfig()
    ctx = AppContext(cfg=cfg)
    metrics = Metrics(ctx)
    
    # Test that config gauges exist and can be updated
    assert metrics.cfg_levels_per_side is not None
    assert metrics.cfg_k_vola_spread is not None
    assert metrics.cfg_skew_coeff is not None
    assert metrics.cfg_imbalance_cutoff is not None
    assert metrics.cfg_max_create_per_sec is not None
    assert metrics.cfg_max_cancel_per_sec is not None
    
    # Test that export_cfg_gauges method works
    metrics.export_cfg_gauges(cfg)
    # Should not raise any exceptions

