"""
Tests for E1+ schema upgrades and migrations.
"""

import pytest
from datetime import datetime, timezone, timedelta

from src.storage.validators import upgrade_summary, validate_summary_payload


class TestSchemaUpgrade:
    """Test schema upgrade functionality."""

    def test_e1_0_to_e1_1_upgrade_with_missing_fields(self):
        """Test that e1.0 payload missing some fields gets upgraded to e1.1 with defaults."""
        # Minimal e1.0 payload missing some required fields
        e1_0_payload = {
            "schema_version": "e1.0",
            "symbol": "TESTUPG",
            "hour_utc": "2025-01-15T10:00:00Z",
            "counts": {"orders": 5, "quotes": 10, "fills": 3},
            "hit_rate_by_bin": {"5": {"count": 8, "fills": 2}},
            "queue_wait_cdf_ms": [{"p": 0.5, "v": 120.0}],
            "metadata": {"git_sha": "abc123", "cfg_hash": "def456"}
            # Missing: bins_max_bps, percentiles_used, window_utc, generated_at_utc
        }
        
        upgraded = upgrade_summary(e1_0_payload)
        
        # Should be upgraded to e1.1
        assert upgraded["schema_version"] == "e1.1"
        
        # Should have added missing fields with defaults
        assert "bins_max_bps" in upgraded
        assert upgraded["bins_max_bps"] == 50  # Default value
        
        assert "percentiles_used" in upgraded
        assert upgraded["percentiles_used"] == [0.1, 0.25, 0.5, 0.75, 0.9, 0.95, 0.99]
        
        assert "window_utc" in upgraded
        assert "hour_start" in upgraded["window_utc"]
        assert "hour_end" in upgraded["window_utc"]
        
        assert "generated_at_utc" in upgraded
        assert upgraded["generated_at_utc"].endswith("Z")
        
        # Original fields should be preserved
        assert upgraded["symbol"] == "TESTUPG"
        assert upgraded["counts"] == {"orders": 5, "quotes": 10, "fills": 3}
        assert upgraded["hit_rate_by_bin"] == {"5": {"count": 8, "fills": 2}}

    def test_upgrade_with_hour_utc_reconstruction(self):
        """Test window_utc reconstruction from hour_utc."""
        payload = {
            "schema_version": "e1.0",
            "symbol": "RECON",
            "hour_utc": "2025-01-15T14:00:00Z",  # 2 PM UTC
            "counts": {"orders": 1, "quotes": 2, "fills": 1},
            "hit_rate_by_bin": {},
            "queue_wait_cdf_ms": [],
            "metadata": {"git_sha": "test", "cfg_hash": "test"}
        }
        
        upgraded = upgrade_summary(payload)
        
        # window_utc should be reconstructed from hour_utc
        assert upgraded["window_utc"]["hour_start"] == "2025-01-15T14:00:00Z"
        assert upgraded["window_utc"]["hour_end"] == "2025-01-15T15:00:00Z"  # +1 hour

    def test_upgrade_with_hour_utc_midnight_edge_case(self):
        """Test window_utc reconstruction at midnight boundary."""
        payload = {
            "schema_version": "e1.0", 
            "symbol": "MIDNIGHT",
            "hour_utc": "2025-01-15T23:00:00Z",  # 11 PM UTC
            "counts": {"orders": 1, "quotes": 1, "fills": 0},
            "hit_rate_by_bin": {},
            "queue_wait_cdf_ms": [],
            "metadata": {"git_sha": "test", "cfg_hash": "test"}
        }
        
        upgraded = upgrade_summary(payload)
        
        # Should handle midnight rollover correctly
        assert upgraded["window_utc"]["hour_start"] == "2025-01-15T23:00:00Z"
        assert upgraded["window_utc"]["hour_end"] == "2025-01-16T00:00:00Z"  # Next day

    def test_upgrade_preserves_existing_fields(self):
        """Test that upgrade doesn't overwrite existing fields."""
        payload = {
            "schema_version": "e1.0",
            "symbol": "PRESERVE",
            "hour_utc": "2025-01-15T12:00:00Z",
            "bins_max_bps": 25,  # Custom value
            "percentiles_used": [0.5, 0.9],  # Custom percentiles
            "window_utc": {  # Existing window
                "hour_start": "2025-01-15T12:00:00Z",
                "hour_end": "2025-01-15T13:00:00Z"
            },
            "counts": {"orders": 2, "quotes": 4, "fills": 1},
            "hit_rate_by_bin": {},
            "queue_wait_cdf_ms": [],
            "metadata": {"git_sha": "test", "cfg_hash": "test"}
        }
        
        upgraded = upgrade_summary(payload)
        
        # Should preserve existing custom values
        assert upgraded["bins_max_bps"] == 25
        assert upgraded["percentiles_used"] == [0.5, 0.9]
        assert upgraded["window_utc"]["hour_start"] == "2025-01-15T12:00:00Z"
        assert upgraded["window_utc"]["hour_end"] == "2025-01-15T13:00:00Z"

    def test_upgrade_round_trip_stability(self):
        """Test that upgrading twice produces identical results."""
        payload = {
            "schema_version": "e1.0",
            "symbol": "STABLE",
            "hour_utc": "2025-01-15T16:00:00Z",
            "counts": {"orders": 3, "quotes": 6, "fills": 2},
            "hit_rate_by_bin": {"10": {"count": 4, "fills": 1}},
            "queue_wait_cdf_ms": [{"p": 0.5, "v": 150.0}, {"p": 0.9, "v": 300.0}],
            "metadata": {"git_sha": "stable", "cfg_hash": "test"}
        }
        
        first_upgrade = upgrade_summary(payload)
        second_upgrade = upgrade_summary(first_upgrade)
        
        # Remove timestamps for comparison (they will differ)
        first_copy = dict(first_upgrade)
        second_copy = dict(second_upgrade)
        del first_copy["generated_at_utc"]
        del second_copy["generated_at_utc"]
        
        # Should be identical
        assert first_copy == second_copy
        assert second_upgrade["schema_version"] == "e1.1"

    def test_upgrade_then_validate_success(self):
        """Test that upgraded payload passes validation."""
        payload = {
            "schema_version": "e1.0",
            "symbol": "VALID",
            "hour_utc": "2025-01-15T08:00:00Z",
            "counts": {"orders": 10, "quotes": 20, "fills": 5},
            "hit_rate_by_bin": {
                "0": {"count": 5, "fills": 2},
                "10": {"count": 8, "fills": 3},
                "25": {"count": 7, "fills": 0}
            },
            "queue_wait_cdf_ms": [
                {"p": 0.25, "v": 100.0},
                {"p": 0.5, "v": 150.0},
                {"p": 0.75, "v": 200.0},
                {"p": 0.9, "v": 250.0}
            ],
            "metadata": {"git_sha": "valid123", "cfg_hash": "valid456"}
        }
        
        upgraded = upgrade_summary(payload)
        is_valid, errors = validate_summary_payload(upgraded)
        
        assert is_valid, f"Upgraded payload should be valid, got errors: {errors}"
        assert len(errors) == 0

    def test_upgrade_handles_invalid_hour_utc_gracefully(self):
        """Test that upgrade handles invalid hour_utc gracefully."""
        payload = {
            "schema_version": "e1.0",
            "symbol": "INVALID_TIME",
            "hour_utc": "invalid-timestamp",  # Invalid format
            "counts": {"orders": 1, "quotes": 1, "fills": 0},
            "hit_rate_by_bin": {},
            "queue_wait_cdf_ms": [],
            "metadata": {"git_sha": "test", "cfg_hash": "test"}
        }
        
        # Should not raise exception, fallback to current time
        upgraded = upgrade_summary(payload)
        
        assert upgraded["schema_version"] == "e1.1"
        assert "window_utc" in upgraded
        assert "hour_start" in upgraded["window_utc"]
        assert upgraded["window_utc"]["hour_start"].endswith("Z")

    def test_upgrade_adds_generated_at_utc(self):
        """Test that upgrade always adds generated_at_utc."""
        payload = {
            "schema_version": "e1.0",
            "symbol": "TIMESTAMP",
            "hour_utc": "2025-01-15T20:00:00Z",
            "counts": {"orders": 1, "quotes": 1, "fills": 0},
            "hit_rate_by_bin": {},
            "queue_wait_cdf_ms": [],
            "metadata": {"git_sha": "test", "cfg_hash": "test"}
        }
        
        # Test multiple upgrades have different timestamps
        upgrade1 = upgrade_summary(payload)
        upgrade2 = upgrade_summary(payload)
        
        assert "generated_at_utc" in upgrade1
        assert "generated_at_utc" in upgrade2
        assert upgrade1["generated_at_utc"] != upgrade2["generated_at_utc"]  # Different timestamps
        
        # Both should be valid UTC timestamps
        for ts in [upgrade1["generated_at_utc"], upgrade2["generated_at_utc"]]:
            assert ts.endswith("Z")
            # Should be parseable
            datetime.fromisoformat(ts.replace('Z', '+00:00'))

    def test_upgrade_preserves_non_schema_fields(self):
        """Test that upgrade preserves unknown/custom fields."""
        payload = {
            "schema_version": "e1.0",
            "symbol": "CUSTOM",
            "hour_utc": "2025-01-15T11:00:00Z",
            "counts": {"orders": 1, "quotes": 1, "fills": 0},
            "hit_rate_by_bin": {},
            "queue_wait_cdf_ms": [],
            "metadata": {"git_sha": "test", "cfg_hash": "test"},
            "custom_field": "should_be_preserved",
            "custom_object": {"nested": "data"}
        }
        
        upgraded = upgrade_summary(payload)
        
        # Custom fields should be preserved
        assert upgraded["custom_field"] == "should_be_preserved"
        assert upgraded["custom_object"] == {"nested": "data"}
