#!/usr/bin/env python3
"""
Unit tests for KPI Gate thresholds.

Tests WARN/FAIL thresholds and reason generation.
"""

import pytest
from pathlib import Path

# Import module under test
import sys
sys.path.insert(0, str(Path(__file__).parents[2]))

from tools.ci.validate_readiness import KPIThresholds, check_kpi_thresholds


def test_kpi_thresholds_defaults():
    """Test that default thresholds are loaded correctly."""
    thresholds = KPIThresholds()
    
    assert thresholds.adverse_bps_p95_warn == 4.0
    assert thresholds.adverse_bps_p95_fail == 6.0
    assert thresholds.slippage_bps_p95_warn == 3.0
    assert thresholds.slippage_bps_p95_fail == 5.0
    assert thresholds.cancel_ratio_warn == 0.55
    assert thresholds.cancel_ratio_fail == 0.70
    assert thresholds.order_age_p95_ms_warn == 330.0
    assert thresholds.order_age_p95_ms_fail == 360.0
    assert thresholds.ws_lag_p95_ms_warn == 120.0
    assert thresholds.ws_lag_p95_ms_fail == 180.0
    assert thresholds.net_bps_fail == 2.5
    assert thresholds.maker_share_pct_fail == 85.0


def test_kpi_gate_all_ok():
    """Test KPI Gate with all metrics OK."""
    metrics = {
        "totals": {
            "net_bps": 3.5,  # > 2.5
            "adverse_bps_p95": 2.0,  # < 4.0 (WARN)
            "slippage_bps_p95": 1.0,  # < 3.0 (WARN)
            "cancel_ratio": 0.30,  # < 0.55 (WARN)
            "order_age_p95_ms": 250.0,  # < 330 (WARN)
            "ws_lag_p95_ms": 80.0,  # < 120 (WARN)
            "maker_share_pct": 90.0,  # > 85
        }
    }
    
    thresholds = KPIThresholds()
    verdict, reasons = check_kpi_thresholds(metrics, thresholds)
    
    assert verdict == "OK"
    assert len(reasons) == 0


def test_kpi_gate_warn_adverse():
    """Test KPI Gate with adverse_bps in WARN range."""
    metrics = {
        "totals": {
            "net_bps": 3.5,
            "adverse_bps_p95": 5.0,  # > 4.0 (WARN), < 6.0 (FAIL)
            "slippage_bps_p95": 1.0,
            "cancel_ratio": 0.30,
            "order_age_p95_ms": 250.0,
            "ws_lag_p95_ms": 80.0,
            "maker_share_pct": 90.0,
        }
    }
    
    thresholds = KPIThresholds()
    verdict, reasons = check_kpi_thresholds(metrics, thresholds)
    
    assert verdict == "WARN"
    assert "EDGE:adverse" in reasons
    assert len(reasons) == 1


def test_kpi_gate_fail_adverse():
    """Test KPI Gate with adverse_bps in FAIL range."""
    metrics = {
        "totals": {
            "net_bps": 3.5,
            "adverse_bps_p95": 7.0,  # > 6.0 (FAIL)
            "slippage_bps_p95": 1.0,
            "cancel_ratio": 0.30,
            "order_age_p95_ms": 250.0,
            "ws_lag_p95_ms": 80.0,
            "maker_share_pct": 90.0,
        }
    }
    
    thresholds = KPIThresholds()
    verdict, reasons = check_kpi_thresholds(metrics, thresholds)
    
    assert verdict == "FAIL"
    assert "EDGE:adverse" in reasons


def test_kpi_gate_fail_net_bps():
    """Test KPI Gate with net_bps too low (FAIL only)."""
    metrics = {
        "totals": {
            "net_bps": 2.0,  # < 2.5 (FAIL)
            "adverse_bps_p95": 2.0,
            "slippage_bps_p95": 1.0,
            "cancel_ratio": 0.30,
            "order_age_p95_ms": 250.0,
            "ws_lag_p95_ms": 80.0,
            "maker_share_pct": 90.0,
        }
    }
    
    thresholds = KPIThresholds()
    verdict, reasons = check_kpi_thresholds(metrics, thresholds)
    
    assert verdict == "FAIL"
    assert "EDGE:net_bps" in reasons


def test_kpi_gate_fail_maker_share():
    """Test KPI Gate with maker_share too low (FAIL only)."""
    metrics = {
        "totals": {
            "net_bps": 3.5,
            "adverse_bps_p95": 2.0,
            "slippage_bps_p95": 1.0,
            "cancel_ratio": 0.30,
            "order_age_p95_ms": 250.0,
            "ws_lag_p95_ms": 80.0,
            "maker_share_pct": 80.0,  # < 85 (FAIL)
        }
    }
    
    thresholds = KPIThresholds()
    verdict, reasons = check_kpi_thresholds(metrics, thresholds)
    
    assert verdict == "FAIL"
    assert "EDGE:maker_share" in reasons


