"""
Risk Guards - SOFT/HARD protection system.

Monitors multiple risk factors and determines appropriate guard level:
- NONE: All clear
- SOFT: Scale size, widen spread
- HARD: Halt quoting temporarily
"""

import enum
import math
import time
from collections import deque
from typing import Dict, List, Optional, Tuple

from src.common.config import RiskGuardsConfig


class GuardLevel(enum.Enum):
    """Guard level severity."""
    NONE = 0
    SOFT = 1
    HARD = 2


class RiskGuards:
    """
    Multi-factor risk guard system.
    
    Monitors:
    - Volatility (EMA of mid-price changes)
    - Latency (p95 from ring buffer)
    - PnL drawdown (rolling z-score)
    - Inventory (% of max position)
    - Taker fills (count in rolling window)
    
    Returns guard level:
    - NONE: Normal operation
    - SOFT: Reduce size, widen spread
    - HARD: Halt quoting
    """
    
    def __init__(self, cfg: RiskGuardsConfig):
        self.cfg = cfg
        
        # Volatility tracking (EMA)
        self.vol_ema_bps: float = 0.0
        self.vol_ema_alpha: float = 2.0 / (cfg.vol_ema_sec + 1)
        self.last_mid: Optional[float] = None
        self.last_ts_ms: Optional[int] = None
        
        # Latency samples (ring buffer for p95)
        self.latency_samples: deque = deque(maxlen=100)
        
        # PnL tracking (rolling window for z-score)
        self.pnl_window: deque = deque(maxlen=60)  # 1 hour
        self.pnl_sum: float = 0.0
        self.pnl_sq_sum: float = 0.0
        
        # Inventory (current %)
        self.inventory_pct: float = 0.0
        
        # Taker fills (timestamps in rolling window)
        self.taker_fills: deque = deque(maxlen=100)
        
        # Guard state
        self.current_level: GuardLevel = GuardLevel.NONE
        self.halt_until_ms: Optional[int] = None
        
        # Metrics
        self.metrics: Dict[str, float] = {
            'vol_bps': 0.0,
            'latency_p95_ms': 0.0,
            'pnl_z_score': 0.0,
            'inventory_pct': 0.0,
            'taker_fills_count': 0,
            'guard_level': 0,
        }
        self.reason_counts: Dict[str, int] = {
            'vol': 0,
            'latency': 0,
            'pnl': 0,
            'inventory': 0,
            'takers': 0,
        }
    
    def update_vol(self, mid: float, ts_ms: int) -> None:
        """
        Update volatility EMA from mid-price.
        
        Args:
            mid: Current mid-price
            ts_ms: Timestamp in milliseconds
        """
        if self.last_mid is not None and self.last_ts_ms is not None:
            dt_sec = max(0.001, (ts_ms - self.last_ts_ms) / 1000.0)
            
            # Compute price change in bps
            price_change_bps = abs((mid - self.last_mid) / self.last_mid) * 10000.0
            
            # Update EMA
            self.vol_ema_bps = (
                self.vol_ema_alpha * price_change_bps +
                (1 - self.vol_ema_alpha) * self.vol_ema_bps
            )
        
        self.last_mid = mid
        self.last_ts_ms = ts_ms
        self.metrics['vol_bps'] = self.vol_ema_bps
    
    def update_latency(self, sample_ms: float) -> None:
        """
        Add latency sample.
        
        Args:
            sample_ms: Latency sample in milliseconds
        """
        self.latency_samples.append(sample_ms)
        
        # Compute p95
        if len(self.latency_samples) >= 5:
            sorted_samples = sorted(self.latency_samples)
            p95_idx = int(len(sorted_samples) * 0.95)
            p95_lat = sorted_samples[min(p95_idx, len(sorted_samples) - 1)]
            self.metrics['latency_p95_ms'] = p95_lat
    
    def update_pnl(self, pnl_delta: float) -> None:
        """
        Add PnL delta to rolling window.
        
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
        
        # Compute z-score
        n = len(self.pnl_window)
        if n >= 10:
            mean = self.pnl_sum / n
            variance = (self.pnl_sq_sum / n) - (mean * mean)
            std = math.sqrt(max(0.0, variance))
            
            if std > 1e-6:
                z_score = (self.pnl_window[-1] - mean) / std
                self.metrics['pnl_z_score'] = z_score
    
    def update_inventory_pct(self, pct: float) -> None:
        """
        Update current inventory percentage.
        
        Args:
            pct: Inventory as % of max position (can be negative)
        """
        self.inventory_pct = pct
        self.metrics['inventory_pct'] = pct
    
    def update_taker_fills(self, ts_ms: int) -> None:
        """
        Record a taker fill timestamp.
        
        Args:
            ts_ms: Fill timestamp in milliseconds
        """
        self.taker_fills.append(ts_ms)
        
        # Count recent fills (within window)
        window_ms = self.cfg.taker_fills_window_min * 60 * 1000
        now_ms = int(time.time() * 1000)
        cutoff_ms = now_ms - window_ms
        
        recent_count = sum(1 for ts in self.taker_fills if ts >= cutoff_ms)
        self.metrics['taker_fills_count'] = recent_count
    
    def assess(self, now_ms: Optional[int] = None) -> Tuple[GuardLevel, List[str]]:
        """
        Assess current risk level and determine guard action.
        
        Args:
            now_ms: Current timestamp (optional)
        
        Returns:
            (guard_level, reasons) tuple
        """
        if now_ms is None:
            now_ms = int(time.time() * 1000)
        
        if not self.cfg.enabled:
            return GuardLevel.NONE, []
        
        # Check if still in HARD halt period
        if self.halt_until_ms is not None and now_ms < self.halt_until_ms:
            return GuardLevel.HARD, ['halt_cooldown']
        
        # Reset halt
        self.halt_until_ms = None
        
        # Check each condition
        reasons_hard = []
        reasons_soft = []
        
        # 1. Volatility
        if self.vol_ema_bps > self.cfg.vol_hard_bps:
            reasons_hard.append(f'vol:{self.vol_ema_bps:.1f}bps')
            self.reason_counts['vol'] += 1
        elif self.vol_ema_bps > self.cfg.vol_soft_bps:
            reasons_soft.append(f'vol:{self.vol_ema_bps:.1f}bps')
        
        # 2. Latency
        p95_lat = self.metrics.get('latency_p95_ms', 0.0)
        if p95_lat > self.cfg.latency_p95_hard_ms:
            reasons_hard.append(f'p95:{p95_lat:.0f}ms')
            self.reason_counts['latency'] += 1
        elif p95_lat > self.cfg.latency_p95_soft_ms:
            reasons_soft.append(f'p95:{p95_lat:.0f}ms')
        
        # 3. PnL z-score
        pnl_z = self.metrics.get('pnl_z_score', 0.0)
        if pnl_z < self.cfg.pnl_hard_z:
            reasons_hard.append(f'pnl_z:{pnl_z:.2f}')
            self.reason_counts['pnl'] += 1
        elif pnl_z < self.cfg.pnl_soft_z:
            reasons_soft.append(f'pnl_z:{pnl_z:.2f}')
        
        # 4. Inventory
        abs_inv = abs(self.inventory_pct)
        if abs_inv > self.cfg.inventory_pct_hard:
            reasons_hard.append(f'inv:{self.inventory_pct:.1f}%')
            self.reason_counts['inventory'] += 1
        elif abs_inv > self.cfg.inventory_pct_soft:
            reasons_soft.append(f'inv:{self.inventory_pct:.1f}%')
        
        # 5. Taker fills
        taker_count = self._count_recent_taker_fills(now_ms)
        if taker_count >= self.cfg.taker_fills_hard:
            reasons_hard.append(f'takers:{taker_count}/{self.cfg.taker_fills_window_min}min')
            self.reason_counts['takers'] += 1
        elif taker_count >= self.cfg.taker_fills_soft:
            reasons_soft.append(f'takers:{taker_count}/{self.cfg.taker_fills_window_min}min')
        
        # Determine level
        if reasons_hard:
            level = GuardLevel.HARD
            # Set halt period
            self.halt_until_ms = now_ms + self.cfg.halt_ms_hard
            reasons = reasons_hard
        elif reasons_soft:
            level = GuardLevel.SOFT
            reasons = reasons_soft
        else:
            level = GuardLevel.NONE
            reasons = []
        
        # Update state
        self.current_level = level
        self.metrics['guard_level'] = level.value
        
        # Log
        if level != GuardLevel.NONE:
            self._log_guard(level, reasons)
        
        return level, reasons
    
    def _count_recent_taker_fills(self, now_ms: int) -> int:
        """Count taker fills in recent window."""
        window_ms = self.cfg.taker_fills_window_min * 60 * 1000
        cutoff_ms = now_ms - window_ms
        return sum(1 for ts in self.taker_fills if ts >= cutoff_ms)
    
    def _log_guard(self, level: GuardLevel, reasons: List[str]) -> None:
        """Log guard activation."""
        reasons_str = ' '.join(reasons)
        print(f"[GUARD] level={level.name} reason={reasons_str}")
    
    def get_metrics(self) -> Dict[str, float]:
        """
        Get current metrics.
        
        Returns:
            Dictionary of metric values
        """
        return self.metrics.copy()
    
    def get_reason_counts(self) -> Dict[str, int]:
        """
        Get reason counts (for monitoring).
        
        Returns:
            Dictionary of reason→count
        """
        return self.reason_counts.copy()
