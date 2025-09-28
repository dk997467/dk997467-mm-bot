"""
Low-cardinality Position Skew metrics writer (stdlib-only).

This module does not depend on any external metrics library. It interacts with
an optional "registry" object that is expected to expose attributes compatible
with Prometheus-like counters/gauges (i.e., .inc() and .set()). All operations
are best-effort and safely no-op if metrics are absent.
"""

from typing import Dict, Iterable, Optional
import time


class PositionSkewMetricsWriter:
    """Writer for low-cardinality position skew metrics and compact snapshot.

    API:
      - __init__(registry)
      - on_breach(symbol_breach: Iterable[str], color_breach: bool)
      - snapshot(positions_by_symbol: Dict[str, float]) -> Dict[str, float]
    """

    def __init__(self, registry: Optional[object] = None) -> None:
        self._r = registry
        # Internal last state (best-effort)
        self._last_ts: float = 0.0
        self._last_symbol_breach_count: int = 0
        self._last_color_breach: int = 0

    # --- helpers (best-effort; tolerate missing registry/metrics) ---
    def _inc_counter(self, name: str) -> None:
        try:
            c = getattr(self._r, name, None)
            if c is not None:
                c.inc()  # type: ignore[attr-defined]
        except Exception:
            pass

    def _set_gauge(self, name: str, value: float) -> None:
        try:
            g = getattr(self._r, name, None)
            if g is not None:
                g.set(float(value))  # type: ignore[attr-defined]
        except Exception:
            pass

    # --- public API ---
    def on_breach(self, symbol_breach: Iterable[str], color_breach: bool) -> None:
        """Record a skew breach event with low-cardinality metrics.

        - pos_skew_breach_total++
        - pos_skew_last_ts = now
        - pos_skew_symbol_breach_count = len(unique(symbol_breach))
        - pos_skew_color_breach = 1/0
        """
        try:
            sb = set(symbol_breach or [])
        except Exception:
            sb = set()
        count = int(len(sb))
        now_ts = time.time()

        # Metrics (best-effort)
        self._inc_counter('pos_skew_breach_total')
        self._set_gauge('pos_skew_last_ts', now_ts)
        self._set_gauge('pos_skew_symbol_breach_count', float(count))
        self._set_gauge('pos_skew_color_breach', 1.0 if color_breach else 0.0)

        # Internal snapshot
        self._last_ts = float(now_ts)
        self._last_symbol_breach_count = int(count)
        self._last_color_breach = 1 if bool(color_breach) else 0

    def snapshot(self, positions_by_symbol: Dict[str, float]) -> Dict[str, float]:
        """Return a compact deterministic copy of positions_by_symbol.

        The snapshot is a simple mapping symbol->float value. Construction is
        deterministic via sorted symbol order. This is intended for artifacts
        export (e.g., artifacts/metrics.json) and is separate from metrics.
        """
        try:
            items = list(positions_by_symbol.items()) if isinstance(positions_by_symbol, dict) else []
        except Exception:
            items = []
        # Deterministic by symbol name
        items.sort(key=lambda kv: str(kv[0]))
        out: Dict[str, float] = {}
        for sym, val in items:
            try:
                s = str(sym)
            except Exception:
                s = f"{sym}"
            try:
                out[s] = float(val)
            except Exception:
                # If value cannot be coerced, set 0.0 to keep deterministic keys
                out[s] = 0.0
        return out


