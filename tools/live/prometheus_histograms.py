"""
Prometheus histogram metrics for true p95/p99 tracking.

Provides histogram instrumentation for:
- Latency measurements (mm_latency_ms)
- Risk ratio snapshots (mm_risk_ratio)

Thread-safe and designed to work alongside existing gauge metrics.
"""
from __future__ import annotations

import threading
from typing import Optional

# Try to import prometheus_client, fail gracefully if not available
try:
    from prometheus_client import Histogram, REGISTRY
    HAS_PROMETHEUS = True
except ImportError:
    HAS_PROMETHEUS = False
    Histogram = None
    REGISTRY = None


# Module-level histograms (singleton pattern)
_latency_histogram: Optional[Histogram] = None
_risk_histogram: Optional[Histogram] = None
_init_lock = threading.Lock()


def _ensure_histograms_initialized() -> None:
    """
    Initialize Prometheus histograms lazily (thread-safe).
    
    Only initializes once, even with multiple threads.
    """
    global _latency_histogram, _risk_histogram
    
    if not HAS_PROMETHEUS:
        return
    
    # Double-checked locking pattern
    if _latency_histogram is not None and _risk_histogram is not None:
        return
    
    with _init_lock:
        # Check again inside lock
        if _latency_histogram is not None and _risk_histogram is not None:
            return
        
        # Initialize latency histogram
        _latency_histogram = Histogram(
            'mm_latency_ms',
            'Latency per operation (milliseconds)',
            buckets=[5, 10, 20, 50, 100, 150, 200, 250, 300, 400, 600, 1000],
            registry=REGISTRY
        )
        
        # Initialize risk histogram  
        _risk_histogram = Histogram(
            'mm_risk_ratio',
            'Risk ratio snapshot (0.0-1.0)',
            buckets=[0.01, 0.05, 0.1, 0.2, 0.3, 0.4, 0.5, 0.7, 1.0],
            registry=REGISTRY
        )


def observe_latency_ms(value: float) -> None:
    """
    Record a latency observation in milliseconds.
    
    Args:
        value: Latency in milliseconds (non-negative)
        
    Example:
        >>> observe_latency_ms(125.3)
        >>> observe_latency_ms(89.5)
    """
    if not HAS_PROMETHEUS:
        return
    
    try:
        _ensure_histograms_initialized()
        if _latency_histogram is not None and value is not None:
            v = float(value)
            if v >= 0:
                _latency_histogram.observe(v)
    except Exception:
        # Never break on metrics
        pass


def observe_risk_ratio(value: float) -> None:
    """
    Record a risk ratio observation (0.0-1.0).
    
    Args:
        value: Risk ratio (0.0 = no risk, 1.0 = at limit)
        
    Example:
        >>> observe_risk_ratio(0.30)
        >>> observe_risk_ratio(0.45)
    """
    if not HAS_PROMETHEUS:
        return
    
    try:
        _ensure_histograms_initialized()
        if _risk_histogram is not None and value is not None:
            v = float(value)
            if 0.0 <= v <= 1.0:
                _risk_histogram.observe(v)
    except Exception:
        # Never break on metrics
        pass


def is_available() -> bool:
    """
    Check if Prometheus histograms are available.
    
    Returns:
        True if prometheus_client is installed and histograms initialized
    """
    return HAS_PROMETHEUS and _latency_histogram is not None and _risk_histogram is not None


def get_latency_histogram() -> Optional[Histogram]:
    """Get the latency histogram (for testing/inspection)."""
    _ensure_histograms_initialized()
    return _latency_histogram


def get_risk_histogram() -> Optional[Histogram]:
    """Get the risk histogram (for testing/inspection)."""
    _ensure_histograms_initialized()
    return _risk_histogram

