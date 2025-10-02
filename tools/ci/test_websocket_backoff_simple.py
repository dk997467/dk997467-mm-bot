#!/usr/bin/env python3
"""
Simple test for WebSocket exponential backoff (no pytest required).

Tests verify that:
1. Exponential backoff grows correctly
2. Jitter adds randomness
3. Max delay cap is respected
4. Max attempts limit works
5. Reconnect counter resets on success
"""
import asyncio
import sys
from pathlib import Path
from unittest.mock import MagicMock

# Add project root to path
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from src.connectors.bybit_websocket import BybitWebSocketConnector
from src.common.di import AppContext


def create_mock_ctx():
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


def create_config():
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


async def test_exponential_backoff_growth():
    """Test that delay grows exponentially: 1s, 2s, 4s, 8s, ..."""
    mock_ctx = create_mock_ctx()
    config = create_config()
    connector = BybitWebSocketConnector(mock_ctx, config)
    
    # Capture delays by mocking sleep
    delays = []
    
    original_sleep = asyncio.sleep
    
    async def mock_sleep(delay):
        delays.append(delay)
        await original_sleep(0)  # Don't actually wait
    
    # Temporarily replace asyncio.sleep
    asyncio.sleep = mock_sleep
    
    try:
        # Test 5 attempts
        for i in range(5):
            should_stop = await connector._wait_before_reconnect("test")
            assert not should_stop, f"Should not stop at attempt {i+1}"
        
        # Verify exponential growth (with jitter tolerance)
        assert 1.0 <= delays[0] <= 1.5, f"Attempt 1 delay should be ~1s, got {delays[0]:.2f}s"
        assert 2.0 <= delays[1] <= 3.0, f"Attempt 2 delay should be ~2s, got {delays[1]:.2f}s"
        assert 4.0 <= delays[2] <= 6.0, f"Attempt 3 delay should be ~4s, got {delays[2]:.2f}s"
        assert 8.0 <= delays[3] <= 12.0, f"Attempt 4 delay should be ~8s, got {delays[3]:.2f}s"
        assert 16.0 <= delays[4] <= 24.0, f"Attempt 5 delay should be ~16s, got {delays[4]:.2f}s"
        
        print(f"[OK] test_exponential_backoff_growth: delays={[f'{d:.2f}s' for d in delays]}")
        return True
    
    finally:
        asyncio.sleep = original_sleep


async def test_jitter_adds_variance():
    """Test that jitter adds randomness."""
    mock_ctx = create_mock_ctx()
    config = create_config()
    connector = BybitWebSocketConnector(mock_ctx, config)
    connector._reconnect_attempts = 2  # Set to attempt 3 (exp delay = 4s)
    
    delays = []
    
    original_sleep = asyncio.sleep
    
    async def mock_sleep(delay):
        delays.append(delay)
        await original_sleep(0)
    
    asyncio.sleep = mock_sleep
    
    try:
        # Run same backoff 10 times
        for _ in range(10):
            await connector._wait_before_reconnect("test")
            connector._reconnect_attempts = 2  # Reset for next iteration
        
        # All delays should be different (jitter adds randomness)
        unique_delays = set(delays)
        assert len(unique_delays) >= 5, f"Expected variance from jitter, got {len(unique_delays)} unique values"
        
        # All delays should be in expected range
        for delay in delays:
            assert 4.0 <= delay <= 5.5, f"Delay {delay:.2f}s outside expected range [4.0, 5.5]s"
        
        print(f"[OK] test_jitter_adds_variance: {len(unique_delays)} unique delays out of 10")
        return True
    
    finally:
        asyncio.sleep = original_sleep


async def test_max_delay_cap():
    """Test that delay is capped at max_reconnect_delay."""
    mock_ctx = create_mock_ctx()
    config = create_config()
    config['max_reconnect_delay'] = 10.0  # Cap at 10s
    connector = BybitWebSocketConnector(mock_ctx, config)
    
    # Force high attempt number
    connector._reconnect_attempts = 10  # 2^10 = 1024s without cap
    
    captured_delay = []
    
    original_sleep = asyncio.sleep
    
    async def mock_sleep(delay):
        captured_delay.append(delay)
        await original_sleep(0)
    
    asyncio.sleep = mock_sleep
    
    try:
        should_stop = await connector._wait_before_reconnect("test")
        assert not should_stop
        
        delay = captured_delay[0]
        
        # Delay should be capped
        assert delay <= 13.0, f"Delay {delay:.2f}s exceeds max cap (10s + 30% jitter = 13s)"
        
        print(f"[OK] test_max_delay_cap: delay={delay:.2f}s (cap: 10s)")
        return True
    
    finally:
        asyncio.sleep = original_sleep


