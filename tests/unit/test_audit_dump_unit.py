#!/usr/bin/env python3
"""
Unit tests for tools/audit/dump.py — Artifact dump utility.

Tests:
- collect_artifacts() with temp directories
- main() with mocked arguments
- Edge cases: empty dir, missing dir, permission errors
"""
import json
import pytest
from pathlib import Path
from tools.audit.dump import collect_artifacts, main


# ======================================================================
# Test collect_artifacts
# ======================================================================

def test_collect_artifacts_empty_directory(tmp_path):
    """Test collect_artifacts on empty directory returns empty list."""
    empty_dir = tmp_path / "empty"
    empty_dir.mkdir()
    
    result = collect_artifacts(empty_dir)
    
    assert result == []


def test_collect_artifacts_nonexistent_directory(tmp_path):
    """Test collect_artifacts on non-existent directory returns empty list."""
    nonexistent = tmp_path / "does_not_exist"
    
    result = collect_artifacts(nonexistent)
    
    assert result == []


def test_collect_artifacts_single_file(tmp_path):
    """Test collect_artifacts with single file."""
    test_file = tmp_path / "test.txt"
    test_file.write_text("Hello, World!")
    
    result = collect_artifacts(tmp_path)
    
    assert len(result) == 1
    assert result[0]["path"] == "test.txt"
    assert result[0]["size"] == len("Hello, World!")
    assert result[0]["type"] == ".txt"
    assert "modified" in result[0]


def test_collect_artifacts_multiple_files(tmp_path):
    """Test collect_artifacts with multiple files."""
    (tmp_path / "file1.json").write_text("{}")
    (tmp_path / "file2.log").write_text("log entry")
    (tmp_path / "file3").write_text("no extension")
    
    result = collect_artifacts(tmp_path)
    
    assert len(result) == 3
    
    # Check all files are present
    paths = {item["path"] for item in result}
    assert paths == {"file1.json", "file2.log", "file3"}
    
    # Check types
    types = {item["type"] for item in result}
    assert ".json" in types
    assert ".log" in types
    assert "unknown" in types


def test_collect_artifacts_nested_directories(tmp_path):
    """Test collect_artifacts with nested directory structure."""
    nested = tmp_path / "level1" / "level2"
    nested.mkdir(parents=True)
    
    (tmp_path / "root.txt").write_text("root")
    (tmp_path / "level1" / "mid.txt").write_text("mid")
    (nested / "deep.txt").write_text("deep")
    
    result = collect_artifacts(tmp_path)
    
    assert len(result) == 3
    
    # Check paths are relative to base
    paths = {item["path"] for item in result}
    assert "root.txt" in paths
    assert str(Path("level1") / "mid.txt") in paths
    assert str(Path("level1") / "level2" / "deep.txt") in paths


def test_collect_artifacts_ignores_directories(tmp_path):
    """Test collect_artifacts only collects files, not directories."""
    (tmp_path / "dir1").mkdir()
    (tmp_path / "dir2").mkdir()
    (tmp_path / "file.txt").write_text("test")
    
    result = collect_artifacts(tmp_path)
    
    # Should only have the file, not directories
    assert len(result) == 1
    assert result[0]["path"] == "file.txt"


def test_collect_artifacts_file_sizes(tmp_path):
    """Test collect_artifacts correctly reports file sizes."""
    small_file = tmp_path / "small.txt"
    small_file.write_text("a" * 10)
    
    large_file = tmp_path / "large.txt"
    large_file.write_text("b" * 1000)
    
    result = collect_artifacts(tmp_path)
    
    sizes = {item["path"]: item["size"] for item in result}
    assert sizes["small.txt"] == 10
    assert sizes["large.txt"] == 1000


# ======================================================================
# Test main() CLI function
# ======================================================================

