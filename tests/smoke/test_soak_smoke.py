"""
Soak Test Smoke Suite (<2 minutes).

Fast validation of soak test infrastructure:
- 3 iterations with mock data
- SOAK_SLEEP_SECONDS=5 (vs 300 in production)
- Sanity KPI checks (risk <= 0.8, net > -10)

Purpose: Quick feedback loop for soak test changes.
"""
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest


# Add project root to path
PROJECT_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))


class TestSoakSmoke:
    """Smoke tests for soak test infrastructure."""
    
    @pytest.fixture(autouse=True)
    def setup_env(self, tmp_path, monkeypatch):
        """Setup test environment with fast sleep."""
        # Fast iteration sleep for smoke testing
        monkeypatch.setenv("SOAK_SLEEP_SECONDS", "5")
        
        # Use temp artifacts directory
        artifacts_dir = tmp_path / "artifacts" / "soak"
        artifacts_dir.mkdir(parents=True)
        monkeypatch.setenv("ARTIFACTS_ROOT", str(tmp_path / "artifacts"))
        
        # Store for test access
        self.artifacts_dir = artifacts_dir
        self.tmp_path = tmp_path
    
    def test_smoke_3_iterations_with_mock(self):
        """
        Run 3-iteration mini-soak with mock data.
        
        Validates:
        - ITER_SUMMARY files created
        - Live-apply executed
        - EDGE_REPORT parseable
        - Basic KPI sanity (not production thresholds)
        """
        # Run soak test with 3 iterations
        cmd = [
            sys.executable,
            "-m", "tools.soak.run",
            "--iterations", "3",
            "--auto-tune",
            "--mock"
        ]
        
        # Execute with timeout
        result = subprocess.run(
            cmd,
            cwd=PROJECT_ROOT,
            capture_output=True,
            text=True,
            timeout=120,  # 2-minute timeout
            env={**os.environ, "SOAK_SLEEP_SECONDS": "5"}
        )
        
        # Print output for debugging
        print("\n=== STDOUT ===")
        print(result.stdout)
        print("\n=== STDERR ===")
        print(result.stderr)
        
        # Should complete successfully
        assert result.returncode == 0, f"Soak run failed: {result.stderr}"
        
        # Verify artifacts created
        latest_dir = Path("artifacts/soak/latest")
        assert latest_dir.exists(), "Latest artifacts directory not found"
        
        # Verify ITER_SUMMARY files for all 3 iterations
        for i in range(1, 4):
            iter_summary = latest_dir / f"ITER_SUMMARY_{i}.json"
            assert iter_summary.exists(), f"ITER_SUMMARY_{i}.json not found"
            
            # Validate structure
            with open(iter_summary, 'r') as f:
                data = json.load(f)
            
            assert "summary" in data, f"ITER_SUMMARY_{i} missing 'summary' key"
            assert "iteration" in data, f"ITER_SUMMARY_{i} missing 'iteration' key"
            assert data["iteration"] == i, f"ITER_SUMMARY_{i} has wrong iteration number"
        
        # Verify TUNING_REPORT exists
        tuning_report = latest_dir / "TUNING_REPORT.json"
        assert tuning_report.exists(), "TUNING_REPORT.json not found"
        
        with open(tuning_report, 'r') as f:
            tuning_data = json.load(f)
        
        assert "iterations" in tuning_data, "TUNING_REPORT missing 'iterations' key"
        assert len(tuning_data["iterations"]) == 3, "TUNING_REPORT should have 3 iterations"
    
    def test_smoke_sanity_kpi_checks(self):
        """
        Validate sanity KPI thresholds (relaxed for smoke test).
        
        Thresholds (vs production):
        - risk_ratio <= 0.8 (vs 0.5 production hard limit)
        - net_bps > -10 (vs 2.0 production)
        - maker_taker >= 0.5 (vs 0.9 production)
        """
        # Run soak test
        cmd = [
            sys.executable,
            "-m", "tools.soak.run",
            "--iterations", "3",
            "--auto-tune",
            "--mock"
        ]
        
        result = subprocess.run(
            cmd,
            cwd=PROJECT_ROOT,
            capture_output=True,
            text=True,
            timeout=120,
            env={**os.environ, "SOAK_SLEEP_SECONDS": "5"}
        )
        
        assert result.returncode == 0, f"Soak run failed: {result.stderr}"
        
        # Load final iteration summary
        latest_dir = Path("artifacts/soak/latest")
        iter_summary_3 = latest_dir / "ITER_SUMMARY_3.json"
        
        with open(iter_summary_3, 'r') as f:
            data = json.load(f)
        
        summary = data["summary"]
        
        # Sanity checks (relaxed thresholds)
        risk_ratio = summary.get("risk_ratio", 1.0)
        net_bps = summary.get("net_bps", 0.0)
        maker_taker = summary.get("maker_taker_ratio", 0.0)
        
        print(f"\n=== Final Metrics ===")
        print(f"risk_ratio: {risk_ratio:.2%}")
        print(f"net_bps: {net_bps:.2f}")
        print(f"maker_taker: {maker_taker:.2%}")
        
        # SANITY (not production) thresholds
        assert risk_ratio <= 0.8, f"Risk too high: {risk_ratio:.2%} > 80%"
        assert net_bps > -10, f"Net BPS too negative: {net_bps:.2f} < -10"
        assert maker_taker >= 0.5, f"Maker/Taker ratio too low: {maker_taker:.2%} < 50%"
        
        print("\n✅ All sanity KPI checks passed")
    
    def test_smoke_config_manager_integration(self):
        """
        Validate ConfigManager integration in soak test.
        
        Verifies:
        - Profile loaded correctly
        - runtime_overrides.json created
        - Precedence working
        """
        # Import ConfigManager
        from tools.soak.config_manager import ConfigManager
        
        # Initialize
        config_mgr = ConfigManager()
        
        # Load steady_safe profile
        overrides = config_mgr.load(profile="steady_safe", verbose=True)
        
        # Verify profile values
        assert overrides["min_interval_ms"] == 75, "Profile not loaded correctly"
        assert overrides["tail_age_ms"] == 740, "Profile not loaded correctly"
        
        # Verify sources tracked
        sources = overrides.get("_sources", {})
        assert sources["min_interval_ms"] == "profile:steady_safe"
        
        # Test CLI override precedence
        cli_overrides = {"min_interval_ms": 999}
        overrides_with_cli = config_mgr.load(
            profile="steady_safe",
            cli_overrides=cli_overrides,
            verbose=False
        )
        
        # CLI should win
        assert overrides_with_cli["min_interval_ms"] == 999
        sources_cli = overrides_with_cli.get("_sources", {})
        assert sources_cli["min_interval_ms"] == "cli"
        
        print("\n✅ ConfigManager integration validated")
    
    def test_smoke_live_apply_executed(self):
        """
        Verify live-apply mechanism executed with full tracking.
        
        Checks (ITER_SUMMARY + TUNING_REPORT parity):
        - proposed_deltas (always present, even if {})
        - applied (bool)
        - skip_reason (string, empty if applied)
        - changed_keys (list)
        - state_hash (hex string)
        - signature (backwards compat)
        """
        # Run soak test
        cmd = [
            sys.executable,
            "-m", "tools.soak.run",
            "--iterations", "3",
            "--auto-tune",
            "--mock"
        ]
        
        result = subprocess.run(
            cmd,
            cwd=PROJECT_ROOT,
            capture_output=True,
            text=True,
            timeout=120,
            env={**os.environ, "SOAK_SLEEP_SECONDS": "5"}
        )
        
        assert result.returncode == 0
        
        latest_dir = Path("artifacts/soak/latest")
        
        # Check ITER_SUMMARY files for tracking fields
        for i in range(1, 4):
            iter_summary = latest_dir / f"ITER_SUMMARY_{i}.json"
            with open(iter_summary, 'r') as f:
                data = json.load(f)
            
            tuning = data["tuning"]
            
            # Required tracking fields
            assert "proposed_deltas" in tuning, f"ITER_SUMMARY_{i}: Missing proposed_deltas"
            assert "applied" in tuning, f"ITER_SUMMARY_{i}: Missing applied"
            assert "skip_reason" in tuning, f"ITER_SUMMARY_{i}: Missing skip_reason"
            assert "changed_keys" in tuning, f"ITER_SUMMARY_{i}: Missing changed_keys"
            assert "state_hash" in tuning, f"ITER_SUMMARY_{i}: Missing state_hash"
            
            # Type validation
            assert isinstance(tuning["proposed_deltas"], dict), f"ITER_SUMMARY_{i}: proposed_deltas not dict"
            assert isinstance(tuning["applied"], bool), f"ITER_SUMMARY_{i}: applied not bool"
            assert isinstance(tuning["skip_reason"], (str, dict)), f"ITER_SUMMARY_{i}: skip_reason not str/dict"
            assert isinstance(tuning["changed_keys"], list), f"ITER_SUMMARY_{i}: changed_keys not list"
            
            # If applied, state_hash must be present
            if tuning["applied"]:
                assert tuning["state_hash"] is not None, f"ITER_SUMMARY_{i}: state_hash missing when applied=true"
            
            print(f"✓ ITER_SUMMARY_{i}: applied={tuning['applied']}, changed_keys={tuning['changed_keys']}")
        
        # Check TUNING_REPORT for parity
        tuning_report = latest_dir / "TUNING_REPORT.json"
        with open(tuning_report, 'r') as f:
            tuning_data = json.load(f)
        
        assert len(tuning_data["iterations"]) == 3, "TUNING_REPORT should have 3 iterations"
        
        # Verify TUNING_REPORT has same tracking fields
        for iteration in tuning_data["iterations"]:
            iter_idx = iteration["iteration"]
            
            # Required tracking fields (same as ITER_SUMMARY)
            assert "proposed_deltas" in iteration, f"TUNING_REPORT[{iter_idx}]: Missing proposed_deltas"
            assert "applied" in iteration, f"TUNING_REPORT[{iter_idx}]: Missing applied"
            assert "skip_reason" in iteration, f"TUNING_REPORT[{iter_idx}]: Missing skip_reason"
            assert "changed_keys" in iteration, f"TUNING_REPORT[{iter_idx}]: Missing changed_keys"
            assert "state_hash" in iteration, f"TUNING_REPORT[{iter_idx}]: Missing state_hash"
            assert "signature" in iteration, f"TUNING_REPORT[{iter_idx}]: Missing signature"
            
            # Signature should always be present (even if "na")
            assert iteration["signature"] is not None, f"TUNING_REPORT[{iter_idx}]: signature is None"
            
            print(f"✓ TUNING_REPORT[{iter_idx}]: applied={iteration['applied']}, changed_keys={iteration['changed_keys']}")
        
        print(f"\n✅ Live-apply executed with full tracking for {len(tuning_data['iterations'])} iterations")
    
    def test_smoke_new_fields_present(self):
        """
        Verify new fields are present and populated correctly.
        
        Checks:
        - p95_latency_ms > 0 (in mock runs)
        - maker_taker_ratio present
        - maker_taker_source in {fills_volume, fills_count, weekly_rollup, mock_default}
        """
        # Run soak test
        cmd = [
            sys.executable,
            "-m", "tools.soak.run",
            "--iterations", "3",
            "--auto-tune",
            "--mock"
        ]
        
        result = subprocess.run(
            cmd,
            cwd=PROJECT_ROOT,
            capture_output=True,
            text=True,
            timeout=120,
            env={**os.environ, "SOAK_SLEEP_SECONDS": "5"}
        )
        
        assert result.returncode == 0
        
        latest_dir = Path("artifacts/soak/latest")
        
        # Check all iterations for new fields
        for i in range(1, 4):
            iter_summary = latest_dir / f"ITER_SUMMARY_{i}.json"
            with open(iter_summary, 'r') as f:
                data = json.load(f)
            
            summary = data["summary"]
            
            # p95_latency_ms must be present and > 0 in mock mode
            assert "p95_latency_ms" in summary, f"ITER_SUMMARY_{i}: Missing p95_latency_ms"
            p95_latency = summary["p95_latency_ms"]
            assert p95_latency > 0, f"ITER_SUMMARY_{i}: p95_latency_ms={p95_latency} should be > 0 in mock mode"
            
            # maker_taker_ratio must be present
            assert "maker_taker_ratio" in summary, f"ITER_SUMMARY_{i}: Missing maker_taker_ratio"
            maker_taker_ratio = summary["maker_taker_ratio"]
            assert 0.0 <= maker_taker_ratio <= 1.0, f"ITER_SUMMARY_{i}: maker_taker_ratio={maker_taker_ratio} out of range [0, 1]"
            
            # maker_taker_source must be present and valid
            assert "maker_taker_source" in summary, f"ITER_SUMMARY_{i}: Missing maker_taker_source"
            maker_taker_source = summary["maker_taker_source"]
            valid_sources = {"fills_volume", "fills_count", "weekly_rollup", "mock_default", "internal_fills", "existing", "fallback"}
            assert maker_taker_source in valid_sources, f"ITER_SUMMARY_{i}: maker_taker_source={maker_taker_source} not in {valid_sources}"
            
            print(f"✓ ITER_SUMMARY_{i}: p95_latency={p95_latency:.1f}ms, maker_taker={maker_taker_ratio:.2%} (source={maker_taker_source})")
        
        print(f"\n✅ All new fields present and valid for 3 iterations")
    
    def test_smoke_runtime_lt_2_minutes(self, benchmark=None):
        """
        Verify test completes in <2 minutes.
        
        This is critical for fast CI feedback.
        """
        import time
        
        start = time.time()
        
        # Run soak test
        cmd = [
            sys.executable,
            "-m", "tools.soak.run",
            "--iterations", "3",
            "--auto-tune",
            "--mock"
        ]
        
        result = subprocess.run(
            cmd,
            cwd=PROJECT_ROOT,
            capture_output=True,
            text=True,
            timeout=120,
            env={**os.environ, "SOAK_SLEEP_SECONDS": "5"}
        )
        
        duration = time.time() - start
        
        print(f"\n⏱️ Test duration: {duration:.1f}s")
        
        assert result.returncode == 0
        assert duration < 120, f"Test too slow: {duration:.1f}s > 120s"
        
        print(f"✅ Completed in {duration:.1f}s (within 2-minute limit)")


@pytest.mark.smoke
class TestSoakSmokeMarked:
    """Marked smoke tests for selective running."""
    
    def test_quick_sanity(self):
        """Ultra-fast sanity check (can run pre-commit)."""
        from tools.soak.config_manager import ConfigManager
        
        # Just verify infrastructure loads
        config_mgr = ConfigManager()
        profiles = config_mgr.list_profiles()
        
        assert len(profiles) >= 3
        assert "steady_safe" in profiles
        
        print("\n✅ Quick sanity passed")


if __name__ == "__main__":
    # Run with verbose output
    pytest.main([__file__, "-v", "-s", "-k", "smoke"])

