"""
Live Execution Metrics — Prometheus metrics for order execution.

Metrics:
- orders_placed_total: Counter of orders placed
- orders_filled_total: Counter of orders fully filled
- orders_partially_filled_total: Counter of orders partially filled
- orders_rejected_total: Counter of orders rejected
- orders_canceled_total: Counter of orders canceled
- order_latency_seconds: Histogram of order placement latency
- fill_latency_seconds: Histogram of time from order to fill
- order_retry_count: Histogram of retry attempts per order
- position_qty: Gauge of current position quantity per symbol
- position_pnl: Gauge of position P&L per symbol

Usage:
    # Initialize metrics
    metrics = LiveExecutionMetrics()
    
    # Track order placement
    with metrics.track_order_latency():
        response = client.place_order(...)
        metrics.increment_orders_placed(response.symbol, response.side)
    
    # Track fill
    metrics.increment_orders_filled(fill.symbol, fill.side)
    metrics.observe_fill_latency(fill.symbol, latency_seconds)
    
    # Export to Prometheus
    prom_text = metrics.export_prometheus()
    Path("metrics.prom").write_text(prom_text)
"""

from __future__ import annotations

import time
import logging
from typing import Dict, Optional, Literal
from dataclasses import dataclass, field
from contextlib import contextmanager
from datetime import datetime, timezone

logger = logging.getLogger(__name__)


@dataclass
class CounterMetric:
    """Counter metric (monotonically increasing)."""
    
    name: str
    help_text: str
    labels: Dict[str, str] = field(default_factory=dict)
    value: int = 0
    
    def increment(self, amount: int = 1) -> None:
        """Increment counter."""
        self.value += amount
    
    def to_prometheus(self) -> str:
        """Format as Prometheus metric."""
        label_str = ",".join(f'{k}="{v}"' for k, v in sorted(self.labels.items()))
        if label_str:
            return f"{self.name}{{{label_str}}} {self.value}"
        else:
            return f"{self.name} {self.value}"


@dataclass
class GaugeMetric:
    """Gauge metric (can go up or down)."""
    
    name: str
    help_text: str
    labels: Dict[str, str] = field(default_factory=dict)
    value: float = 0.0
    
    def set(self, value: float) -> None:
        """Set gauge value."""
        self.value = value
    
    def to_prometheus(self) -> str:
        """Format as Prometheus metric."""
        label_str = ",".join(f'{k}="{v}"' for k, v in sorted(self.labels.items()))
        if label_str:
            return f"{self.name}{{{label_str}}} {self.value}"
        else:
            return f"{self.name} {self.value}"


@dataclass
class HistogramMetric:
    """Histogram metric (distribution of observations)."""
    
    name: str
    help_text: str
    labels: Dict[str, str] = field(default_factory=dict)
    buckets: list[float] = field(default_factory=lambda: [0.001, 0.005, 0.01, 0.05, 0.1, 0.5, 1.0, 5.0, 10.0])
    observations: list[float] = field(default_factory=list)
    sum: float = 0.0
    count: int = 0
    
    def observe(self, value: float) -> None:
        """Add observation."""
        self.observations.append(value)
        self.sum += value
        self.count += 1
    
    def to_prometheus(self) -> list[str]:
        """Format as Prometheus histogram."""
        lines = []
        label_str = ",".join(f'{k}="{v}"' for k, v in sorted(self.labels.items()))
        
        # Bucket counts
        for bucket in self.buckets:
            count = sum(1 for obs in self.observations if obs <= bucket)
            le_label = f'le="{bucket}"'
            if label_str:
                full_label = f"{label_str},{le_label}"
            else:
                full_label = le_label
            lines.append(f"{self.name}_bucket{{{full_label}}} {count}")
        
        # +Inf bucket
        le_label = 'le="+Inf"'
        if label_str:
            full_label = f"{label_str},{le_label}"
        else:
            full_label = le_label
        lines.append(f"{self.name}_bucket{{{full_label}}} {self.count}")
        
        # Sum and count
        if label_str:
            lines.append(f"{self.name}_sum{{{label_str}}} {self.sum}")
            lines.append(f"{self.name}_count{{{label_str}}} {self.count}")
        else:
            lines.append(f"{self.name}_sum {self.sum}")
            lines.append(f"{self.name}_count {self.count}")
        
        return lines


