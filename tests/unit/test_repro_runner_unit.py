#!/usr/bin/env python3
"""
Unit tests for tools/debug/repro_runner.py — Event replay runner.

Tests:
- run_case() with various event streams
- Guard reason detection (DRIFT, REG)
- Edge cases: empty files, invalid JSON, mixed events
"""
import json
import pytest
from pathlib import Path
from tools.debug.repro_runner import run_case


# ======================================================================
# Test run_case
# ======================================================================

def test_run_case_empty_file(tmp_path):
    """Test run_case with empty file."""
    events_file = tmp_path / "events.jsonl"
    events_file.write_text("")
    
    result = run_case(str(events_file))
    
    assert result["fail"] is False
    assert result["reason"] == "NONE"
    assert result["metrics"]["events_total"] == 0
    assert result["metrics"]["types"] == {}


def test_run_case_single_event(tmp_path):
    """Test run_case with single event."""
    events_file = tmp_path / "events.jsonl"
    events_file.write_text('{"type": "quote", "side": "buy"}\n')
    
    result = run_case(str(events_file))
    
    assert result["fail"] is False
    assert result["reason"] == "NONE"
    assert result["metrics"]["events_total"] == 1
    assert result["metrics"]["types"] == {"quote": 1}


def test_run_case_multiple_events_same_type(tmp_path):
    """Test run_case with multiple events of same type."""
    events_file = tmp_path / "events.jsonl"
    events = [
        '{"type": "trade", "price": 100.0}\n',
        '{"type": "trade", "price": 101.0}\n',
        '{"type": "trade", "price": 102.0}\n',
    ]
    events_file.write_text("".join(events))
    
    result = run_case(str(events_file))
    
    assert result["fail"] is False
    assert result["reason"] == "NONE"
    assert result["metrics"]["events_total"] == 3
    assert result["metrics"]["types"] == {"trade": 3}


def test_run_case_mixed_event_types(tmp_path):
    """Test run_case with mixed event types."""
    events_file = tmp_path / "events.jsonl"
    events = [
        '{"type": "quote", "side": "buy"}\n',
        '{"type": "trade", "price": 100.0}\n',
        '{"type": "quote", "side": "sell"}\n',
        '{"type": "fill", "qty": 1.0}\n',
    ]
    events_file.write_text("".join(events))
    
    result = run_case(str(events_file))
    
    assert result["fail"] is False
    assert result["reason"] == "NONE"
    assert result["metrics"]["events_total"] == 4
    assert result["metrics"]["types"] == {"fill": 1, "quote": 2, "trade": 1}


def test_run_case_guard_drift_reason(tmp_path):
    """Test run_case detects DRIFT guard reason."""
    events_file = tmp_path / "events.jsonl"
    events = [
        '{"type": "quote", "side": "buy"}\n',
        '{"type": "guard", "reason": "DRIFT_TOO_HIGH"}\n',
        '{"type": "trade", "price": 100.0}\n',
    ]
    events_file.write_text("".join(events))
    
    result = run_case(str(events_file))
    
    assert result["fail"] is True
    assert result["reason"] == "DRIFT"
    assert result["metrics"]["events_total"] == 3
    assert result["metrics"]["types"]["guard"] == 1


def test_run_case_guard_reg_reason(tmp_path):
    """Test run_case detects REG guard reason."""
    events_file = tmp_path / "events.jsonl"
    events = [
        '{"type": "quote", "side": "buy"}\n',
        '{"type": "guard", "reason": "REGRESSION_DETECTED"}\n',
        '{"type": "trade", "price": 100.0}\n',
    ]
    events_file.write_text("".join(events))
    
    result = run_case(str(events_file))
    
    assert result["fail"] is True
    assert result["reason"] == "REG"
    assert result["metrics"]["events_total"] == 3


