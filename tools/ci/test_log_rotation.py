#!/usr/bin/env python3
"""
Test suite for log rotation functionality in full_stack_validate.py

Tests verify that:
1. Old logs are properly cleaned up (MAX_LOG_FILES_PER_STEP)
2. Disk space monitoring works correctly
3. Aggressive cleanup triggers when exceeding threshold
4. Edge cases are handled (empty directory, missing files, etc.)
"""
import os
import sys
import tempfile
import time
from pathlib import Path

# Import functions under test
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from tools.ci.full_stack_validate import (
    _cleanup_old_logs,
    _check_disk_space,
    CI_ARTIFACTS_DIR,
    MAX_LOG_FILES_PER_STEP,
)


def test_cleanup_old_logs_basic():
    """Test basic log rotation: keeps only last N files."""
    with tempfile.TemporaryDirectory() as tmpdir:
        test_dir = Path(tmpdir) / "ci"
        test_dir.mkdir()
        
        # Monkey-patch CI_ARTIFACTS_DIR for testing
        import tools.ci.full_stack_validate as fsv
        original_dir = fsv.CI_ARTIFACTS_DIR
        fsv.CI_ARTIFACTS_DIR = test_dir
        
        try:
            # Create 10 old log files
            label = "test_step"
            for i in range(10):
                out_log = test_dir / f"{label}.2025010{i:02d}_120000.out.log"
                err_log = test_dir / f"{label}.2025010{i:02d}_120000.err.log"
                out_log.write_text(f"log {i}")
                err_log.write_text(f"err {i}")
                # Set different mtimes to ensure sorting
                mtime = time.time() - (10 - i) * 60  # Newer files have higher mtime
                os.utime(out_log, (mtime, mtime))
                os.utime(err_log, (mtime, mtime))
            
            # Verify all 20 files exist
            all_logs = list(test_dir.glob("*.log"))
            assert len(all_logs) == 20, f"Expected 20 files, got {len(all_logs)}"
            
            # Run cleanup
            _cleanup_old_logs(label)
            
            # Should keep only last MAX_LOG_FILES_PER_STEP (5) of each type
            remaining_logs = list(test_dir.glob("*.log"))
            expected_count = MAX_LOG_FILES_PER_STEP * 2  # out + err
            assert len(remaining_logs) == expected_count, \
                f"Expected {expected_count} files after cleanup, got {len(remaining_logs)}"
            
            # Verify newest files are kept
            remaining_out = sorted(test_dir.glob(f"{label}.*.out.log"))
            remaining_err = sorted(test_dir.glob(f"{label}.*.err.log"))
            
            assert len(remaining_out) == MAX_LOG_FILES_PER_STEP
            assert len(remaining_err) == MAX_LOG_FILES_PER_STEP
            
            # Check that oldest files (indices 0-4) are deleted
            for i in range(5):
                old_out = test_dir / f"{label}.2025010{i:02d}_120000.out.log"
                old_err = test_dir / f"{label}.2025010{i:02d}_120000.err.log"
                assert not old_out.exists(), f"Old file should be deleted: {old_out}"
                assert not old_err.exists(), f"Old file should be deleted: {old_err}"
            
            # Check that newest files (indices 5-9) are kept
            for i in range(5, 10):
                kept_out = test_dir / f"{label}.2025010{i:02d}_120000.out.log"
                kept_err = test_dir / f"{label}.2025010{i:02d}_120000.err.log"
                assert kept_out.exists(), f"New file should be kept: {kept_out}"
                assert kept_err.exists(), f"New file should be kept: {kept_err}"
            
            print("[OK] test_cleanup_old_logs_basic passed")
        
        finally:
            fsv.CI_ARTIFACTS_DIR = original_dir


def test_cleanup_old_logs_empty_directory():
    """Test cleanup with no existing logs (edge case)."""
    with tempfile.TemporaryDirectory() as tmpdir:
        test_dir = Path(tmpdir) / "ci"
        test_dir.mkdir()
        
        import tools.ci.full_stack_validate as fsv
        original_dir = fsv.CI_ARTIFACTS_DIR
        fsv.CI_ARTIFACTS_DIR = test_dir
        
        try:
            # Run cleanup on empty directory (should not crash)
            _cleanup_old_logs("nonexistent_step")
            
            # Verify directory is still empty
            assert len(list(test_dir.glob("*.log"))) == 0
            
            print("[OK] test_cleanup_old_logs_empty_directory passed")
        
        finally:
            fsv.CI_ARTIFACTS_DIR = original_dir


