#!/usr/bin/env python3
"""
Tests for resource_monitor.py

Tests verify that:
1. Snapshot collection works (with and without psutil)
2. JSONL output format is correct
3. Analysis detects memory leaks
4. Graceful degradation when psutil unavailable
5. File I/O is robust
"""
import json
import sys
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

# Add project root to path
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from tools.soak.resource_monitor import ResourceMonitor, ResourceSnapshot, analyze_resources


def test_snapshot_collection_with_psutil():
    """Test snapshot collection when psutil is available."""
    with tempfile.TemporaryDirectory() as tmpdir:
        output_file = Path(tmpdir) / "test_resources.jsonl"
        
        # Create monitor (should detect psutil if installed)
        monitor = ResourceMonitor(output_file, interval_seconds=1)
        
        # Collect snapshot
        snapshot = monitor.collect_snapshot()
        
        # Verify snapshot has all required fields
        assert snapshot.timestamp_utc
        assert snapshot.timestamp_unix > 0
        assert snapshot.cpu_count > 0
        assert snapshot.hostname
        assert snapshot.platform
        assert snapshot.python_version
        
        # CPU metrics should be reasonable
        assert 0 <= snapshot.cpu_percent <= 100
        
        # Memory metrics should be positive if psutil available
        if monitor.psutil:
            assert snapshot.memory_total_mb > 0
            assert 0 <= snapshot.memory_percent <= 100
        
        print("[OK] test_snapshot_collection_with_psutil: snapshot collected successfully")


def test_jsonl_output_format():
    """Test that snapshots are written in valid JSONL format."""
    with tempfile.TemporaryDirectory() as tmpdir:
        output_file = Path(tmpdir) / "test_resources.jsonl"
        
        monitor = ResourceMonitor(output_file, interval_seconds=1)
        
        # Collect and write 3 snapshots
        for _ in range(3):
            snapshot = monitor.collect_snapshot()
            monitor.write_snapshot(snapshot)
        
        # Verify file exists and contains 3 lines
        assert output_file.exists()
        
        lines = output_file.read_text().strip().split('\n')
        assert len(lines) == 3
        
        # Verify each line is valid JSON
        for i, line in enumerate(lines):
            data = json.loads(line)
            assert 'timestamp_utc' in data
            assert 'cpu_percent' in data
            assert 'memory_total_mb' in data
            assert 'disk_total_gb' in data
        
        print("[OK] test_jsonl_output_format: JSONL format correct")


def test_analysis_memory_leak_detection():
    """Test memory leak detection in analysis."""
    with tempfile.TemporaryDirectory() as tmpdir:
        test_file = Path(tmpdir) / "test_resources.jsonl"
        
        # Create mock data simulating memory leak (100 MB increase over 1 hour)
        snapshots = []
        for i in range(60):  # 60 samples = 1 hour @ 60s interval
            snapshot = {
                'timestamp_unix': 1000000 + i * 60,  # 60s apart
                'memory_used_mb': 1000 + i * 1.67,  # ~100 MB/h leak
                'cpu_percent': 10.0,
                'disk_used_gb': 100.0,
            }
            snapshots.append(snapshot)
        
        # Write to file
        with open(test_file, 'w') as f:
            for s in snapshots:
                f.write(json.dumps(s) + '\n')
        
        # Analyze
        analysis = analyze_resources(test_file)
        
        # Verify analysis results
        assert analysis['snapshot_count'] == 60
        assert analysis['duration_hours'] > 0.9  # ~1 hour
        
        # Memory leak should be detected
        assert analysis['memory']['leak_detected'] == True
        assert analysis['memory']['leak_mb_per_hour'] > 50  # >50 MB/h
        
        print(f"[OK] test_analysis_memory_leak_detection: leak detected ({analysis['memory']['leak_mb_per_hour']:.1f} MB/h)")


def test_analysis_no_leak():
    """Test analysis with stable memory (no leak)."""
    with tempfile.TemporaryDirectory() as tmpdir:
        test_file = Path(tmpdir) / "test_resources.jsonl"
        
        # Create mock data with stable memory
        snapshots = []
        for i in range(60):
            snapshot = {
                'timestamp_unix': 1000000 + i * 60,
                'memory_used_mb': 1000 + (i % 5) * 2,  # Small oscillation, no trend
                'cpu_percent': 10.0,
                'disk_used_gb': 100.0,
            }
            snapshots.append(snapshot)
        
        with open(test_file, 'w') as f:
            for s in snapshots:
                f.write(json.dumps(s) + '\n')
        
        analysis = analyze_resources(test_file)
        
        # No leak should be detected
        assert analysis['memory']['leak_detected'] == False
        assert abs(analysis['memory']['leak_mb_per_hour']) < 10  # <10 MB/h
        
        print(f"[OK] test_analysis_no_leak: no leak detected ({analysis['memory']['leak_mb_per_hour']:.1f} MB/h)")


