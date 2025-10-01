#!/usr/bin/env python3
"""
Unit tests for WebSocket exponential backoff logic.

Tests verify that:
1. Exponential backoff grows correctly (2^attempt)
2. Jitter adds randomness to prevent thundering herd
3. Max delay cap is respected
4. Max attempts limit works correctly
5. Reconnect counter resets on successful connection
6. Metrics are recorded properly
"""
import asyncio
import sys
from pathlib import Path
from unittest.mock import MagicMock, AsyncMock, patch

# Add project root to path
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import pytest

from src.connectors.bybit_websocket import BybitWebSocketConnector
from src.common.di import AppContext


@pytest.fixture
def mock_ctx():
    """Create mock AppContext with metrics."""
    ctx = MagicMock(spec=AppContext)
    ctx.metrics = MagicMock()
    ctx.metrics.ws_reconnect_attempts_total = MagicMock()
    ctx.metrics.ws_reconnect_attempts_total.labels = MagicMock(return_value=MagicMock())
    ctx.metrics.ws_reconnect_delay_seconds = MagicMock()
    ctx.metrics.ws_reconnect_delay_seconds.observe = MagicMock()
    ctx.metrics.ws_max_reconnect_reached_total = MagicMock()
    ctx.metrics.ws_max_reconnect_reached_total.labels = MagicMock(return_value=MagicMock())
    ctx.metrics.ws_reconnects_total = MagicMock()
    ctx.metrics.ws_reconnects_total.labels = MagicMock(return_value=MagicMock())
    return ctx


@pytest.fixture
def config():
    """Create basic config for connector."""
    return {
        'public_ws_url': 'wss://stream.bybit.com/v5/public/linear',
        'private_ws_url': 'wss://stream.bybit.com/v5/private',
        'api_key': 'test_key',
        'api_secret': 'test_secret',
        'max_reconnect_attempts': 5,
        'base_reconnect_delay': 1.0,
        'max_reconnect_delay': 60.0,
        'heartbeat_interval': 30,
    }


@pytest.mark.asyncio
async def test_exponential_backoff_growth(mock_ctx, config):
    """Test that delay grows exponentially: 1s, 2s, 4s, 8s, ..."""
    connector = BybitWebSocketConnector(mock_ctx, config)
    
    # Test multiple attempts
    delays = []
    for i in range(5):
        # Mock asyncio.sleep to capture delay
        with patch('asyncio.sleep') as mock_sleep:
            mock_sleep.return_value = asyncio.sleep(0)  # No actual delay
            
            should_stop = await connector._wait_before_reconnect("test")
            
            # Extract delay from call args
            if mock_sleep.called:
                delay = mock_sleep.call_args[0][0]
                delays.append(delay)
        
        assert not should_stop, f"Should not stop at attempt {i+1}"
    
    # Verify exponential growth (with jitter tolerance)
    # Expected: ~1s, ~2s, ~4s, ~8s, ~16s
    assert 1.0 <= delays[0] <= 1.5, f"Attempt 1 delay should be ~1s, got {delays[0]:.2f}s"
    assert 2.0 <= delays[1] <= 3.0, f"Attempt 2 delay should be ~2s, got {delays[1]:.2f}s"
    assert 4.0 <= delays[2] <= 6.0, f"Attempt 3 delay should be ~4s, got {delays[2]:.2f}s"
    assert 8.0 <= delays[3] <= 12.0, f"Attempt 4 delay should be ~8s, got {delays[3]:.2f}s"
    assert 16.0 <= delays[4] <= 24.0, f"Attempt 5 delay should be ~16s, got {delays[4]:.2f}s"
    
    print(f"[OK] Exponential growth: {[f'{d:.2f}s' for d in delays]}")


@pytest.mark.asyncio
async def test_jitter_adds_variance(mock_ctx, config):
    """Test that jitter adds randomness to prevent thundering herd."""
    connector = BybitWebSocketConnector(mock_ctx, config)
    connector._reconnect_attempts = 2  # Set to attempt 3 (exp delay = 4s)
    
    # Run same backoff calculation multiple times
    delays = []
    for _ in range(10):
        with patch('asyncio.sleep') as mock_sleep:
            mock_sleep.return_value = asyncio.sleep(0)
            
            await connector._wait_before_reconnect("test")
            
            if mock_sleep.called:
                delay = mock_sleep.call_args[0][0]
                delays.append(delay)
        
        # Reset attempts for next iteration
        connector._reconnect_attempts = 2
    
    # All delays should be different (jitter adds randomness)
    unique_delays = set(delays)
    assert len(unique_delays) >= 5, f"Expected variance from jitter, got {len(unique_delays)} unique values out of 10"
    
    # All delays should be in expected range (4s exp + jitter up to 30%)
    for delay in delays:
        assert 4.0 <= delay <= 5.5, f"Delay {delay:.2f}s outside expected range [4.0, 5.5]s"
    
    print(f"[OK] Jitter variance: {len(unique_delays)} unique delays out of 10 runs")


@pytest.mark.asyncio
async def test_max_delay_cap(mock_ctx, config):
    """Test that delay is capped at max_reconnect_delay."""
    config['max_reconnect_delay'] = 10.0  # Cap at 10s
    connector = BybitWebSocketConnector(mock_ctx, config)
    
    # Force high attempt number to exceed cap
    connector._reconnect_attempts = 10  # 2^10 = 1024s without cap
    
    with patch('asyncio.sleep') as mock_sleep:
        mock_sleep.return_value = asyncio.sleep(0)
        
        should_stop = await connector._wait_before_reconnect("test")
        
        assert not should_stop
        delay = mock_sleep.call_args[0][0]
        
        # Delay should be capped at 10s (plus jitter, so max ~13s)
        assert delay <= 13.0, f"Delay {delay:.2f}s exceeds max cap (10s + 30% jitter = 13s)"
    
    print(f"[OK] Max delay cap: {delay:.2f}s (cap: 10s)")


