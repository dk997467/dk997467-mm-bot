"""
Latency collector for p95/p99 tracking.

Records per-operation latencies and computes percentiles on demand.
Also exports to Prometheus histograms for true p95/p99 computation.
"""
from __future__ import annotations

from typing import List
import math

# Import histogram support (optional dependency)
try:
    from tools.live import prometheus_histograms
except ImportError:
    prometheus_histograms = None


class LatencyCollector:
    """
    Collector for recording latency samples and computing percentiles.
    
    Usage:
        >>> collector = LatencyCollector()
        >>> collector.record_ms(125.3)
        >>> collector.record_ms(89.1)
        >>> collector.record_ms(156.7)
        >>> collector.p95()
        156.7
    """
    
    def __init__(self) -> None:
        """Initialize collector with empty sample list."""
        self._samples_ms: List[float] = []
    
    def record_ms(self, value: float) -> None:
        """
        Record a latency sample in milliseconds.
        
        Also exports to Prometheus histogram if available.
        
        Args:
            value: Latency in milliseconds (non-negative)
        """
        if value is None:
            return
        try:
            v = float(value)
            if v >= 0:
                self._samples_ms.append(v)
                
                # Export to Prometheus histogram
                if prometheus_histograms is not None:
                    prometheus_histograms.observe_latency_ms(v)
        except Exception:
            pass
    
    def p95(self) -> float:
        """
        Compute 95th percentile of recorded samples.
        
        Returns:
            95th percentile latency in milliseconds (0.0 if no samples)
        """
        if not self._samples_ms:
            return 0.0
        xs = sorted(self._samples_ms)
        k = max(0, int(math.ceil(0.95 * len(xs)) - 1))
        return float(xs[k])
    
    def p99(self) -> float:
        """
        Compute 99th percentile of recorded samples.
        
        Returns:
            99th percentile latency in milliseconds (0.0 if no samples)
        """
        if not self._samples_ms:
            return 0.0
        xs = sorted(self._samples_ms)
        k = max(0, int(math.ceil(0.99 * len(xs)) - 1))
        return float(xs[k])
    
    def count(self) -> int:
        """Return number of samples recorded."""
        return len(self._samples_ms)
    
    def clear(self) -> None:
        """Clear all samples."""
        self._samples_ms.clear()