class LiveExecutionMetrics:
    """
    Prometheus metrics collector for live execution engine.
    
    Tracks:
    - Order placement/fill/reject/cancel counts
    - Order and fill latencies
    - Retry counts
    - Position quantities and P&L
    
    Thread-safety: Not thread-safe. Use locks if accessing from multiple threads.
    """
    
    def __init__(self):
        """Initialize metrics collector."""
        # Counters
        self._orders_placed: Dict[tuple, CounterMetric] = {}
        self._orders_filled: Dict[tuple, CounterMetric] = {}
        self._orders_partially_filled: Dict[tuple, CounterMetric] = {}
        self._orders_rejected: Dict[tuple, CounterMetric] = {}
        self._orders_canceled: Dict[tuple, CounterMetric] = {}
        self._freeze_triggered: Dict[tuple, CounterMetric] = {}
        
        # Histograms
        self._order_latency: Dict[tuple, HistogramMetric] = {}
        self._fill_latency: Dict[tuple, HistogramMetric] = {}
        self._retry_count: Dict[tuple, HistogramMetric] = {}
        
        # Gauges
        self._position_qty: Dict[tuple, GaugeMetric] = {}
        self._position_pnl: Dict[tuple, GaugeMetric] = {}
        
        logger.info("LiveExecutionMetrics initialized")
    
    # ========================================================================
    # Counter Methods
    # ========================================================================
    
    def increment_orders_placed(self, symbol: str, side: str) -> None:
        """Increment orders_placed_total counter."""
        key = (symbol, side)
        if key not in self._orders_placed:
            self._orders_placed[key] = CounterMetric(
                name="orders_placed_total",
                help_text="Total orders placed",
                labels={"symbol": symbol, "side": side},
            )
        self._orders_placed[key].increment()
    
    def increment_orders_filled(self, symbol: str, side: str) -> None:
        """Increment orders_filled_total counter."""
        key = (symbol, side)
        if key not in self._orders_filled:
            self._orders_filled[key] = CounterMetric(
                name="orders_filled_total",
                help_text="Total orders fully filled",
                labels={"symbol": symbol, "side": side},
            )
        self._orders_filled[key].increment()
    
    def increment_orders_partially_filled(self, symbol: str, side: str) -> None:
        """Increment orders_partially_filled_total counter."""
        key = (symbol, side)
        if key not in self._orders_partially_filled:
            self._orders_partially_filled[key] = CounterMetric(
                name="orders_partially_filled_total",
                help_text="Total orders partially filled",
                labels={"symbol": symbol, "side": side},
            )
        self._orders_partially_filled[key].increment()
    
    def increment_orders_rejected(self, symbol: str, side: str, reason: str = "unknown") -> None:
        """Increment orders_rejected_total counter."""
        key = (symbol, side, reason)
        if key not in self._orders_rejected:
            self._orders_rejected[key] = CounterMetric(
                name="orders_rejected_total",
                help_text="Total orders rejected",
                labels={"symbol": symbol, "side": side, "reason": reason},
            )
        self._orders_rejected[key].increment()
    
    def increment_orders_canceled(self, symbol: str, side: str) -> None:
        """Increment orders_canceled_total counter."""
        key = (symbol, side)
        if key not in self._orders_canceled:
            self._orders_canceled[key] = CounterMetric(
                name="orders_canceled_total",
                help_text="Total orders canceled",
                labels={"symbol": symbol, "side": side},
            )
        self._orders_canceled[key].increment()
    
    def increment_freeze_triggered(self, reason: str = "edge_collapse") -> None:
        """Increment freeze_triggered_total counter."""
        key = (reason,)
        if key not in self._freeze_triggered:
            self._freeze_triggered[key] = CounterMetric(
                name="freeze_triggered_total",
                help_text="Total system freezes triggered",
                labels={"reason": reason},
            )
        self._freeze_triggered[key].increment()
    
    # ========================================================================
    # Histogram Methods
    # ========================================================================
    
    def observe_order_latency(self, symbol: str, latency_seconds: float) -> None:
        """Observe order placement latency."""
        key = (symbol,)
        if key not in self._order_latency:
            self._order_latency[key] = HistogramMetric(
                name="order_latency_seconds",
                help_text="Order placement latency in seconds",
                labels={"symbol": symbol},
            )
        self._order_latency[key].observe(latency_seconds)
    
    def observe_fill_latency(self, symbol: str, latency_seconds: float) -> None:
        """Observe fill latency (time from order to fill)."""
        key = (symbol,)
        if key not in self._fill_latency:
            self._fill_latency[key] = HistogramMetric(
                name="fill_latency_seconds",
                help_text="Fill latency (order to fill) in seconds",
                labels={"symbol": symbol},
            )
        self._fill_latency[key].observe(latency_seconds)
    
    def observe_retry_count(self, symbol: str, retry_count: int) -> None:
        """Observe retry count for order placement."""
        key = (symbol,)
        if key not in self._retry_count:
            self._retry_count[key] = HistogramMetric(
                name="order_retry_count",
                help_text="Retry attempts per order",
                labels={"symbol": symbol},
                buckets=[0, 1, 2, 3, 4, 5, 10],
            )
        self._retry_count[key].observe(float(retry_count))
    
    # ========================================================================
    # Gauge Methods
    # ========================================================================
    
    def set_position_qty(self, symbol: str, qty: float) -> None:
        """Set position quantity gauge."""
        key = (symbol,)
        if key not in self._position_qty:
            self._position_qty[key] = GaugeMetric(
                name="position_qty",
                help_text="Current position quantity",
                labels={"symbol": symbol},
            )
        self._position_qty[key].set(qty)
    
    def set_position_pnl(self, symbol: str, pnl: float) -> None:
        """Set position P&L gauge."""
        key = (symbol,)
        if key not in self._position_pnl:
            self._position_pnl[key] = GaugeMetric(
                name="position_pnl",
                help_text="Position P&L (realized + unrealized)",
                labels={"symbol": symbol},
            )
        self._position_pnl[key].set(pnl)
    
    # ========================================================================
    # Context Managers
    # ========================================================================
    
    @contextmanager
    def track_order_latency(self, symbol: str):
        """Context manager to track order placement latency."""
        start_time = time.perf_counter()
        try:
            yield
        finally:
            latency_seconds = time.perf_counter() - start_time
            self.observe_order_latency(symbol, latency_seconds)
    
    # ========================================================================
    # Export
    # ========================================================================
    
    def export_prometheus(self) -> str:
        """
        Export all metrics in Prometheus text format.
        
        Returns:
            Metrics in Prometheus exposition format
        """
        lines = []
        
        # Header
        lines.append(f"# Generated: {datetime.now(timezone.utc).isoformat()}")
        lines.append("# Live Execution Metrics")
        lines.append("")
        
        # Counters
        if self._orders_placed:
            lines.append("# HELP orders_placed_total Total orders placed")
            lines.append("# TYPE orders_placed_total counter")
            for metric in self._orders_placed.values():
                lines.append(metric.to_prometheus())
            lines.append("")
        
        if self._orders_filled:
            lines.append("# HELP orders_filled_total Total orders fully filled")
            lines.append("# TYPE orders_filled_total counter")
            for metric in self._orders_filled.values():
                lines.append(metric.to_prometheus())
            lines.append("")
        
        if self._orders_partially_filled:
            lines.append("# HELP orders_partially_filled_total Total orders partially filled")
            lines.append("# TYPE orders_partially_filled_total counter")
            for metric in self._orders_partially_filled.values():
                lines.append(metric.to_prometheus())
            lines.append("")
        
        if self._orders_rejected:
            lines.append("# HELP orders_rejected_total Total orders rejected")
            lines.append("# TYPE orders_rejected_total counter")
            for metric in self._orders_rejected.values():
                lines.append(metric.to_prometheus())
            lines.append("")
        
        if self._orders_canceled:
            lines.append("# HELP orders_canceled_total Total orders canceled")
            lines.append("# TYPE orders_canceled_total counter")
            for metric in self._orders_canceled.values():
                lines.append(metric.to_prometheus())
            lines.append("")
        
        if self._freeze_triggered:
            lines.append("# HELP freeze_triggered_total Total system freezes triggered")
            lines.append("# TYPE freeze_triggered_total counter")
            for metric in self._freeze_triggered.values():
                lines.append(metric.to_prometheus())
            lines.append("")
        
        # Histograms
        if self._order_latency:
            lines.append("# HELP order_latency_seconds Order placement latency in seconds")
            lines.append("# TYPE order_latency_seconds histogram")
            for metric in self._order_latency.values():
                lines.extend(metric.to_prometheus())
            lines.append("")
        
        if self._fill_latency:
            lines.append("# HELP fill_latency_seconds Fill latency (order to fill) in seconds")
            lines.append("# TYPE fill_latency_seconds histogram")
            for metric in self._fill_latency.values():
                lines.extend(metric.to_prometheus())
            lines.append("")
        
        if self._retry_count:
            lines.append("# HELP order_retry_count Retry attempts per order")
            lines.append("# TYPE order_retry_count histogram")
            for metric in self._retry_count.values():
                lines.extend(metric.to_prometheus())
            lines.append("")
        
        # Gauges
        if self._position_qty:
            lines.append("# HELP position_qty Current position quantity")
            lines.append("# TYPE position_qty gauge")
            for metric in self._position_qty.values():
                lines.append(metric.to_prometheus())
            lines.append("")
        
        if self._position_pnl:
            lines.append("# HELP position_pnl Position P&L (realized + unrealized)")
            lines.append("# TYPE position_pnl gauge")
            for metric in self._position_pnl.values():
                lines.append(metric.to_prometheus())
            lines.append("")
        
        return "\n".join(lines)
    
    def reset(self) -> None:
        """Reset all metrics (for testing)."""
        self._orders_placed.clear()
        self._orders_filled.clear()
        self._orders_partially_filled.clear()
        self._orders_rejected.clear()
        self._orders_canceled.clear()
        self._freeze_triggered.clear()
        self._order_latency.clear()
        self._fill_latency.clear()
        self._retry_count.clear()
        self._position_qty.clear()
        self._position_pnl.clear()
        logger.warning("All metrics reset")


# Global metrics instance (singleton pattern for convenience)
_global_metrics: Optional[LiveExecutionMetrics] = None


def get_global_metrics() -> LiveExecutionMetrics:
    """
    Get global metrics instance (singleton).
    
    Returns:
        LiveExecutionMetrics instance
    """
    global _global_metrics
    if _global_metrics is None:
        _global_metrics = LiveExecutionMetrics()
    return _global_metrics


def reset_global_metrics() -> None:
    """Reset global metrics instance."""
    global _global_metrics
    _global_metrics = None

