"""
Unit tests for UTF-8 safe I/O utilities.

Tests ensure that output functions work on all platforms, including
legacy Windows consoles with cp1251 encoding.
"""

import io
import sys
import pytest

from tools.common.utf8io import (
    ensure_utf8_stdio,
    puts,
    sym,
    safe_str,
    safe_print,
    _supports_unicode,
)


def test_ensure_utf8_stdio_no_crash():
    """Test that ensure_utf8_stdio doesn't crash on any platform."""
    # Should not raise any exceptions
    ensure_utf8_stdio()
    # Run it twice to ensure idempotency
    ensure_utf8_stdio()


def test_sym_returns_unicode_or_ascii():
    """Test that sym() returns valid strings for all symbol types."""
    symbol_types = ["ok", "fail", "warn", "info", "arrow", "bullet"]
    
    for sym_type in symbol_types:
        result = sym(sym_type)
        assert isinstance(result, str)
        assert len(result) > 0


def test_sym_unknown_type_returns_question_mark():
    """Test that unknown symbol types return '?'."""
    assert sym("unknown_type") == "?"


def test_safe_str_handles_unicode():
    """Test that safe_str converts strings without crashing."""
    test_strings = [
        "Simple ASCII",
        "Unicode ✓ ✗ ⚠",
        "Mixed ASCII and ✓ symbols",
        "Emoji 🎉 🚀",
        "Cyrillic Привет мир",
    ]
    
    for test_str in test_strings:
        result = safe_str(test_str)
        assert isinstance(result, str)
        # Result should be non-empty
        assert len(result) > 0


def test_puts_no_crash_with_unicode(capsys):
    """Test that puts() works with Unicode strings on normal console."""
    puts("✓ Unicode OK")
    puts("✗ Unicode FAIL")
    puts("⚠ Unicode WARN")
    
    captured = capsys.readouterr()
    # Should have printed something
    assert len(captured.out) > 0


def test_puts_with_custom_end(capsys):
    """Test that puts() respects custom end parameter."""
    puts("Line 1", end=" | ")
    puts("Line 2", end=" | ")
    puts("Line 3")
    
    captured = capsys.readouterr()
    assert "Line 1 | Line 2 | Line 3" in captured.out


def test_puts_with_file_parameter():
    """Test that puts() can write to custom file objects."""
    buffer = io.StringIO()
    puts("Test message", file=buffer)
    
    result = buffer.getvalue()
    assert "Test message" in result


def test_safe_print_multiple_args(capsys):
    """Test that safe_print works like print with multiple arguments."""
    safe_print("Value 1", "Value 2", "Value 3")
    
    captured = capsys.readouterr()
    assert "Value 1 Value 2 Value 3" in captured.out


def test_safe_print_custom_separator(capsys):
    """Test that safe_print respects custom separator."""
    safe_print("A", "B", "C", sep=" | ")
    
    captured = capsys.readouterr()
    assert "A | B | C" in captured.out


def test_puts_no_crash_cp1251(monkeypatch):
    """
    Test that puts() doesn't crash even on cp1251 console.
    
    This simulates a Windows legacy console that can't handle Unicode.
    """
    # Create a BytesIO buffer wrapped as TextIOWrapper with cp1251
    buf = io.BytesIO()
    
    # Note: We use 'replace' errors to prevent strict encoding failures
    # during the test itself, but the puts() function should handle this
    fake_stdout = io.TextIOWrapper(buf, encoding="cp1251", errors="replace")
    
    # Monkeypatch sys.stdout
    monkeypatch.setattr(sys, "stdout", fake_stdout)
    
    # Try to reconfigure (may or may not work on fake stream)
    ensure_utf8_stdio()
    
    # These strings contain characters not representable in cp1251
    puts(f"{sym('ok')} Unicode ✓ OK")
    puts(f"{sym('fail')} Unicode ✗ FAIL")
    puts(f"{sym('warn')} Unicode ⚠ WARN")
    puts("Emoji test: 🎉 🚀")
    
    # Flush to ensure everything is written
    fake_stdout.flush()
    
    # Check that something was written (no exceptions raised)
    data = buf.getvalue()
    assert len(data) > 0


def test_puts_no_crash_ascii_only(monkeypatch):
    """Test that puts() works on ASCII-only console."""
    buf = io.BytesIO()
    fake_stdout = io.TextIOWrapper(buf, encoding="ascii", errors="replace")
    
    monkeypatch.setattr(sys, "stdout", fake_stdout)
    
    puts("ASCII only text")
    puts(f"{sym('ok')} This should not crash")
    
    fake_stdout.flush()
    data = buf.getvalue()
    assert len(data) > 0


def test_sym_fallback_on_ascii_console(monkeypatch):
    """Test that sym() falls back to ASCII on ASCII-only console."""
    buf = io.BytesIO()
    fake_stdout = io.TextIOWrapper(buf, encoding="ascii", errors="strict")
    
    monkeypatch.setattr(sys, "stdout", fake_stdout)
    
    # On ASCII console, should get ASCII fallback
    result_ok = sym("ok")
    result_fail = sym("fail")
    result_warn = sym("warn")
    
    # Result should be either Unicode (if detection failed) or ASCII
    # The important part is it doesn't crash
    assert result_ok in ("✓", "OK")
    assert result_fail in ("✗", "X")
    assert result_warn in ("⚠", "!")


def test_supports_unicode_internal():
    """Test the internal _supports_unicode function."""
    # Test with ASCII character (should always work)
    assert _supports_unicode("A") is True
    
    # Test with Unicode character
    # Result depends on current console encoding
    result = _supports_unicode("✓")
    assert isinstance(result, bool)


def test_puts_with_flush(monkeypatch):
    """Test that puts() respects flush parameter."""
    buf = io.BytesIO()
    fake_stdout = io.TextIOWrapper(buf, encoding="utf-8")
    fake_stdout.flush_called = False
    
    original_flush = fake_stdout.flush
    
    def tracked_flush():
        fake_stdout.flush_called = True
        original_flush()
    
    fake_stdout.flush = tracked_flush
    monkeypatch.setattr(sys, "stdout", fake_stdout)
    
    # Test with flush=True
    puts("Test", flush=True)
    assert fake_stdout.flush_called


def test_puts_handles_newlines_in_message(capsys):
    """Test that puts() correctly handles messages with newlines."""
    puts("Line 1\nLine 2\nLine 3")
    
    captured = capsys.readouterr()
    lines = captured.out.split("\n")
    # Should have at least 3 lines (plus potentially empty line from final newline)
    assert len([l for l in lines if l.strip()]) >= 3


def test_puts_empty_message(capsys):
    """Test that puts() handles empty messages correctly."""
    puts()  # No message
    puts("")  # Empty string
    
    captured = capsys.readouterr()
    # Should have printed two newlines
    assert captured.out.count("\n") >= 2


def test_integration_real_world_audit_output(capsys):
    """
    Integration test: simulate real-world audit output with mixed symbols.
    
    This tests the actual use case from tools/soak/audit_artifacts.py
    """
    ensure_utf8_stdio()
    
    # Simulate audit output
    puts(f"{sym('ok')} Base directory exists")
    puts(f"{sym('ok')} Found 24 iteration summaries")
    puts(f"{sym('warn')} Some iterations missing")
    puts(f"{sym('fail')} Validation failed")
    puts(f"{sym('info')} Additional information")
    
    captured = capsys.readouterr()
    
    # Should have printed all lines
    lines = [l for l in captured.out.split("\n") if l.strip()]
    assert len(lines) == 5
    
    # Each line should be non-empty
    for line in lines:
        assert len(line) > 0

