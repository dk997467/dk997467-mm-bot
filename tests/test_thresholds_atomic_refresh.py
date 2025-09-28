"""
Test atomic refresh of throttle thresholds.

Ensures no mixed states during concurrent read/write operations.
"""
import threading
import time
import tempfile
from pathlib import Path
from src.deploy.thresholds import refresh_thresholds, get_throttle_thresholds


def test_thresholds_atomic_refresh():
    """Test that concurrent reads during refresh see either old or new values, never mixed."""
    # Create test YAML files
    old_yaml = """
throttle:
  global:
    max_throttle_backoff_ms: 1000
    max_throttle_events_in_window_total: 50
  per_symbol:
    BTCUSDT:
      max_throttle_backoff_ms: 1500
"""
    
    new_yaml = """
throttle:
  global:
    max_throttle_backoff_ms: 2000
    max_throttle_events_in_window_total: 100
  per_symbol:
    BTCUSDT:
      max_throttle_backoff_ms: 3000
    ETHUSDT:
      max_throttle_backoff_ms: 2500
"""
    
    with tempfile.TemporaryDirectory() as temp_dir:
        yaml_path = Path(temp_dir) / "test_thresholds.yaml"
        
        # Load initial state
        yaml_path.write_text(old_yaml, encoding='utf-8')
        refresh_thresholds(str(yaml_path))
        
        # Results collector
        results = []
        stop_reading = threading.Event()
        
        def reader():
            """Continuously read thresholds and collect snapshots."""
            while not stop_reading.is_set():
                try:
                    btc = get_throttle_thresholds("BTCUSDT")
                    eth = get_throttle_thresholds("ETHUSDT")
                    results.append({
                        "btc_backoff": btc.get("max_throttle_backoff_ms", 0),
                        "btc_events": btc.get("max_throttle_events_in_window_total", 0),
                        "eth_backoff": eth.get("max_throttle_backoff_ms", 0),
                        "eth_events": eth.get("max_throttle_events_in_window_total", 0),
                    })
                    time.sleep(0.001)  # Small delay
                except Exception:
                    pass
        
        # Start multiple reader threads
        readers = []
        for i in range(3):
            t = threading.Thread(target=reader)
            t.start()
            readers.append(t)
        
        # Let readers collect some "old" data
        time.sleep(0.05)
        
        # Perform atomic refresh
        yaml_path.write_text(new_yaml, encoding='utf-8')
        refresh_thresholds(str(yaml_path))
        
        # Let readers collect some "new" data
        time.sleep(0.05)
        
        # Stop readers
        stop_reading.set()
        for t in readers:
            t.join(timeout=1.0)
    
    # Analyze results for atomicity
    old_state = {
        "btc_backoff": 1500,  # per-symbol override
        "btc_events": 50,     # global default
        "eth_backoff": 1000,  # global default (no override)
        "eth_events": 50,     # global default
    }
    
    new_state = {
        "btc_backoff": 3000,  # new per-symbol override
        "btc_events": 100,    # new global default
        "eth_backoff": 2500,  # new per-symbol override
        "eth_events": 100,    # new global default
    }
    
    # Check that all results are either completely old or completely new
    mixed_states = 0
    old_count = 0
    new_count = 0
    
    for result in results:
        if result == old_state:
            old_count += 1
        elif result == new_state:
            new_count += 1
        else:
            # This should never happen in atomic implementation
            mixed_states += 1
    
    # Ensure we got both old and new states (test actually ran)
    assert old_count > 0, f"Should have seen old state, got {len(results)} results"
    assert new_count > 0, f"Should have seen new state, got {len(results)} results"
    
    # Most importantly: no mixed states
    assert mixed_states == 0, f"Found {mixed_states} mixed states out of {len(results)} total - not atomic!"
    
    print(f"Atomicity test passed: {old_count} old states, {new_count} new states, {mixed_states} mixed states")


if __name__ == "__main__":
    test_thresholds_atomic_refresh()
    print("All atomic refresh tests passed!")