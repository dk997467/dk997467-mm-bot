"""
Unit tests for Prometheus metrics (tools/obs/metrics.py).

Tests:
- Counter: increment, get, render
- Gauge: set, inc, dec, get, render
- Histogram: observe, buckets, render
- Registry: register, get, render_prometheus
- Deterministic rendering (sorted keys/labels)
- Pre-registered global metrics
"""

from __future__ import annotations

import pytest

from tools.obs.metrics import (
    Counter,
    Gauge,
    Histogram,
    MetricsRegistry,
    get_registry,
    render_prometheus,
    ORDERS_PLACED,
    ORDERS_FILLED,
    FREEZE_EVENTS,
)


def test_counter_basic():
    """Test basic counter operations."""
    counter = Counter("test_counter", "Test counter", labels=("symbol",))
    
    counter.inc(symbol="BTCUSDT")
    assert counter.get(symbol="BTCUSDT") == 1.0
    
    counter.inc(amount=5.0, symbol="BTCUSDT")
    assert counter.get(symbol="BTCUSDT") == 6.0
    
    counter.inc(symbol="ETHUSDT")
    assert counter.get(symbol="ETHUSDT") == 1.0
    assert counter.get(symbol="BTCUSDT") == 6.0


def test_counter_render():
    """Test counter Prometheus rendering."""
    counter = Counter("requests_total", "Total requests", labels=("method",))
    
    counter.inc(method="GET")
    counter.inc(method="GET")
    counter.inc(method="POST")
    
    output = counter.render()
    
    assert "# HELP requests_total Total requests" in output
    assert "# TYPE requests_total counter" in output
    assert 'requests_total{method="GET"} 2' in output or 'requests_total{method="GET"} 2.0' in output
    assert 'requests_total{method="POST"} 1' in output or 'requests_total{method="POST"} 1.0' in output


def test_gauge_basic():
    """Test basic gauge operations."""
    gauge = Gauge("test_gauge", "Test gauge", labels=("symbol",))
    
    gauge.set(100.5, symbol="BTCUSDT")
    assert gauge.get(symbol="BTCUSDT") == 100.5
    
    gauge.inc(10.0, symbol="BTCUSDT")
    assert gauge.get(symbol="BTCUSDT") == 110.5
    
    gauge.dec(5.0, symbol="BTCUSDT")
    assert gauge.get(symbol="BTCUSDT") == 105.5


def test_gauge_render():
    """Test gauge Prometheus rendering."""
    gauge = Gauge("temperature_celsius", "Temperature in Celsius", labels=("location",))
    
    gauge.set(23.5, location="office")
    gauge.set(18.0, location="server_room")
    
    output = gauge.render()
    
    assert "# HELP temperature_celsius Temperature in Celsius" in output
    assert "# TYPE temperature_celsius gauge" in output
    assert 'temperature_celsius{location="office"} 23.5' in output
    assert 'temperature_celsius{location="server_room"} 18' in output or 'temperature_celsius{location="server_room"} 18.0' in output


def test_histogram_basic():
    """Test basic histogram operations."""
    histogram = Histogram(
        "response_time_ms",
        "Response time in ms",
        buckets=(10, 50, 100, 500),
        labels=("endpoint",),
    )
    
    histogram.observe(5.0, endpoint="/api")
    histogram.observe(25.0, endpoint="/api")
    histogram.observe(75.0, endpoint="/api")
    histogram.observe(600.0, endpoint="/api")
    
    assert histogram.get_count(endpoint="/api") == 4
    assert histogram.get_sum(endpoint="/api") == 705.0


def test_histogram_buckets():
    """Test histogram bucket counting."""
    histogram = Histogram(
        "latency_ms",
        "Latency in ms",
        buckets=(10, 50, 100),
        labels=(),
    )
    
    histogram.observe(5.0)   # <= 10
    histogram.observe(25.0)  # <= 50
    histogram.observe(75.0)  # <= 100
    histogram.observe(150.0) # > 100, only in +Inf
    
    # Render and check bucket counts
    output = histogram.render()
    
    # Bucket counts are cumulative
    # le="10" should have 1 (5.0)
    # le="50" should have 2 (5.0, 25.0)
    # le="100" should have 3 (5.0, 25.0, 75.0)
    # le="+Inf" should have 4 (all)
    
    assert 'latency_ms_bucket{le="10"} 1' in output or 'latency_ms_bucket{le="10"} 1.0' in output
    assert 'latency_ms_bucket{le="50"} 2' in output or 'latency_ms_bucket{le="50"} 2.0' in output
    assert 'latency_ms_bucket{le="100"} 3' in output or 'latency_ms_bucket{le="100"} 3.0' in output
    assert 'latency_ms_bucket{le="+Inf"} 4' in output


