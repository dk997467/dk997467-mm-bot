"""
Unit tests for golden file comparison.
"""

import sys
sys.path.insert(0, ".")

from tools.tests.golden_compare import compare_values


def test_compare_identical():
    """Test comparison of identical values."""
    baseline = {"a": 1, "b": 2.0, "c": "test"}
    actual = {"a": 1, "b": 2.0, "c": "test"}
    
    drifts = compare_values(baseline, actual, "root")
    assert len(drifts) == 0
    
    print("✓ Identical values test passed")


def test_compare_float_drift():
    """Test float comparison with drift."""
    baseline = {"value": 2.0}
    actual = {"value": 2.1}
    
    drifts = compare_values(baseline, actual, "root", tolerance=1e-9)
    assert len(drifts) == 1
    assert "root.value" in drifts[0]
    assert "float drift" in drifts[0]
    
    print("✓ Float drift test passed")


def test_compare_missing_keys():
    """Test comparison with missing keys."""
    baseline = {"a": 1, "b": 2, "c": 3}
    actual = {"a": 1, "b": 2}
    
    drifts = compare_values(baseline, actual, "root")
    assert len(drifts) == 1
    assert "missing keys" in drifts[0]
    assert "'c'" in drifts[0]
    
    print("✓ Missing keys test passed")


def test_compare_extra_keys():
    """Test comparison with extra keys."""
    baseline = {"a": 1}
    actual = {"a": 1, "b": 2}
    
    drifts = compare_values(baseline, actual, "root")
    assert len(drifts) == 1
    assert "extra keys" in drifts[0]
    assert "'b'" in drifts[0]
    
    print("✓ Extra keys test passed")


def test_compare_type_mismatch():
    """Test comparison with type mismatch."""
    baseline = {"value": 1}
    actual = {"value": "1"}
    
    drifts = compare_values(baseline, actual, "root")
    assert len(drifts) == 1
    assert "type mismatch" in drifts[0]
    
    print("✓ Type mismatch test passed")


if __name__ == "__main__":
    test_compare_identical()
    test_compare_float_drift()
    test_compare_missing_keys()
    test_compare_extra_keys()
    test_compare_type_mismatch()
    print("\n✓ All golden compare tests passed")

