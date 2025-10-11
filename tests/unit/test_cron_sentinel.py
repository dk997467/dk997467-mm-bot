"""
Unit tests for cron sentinel.
"""

import sys
sys.path.insert(0, ".")

import tempfile
import time
from datetime import timedelta
from pathlib import Path

from tools.cron.sentinel import parse_max_age, check_artifact_freshness


def test_parse_max_age():
    """Test max age parsing."""
    assert parse_max_age("1d") == timedelta(days=1)
    assert parse_max_age("24h") == timedelta(hours=24)
    assert parse_max_age("30m") == timedelta(minutes=30)
    assert parse_max_age("60s") == timedelta(seconds=60)
    
    print("✓ Max age parsing tests passed")


def test_artifact_freshness_fresh():
    """Test freshness check for fresh artifact."""
    with tempfile.NamedTemporaryFile(delete=False) as tmp:
        tmp.write(b"test")
        tmp_path = tmp.name
    
    try:
        result = check_artifact_freshness(tmp_path, timedelta(hours=1))
        assert result["status"] == "fresh"
        assert result["age"] is not None
    finally:
        Path(tmp_path).unlink()
    
    print("✓ Fresh artifact test passed")


def test_artifact_freshness_missing():
    """Test freshness check for missing artifact."""
    result = check_artifact_freshness("/nonexistent/file.txt", timedelta(hours=1))
    assert result["status"] == "missing"
    
    print("✓ Missing artifact test passed")


if __name__ == "__main__":
    test_parse_max_age()
    test_artifact_freshness_fresh()
    test_artifact_freshness_missing()
    print("\n✓ All cron_sentinel tests passed")

