"""
Tests for process_manager module.

Tests process tree killing, zombie detection, and cleanup.
"""
import os
import sys
import time
import subprocess
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.common.process_manager import (
    PSUTIL_AVAILABLE,
    kill_process_tree,
    get_zombie_processes,
    cleanup_zombies,
    get_process_tree_info,
)


def test_psutil_availability():
    """Test that psutil availability is detected correctly."""
    print(f"[INFO] psutil available: {PSUTIL_AVAILABLE}")
    # Just check it's a boolean
    assert isinstance(PSUTIL_AVAILABLE, bool)
    print("[OK] psutil availability check passed")


def test_kill_process_tree_simple():
    """Test killing a simple process (sleep command)."""
    if not PSUTIL_AVAILABLE:
        print("[SKIP] psutil not available, skipping test")
        return
    
    # Start a simple sleep process
    is_windows = sys.platform.startswith('win')
    
    if is_windows:
        # Windows: timeout command (similar to sleep)
        proc = subprocess.Popen(
            ["timeout", "/t", "30"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL
        )
    else:
        # Unix: sleep command
        proc = subprocess.Popen(
            ["sleep", "30"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL
        )
    
    pid = proc.pid
    print(f"[INFO] Started process PID={pid}")
    
    # Give it a moment to start
    time.sleep(0.5)
    
    # Kill it
    success = kill_process_tree(pid, timeout=2.0, include_parent=True)
    
    print(f"[INFO] kill_process_tree returned: {success}")
    
    # Check process is dead
    time.sleep(0.5)
    try:
        # poll() returns None if process is still running
        returncode = proc.poll()
        assert returncode is not None, "Process should be dead"
        print(f"[OK] Process killed successfully (returncode={returncode})")
    except Exception as e:
        print(f"[ERROR] Process check failed: {e}")
        # Try to clean up
        try:
            proc.kill()
        except:
            pass
        raise


def test_kill_process_tree_with_children():
    """Test killing a process tree (parent + children)."""
    if not PSUTIL_AVAILABLE:
        print("[SKIP] psutil not available, skipping test")
        return
    
    is_windows = sys.platform.startswith('win')
    
    # Create a parent process that spawns children
    if is_windows:
        # Windows: cmd.exe that spawns timeout
        script = "timeout /t 30"
        proc = subprocess.Popen(
            ["cmd", "/c", script],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=subprocess.CREATE_NEW_PROCESS_GROUP
        )
    else:
        # Unix: sh that spawns sleep
        script = "sleep 30 & sleep 30 & wait"
        proc = subprocess.Popen(
            ["sh", "-c", script],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            preexec_fn=os.setsid
        )
    
    pid = proc.pid
    print(f"[INFO] Started parent process PID={pid}")
    
    # Give it time to spawn children
    time.sleep(1.0)
    
    # Get process tree info before killing
    tree_info = get_process_tree_info(pid)
    print(f"[INFO] Process tree before kill: {tree_info}")
    
    # Kill entire tree
    success = kill_process_tree(pid, timeout=2.0, include_parent=True)
    
    print(f"[INFO] kill_process_tree returned: {success}")
    
    # Check all processes are dead
    time.sleep(0.5)
    try:
        returncode = proc.poll()
        assert returncode is not None, "Parent process should be dead"
        print(f"[OK] Process tree killed successfully (returncode={returncode})")
    except Exception as e:
        print(f"[ERROR] Process check failed: {e}")
        # Try to clean up
        try:
            proc.kill()
        except:
            pass
        raise


def test_get_process_tree_info():
    """Test getting process tree information."""
    if not PSUTIL_AVAILABLE:
        print("[SKIP] psutil not available, skipping test")
        return
    
    # Get info for current process
    pid = os.getpid()
    info = get_process_tree_info(pid)
    
    print(f"[INFO] Current process tree: {info}")
    
    # Check structure
    assert 'parent' in info
    assert 'children' in info
    assert 'total_count' in info
    assert info['parent']['pid'] == pid
    
    print("[OK] Process tree info retrieved successfully")


def test_get_zombie_processes():
    """Test zombie process detection."""
    if not PSUTIL_AVAILABLE:
        print("[SKIP] psutil not available, skipping test")
        return
    
    # Just test that function works (may return empty list)
    zombies = get_zombie_processes()
    
    print(f"[INFO] Zombie processes found: {len(zombies)}")
    
    # Check it returns a list
    assert isinstance(zombies, list)
    
    if zombies:
        print(f"[INFO] Zombie PIDs: {zombies}")
    
    print("[OK] Zombie process detection works")


def test_cleanup_zombies():
    """Test zombie cleanup."""
    if not PSUTIL_AVAILABLE:
        print("[SKIP] psutil not available, skipping test")
        return
    
    # Just test that function works
    cleaned = cleanup_zombies()
    
    print(f"[INFO] Zombies cleaned: {cleaned}")
    
    # Check it returns an integer
    assert isinstance(cleaned, int)
    assert cleaned >= 0
    
    print("[OK] Zombie cleanup works")


def test_kill_already_dead_process():
    """Test killing a process that's already dead."""
    if not PSUTIL_AVAILABLE:
        print("[SKIP] psutil not available, skipping test")
        return
    
    # Start and immediately kill a process
    proc = subprocess.Popen(
        ["python", "-c", "exit(0)"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL
    )
    
    pid = proc.pid
    
    # Wait for it to die
    proc.wait(timeout=5)
    
    # Try to kill already dead process
    success = kill_process_tree(pid, timeout=1.0, include_parent=True)
    
    # Should return True (process is gone)
    print(f"[INFO] kill_process_tree on dead process returned: {success}")
    assert success == True
    
    print("[OK] Killing already dead process handled correctly")


if __name__ == "__main__":
    print("Running process_manager tests...")
    print("=" * 60)
    
    test_psutil_availability()
    test_kill_process_tree_simple()
    test_kill_process_tree_with_children()
    test_get_process_tree_info()
    test_get_zombie_processes()
    test_cleanup_zombies()
    test_kill_already_dead_process()
    
    print("=" * 60)
    print("[OK] All process_manager tests passed!")

