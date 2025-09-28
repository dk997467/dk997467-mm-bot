"""
File locking utilities for concurrent-safe summary writing.

Provides lockfile and O_EXCL based protection against race conditions.
"""

import os
import time
import random
import logging
from contextlib import contextmanager
from pathlib import Path
from typing import Literal, Generator
from datetime import datetime

logger = logging.getLogger(__name__)


class LockAcquisitionError(Exception):
    """Raised when lock cannot be acquired."""
    pass


def _generate_unique_suffix() -> str:
    """Generate unique suffix for temporary files."""
    timestamp = int(time.time() * 1000000)  # microseconds
    random_part = random.randint(1000, 9999)
    return f"{os.getpid()}.{timestamp}.{random_part:04x}"


@contextmanager
def _acquire_lockfile_lock(lock_path: Path, timeout_sec: float = 30.0) -> Generator[None, None, None]:
    """
    Acquire exclusive lock using lockfile approach.
    
    Creates a .lock file with O_CREAT|O_EXCL to ensure atomicity.
    """
    acquired = False
    start_time = time.time()
    
    while time.time() - start_time < timeout_sec:
        try:
            # Try to create lock file exclusively
            fd = os.open(str(lock_path), os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)
            try:
                # Write some metadata to lock file
                lock_info = f"pid={os.getpid()}\ntime={datetime.now().isoformat()}\n"
                os.write(fd, lock_info.encode('utf-8'))
                os.fsync(fd)
            finally:
                os.close(fd)
            
            acquired = True
            logger.debug(f"[E1+] Acquired lockfile: {lock_path}")
            break
            
        except FileExistsError:
            # Lock file exists, wait and retry
            jitter = random.uniform(0.01, 0.05)  # 10-50ms jitter
            time.sleep(0.1 + jitter)
            continue
        except OSError as e:
            logger.warning(f"[E1+] Lockfile acquisition failed: {e}")
            raise LockAcquisitionError(f"Cannot create lockfile {lock_path}: {e}")
    
    if not acquired:
        raise LockAcquisitionError(f"Lock timeout after {timeout_sec}s: {lock_path}")
    
    try:
        yield
    finally:
        # Always clean up lock file
        try:
            if lock_path.exists():
                lock_path.unlink()
                logger.debug(f"[E1+] Released lockfile: {lock_path}")
        except OSError as e:
            logger.warning(f"[E1+] Failed to remove lockfile {lock_path}: {e}")


@contextmanager
def _acquire_o_excl_lock(tmp_path: Path, max_retries: int = 5) -> Generator[Path, None, None]:
    """
    Acquire exclusive lock using O_EXCL on temporary file creation.
    
    Returns the unique temporary file path that was successfully created.
    """
    for attempt in range(max_retries):
        unique_suffix = _generate_unique_suffix()
        candidate_path = tmp_path.parent / f"{tmp_path.name}.tmp.{unique_suffix}"
        
        try:
            # Try to create temp file exclusively
            fd = os.open(str(candidate_path), os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)
            os.close(fd)  # Just testing creation, will reopen for writing
            
            logger.debug(f"[E1+] Acquired O_EXCL lock: {candidate_path}")
            
            try:
                yield candidate_path
            finally:
                # Clean up temp file
                try:
                    if candidate_path.exists():
                        candidate_path.unlink()
                        logger.debug(f"[E1+] Cleaned up O_EXCL temp: {candidate_path}")
                except OSError as e:
                    logger.warning(f"[E1+] Failed to cleanup temp file {candidate_path}: {e}")
            
            return  # Success, exit the retry loop
            
        except FileExistsError:
            # This specific temp name exists, try another
            if attempt < max_retries - 1:
                jitter = random.uniform(0.001, 0.01)  # 1-10ms jitter
                time.sleep(jitter)
                continue
            else:
                raise LockAcquisitionError(f"Cannot create unique temp file after {max_retries} attempts")
        except OSError as e:
            logger.warning(f"[E1+] O_EXCL attempt {attempt + 1} failed: {e}")
            if attempt < max_retries - 1:
                jitter = random.uniform(0.01, 0.05)
                time.sleep(jitter)
                continue
            else:
                raise LockAcquisitionError(f"O_EXCL lock failed after {max_retries} attempts: {e}")


@contextmanager
def acquire_hour_lock(
    symbol: str, 
    hour_start_utc: datetime, 
    summaries_dir: Path, 
    lock_mode: Literal["none", "lockfile", "o_excl"] = "lockfile"
) -> Generator[None, None, None]:
    """
    Acquire exclusive lock for writing a specific hour's summary.
    
    Args:
        symbol: Trading symbol
        hour_start_utc: Hour being written (for lock naming)
        summaries_dir: Base summaries directory 
        lock_mode: Locking strategy to use
        
    Yields:
        None (context manager for exclusive access)
    """
    if lock_mode == "none":
        # No locking, just yield immediately
        yield
        return
    
    # Construct paths
    symbol_dir = summaries_dir / symbol
    symbol_dir.mkdir(parents=True, exist_ok=True)
    
    hour_str = hour_start_utc.strftime('%Y-%m-%d_%H')
    summary_filename = f"{symbol}_{hour_str}.json"
    summary_path = symbol_dir / summary_filename
    
    if lock_mode == "lockfile":
        lock_path = symbol_dir / f"{summary_filename}.lock"
        
        try:
            with _acquire_lockfile_lock(lock_path):
                yield
        except LockAcquisitionError:
            # Fallback to O_EXCL if lockfile fails
            logger.warning(f"[E1+] Lockfile failed for {symbol}:{hour_str}, falling back to O_EXCL")
            with _acquire_o_excl_lock(summary_path):
                yield
    
    elif lock_mode == "o_excl":
        with _acquire_o_excl_lock(summary_path):
            yield
    
    else:
        raise ValueError(f"Unknown lock_mode: {lock_mode}")


def cleanup_stale_locks(summaries_dir: Path, max_age_hours: int = 2):
    """
    Clean up stale lock files older than max_age_hours.
    
    Should be called periodically to prevent accumulation of dead locks.
    """
    if not summaries_dir.exists():
        return
    
    cutoff_time = time.time() - (max_age_hours * 3600)
    removed_count = 0
    
    try:
        for lock_file in summaries_dir.rglob("*.lock"):
            try:
                if lock_file.stat().st_mtime < cutoff_time:
                    lock_file.unlink()
                    removed_count += 1
                    logger.debug(f"[E1+] Removed stale lock: {lock_file}")
            except OSError as e:
                logger.warning(f"[E1+] Failed to remove stale lock {lock_file}: {e}")
        
        if removed_count > 0:
            logger.info(f"[E1+] Cleaned up {removed_count} stale lock files")
            
    except Exception as e:
        logger.error(f"[E1+] Error during stale lock cleanup: {e}")


def get_lock_info(lock_path: Path) -> dict:
    """
    Read information from a lock file.
    
    Returns dict with lock metadata or empty dict if unavailable.
    """
    try:
        if not lock_path.exists():
            return {}
        
        with open(lock_path, 'r') as f:
            content = f.read()
        
        info = {}
        for line in content.strip().split('\n'):
            if '=' in line:
                key, value = line.split('=', 1)
                info[key] = value
        
        return info
        
    except Exception as e:
        logger.warning(f"[E1+] Failed to read lock info from {lock_path}: {e}")
        return {}
