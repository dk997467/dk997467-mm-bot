"""
Prometheus-compatible metrics (stdlib-only).

Provides:
- Counter: Monotonically increasing counter
- Gauge: Value that can go up and down
- Histogram: Observations bucketed by value ranges

Renders metrics in Prometheus/OpenMetrics text format.
"""

from __future__ import annotations

import threading
from typing import Any


class Counter:
    """
    Counter metric (monotonically increasing).
    
    Thread-safe.
    """
    
    def __init__(self, name: str, help_text: str, labels: tuple[str, ...] = ()):
        """
        Initialize counter.
        
        Args:
            name: Metric name (e.g. "mm_orders_placed_total")
            help_text: Help text for metric
            labels: Label names (e.g. ("symbol",))
        """
        self.name = name
        self.help_text = help_text
        self.labels = labels
        self._values: dict[tuple[str, ...], float] = {}
        self._lock = threading.Lock()
    
    def inc(self, amount: float = 1.0, **label_values: str) -> None:
        """
        Increment counter.
        
        Args:
            amount: Amount to increment by (default 1.0)
            **label_values: Label values (must match self.labels)
        """
        label_key = self._make_label_key(label_values)
        with self._lock:
            self._values[label_key] = self._values.get(label_key, 0.0) + amount
    
    def get(self, **label_values: str) -> float:
        """Get current counter value."""
        label_key = self._make_label_key(label_values)
        with self._lock:
            return self._values.get(label_key, 0.0)
    
    def _make_label_key(self, label_values: dict[str, str]) -> tuple[str, ...]:
        """Convert label values dict to sorted tuple (for consistent hashing)."""
        if set(label_values.keys()) != set(self.labels):
            raise ValueError(f"Expected labels {self.labels}, got {list(label_values.keys())}")
        return tuple(label_values[label] for label in self.labels)
    
    def render(self) -> str:
        """Render metric in Prometheus text format."""
        lines = [
            f"# HELP {self.name} {self.help_text}",
            f"# TYPE {self.name} counter",
        ]
        
        with self._lock:
            # Sort by label values for determinism
            for label_key, value in sorted(self._values.items()):
                if self.labels:
                    label_str = ",".join(
                        f'{label}="{label_key[i]}"'
                        for i, label in enumerate(self.labels)
                    )
                    lines.append(f'{self.name}{{{label_str}}} {value}')
                else:
                    lines.append(f'{self.name} {value}')
        
        return "\n".join(lines) + "\n"


class Gauge:
    """
    Gauge metric (can go up or down).
    
    Thread-safe.
    """
    
    def __init__(self, name: str, help_text: str, labels: tuple[str, ...] = ()):
        """
        Initialize gauge.
        
        Args:
            name: Metric name (e.g. "mm_edge_bps")
            help_text: Help text for metric
            labels: Label names (e.g. ("symbol",))
        """
        self.name = name
        self.help_text = help_text
        self.labels = labels
        self._values: dict[tuple[str, ...], float] = {}
        self._lock = threading.Lock()
    
    def set(self, value: float, **label_values: str) -> None:
        """
        Set gauge value.
        
        Args:
            value: New value
            **label_values: Label values (must match self.labels)
        """
        label_key = self._make_label_key(label_values)
        with self._lock:
            self._values[label_key] = value
    
    def inc(self, amount: float = 1.0, **label_values: str) -> None:
        """Increment gauge by amount."""
        label_key = self._make_label_key(label_values)
        with self._lock:
            self._values[label_key] = self._values.get(label_key, 0.0) + amount
    
    def dec(self, amount: float = 1.0, **label_values: str) -> None:
        """Decrement gauge by amount."""
        self.inc(-amount, **label_values)
    
    def get(self, **label_values: str) -> float:
        """Get current gauge value."""
        label_key = self._make_label_key(label_values)
        with self._lock:
            return self._values.get(label_key, 0.0)
    
    def _make_label_key(self, label_values: dict[str, str]) -> tuple[str, ...]:
        """Convert label values dict to sorted tuple."""
        if set(label_values.keys()) != set(self.labels):
            raise ValueError(f"Expected labels {self.labels}, got {list(label_values.keys())}")
        return tuple(label_values[label] for label in self.labels)
    
    def render(self) -> str:
        """Render metric in Prometheus text format."""
        lines = [
            f"# HELP {self.name} {self.help_text}",
            f"# TYPE {self.name} gauge",
        ]
        
        with self._lock:
            # Sort by label values for determinism
            for label_key, value in sorted(self._values.items()):
                if self.labels:
                    label_str = ",".join(
                        f'{label}="{label_key[i]}"'
                        for i, label in enumerate(self.labels)
                    )
                    lines.append(f'{self.name}{{{label_str}}} {value}')
                else:
                    lines.append(f'{self.name} {value}')
        
        return "\n".join(lines) + "\n"


