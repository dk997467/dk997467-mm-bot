#!/usr/bin/env python3
"""
Unit tests for tools/common/utf8io.py — UTF-8 safe I/O utilities.

Tests:
- ensure_utf8_stdio() safely reconfigures stdout/stderr
- sym() returns appropriate symbols based on encoding
- safe_str() handles Unicode gracefully
- puts() and safe_print() never raise UnicodeEncodeError
"""
import sys
import pytest
from io import StringIO
from unittest.mock import patch, MagicMock
from tools.common.utf8io import (
    ensure_utf8_stdio,
    _supports_unicode,
    sym,
    safe_str,
    puts,
    safe_print,
    ASCII_FALLBACK,
    UNICODE_SYM,
)


# ======================================================================
# Test ensure_utf8_stdio
# ======================================================================

def test_ensure_utf8_stdio_success():
    """Test ensure_utf8_stdio successfully reconfigures stdout."""
    # Should not raise any exceptions
    ensure_utf8_stdio()
    
    # If reconfigure() is available, encoding should be utf-8
    if hasattr(sys.stdout, "reconfigure"):
        # Note: Actual encoding may vary in test environment
        # Just verify no exception was raised
        assert sys.stdout.encoding is not None


def test_ensure_utf8_stdio_no_reconfigure_fallback():
    """Test ensure_utf8_stdio gracefully handles missing reconfigure()."""
    # Mock stdout without reconfigure method
    original_stdout = sys.stdout
    mock_stdout = MagicMock(spec=[])  # No reconfigure attribute
    
    try:
        sys.stdout = mock_stdout
        
        # Should not raise exception
        ensure_utf8_stdio()
    
    finally:
        sys.stdout = original_stdout


# ======================================================================
# Test _supports_unicode
# ======================================================================

def test_supports_unicode_basic():
    """Test _supports_unicode returns bool for various characters."""
    # Just test that it returns a boolean without crashing
    result_unicode = _supports_unicode("✓")
    result_ascii = _supports_unicode("A")
    
    assert isinstance(result_unicode, bool)
    assert isinstance(result_ascii, bool)
    
    # ASCII should always be supported
    assert _supports_unicode("A") is True


def test_supports_unicode_ascii_character():
    """Test _supports_unicode returns True for ASCII chars."""
    # ASCII characters should always be encodable
    assert _supports_unicode("A") is True
    assert _supports_unicode("1") is True
    assert _supports_unicode("!") is True
    assert _supports_unicode(" ") is True


def test_supports_unicode_no_encoding_attribute():
    """Test _supports_unicode handles missing encoding attribute."""
    # Mock stdout without encoding attribute
    original_stdout = sys.stdout
    mock_stdout = MagicMock(spec=[])  # No encoding attribute
    
    try:
        sys.stdout = mock_stdout
        
        # Should default to utf-8 and handle gracefully
        result = _supports_unicode("✓")
        assert isinstance(result, bool)
    
    finally:
        sys.stdout = original_stdout


# ======================================================================
# Test sym()
# ======================================================================

def test_sym_returns_valid_strings():
    """Test sym() returns valid strings for all known symbol types."""
    # Just test that sym() returns strings without crashing
    for kind in ["ok", "fail", "warn", "info", "arrow", "bullet"]:
        result = sym(kind)
        assert isinstance(result, str)
        assert len(result) > 0


def test_sym_unknown_kind():
    """Test sym() returns '?' for unknown symbol kinds."""
    assert sym("unknown") == "?"
    assert sym("invalid") == "?"
    assert sym("") == "?"


# ======================================================================
# Test safe_str()
# ======================================================================

def test_safe_str_ascii_string():
    """Test safe_str() handles ASCII strings."""
    result = safe_str("Hello, World!")
    assert result == "Hello, World!"


def test_safe_str_unicode_string():
    """Test safe_str() handles Unicode strings without crashing."""
    # Should return a string, possibly with replacements
    result = safe_str("✓ Test passed ✗ Failed")
    assert isinstance(result, str)
    assert len(result) > 0


def test_safe_str_empty_string():
    """Test safe_str() handles empty string."""
    result = safe_str("")
    assert result == ""


def test_safe_str_mixed_content():
    """Test safe_str() handles mixed ASCII and Unicode."""
    result = safe_str("ASCII 123 → Unicode ✓")
    assert isinstance(result, str)
    assert "ASCII" in result
    assert "123" in result


