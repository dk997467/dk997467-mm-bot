"""
Taker fill tracker for enforcing hourly caps.

Tracks taker fills in a rolling window to prevent excessive slippage
by limiting taker fills per hour (both count and percentage).
"""
import time
from collections import deque
from typing import Deque, Tuple
from dataclasses import dataclass


@dataclass
class FillRecord:
    """Record of a fill event."""
    timestamp_ms: int
    is_taker: bool
    symbol: str


class TakerTracker:
    """
    Track taker fills in rolling window and enforce caps.
    
    Enforces two limits:
    1. Max absolute number of taker fills per hour
    2. Max taker share as percentage of all fills per hour
    """
    
    def __init__(self, max_taker_fills_per_hour: int = 50, 
                 max_taker_share_pct: float = 10.0,
                 rolling_window_sec: int = 3600):
        """
        Initialize taker tracker.
        
        Args:
            max_taker_fills_per_hour: Max number of taker fills in rolling window
            max_taker_share_pct: Max taker share as % of all fills (0-100)
            rolling_window_sec: Rolling window duration in seconds (default 1 hour)
        """
        self.max_taker_fills = max_taker_fills_per_hour
        self.max_taker_share_pct = max_taker_share_pct
        self.rolling_window_ms = rolling_window_sec * 1000
        
        # Rolling window of fills (timestamp, is_taker, symbol)
        self.fills: Deque[FillRecord] = deque()
    
    def record_fill(self, symbol: str, is_taker: bool, timestamp_ms: int = None) -> None:
        """
        Record a fill event.
        
        Args:
            symbol: Trading symbol
            is_taker: True if taker fill, False if maker fill
            timestamp_ms: Fill timestamp in milliseconds (None = current time)
        """
        if timestamp_ms is None:
            timestamp_ms = int(time.time() * 1000)
        
        self.fills.append(FillRecord(
            timestamp_ms=timestamp_ms,
            is_taker=is_taker,
            symbol=symbol
        ))
        
        # Clean up old fills outside rolling window
        self._cleanup_old_fills(timestamp_ms)
    
    def _cleanup_old_fills(self, now_ms: int) -> None:
        """Remove fills outside rolling window."""
        cutoff_ms = now_ms - self.rolling_window_ms
        
        while self.fills and self.fills[0].timestamp_ms < cutoff_ms:
            self.fills.popleft()
    
    def can_take_liquidity(self, symbol: str = None, timestamp_ms: int = None) -> Tuple[bool, str]:
        """
        Check if taker fill is allowed based on caps.
        
        Args:
            symbol: Optional symbol filter (not implemented yet)
            timestamp_ms: Current timestamp (None = current time)
        
        Returns:
            (allowed, reason) tuple:
                - (True, "") if taker fill is allowed
                - (False, reason) if taker fill would exceed caps
        """
        if timestamp_ms is None:
            timestamp_ms = int(time.time() * 1000)
        
        # Clean up old fills
        self._cleanup_old_fills(timestamp_ms)
        
        # Count taker and total fills in window
        taker_count = sum(1 for f in self.fills if f.is_taker)
        total_count = len(self.fills)
        
        # Check absolute count limit
        if taker_count >= self.max_taker_fills:
            return False, f"taker_count_exceeded (limit={self.max_taker_fills})"
        
        # Check percentage limit (only if we have enough fills for meaningful percentage)
        if total_count >= 10:  # Minimum sample size
            taker_share_pct = (taker_count / total_count) * 100.0
            
            # Simulate adding one more taker fill
            simulated_taker_share = ((taker_count + 1) / (total_count + 1)) * 100.0
            
            if simulated_taker_share > self.max_taker_share_pct:
                return False, f"taker_share_exceeded (current={taker_share_pct:.1f}%, limit={self.max_taker_share_pct:.1f}%)"
        
        return True, ""
    
    def get_stats(self, timestamp_ms: int = None) -> dict:
        """
        Get current taker fill statistics.
        
        Returns:
            Dict with keys:
                - taker_count: Number of taker fills in window
                - maker_count: Number of maker fills in window
                - total_count: Total fills in window
                - taker_share_pct: Taker share as percentage
                - can_take: Whether taker fills are currently allowed (based on current share)
        """
        if timestamp_ms is None:
            timestamp_ms = int(time.time() * 1000)
        
        # Clean up old fills
        self._cleanup_old_fills(timestamp_ms)
        
        taker_count = sum(1 for f in self.fills if f.is_taker)
        maker_count = sum(1 for f in self.fills if not f.is_taker)
        total_count = len(self.fills)
        
        taker_share_pct = (taker_count / total_count * 100.0) if total_count > 0 else 0.0
        
        # Check if current taker share exceeds limit
        # can_take = taker_share_pct <= max_taker_share_pct
        can_take = taker_share_pct <= self.max_taker_share_pct
        
        # Also check absolute count limit
        if taker_count >= self.max_taker_fills:
            can_take = False
            reason = f"taker_count_exceeded (limit={self.max_taker_fills})"
        elif not can_take:
            reason = f"taker_share_exceeded (current={taker_share_pct:.1f}%, limit={self.max_taker_share_pct:.1f}%)"
        else:
            reason = None
        
        return {
            'taker_count': taker_count,
            'maker_count': maker_count,
            'total_count': total_count,
            'taker_share_pct': taker_share_pct,
            'can_take': can_take,
            'block_reason': reason,
        }
    
    def reset(self) -> None:
        """Clear all recorded fills."""
        self.fills.clear()