class Histogram:
    """
    Histogram metric (observations bucketed by value ranges).
    
    Thread-safe.
    """
    
    def __init__(
        self,
        name: str,
        help_text: str,
        buckets: tuple[float, ...],
        labels: tuple[str, ...] = (),
    ):
        """
        Initialize histogram.
        
        Args:
            name: Metric name (e.g. "mm_order_latency_ms")
            help_text: Help text for metric
            buckets: Bucket upper bounds (e.g. (1, 5, 10, 25, 50, 100, 250, 500))
            labels: Label names (e.g. ("symbol",))
        """
        self.name = name
        self.help_text = help_text
        self.buckets = tuple(sorted(buckets))  # Ensure sorted
        self.labels = labels
        
        # Storage: label_key -> {"sum": float, "count": int, "buckets": {le: count}}
        self._data: dict[tuple[str, ...], dict[str, Any]] = {}
        self._lock = threading.Lock()
    
    def observe(self, value: float, **label_values: str) -> None:
        """
        Observe a value (add to histogram).
        
        Args:
            value: Observed value
            **label_values: Label values (must match self.labels)
        """
        label_key = self._make_label_key(label_values)
        
        with self._lock:
            if label_key not in self._data:
                self._data[label_key] = {
                    "sum": 0.0,
                    "count": 0,
                    "buckets": {le: 0 for le in self.buckets},
                }
            
            data = self._data[label_key]
            data["sum"] += value
            data["count"] += 1
            
            # Increment bucket counts
            for le in self.buckets:
                if value <= le:
                    data["buckets"][le] += 1
    
    def get_count(self, **label_values: str) -> int:
        """Get total observation count."""
        label_key = self._make_label_key(label_values)
        with self._lock:
            if label_key not in self._data:
                return 0
            return self._data[label_key]["count"]
    
    def get_sum(self, **label_values: str) -> float:
        """Get sum of all observations."""
        label_key = self._make_label_key(label_values)
        with self._lock:
            if label_key not in self._data:
                return 0.0
            return self._data[label_key]["sum"]
    
    def _make_label_key(self, label_values: dict[str, str]) -> tuple[str, ...]:
        """Convert label values dict to sorted tuple."""
        if set(label_values.keys()) != set(self.labels):
            raise ValueError(f"Expected labels {self.labels}, got {list(label_values.keys())}")
        return tuple(label_values[label] for label in self.labels)
    
    def render(self) -> str:
        """Render metric in Prometheus text format."""
        lines = [
            f"# HELP {self.name} {self.help_text}",
            f"# TYPE {self.name} histogram",
        ]
        
        with self._lock:
            # Sort by label values for determinism
            for label_key, data in sorted(self._data.items()):
                # Build base label string
                if self.labels:
                    base_labels = ",".join(
                        f'{label}="{label_key[i]}"'
                        for i, label in enumerate(self.labels)
                    )
                else:
                    base_labels = ""
                
                # Render bucket counts
                for le in self.buckets:
                    count = data["buckets"][le]
                    if base_labels:
                        label_str = f'{base_labels},le="{le}"'
                    else:
                        label_str = f'le="{le}"'
                    lines.append(f'{self.name}_bucket{{{label_str}}} {count}')
                
                # Render +Inf bucket (cumulative count)
                if base_labels:
                    label_str = f'{base_labels},le="+Inf"'
                else:
                    label_str = 'le="+Inf"'
                lines.append(f'{self.name}_bucket{{{label_str}}} {data["count"]}')
                
                # Render sum and count
                if base_labels:
                    lines.append(f'{self.name}_sum{{{base_labels}}} {data["sum"]}')
                    lines.append(f'{self.name}_count{{{base_labels}}} {data["count"]}')
                else:
                    lines.append(f'{self.name}_sum {data["sum"]}')
                    lines.append(f'{self.name}_count {data["count"]}')
        
        return "\n".join(lines) + "\n"


class MetricsRegistry:
    """
    Global metrics registry.
    
    Thread-safe.
    """
    
    def __init__(self):
        """Initialize empty registry."""
        self._metrics: dict[str, Counter | Gauge | Histogram] = {}
        self._lock = threading.Lock()
    
    def register_counter(
        self,
        name: str,
        help_text: str,
        labels: tuple[str, ...] = (),
    ) -> Counter:
        """Register and return a new counter."""
        with self._lock:
            if name in self._metrics:
                raise ValueError(f"Metric {name} already registered")
            counter = Counter(name, help_text, labels)
            self._metrics[name] = counter
            return counter
    
    def register_gauge(
        self,
        name: str,
        help_text: str,
        labels: tuple[str, ...] = (),
    ) -> Gauge:
        """Register and return a new gauge."""
        with self._lock:
            if name in self._metrics:
                raise ValueError(f"Metric {name} already registered")
            gauge = Gauge(name, help_text, labels)
            self._metrics[name] = gauge
            return gauge
    
    def register_histogram(
        self,
        name: str,
        help_text: str,
        buckets: tuple[float, ...],
        labels: tuple[str, ...] = (),
    ) -> Histogram:
        """Register and return a new histogram."""
        with self._lock:
            if name in self._metrics:
                raise ValueError(f"Metric {name} already registered")
            histogram = Histogram(name, help_text, buckets, labels)
            self._metrics[name] = histogram
            return histogram
    
    def get(self, name: str) -> Counter | Gauge | Histogram:
        """Get registered metric by name."""
        with self._lock:
            if name not in self._metrics:
                raise KeyError(f"Metric {name} not registered")
            return self._metrics[name]
    
    def render_prometheus(self) -> str:
        """
        Render all metrics in Prometheus text format.
        
        Metrics are sorted by name for determinism.
        """
        with self._lock:
            # Sort metrics by name for determinism
            sorted_metrics = sorted(self._metrics.items())
        
        lines = []
        for name, metric in sorted_metrics:
            lines.append(metric.render())
        
        return "".join(lines)


