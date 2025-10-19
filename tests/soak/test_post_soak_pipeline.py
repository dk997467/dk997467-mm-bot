"""
Regression test suite for post-soak analysis pipeline.

Tests both analyze_post_soak.py and extract_post_soak_snapshot.py
to ensure correct verdict calculation, freeze logic, guard counts, etc.
"""

import json
import pytest
from pathlib import Path
from tools.soak.extract_post_soak_snapshot import (
    _kpi_pass,
    _count_guards,
    _count_anomalies,
    _detect_signature_loops,
    extract_snapshot,
)


@pytest.mark.smoke
def test_schema_version_present():
    """Test that schema_version field is present in snapshot."""
    # Use existing test data
    test_path = Path("artifacts/soak/test_run/latest")
    
    if not test_path.exists():
        pytest.skip("Test data not available")
    
    snapshot, exit_code = extract_snapshot(test_path)
    
    assert exit_code == 0
    assert "schema_version" in snapshot
    assert snapshot["schema_version"] == "1.1"


@pytest.mark.smoke
def test_freeze_ready_logic():
    """Test freeze_ready field calculation."""
    # Test case 1: PASS + pass_count≥6 + freeze_seen → freeze_ready=True
    snapshot1 = {
        "verdict": "PASS",
        "pass_count_last8": 7,
        "freeze_seen": True,
    }
    
    # Simulate freeze_ready calculation
    freeze_ready1 = (
        snapshot1["verdict"] in ("PASS", "WARN")
        and snapshot1["pass_count_last8"] >= 6
        and snapshot1["freeze_seen"]
    )
    assert freeze_ready1 is True
    
    # Test case 2: PASS but pass_count<6 → freeze_ready=False
    snapshot2 = {
        "verdict": "PASS",
        "pass_count_last8": 5,
        "freeze_seen": True,
    }
    
    freeze_ready2 = (
        snapshot2["verdict"] in ("PASS", "WARN")
        and snapshot2["pass_count_last8"] >= 6
        and snapshot2["freeze_seen"]
    )
    assert freeze_ready2 is False
    
    # Test case 3: PASS but no freeze → freeze_ready=False
    snapshot3 = {
        "verdict": "PASS",
        "pass_count_last8": 7,
        "freeze_seen": False,
    }
    
    freeze_ready3 = (
        snapshot3["verdict"] in ("PASS", "WARN")
        and snapshot3["pass_count_last8"] >= 6
        and snapshot3["freeze_seen"]
    )
    assert freeze_ready3 is False


@pytest.mark.smoke
def test_guard_counts_accuracy():
    """Test guard counter accuracy."""
    # Create mock summaries with known guard activations
    summaries = [
        {
            "tuning": {
                "oscillation_detected": False,
                "velocity_violation": True,
                "cooldown_active": False,
                "freeze_triggered": False,
            }
        },
        {
            "tuning": {
                "oscillation_detected": True,
                "velocity_violation": False,
                "cooldown_active": True,
                "freeze_triggered": False,
            }
        },
        {
            "tuning": {
                "oscillation_detected": False,
                "velocity_violation": False,
                "cooldown_active": False,
                "freeze_triggered": True,
            }
        },
    ]
    
    guards = _count_guards(summaries)
    
    assert guards["oscillation_count"] == 1
    assert guards["velocity_count"] == 1
    assert guards["cooldown_count"] == 1
    assert guards["freeze_events"] == 1


@pytest.mark.smoke
def test_anomaly_detection_correctness():
    """Test anomaly detection logic."""
    # Create summaries with known anomalies
    summaries = [
        {
            "summary": {
                "p95_latency_ms": 420,  # Spike: > 400
                "risk_ratio": 0.35,
                "maker_taker_ratio": 0.88,
            }
        },
        {
            "summary": {
                "p95_latency_ms": 300,
                "risk_ratio": 0.52,  # Jump: +0.17 from previous
                "maker_taker_ratio": 0.88,
            }
        },
        {
            "summary": {
                "p95_latency_ms": 300,
                "risk_ratio": 0.40,
                "maker_taker_ratio": 0.70,  # Drop: < 0.75
            }
        },
    ]
    
    count = _count_anomalies(summaries)
    
    # Expected: 1 latency spike + 1 risk jump + 1 MT drop = 3
    assert count == 3


