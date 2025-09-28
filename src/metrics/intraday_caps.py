"""
Intraday Caps metrics writer (stdlib-only).
"""

from typing import Dict, Optional


class IntradayCapsMetricsWriter:
    def __init__(self, registry: Optional[object] = None) -> None:
        self._r = registry
        self._last_pnl: float = 0.0
        self._last_turnover: float = 0.0
        self._last_vol: float = 0.0
        self._last_breached: int = 0

    def on_update(self, pnl: float, turnover: float, vol: float, breached: bool) -> None:
        # Update internal snapshot deterministically
        try:
            self._last_pnl = float(pnl)
            self._last_turnover = float(turnover)
            self._last_vol = float(vol)
            self._last_breached = 1 if breached else 0
        except Exception:
            # Keep previous values if casting fails
            pass
        # Best-effort push to registry if provided
        try:
            if self._r is None:
                return
            if hasattr(self._r, 'intraday_caps_pnl'):
                self._r.intraday_caps_pnl.set(self._last_pnl)
            if hasattr(self._r, 'intraday_caps_turnover'):
                self._r.intraday_caps_turnover.set(self._last_turnover)
            if hasattr(self._r, 'intraday_caps_vol'):
                self._r.intraday_caps_vol.set(self._last_vol)
            if hasattr(self._r, 'intraday_caps_breached'):
                self._r.intraday_caps_breached.set(self._last_breached)
        except Exception:
            pass

    def snapshot(self) -> Dict[str, float]:
        return {
            'pnl': float(self._last_pnl),
            'turnover': float(self._last_turnover),
            'vol': float(self._last_vol),
            'breached': int(self._last_breached),
        }


