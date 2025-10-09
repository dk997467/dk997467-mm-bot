"""
Unit tests для performance tracer.
"""
import pytest
import time
from src.monitoring.tracer import PerformanceTracer, Trace, Span


def test_tracer_basic_span():
    """
    Test: tracer измеряет duration стадии.
    
    Acceptance:
    - Span имеет duration_ms > 0
    """
    tracer = PerformanceTracer(enabled=True, sample_rate=1.0)
    
    tracer.start_trace("test_trace_1")
    
    with tracer.span("stage_test"):
        time.sleep(0.01)  # 10ms
    
    trace = tracer.finish_trace()
    
    assert trace is not None
    assert len(trace.spans) == 1
    assert trace.spans[0].name == "stage_test"
    assert trace.spans[0].duration_ms >= 10.0
    print(f"[TEST] Stage duration: {trace.spans[0].duration_ms:.2f}ms")


def test_tracer_multiple_stages():
    """
    Test: tracer возвращает 5 ключей (5 стадий).
    
    Acceptance:
    - Trace содержит все 5 стадий
    - Каждая стадия имеет duration
    """
    tracer = PerformanceTracer(enabled=True, sample_rate=1.0)
    
    tracer.start_trace("test_trace_2")
    
    # 5 stages
    with tracer.span("stage_fetch_md"):
        time.sleep(0.005)
    
    with tracer.span("stage_spread"):
        time.sleep(0.003)
    
    with tracer.span("stage_guards"):
        time.sleep(0.002)
    
    with tracer.span("stage_emit"):
        time.sleep(0.008)
    
    with tracer.span("tick_total"):
        time.sleep(0.001)
    
    trace = tracer.finish_trace()
    
    assert trace is not None
    assert len(trace.spans) == 5
    
    stage_durations = trace.get_stage_durations()
    assert "stage_fetch_md" in stage_durations
    assert "stage_spread" in stage_durations
    assert "stage_guards" in stage_durations
    assert "stage_emit" in stage_durations
    assert "tick_total" in stage_durations
    
    print(f"[TEST] Stage durations: {stage_durations}")


def test_tracer_buffer_clear():
    """
    Test: буфер очищается после get_traces(clear=True).
    
    Acceptance:
    - После clear() буфер пуст
    """
    tracer = PerformanceTracer(enabled=True, sample_rate=1.0)
    
    # Create 3 traces
    for i in range(3):
        tracer.start_trace(f"trace_{i}")
        with tracer.span("stage_test"):
            time.sleep(0.001)
        tracer.finish_trace()
    
    # Get traces (clear=True)
    traces = tracer.get_traces(clear=True)
    assert len(traces) == 3
    
    # Get traces again (should be empty)
    traces2 = tracer.get_traces(clear=False)
    assert len(traces2) == 0
    print("[TEST] Buffer cleared successfully")


def test_tracer_sampling():
    """
    Test: сэмплинг работает (sample_rate=0.5).
    
    Acceptance:
    - Примерно 50% тиков трейсятся
    """
    tracer = PerformanceTracer(enabled=True, sample_rate=0.5)
    
    sampled_count = 0
    for i in range(100):
        if tracer.should_trace():
            sampled_count += 1
    
    # Should be ~50 (±10 tolerance)
    assert 40 <= sampled_count <= 60, f"Sampled {sampled_count}/100, expected ~50"
    print(f"[TEST] Sampled {sampled_count}/100 ticks (expected ~50)")


def test_tracer_overhead():
    """
    Test: накладные ≤ 3%.
    
    Acceptance:
    - Overhead < 3%
    """
    tracer = PerformanceTracer(enabled=True, sample_rate=1.0)
    
    # Run 100 ticks with tracing
    for i in range(100):
        tracer.start_trace(f"tick_{i}")
        
        with tracer.span("stage_fetch_md"):
            time.sleep(0.001)
        
        with tracer.span("stage_emit"):
            time.sleep(0.002)
        
        tracer.finish_trace()
    
    overhead_pct = tracer.get_overhead_pct()
    print(f"[TEST] Overhead: {overhead_pct:.2f}%")
    
    assert overhead_pct <= 3.0, f"Overhead {overhead_pct:.2f}% exceeds 3%"


def test_tracer_disabled():
    """
    Test: tracer выключен (enabled=false).
    
    Acceptance:
    - finish_trace() возвращает None
    - Overhead = 0%
    """
    tracer = PerformanceTracer(enabled=False, sample_rate=1.0)
    
    tracer.start_trace("test_trace")
    
    with tracer.span("stage_test"):
        time.sleep(0.01)
    
    trace = tracer.finish_trace()
    
    assert trace is None
    print("[TEST] Tracer disabled, no traces collected")


def test_tracer_percentiles():
    """
    Test: compute_percentiles корректно вычисляет p50, p95, p99.
    
    Acceptance:
    - Перцентили монотонно возрастают: p50 < p95 < p99
    """
    tracer = PerformanceTracer(enabled=True, sample_rate=1.0)
    
    # Create 100 traces with varying durations
    for i in range(100):
        tracer.start_trace(f"tick_{i}")
        
        # Variable duration (1-10ms)
        duration_ms = 0.001 * (1 + (i % 10))
        with tracer.span("stage_test"):
            time.sleep(duration_ms)
        
        tracer.finish_trace()
    
    percentiles = tracer.compute_percentiles("stage_test", [0.5, 0.95, 0.99])
    
    print(f"[TEST] Percentiles: p50={percentiles[0.5]:.2f}ms, p95={percentiles[0.95]:.2f}ms, p99={percentiles[0.99]:.2f}ms")
    
    # Monotonic increase
    assert percentiles[0.5] <= percentiles[0.95] <= percentiles[0.99]


def test_tracer_export_json():
    """
    Test: export_to_json создаёт детерминированный JSON.
    
    Acceptance:
    - JSON содержит trace_id, duration_ms, stage_durations
    """
    tracer = PerformanceTracer(enabled=True, sample_rate=1.0)
    
    tracer.start_trace("golden_trace_1", metadata={"symbols": ["BTCUSDT", "ETHUSDT"]})
    
    with tracer.span("stage_fetch_md"):
        time.sleep(0.005)
    
    with tracer.span("stage_emit"):
        time.sleep(0.008)
    
    trace = tracer.finish_trace()
    
    json_data = tracer.export_to_json(trace)
    
    assert "trace_id" in json_data
    assert "duration_ms" in json_data
    assert "stage_durations" in json_data
    assert "stage_fetch_md" in json_data["stage_durations"]
    assert "stage_emit" in json_data["stage_durations"]
    
    print(f"[TEST] JSON export: {json_data}")
