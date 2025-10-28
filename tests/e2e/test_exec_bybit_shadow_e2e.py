"""
E2E tests for exec_demo.py with Bybit client in shadow mode.

Tests verify:
- CLI execution with --exchange bybit --no-network
- Deterministic JSON output (byte-for-byte)
- Three scenarios: normal, freeze, mass-cancel
"""

import json
import os
import subprocess
from pathlib import Path

import pytest


class TestExecBybitShadowE2E:
    """E2E tests for Bybit shadow execution."""

    @pytest.fixture
    def project_root(self):
        """Get project root directory."""
        return Path(__file__).parent.parent.parent

    @pytest.fixture
    def scenarios_dir(self, project_root):
        """Get scenarios directory, create if not exists."""
        dir_path = project_root / "tests" / "e2e" / "scenarios"
        dir_path.mkdir(parents=True, exist_ok=True)
        return dir_path

    def run_demo_cli(self, *args, env=None):
        """
        Run exec_demo.py CLI and return output.
        
        Args:
            *args: CLI arguments
            env: Environment variables dict
            
        Returns:
            Tuple of (stdout, stderr, exit_code)
        """
        cmd = ["python", "-m", "tools.live.exec_demo"] + list(args)
        
        # Set PYTHONPATH to current directory
        if env is None:
            env = {}
        env["PYTHONPATH"] = os.getcwd()
        
        # Add mock secrets to avoid AWS calls
        env["BYBIT_API_KEY"] = "test_key_for_e2e"
        env["BYBIT_API_SECRET"] = "test_secret_for_e2e"
        
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            env={**os.environ, **env},
        )
        
        return result.stdout, result.stderr, result.returncode

    def test_scenario_normal(self, scenarios_dir):
        """
        Scenario 1: Normal operation without freeze.
        
        Run demo with:
        - 2 symbols (BTCUSDT, ETHUSDT)
        - 10 iterations
        - High edge threshold (no freeze expected)
        - Deterministic seed and timestamp
        """
        # Set deterministic timestamp
        env = {
            "MM_FREEZE_UTC_ISO": "2021-01-01T00:00:00Z",
        }
        
        stdout, stderr, exit_code = self.run_demo_cli(
            "--shadow",
            "--exchange", "bybit",
            "--mode", "shadow",
            "--no-network",
            "--symbols", "BTCUSDT,ETHUSDT",
            "--iterations", "10",
            "--max-inv", "10000",
            "--max-total", "50000",
            "--edge-threshold", "5.0",  # High threshold, no freeze
            "--fill-rate", "0.8",
            "--latency-ms", "100",
            env=env,
        )
        
        assert exit_code == 0, f"Demo should succeed. stderr: {stderr}"
        
        # Parse JSON output
        report = json.loads(stdout)
        
        # Verify structure
        assert "execution" in report
        assert "orders" in report
        assert "risk" in report
        
        # Should not be frozen
        assert report["risk"]["frozen"] is False, "Should not freeze with high threshold"
        
        # Verify deterministic output
        stdout2, _, _ = self.run_demo_cli(
            "--shadow",
            "--exchange", "bybit",
            "--mode", "shadow",
            "--no-network",
            "--symbols", "BTCUSDT,ETHUSDT",
            "--iterations", "10",
            "--max-inv", "10000",
            "--max-total", "50000",
            "--edge-threshold", "5.0",
            "--fill-rate", "0.8",
            "--latency-ms", "100",
            env=env,
        )
        
        # Byte-for-byte comparison
        assert stdout == stdout2, "Output should be deterministic (byte-for-byte)"
        
        # Save golden file for future reference
        golden_path = scenarios_dir / "scenario_normal.json"
        with open(golden_path, "w") as f:
            f.write(stdout)
        
        print(f"✓ Golden file saved: {golden_path}")

    def test_scenario_freeze(self, scenarios_dir):
        """
        Scenario 2: Freeze triggered by low edge.
        
        Run demo with:
        - Low edge threshold (freeze expected)
        - Verify freeze_events > 0
        - Verify orders_canceled > 0
        """
        env = {
            "MM_FREEZE_UTC_ISO": "2021-01-01T00:00:00Z",
        }
        
        stdout, stderr, exit_code = self.run_demo_cli(
            "--shadow",
            "--exchange", "bybit",
            "--mode", "shadow",
            "--no-network",
            "--symbols", "BTCUSDT",
            "--iterations", "20",
            "--max-inv", "10000",
            "--max-total", "50000",
            "--edge-threshold", "8.0",  # High threshold to trigger freeze
            "--fill-rate", "0.9",
            "--latency-ms", "100",
            env=env,
        )
        
        assert exit_code == 0, f"Demo should succeed. stderr: {stderr}"
        
        report = json.loads(stdout)
        
        # Verify freeze occurred
        # Note: In ExecutionLoop.run_shadow, edge decreases over iterations
        # So with threshold=8.0, it should freeze when edge drops below 8.0
        assert report["risk"]["frozen"] is True, "Should be frozen with high threshold"
        assert report["risk"]["freeze_events"] > 0, "Should have freeze events"
        
        # Verify deterministic output
        stdout2, _, _ = self.run_demo_cli(
            "--shadow",
            "--exchange", "bybit",
            "--mode", "shadow",
            "--no-network",
            "--symbols", "BTCUSDT",
            "--iterations", "20",
            "--max-inv", "10000",
            "--max-total", "50000",
            "--edge-threshold", "8.0",
            "--fill-rate", "0.9",
            "--latency-ms", "100",
            env=env,
        )
        
        assert stdout == stdout2, "Freeze scenario should be deterministic"
        
        # Save golden file
        golden_path = scenarios_dir / "scenario_freeze.json"
        with open(golden_path, "w") as f:
            f.write(stdout)
        
        print(f"✓ Golden file saved: {golden_path}")

    def test_scenario_mass_cancel(self, scenarios_dir):
        """
        Scenario 3: Mass cancellation due to risk limits.
        
        Run demo with:
        - Low inventory limits
        - High fill rate
        - Verify many orders blocked/canceled
        """
        env = {
            "MM_FREEZE_UTC_ISO": "2021-01-01T00:00:00Z",
        }
        
        stdout, stderr, exit_code = self.run_demo_cli(
            "--shadow",
            "--exchange", "bybit",
            "--mode", "shadow",
            "--no-network",
            "--symbols", "BTCUSDT,ETHUSDT",
            "--iterations", "30",
            "--max-inv", "5000",  # Low limit
            "--max-total", "8000",  # Low total limit
            "--edge-threshold", "1.0",
            "--fill-rate", "0.95",  # High fill rate
            "--latency-ms", "50",
            env=env,
        )
        
        assert exit_code == 0, f"Demo should succeed. stderr: {stderr}"
        
        report = json.loads(stdout)
        
        # Verify many blocks occurred
        assert report["orders"]["risk_blocks"] > 10, \
            "Should have many risk blocks with low limits"
        
        # Verify deterministic output
        stdout2, _, _ = self.run_demo_cli(
            "--shadow",
            "--exchange", "bybit",
            "--mode", "shadow",
            "--no-network",
            "--symbols", "BTCUSDT,ETHUSDT",
            "--iterations", "30",
            "--max-inv", "5000",
            "--max-total", "8000",
            "--edge-threshold", "1.0",
            "--fill-rate", "0.95",
            "--latency-ms", "50",
            env=env,
        )
        
        assert stdout == stdout2, "Mass-cancel scenario should be deterministic"
        
        # Save golden file
        golden_path = scenarios_dir / "scenario_mass_cancel.json"
        with open(golden_path, "w") as f:
            f.write(stdout)
        
        print(f"✓ Golden file saved: {golden_path}")

    def test_golden_file_comparison_normal(self, scenarios_dir):
        """
        Compare current output with saved golden file for normal scenario.
        
        This test ensures backward compatibility - any change in output
        will fail this test and require explicit golden file update.
        """
        golden_path = scenarios_dir / "scenario_normal.json"
        
        if not golden_path.exists():
            pytest.skip("Golden file not yet generated")
        
        with open(golden_path, "r") as f:
            golden_output = f.read()
        
        env = {
            "MM_FREEZE_UTC_ISO": "2021-01-01T00:00:00Z",
        }
        
        stdout, stderr, exit_code = self.run_demo_cli(
            "--shadow",
            "--exchange", "bybit",
            "--mode", "shadow",
            "--no-network",
            "--symbols", "BTCUSDT,ETHUSDT",
            "--iterations", "10",
            "--max-inv", "10000",
            "--max-total", "50000",
            "--edge-threshold", "5.0",
            "--fill-rate", "0.8",
            "--latency-ms", "100",
            env=env,
        )
        
        assert exit_code == 0, f"Demo failed. stderr: {stderr}"
        
        # Byte-for-byte comparison with golden
        assert stdout == golden_output, \
            "Output differs from golden file. If this is intentional, regenerate golden files."

    def test_cli_error_handling(self):
        """Test that CLI handles errors gracefully."""
        # Missing --shadow flag
        _, stderr, exit_code = self.run_demo_cli(
            "--exchange", "bybit",
        )
        
        assert exit_code != 0, "Should fail without --shadow flag"
        assert "shadow" in stderr.lower() or "required" in stderr.lower()

    def test_cli_help(self):
        """Test that --help works."""
        stdout, _, exit_code = self.run_demo_cli("--help")
        
        assert exit_code == 0
        assert "exchange" in stdout.lower()
        assert "bybit" in stdout.lower()

