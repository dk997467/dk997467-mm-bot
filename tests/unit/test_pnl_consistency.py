"""
Unit tests for P&L formula consistency with gross_bps and fees_bps.

Validates the formula: net_bps ≈ gross_bps - adverse_bps_p95 - slippage_bps_p95 - fees_bps
"""
import pytest


class TestPnLConsistency:
    """Test P&L formula consistency."""
    
    def test_formula_exact_match(self):
        """Test P&L formula with exact values."""
        # Given
        gross_bps = 10.0
        adverse_p95 = 2.0
        slippage_p95 = 1.5
        fees_bps = 0.5
        
        # Expected net
        expected_net = gross_bps - adverse_p95 - slippage_p95 - fees_bps
        assert expected_net == 6.0
        
        # Compute using formula
        computed_net = gross_bps - adverse_p95 - slippage_p95 - fees_bps
        
        # Should match within tolerance (0.05 bps)
        assert abs(computed_net - expected_net) <= 0.05
    
    def test_formula_with_tolerance(self):
        """Test P&L formula with floating point tolerance."""
        # Real-world example from soak test
        gross_bps = 7.25
        adverse_p95 = 1.5
        slippage_p95 = 1.0
        fees_bps = 0.0
        net_bps = 4.75
        
        # Compute from formula
        computed_net = gross_bps - adverse_p95 - slippage_p95 - fees_bps
        
        # Should match within 0.05 bps tolerance
        error = abs(computed_net - net_bps)
        assert error <= 0.05, f"Error {error:.4f} exceeds tolerance"
    
    def test_imputed_gross_calculation(self):
        """Test imputation of gross_bps from net + costs."""
        # Given only net and costs
        net_bps = 4.75
        adverse_p95 = 1.5
        slippage_p95 = 1.0
        fees_bps = 0.0
        
        # Impute gross
        gross_imputed = net_bps + adverse_p95 + slippage_p95 + fees_bps
        assert gross_imputed == 7.25
        
        # Verify reverse calculation
        net_verified = gross_imputed - adverse_p95 - slippage_p95 - fees_bps
        assert abs(net_verified - net_bps) <= 0.05
    
    def test_last8_consistency_synthetic_data(self):
        """Test consistency across last-8 iterations (synthetic data)."""
        # Synthetic data from soak test (iterations 17-24)
        last_8_data = [
            {"net": 4.4, "adverse": 1.5, "slippage": 1.0, "fees": 0.0},
            {"net": 4.5, "adverse": 1.5, "slippage": 1.0, "fees": 0.0},
            {"net": 4.6, "adverse": 1.5, "slippage": 1.0, "fees": 0.0},
            {"net": 4.7, "adverse": 1.5, "slippage": 1.0, "fees": 0.0},
            {"net": 4.8, "adverse": 1.5, "slippage": 1.0, "fees": 0.0},
            {"net": 4.9, "adverse": 1.5, "slippage": 1.0, "fees": 0.0},
            {"net": 5.0, "adverse": 1.5, "slippage": 1.0, "fees": 0.0},
            {"net": 5.1, "adverse": 1.5, "slippage": 1.0, "fees": 0.0},
        ]
        
        errors = []
        for i, row in enumerate(last_8_data, start=17):
            # Impute gross
            gross = row["net"] + row["adverse"] + row["slippage"] + row["fees"]
            
            # Verify
            net_computed = gross - row["adverse"] - row["slippage"] - row["fees"]
            error = abs(net_computed - row["net"])
            
            if error > 0.05:
                errors.append(f"Iter {i}: error={error:.4f} bps")
        
        assert len(errors) == 0, f"P&L inconsistencies: {errors}"
    
    def test_zero_fees_case(self):
        """Test formula when fees_bps is zero (common case)."""
        gross_bps = 8.0
        adverse_p95 = 2.0
        slippage_p95 = 1.5
        fees_bps = 0.0
        
        net_bps = gross_bps - adverse_p95 - slippage_p95 - fees_bps
        assert net_bps == 4.5
    
    def test_fees_present_case(self):
        """Test formula when fees_bps is non-zero."""
        gross_bps = 10.0
        adverse_p95 = 2.0
        slippage_p95 = 1.5
        fees_bps = 1.0  # 1 bps in fees
        
        net_bps = gross_bps - adverse_p95 - slippage_p95 - fees_bps
        assert net_bps == 5.5
    
    def test_negative_net_possible(self):
        """Test that negative net_bps is mathematically valid."""
        # Losing scenario: costs exceed gross
        gross_bps = 2.0
        adverse_p95 = 1.5
        slippage_p95 = 1.0
        fees_bps = 0.5
        
        net_bps = gross_bps - adverse_p95 - slippage_p95 - fees_bps
        assert net_bps == -1.0  # Loss
        
        # Consistency check still holds
        gross_verified = net_bps + adverse_p95 + slippage_p95 + fees_bps
        assert abs(gross_verified - gross_bps) <= 0.05