def test_histogram_render():
    """Test histogram Prometheus rendering."""
    histogram = Histogram(
        "request_duration_ms",
        "Request duration in ms",
        buckets=(1, 5, 10),
        labels=("method",),
    )
    
    histogram.observe(0.5, method="GET")
    histogram.observe(3.0, method="GET")
    histogram.observe(12.0, method="GET")
    
    output = histogram.render()
    
    assert "# HELP request_duration_ms Request duration in ms" in output
    assert "# TYPE request_duration_ms histogram" in output
    assert 'request_duration_ms_sum{method="GET"} 15.5' in output
    assert 'request_duration_ms_count{method="GET"} 3' in output


def test_registry_basic():
    """Test metrics registry."""
    registry = MetricsRegistry()
    
    counter = registry.register_counter("test_counter", "Test", labels=("type",))
    gauge = registry.register_gauge("test_gauge", "Test")
    
    counter.inc(type="a")
    gauge.set(42.0)
    
    assert registry.get("test_counter") is counter
    assert registry.get("test_gauge") is gauge


def test_registry_duplicate_name_error():
    """Test that registering duplicate name raises error."""
    registry = MetricsRegistry()
    
    registry.register_counter("duplicate", "First")
    
    with pytest.raises(ValueError, match="already registered"):
        registry.register_counter("duplicate", "Second")


def test_registry_render_prometheus():
    """Test rendering all metrics in Prometheus format."""
    registry = MetricsRegistry()
    
    counter = registry.register_counter("requests_total", "Total requests")
    gauge = registry.register_gauge("active_connections", "Active connections")
    
    counter.inc()
    counter.inc()
    gauge.set(5.0)
    
    output = registry.render_prometheus()
    
    # Should contain both metrics
    assert "requests_total" in output
    assert "active_connections" in output
    assert "# TYPE requests_total counter" in output
    assert "# TYPE active_connections gauge" in output


def test_registry_sorted_output():
    """Test that metrics are rendered in sorted order."""
    registry = MetricsRegistry()
    
    registry.register_counter("zebra_total", "Z metric")
    registry.register_counter("apple_total", "A metric")
    registry.register_counter("banana_total", "B metric")
    
    output = registry.render_prometheus()
    
    # Check order in output
    apple_pos = output.index("apple_total")
    banana_pos = output.index("banana_total")
    zebra_pos = output.index("zebra_total")
    
    assert apple_pos < banana_pos < zebra_pos


def test_global_registry():
    """Test global registry access."""
    registry = get_registry()
    
    # Should be able to access pre-registered metrics
    assert registry.get("mm_orders_placed_total") is not None
    assert registry.get("mm_freeze_events_total") is not None


def test_preregistered_metrics():
    """Test that pre-registered MM metrics exist."""
    # Should be accessible as module-level variables
    ORDERS_PLACED.inc(symbol="BTCUSDT")
    ORDERS_FILLED.inc(symbol="ETHUSDT")
    FREEZE_EVENTS.inc()
    
    # Should be in global registry
    registry = get_registry()
    output = registry.render_prometheus()
    
    assert "mm_orders_placed_total" in output
    assert "mm_orders_filled_total" in output
    assert "mm_freeze_events_total" in output


def test_counter_sorted_labels():
    """Test that counter labels are rendered in sorted order."""
    counter = Counter("test", "Test", labels=("symbol", "side"))
    
    counter.inc(symbol="BTC", side="buy")
    counter.inc(symbol="BTC", side="sell")
    counter.inc(symbol="ETH", side="buy")
    
    output = counter.render()
    
    # Labels should be in sorted order: BTC/buy, BTC/sell, ETH/buy
    btc_buy_pos = output.index('symbol="BTC",side="buy"')
    btc_sell_pos = output.index('symbol="BTC",side="sell"')
    eth_buy_pos = output.index('symbol="ETH",side="buy"')
    
    assert btc_buy_pos < btc_sell_pos < eth_buy_pos


def test_gauge_no_labels():
    """Test gauge without labels."""
    gauge = Gauge("simple_gauge", "Simple gauge")
    
    gauge.set(100.0)
    
    output = gauge.render()
    
    # Should not have curly braces (no labels)
    assert "simple_gauge 100" in output or "simple_gauge 100.0" in output
    assert "{" not in output.split("\n")[-2]  # Last non-empty line


def test_histogram_sorted_buckets():
    """Test that histogram buckets are sorted."""
    histogram = Histogram(
        "test",
        "Test",
        buckets=(500, 10, 100, 50),  # Unsorted input
        labels=(),
    )
    
    # Buckets should be sorted internally
    assert histogram.buckets == (10, 50, 100, 500)
    
    histogram.observe(25.0)
    
    output = histogram.render()
    
    # Should render in sorted order
    le10_pos = output.index('le="10"')
    le50_pos = output.index('le="50"')
    le100_pos = output.index('le="100"')
    le500_pos = output.index('le="500"')
    
    assert le10_pos < le50_pos < le100_pos < le500_pos

