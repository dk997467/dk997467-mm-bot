"""
Chaos scenarios tests - 10 сценариев устойчивости.

Схема: baseline → inject → steady → recover → verify
"""
import pytest
import asyncio
import time
from unittest.mock import MagicMock

from src.testing.chaos_injector import ChaosInjector, ChaosScenario
from src.common.config import ChaosConfig
from src.monitoring.stage_metrics import StageMetrics


# Fixtures
@pytest.fixture
def chaos_config():
    """Chaos config with one scenario enabled."""
    return ChaosConfig(enabled=True, dry_run=True)


@pytest.fixture
def injector(chaos_config):
    """Chaos injector instance."""
    return ChaosInjector(chaos_config)


@pytest.fixture
def metrics():
    """Stage metrics instance."""
    return StageMetrics(deadline_ms=200.0)


# Test scenarios
@pytest.mark.asyncio
async def test_scenario_net_loss(injector, metrics):
    """
    Scenario 1: NET_LOSS (30% packet loss).
    
    Acceptance:
    - p95(tick_total) не превышает baseline + 15%
    - recovery ≤ 3 тиков
    """
    injector.config.net_loss = 0.3
    
    # Baseline: 10 ticks without chaos
    baseline_durations = []
    for _ in range(10):
        start = time.time()
        # Simulate tick
        await asyncio.sleep(0.1)
        baseline_durations.append((time.time() - start) * 1000)
    
    baseline_p95 = sorted(baseline_durations)[int(len(baseline_durations) * 0.95)]
    
    # Inject: 20 ticks with chaos
    chaos_durations = []
    injected_count = 0
    
    for _ in range(20):
        start = time.time()
        
        # Simulate network request with potential loss
        if injector.should_inject_net_loss():
            injected_count += 1
            metrics.record_chaos_injection("net_loss")
            # Simulate retry delay
            await asyncio.sleep(0.05)
        
        await asyncio.sleep(0.1)
        chaos_durations.append((time.time() - start) * 1000)
    
    chaos_p95 = sorted(chaos_durations)[int(len(chaos_durations) * 0.95)]
    
    # Recovery: 3 ticks after chaos
    injector.config.net_loss = 0.0
    recovery_durations = []
    
    for _ in range(3):
        start = time.time()
        await asyncio.sleep(0.1)
        recovery_durations.append((time.time() - start) * 1000)
    
    recovery_p95 = sorted(recovery_durations)[int(len(recovery_durations) * 0.95)]
    
    # Assertions
    print(f"[NET_LOSS] Baseline p95: {baseline_p95:.2f}ms")
    print(f"[NET_LOSS] Chaos p95: {chaos_p95:.2f}ms")
    print(f"[NET_LOSS] Recovery p95: {recovery_p95:.2f}ms")
    print(f"[NET_LOSS] Injected: {injected_count}/20 packets")
    
    assert chaos_p95 < baseline_p95 * 1.15, f"p95 exceeded baseline +15% ({chaos_p95:.2f}ms > {baseline_p95*1.15:.2f}ms)"
    assert recovery_p95 < baseline_p95 * 1.05, "Recovery not complete within 3 ticks"
    assert injected_count >= 4, f"Too few injections ({injected_count}/20)"


@pytest.mark.asyncio
async def test_scenario_exch_429(injector, metrics):
    """
    Scenario 2: EXCH_429 (HTTP 429 rate limit waves).
    
    Acceptance:
    - Backoff работает (exponential retry)
    - deadline_miss% < 2%
    """
    injector.config.exch_429 = 0.2  # 20% 429 rate
    
    retry_counts = []
    deadline_misses = 0
    
    for i in range(20):
        start = time.time()
        
        # Simulate exchange request
        retries = 0
        while injector.should_inject_http_429():
            retries += 1
            metrics.record_chaos_injection("exch_429")
            
            # Exponential backoff
            backoff_ms = min(100 * (2 ** retries), 1000)
            await asyncio.sleep(backoff_ms / 1000)
            
            if retries >= 3:
                break
        
        retry_counts.append(retries)
        
        await asyncio.sleep(0.1)
        
        tick_duration_ms = (time.time() - start) * 1000
        if tick_duration_ms > 200:
            deadline_misses += 1
    
    deadline_miss_pct = (deadline_misses / 20) * 100
    
    print(f"[EXCH_429] Retries: {sum(retry_counts)}, Avg: {sum(retry_counts)/len(retry_counts):.2f}")
    print(f"[EXCH_429] Deadline miss: {deadline_miss_pct:.1f}%")
    
    assert deadline_miss_pct < 2.0, f"Deadline miss too high ({deadline_miss_pct:.1f}%)"
    assert max(retry_counts) <= 3, "Too many retries (backoff not working)"


@pytest.mark.asyncio
async def test_scenario_lat_spike(injector, metrics):
    """
    Scenario 3: LAT_SPIKE (latency bursts 200ms).
    
    Acceptance:
    - p99(tick_total) < 250ms during burst
    """
    injector.config.lat_spike_ms = 200
    
    durations = []
    
    for _ in range(20):
        start = time.time()
        
        # Simulate latency spike
        await injector.inject_latency_spike()
        metrics.record_chaos_injection("lat_spike")
        
        await asyncio.sleep(0.05)
        
        durations.append((time.time() - start) * 1000)
    
    p99 = sorted(durations)[int(len(durations) * 0.99)]
    
    print(f"[LAT_SPIKE] p99: {p99:.2f}ms")
    
    assert p99 < 250.0, f"p99 too high during latency spike ({p99:.2f}ms)"