def test_cleanup_multiple_steps():
    """Test that cleanup only affects the specified step."""
    with tempfile.TemporaryDirectory() as tmpdir:
        test_dir = Path(tmpdir) / "ci"
        test_dir.mkdir()
        
        import tools.ci.full_stack_validate as fsv
        original_dir = fsv.CI_ARTIFACTS_DIR
        fsv.CI_ARTIFACTS_DIR = test_dir
        
        try:
            # Create logs for two different steps
            for step in ["step_a", "step_b"]:
                for i in range(7):
                    out_log = test_dir / f"{step}.2025010{i:02d}_120000.out.log"
                    err_log = test_dir / f"{step}.2025010{i:02d}_120000.err.log"
                    out_log.write_text(f"{step} log {i}")
                    err_log.write_text(f"{step} err {i}")
                    mtime = time.time() - (7 - i) * 60
                    os.utime(out_log, (mtime, mtime))
                    os.utime(err_log, (mtime, mtime))
            
            # Total: 28 files (7 out + 7 err for each step)
            all_logs_before = list(test_dir.glob("*.log"))
            assert len(all_logs_before) == 28
            
            # Cleanup only step_a
            _cleanup_old_logs("step_a")
            
            # step_a should have only 10 files (5 out + 5 err)
            step_a_logs = list(test_dir.glob("step_a.*.log"))
            assert len(step_a_logs) == MAX_LOG_FILES_PER_STEP * 2
            
            # step_b should still have all 14 files
            step_b_logs = list(test_dir.glob("step_b.*.log"))
            assert len(step_b_logs) == 14
            
            print("[OK] test_cleanup_multiple_steps passed")
        
        finally:
            fsv.CI_ARTIFACTS_DIR = original_dir


def test_check_disk_space_normal():
    """Test disk space check with normal size (no cleanup)."""
    with tempfile.TemporaryDirectory() as tmpdir:
        test_dir = Path(tmpdir) / "ci"
        test_dir.mkdir()
        
        import tools.ci.full_stack_validate as fsv
        original_dir = fsv.CI_ARTIFACTS_DIR
        fsv.CI_ARTIFACTS_DIR = test_dir
        
        try:
            # Create small log files (well below threshold)
            for i in range(5):
                log_file = test_dir / f"step.{i}.out.log"
                log_file.write_text("x" * 1024)  # 1KB each
            
            # Should run without warnings or cleanup
            _check_disk_space()
            
            # All files should still exist
            assert len(list(test_dir.glob("*.log"))) == 5
            
            print("[OK] test_check_disk_space_normal passed")
        
        finally:
            fsv.CI_ARTIFACTS_DIR = original_dir


def test_check_disk_space_aggressive_cleanup():
    """Test aggressive cleanup when exceeding threshold."""
    with tempfile.TemporaryDirectory() as tmpdir:
        test_dir = Path(tmpdir) / "ci"
        test_dir.mkdir()
        
        import tools.ci.full_stack_validate as fsv
        original_dir = fsv.CI_ARTIFACTS_DIR
        original_threshold = fsv.AGGRESSIVE_CLEANUP_THRESHOLD_MB
        
        # Lower threshold for testing (1MB)
        fsv.CI_ARTIFACTS_DIR = test_dir
        fsv.AGGRESSIVE_CLEANUP_THRESHOLD_MB = 1
        
        try:
            # Create logs that exceed 1MB total
            for i in range(10):
                out_log = test_dir / f"step.{i:02d}.out.log"
                err_log = test_dir / f"step.{i:02d}.err.log"
                # Each file is 200KB, total = 4MB
                out_log.write_text("x" * (200 * 1024))
                err_log.write_text("x" * (200 * 1024))
                # Set mtimes for proper sorting
                mtime = time.time() - (10 - i) * 60
                os.utime(out_log, (mtime, mtime))
                os.utime(err_log, (mtime, mtime))
            
            # Verify all 20 files exist
            assert len(list(test_dir.glob("*.log"))) == 20
            
            # Run disk space check (should trigger aggressive cleanup)
            _check_disk_space()
            
            # After aggressive cleanup, should keep only last 2 files per type
            # For step label "step", we should have 4 files total (2 out + 2 err)
            remaining_logs = list(test_dir.glob("*.log"))
            assert len(remaining_logs) == 4, \
                f"Expected 4 files after aggressive cleanup, got {len(remaining_logs)}"
            
            print("[OK] test_check_disk_space_aggressive_cleanup passed")
        
        finally:
            fsv.CI_ARTIFACTS_DIR = original_dir
            fsv.AGGRESSIVE_CLEANUP_THRESHOLD_MB = original_threshold


def main():
    """Run all tests."""
    print("Running log rotation tests...\n")
    
    tests = [
        test_cleanup_old_logs_basic,
        test_cleanup_old_logs_empty_directory,
        test_cleanup_multiple_steps,
        test_check_disk_space_normal,
        test_check_disk_space_aggressive_cleanup,
    ]
    
    failed = []
    for test_func in tests:
        try:
            test_func()
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

