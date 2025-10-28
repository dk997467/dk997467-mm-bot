"""Unit tests for Accuracy Gate polish features (reasons, overlap, filters)"""
import json
import tempfile
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Dict

import pytest


def create_iter_file(path: Path, symbol_data: Dict, age_min: int = 0):
    """Helper to create mock ITER_SUMMARY file."""
    ts = datetime.now(timezone.utc) - timedelta(minutes=age_min)
    data = {
        "meta": {"timestamp": ts.isoformat()},
        **symbol_data
    }
    path.write_text(json.dumps(data), encoding="utf-8")


class TestReasonsAndOverlap:
    """Test reasons and overlap_windows tracking."""
    
    def test_no_overlap_reason(self, tmp_path):
        """Should add 'no_overlap' reason when symbols don't overlap."""
        # Shadow: BTCUSDT only
        shadow_dir = tmp_path / "shadow"
        shadow_dir.mkdir()
        for i in range(24):
            create_iter_file(
                shadow_dir / f"ITER_{i:03d}.json",
                {"BTCUSDT": {"edge_bps": 3.5, "maker_taker_ratio": 0.85, 
                            "p95_latency_ms": 300, "risk_ratio": 0.35}}
            )
        
        # Dryrun: ETHUSDT only (no overlap!)
        dryrun_dir = tmp_path / "dryrun"
        dryrun_dir.mkdir()
        for i in range(24):
            create_iter_file(
                dryrun_dir / f"ITER_{i:03d}.json",
                {"ETHUSDT": {"edge_bps": 2.8, "maker_taker_ratio": 0.83,
                            "p95_latency_ms": 320, "risk_ratio": 0.37}}
            )
        
        out_dir = tmp_path / "reports"
        out_dir.mkdir()
        
        # Run comparison
        import subprocess
        import sys
        result = subprocess.run([
            sys.executable, "-m", "tools.accuracy.compare_shadow_dryrun",
            "--shadow", str(shadow_dir / "ITER_*.json"),
            "--dryrun", str(dryrun_dir / "ITER_*.json"),
            "--symbols", "BTCUSDT,ETHUSDT",
            "--min-windows", "24",
            "--out-dir", str(out_dir)
        ], capture_output=True, text=True)
        
        # Load summary
        summary_path = out_dir / "ACCURACY_SUMMARY.json"
        assert summary_path.exists()
        
        summary = json.loads(summary_path.read_text())
        
        # Check reasons
        assert "no_overlap" in summary["overall"]["reasons"]
        
        # Check per_symbol
        assert "per_symbol" in summary
        btc_stats = summary["per_symbol"]["BTCUSDT"]
        assert btc_stats["overlap_windows"] == 0
        assert "no_overlap" in btc_stats["reasons"]
    
    def test_filtered_by_max_age_reason(self, tmp_path):
        """Should add 'filtered_by_max_age' when old data is filtered."""
        # Shadow: recent data
        shadow_dir = tmp_path / "shadow"
        shadow_dir.mkdir()
        for i in range(24):
            create_iter_file(
                shadow_dir / f"ITER_{i:03d}.json",
                {"BTCUSDT": {"edge_bps": 3.5, "maker_taker_ratio": 0.85,
                            "p95_latency_ms": 300, "risk_ratio": 0.35}},
                age_min=10  # Recent (10 min old)
            )
        
        # Dryrun: OLD data (should be filtered)
        dryrun_dir = tmp_path / "dryrun"
        dryrun_dir.mkdir()
        for i in range(24):
            create_iter_file(
                dryrun_dir / f"ITER_{i:03d}.json",
                {"BTCUSDT": {"edge_bps": 3.5, "maker_taker_ratio": 0.85,
                            "p95_latency_ms": 300, "risk_ratio": 0.35}},
                age_min=120  # OLD (120 min old, will be filtered with max-age=90)
            )
        
        out_dir = tmp_path / "reports"
        out_dir.mkdir()
        
        # Run comparison with max-age=90
        import subprocess
        import sys
        result = subprocess.run([
            sys.executable, "-m", "tools.accuracy.compare_shadow_dryrun",
            "--shadow", str(shadow_dir / "ITER_*.json"),
            "--dryrun", str(dryrun_dir / "ITER_*.json"),
            "--symbols", "BTCUSDT",
            "--min-windows", "12",  # Lower threshold to avoid immediate fail
            "--max-age-min", "90",
            "--out-dir", str(out_dir)
        ], capture_output=True, text=True)
        
        # Should exit 1 (insufficient dryrun windows after filtering)
        assert result.returncode == 1
        
        # Check that summary was not created (insufficient windows)
        # But we can verify from stderr that filtering happened
        assert "filtered" in result.stderr.lower() or "Insufficient" in result.stderr
    
    def test_overlap_windows_tracking(self, tmp_path):
        """Should correctly track overlap_windows for matching data."""
        # Both have BTCUSDT
        shadow_dir = tmp_path / "shadow"
        shadow_dir.mkdir()
        for i in range(24):
            create_iter_file(
                shadow_dir / f"ITER_{i:03d}.json",
                {"BTCUSDT": {"edge_bps": 3.5, "maker_taker_ratio": 0.85,
                            "p95_latency_ms": 300, "risk_ratio": 0.35}}
            )
        
        dryrun_dir = tmp_path / "dryrun"
        dryrun_dir.mkdir()
        for i in range(24):
            create_iter_file(
                dryrun_dir / f"ITER_{i:03d}.json",
                {"BTCUSDT": {"edge_bps": 3.5, "maker_taker_ratio": 0.85,
                            "p95_latency_ms": 300, "risk_ratio": 0.35}}
            )
        
        out_dir = tmp_path / "reports"
        out_dir.mkdir()
        
        import subprocess
        import sys
        subprocess.run([
            sys.executable, "-m", "tools.accuracy.compare_shadow_dryrun",
            "--shadow", str(shadow_dir / "ITER_*.json"),
            "--dryrun", str(dryrun_dir / "ITER_*.json"),
            "--symbols", "BTCUSDT",
            "--min-windows", "24",
            "--out-dir", str(out_dir)
        ], check=True)
        
        summary = json.loads((out_dir / "ACCURACY_SUMMARY.json").read_text())
        
        # Check overlap
        btc_stats = summary["per_symbol"]["BTCUSDT"]
        assert btc_stats["overlap_windows"] == 24
        assert btc_stats["shadow_windows"] == 24
        assert btc_stats["dry_windows"] == 24
        assert len(btc_stats["reasons"]) == 0  # No issues


