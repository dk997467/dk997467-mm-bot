"""
Unit tests для stage metrics.
"""
import pytest
from src.monitoring.stage_metrics import StageMetrics
from src.monitoring.tracer import Trace, Span


def test_metrics_record_trace():
    """
    Test: metrics записывает trace.
    
    Acceptance:
    - total_ticks увеличивается
    - stage_durations заполняются
    """
    metrics = StageMetrics(deadline_ms=200.0)
    
    # Create trace
    trace = Trace(trace_id="test_1", start_ns=0)
    trace.spans.append(Span(name="stage_fetch_md", start_ns=0, end_ns=50_000_000))
    trace.spans[-1].duration_ms = 50.0
    trace.spans.append(Span(name="stage_emit", start_ns=50_000_000, end_ns=150_000_000))
    trace.spans[-1].duration_ms = 100.0
    trace.end_ns = 150_000_000
    
    metrics.record_trace(trace)
    
    assert metrics._total_ticks == 1
    assert "stage_fetch_md" in metrics._stage_durations
    assert "stage_emit" in metrics._stage_durations
    print("[TEST] Trace recorded successfully")


def test_metrics_deadline_miss():
    """
    Test: deadline miss tracking.
    
    Acceptance:
    - deadline_miss_pct < 2% для canary
    """
    metrics = StageMetrics(deadline_ms=200.0)
    
    # 100 ticks: 98 within deadline, 2 over deadline
    for i in range(98):
        trace = Trace(trace_id=f"tick_{i}", start_ns=0)
        trace.end_ns = 150_000_000  # 150ms (within deadline)
        metrics.record_trace(trace)
    
    for i in range(2):
        trace = Trace(trace_id=f"tick_slow_{i}", start_ns=0)
        trace.end_ns = 250_000_000  # 250ms (over deadline)
        metrics.record_trace(trace)
    
    deadline_miss_pct = metrics.get_deadline_miss_pct()
    
    print(f"[TEST] Deadline miss: {deadline_miss_pct:.2f}%")
    assert deadline_miss_pct == 2.0
    assert deadline_miss_pct < 2.5  # Canary threshold


def test_metrics_guard_trips():
    """
    Test: guard trip tracking.
    
    Acceptance:
    - Guard trips counter работает
    """
    metrics = StageMetrics()
    
    metrics.record_guard_trip("vol_soft")
    metrics.record_guard_trip("vol_soft")
    metrics.record_guard_trip("latency_hard")
    
    summary = metrics.get_summary()
    
    assert summary["guard_trips"]["vol_soft"] == 2
    assert summary["guard_trips"]["latency_hard"] == 1
    print(f"[TEST] Guard trips: {summary['guard_trips']}")


def test_metrics_percentiles():
    """
    Test: stage percentiles вычисляются корректно.
    
    Acceptance:
    - p50 < p95 < p99
    """
    metrics = StageMetrics()
    
    # 100 traces with varying durations
    for i in range(100):
        trace = Trace(trace_id=f"tick_{i}", start_ns=0)
        duration_ms = 50.0 + i  # 50-150ms
        trace.spans.append(Span(name="stage_test", start_ns=0, end_ns=int(duration_ms * 1_000_000)))
        trace.spans[-1].duration_ms = duration_ms
        trace.end_ns = int(duration_ms * 1_000_000)
        metrics.record_trace(trace)
    
    percentiles = metrics.get_stage_percentiles("stage_test", [0.5, 0.95, 0.99])
    
    print(f"[TEST] Percentiles: p50={percentiles[0.5]:.2f}ms, p95={percentiles[0.95]:.2f}ms, p99={percentiles[0.99]:.2f}ms")
    
    assert percentiles[0.5] < percentiles[0.95] < percentiles[0.99]


def test_metrics_summary():
    """
    Test: summary содержит все ключи.
    
    Acceptance:
    - Summary имеет total_ticks, deadline_miss_pct, stage_percentiles
    """
    metrics = StageMetrics()
    
    # Create 10 traces
    for i in range(10):
        trace = Trace(trace_id=f"tick_{i}", start_ns=0)
        trace.spans.append(Span(name=StageMetrics.STAGE_FETCH_MD, start_ns=0, end_ns=50_000_000))
        trace.spans[-1].duration_ms = 50.0
        trace.end_ns = 50_000_000
        metrics.record_trace(trace)
    
    summary = metrics.get_summary()
    
    assert "total_ticks" in summary
    assert "deadline_miss_pct" in summary
    assert "stage_percentiles" in summary
    assert "guard_trips" in summary
    
    assert summary["total_ticks"] == 10
    print(f"[TEST] Summary: {summary}")


def test_metrics_reset():
    """
    Test: reset() очищает все метрики.
    
    Acceptance:
    - После reset() total_ticks = 0
    """
    metrics = StageMetrics()
    
    # Add some data
    trace = Trace(trace_id="test", start_ns=0)
    trace.end_ns = 100_000_000
    metrics.record_trace(trace)
    metrics.record_guard_trip("vol_soft")
    
    assert metrics._total_ticks == 1
    
    # Reset
    metrics.reset()
    
    assert metrics._total_ticks == 0
    assert len(metrics._stage_durations) == 0
    assert len(metrics._guard_trips) == 0
    print("[TEST] Metrics reset successfully")


def test_metrics_prometheus_export():
    """
    Test: export_to_prometheus создаёт корректный формат.
    
    Acceptance:
    - Output содержит "# HELP", "# TYPE", metric names
    """
    metrics = StageMetrics()
    
    # Add some data
    trace = Trace(trace_id="test", start_ns=0)
    trace.spans.append(Span(name=StageMetrics.STAGE_TICK_TOTAL, start_ns=0, end_ns=150_000_000))
    trace.spans[-1].duration_ms = 150.0
    trace.end_ns = 150_000_000
    metrics.record_trace(trace)
    metrics.record_guard_trip("vol_soft")
    
    prom_output = metrics.export_to_prometheus()
    
    assert "# HELP mm_stage_duration_ms" in prom_output
    assert "# TYPE mm_stage_duration_ms histogram" in prom_output
    assert "mm_guard_trips_total" in prom_output
    assert "mm_tick_deadline_miss_total" in prom_output
    
    print(f"[TEST] Prometheus export:\n{prom_output}")
