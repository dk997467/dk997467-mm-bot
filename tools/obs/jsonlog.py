"""
Structured JSON logger with determinism and secret masking.

Pure stdlib implementation with:
- Deterministic output (sorted keys, stable timestamp)
- Secret masking for sensitive fields
- Single-line JSON per log entry
- Support for MM_FREEZE_UTC_ISO environment variable for testing
"""

from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone
from typing import Any, Callable


# Fields to mask (case-insensitive matching)
SENSITIVE_FIELDS = {
    "key",
    "secret",
    "token",
    "password",
    "api_key",
    "api_secret",
    "apikey",
    "apisecret",
}


def _mask_value(value: Any) -> str:
    """
    Mask sensitive value: first 3 chars + *****
    
    Examples:
        "abcdef123" -> "abc*****"
        "xy" -> "xy*****"
        "" -> "*****"
    """
    s = str(value)
    if len(s) <= 3:
        return s + "*****"
    return s[:3] + "*****"


def _mask_sensitive_recursive(data: Any) -> Any:
    """
    Recursively mask sensitive fields in nested structures.
    
    Returns a new structure with masked values (does not mutate input).
    """
    if isinstance(data, dict):
        return {
            k: (
                _mask_value(v)
                if any(sens in k.lower() for sens in SENSITIVE_FIELDS)
                else _mask_sensitive_recursive(v)
            )
            for k, v in data.items()
        }
    elif isinstance(data, list):
        return [_mask_sensitive_recursive(item) for item in data]
    elif isinstance(data, tuple):
        return tuple(_mask_sensitive_recursive(item) for item in data)
    else:
        return data


class JSONLogger:
    """
    Structured JSON logger with deterministic output.
    
    Features:
    - Single-line JSON per log entry
    - Sorted keys for determinism
    - Secret masking
    - Supports frozen time via MM_FREEZE_UTC_ISO env var
    """
    
    def __init__(
        self,
        name: str,
        *,
        default_ctx: dict[str, Any] | None = None,
        output_stream=None,
        clock: Callable[[], str] | None = None,
    ):
        """
        Initialize JSON logger.
        
        Args:
            name: Logger name
            default_ctx: Default context fields added to every log entry
            output_stream: Output stream (default: sys.stderr)
            clock: Custom clock function returning ISO timestamp (for testing)
        """
        self.name = name
        self.default_ctx = default_ctx or {}
        self.output_stream = output_stream or sys.stderr
        self._clock = clock or self._default_clock
    
    def _default_clock(self) -> str:
        """
        Get current UTC timestamp.
        
        Respects MM_FREEZE_UTC_ISO environment variable for determinism.
        """
        frozen = os.environ.get("MM_FREEZE_UTC_ISO")
        if frozen:
            return frozen
        return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")
    
    def _emit(self, level: str, event: str, **kv: Any) -> None:
        """
        Emit a log entry as single-line JSON.
        
        Args:
            level: Log level (DEBUG, INFO, WARN, ERROR, CRITICAL)
            event: Event name/description
            **kv: Additional key-value pairs
        """
        # Build log entry
        entry = {
            "ts_utc": self._clock(),
            "lvl": level,
            "name": self.name,
            "event": event,
        }
        
        # Add default context
        entry.update(self.default_ctx)
        
        # Add custom fields
        entry.update(kv)
        
        # Mask sensitive fields
        masked = _mask_sensitive_recursive(entry)
        
        # Serialize to single-line JSON (sorted keys, compact)
        line = json.dumps(masked, sort_keys=True, separators=(",", ":")) + "\n"
        
        # Write to stream
        self.output_stream.write(line)
        self.output_stream.flush()
    
    def debug(self, event: str, **kv: Any) -> None:
        """Log DEBUG level event."""
        self._emit("DEBUG", event, **kv)
    
    def info(self, event: str, **kv: Any) -> None:
        """Log INFO level event."""
        self._emit("INFO", event, **kv)
    
    def warn(self, event: str, **kv: Any) -> None:
        """Log WARN level event."""
        self._emit("WARN", event, **kv)
    
    def warning(self, event: str, **kv: Any) -> None:
        """Alias for warn (compatibility with stdlib logging)."""
        self.warn(event, **kv)
    
    def error(self, event: str, **kv: Any) -> None:
        """Log ERROR level event."""
        self._emit("ERROR", event, **kv)
    
    def critical(self, event: str, **kv: Any) -> None:
        """Log CRITICAL level event."""
        self._emit("CRITICAL", event, **kv)


def get_logger(
    name: str,
    *,
    default_ctx: dict[str, Any] | None = None,
    output_stream=None,
    clock: Callable[[], str] | None = None,
) -> JSONLogger:
    """
    Get a structured JSON logger.
    
    Args:
        name: Logger name
        default_ctx: Default context fields added to every log entry
        output_stream: Output stream (default: sys.stderr)
        clock: Custom clock function returning ISO timestamp (for testing)
    
    Returns:
        JSONLogger instance
    
    Example:
        >>> logger = get_logger("mm.execution", default_ctx={"env": "prod"})
        >>> logger.info("order_placed", symbol="BTCUSDT", qty=0.001, price=50000)
        # Output (single line):
        # {"env":"prod","event":"order_placed","lvl":"INFO","name":"mm.execution","price":50000,"qty":0.001,"symbol":"BTCUSDT","ts_utc":"2025-10-27T10:00:00.000000Z"}
    """
    return JSONLogger(
        name,
        default_ctx=default_ctx,
        output_stream=output_stream,
        clock=clock,
    )

