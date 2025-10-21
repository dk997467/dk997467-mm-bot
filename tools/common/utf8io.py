#!/usr/bin/env python3
"""
UTF-8 safe I/O utilities for cross-platform console output.

This module provides utilities to ensure UTF-8 output on all platforms,
with graceful ASCII fallback for legacy consoles (e.g., Windows cp1251).

Usage:
    from tools.common.utf8io import ensure_utf8_stdio, puts, sym
    
    ensure_utf8_stdio()  # Reconfigure stdio to UTF-8 if possible
    puts(f"{sym('ok')} Task completed successfully")
    puts(f"{sym('fail')} Task failed")
    puts(f"{sym('warn')} Warning message")
"""

from __future__ import annotations
import sys
import os
from typing import Optional

# Symbol mappings
ASCII_FALLBACK = {
    "ok": "OK",
    "fail": "X",
    "warn": "!",
    "info": "i",
    "arrow": "->",
    "bullet": "*",
}

UNICODE_SYM = {
    "ok": "✓",
    "fail": "✗",
    "warn": "⚠",
    "info": "ℹ",
    "arrow": "→",
    "bullet": "•",
}


def ensure_utf8_stdio() -> None:
    """
    Reconfigure stdout/stderr to use UTF-8 encoding if possible.
    
    This is safe to call multiple times and will not raise exceptions.
    On Python 3.7+, uses reconfigure() to change encoding without
    recreating the stream objects.
    """
    try:
        # Python 3.7+ supports reconfigure()
        if hasattr(sys.stdout, "reconfigure"):
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        if hasattr(sys.stderr, "reconfigure"):
            sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        # If reconfigure fails, we'll just use whatever encoding is available
        pass


def _supports_unicode(char: str) -> bool:
    """
    Check if the current stdout encoding supports a specific character.
    
    Args:
        char: Single character to test
        
    Returns:
        True if the character can be encoded with current stdout encoding
    """
    # Get current encoding from stdout, environment, or default to utf-8
    enc = (
        getattr(sys.stdout, "encoding", None)
        or os.environ.get("PYTHONIOENCODING")
        or "utf-8"
    )
    
    try:
        char.encode(enc)
        return True
    except (UnicodeEncodeError, LookupError, AttributeError):
        return False


def sym(kind: str) -> str:
    """
    Get a symbol with automatic fallback to ASCII if console doesn't support Unicode.
    
    Args:
        kind: Symbol type (ok, fail, warn, info, arrow, bullet)
        
    Returns:
        Unicode symbol if supported, otherwise ASCII fallback
        
    Examples:
        >>> sym('ok')  # Returns '✓' on UTF-8 console, 'OK' on ASCII
        '✓'
        >>> sym('fail')  # Returns '✗' on UTF-8 console, 'X' on ASCII
        '✗'
    """
    unicode_char = UNICODE_SYM.get(kind, "?")
    
    # Check if console supports this Unicode character
    if _supports_unicode(unicode_char):
        return unicode_char
    
    # Fall back to ASCII
    return ASCII_FALLBACK.get(kind, "?")


def safe_str(s: str) -> str:
    """
    Convert string to console-safe representation with error replacement.
    
    Args:
        s: Input string (may contain any Unicode characters)
        
    Returns:
        String safe for current console encoding
    """
    enc = getattr(sys.stdout, "encoding", None) or "utf-8"
    
    try:
        # Try to encode/decode with current encoding
        return s.encode(enc, errors="replace").decode(enc, errors="replace")
    except Exception:
        # Ultimate fallback: ASCII with replacement
        return s.encode("ascii", errors="replace").decode("ascii")


def puts(msg: str = "", *, file=None, end: str = "\n", flush: bool = False) -> None:
    """
    Print message to console without ever raising UnicodeEncodeError.
    
    This function is a safe replacement for print() that handles
    encoding errors gracefully on all platforms.
    
    Args:
        msg: Message to print
        file: Output stream (default: sys.stdout)
        end: String to append at end (default: newline)
        flush: Whether to flush stream after writing
        
    Examples:
        >>> puts("✓ Task completed")  # Safe on all consoles
        >>> puts(f"{sym('ok')} All tests passed")  # Recommended pattern
    """
    stream = file or sys.stdout
    
    try:
        # Try to write the safe string representation
        stream.write(safe_str(msg) + end)
        if flush:
            stream.flush()
    except Exception:
        # Last-ditch fallback: force ASCII
        try:
            ascii_msg = msg.encode("ascii", errors="replace").decode("ascii")
            stream.write(ascii_msg + end)
            if flush:
                stream.flush()
        except Exception:
            # If even ASCII fails, we give up silently
            pass


def safe_print(*args, sep: str = " ", end: str = "\n", file=None, flush: bool = False) -> None:
    """
    Drop-in replacement for print() with Unicode safety.
    
    Args:
        *args: Values to print (will be converted to strings)
        sep: Separator between arguments
        end: String to append at end
        file: Output stream
        flush: Whether to flush stream
    """
    msg = sep.join(str(arg) for arg in args)
    puts(msg, file=file, end=end, flush=flush)

