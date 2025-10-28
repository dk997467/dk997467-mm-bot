#!/usr/bin/env python3
"""
Unit tests for tools/freeze_config.py — Configuration freeze snapshot tool.

Tests:
- create_freeze_snapshot() with valid config
- main() CLI function
- Edge cases: missing source file, various config types
"""
import json
import pytest
import warnings
from pathlib import Path
from datetime import datetime
from tools.freeze_config import create_freeze_snapshot, main


# Ignore DeprecationWarning for datetime.utcnow() in Python 3.13+
pytestmark = pytest.mark.filterwarnings("ignore::DeprecationWarning:tools.freeze_config")


# ======================================================================
# Test create_freeze_snapshot
# ======================================================================

def test_create_freeze_snapshot_success(tmp_path, monkeypatch):
    """Test create_freeze_snapshot successfully creates snapshot."""
    # Change to tmp_path so artifacts are created there
    monkeypatch.chdir(tmp_path)
    
    # Create source config
    source_config = {"param1": 1.5, "param2": "value", "param3": 100}
    source_file = tmp_path / "config.json"
    source_file.write_text(json.dumps(source_config))
    
    # Create snapshot
    result = create_freeze_snapshot(str(source_file), "test_label")
    
    assert result == 0
    
    # Check snapshot directory exists
    snapshot_dir = tmp_path / "artifacts" / "soak" / "snapshots"
    assert snapshot_dir.exists()
    
    # Check snapshot file exists (with timestamp)
    snapshot_files = list(snapshot_dir.glob("freeze_test_label_*.json"))
    assert len(snapshot_files) == 1
    
    # Check snapshot content
    with open(snapshot_files[0], "r", encoding="utf-8") as f:
        snapshot = json.load(f)
    
    assert "metadata" in snapshot
    assert "config" in snapshot
    assert snapshot["metadata"]["label"] == "test_label"
    assert snapshot["metadata"]["source"] == str(source_file)
    assert snapshot["metadata"]["version"] == "1.0"
    assert snapshot["config"] == source_config


def test_create_freeze_snapshot_creates_directory(tmp_path, monkeypatch):
    """Test create_freeze_snapshot creates snapshot directory if missing."""
    monkeypatch.chdir(tmp_path)
    
    # Create source config
    source_file = tmp_path / "config.json"
    source_file.write_text('{"test": 1}')
    
    # Snapshot directory doesn't exist yet
    snapshot_dir = tmp_path / "artifacts" / "soak" / "snapshots"
    assert not snapshot_dir.exists()
    
    # Create snapshot
    create_freeze_snapshot(str(source_file), "test")
    
    # Directory should now exist
    assert snapshot_dir.exists()


def test_create_freeze_snapshot_missing_source(tmp_path, monkeypatch, capsys):
    """Test create_freeze_snapshot handles missing source file."""
    monkeypatch.chdir(tmp_path)
    
    nonexistent_file = tmp_path / "does_not_exist.json"
    
    result = create_freeze_snapshot(str(nonexistent_file), "test_label")
    
    # Should return error code
    assert result == 1
    
    # Check error message was printed
    captured = capsys.readouterr()
    assert "[ERROR]" in captured.out
    assert "not found" in captured.out


def test_create_freeze_snapshot_timestamp_format(tmp_path, monkeypatch):
    """Test create_freeze_snapshot uses correct timestamp format."""
    monkeypatch.chdir(tmp_path)
    
    source_file = tmp_path / "config.json"
    source_file.write_text('{"test": 1}')
    
    create_freeze_snapshot(str(source_file), "label")
    
    # Check snapshot filename format: freeze_label_YYYYMMDD_HHMMSS.json
    snapshot_dir = tmp_path / "artifacts" / "soak" / "snapshots"
    snapshot_files = list(snapshot_dir.glob("freeze_label_*.json"))
    
    assert len(snapshot_files) == 1
    
    filename = snapshot_files[0].name
    # Format: freeze_label_20250127_123456.json
    assert filename.startswith("freeze_label_")
    assert filename.endswith(".json")
    
    # Extract timestamp part
    timestamp_part = filename.replace("freeze_label_", "").replace(".json", "")
    # Should be YYYYMMDD_HHMMSS format (15 chars)
    assert len(timestamp_part) == 15
    assert timestamp_part[8] == "_"  # Underscore between date and time


def test_create_freeze_snapshot_metadata_fields(tmp_path, monkeypatch):
    """Test create_freeze_snapshot includes all required metadata."""
    monkeypatch.chdir(tmp_path)
    
    source_file = tmp_path / "config.json"
    source_file.write_text('{"test": 1}')
    
    create_freeze_snapshot(str(source_file), "my_label")
    
    snapshot_dir = tmp_path / "artifacts" / "soak" / "snapshots"
    snapshot_files = list(snapshot_dir.glob("freeze_my_label_*.json"))
    
    with open(snapshot_files[0], "r", encoding="utf-8") as f:
        snapshot = json.load(f)
    
    metadata = snapshot["metadata"]
    
    # Check all required fields
    assert "label" in metadata
    assert "created_at" in metadata
    assert "source" in metadata
    assert "version" in metadata
    
    # Check created_at is ISO format with Z suffix
    assert metadata["created_at"].endswith("Z")
    # Should be parseable as ISO datetime
    datetime.fromisoformat(metadata["created_at"].rstrip("Z"))


