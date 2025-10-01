"""
Robust process management with psutil for preventing zombie processes.

This module provides utilities to:
1. Kill entire process trees (parent + all children)
2. Graceful termination with fallback to force kill
3. Cross-platform support (Windows, Linux, macOS)
4. Timeout-based cleanup
"""
import os
import sys
import time
import signal
from typing import List, Optional

try:
    import psutil
    PSUTIL_AVAILABLE = True
except ImportError:
    PSUTIL_AVAILABLE = False
    print("[WARN] psutil not available, using fallback process management", file=sys.stderr)


def kill_process_tree(
    pid: int,
    timeout: float = 5.0,
    include_parent: bool = True
) -> bool:
    """
    Kill entire process tree (parent + all children).
    
    Uses psutil for robust cross-platform process management.
    Falls back to OS-specific commands if psutil is not available.
    
    Args:
        pid: Process ID of the parent process
        timeout: Grace period for SIGTERM before SIGKILL (seconds)
        include_parent: If True, kill parent process as well
    
    Returns:
        True if all processes were killed successfully, False otherwise
    
    Process:
        1. Send SIGTERM to all processes (graceful)
        2. Wait up to `timeout` seconds
        3. Send SIGKILL to any survivors (force)
    """
    if not PSUTIL_AVAILABLE:
        return _kill_process_tree_fallback(pid, include_parent)
    
    try:
        # Get parent process
        try:
            parent = psutil.Process(pid)
        except psutil.NoSuchProcess:
            # Process already dead
            return True
        
        # Get all children recursively
        try:
            children = parent.children(recursive=True)
        except psutil.NoSuchProcess:
            # Parent died while getting children
            return True
        
        # Build list of processes to kill
        processes = children + ([parent] if include_parent else [])
        
        if not processes:
            return True
        
        # Step 1: Send SIGTERM (graceful)
        for proc in processes:
            try:
                proc.terminate()
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                pass
        
        # Step 2: Wait for graceful termination
        gone, alive = psutil.wait_procs(processes, timeout=timeout)
        
        # Step 3: Force kill survivors
        for proc in alive:
            try:
                proc.kill()
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                pass
        
        # Final check: wait a bit for SIGKILL to take effect
        if alive:
            time.sleep(0.5)
            still_alive = [p for p in alive if p.is_running()]
            if still_alive:
                # Log warning but don't fail
                print(
                    f"[WARN] Failed to kill {len(still_alive)} processes: "
                    f"PIDs={[p.pid for p in still_alive]}",
                    file=sys.stderr
                )
                return False
        
        return True
    
    except Exception as e:
        print(f"[ERROR] kill_process_tree failed: {e}", file=sys.stderr)
        return False


def _kill_process_tree_fallback(pid: int, include_parent: bool = True) -> bool:
    """
    Fallback process tree killer without psutil.
    
    Uses OS-specific commands: taskkill on Windows, kill on Unix.
    Less robust than psutil version - may miss some children.
    """
    is_windows = sys.platform.startswith('win')
    
    try:
        if is_windows:
            # Windows: taskkill /F /T kills process tree
            import subprocess
            
            # /F = force, /T = tree (kill children), /PID = process ID
            result = subprocess.run(
                ["taskkill", "/F", "/T", "/PID", str(pid)],
                capture_output=True,
                timeout=10
            )
            
            return result.returncode == 0
        else:
            # Unix: kill process group
            try:
                # Try to get process group ID
                pgid = os.getpgid(pid)
                # Kill entire process group
                os.killpg(pgid, signal.SIGTERM)
                
                # Wait a bit
                time.sleep(1.0)
                
                # Check if still alive, then SIGKILL
                try:
                    os.killpg(pgid, signal.SIGKILL)
                except ProcessLookupError:
                    # Process group already dead
                    pass
                
                return True
            except ProcessLookupError:
                # Process already dead
                return True
            except PermissionError:
                print(f"[ERROR] Permission denied to kill process {pid}", file=sys.stderr)
                return False
    
    except Exception as e:
        print(f"[ERROR] _kill_process_tree_fallback failed: {e}", file=sys.stderr)
        return False


def get_zombie_processes() -> List[int]:
    """
    Get list of zombie process PIDs.
    
    Returns:
        List of PIDs that are zombie processes
    """
    if not PSUTIL_AVAILABLE:
        print("[WARN] psutil not available, cannot detect zombies", file=sys.stderr)
        return []
    
    zombies = []
    try:
        for proc in psutil.process_iter(['pid', 'status']):
            try:
                if proc.info['status'] == psutil.STATUS_ZOMBIE:
                    zombies.append(proc.info['pid'])
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                pass
    except Exception as e:
        print(f"[ERROR] get_zombie_processes failed: {e}", file=sys.stderr)
    
    return zombies


def cleanup_zombies(parent_pid: Optional[int] = None) -> int:
    """
    Clean up zombie processes.
    
    Args:
        parent_pid: If specified, only clean zombies of this parent.
                    If None, attempt to clean all zombies (may fail due to permissions).
    
    Returns:
        Number of zombies cleaned up
    """
    if not PSUTIL_AVAILABLE:
        print("[WARN] psutil not available, cannot cleanup zombies", file=sys.stderr)
        return 0
    
    cleaned = 0
    try:
        for proc in psutil.process_iter(['pid', 'ppid', 'status']):
            try:
                info = proc.info
                
                # Skip if not zombie
                if info['status'] != psutil.STATUS_ZOMBIE:
                    continue
                
                # If parent_pid specified, only clean children of that parent
                if parent_pid is not None and info['ppid'] != parent_pid:
                    continue
                
                # Try to reap zombie by waiting on it
                try:
                    # On Unix, wait() will reap the zombie
                    os.waitpid(info['pid'], os.WNOHANG)
                    cleaned += 1
                except (OSError, ChildProcessError):
                    # Not our child or already reaped
                    pass
            
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                pass
    
    except Exception as e:
        print(f"[ERROR] cleanup_zombies failed: {e}", file=sys.stderr)
    
    return cleaned


def get_process_tree_info(pid: int) -> dict:
    """
    Get information about process and its children.
    
    Args:
        pid: Parent process ID
    
    Returns:
        Dict with process tree information:
        {
            'parent': {'pid': int, 'name': str, 'status': str},
            'children': [{'pid': int, 'name': str, 'status': str}, ...],
            'total_count': int
        }
    """
    if not PSUTIL_AVAILABLE:
        return {'error': 'psutil not available'}
    
    try:
        parent = psutil.Process(pid)
        children = parent.children(recursive=True)
        
        return {
            'parent': {
                'pid': parent.pid,
                'name': parent.name(),
                'status': parent.status()
            },
            'children': [
                {
                    'pid': child.pid,
                    'name': child.name(),
                    'status': child.status()
                }
                for child in children
            ],
            'total_count': 1 + len(children)
        }
    
    except psutil.NoSuchProcess:
        return {'error': 'process not found'}
    except Exception as e:
        return {'error': str(e)}


# Expose availability flag
__all__ = [
    'PSUTIL_AVAILABLE',
    'kill_process_tree',
    'get_zombie_processes',
    'cleanup_zombies',
    'get_process_tree_info',
]