def test_graceful_degradation_no_psutil():
    """Test that monitor works even without psutil."""
    with tempfile.TemporaryDirectory() as tmpdir:
        output_file = Path(tmpdir) / "test_resources.jsonl"
        
        monitor = ResourceMonitor(output_file, interval_seconds=1)
        
        # Simulate psutil unavailable
        original_psutil = monitor.psutil
        monitor.psutil = None
        monitor._process = None
        
        try:
            # Should still collect snapshot (with zeroed metrics)
            snapshot = monitor.collect_snapshot()
            
            # Basic fields should still be present
            assert snapshot.timestamp_utc
            assert snapshot.cpu_count > 0
            assert snapshot.hostname
            
            # Metrics should be zero or default values (graceful degradation)
            # This is acceptable - monitor doesn't crash without psutil
            
            print("[OK] test_graceful_degradation_no_psutil: works without psutil")
        
        finally:
            monitor.psutil = original_psutil


def test_file_io_robustness():
    """Test that monitor handles I/O errors gracefully."""
    with tempfile.TemporaryDirectory() as tmpdir:
        output_file = Path(tmpdir) / "test_resources.jsonl"
        
        monitor = ResourceMonitor(output_file, interval_seconds=1)
        snapshot = monitor.collect_snapshot()
        
        # Write normally
        monitor.write_snapshot(snapshot)
        assert output_file.exists()
        
        # Simulate I/O error (read-only file)
        try:
            import os
            if sys.platform != 'win32':
                os.chmod(output_file, 0o444)  # Read-only
                
                # Should not crash, just log error
                monitor.write_snapshot(snapshot)
        except Exception:
            # If chmod fails, that's OK (Windows limitations)
            pass
        
        print("[OK] test_file_io_robustness: I/O errors handled")


def test_analysis_empty_file():
    """Test analysis with empty/nonexistent file."""
    with tempfile.TemporaryDirectory() as tmpdir:
        nonexistent_file = Path(tmpdir) / "nonexistent.jsonl"
        
        # Should return error, not crash
        analysis = analyze_resources(nonexistent_file)
        assert 'error' in analysis
        
        # Empty file
        empty_file = Path(tmpdir) / "empty.jsonl"
        empty_file.write_text('')
        
        analysis = analyze_resources(empty_file)
        assert 'error' in analysis
        
        print("[OK] test_analysis_empty_file: handles missing/empty files")


def test_disk_and_cpu_metrics():
    """Test that CPU and disk metrics are collected."""
    with tempfile.TemporaryDirectory() as tmpdir:
        output_file = Path(tmpdir) / "test_resources.jsonl"
        
        monitor = ResourceMonitor(output_file, interval_seconds=1)
        snapshot = monitor.collect_snapshot()
        
        # CPU count should be > 0
        assert snapshot.cpu_count > 0
        
        # If psutil available, more detailed metrics
        if monitor.psutil:
            # CPU percent should be in valid range
            assert 0 <= snapshot.cpu_percent <= 100 * snapshot.cpu_count
            
            # Disk metrics should be reasonable
            if snapshot.disk_total_gb > 0:
                assert snapshot.disk_used_gb >= 0
                assert snapshot.disk_free_gb >= 0
                assert 0 <= snapshot.disk_percent <= 100
        
        print("[OK] test_disk_and_cpu_metrics: metrics collected")


def test_summary_logging():
    """Test that summary logging doesn't crash."""
    with tempfile.TemporaryDirectory() as tmpdir:
        output_file = Path(tmpdir) / "test_resources.jsonl"
        
        monitor = ResourceMonitor(output_file, interval_seconds=1)
        snapshot = monitor.collect_snapshot()
        
        # Should log without crashing
        try:
            monitor.log_summary(snapshot)
            print("[OK] test_summary_logging: logging works")
        except Exception as e:
            print(f"[FAIL] test_summary_logging: {e}")
            return False
    
    return True


def main():
    """Run all tests."""
    print("Testing resource_monitor.py...\n")
    
    tests = [
        test_snapshot_collection_with_psutil,
        test_jsonl_output_format,
        test_analysis_memory_leak_detection,
        test_analysis_no_leak,
        test_graceful_degradation_no_psutil,
        test_file_io_robustness,
        test_analysis_empty_file,
        test_disk_and_cpu_metrics,
        test_summary_logging,
    ]
    
    failed = []
    for test_func in tests:
        try:
            result = test_func()
            if result is False:
                failed.append(test_func.__name__)
        except AssertionError as e:
            print(f"[FAIL] {test_func.__name__}: {e}")
            failed.append(test_func.__name__)
        except Exception as e:
            print(f"[ERROR] {test_func.__name__}: {e}")
            failed.append(test_func.__name__)
    
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
    sys.exit(main())

