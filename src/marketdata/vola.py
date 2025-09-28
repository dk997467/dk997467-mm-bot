"""
EWMA volatility calculation for portfolio allocation.
"""

import time
from typing import Dict, Optional
from dataclasses import dataclass, field

from src.metrics.exporter import Metrics


@dataclass
class VolatilityTracker:
    """Tracks EWMA volatility for symbols."""
    
    symbol: str
    alpha: float = 0.3
    min_samples: int = 10
    _ewma: Optional[float] = None
    _last_price: Optional[float] = None
    _last_update_ts: float = 0.0
    _sample_count: int = 0
    
    def update(self, mid_price: float, timestamp: float) -> float:
        """Update EWMA volatility with guards (valid mid>0, monotonic ts)."""
        try:
            mp = float(mid_price)
            ts = float(timestamp)
        except Exception:
            return float(self._ewma or 0.0)

        if mp <= 0:
            return float(self._ewma or 0.0)

        if self._last_update_ts and ts < self._last_update_ts:
            return float(self._ewma or 0.0)

        if self._last_price is None:
            self._ewma = 0.0
            self._last_price = mp
            self._last_update_ts = ts
            self._sample_count = 1
            return float(self._ewma)

        # Calculate return
        if self._last_price > 0:
            ret = (mp - self._last_price) / self._last_price
        else:
            ret = 0.0

        # Update EWMA volatility
        if self._ewma is None:
            self._ewma = abs(ret)
        else:
            self._ewma = self.alpha * abs(ret) + (1 - self.alpha) * self._ewma
        
        # Update state
        self._last_price = mp
        self._last_update_ts = ts
        self._sample_count += 1
        
        return float(self._ewma)
    
    @property
    def volatility(self) -> float:
        """Get current volatility estimate."""
        if self._ewma is None or self._sample_count < self.min_samples:
            return 0.0
        return self._ewma
    
    @property
    def is_ready(self) -> bool:
        """Check if volatility estimate is ready."""
        return self._sample_count >= self.min_samples


class VolatilityManager:
    """Manages volatility tracking for multiple symbols."""
    
    def __init__(self, alpha: float = 0.3, min_samples: int = 10):
        """Initialize volatility manager."""
        self.alpha = alpha
        self.min_samples = min_samples
        self.trackers: Dict[str, VolatilityTracker] = {}
        self.metrics: Optional[Metrics] = None
    
    def set_metrics(self, metrics: Metrics):
        """Set metrics exporter for volatility gauges."""
        self.metrics = metrics
    
    def get_or_create_tracker(self, symbol: str) -> VolatilityTracker:
        """Get existing tracker or create new one for symbol."""
        if symbol not in self.trackers:
            self.trackers[symbol] = VolatilityTracker(
                symbol=symbol,
                alpha=self.alpha,
                min_samples=self.min_samples
            )
        return self.trackers[symbol]
    
    def update(self, symbol: str, mid_price: float, timestamp: Optional[float] = None) -> float:
        """Update volatility for symbol and return current estimate."""
        if timestamp is None:
            timestamp = time.time()
        
        tracker = self.get_or_create_tracker(symbol)
        vol = tracker.update(mid_price, timestamp)
        
        # Update metrics if available
        if self.metrics:
            self.metrics.vola_ewma.labels(symbol=symbol).set(float(vol))
        
        return float(vol)
    
    def get_volatility(self, symbol: str) -> float:
        """Get current volatility estimate for symbol."""
        if symbol not in self.trackers:
            return 0.0
        return float(self.trackers[symbol].volatility)
    
    def get_all_volatilities(self) -> Dict[str, float]:
        """Get volatility estimates for all tracked symbols."""
        return {sym: tracker.volatility for sym, tracker in self.trackers.items()}
    
    def is_ready(self, symbol: str) -> bool:
        """Check if volatility estimate is ready for symbol."""
        if symbol not in self.trackers:
            return False
        return self.trackers[symbol].is_ready