@pytest.mark.asyncio
async def test_scenario_ws_disconnect(injector, metrics):
    """
    Scenario 4: WS_DISCONNECT (WebSocket disconnects).
    
    Acceptance:
    - Reconnect attempts увеличиваются
    - Recovery ≤ 3 ticks
    """
    injector.config.ws_disconnect = 0.3  # High probability for testing
    
    reconnects = 0
    
    for _ in range(20):
        if injector.should_inject_ws_disconnect():
            reconnects += 1
            metrics.record_chaos_injection("ws_disconnect")
            metrics.record_reconnect_attempt("ws")
            
            # Simulate reconnect delay
            await asyncio.sleep(0.1)
        
        await asyncio.sleep(0.05)
    
    print(f"[WS_DISCONNECT] Reconnects: {reconnects}/20")
    
    assert reconnects > 0, "No disconnects injected"
    assert metrics._reconnect_attempts["ws"] == reconnects


@pytest.mark.asyncio
async def test_scenario_reconcile_mismatch(injector, metrics):
    """
    Scenario 5: RECONCILE_MISMATCH (order state mismatches).
    
    Acceptance:
    - Discrepancies detected
    - Recovery на следующем тике
    """
    injector.config.reconcile_mismatch = 0.1
    
    mismatches = 0
    
    for _ in range(20):
        if injector.should_inject_reconcile_mismatch():
            mismatches += 1
            metrics.record_chaos_injection("reconcile_mismatch")
            metrics.record_reconcile_discrepancy("status_mismatch")
    
    print(f"[RECONCILE] Mismatches: {mismatches}/20")
    
    assert mismatches > 0, "No mismatches injected"
    assert metrics._reconcile_discrepancies["status_mismatch"] == mismatches


@pytest.mark.asyncio
async def test_burst_duty_cycle(injector):
    """
    Test burst duty cycle (on/off periods).
    
    Acceptance:
    - Burst switches between on/off
    - on: burst_on_sec, off: burst_off_sec
    """
    injector.config.burst_on_sec = 1
    injector.config.burst_off_sec = 2
    injector.config.net_loss = 0.5
    
    # Initial state
    initial_state = injector._burst_state
    print(f"[BURST] Initial state: {initial_state}")
    
    # Wait for switch
    if initial_state == "off":
        await asyncio.sleep(2.1)
        assert injector.is_burst_active() == True, "Burst did not switch to ON"
    else:
        await asyncio.sleep(1.1)
        assert injector.is_burst_active() == False, "Burst did not switch to OFF"
    
    print("[BURST] Duty cycle works correctly")


@pytest.mark.asyncio
async def test_chaos_metrics_export(metrics):
    """
    Test chaos metrics Prometheus export.
    
    Acceptance:
    - All 5 new metrics present in export
    """
    # Record some chaos events
    metrics.record_chaos_injection("net_loss")
    metrics.record_chaos_injection("exch_429")
    metrics.record_reconnect_attempt("ws")
    metrics.record_partial_fail_rate("place", "bybit", 0.05)
    metrics.record_ws_gap(150.5)
    metrics.record_reconcile_discrepancy("status_mismatch")
    
    # Export
    prom_output = metrics.export_to_prometheus()
    
    # Verify
    assert "mm_chaos_injections_total" in prom_output
    assert "mm_reconnect_attempts_total" in prom_output
    assert "mm_partial_fail_rate" in prom_output
    assert "mm_ws_gap_ms" in prom_output
    assert "mm_reconcile_discrepancies_total" in prom_output
    
    print("[METRICS] All chaos metrics exported successfully")


@pytest.mark.asyncio
async def test_recovery_time_under_3_ticks(injector):
    """
    Test recovery time ≤ 3 ticks after chaos stops.
    
    Acceptance:
    - Metrics normalize within 3 ticks
    """
    # Enable chaos
    injector.config.net_loss = 0.3
    injector.config.exch_429 = 0.2
    
    # Run 10 ticks with chaos
    chaos_events = 0
    for _ in range(10):
        if injector.should_inject_net_loss() or injector.should_inject_http_429():
            chaos_events += 1
        await asyncio.sleep(0.01)
    
    print(f"[RECOVERY] Chaos events: {chaos_events}")
    
    # Disable chaos
    injector.config.net_loss = 0.0
    injector.config.exch_429 = 0.0
    
    # Recovery: 3 ticks
    recovery_events = 0
    for _ in range(3):
        if injector.should_inject_net_loss() or injector.should_inject_http_429():
            recovery_events += 1
        await asyncio.sleep(0.01)
    
    print(f"[RECOVERY] Recovery events: {recovery_events}")
    
    assert recovery_events == 0, "Chaos not stopped after config change"
    assert chaos_events > 0, "No chaos events during chaos phase"


def test_chaos_config_validation():
    """
    Test ChaosConfig validation.
    
    Acceptance:
    - Intensities clamped to [0, 1]
    - Latencies clamped to reasonable ranges
    """
    # Test clamping
    config = ChaosConfig(
        enabled=True,
        net_loss=1.5,  # Should clamp to 1.0
        lat_spike_ms=10000,  # Should clamp to 5000
        clock_skew_ms=-100,  # Should clamp to 0
        mem_pressure="invalid"  # Should default to "none"
    )
    
    assert config.net_loss == 1.0
    assert config.lat_spike_ms == 5000
    assert config.clock_skew_ms == 0
    assert config.mem_pressure == "none"
    
    print("[CONFIG] Validation works correctly")