def test_create_freeze_snapshot_various_config_types(tmp_path, monkeypatch):
    """Test create_freeze_snapshot handles various config value types."""
    monkeypatch.chdir(tmp_path)
    
    source_config = {
        "float_param": 1.23,
        "int_param": 42,
        "string_param": "value",
        "bool_param": True,
        "null_param": None,
        "list_param": [1, 2, 3],
        "dict_param": {"nested": "value"}
    }
    source_file = tmp_path / "config.json"
    source_file.write_text(json.dumps(source_config))
    
    create_freeze_snapshot(str(source_file), "test")
    
    snapshot_dir = tmp_path / "artifacts" / "soak" / "snapshots"
    snapshot_files = list(snapshot_dir.glob("freeze_test_*.json"))
    
    with open(snapshot_files[0], "r", encoding="utf-8") as f:
        snapshot = json.load(f)
    
    # Config should be preserved exactly
    assert snapshot["config"] == source_config


def test_create_freeze_snapshot_empty_config(tmp_path, monkeypatch):
    """Test create_freeze_snapshot handles empty config."""
    monkeypatch.chdir(tmp_path)
    
    source_file = tmp_path / "config.json"
    source_file.write_text('{}')
    
    result = create_freeze_snapshot(str(source_file), "empty")
    
    assert result == 0
    
    snapshot_dir = tmp_path / "artifacts" / "soak" / "snapshots"
    snapshot_files = list(snapshot_dir.glob("freeze_empty_*.json"))
    
    with open(snapshot_files[0], "r", encoding="utf-8") as f:
        snapshot = json.load(f)
    
    assert snapshot["config"] == {}


# ======================================================================
# Test main() CLI function
# ======================================================================

def test_main_success(tmp_path, monkeypatch):
    """Test main() successfully creates snapshot."""
    monkeypatch.chdir(tmp_path)
    
    source_file = tmp_path / "source.json"
    source_file.write_text('{"param": 1}')
    
    exit_code = main(["--source", str(source_file), "--label", "cli_test"])
    
    assert exit_code == 0
    
    # Check snapshot was created
    snapshot_dir = tmp_path / "artifacts" / "soak" / "snapshots"
    snapshot_files = list(snapshot_dir.glob("freeze_cli_test_*.json"))
    assert len(snapshot_files) == 1


def test_main_missing_source(tmp_path, monkeypatch):
    """Test main() handles missing source file."""
    monkeypatch.chdir(tmp_path)
    
    exit_code = main(["--source", "nonexistent.json", "--label", "test"])
    
    assert exit_code == 1


def test_main_requires_source_argument():
    """Test main() requires --source argument."""
    with pytest.raises(SystemExit):
        main(["--label", "test"])


def test_main_requires_label_argument(tmp_path):
    """Test main() requires --label argument."""
    source_file = tmp_path / "config.json"
    source_file.write_text('{}')
    
    with pytest.raises(SystemExit):
        main(["--source", str(source_file)])


def test_main_label_with_special_characters(tmp_path, monkeypatch):
    """Test main() handles labels with special characters."""
    monkeypatch.chdir(tmp_path)
    
    source_file = tmp_path / "config.json"
    source_file.write_text('{"test": 1}')
    
    # Labels with underscores, hyphens, etc.
    labels = ["test-label", "test_label", "test.label", "2025Q4"]
    
    for label in labels:
        exit_code = main(["--source", str(source_file), "--label", label])
        assert exit_code == 0
        
        # Check snapshot was created
        snapshot_dir = tmp_path / "artifacts" / "soak" / "snapshots"
        snapshot_files = list(snapshot_dir.glob(f"freeze_{label}_*.json"))
        assert len(snapshot_files) >= 1


# ======================================================================
# Integration Tests
# ======================================================================

def test_create_snapshot_multiple_times(tmp_path, monkeypatch):
    """Test creating multiple snapshots with same label."""
    import time
    
    monkeypatch.chdir(tmp_path)
    
    source_file = tmp_path / "config.json"
    source_file.write_text('{"version": 1}')
    
    # Create first snapshot
    create_freeze_snapshot(str(source_file), "same_label")
    
    # Small delay to ensure different timestamp
    time.sleep(0.1)
    
    # Update config
    source_file.write_text('{"version": 2}')
    
    # Create second snapshot with same label
    create_freeze_snapshot(str(source_file), "same_label")
    
    # At least one snapshot should exist
    snapshot_dir = tmp_path / "artifacts" / "soak" / "snapshots"
    snapshot_files = list(snapshot_dir.glob("freeze_same_label_*.json"))
    
    # Due to timestamp resolution, might be 1 or 2 files
    assert len(snapshot_files) >= 1
    
    # If we have 2 files, check they have different content
    if len(snapshot_files) == 2:
        with open(snapshot_files[0], "r", encoding="utf-8") as f:
            s1 = json.load(f)
        with open(snapshot_files[1], "r", encoding="utf-8") as f:
            s2 = json.load(f)
        
        assert s1["config"]["version"] != s2["config"]["version"]


# ======================================================================
# Run tests
# ======================================================================

if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])