def test_kpi_gate_multiple_warnings():
    """Test KPI Gate with multiple WARN triggers."""
    metrics = {
        "totals": {
            "net_bps": 3.5,
            "adverse_bps_p95": 5.0,  # WARN
            "slippage_bps_p95": 4.0,  # WARN (> 3.0)
            "cancel_ratio": 0.60,  # WARN (> 0.55)
            "order_age_p95_ms": 250.0,
            "ws_lag_p95_ms": 80.0,
            "maker_share_pct": 90.0,
        }
    }
    
    thresholds = KPIThresholds()
    verdict, reasons = check_kpi_thresholds(metrics, thresholds)
    
    assert verdict == "WARN"
    assert "EDGE:adverse" in reasons
    assert "EDGE:slippage" in reasons
    assert "EDGE:cancel_ratio" in reasons
    assert len(reasons) == 3


def test_kpi_gate_multiple_failures():
    """Test KPI Gate with multiple FAIL triggers."""
    metrics = {
        "totals": {
            "net_bps": 1.5,  # FAIL
            "adverse_bps_p95": 7.0,  # FAIL
            "slippage_bps_p95": 6.0,  # FAIL (> 5.0)
            "cancel_ratio": 0.75,  # FAIL (> 0.70)
            "order_age_p95_ms": 250.0,
            "ws_lag_p95_ms": 80.0,
            "maker_share_pct": 80.0,  # FAIL
        }
    }
    
    thresholds = KPIThresholds()
    verdict, reasons = check_kpi_thresholds(metrics, thresholds)
    
    assert verdict == "FAIL"
    assert "EDGE:net_bps" in reasons
    assert "EDGE:adverse" in reasons
    assert "EDGE:slippage" in reasons
    assert "EDGE:cancel_ratio" in reasons
    assert "EDGE:maker_share" in reasons
    assert len(reasons) == 5


def test_kpi_gate_warn_and_fail_mixed():
    """Test KPI Gate with mixed WARN and FAIL (FAIL takes precedence)."""
    metrics = {
        "totals": {
            "net_bps": 1.5,  # FAIL
            "adverse_bps_p95": 5.0,  # WARN (but overall verdict is FAIL)
            "slippage_bps_p95": 1.0,
            "cancel_ratio": 0.30,
            "order_age_p95_ms": 250.0,
            "ws_lag_p95_ms": 80.0,
            "maker_share_pct": 90.0,
        }
    }
    
    thresholds = KPIThresholds()
    verdict, reasons = check_kpi_thresholds(metrics, thresholds)
    
    assert verdict == "FAIL"  # FAIL takes precedence
    assert "EDGE:net_bps" in reasons
    assert "EDGE:adverse" in reasons  # WARN trigger also added
    assert len(reasons) == 2


def test_kpi_gate_cancel_ratio_warn():
    """Test KPI Gate with cancel_ratio in WARN range."""
    metrics = {
        "totals": {
            "net_bps": 3.5,
            "adverse_bps_p95": 2.0,
            "slippage_bps_p95": 1.0,
            "cancel_ratio": 0.60,  # > 0.55 (WARN), < 0.70 (FAIL)
            "order_age_p95_ms": 250.0,
            "ws_lag_p95_ms": 80.0,
            "maker_share_pct": 90.0,
        }
    }
    
    thresholds = KPIThresholds()
    verdict, reasons = check_kpi_thresholds(metrics, thresholds)
    
    assert verdict == "WARN"
    assert "EDGE:cancel_ratio" in reasons


def test_kpi_gate_order_age_warn():
    """Test KPI Gate with order_age_p95_ms in WARN range."""
    metrics = {
        "totals": {
            "net_bps": 3.5,
            "adverse_bps_p95": 2.0,
            "slippage_bps_p95": 1.0,
            "cancel_ratio": 0.30,
            "order_age_p95_ms": 340.0,  # > 330 (WARN), < 360 (FAIL)
            "ws_lag_p95_ms": 80.0,
            "maker_share_pct": 90.0,
        }
    }
    
    thresholds = KPIThresholds()
    verdict, reasons = check_kpi_thresholds(metrics, thresholds)
    
    assert verdict == "WARN"
    assert "EDGE:order_age" in reasons


def test_kpi_gate_ws_lag_fail():
    """Test KPI Gate with ws_lag_p95_ms in FAIL range."""
    metrics = {
        "totals": {
            "net_bps": 3.5,
            "adverse_bps_p95": 2.0,
            "slippage_bps_p95": 1.0,
            "cancel_ratio": 0.30,
            "order_age_p95_ms": 250.0,
            "ws_lag_p95_ms": 200.0,  # > 180 (FAIL)
            "maker_share_pct": 90.0,
        }
    }
    
    thresholds = KPIThresholds()
    verdict, reasons = check_kpi_thresholds(metrics, thresholds)
    
    assert verdict == "FAIL"
    assert "EDGE:ws_lag" in reasons


def test_kpi_gate_missing_fields():
    """Test KPI Gate with missing fields (defaults to 0.0)."""
    metrics = {
        "totals": {
            # Missing most fields - should default to 0.0
            "net_bps": 3.5,  # Only this field present
            "maker_share_pct": 90.0,
        }
    }
    
    thresholds = KPIThresholds()
    verdict, reasons = check_kpi_thresholds(metrics, thresholds)
    
    # Should be OK since missing fields default to 0.0 (below WARN thresholds)
    assert verdict == "OK"
    assert len(reasons) == 0


if __name__ == "__main__":
    pytest.main([__file__, "-v"])