# Global registry
_REGISTRY = MetricsRegistry()


def get_registry() -> MetricsRegistry:
    """Get global metrics registry."""
    return _REGISTRY


def render_prometheus() -> str:
    """Render all registered metrics in Prometheus text format."""
    # Sync freeze events from live metrics (if available)
    try:
        from tools.live import metrics as live_metrics
        freeze_count = live_metrics.get_freeze_events_total()
        # Set the value directly in the counter (no labels, so key is empty tuple)
        if hasattr(FREEZE_EVENTS, "_values") and hasattr(FREEZE_EVENTS, "_lock"):
            with FREEZE_EVENTS._lock:
                FREEZE_EVENTS._values[()] = float(freeze_count)
    except Exception:
        pass  # Don't break if live metrics unavailable
    
    return _REGISTRY.render_prometheus()


# Pre-register standard MM-Bot metrics
ORDERS_PLACED = _REGISTRY.register_counter(
    "mm_orders_placed_total",
    "Total number of orders placed",
    labels=("symbol",),
)

ORDERS_FILLED = _REGISTRY.register_counter(
    "mm_orders_filled_total",
    "Total number of orders filled",
    labels=("symbol",),
)

ORDERS_REJECTED = _REGISTRY.register_counter(
    "mm_orders_rejected_total",
    "Total number of orders rejected",
    labels=("symbol",),
)

ORDER_LATENCY = _REGISTRY.register_histogram(
    "mm_order_latency_ms",
    "Order placement latency in milliseconds",
    buckets=(1, 5, 10, 25, 50, 100, 250, 500),
    labels=("symbol",),
)

EDGE_BPS = _REGISTRY.register_gauge(
    "mm_edge_bps",
    "Current edge in basis points",
    labels=("symbol",),
)

RISK_RATIO = _REGISTRY.register_gauge(
    "mm_risk_ratio",
    "Current risk ratio (inventory / max_inventory)",
    labels=(),
)

FREEZE_EVENTS = _REGISTRY.register_counter(
    "mm_freeze_events_total",
    "Total number of freeze events triggered",
    labels=(),
)

# P0.3 Live-prep metrics
ORDERS_BLOCKED = _REGISTRY.register_counter(
    "mm_orders_blocked_total",
    "Total number of orders blocked before placement",
    labels=("symbol", "reason"),
)

POST_ONLY_ADJUSTMENTS = _REGISTRY.register_counter(
    "mm_post_only_adjustments_total",
    "Total number of post-only price adjustments applied",
    labels=("symbol", "side"),
)

MAKER_ONLY_ENABLED = _REGISTRY.register_gauge(
    "mm_maker_only_enabled",
    "Maker-only mode enabled (1=yes, 0=no)",
    labels=(),
)

# P0.10 Testnet Soak & Canary metrics
RECON_DIVERGENCE = _REGISTRY.register_counter(
    "mm_recon_divergence_total",
    "Total number of reconciliation divergences detected",
    labels=("type",),
)

MAKER_TAKER_RATIO = _REGISTRY.register_gauge(
    "mm_maker_taker_ratio",
    "Ratio of maker to total notional (0-1)",
    labels=(),
)

NET_BPS = _REGISTRY.register_gauge(
    "mm_net_bps",
    "Net trading cost in basis points (fees - rebates)",
    labels=(),
)

LIVE_ENABLE = _REGISTRY.register_gauge(
    "mm_live_enable",
    "Live trading mode enabled (1=yes, 0=no)",
    labels=(),
)

SYMBOL_FILTERS_SOURCE = _REGISTRY.register_counter(
    "mm_symbol_filters_source_total",
    "Symbol filters fetch source",
    labels=("source",),
)

SYMBOL_FILTERS_FETCH_ERRORS = _REGISTRY.register_counter(
    "mm_symbol_filters_fetch_errors_total",
    "Total number of symbol filters fetch errors",
    labels=(),
)