def test_run_case_drift_precedence_over_reg(tmp_path):
    """Test run_case gives precedence to DRIFT over REG."""
    events_file = tmp_path / "events.jsonl"
    events = [
        '{"type": "guard", "reason": "REGRESSION_DETECTED"}\n',
        '{"type": "guard", "reason": "DRIFT_TOO_HIGH"}\n',
    ]
    events_file.write_text("".join(events))
    
    result = run_case(str(events_file))
    
    # DRIFT should override REG
    assert result["fail"] is True
    assert result["reason"] == "DRIFT"


def test_run_case_reg_precedence_maintains_fail(tmp_path):
    """Test run_case REG doesn't override existing fail state."""
    events_file = tmp_path / "events.jsonl"
    events = [
        '{"type": "guard", "reason": "REGRESSION_FIRST"}\n',
        '{"type": "guard", "reason": "REGRESSION_SECOND"}\n',
    ]
    events_file.write_text("".join(events))
    
    result = run_case(str(events_file))
    
    assert result["fail"] is True
    assert result["reason"] == "REG"


def test_run_case_invalid_json_lines_skipped(tmp_path):
    """Test run_case skips invalid JSON lines."""
    events_file = tmp_path / "events.jsonl"
    events = [
        '{"type": "quote", "side": "buy"}\n',
        'INVALID JSON LINE\n',
        '{"type": "trade", "price": 100.0}\n',
        '{broken json\n',
    ]
    events_file.write_text("".join(events))
    
    result = run_case(str(events_file))
    
    # Only 2 valid events should be counted
    assert result["metrics"]["events_total"] == 2
    assert result["metrics"]["types"] == {"quote": 1, "trade": 1}


def test_run_case_blank_lines_skipped(tmp_path):
    """Test run_case skips blank lines."""
    events_file = tmp_path / "events.jsonl"
    events = [
        '{"type": "quote"}\n',
        '\n',
        '   \n',
        '{"type": "trade"}\n',
        '\n',
    ]
    events_file.write_text("".join(events))
    
    result = run_case(str(events_file))
    
    # Only 2 non-blank events
    assert result["metrics"]["events_total"] == 2


def test_run_case_event_without_type(tmp_path):
    """Test run_case handles events without 'type' field."""
    events_file = tmp_path / "events.jsonl"
    events = [
        '{"price": 100.0}\n',
        '{"side": "buy"}\n',
    ]
    events_file.write_text("".join(events))
    
    result = run_case(str(events_file))
    
    # Events without 'type' get empty string as type
    assert result["metrics"]["events_total"] == 2
    assert result["metrics"]["types"] == {"": 2}


def test_run_case_guard_without_reason(tmp_path):
    """Test run_case handles guard events without 'reason' field."""
    events_file = tmp_path / "events.jsonl"
    events = [
        '{"type": "guard"}\n',
    ]
    events_file.write_text("".join(events))
    
    result = run_case(str(events_file))
    
    # Guard without reason doesn't trigger fail
    assert result["fail"] is False
    assert result["reason"] == "NONE"


def test_run_case_deterministic_type_ordering(tmp_path):
    """Test run_case returns types in sorted order."""
    events_file = tmp_path / "events.jsonl"
    events = [
        '{"type": "zebra"}\n',
        '{"type": "apple"}\n',
        '{"type": "middle"}\n',
    ]
    events_file.write_text("".join(events))
    
    result = run_case(str(events_file))
    
    # Types should be alphabetically sorted
    assert list(result["metrics"]["types"].keys()) == ["apple", "middle", "zebra"]


def test_run_case_large_event_count(tmp_path):
    """Test run_case handles large number of events."""
    events_file = tmp_path / "events.jsonl"
    
    # Generate 1000 events
    events = [f'{{"type": "event_{i % 10}"}}\n' for i in range(1000)]
    events_file.write_text("".join(events))
    
    result = run_case(str(events_file))
    
    assert result["metrics"]["events_total"] == 1000
    assert len(result["metrics"]["types"]) == 10
    # Each type should have 100 events (1000 / 10)
    for count in result["metrics"]["types"].values():
        assert count == 100


# ======================================================================
# Run tests
# ======================================================================

if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])