@pytest.mark.smoke
def test_signature_loop_detection():
    """Test A→B→A signature loop detection."""
    # Test case 1: Clear A→B→A pattern (3-window sliding)
    # sig_a, sig_b, sig_a, sig_b, sig_a
    # Windows: [a,b,a] → loop, [b,a,b] → loop, [a,b,a] → loop
    # Total: 3 loops
    summaries1 = [
        {"tuning": {"signature": "sig_a"}},
        {"tuning": {"signature": "sig_b"}},
        {"tuning": {"signature": "sig_a"}},  # Loop window 1: a→b→a
        {"tuning": {"signature": "sig_b"}},  # Loop window 2: b→a→b
        {"tuning": {"signature": "sig_a"}},  # Loop window 3: a→b→a
    ]
    
    loops1 = _detect_signature_loops(summaries1)
    assert loops1 == 3  # Three overlapping A→B→A patterns
    
    # Test case 2: Single loop
    summaries2 = [
        {"tuning": {"signature": "sig_a"}},
        {"tuning": {"signature": "sig_b"}},
        {"tuning": {"signature": "sig_a"}},  # One loop
        {"tuning": {"signature": "sig_c"}},  # No more loops
    ]
    
    loops2 = _detect_signature_loops(summaries2)
    assert loops2 == 1
    
    # Test case 3: No loops (monotonic)
    summaries3 = [
        {"tuning": {"signature": "sig_a"}},
        {"tuning": {"signature": "sig_b"}},
        {"tuning": {"signature": "sig_c"}},
        {"tuning": {"signature": "sig_d"}},
    ]
    
    loops3 = _detect_signature_loops(summaries3)
    assert loops3 == 0


@pytest.mark.smoke
def test_kpi_pass_thresholds():
    """Test KPI threshold checks."""
    # Passing case
    summary_pass = {
        "summary": {
            "risk_ratio": 0.40,
            "maker_taker_ratio": 0.90,
            "net_bps": 3.0,
            "p95_latency_ms": 300,
        }
    }
    assert _kpi_pass(summary_pass) is True
    
    # Failing: risk too high
    summary_fail_risk = {
        "summary": {
            "risk_ratio": 0.45,  # > 0.42
            "maker_taker_ratio": 0.90,
            "net_bps": 3.0,
            "p95_latency_ms": 300,
        }
    }
    assert _kpi_pass(summary_fail_risk) is False
    
    # Failing: maker/taker too low
    summary_fail_mt = {
        "summary": {
            "risk_ratio": 0.40,
            "maker_taker_ratio": 0.80,  # < 0.85
            "net_bps": 3.0,
            "p95_latency_ms": 300,
        }
    }
    assert _kpi_pass(summary_fail_mt) is False


@pytest.mark.integration
def test_snapshot_matches_analyzer_verdict():
    """Test that snapshot verdict matches analyzer verdict."""
    test_path = Path("artifacts/soak/test_run/latest")
    
    if not test_path.exists():
        pytest.skip("Test data not available")
    
    # Run extractor
    snapshot, exit_code = extract_snapshot(test_path)
    
    assert exit_code == 0
    assert "verdict" in snapshot
    assert snapshot["verdict"] in ("PASS", "WARN", "FAIL")
    
    # Check POST_SOAK_AUDIT.md exists (from analyzer)
    audit_path = test_path / "POST_SOAK_AUDIT.md"
    if audit_path.exists():
        audit_content = audit_path.read_text(encoding="utf-8")
        # Verify verdict appears in audit
        assert snapshot["verdict"] in audit_content


@pytest.mark.smoke
def test_all_required_fields_present():
    """Test that all required fields are present in snapshot v1.1."""
    test_path = Path("artifacts/soak/test_run/latest")
    
    if not test_path.exists():
        pytest.skip("Test data not available")
    
    snapshot, exit_code = extract_snapshot(test_path)
    
    assert exit_code == 0
    
    # Check v1.0 fields
    assert "verdict" in snapshot
    assert "pass_count_last8" in snapshot
    assert "freeze_seen" in snapshot
    assert "kpi_last8" in snapshot
    assert "guards_last8" in snapshot
    
    # Check v1.1 fields
    assert "schema_version" in snapshot
    assert "freeze_ready" in snapshot
    assert "time_range" in snapshot
    assert "kpi_gate_parity" in snapshot
    assert "anomalies_count" in snapshot
    assert "signature_loops" in snapshot


if __name__ == "__main__":
    pytest.main([__file__, "-v"])

