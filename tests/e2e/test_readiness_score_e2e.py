"""
E2E test for readiness_score deterministic JSON output.

Tests that:
1. Output is deterministic with CI_FAKE_UTC
2. JSON format is compact (no whitespace, sorted keys)
3. Exit code is 0
"""

import json
import subprocess
import sys
import os


def test_readiness_json_deterministic():
    """
    Test readiness_score produces deterministic JSON output.
    """
    # Run with fake UTC time
    env = os.environ.copy()
    env["CI_FAKE_UTC"] = "1970-01-01T00:00:00Z"
    
    result = subprocess.run(
        [sys.executable, "-m", "tools.release.readiness_score"],
        capture_output=True,
        text=True,
        env=env,
        timeout=30
    )
    
    # Check exit code
    assert result.returncode == 0, f"Expected exit code 0, got {result.returncode}"
    
    # Parse JSON from stdout (last line)
    lines = result.stdout.strip().split('\n')
    json_line = lines[-1]  # Last line should be JSON
    
    # Verify it's valid JSON
    try:
        data = json.loads(json_line)
    except json.JSONDecodeError as e:
        raise AssertionError(f"Failed to parse JSON: {e}\nOutput: {json_line}")
    
    # Check structure
    assert "runtime" in data, "Missing 'runtime' key"
    assert "score" in data, "Missing 'score' key"
    assert "sections" in data, "Missing 'sections' key"
    assert "verdict" in data, "Missing 'verdict' key"
    
    # Check runtime structure
    assert "utc" in data["runtime"], "Missing 'runtime.utc'"
    assert "version" in data["runtime"], "Missing 'runtime.version'"
    assert data["runtime"]["utc"] == "1970-01-01T00:00:00Z", \
        f"Expected utc '1970-01-01T00:00:00Z', got {data['runtime']['utc']}"
    
    # Check sections
    expected_sections = ["chaos", "edge", "guards", "latency", "taker", "tests"]
    for sec in expected_sections:
        assert sec in data["sections"], f"Missing section '{sec}'"
    
    # Verify JSON is compact (no whitespace after colons/commas)
    assert ", " not in json_line, "JSON should have no space after comma"
    assert ": " not in json_line, "JSON should have no space after colon"
    
    # Verify keys are sorted (check runtime comes first in serialization)
    assert json_line.index('"runtime"') < json_line.index('"score"'), \
        "Keys should be sorted: 'runtime' before 'score'"
    
    print(f"✓ Readiness score deterministic test passed")
    print(f"  UTC: {data['runtime']['utc']}")
    print(f"  Score: {data['score']}")
    print(f"  Verdict: {data['verdict']}")


def test_readiness_json_format():
    """
    Test that JSON format matches expected compact structure.
    """
    env = os.environ.copy()
    env["CI_FAKE_UTC"] = "2025-01-01T12:00:00Z"
    
    result = subprocess.run(
        [sys.executable, "-m", "tools.release.readiness_score"],
        capture_output=True,
        text=True,
        env=env,
        timeout=30
    )
    
    assert result.returncode == 0
    
    lines = result.stdout.strip().split('\n')
    json_line = lines[-1]
    
    # Re-serialize with same format and compare
    data = json.loads(json_line)
    expected_json = json.dumps(data, sort_keys=True, separators=(",", ":"))
    
    assert json_line == expected_json, \
        f"JSON format mismatch.\nGot:      {json_line}\nExpected: {expected_json}"
    
    print("✓ Readiness JSON format test passed")


if __name__ == "__main__":
    test_readiness_json_deterministic()
    test_readiness_json_format()
    print("\n✓ All readiness score E2E tests passed")