def test_main_success(tmp_path):
    """Test main() successfully creates index file."""
    # Create test artifacts
    artifacts_dir = tmp_path / "artifacts"
    artifacts_dir.mkdir()
    (artifacts_dir / "test1.json").write_text("{}")
    (artifacts_dir / "test2.log").write_text("log")
    
    output_file = tmp_path / "out" / "DUMP_INDEX.json"
    
    # Run main with custom args
    exit_code = main(["--base", str(artifacts_dir), "--out", str(output_file)])
    
    # Should exit successfully
    assert exit_code == 0
    
    # Check output file exists
    assert output_file.exists()
    
    # Check output content
    with open(output_file, "r", encoding="utf-8") as f:
        index = json.load(f)
    
    assert index["status"] == "OK"
    assert index["base_dir"] == str(artifacts_dir)
    assert index["artifact_count"] == 2
    assert len(index["artifacts"]) == 2


def test_main_creates_output_directory(tmp_path):
    """Test main() creates output directory if it doesn't exist."""
    artifacts_dir = tmp_path / "artifacts"
    artifacts_dir.mkdir()
    (artifacts_dir / "file.txt").write_text("test")
    
    # Output dir doesn't exist yet
    output_file = tmp_path / "deep" / "nested" / "out.json"
    assert not output_file.parent.exists()
    
    # Run main
    exit_code = main(["--base", str(artifacts_dir), "--out", str(output_file)])
    
    assert exit_code == 0
    assert output_file.exists()


def test_main_empty_artifacts_directory(tmp_path):
    """Test main() with empty artifacts directory."""
    artifacts_dir = tmp_path / "artifacts"
    artifacts_dir.mkdir()
    
    output_file = tmp_path / "out.json"
    
    exit_code = main(["--base", str(artifacts_dir), "--out", str(output_file)])
    
    assert exit_code == 0
    
    # Check index shows 0 artifacts
    with open(output_file, "r", encoding="utf-8") as f:
        index = json.load(f)
    
    assert index["artifact_count"] == 0
    assert index["artifacts"] == []


def test_main_nonexistent_base_directory(tmp_path):
    """Test main() with non-existent base directory (graceful handling)."""
    artifacts_dir = tmp_path / "does_not_exist"
    output_file = tmp_path / "out.json"
    
    exit_code = main(["--base", str(artifacts_dir), "--out", str(output_file)])
    
    # Should still succeed (returns empty list)
    assert exit_code == 0
    
    # Check index shows 0 artifacts
    with open(output_file, "r", encoding="utf-8") as f:
        index = json.load(f)
    
    assert index["artifact_count"] == 0


def test_main_default_arguments(tmp_path, monkeypatch):
    """Test main() uses default arguments when none provided."""
    # Change to tmp_path so "artifacts" is created there
    monkeypatch.chdir(tmp_path)
    
    # Create default artifacts directory
    artifacts_dir = tmp_path / "artifacts"
    artifacts_dir.mkdir()
    (artifacts_dir / "test.txt").write_text("test")
    
    # Run main with no args (uses defaults)
    exit_code = main([])
    
    assert exit_code == 0
    
    # Check default output location
    default_output = tmp_path / "artifacts" / "audit" / "DUMP_INDEX.json"
    assert default_output.exists()


# ======================================================================
# Test Edge Cases
# ======================================================================

def test_collect_artifacts_with_special_characters(tmp_path):
    """Test collect_artifacts handles filenames with special characters."""
    (tmp_path / "file with spaces.txt").write_text("test")
    (tmp_path / "file-with-dashes.log").write_text("test")
    (tmp_path / "file_with_underscores.json").write_text("test")
    
    result = collect_artifacts(tmp_path)
    
    assert len(result) == 3
    paths = {item["path"] for item in result}
    assert "file with spaces.txt" in paths
    assert "file-with-dashes.log" in paths
    assert "file_with_underscores.json" in paths


def test_collect_artifacts_hidden_files_included(tmp_path):
    """Test collect_artifacts includes hidden files (starting with dot)."""
    (tmp_path / ".hidden").write_text("hidden")
    (tmp_path / "visible.txt").write_text("visible")
    
    result = collect_artifacts(tmp_path)
    
    # Should include hidden files
    assert len(result) == 2
    paths = {item["path"] for item in result}
    assert ".hidden" in paths


# ======================================================================
# Run tests
# ======================================================================

if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])

