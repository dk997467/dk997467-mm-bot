"""
Test thresholds reload metrics and versioning.

Ensures metrics are correctly incremented and version tracking works.
"""
import tempfile
from pathlib import Path
from src.deploy.thresholds import refresh_thresholds, get_thresholds_version
from src.metrics.exporter import _get_thresholds_metrics_snapshot_for_tests, _reset_thresholds_metrics_for_tests


def test_thresholds_reload_metrics_success():
    """Test successful reload increments ok counter and version."""
    _reset_thresholds_metrics_for_tests()
    
    yaml_content = """
throttle:
  global:
    max_throttle_backoff_ms: 1000
    max_throttle_events_in_window_total: 50
  per_symbol:
    BTCUSDT:
      max_throttle_backoff_ms: 1500
"""
    
    with tempfile.TemporaryDirectory() as temp_dir:
        yaml_path = Path(temp_dir) / "test_thresholds.yaml"
        yaml_path.write_text(yaml_content, encoding='utf-8')
        
        # Get initial state
        initial_metrics = _get_thresholds_metrics_snapshot_for_tests()
        initial_version = get_thresholds_version()
        
        # Perform successful reload
        summary = refresh_thresholds(str(yaml_path))
        
        # Check metrics
        final_metrics = _get_thresholds_metrics_snapshot_for_tests()
        final_version = get_thresholds_version()
        
        # Verify success counter incremented
        assert final_metrics["reload"]["ok"] == initial_metrics["reload"]["ok"] + 1
        assert final_metrics["reload"]["failed"] == initial_metrics["reload"]["failed"]
        
        # Verify version incremented
        assert final_version == initial_version + 1
        assert summary["version"] == final_version
        
        # Verify version in metrics
        assert final_metrics["version"] == final_version
        
        print(f"Success test passed: version {initial_version} -> {final_version}")


def test_thresholds_reload_metrics_failure():
    """Test failed reload increments failed counter."""
    _reset_thresholds_metrics_for_tests()
    
    with tempfile.TemporaryDirectory() as temp_dir:
        # Use non-existent file to trigger failure
        yaml_path = Path(temp_dir) / "nonexistent.yaml"
        
        # Get initial state
        initial_metrics = _get_thresholds_metrics_snapshot_for_tests()
        initial_version = get_thresholds_version()
        
        # Perform failed reload
        try:
            refresh_thresholds(str(yaml_path))
            assert False, "Expected refresh to fail"
        except Exception:
            pass  # Expected failure
        
        # Check metrics
        final_metrics = _get_thresholds_metrics_snapshot_for_tests()
        final_version = get_thresholds_version()
        
        # Verify failed counter incremented
        assert final_metrics["reload"]["failed"] == initial_metrics["reload"]["failed"] + 1
        assert final_metrics["reload"]["ok"] == initial_metrics["reload"]["ok"]
        
        # Verify version unchanged on failure
        assert final_version == initial_version
        
        print(f"Failure test passed: version unchanged at {final_version}")


def test_thresholds_version_incremental():
    """Test that version increments properly across multiple reloads."""
    _reset_thresholds_metrics_for_tests()
    
    yaml_content_v1 = """
throttle:
  global:
    max_throttle_backoff_ms: 1000
"""
    
    yaml_content_v2 = """
throttle:
  global:
    max_throttle_backoff_ms: 2000
"""
    
    yaml_content_v3 = """
throttle:
  global:
    max_throttle_backoff_ms: 3000
"""
    
    with tempfile.TemporaryDirectory() as temp_dir:
        yaml_path = Path(temp_dir) / "test_thresholds.yaml"
        
        # Initial version
        initial_version = get_thresholds_version()
        
        # Reload 1
        yaml_path.write_text(yaml_content_v1, encoding='utf-8')
        summary1 = refresh_thresholds(str(yaml_path))
        version1 = get_thresholds_version()
        
        # Reload 2
        yaml_path.write_text(yaml_content_v2, encoding='utf-8')
        summary2 = refresh_thresholds(str(yaml_path))
        version2 = get_thresholds_version()
        
        # Reload 3
        yaml_path.write_text(yaml_content_v3, encoding='utf-8')
        summary3 = refresh_thresholds(str(yaml_path))
        version3 = get_thresholds_version()
        
        # Verify incremental versioning
        assert version1 == initial_version + 1
        assert version2 == version1 + 1
        assert version3 == version2 + 1
        
        # Verify summary versions
        assert summary1["version"] == version1
        assert summary2["version"] == version2
        assert summary3["version"] == version3
        
        # Check final metrics
        final_metrics = _get_thresholds_metrics_snapshot_for_tests()
        assert final_metrics["reload"]["ok"] == 3
        assert final_metrics["reload"]["failed"] == 0
        assert final_metrics["version"] == version3
        
        print(f"Incremental test passed: {initial_version} -> {version1} -> {version2} -> {version3}")


if __name__ == "__main__":
    test_thresholds_reload_metrics_success()
    test_thresholds_reload_metrics_failure()
    test_thresholds_version_incremental()
    print("All reload metrics tests passed!")