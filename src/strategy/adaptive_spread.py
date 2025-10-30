"""
Adaptive Spread Estimator.

Dynamically adjusts spread based on:
- Volatility (EMA of mid-price changes)
- Liquidity (orderbook depth)
- Latency (p95 from ring buffer)
- PnL deviation (rolling z-score)
"""

import math
import time
from collections import deque
from typing import Dict, Optional

from src.common.config import AdaptiveSpreadConfig


class AdaptiveSpreadEstimator:
    """
    Estimates adaptive spread based on market conditions.
    
    Formula:
        score = vol_weight*vol + liq_weight*liq + lat_weight*lat + pnl_weight*pnl
        target_spread = base_spread * (1 + score)
        final = clamp(smooth(target), min, max)
    """
    
    def __init__(self, cfg: AdaptiveSpreadConfig):
        self.cfg = cfg
        
        # State
        self.last_spread_bps = cfg.base_spread_bps
        self.last_mid: Optional[float] = None
        self.last_ts_ms: Optional[int] = None
        self.last_change_ts_ms: Optional[int] = None
        
        # Volatility tracking (EMA)
        self.vol_ema_bps: float = 0.0
        self.vol_ema_alpha: float = 2.0 / (cfg.vol_window_sec + 1)  # EMA smoothing
        
        # PnL tracking (rolling window for z-score)
        self.pnl_window: deque = deque(maxlen=60)  # Keep 1 hour of samples
        self.pnl_sum: float = 0.0
        self.pnl_sq_sum: float = 0.0
        
        # Latency samples (ring buffer for p95)
        self.latency_samples: deque = deque(maxlen=100)
        
        # Metrics
        self.metrics: Dict[str, float] = {
            'vol_score': 0.0,
            'liq_score': 0.0,
            'lat_score': 0.0,
            'pnl_score': 0.0,
            'total_score': 0.0,
            'target_spread_bps': cfg.base_spread_bps,
            'final_spread_bps': cfg.base_spread_bps,
        }
    
    def update_mid(self, mid: float, ts_ms: int) -> None:
        """
        Update mid-price and compute volatility.
        
        Args:
            mid: Current mid-price
            ts_ms: Timestamp in milliseconds
        """
        if self.last_mid is not None and self.last_ts_ms is not None:
            dt_sec = max(0.001, (ts_ms - self.last_ts_ms) / 1000.0)
            
            # Compute price change in bps
            price_change_bps = abs((mid - self.last_mid) / self.last_mid) * 10000.0
            
            # Update EMA volatility
            self.vol_ema_bps = (
                self.vol_ema_alpha * price_change_bps +
                (1 - self.vol_ema_alpha) * self.vol_ema_bps
            )
        
        self.last_mid = mid
        self.last_ts_ms = ts_ms
    
    def update_pnl(self, pnl_delta: float) -> None:
        """
        Update PnL rolling window for z-score computation.
        
        Args:
            pnl_delta: PnL change (positive or negative)
        """
        # Remove oldest sample if window is full
        if len(self.pnl_window) == self.pnl_window.maxlen:
            oldest = self.pnl_window[0]
            self.pnl_sum -= oldest
            self.pnl_sq_sum -= oldest * oldest
        
        # Add new sample
        self.pnl_window.append(pnl_delta)
        self.pnl_sum += pnl_delta
        self.pnl_sq_sum += pnl_delta * pnl_delta
    
    def update_latency(self, sample_ms: float) -> None:
        """
        Update latency sample ring buffer.
        
        Args:
            sample_ms: Latency sample in milliseconds
        """
        self.latency_samples.append(sample_ms)
    
    def compute_spread_bps(
        self,
        liquidity_bid: float = 10.0,
        liquidity_ask: float = 10.0,
        now_ms: Optional[int] = None,
    ) -> float:
        """
        Compute adaptive spread in bps.
        
        Args:
            liquidity_bid: Total volume in top N bid levels
            liquidity_ask: Total volume in top N ask levels
            now_ms: Current timestamp (for cooloff)
        
        Returns:
            Adaptive spread in bps
        """
        if now_ms is None:
            now_ms = int(time.time() * 1000)
        
        if not self.cfg.enabled:
            return self.cfg.base_spread_bps
        
        # Compute individual scores (0..1 range)
        vol_score = self._compute_vol_score()
        liq_score = self._compute_liq_score(liquidity_bid, liquidity_ask)
        lat_score = self._compute_lat_score()
        pnl_score = self._compute_pnl_score()
        
        # Start with base spread
        spread = self.cfg.base_spread_bps
        
        # Add individual terms (additive, not multiplicative)
        spread += vol_score * self.cfg.vol_sensitivity * 1.5  # Up to +1.5 bps per 1.0 vol_score
        spread += liq_score * self.cfg.liquidity_sensitivity * 1.0  # Up to +1.0 bps per 1.0 liq_score
        spread += lat_score * self.cfg.latency_sensitivity * 0.8  # Up to +0.8 bps per 1.0 lat_score
        spread += pnl_score * self.cfg.pnl_dev_sensitivity * 1.2  # Up to +1.2 bps per 1.0 pnl_score
        
        # Compute total score for metrics
        total_score = (
            self.cfg.vol_sensitivity * vol_score +
            self.cfg.liquidity_sensitivity * liq_score +
            self.cfg.latency_sensitivity * lat_score +
            self.cfg.pnl_dev_sensitivity * pnl_score
        )
        
        # Hard clamp to min/max
        spread = max(self.cfg.min_spread_bps, min(self.cfg.max_spread_bps, spread))
        
        # Cooloff: if we just changed recently, don't change again
        if self.last_change_ts_ms is not None:
            cooloff_remaining_ms = self.cfg.cooloff_ms - (now_ms - self.last_change_ts_ms)
            if cooloff_remaining_ms > 0:
                # Still in cooloff, return previous spread
                spread = self.last_spread_bps
        
        # Apply step limit (smooth transitions) AFTER cooloff check
        delta = spread - self.last_spread_bps
        if abs(delta) > self.cfg.clamp_step_bps:
            spread = self.last_spread_bps + math.copysign(self.cfg.clamp_step_bps, delta)
        
        # Update state
        if abs(spread - self.last_spread_bps) > 0.001:
            self.last_change_ts_ms = now_ms
        elif self.last_change_ts_ms is None:
            # Initialize timestamp on first call
            self.last_change_ts_ms = now_ms
        
        self.last_spread_bps = spread
        
        # Update metrics
        self.metrics['vol_score'] = vol_score
        self.metrics['liq_score'] = liq_score
        self.metrics['lat_score'] = lat_score
        self.metrics['pnl_score'] = pnl_score
        self.metrics['total_score'] = total_score
        self.metrics['target_spread_bps'] = spread
        self.metrics['final_spread_bps'] = spread
        
        # Log
        self._log_computation()
        
        return spread
    
    def _compute_vol_score(self) -> float:
        """
        Compute volatility score (0..1).
        
        Logic:
            - If vol_ema <= soft threshold: 0.0
            - If vol_ema >= hard threshold: 1.0
            - Linear interpolation in between
        """
        # Lower thresholds to be more sensitive to volatility
        soft_bps = 0.5  # Very low threshold
        hard_bps = 5.0  # Moderate threshold
        
        if self.vol_ema_bps <= soft_bps:
            return 0.0
        elif self.vol_ema_bps >= hard_bps:
            return 1.0
        else:
            return (self.vol_ema_bps - soft_bps) / (hard_bps - soft_bps)
    
    def _compute_liq_score(self, liquidity_bid: float, liquidity_ask: float) -> float:
        """
        Compute liquidity score (0..1).
        
        Logic:
            - Higher liquidity → lower score (tighter spread OK)
            - Lower liquidity → higher score (widen spread)
            - Normalize relative to typical levels
        """
        # Average liquidity (both sides)
        avg_liq = (liquidity_bid + liquidity_ask) / 2.0
        
        # Typical baseline (assume 10.0 as "good liquidity", 1.0 as "poor")
        good_liq = 10.0
        poor_liq = 1.0
        
        if avg_liq >= good_liq:
            return 0.0
        elif avg_liq <= poor_liq:
            return 1.0
        else:
            # Linear: liq=1 → score=1.0, liq=10 → score=0
            return (good_liq - avg_liq) / (good_liq - poor_liq)
    
    def _compute_lat_score(self) -> float:
        """
        Compute latency score (0..1) based on p95.
        
        Logic:
            - p95 <= 150ms → 0.0
            - p95 >= 400ms → 1.0
            - Linear in between
        """
        if len(self.latency_samples) < 5:
            return 0.0
        
        # Compute p95
        sorted_samples = sorted(self.latency_samples)
        p95_idx = int(len(sorted_samples) * 0.95)
        p95_lat = sorted_samples[min(p95_idx, len(sorted_samples) - 1)]
        
        soft_ms = 150.0
        hard_ms = 400.0
        
        if p95_lat <= soft_ms:
            return 0.0
        elif p95_lat >= hard_ms:
            return 1.0
        else:
            return (p95_lat - soft_ms) / (hard_ms - soft_ms)
    
    def _compute_pnl_score(self) -> float:
        """
        Compute PnL deviation score (0..1) based on rolling mean.
        
        Logic:
            - mean >= 0 → 0.0 (profit, no issue)
            - mean <= -10 → 1.0 (significant loss)
            - Linear in between
        """
        n = len(self.pnl_window)
        if n < 10:
            return 0.0
        
        # Compute mean
        mean = self.pnl_sum / n
        
        # If mean is positive (profits), no adjustment needed
        if mean >= 0.0:
            return 0.0
        
        # If mean is negative (losses), scale linearly
        # mean=-10 or worse → score=1.0
        # mean=0 → score=0.0
        threshold = -10.0
        if mean <= threshold:
            return 1.0
        else:
            # Linear: mean=0 → 0, mean=-10 → 1.0
            return abs(mean) / abs(threshold)
    
    def _log_computation(self) -> None:
        """Log spread computation details."""
        m = self.metrics
        print(
            f"[ADSPREAD] base={self.cfg.base_spread_bps:.2f} "
            f"vol={m['vol_score']:.2f} liq={m['liq_score']:.2f} "
            f"lat={m['lat_score']:.2f} pnl={m['pnl_score']:.2f} "
            f"total={m['total_score']:.2f} final={m['final_spread_bps']:.2f}"
        )
    
    def get_metrics(self) -> Dict[str, float]:
        """
        Get current metrics.
        
        Returns:
            Dictionary of metric values
        """
        return self.metrics.copy()
