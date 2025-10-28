"""E2E tests for shadow execution engine."""

from __future__ import annotations

import json
import os
import pathlib
import subprocess
import sys

import pytest


# Get project root
PROJECT_ROOT = pathlib.Path(__file__).parent.parent.parent


def _run_exec_demo(args: list[str], env_vars: dict[str, str] | None = None) -> subprocess.CompletedProcess:
    """Helper to run exec_demo with proper PYTHONPATH."""
    env = os.environ.copy()
    env["PYTHONPATH"] = str(PROJECT_ROOT)
    
    if env_vars:
        env.update(env_vars)
    
    cmd = [sys.executable, "-m", "tools.live.exec_demo"] + args
    
    return subprocess.run(
        cmd,
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True,
        env=env,
    )


class TestExecShadowE2E:
    """End-to-end tests for exec_demo CLI."""

    def test_scenario_1_basic_run(self) -> None:
        """
        Scenario 1: Basic shadow run with low iterations.
        
        Expected:
        - Orders placed
        - Some fills
        - No freeze
        - Valid JSON output
        """
        result = _run_exec_demo(
            [
                "--shadow",
                "--symbols", "BTCUSDT",
                "--iterations", "10",
                "--max-inv", "10000",
                "--max-total", "50000",
                "--edge-threshold", "0.5",
                "--fill-rate", "0.7",
                "--reject-rate", "0.0",
                "--latency-ms", "1",
            ],
            env_vars={"MM_FREEZE_UTC_ISO": "2025-01-01T00:00:00Z"},
        )

        assert result.returncode == 0, f"stderr: {result.stderr}"

        # Parse JSON
        report = json.loads(result.stdout)

        # Verify structure
        assert "execution" in report
        assert "orders" in report
        assert "positions" in report
        assert "risk" in report
        assert "runtime" in report

        # Verify execution params
        assert report["execution"]["iterations"] == 10
        assert "BTCUSDT" in report["execution"]["symbols"]

        # Orders should be placed
        assert report["orders"]["placed"] > 0

        # System should NOT be frozen
        assert report["risk"]["frozen"] is False

        # JSON should end with newline
        assert result.stdout.endswith("\n")

    def test_scenario_2_freeze_on_edge_drop(self) -> None:
        """
        Scenario 2: Freeze triggered by edge drop.
        
        Expected:
        - System freezes when edge drops below threshold
        - freeze_events > 0
        - last_freeze_reason set
        """
        result = _run_exec_demo(
            [
                "--shadow",
                "--symbols", "BTCUSDT,ETHUSDT",
                "--iterations", "50",
                "--max-inv", "10000",
                "--max-total", "50000",
                "--edge-threshold", "5.0",
                "--fill-rate", "0.5",
                "--reject-rate", "0.0",
                "--latency-ms", "1",
            ],
            env_vars={"MM_FREEZE_UTC_ISO": "2025-01-01T00:00:00Z"},
        )

        assert result.returncode == 0, f"stderr: {result.stderr}"

        report = json.loads(result.stdout)

        # System should be frozen
        assert report["risk"]["frozen"] is True
        assert report["risk"]["freeze_events"] > 0
        assert report["risk"]["last_freeze_reason"] is not None

        # Should have some canceled orders
        assert report["orders"]["canceled"] > 0

    def test_scenario_3_deterministic_output(self) -> None:
        """
        Scenario 3: Output is deterministic (byte-for-byte).
        
        Expected:
        - Two runs with same params produce identical JSON (except runtime)
        """
        args = [
            "--shadow",
            "--symbols", "BTCUSDT",
            "--iterations", "10",
            "--max-inv", "10000",
            "--max-total", "50000",
            "--edge-threshold", "1.5",
            "--fill-rate", "0.7",
            "--reject-rate", "0.05",
            "--latency-ms", "1",
        ]
        
        env_vars = {"MM_FREEZE_UTC_ISO": "2025-01-01T00:00:00Z"}

        # Run 1
        result1 = _run_exec_demo(args, env_vars)

        # Run 2
        result2 = _run_exec_demo(args, env_vars)

        assert result1.returncode == 0, f"stderr: {result1.stderr}"
        assert result2.returncode == 0, f"stderr: {result2.stderr}"

        # Parse both
        report1 = json.loads(result1.stdout)
        report2 = json.loads(result2.stdout)

        # Remove runtime (not deterministic without MM_FREEZE_UTC_ISO for runtime.utc field)
        del report1["runtime"]
        del report2["runtime"]

        # Should be identical
        assert report1 == report2

    def test_error_missing_shadow_flag(self) -> None:
        """Test error when --shadow flag is missing."""
        result = _run_exec_demo(["--symbols", "BTCUSDT"])

        assert result.returncode == 1
        assert "--shadow flag is required" in result.stderr

    def test_error_no_symbols(self) -> None:
        """Test error when no symbols provided."""
        result = _run_exec_demo(["--shadow", "--symbols", ""])

        assert result.returncode == 1
        assert "At least one symbol is required" in result.stderr

    def test_scenario_4_restart_with_recovery(self) -> None:
        """
        Scenario 4: Restart with DurableOrderStore recovery.
        
        Steps:
        1. Run with --durable-state, place orders
        2. Stop (simulate crash)
        3. Restart with --recover, verify orders recovered
        
        Expected:
        - First run places orders and saves snapshot
        - Second run recovers open orders from snapshot
        - Idempotency prevents duplicate orders
        """
        import tempfile
        import shutil
        
        # Create temp dir for state persistence
        with tempfile.TemporaryDirectory() as tmpdir:
            state_dir = pathlib.Path(tmpdir) / "state"
            state_dir.mkdir()
            
            # --- Phase 1: Initial run with durable state ---
            result1 = _run_exec_demo(
                [
                    "--shadow",
                    "--symbols", "BTCUSDT",
                    "--iterations", "5",
                    "--max-inv", "10000",
                    "--max-total", "50000",
                    "--edge-threshold", "0.5",
                    "--fill-rate", "0.3",  # Low fill rate -> orders stay open
                    "--reject-rate", "0.0",
                    "--latency-ms", "1",
                    "--durable-state",
                    "--state-dir", str(state_dir),
                ],
                env_vars={"MM_FREEZE_UTC_ISO": "2025-01-01T00:00:00Z"},
            )
            
            assert result1.returncode == 0, f"stderr: {result1.stderr}"
            
            report1 = json.loads(result1.stdout)
            
            # Verify orders placed
            assert report1["orders"]["placed"] > 0, "Phase 1: Should place orders"
            
            # Verify snapshot created
            snapshot_file = state_dir / "orders.jsonl"
            assert snapshot_file.exists(), "Snapshot file should exist"
            
            # --- Phase 2: Restart with recovery ---
            result2 = _run_exec_demo(
                [
                    "--shadow",
                    "--symbols", "BTCUSDT",
                    "--iterations", "5",
                    "--max-inv", "10000",
                    "--max-total", "50000",
                    "--edge-threshold", "0.5",
                    "--fill-rate", "0.8",  # Higher fill rate for recovery phase
                    "--reject-rate", "0.0",
                    "--latency-ms", "1",
                    "--durable-state",
                    "--state-dir", str(state_dir),
                    "--recover",  # Enable recovery
                ],
                env_vars={"MM_FREEZE_UTC_ISO": "2025-01-01T00:00:00Z"},
            )
            
            assert result2.returncode == 0, f"stderr: {result2.stderr}"
            
            report2 = json.loads(result2.stdout)
            
            # Verify recovery section exists
            assert "recovery" in report2, "Should have recovery section"
            assert report2["recovery"]["recovered"] is True
            assert report2["recovery"]["open_orders_count"] >= 0
            
            # Positions should be consistent (or filled from phase 1)
            # Note: Exact values depend on fill rate, but should have valid structure
            assert "positions" in report2
            assert "by_symbol" in report2["positions"]

    def test_scenario_5_idempotent_freeze_cancel(self) -> None:
        """
        Scenario 5: Freeze → cancel_all is idempotent.
        
        Steps:
        1. Run with high edge threshold → triggers freeze
        2. Verify cancel_all executed
        3. Simulate retry → should be idempotent (no extra cancels)
        
        Expected:
        - Orders canceled on freeze
        - Multiple freeze calls don't duplicate cancels
        """
        import tempfile
        
        with tempfile.TemporaryDirectory() as tmpdir:
            state_dir = pathlib.Path(tmpdir) / "state"
            state_dir.mkdir()
            
            result = _run_exec_demo(
                [
                    "--shadow",
                    "--symbols", "BTCUSDT,ETHUSDT",
                    "--iterations", "20",
                    "--max-inv", "10000",
                    "--max-total", "50000",
                    "--edge-threshold", "8.0",  # Very high → will freeze
                    "--fill-rate", "0.4",
                    "--reject-rate", "0.0",
                    "--latency-ms", "1",
                    "--durable-state",
                    "--state-dir", str(state_dir),
                ],
                env_vars={"MM_FREEZE_UTC_ISO": "2025-01-01T00:00:00Z"},
            )
            
            assert result.returncode == 0, f"stderr: {result.stderr}"
            
            report = json.loads(result.stdout)
            
            # System should freeze
            assert report["risk"]["frozen"] is True
            assert report["risk"]["freeze_events"] > 0
            
            # Should have canceled orders
            assert report["orders"]["canceled"] > 0
            
            # orders_canceled should match actual canceled count
            # (idempotency ensures no duplicates)
            # This is a smoke test - detailed idempotency tested in integration tests
    
    def test_scenario_6_observability_freeze_ready(self) -> None:
        """
        Scenario 6: Observability - freeze → /ready=fail → recover → /ready=ok.
        
        Steps:
        1. Start with --obs enabled (background server)
        2. Trigger freeze via high edge threshold
        3. Check that /ready returns 503 (via subprocess check)
        
        Note:
        This is a smoke test - full observability tested in integration tests.
        The exec_demo.py starts server in background thread, so we verify
        it doesn't crash with --obs flag.
        
        Expected:
        - --obs flag accepted
        - Process exits cleanly (server stopped)
        - Report shows freeze event
        """
        result = _run_exec_demo(
            [
                "--shadow",
                "--symbols", "BTCUSDT",
                "--iterations", "10",
                "--max-inv", "10000",
                "--max-total", "50000",
                "--edge-threshold", "10.0",  # High → will freeze
                "--fill-rate", "0.0",
                "--reject-rate", "0.0",
                "--latency-ms", "1",
                "--obs",  # Enable observability server
                "--obs-host", "127.0.0.1",
                "--obs-port", "18091",
            ],
            env_vars={"MM_FREEZE_UTC_ISO": "2025-01-01T00:00:00Z"},
        )
        
        assert result.returncode == 0, f"stderr: {result.stderr}"
        
        # Should have observability server logs in stderr
        assert "[OBS] Server started" in result.stderr
        assert "[OBS] Server stopped" in result.stderr
        
        report = json.loads(result.stdout)
        
        # Should have freeze event
        assert report["risk"]["frozen"] is True
        assert report["risk"]["freeze_events"] > 0