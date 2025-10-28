"""
Unit tests for JSONLogger (tools/obs/jsonlog.py).

Tests:
- Basic logging (info/warn/error/debug/critical)
- Secret masking (key, secret, token, password)
- Deterministic output (sorted keys, stable timestamp)
- One-line JSON output
- Nested structures (dict/list)
- Default context propagation
"""

from __future__ import annotations

import io
import json
import os

import pytest

from tools.obs.jsonlog import get_logger, _mask_value, _mask_sensitive_recursive


def test_mask_value():
    """Test value masking logic."""
    assert _mask_value("abcdef123") == "abc*****"
    assert _mask_value("xy") == "xy*****"
    assert _mask_value("") == "*****"
    assert _mask_value("a") == "a*****"


def test_mask_sensitive_dict():
    """Test recursive masking of sensitive fields."""
    data = {
        "user": "alice",
        "api_key": "secret123",
        "password": "pass456",
        "public_field": "visible",
    }
    
    masked = _mask_sensitive_recursive(data)
    
    assert masked["user"] == "alice"
    assert masked["api_key"] == "sec*****"
    assert masked["password"] == "pas*****"
    assert masked["public_field"] == "visible"


def test_mask_sensitive_nested():
    """Test masking in nested structures."""
    data = {
        "config": {
            "api_secret": "topsecret",
            "endpoint": "https://api.example.com",
        },
        "tokens": ["token1", "token2"],
    }
    
    masked = _mask_sensitive_recursive(data)
    
    assert masked["config"]["api_secret"] == "top*****"
    assert masked["config"]["endpoint"] == "https://api.example.com"
    assert isinstance(masked["tokens"], list)


def test_jsonlogger_basic_output():
    """Test basic JSON log output."""
    # Capture output
    output = io.StringIO()
    
    # Fixed clock for determinism
    def fake_clock():
        return "2025-10-27T10:00:00.000000Z"
    
    logger = get_logger("test.module", output_stream=output, clock=fake_clock)
    logger.info("test_event", foo="bar", num=42)
    
    # Parse output
    line = output.getvalue()
    assert line.endswith("\n")
    
    parsed = json.loads(line)
    
    # Verify fields
    assert parsed["ts_utc"] == "2025-10-27T10:00:00.000000Z"
    assert parsed["lvl"] == "INFO"
    assert parsed["name"] == "test.module"
    assert parsed["event"] == "test_event"
    assert parsed["foo"] == "bar"
    assert parsed["num"] == 42


def test_jsonlogger_sorted_keys():
    """Test that keys are sorted for determinism."""
    output = io.StringIO()
    
    def fake_clock():
        return "2025-10-27T10:00:00.000000Z"
    
    logger = get_logger("test", output_stream=output, clock=fake_clock)
    logger.info("event", zebra="z", apple="a", banana="b")
    
    line = output.getvalue()
    
    # Check that JSON is sorted (apple < banana < zebra alphabetically)
    # The line should have keys in sorted order
    assert line.index('"apple"') < line.index('"banana"')
    assert line.index('"banana"') < line.index('"zebra"')


def test_jsonlogger_secret_masking():
    """Test that sensitive fields are masked."""
    output = io.StringIO()
    
    def fake_clock():
        return "2025-10-27T10:00:00.000000Z"
    
    logger = get_logger("test", output_stream=output, clock=fake_clock)
    logger.info(
        "auth",
        api_key="secret123",
        password="pass456",
        user="alice",
    )
    
    line = output.getvalue()
    parsed = json.loads(line)
    
    assert parsed["api_key"] == "sec*****"
    assert parsed["password"] == "pas*****"
    assert parsed["user"] == "alice"


def test_jsonlogger_default_context():
    """Test that default context is added to all logs."""
    output = io.StringIO()
    
    def fake_clock():
        return "2025-10-27T10:00:00.000000Z"
    
    logger = get_logger(
        "test",
        default_ctx={"env": "prod", "version": "1.0"},
        output_stream=output,
        clock=fake_clock,
    )
    logger.info("event", custom="value")
    
    line = output.getvalue()
    parsed = json.loads(line)
    
    assert parsed["env"] == "prod"
    assert parsed["version"] == "1.0"
    assert parsed["custom"] == "value"


def test_jsonlogger_levels():
    """Test all log levels."""
    output = io.StringIO()
    
    def fake_clock():
        return "2025-10-27T10:00:00.000000Z"
    
    logger = get_logger("test", output_stream=output, clock=fake_clock)
    
    logger.debug("debug_event")
    logger.info("info_event")
    logger.warn("warn_event")
    logger.error("error_event")
    logger.critical("critical_event")
    
    lines = output.getvalue().strip().split("\n")
    assert len(lines) == 5
    
    levels = [json.loads(line)["lvl"] for line in lines]
    assert levels == ["DEBUG", "INFO", "WARN", "ERROR", "CRITICAL"]


def test_jsonlogger_one_line_per_entry():
    """Test that each log entry is exactly one line."""
    output = io.StringIO()
    
    def fake_clock():
        return "2025-10-27T10:00:00.000000Z"
    
    logger = get_logger("test", output_stream=output, clock=fake_clock)
    
    # Log with nested structures
    logger.info(
        "complex",
        nested={"a": 1, "b": 2},
        list_data=[1, 2, 3],
        text="multi\nline\ntext",
    )
    
    line = output.getvalue()
    
    # Should be exactly one line (ending with \n, no other \n in middle)
    assert line.count("\n") == 1
    assert line.endswith("\n")


def test_jsonlogger_uses_mm_freeze_utc_iso():
    """Test that MM_FREEZE_UTC_ISO env var is respected."""
    output = io.StringIO()
    
    # Set frozen time via env var
    frozen_time = "2025-01-01T00:00:00.000000Z"
    os.environ["MM_FREEZE_UTC_ISO"] = frozen_time
    
    try:
        logger = get_logger("test", output_stream=output)
        logger.info("event")
        
        line = output.getvalue()
        parsed = json.loads(line)
        
        assert parsed["ts_utc"] == frozen_time
    finally:
        # Clean up env var
        del os.environ["MM_FREEZE_UTC_ISO"]


def test_jsonlogger_compact_separators():
    """Test that JSON uses compact separators (no spaces)."""
    output = io.StringIO()
    
    def fake_clock():
        return "2025-10-27T10:00:00.000000Z"
    
    logger = get_logger("test", output_stream=output, clock=fake_clock)
    logger.info("event", a=1, b=2)
    
    line = output.getvalue()
    
    # Should have no spaces after : or ,
    assert ", " not in line  # No space after comma
    assert ": " not in line  # No space after colon

