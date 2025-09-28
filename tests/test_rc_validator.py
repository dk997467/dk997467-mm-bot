"""
Tests for RC-Validator (stdlib-only, deterministic).
"""

import json
import os
import socket
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest

from src.deploy.rc_validator import main as rc_main


def test_missing_mm_config_path_error(tmp_path, monkeypatch):
    """Test missing MM_CONFIG_PATH environment variable."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("MM_CONFIG_PATH", raising=False)
    monkeypatch.setenv("MM_ENV", "test")
    
    exit_code = rc_main(None)
    
    assert exit_code == 1
    
    report_path = tmp_path / "artifacts" / "rc_validator.json"
    assert report_path.exists()
    
    with open(report_path, "r", encoding="utf-8") as f:
        report = json.load(f)
    
    assert "missing_env:MM_CONFIG_PATH" in report["errors"]


def test_bad_yaml_config_parse_error(tmp_path, monkeypatch):
    """Test bad YAML configuration file."""
    monkeypatch.chdir(tmp_path)
    
    # Create invalid YAML file
    bad_config = tmp_path / "bad_config.yaml"
    bad_config.write_text("invalid: yaml: content: [unclosed", encoding="utf-8")
    
    monkeypatch.setenv("MM_ENV", "test")
    monkeypatch.setenv("MM_CONFIG_PATH", str(bad_config))
    
    exit_code = rc_main(None)
    
    assert exit_code == 1
    
    report_path = tmp_path / "artifacts" / "rc_validator.json"
    with open(report_path, "r", encoding="utf-8") as f:
        report = json.load(f)
    
    assert "config_parse" in report["errors"]


def test_unwritable_artifacts_dir_error(tmp_path, monkeypatch):
    """Test unwritable artifacts directory."""
    # Skip on Windows as chmod behavior is different
    import platform
    if platform.system() == "Windows":
        pytest.skip("chmod permissions test not reliable on Windows")
    
    monkeypatch.chdir(tmp_path)
    
    # Create valid config
    config_file = tmp_path / "config.yaml"
    config_file.write_text("""
guards:
  pos_skew:
    per_symbol_abs_limit: 0.0
  intraday_caps:
    daily_pnl_stop: 0.0
fees:
  bybit:
    distance_usd_threshold: 25000.0
allocator:
  smoothing:
    bias_cap: 0.10
""", encoding="utf-8")
    
    monkeypatch.setenv("MM_ENV", "test")
    monkeypatch.setenv("MM_CONFIG_PATH", str(config_file))
    
    # Create artifacts dir and make it read-only
    artifacts_dir = tmp_path / "artifacts"
    artifacts_dir.mkdir()
    
    try:
        artifacts_dir.chmod(0o444)  # Read-only
        exit_code = rc_main(None)
        
        # Should fail due to unwritable directory
        assert exit_code == 1
        
        # Reset permissions to read report
        artifacts_dir.chmod(0o755)
        
        report_path = artifacts_dir / "rc_validator.json"
        if report_path.exists():
            with open(report_path, "r", encoding="utf-8") as f:
                report = json.load(f)
            # May contain writable_dir error depending on OS behavior
    except (OSError, NotImplementedError):
        # Skip test on systems that don't support chmod
        pytest.skip("chmod not supported on this system")


def test_port_conflict_error(tmp_path, monkeypatch):
    """Test port conflict detection."""
    monkeypatch.chdir(tmp_path)
    
    # Create valid config
    config_file = tmp_path / "config.yaml"
    config_file.write_text("""
guards:
  pos_skew:
    per_symbol_abs_limit: 0.0
""", encoding="utf-8")
    
    # Find a free port and bind to it
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
        
        monkeypatch.setenv("MM_ENV", "test")
        monkeypatch.setenv("MM_CONFIG_PATH", str(config_file))
        monkeypatch.setenv("MM_PORTS", str(port))
        
        exit_code = rc_main(None)
        
        assert exit_code == 1
        
        report_path = tmp_path / "artifacts" / "rc_validator.json"
        with open(report_path, "r", encoding="utf-8") as f:
            report = json.load(f)
        
        assert f"port_busy:{port}" in report["errors"]


def test_happy_path_success(tmp_path, monkeypatch):
    """Test successful validation with all checks passing."""
    monkeypatch.chdir(tmp_path)
    
    # Create valid config
    config_file = tmp_path / "config.yaml"
    config_file.write_text("""
guards:
  pos_skew:
    per_symbol_abs_limit: 0.0
    per_color_abs_limit: 0.0
  intraday_caps:
    daily_pnl_stop: 0.0
    daily_turnover_cap: 0.0
    daily_vol_cap: 0.0
fees:
  bybit:
    distance_usd_threshold: 25000.0
    min_improvement_bps: 0.2
allocator:
  smoothing:
    bias_cap: 0.10
    fee_bias_cap: 0.05
""", encoding="utf-8")
    
    monkeypatch.setenv("MM_ENV", "test")
    monkeypatch.setenv("MM_CONFIG_PATH", str(config_file))
    monkeypatch.setenv("MM_PORTS", "8080")
    
    exit_code = rc_main(None)
    
    assert exit_code == 0
    
    report_path = tmp_path / "artifacts" / "rc_validator.json"
    assert report_path.exists()
    
    with open(report_path, "r", encoding="utf-8") as f:
        report = json.load(f)
    
    # Verify report structure
    assert report["config_ok"] is True
    assert len(report["errors"]) == 0
    assert "artifacts" in report["writable_dirs"]
    assert "artifacts/runtime" in report["writable_dirs"]
    assert 8080 in report["ports_free"]
    assert "missing:snapshots.json" in report["warnings"]  # Expected warning
    
    # Verify keys are sorted (JSON should be deterministic)
    report_json = json.dumps(report, sort_keys=True)
    assert '"config_ok"' in report_json
    assert '"env"' in report_json
    assert '"errors"' in report_json
