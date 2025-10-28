#!/usr/bin/env python3
"""E2E tests for risk_monitor_cli."""
import json
import subprocess
import sys
import os
import pytest
from pathlib import Path


class TestRiskMonitorCLIE2E:
    """E2E tests for risk monitor CLI."""
    
    def test_demo_mode_json_output(self, tmp_path):
        """Test demo mode produces valid JSON output."""
        # Run CLI in demo mode
        env = os.environ.copy()
        env['MM_FREEZE_UTC_ISO'] = '2025-01-01T00:00:00Z'
        
        result = subprocess.run(
            [
                sys.executable, "-m", "tools.live.risk_monitor_cli",
                "--demo",
                "--max-inv", "10000",
                "--max-total", "50000",
                "--edge-threshold", "1.5"
            ],
            capture_output=True,
            text=True,
            env=env,
            cwd=Path(__file__).resolve().parents[2]
        )
        
        # Check exit code
        assert result.returncode == 0, f"CLI failed: {result.stderr}"
        
        # Parse JSON output
        output = result.stdout.strip()
        assert output.endswith('\n') or output  # Should have trailing newline in original
        
        try:
            report = json.loads(output)
        except json.JSONDecodeError as e:
            pytest.fail(f"Invalid JSON output: {e}\nOutput: {output}")
        
        # Verify report structure
        assert "status" in report
        assert report["status"] == "OK"
        
        assert "frozen" in report
        assert isinstance(report["frozen"], bool)
        
        assert "positions" in report
        assert isinstance(report["positions"], dict)
        
        assert "metrics" in report
        metrics = report["metrics"]
        assert "blocks_total" in metrics
        assert "freezes_total" in metrics
        assert "last_freeze_reason" in metrics
        assert "last_freeze_symbol" in metrics
        
        assert "runtime" in report
        runtime = report["runtime"]
        assert "utc" in runtime
        assert runtime["utc"] == "2025-01-01T00:00:00Z"
        assert "version" in runtime
    
    def test_demo_mode_deterministic_output(self, tmp_path):
        """Test demo mode produces deterministic output."""
        env = os.environ.copy()
        env['MM_FREEZE_UTC_ISO'] = '2025-01-01T00:00:00Z'
        
        # Run CLI twice
        result1 = subprocess.run(
            [
                sys.executable, "-m", "tools.live.risk_monitor_cli",
                "--demo",
                "--max-inv", "10000",
                "--max-total", "50000",
                "--edge-threshold", "1.5"
            ],
            capture_output=True,
            text=True,
            env=env,
            cwd=Path(__file__).resolve().parents[2]
        )
        
        result2 = subprocess.run(
            [
                sys.executable, "-m", "tools.live.risk_monitor_cli",
                "--demo",
                "--max-inv", "10000",
                "--max-total", "50000",
                "--edge-threshold", "1.5"
            ],
            capture_output=True,
            text=True,
            env=env,
            cwd=Path(__file__).resolve().parents[2]
        )
        
        # Outputs should be identical
        assert result1.stdout == result2.stdout
        assert result1.returncode == result2.returncode
    
    def test_demo_mode_without_frozen_time(self, tmp_path):
        """Test demo mode works without MM_FREEZE_UTC_ISO."""
        env = os.environ.copy()
        # Ensure MM_FREEZE_UTC_ISO is not set
        env.pop('MM_FREEZE_UTC_ISO', None)
        
        result = subprocess.run(
            [
                sys.executable, "-m", "tools.live.risk_monitor_cli",
                "--demo",
                "--max-inv", "10000",
                "--max-total", "50000",
                "--edge-threshold", "1.5"
            ],
            capture_output=True,
            text=True,
            env=env,
            cwd=Path(__file__).resolve().parents[2]
        )
        
        assert result.returncode == 0
        
        # Parse output
        report = json.loads(result.stdout.strip())
        
        # UTC should be present and in ISO format
        assert "runtime" in report
        assert "utc" in report["runtime"]
        utc = report["runtime"]["utc"]
        
        # Basic ISO format check (YYYY-MM-DDTHH:MM:SSZ)
        assert len(utc) >= 19
        assert "T" in utc
        assert utc.endswith("Z")
    
    def test_demo_mode_custom_limits(self, tmp_path):
        """Test demo mode with custom limits."""
        env = os.environ.copy()
        env['MM_FREEZE_UTC_ISO'] = '2025-01-01T00:00:00Z'
        
        result = subprocess.run(
            [
                sys.executable, "-m", "tools.live.risk_monitor_cli",
                "--demo",
                "--max-inv", "5000",
                "--max-total", "10000",
                "--edge-threshold", "2.0"
            ],
            capture_output=True,
            text=True,
            env=env,
            cwd=Path(__file__).resolve().parents[2]
        )
        
        assert result.returncode == 0
        
        report = json.loads(result.stdout.strip())
        
        # Verify report is valid
        assert report["status"] == "OK"
        assert "frozen" in report
        assert "metrics" in report
    
    def test_cli_without_demo_flag_shows_help(self, tmp_path):
        """Test CLI without --demo flag shows help."""
        result = subprocess.run(
            [sys.executable, "-m", "tools.live.risk_monitor_cli"],
            capture_output=True,
            text=True,
            cwd=Path(__file__).resolve().parents[2]
        )
        
        assert result.returncode == 0
        assert "usage:" in result.stdout.lower() or "--demo" in result.stdout


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])