class TestFilters:
    """Test --only-symbols, --skip-symbols, --skip-kpi filters."""
    
    def test_only_symbols_filter(self, tmp_path):
        """Should only compare specified symbols with --only-symbols."""
        # Create data for 3 symbols
        shadow_dir = tmp_path / "shadow"
        shadow_dir.mkdir()
        for i in range(24):
            create_iter_file(
                shadow_dir / f"ITER_{i:03d}.json",
                {
                    "BTCUSDT": {"edge_bps": 3.5, "maker_taker_ratio": 0.85,
                               "p95_latency_ms": 300, "risk_ratio": 0.35},
                    "ETHUSDT": {"edge_bps": 2.8, "maker_taker_ratio": 0.83,
                               "p95_latency_ms": 320, "risk_ratio": 0.37},
                    "SOLUSDT": {"edge_bps": 2.5, "maker_taker_ratio": 0.80,
                               "p95_latency_ms": 340, "risk_ratio": 0.40}
                }
            )
        
        dryrun_dir = tmp_path / "dryrun"
        dryrun_dir.mkdir()
        for i in range(24):
            create_iter_file(
                dryrun_dir / f"ITER_{i:03d}.json",
                {
                    "BTCUSDT": {"edge_bps": 3.5, "maker_taker_ratio": 0.85,
                               "p95_latency_ms": 300, "risk_ratio": 0.35},
                    "ETHUSDT": {"edge_bps": 2.8, "maker_taker_ratio": 0.83,
                               "p95_latency_ms": 320, "risk_ratio": 0.37},
                    "SOLUSDT": {"edge_bps": 2.5, "maker_taker_ratio": 0.80,
                               "p95_latency_ms": 340, "risk_ratio": 0.40}
                }
            )
        
        out_dir = tmp_path / "reports"
        out_dir.mkdir()
        
        import subprocess
        import sys
        subprocess.run([
            sys.executable, "-m", "tools.accuracy.compare_shadow_dryrun",
            "--shadow", str(shadow_dir / "ITER_*.json"),
            "--dryrun", str(dryrun_dir / "ITER_*.json"),
            "--only-symbols", "BTCUSDT,ETHUSDT",  # Only these 2
            "--min-windows", "24",
            "--out-dir", str(out_dir)
        ], check=True)
        
        summary = json.loads((out_dir / "ACCURACY_SUMMARY.json").read_text())
        
        # Check that only BTCUSDT and ETHUSDT are in results
        assert set(summary["symbols"].keys()) == {"BTCUSDT", "ETHUSDT"}
        assert "SOLUSDT" not in summary["symbols"]
        
        # Check filters in meta
        assert summary["meta"]["filters"]["only_symbols"] == ["BTCUSDT", "ETHUSDT"]


class TestSanitySummary:
    """Test ACCURACY_SANITY_SUMMARY.json generation."""
    
    def test_sanity_summary_created(self, tmp_path):
        """Should create ACCURACY_SANITY_SUMMARY.json with scenarios."""
        import subprocess
        import sys
        
        # Run sanity check
        result = subprocess.run([
            sys.executable, "-m", "tools.accuracy.sanity_check",
            "--min-windows", "12",
            "--max-age-min", "90",
            "--report-dir", str(tmp_path)
        ], capture_output=True, text=True)
        
        # Check that ACCURACY_SANITY_SUMMARY.json was created
        summary_path = tmp_path / "ACCURACY_SANITY_SUMMARY.json"
        assert summary_path.exists()
        
        summary = json.loads(summary_path.read_text())
        
        # Check structure
        assert "sanity_verdict" in summary
        assert summary["sanity_verdict"] in ["PASS", "ATTENTION"]
        
        assert "scenarios" in summary
        assert "empty_nonoverlap" in summary["scenarios"]
        assert "max_age" in summary["scenarios"]
        assert "formatting" in summary["scenarios"]
        
        # Check scenario structure
        s1 = summary["scenarios"]["empty_nonoverlap"]
        assert "expected" in s1
        assert "actual" in s1
        assert "reasons" in s1
        
        s3 = summary["scenarios"]["formatting"]
        assert "notes" in s3


if __name__ == "__main__":
    pytest.main([__file__, "-v"])

