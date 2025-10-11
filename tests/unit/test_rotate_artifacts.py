"""
Unit tests for artifact rotation.
"""

import sys
sys.path.insert(0, ".")

import tempfile
import time
from pathlib import Path

from tools.ops.rotate_artifacts import (
    parse_size, get_file_age_days, apply_ttl_filter,
    apply_size_filter, apply_count_filter
)


def test_parse_size():
    """Test size string parsing."""
    assert parse_size("1G") == 1024 * 1024 * 1024
    assert parse_size("500M") == 500 * 1024 * 1024
    assert parse_size("1024K") == 1024 * 1024
    assert parse_size("1024") == 1024
    
    print("✓ Size parsing tests passed")


def test_ttl_filter():
    """Test TTL-based filtering."""
    with tempfile.TemporaryDirectory() as tmpdir:
        # Create test files with different ages
        old_file = Path(tmpdir) / "old.txt"
        new_file = Path(tmpdir) / "new.txt"
        
        old_file.write_text("old")
        time.sleep(0.1)
        new_file.write_text("new")
        
        # Mock ages (in days)
        files = [
            (old_file, 10.0, 100),  # 10 days old
            (new_file, 1.0, 100)    # 1 day old
        ]
        
        # Filter files older than 5 days
        to_delete = apply_ttl_filter(files, 5)
        
        assert len(to_delete) == 1
        assert to_delete[0] == old_file
    
    print("✓ TTL filter tests passed")


def test_count_filter():
    """Test count-based filtering."""
    files = [
        (Path("file1.txt"), 5.0, 100),  # 5 days old
        (Path("file2.txt"), 3.0, 100),  # 3 days old
        (Path("file3.txt"), 1.0, 100),  # 1 day old
    ]
    
    # Keep only 2 newest
    to_delete = apply_count_filter(files, 2)
    
    assert len(to_delete) == 1
    assert to_delete[0] == Path("file1.txt")  # Oldest
    
    print("✓ Count filter tests passed")


def test_size_filter():
    """Test size-based filtering."""
    files = [
        (Path("big.txt"), 10.0, 1000),    # 10 days old, 1000 bytes
        (Path("medium.txt"), 5.0, 500),   # 5 days old, 500 bytes
        (Path("small.txt"), 1.0, 100),    # 1 day old, 100 bytes
    ]
    
    # Max total size: 1200 bytes (need to delete 400 bytes)
    to_delete = apply_size_filter(files, 1200)
    
    # Should delete oldest (big.txt) first
    assert len(to_delete) == 1
    assert to_delete[0] == Path("big.txt")
    
    print("✓ Size filter tests passed")


if __name__ == "__main__":
    test_parse_size()
    test_ttl_filter()
    test_count_filter()
    test_size_filter()
    print("\n✓ All rotate_artifacts tests passed")

