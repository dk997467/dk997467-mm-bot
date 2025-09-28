"""
Test-friendly metrics registry stub.
"""


class DummyGauge:
    """Dummy gauge that does nothing."""
    
    def labels(self, **kwargs):
        return self
    
    def set(self, value):
        pass


class DummyCounter:
    """Dummy counter that does nothing."""
    
    def labels(self, **kwargs):
        return self
    
    def inc(self, amount=1.0):
        pass


class DummyMetricsRegistry:
    """Dummy metrics registry for testing."""
    
    def gauge(self, name: str, description: str = "", labelnames=None):
        return DummyGauge()
    
    def counter(self, name: str, description: str = "", labelnames=None):
        return DummyCounter()