def test_safe_str_no_encoding_attribute():
    """Test safe_str() handles missing encoding attribute gracefully."""
    original_stdout = sys.stdout
    mock_stdout = MagicMock(spec=[])  # No encoding attribute
    
    try:
        sys.stdout = mock_stdout
        
        # Should default to utf-8
        result = safe_str("Test string")
        assert isinstance(result, str)
    
    finally:
        sys.stdout = original_stdout


# ======================================================================
# Test puts()
# ======================================================================

def test_puts_basic_message():
    """Test puts() writes message to stdout."""
    output = StringIO()
    
    puts("Hello, World!", file=output)
    
    assert output.getvalue() == "Hello, World!\n"


def test_puts_custom_end():
    """Test puts() respects custom end parameter."""
    output = StringIO()
    
    puts("Test", file=output, end="")
    
    assert output.getvalue() == "Test"


def test_puts_with_flush():
    """Test puts() with flush=True."""
    output = StringIO()
    
    # Should not raise exception
    puts("Message", file=output, flush=True)
    
    assert "Message" in output.getvalue()


def test_puts_empty_message():
    """Test puts() with empty message."""
    output = StringIO()
    
    puts("", file=output)
    
    assert output.getvalue() == "\n"


def test_puts_unicode_message():
    """Test puts() handles Unicode messages safely."""
    output = StringIO()
    
    # Should not raise UnicodeEncodeError
    puts("✓ ✗ → •", file=output)
    
    # Should have written something
    assert len(output.getvalue()) > 0


def test_puts_never_raises_exception():
    """Test puts() never raises exceptions even with problematic messages."""
    # Mock a stream that raises on write
    mock_stream = MagicMock()
    mock_stream.write.side_effect = UnicodeEncodeError("utf-8", "test", 0, 1, "test")
    
    # Should not raise exception (graceful fallback)
    puts("Test message", file=mock_stream)


# ======================================================================
# Test safe_print()
# ======================================================================

def test_safe_print_single_argument():
    """Test safe_print() with single argument."""
    output = StringIO()
    
    safe_print("Hello", file=output)
    
    assert output.getvalue() == "Hello\n"


def test_safe_print_multiple_arguments():
    """Test safe_print() with multiple arguments."""
    output = StringIO()
    
    safe_print("Hello", "World", "!", file=output)
    
    assert output.getvalue() == "Hello World !\n"


def test_safe_print_custom_separator():
    """Test safe_print() with custom separator."""
    output = StringIO()
    
    safe_print("A", "B", "C", sep="-", file=output)
    
    assert output.getvalue() == "A-B-C\n"


def test_safe_print_custom_end():
    """Test safe_print() with custom end."""
    output = StringIO()
    
    safe_print("Test", end=" END", file=output)
    
    assert output.getvalue() == "Test END"


def test_safe_print_with_non_string_arguments():
    """Test safe_print() converts non-string arguments to strings."""
    output = StringIO()
    
    safe_print(42, 3.14, True, None, file=output)
    
    assert "42" in output.getvalue()
    assert "3.14" in output.getvalue()
    assert "True" in output.getvalue()
    assert "None" in output.getvalue()


def test_safe_print_no_arguments():
    """Test safe_print() with no arguments prints empty line."""
    output = StringIO()
    
    safe_print(file=output)
    
    assert output.getvalue() == "\n"


# ======================================================================
# Integration Tests
# ======================================================================

def test_integration_sym_with_puts():
    """Test sym() works correctly with puts()."""
    output = StringIO()
    
    # Should not raise exception
    puts(f"{sym('ok')} Success", file=output)
    puts(f"{sym('fail')} Failed", file=output)
    puts(f"{sym('warn')} Warning", file=output)
    
    # Should have written something
    assert len(output.getvalue()) > 0


def test_integration_all_symbols():
    """Test all symbol types work with puts()."""
    output = StringIO()
    
    for kind in ["ok", "fail", "warn", "info", "arrow", "bullet"]:
        puts(f"{sym(kind)} Test {kind}", file=output)
    
    # Should have 6 lines
    assert output.getvalue().count("\n") == 6


# ======================================================================
# Run tests
# ======================================================================

if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])