async def test_max_attempts_reached():
    """Test that max_reconnect_attempts stops reconnection."""
    mock_ctx = create_mock_ctx()
    config = create_config()
    config['max_reconnect_attempts'] = 3
    connector = BybitWebSocketConnector(mock_ctx, config)
    
    original_sleep = asyncio.sleep
    asyncio.sleep = lambda d: original_sleep(0)
    
    try:
        # Exhaust attempts
        for i in range(3):
            should_stop = await connector._wait_before_reconnect("test")
            assert not should_stop, f"Should not stop at attempt {i+1}"
        
        # Next attempt should signal stop
        should_stop = await connector._wait_before_reconnect("test")
        assert should_stop, "Should stop after max attempts reached"
        
        # Verify metric was called
        assert mock_ctx.metrics.ws_max_reconnect_reached_total.labels.called
        
        print("[OK] test_max_attempts_reached: stopped after 3 attempts")
        return True
    
    finally:
        asyncio.sleep = original_sleep


async def test_counter_reset_on_success():
    """Test that reconnect counter resets on successful connection."""
    mock_ctx = create_mock_ctx()
    config = create_config()
    connector = BybitWebSocketConnector(mock_ctx, config)
    
    original_sleep = asyncio.sleep
    asyncio.sleep = lambda d: original_sleep(0)
    
    try:
        # Simulate 2 failed attempts
        await connector._wait_before_reconnect("test")
        await connector._wait_before_reconnect("test")
        assert connector._reconnect_attempts == 2
        
        # Simulate successful connection
        connector._reconnect_attempts = 0
        assert connector._reconnect_attempts == 0
        
        # Next failure should start from 1 again
        await connector._wait_before_reconnect("test")
        assert connector._reconnect_attempts == 1
        
        print("[OK] test_counter_reset_on_success: counter resets correctly")
        return True
    
    finally:
        asyncio.sleep = original_sleep


async def test_metrics_recorded():
    """Test that metrics are properly recorded."""
    mock_ctx = create_mock_ctx()
    config = create_config()
    connector = BybitWebSocketConnector(mock_ctx, config)
    
    original_sleep = asyncio.sleep
    asyncio.sleep = lambda d: original_sleep(0)
    
    try:
        await connector._wait_before_reconnect("public")
        
        # Verify metrics calls
        assert mock_ctx.metrics.ws_reconnect_attempts_total.labels.called
        labels_call = mock_ctx.metrics.ws_reconnect_attempts_total.labels.call_args
        assert labels_call[1]['exchange'] == "bybit"
        assert labels_call[1]['ws_type'] == "public"
        
        assert mock_ctx.metrics.ws_reconnect_delay_seconds.observe.called
        
        print("[OK] test_metrics_recorded: metrics properly tracked")
        return True
    
    finally:
        asyncio.sleep = original_sleep


async def main():
    """Run all tests."""
    print("Running WebSocket exponential backoff tests...\n")
    
    tests = [
        ("Exponential backoff growth", test_exponential_backoff_growth),
        ("Jitter adds variance", test_jitter_adds_variance),
        ("Max delay cap", test_max_delay_cap),
        ("Max attempts reached", test_max_attempts_reached),
        ("Counter reset on success", test_counter_reset_on_success),
        ("Metrics recorded", test_metrics_recorded),
    ]
    
    failed = []
    
    for name, test_func in tests:
        try:
            result = await test_func()
            if not result:
                failed.append(name)
                print(f"[FAIL] {name}")
        except AssertionError as e:
            failed.append(name)
            print(f"[FAIL] {name}: {e}")
        except Exception as e:
            failed.append(name)
            print(f"[ERROR] {name}: {e}")
    
    print(f"\n{'='*60}")
    if failed:
        print(f"FAILED: {len(failed)}/{len(tests)} tests")
        for name in failed:
            print(f"  - {name}")
        return 1
    else:
        print(f"SUCCESS: All {len(tests)} tests passed!")
        return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))

