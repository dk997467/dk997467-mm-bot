"""
Unit tests for robust_kpi_extract from audit_artifacts.

Tests field extraction fallbacks and edge cases.
"""

import pytest
from tools.soak.audit_artifacts import robust_kpi_extract


def test_basic_paths():
    """Test extraction with all standard field names."""
    data = {
        "summary": {
            "net_bps": 3.1,
            "risk_ratio": 0.33,
            "slippage_bps_p95": 1.1,
            "adverse_bps_p95": 2.2,
            "p95_latency_ms": 310,
            "maker_taker_ratio": 0.86,
        }
    }
    k = robust_kpi_extract(data, 10)
    
    assert k["iter"] == 10
    assert k["net_bps"] == 3.1
    assert k["risk_ratio"] == 0.33
    assert k["slippage_p95"] == 1.1
    assert k["adverse_p95"] == 2.2
    assert k["latency_p95_ms"] == 310
    assert k["maker_taker_ratio"] == 0.86


def test_fallback_percent():
    """Test risk_percent -> risk_ratio conversion."""
    data = {"summary": {"net": 3.0, "risk_percent": 40}}
    k = robust_kpi_extract(data, 1)
    
    assert k["net_bps"] == 3.0
    assert abs(k["risk_ratio"] - 0.40) < 1e-6


def test_fallback_field_names():
    """Test alternative field names."""
    data = {
        "summary": {
            "net": 2.5,  # Instead of net_bps
            "risk": 0.25,  # Instead of risk_ratio
            "sl_p95": 0.9,  # Instead of slippage_bps_p95
            "adv_p95": 1.8,  # Instead of adverse_bps_p95
            "p95": 290,  # Instead of p95_latency_ms
            "maker_ratio": 0.80,  # Instead of maker_taker_ratio
        }
    }
    k = robust_kpi_extract(data, 5)
    
    assert k["net_bps"] == 2.5
    assert k["risk_ratio"] == 0.25
    assert k["slippage_p95"] == 0.9
    assert k["adverse_p95"] == 1.8
    assert k["latency_p95_ms"] == 290
    assert k["maker_taker_ratio"] == 0.80


def test_compute_maker_taker_from_counts():
    """Test maker_taker_ratio computation from counts."""
    data = {"summary": {"maker_count": 85, "taker_count": 15}}
    k = robust_kpi_extract(data, 2)
    
    # 85 / (85 + 15) = 0.85
    assert abs(k["maker_taker_ratio"] - 0.85) < 1e-6


def test_missing_fields():
    """Test handling of missing fields (should return NaN)."""
    data = {"summary": {}}
    k = robust_kpi_extract(data, 3)
    
    # All fields except iter should be NaN
    assert k["iter"] == 3
    # NaN check: x != x is True for NaN
    assert k["net_bps"] != k["net_bps"]
    assert k["risk_ratio"] != k["risk_ratio"]
    assert k["maker_taker_ratio"] != k["maker_taker_ratio"]


def test_partial_data():
    """Test with some fields present, some missing."""
    data = {"summary": {"net_bps": 2.9, "p95_latency_ms": 320}}
    k = robust_kpi_extract(data, 7)
    
    assert k["net_bps"] == 2.9
    assert k["latency_p95_ms"] == 320
    # Others should be NaN
    assert k["risk_ratio"] != k["risk_ratio"]
    assert k["maker_taker_ratio"] != k["maker_taker_ratio"]

