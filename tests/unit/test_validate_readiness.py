"""
Unit tests for readiness validator.
"""

import sys
sys.path.insert(0, ".")

from tools.ci.validate_readiness import validate_structure, validate_ranges, validate_verdict


def test_validate_structure_valid():
    """Test structure validation with valid data."""
    data = {
        "runtime": {"utc": "2025-01-01T00:00:00Z", "version": "0.1.0"},
        "score": 100.0,
        "sections": {
            "chaos": 10.0,
            "edge": 30.0,
            "guards": 10.0,
            "latency": 25.0,
            "taker": 15.0,
            "tests": 10.0
        },
        "verdict": "GO"
    }
    
    errors = validate_structure(data)
    assert len(errors) == 0
    
    print("✓ Valid structure test passed")


def test_validate_structure_missing_keys():
    """Test structure validation with missing keys."""
    data = {
        "score": 100.0,
        "verdict": "GO"
    }
    
    errors = validate_structure(data)
    assert len(errors) >= 2  # Missing 'runtime' and 'sections'
    
    print("✓ Missing keys test passed")


def test_validate_ranges_valid():
    """Test range validation with valid data."""
    data = {
        "score": 60.0,
        "sections": {
            "chaos": 10.0,
            "edge": 0.0,
            "guards": 0.0,
            "latency": 25.0,
            "taker": 15.0,
            "tests": 10.0
        }
    }
    
    errors = validate_ranges(data)
    assert len(errors) == 0
    
    print("✓ Valid ranges test passed")


def test_validate_ranges_invalid():
    """Test range validation with out-of-range values."""
    data = {
        "score": 150.0,  # Should be 0-100
        "sections": {
            "edge": 50.0  # Should be 0-30
        }
    }
    
    errors = validate_ranges(data)
    assert len(errors) >= 2
    
    print("✓ Invalid ranges test passed")


def test_validate_verdict_go():
    """Test verdict validation for GO."""
    data = {
        "score": 100.0,
        "verdict": "GO"
    }
    
    errors = validate_verdict(data)
    assert len(errors) == 0
    
    print("✓ GO verdict test passed")


def test_validate_verdict_hold():
    """Test verdict validation for HOLD."""
    data = {
        "score": 60.0,
        "verdict": "HOLD"
    }
    
    errors = validate_verdict(data)
    assert len(errors) == 0
    
    print("✓ HOLD verdict test passed")


def test_validate_verdict_mismatch():
    """Test verdict validation with score/verdict mismatch."""
    # GO with score < 100
    data1 = {
        "score": 90.0,
        "verdict": "GO"
    }
    errors1 = validate_verdict(data1)
    assert len(errors1) > 0
    
    # HOLD with score == 100
    data2 = {
        "score": 100.0,
        "verdict": "HOLD"
    }
    errors2 = validate_verdict(data2)
    assert len(errors2) > 0
    
    print("✓ Verdict mismatch test passed")


if __name__ == "__main__":
    test_validate_structure_valid()
    test_validate_structure_missing_keys()
    test_validate_ranges_valid()
    test_validate_ranges_invalid()
    test_validate_verdict_go()
    test_validate_verdict_hold()
    test_validate_verdict_mismatch()
    print("\n✓ All readiness validator tests passed")

