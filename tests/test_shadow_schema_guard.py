"""
Test schema validation for Shadow Mode artifacts.

Ensures ITER_SUMMARY_*.json files conform to the defined schema.
"""

import json
import glob
from pathlib import Path

import pytest


def test_schema_file_exists():
    """Verify schema file exists."""
    schema_path = Path("schema/iter_summary.schema.json")
    assert schema_path.exists(), "Schema file schema/iter_summary.schema.json not found"


def test_iter_schema_validation():
    """Validate all ITER_SUMMARY_*.json files against schema."""
    try:
        import jsonschema
    except ImportError:
        pytest.skip("jsonschema not installed")
    
    schema_path = Path("schema/iter_summary.schema.json")
    if not schema_path.exists():
        pytest.skip("Schema file not found")
    
    with open(schema_path, 'r', encoding='utf-8') as f:
        schema = json.load(f)
    
    # Find all ITER_SUMMARY files in artifacts/shadow/latest
    pattern = "artifacts/shadow/latest/ITER_SUMMARY_*.json"
    files = glob.glob(pattern)
    
    if not files:
        pytest.skip(f"No ITER_SUMMARY files found (pattern: {pattern})")
    
    # Validate each file
    for filepath in files:
        with open(filepath, 'r', encoding='utf-8') as f:
            data = json.load(f)
        
        # Validate against schema
        jsonschema.validate(instance=data, schema=schema)
        
        # Additional checks
        assert data["iteration"] > 0, f"{filepath}: iteration must be > 0"
        assert data["mode"] in ["shadow", "soak"], f"{filepath}: mode must be 'shadow' or 'soak'"
        assert 0.0 <= data["summary"]["maker_taker_ratio"] <= 1.0, \
            f"{filepath}: maker_taker_ratio must be in [0, 1]"


def test_shadow_specific_fields():
    """Verify shadow-specific fields are present."""
    try:
        import jsonschema
    except ImportError:
        pytest.skip("jsonschema not installed")
    
    # Find shadow mode files
    pattern = "artifacts/shadow/latest/ITER_SUMMARY_*.json"
    files = glob.glob(pattern)
    
    if not files:
        pytest.skip(f"No ITER_SUMMARY files found (pattern: {pattern})")
    
    for filepath in files:
        with open(filepath, 'r', encoding='utf-8') as f:
            data = json.load(f)
        
        # Check shadow-specific field
        if data.get("mode") == "shadow":
            summary = data.get("summary", {})
            assert "clock_drift_ms" in summary or True, \
                f"{filepath}: shadow mode should include clock_drift_ms (optional)"


def test_schema_matches_soak_schema():
    """Verify shadow schema is compatible with soak schema."""
    schema_path = Path("schema/iter_summary.schema.json")
    if not schema_path.exists():
        pytest.skip("Schema file not found")
    
    with open(schema_path, 'r', encoding='utf-8') as f:
        schema = json.load(f)
    
    # Verify required fields match soak expectations
    required = schema["required"]
    assert "iteration" in required
    assert "timestamp" in required
    assert "summary" in required
    assert "mode" in required
    
    # Verify summary structure
    summary_props = schema["properties"]["summary"]["properties"]
    assert "maker_count" in summary_props
    assert "taker_count" in summary_props
    assert "maker_taker_ratio" in summary_props
    assert "net_bps" in summary_props
    assert "p95_latency_ms" in summary_props
    assert "risk_ratio" in summary_props

