"""
Tests for E1+ summary validation functionality.
"""

import pytest
from datetime import datetime, timezone

from src.storage.validators import validate_summary_payload, validate_hourly_summary_file


class TestSummaryValidation:
    """Test comprehensive summary validation."""

    def test_valid_summary_passes_validation(self):
        """Test that a well-formed summary passes validation."""
        valid_summary = {
            "schema_version": "e1.1",
            "symbol": "VALID",
            "hour_utc": "2025-01-15T10:00:00Z",
            "generated_at_utc": "2025-01-15T10:30:00Z",
            "window_utc": {
                "hour_start": "2025-01-15T10:00:00Z",
                "hour_end": "2025-01-15T11:00:00Z"
            },
            "bins_max_bps": 50,
            "percentiles_used": [0.25, 0.5, 0.75, 0.9, 0.95],
            "counts": {
                "orders": 10,
                "quotes": 25,
                "fills": 8
            },
            "hit_rate_by_bin": {
                "0": {"count": 10, "fills": 3},
                "5": {"count": 8, "fills": 2},
                "15": {"count": 7, "fills": 3}
            },
            "queue_wait_cdf_ms": [
                {"p": 0.25, "v": 100.0},
                {"p": 0.5, "v": 150.0},
                {"p": 0.75, "v": 200.0},
                {"p": 0.9, "v": 280.0},
                {"p": 0.95, "v": 320.0}
            ],
            "metadata": {
                "git_sha": "abc123def456",
                "cfg_hash": "config_hash_123"
            }
        }
        
        is_valid, errors = validate_summary_payload(valid_summary)
        assert is_valid, f"Valid summary should pass, got errors: {errors}"
        assert len(errors) == 0

    def test_missing_required_keys_fails(self):
        """Test that missing required top-level keys fail validation."""
        incomplete_summary = {
            "symbol": "INCOMPLETE",
            "counts": {"orders": 1, "quotes": 1, "fills": 0}
            # Missing: schema_version, window_utc, hit_rate_by_bin, queue_wait_cdf_ms, metadata
        }
        
        is_valid, errors = validate_summary_payload(incomplete_summary)
        assert not is_valid
        assert len(errors) >= 5  # At least 5 missing keys
        
        missing_keys = ["schema_version", "window_utc", "hit_rate_by_bin", "queue_wait_cdf_ms", "metadata"]
        for key in missing_keys:
            assert any(key in error for error in errors), f"Should report missing key: {key}"

    def test_invalid_counts_fail_validation(self):
        """Test that invalid count values fail validation."""
        test_cases = [
            {"orders": -1, "quotes": 5, "fills": 2},  # Negative orders
            {"orders": 5, "quotes": "invalid", "fills": 2},  # Non-integer quotes  
            {"orders": 5, "quotes": 3, "fills": 10},  # Missing fills > quotes validation handled elsewhere
            {"orders": 5, "quotes": 3},  # Missing fills key
        ]
        
        for invalid_counts in test_cases:
            summary = {
                "schema_version": "e1.1",
                "symbol": "BADCOUNT",
                "counts": invalid_counts,
                "hit_rate_by_bin": {},
                "queue_wait_cdf_ms": [],
                "window_utc": {"hour_start": "2025-01-15T10:00:00Z", "hour_end": "2025-01-15T11:00:00Z"},
                "metadata": {"git_sha": "test", "cfg_hash": "test"}
            }
            
            is_valid, errors = validate_summary_payload(summary)
            assert not is_valid, f"Should fail for counts: {invalid_counts}"
            assert len(errors) > 0

    def test_invalid_bin_keys_fail_validation(self):
        """Test that invalid price bin keys fail validation."""
        summary_base = {
            "schema_version": "e1.1",
            "symbol": "BADBIN",
            "counts": {"orders": 5, "quotes": 10, "fills": 3},
            "queue_wait_cdf_ms": [],
            "window_utc": {"hour_start": "2025-01-15T10:00:00Z", "hour_end": "2025-01-15T11:00:00Z"},
            "metadata": {"git_sha": "test", "cfg_hash": "test"},
            "bins_max_bps": 25
        }
        
        # Test invalid bin keys
        invalid_bins = [
            {"invalid_key": {"count": 5, "fills": 2}},  # Non-numeric key
            {"-5": {"count": 5, "fills": 2}},  # Negative bin
            {"30": {"count": 5, "fills": 2}},  # Above bins_max_bps (25)
            {"5.5": {"count": 5, "fills": 2}},  # Float key (should be integer)
        ]
        
        for hit_rate_by_bin in invalid_bins:
            summary = {**summary_base, "hit_rate_by_bin": hit_rate_by_bin}
            is_valid, errors = validate_summary_payload(summary)
            assert not is_valid, f"Should fail for bins: {hit_rate_by_bin}"

    def test_invalid_bin_data_fails_validation(self):
        """Test that invalid bin data structure fails validation."""
        summary_base = {
            "schema_version": "e1.1",
            "symbol": "BADDATA",
            "counts": {"orders": 5, "quotes": 10, "fills": 3},
            "queue_wait_cdf_ms": [],
            "window_utc": {"hour_start": "2025-01-15T10:00:00Z", "hour_end": "2025-01-15T11:00:00Z"},
            "metadata": {"git_sha": "test", "cfg_hash": "test"}
        }
        
        # Test invalid bin data
        invalid_data = [
            {"5": "not_a_dict"},  # String instead of dict
            {"5": {"count": 5}},  # Missing fills
            {"5": {"fills": 3}},  # Missing count
            {"5": {"count": -1, "fills": 3}},  # Negative count
            {"5": {"count": 5, "fills": -1}},  # Negative fills
            {"5": {"count": 3, "fills": 5}},  # fills > count
            {"5": {"count": "invalid", "fills": 3}},  # Non-integer count
        ]
        
        for hit_rate_by_bin in invalid_data:
            summary = {**summary_base, "hit_rate_by_bin": hit_rate_by_bin}
            is_valid, errors = validate_summary_payload(summary)
            assert not is_valid, f"Should fail for bin data: {hit_rate_by_bin}"

    def test_invalid_cdf_fails_validation(self):
        """Test that invalid CDF data fails validation."""
        summary_base = {
            "schema_version": "e1.1",
            "symbol": "BADCDF",
            "counts": {"orders": 5, "quotes": 10, "fills": 3},
            "hit_rate_by_bin": {"5": {"count": 10, "fills": 3}},
            "window_utc": {"hour_start": "2025-01-15T10:00:00Z", "hour_end": "2025-01-15T11:00:00Z"},
            "metadata": {"git_sha": "test", "cfg_hash": "test"}
        }
        
        # Test invalid CDF data
        invalid_cdfs = [
            "not_a_list",  # String instead of list
            [{"p": 0.5}],  # Missing 'v' field
            [{"v": 100.0}],  # Missing 'p' field
            [{"p": "invalid", "v": 100.0}],  # Non-numeric p
            [{"p": 0.5, "v": "invalid"}],  # Non-numeric v
            [{"p": 1.5, "v": 100.0}],  # p > 1.0
            [{"p": -0.1, "v": 100.0}],  # p < 0.0
            [{"p": 0.5, "v": 100.0}, {"p": 0.3, "v": 120.0}],  # p not strictly increasing
            [{"p": 0.3, "v": 150.0}, {"p": 0.5, "v": 100.0}],  # v decreasing
        ]
        
        for queue_wait_cdf_ms in invalid_cdfs:
            summary = {**summary_base, "queue_wait_cdf_ms": queue_wait_cdf_ms}
            is_valid, errors = validate_summary_payload(summary)
            assert not is_valid, f"Should fail for CDF: {queue_wait_cdf_ms}"

    def test_invalid_window_utc_fails_validation(self):
        """Test that invalid window_utc data fails validation."""
        summary_base = {
            "schema_version": "e1.1",
            "symbol": "BADWINDOW",
            "counts": {"orders": 5, "quotes": 10, "fills": 3},
            "hit_rate_by_bin": {"5": {"count": 10, "fills": 3}},
            "queue_wait_cdf_ms": [{"p": 0.5, "v": 100.0}],
            "metadata": {"git_sha": "test", "cfg_hash": "test"}
        }
        
        # Test invalid window_utc
        invalid_windows = [
            "not_a_dict",  # String instead of dict
            {},  # Missing both fields
            {"hour_start": "2025-01-15T10:00:00Z"},  # Missing hour_end
            {"hour_end": "2025-01-15T11:00:00Z"},  # Missing hour_start
            {"hour_start": "invalid", "hour_end": "2025-01-15T11:00:00Z"},  # Invalid start format
            {"hour_start": "2025-01-15T10:00:00Z", "hour_end": "invalid"},  # Invalid end format
            {"hour_start": "2025-01-15T10:00:00", "hour_end": "2025-01-15T11:00:00"},  # Missing Z suffix
            {"hour_start": "2025-01-15T11:00:00Z", "hour_end": "2025-01-15T10:00:00Z"},  # Start >= end
        ]
        
        for window_utc in invalid_windows:
            summary = {**summary_base, "window_utc": window_utc}
            is_valid, errors = validate_summary_payload(summary)
            assert not is_valid, f"Should fail for window: {window_utc}"

    def test_invalid_metadata_fails_validation(self):
        """Test that invalid metadata fails validation."""
        summary_base = {
            "schema_version": "e1.1",
            "symbol": "BADMETA",
            "counts": {"orders": 5, "quotes": 10, "fills": 3},
            "hit_rate_by_bin": {"5": {"count": 10, "fills": 3}},
            "queue_wait_cdf_ms": [{"p": 0.5, "v": 100.0}],
            "window_utc": {"hour_start": "2025-01-15T10:00:00Z", "hour_end": "2025-01-15T11:00:00Z"}
        }
        
        # Test invalid metadata
        invalid_metadata = [
            "not_a_dict",  # String instead of dict
            {},  # Missing both fields
            {"git_sha": "test"},  # Missing cfg_hash
            {"cfg_hash": "test"},  # Missing git_sha
            {"git_sha": "", "cfg_hash": "test"},  # Empty git_sha
            {"git_sha": "test", "cfg_hash": ""},  # Empty cfg_hash
            {"git_sha": 123, "cfg_hash": "test"},  # Non-string git_sha
            {"git_sha": "test", "cfg_hash": 456},  # Non-string cfg_hash
        ]
        
        for metadata in invalid_metadata:
            summary = {**summary_base, "metadata": metadata}
            is_valid, errors = validate_summary_payload(summary)
            assert not is_valid, f"Should fail for metadata: {metadata}"

    def test_invalid_schema_version_fails_validation(self):
        """Test that invalid schema versions fail validation."""
        summary_base = {
            "symbol": "BADSCHEMA",
            "counts": {"orders": 5, "quotes": 10, "fills": 3},
            "hit_rate_by_bin": {"5": {"count": 10, "fills": 3}},
            "queue_wait_cdf_ms": [{"p": 0.5, "v": 100.0}],
            "window_utc": {"hour_start": "2025-01-15T10:00:00Z", "hour_end": "2025-01-15T11:00:00Z"},
            "metadata": {"git_sha": "test", "cfg_hash": "test"}
        }
        
        # Test invalid schema versions
        invalid_versions = [
            123,  # Non-string
            "",   # Empty string
            "v1.0",  # Wrong prefix
            "1.0",   # No prefix
            "e2.0",  # Wrong major version
        ]
        
        for schema_version in invalid_versions:
            summary = {**summary_base, "schema_version": schema_version}
            is_valid, errors = validate_summary_payload(summary)
            assert not is_valid, f"Should fail for schema version: {schema_version}"

    def test_edge_case_valid_summaries(self):
        """Test edge cases that should still be valid."""
        # Empty bins and CDF
        empty_summary = {
            "schema_version": "e1.1",
            "symbol": "EMPTY",
            "counts": {"orders": 0, "quotes": 0, "fills": 0},
            "hit_rate_by_bin": {},  # No bins
            "queue_wait_cdf_ms": [],  # No CDF data
            "window_utc": {"hour_start": "2025-01-15T00:00:00Z", "hour_end": "2025-01-15T01:00:00Z"},
            "metadata": {"git_sha": "test", "cfg_hash": "test"}
        }
        
        is_valid, errors = validate_summary_payload(empty_summary)
        assert is_valid, f"Empty summary should be valid, got errors: {errors}"
        
        # Single CDF point
        single_cdf = {
            "schema_version": "e1.1", 
            "symbol": "SINGLE",
            "counts": {"orders": 1, "quotes": 1, "fills": 1},
            "hit_rate_by_bin": {"0": {"count": 1, "fills": 1}},
            "queue_wait_cdf_ms": [{"p": 0.5, "v": 100.0}],  # Single point
            "window_utc": {"hour_start": "2025-01-15T12:00:00Z", "hour_end": "2025-01-15T13:00:00Z"},
            "metadata": {"git_sha": "test", "cfg_hash": "test"}
        }
        
        is_valid, errors = validate_summary_payload(single_cdf)
        assert is_valid, f"Single CDF point should be valid, got errors: {errors}"

    def test_validate_hourly_summary_file_wrapper(self):
        """Test the convenience wrapper function."""
        # Test with e1.0 payload that needs upgrade
        e1_0_payload = {
            "schema_version": "e1.0",
            "symbol": "WRAPPER",
            "hour_utc": "2025-01-15T14:00:00Z",
            "counts": {"orders": 3, "quotes": 6, "fills": 2},
            "hit_rate_by_bin": {"10": {"count": 4, "fills": 1}},
            "queue_wait_cdf_ms": [{"p": 0.5, "v": 150.0}],
            "metadata": {"git_sha": "wrapper", "cfg_hash": "test"}
        }
        
        # Should upgrade and then validate
        is_valid, errors = validate_hourly_summary_file(e1_0_payload)
        assert is_valid, f"Upgraded e1.0 payload should be valid, got errors: {errors}"

    def test_exception_handling_in_wrapper(self):
        """Test that wrapper handles exceptions gracefully."""
        # Payload that causes upgrade to fail
        bad_payload = {"completely": "invalid", "structure": True}
        
        is_valid, errors = validate_hourly_summary_file(bad_payload)
        assert not is_valid
        assert len(errors) == 1
        assert "Error during upgrade/validation" in errors[0]