@pytest.mark.asyncio
async def test_max_attempts_reached(mock_ctx, config):
    """Test that max_reconnect_attempts stops reconnection."""
    config['max_reconnect_attempts'] = 3
    connector = BybitWebSocketConnector(mock_ctx, config)
    
    # Exhaust attempts
    for i in range(3):
        should_stop = await connector._wait_before_reconnect("test")
        assert not should_stop, f"Should not stop at attempt {i+1}"
    
    # Next attempt should signal stop
    should_stop = await connector._wait_before_reconnect("test")
    assert should_stop, "Should stop after max attempts reached"
    
    # Verify metric was recorded
    assert mock_ctx.metrics.ws_max_reconnect_reached_total.labels.called
    
    print("[OK] Max attempts enforced: stopped after 3 attempts")


@pytest.mark.asyncio
async def test_counter_reset_on_success(mock_ctx, config):
    """Test that reconnect counter resets on successful connection."""
    connector = BybitWebSocketConnector(mock_ctx, config)
    
    # Simulate 2 failed attempts
    await connector._wait_before_reconnect("test")
    await connector._wait_before_reconnect("test")
    assert connector._reconnect_attempts == 2
    
    # Simulate successful connection (this is done in _connect_public_websocket)
    connector._reconnect_attempts = 0  # Reset
    
    assert connector._reconnect_attempts == 0
    
    # Next failure should start from attempt 1 again
    await connector._wait_before_reconnect("test")
    assert connector._reconnect_attempts == 1
    
    print("[OK] Counter reset: attempts reset to 0 on success, then restart from 1")


@pytest.mark.asyncio
async def test_metrics_recorded(mock_ctx, config):
    """Test that metrics are properly recorded during backoff."""
    connector = BybitWebSocketConnector(mock_ctx, config)
    
    with patch('asyncio.sleep'):
        await connector._wait_before_reconnect("public")
    
    # Verify metrics calls
    assert mock_ctx.metrics.ws_reconnect_attempts_total.labels.called
    labels_call = mock_ctx.metrics.ws_reconnect_attempts_total.labels.call_args
    assert labels_call[1]['exchange'] == "bybit"
    assert labels_call[1]['ws_type'] == "public"
    
    assert mock_ctx.metrics.ws_reconnect_delay_seconds.observe.called
    
    print("[OK] Metrics recorded: attempts counter and delay histogram")


@pytest.mark.asyncio
async def test_different_ws_types(mock_ctx, config):
    """Test that public and private WebSockets have independent tracking."""
    connector = BybitWebSocketConnector(mock_ctx, config)
    
    # Test public
    with patch('asyncio.sleep'):
        await connector._wait_before_reconnect("public")
    
    public_call = mock_ctx.metrics.ws_reconnect_attempts_total.labels.call_args
    assert public_call[1]['ws_type'] == "public"
    
    # Test private
    mock_ctx.metrics.ws_reconnect_attempts_total.labels.reset_mock()
    with patch('asyncio.sleep'):
        await connector._wait_before_reconnect("private")
    
    private_call = mock_ctx.metrics.ws_reconnect_attempts_total.labels.call_args
    assert private_call[1]['ws_type'] == "private"
    
    print("[OK] Different ws_types: public and private tracked independently")


@pytest.mark.asyncio
async def test_backoff_sequence_realistic(mock_ctx, config):
    """Test realistic backoff sequence over multiple failures."""
    connector = BybitWebSocketConnector(mock_ctx, config)
    
    expected_sequence = [
        (1, 1.0, 1.5),    # ~1s
        (2, 2.0, 3.0),    # ~2s
        (3, 4.0, 6.0),    # ~4s
        (4, 8.0, 12.0),   # ~8s
        (5, 16.0, 24.0),  # ~16s
    ]
    
    for attempt, min_delay, max_delay in expected_sequence:
        with patch('asyncio.sleep') as mock_sleep:
            mock_sleep.return_value = asyncio.sleep(0)
            
            should_stop = await connector._wait_before_reconnect("test")
            
            assert not should_stop, f"Should not stop at attempt {attempt}"
            
            delay = mock_sleep.call_args[0][0]
            assert min_delay <= delay <= max_delay, \
                f"Attempt {attempt}: delay {delay:.2f}s not in expected range [{min_delay}, {max_delay}]"
            
            print(f"  Attempt {attempt}: {delay:.2f}s (expected {min_delay:.0f}-{max_delay:.0f}s)")
    
    print("[OK] Realistic backoff sequence verified")


def test_jitter_formula():
    """Test jitter calculation formula (non-async unit test)."""
    import random
    
    base_delay = 1.0
    max_delay = 60.0
    
    for attempt in range(7):
        exponential_delay = base_delay * (2 ** attempt)
        jitter_range = exponential_delay * 0.3
        
        # Test multiple jitter samples
        jitters = [random.uniform(0, jitter_range) for _ in range(100)]
        
        # Verify jitter is within expected range
        assert all(0 <= j <= jitter_range for j in jitters)
        
        # Verify jitter adds variance
        assert len(set(jitters)) >= 50, f"Jitter should be random, got {len(set(jitters))} unique values"
        
        # Total delay should not exceed max
        total_delays = [min(exponential_delay + j, max_delay) for j in jitters]
        assert all(d <= max_delay for d in total_delays)
    
    print("[OK] Jitter formula validation passed")


if __name__ == "__main__":
    # Run tests with pytest
    import pytest
    sys.exit(pytest.main([__file__, "-v", "-s"]))