class TestRobustKPIExtractWithGross:
    """Test that robust_kpi_extract() handles gross_bps and fees_bps."""
    
    def test_extract_gross_bps_present(self):
        """Test extraction when gross_bps is in the data."""
        from tools.soak.audit_artifacts import robust_kpi_extract
        
        data = {
            "summary": {
                "net_bps": 4.75,
                "gross_bps": 7.25,
                "fees_bps": 0.0,
                "adverse_bps_p95": 1.5,
                "slippage_bps_p95": 1.0,
            }
        }
        
        result = robust_kpi_extract(data, iter_idx=1)
        
        assert result["gross_bps"] == 7.25
        assert result["fees_bps"] == 0.0
        assert result["gross_imputed"] == False  # Not imputed
    
    def test_extract_gross_bps_imputed(self):
        """Test imputation when gross_bps is missing."""
        from tools.soak.audit_artifacts import robust_kpi_extract
        
        data = {
            "summary": {
                "net_bps": 4.75,
                # gross_bps missing
                "fees_bps": 0.0,
                "adverse_bps_p95": 1.5,
                "slippage_bps_p95": 1.0,
            }
        }
        
        result = robust_kpi_extract(data, iter_idx=1)
        
        # Should be imputed as: 4.75 + 1.5 + 1.0 + 0.0 = 7.25
        assert result["gross_bps"] == 7.25
        assert result["fees_bps"] == 0.0
        assert result["gross_imputed"] == True  # Imputed
    
    def test_extract_fees_bps_defaults_to_zero(self):
        """Test that fees_bps defaults to 0.0 if missing."""
        from tools.soak.audit_artifacts import robust_kpi_extract
        
        data = {
            "summary": {
                "net_bps": 4.75,
                "gross_bps": 7.25,
                # fees_bps missing
            }
        }
        
        result = robust_kpi_extract(data, iter_idx=1)
        
        assert result["fees_bps"] == 0.0  # Default
    
    def test_extract_all_fields_present(self):
        """Test extraction when all P&L fields are present."""
        from tools.soak.audit_artifacts import robust_kpi_extract
        
        data = {
            "summary": {
                "net_bps": 5.5,
                "gross_bps": 10.0,
                "fees_bps": 1.0,
                "adverse_bps_p95": 2.0,
                "slippage_bps_p95": 1.5,
                "risk_ratio": 0.30,
                "p95_latency_ms": 222.5,
                "maker_taker_ratio": 0.85,
            }
        }
        
        result = robust_kpi_extract(data, iter_idx=1)
        
        # Check all fields
        assert result["net_bps"] == 5.5
        assert result["gross_bps"] == 10.0
        assert result["fees_bps"] == 1.0
        assert result["adverse_p95"] == 2.0
        assert result["slippage_p95"] == 1.5
        assert result["gross_imputed"] == False
        
        # Verify formula
        computed_net = result["gross_bps"] - result["adverse_p95"] - result["slippage_p95"] - result["fees_bps"]
        assert abs(computed_net - result["net_bps"]) <= 0.05


class TestCSVColumnsIncludeGross:
    """Test that CSV includes gross_bps, fees_bps, and gross_imputed columns."""
    
    def test_csv_columns_present(self):
        """Test that CSV includes new columns."""
        from tools.soak.audit_artifacts import robust_kpi_extract
        
        data = {
            "summary": {
                "net_bps": 4.75,
                "gross_bps": 7.25,
                "fees_bps": 0.0,
            }
        }
        
        result = robust_kpi_extract(data, iter_idx=1)
        
        # Check that new keys are present
        assert "gross_bps" in result
        assert "fees_bps" in result
        assert "gross_imputed" in result
    
    def test_csv_column_order_preserves_compatibility(self):
        """Test that new columns don't break existing code."""
        from tools.soak.audit_artifacts import robust_kpi_extract
        
        data = {
            "summary": {
                "net_bps": 4.75,
            }
        }
        
        result = robust_kpi_extract(data, iter_idx=1)
        
        # Old columns should still be present
        assert "iter" in result
        assert "net_bps" in result
        assert "risk_ratio" in result
        assert "latency_p95_ms" in result
        assert "maker_taker_ratio" in result
        
        # New columns added
        assert "gross_bps" in result
        assert "fees_bps" in result
        assert "gross_imputed" in result

