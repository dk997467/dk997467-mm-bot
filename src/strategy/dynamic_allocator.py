"""
Dynamic Allocator - Redistribute limits/quotas based on symbol performance.

Uses Symbol Scoreboard scores to dynamically adjust:
- Position size limits per symbol
- Quote refresh rate
- Max parallel quotes
- Attention allocation

Features:
- Softmax/linear normalization of scores to weights
- Hysteresis to prevent thrashing
- Whitelist/Blacklist support
- Auto-blacklist for consistently poor performers
- Prometheus metrics export
"""
import time
from typing import Dict, List, Optional, Any, Set
from dataclasses import dataclass
import threading
import math

from src.strategy.symbol_scoreboard import SymbolScoreboard


@dataclass
class SymbolAllocation:
    """Allocation weights and limits for a symbol."""
    symbol: str
    weight: float  # Relative weight (1.0 = neutral)
    size_multiplier: float  # Multiplier for position size
    quote_refresh_multiplier: float  # Multiplier for quote refresh rate
    max_quotes: int  # Max quotes per tick
    is_active: bool = True  # Whether symbol is tradeable
    last_rebalance_ms: int = 0


class DynamicAllocator:
    """
    Dynamic allocator for per-symbol limits and quotas.
    
    Uses symbol scores to redistribute resources:
    - High-scoring symbols get more size, faster refresh, more quotes
    - Low-scoring symbols get scaled down
    - Auto-blacklist consistently poor performers
    
    Features:
    - Hysteresis to prevent thrashing
    - Whitelist/Blacklist enforcement
    - EMA smoothing of weight changes
    - Thread-safe updates
    """
    
    def __init__(
        self,
        scoreboard: SymbolScoreboard,
        rebalance_period_s: int = 30,
        min_weight: float = 0.1,
        max_weight: float = 3.0,
        hysteresis_threshold: float = 0.05,
        whitelist: Optional[List[str]] = None,
        blacklist: Optional[List[str]] = None,
        auto_blacklist_net_bps: float = -5.0,
        auto_blacklist_window_min: int = 30
    ):
        """
        Initialize allocator.
        
        Args:
            scoreboard: Symbol scoreboard instance
            rebalance_period_s: Rebalance frequency in seconds
            min_weight: Minimum weight (clamp)
            max_weight: Maximum weight (clamp)
            hysteresis_threshold: Minimum weight change to trigger rebalance
            whitelist: Only trade these symbols (None = all)
            blacklist: Never trade these symbols
            auto_blacklist_net_bps: Auto-blacklist threshold
            auto_blacklist_window_min: Auto-blacklist window in minutes
        """
        self.scoreboard = scoreboard
        self.rebalance_period_s = rebalance_period_s
        self.min_weight = min_weight
        self.max_weight = max_weight
        self.hysteresis_threshold = hysteresis_threshold
        
        # Whitelist/Blacklist
        self.whitelist: Set[str] = set(whitelist) if whitelist else set()
        self.blacklist: Set[str] = set(blacklist) if blacklist else set()
        self.auto_blacklist_net_bps = auto_blacklist_net_bps
        self.auto_blacklist_window_min = auto_blacklist_window_min
        
        # Allocations
        self._allocations: Dict[str, SymbolAllocation] = {}
        self._lock = threading.RLock()  # Reentrant lock for nested method calls
        
        # Rebalance tracking
        self._last_rebalance_ms = 0
        self._rebalance_count = 0
        
        print(f"[ALLOCATOR] Initialized: period={rebalance_period_s}s, weights=[{min_weight}, {max_weight}], hysteresis={hysteresis_threshold}")
    
    def should_rebalance(self) -> bool:
        """Check if it's time to rebalance."""
        now_ms = int(time.time() * 1000)
        elapsed_s = (now_ms - self._last_rebalance_ms) / 1000.0
        return elapsed_s >= self.rebalance_period_s
    
    def rebalance(self, symbols: List[str]) -> Dict[str, SymbolAllocation]:
        """
        Rebalance allocations based on current scores.
        
        Args:
            symbols: List of symbols to allocate
        
        Returns:
            Updated allocations
        """
        with self._lock:
            now_ms = int(time.time() * 1000)
            
            # Get scores from scoreboard
            scores = self.scoreboard.get_all_scores()
            
            # Filter symbols
            active_symbols = []
            for symbol in symbols:
                # Check whitelist
                if self.whitelist and symbol not in self.whitelist:
                    continue
                
                # Check blacklist
                if symbol in self.blacklist:
                    continue
                
                # Check auto-blacklist
                if self._should_auto_blacklist(symbol):
                    print(f"[ALLOCATOR] Auto-blacklisting {symbol} (poor performance)")
                    self.blacklist.add(symbol)
                    continue
                
                active_symbols.append(symbol)
            
            # Calculate weights from scores
            weights = self._scores_to_weights(scores, active_symbols)
            
            # Update allocations with hysteresis
            for symbol in active_symbols:
                new_weight = weights.get(symbol, 1.0)
                
                # Get existing allocation
                if symbol in self._allocations:
                    alloc = self._allocations[symbol]
                    old_weight = alloc.weight
                    
                    # Apply hysteresis
                    if abs(new_weight - old_weight) < self.hysteresis_threshold:
                        # Change too small - skip
                        continue
                    
                    # Update with EMA smoothing
                    smoothed_weight = 0.5 * new_weight + 0.5 * old_weight
                    alloc = self._create_allocation(symbol, smoothed_weight, now_ms)
                else:
                    # New symbol - use weight directly
                    alloc = self._create_allocation(symbol, new_weight, now_ms)
                
                self._allocations[symbol] = alloc
            
            # Mark inactive symbols
            for symbol in self._allocations.keys():
                if symbol not in active_symbols:
                    self._allocations[symbol].is_active = False
            
            self._last_rebalance_ms = now_ms
            self._rebalance_count += 1
            
            # Log rebalance
            active_count = sum(1 for a in self._allocations.values() if a.is_active)
            print(f"[ALLOCATOR] Rebalanced: {active_count}/{len(self._allocations)} symbols active, rebalance_count={self._rebalance_count}")
            
            return dict(self._allocations)
    
    def _scores_to_weights(self, scores: Dict[str, float], symbols: List[str]) -> Dict[str, float]:
        """
        Convert scores to weights using softmax normalization.
        
        Args:
            scores: Symbol scores
            symbols: Active symbols
        
        Returns:
            Dict mapping symbol -> weight
        """
        if not symbols:
            return {}
        
        # Get scores for active symbols
        symbol_scores = {s: scores.get(s, 0.5) for s in symbols}  # Default to neutral 0.5
        
        # Softmax normalization with temperature
        temperature = 2.0  # Higher = more uniform distribution
        exp_scores = {s: math.exp(score / temperature) for s, score in symbol_scores.items()}
        total_exp = sum(exp_scores.values())
        
        if total_exp == 0:
            # Fallback: uniform weights
            return {s: 1.0 for s in symbols}
        
        # Normalize to weights
        weights = {s: exp_val / total_exp * len(symbols) for s, exp_val in exp_scores.items()}
        
        # Clamp to [min_weight, max_weight]
        weights = {s: max(self.min_weight, min(self.max_weight, w)) for s, w in weights.items()}
        
        return weights
    
    def _create_allocation(self, symbol: str, weight: float, timestamp_ms: int) -> SymbolAllocation:
        """
        Create allocation from weight.
        
        Allocation rules:
        - size_multiplier = weight (linear scaling)
        - quote_refresh_multiplier = sqrt(weight) (less aggressive)
        - max_quotes = ceil(weight * 3) (discrete scaling)
        """
        return SymbolAllocation(
            symbol=symbol,
            weight=weight,
            size_multiplier=weight,
            quote_refresh_multiplier=math.sqrt(weight),
            max_quotes=max(1, min(10, math.ceil(weight * 3))),
            is_active=True,
            last_rebalance_ms=timestamp_ms
        )
    
    def _should_auto_blacklist(self, symbol: str) -> bool:
        """
        Check if symbol should be auto-blacklisted due to poor performance.
        
        Args:
            symbol: Symbol to check
        
        Returns:
            True if should be blacklisted
        """
        metrics = self.scoreboard.get_metrics(symbol)
        if not metrics:
            return False
        
        # Check if net_bps is consistently negative
        if metrics.net_bps_ema < self.auto_blacklist_net_bps:
            # Check if enough time has passed
            now_ms = int(time.time() * 1000)
            age_min = (now_ms - metrics.first_seen_ms) / 60000.0
            
            if age_min >= self.auto_blacklist_window_min:
                return True
        
        return False
    
    def get_allocation(self, symbol: str) -> Optional[SymbolAllocation]:
        """Get allocation for a symbol."""
        with self._lock:
            return self._allocations.get(symbol)
    
    def get_all_allocations(self) -> Dict[str, SymbolAllocation]:
        """Get all allocations."""
        with self._lock:
            return dict(self._allocations)
    
    def get_active_symbols(self) -> List[str]:
        """Get list of active symbols."""
        with self._lock:
            return [s for s, a in self._allocations.items() if a.is_active]
    
    def export_prometheus(self) -> str:
        """
        Export metrics in Prometheus format.
        
        Returns:
            Prometheus exposition format string
        """
        with self._lock:
            lines = []
            
            # Symbol weights
            lines.append("# HELP mm_symbol_weight Symbol allocation weight (1.0 = neutral)")
            lines.append("# TYPE mm_symbol_weight gauge")
            for symbol, alloc in self._allocations.items():
                if alloc.is_active:
                    lines.append(f'mm_symbol_weight{{symbol="{symbol}"}} {alloc.weight:.6f}')
            
            # Size multipliers
            lines.append("# HELP mm_symbol_size_multiplier Symbol position size multiplier")
            lines.append("# TYPE mm_symbol_size_multiplier gauge")
            for symbol, alloc in self._allocations.items():
                if alloc.is_active:
                    lines.append(f'mm_symbol_size_multiplier{{symbol="{symbol}"}} {alloc.size_multiplier:.6f}')
            
            # Rebalance counter
            lines.append("# HELP mm_allocator_rebalance_total Total allocator rebalances")
            lines.append("# TYPE mm_allocator_rebalance_total counter")
            lines.append(f"mm_allocator_rebalance_total {self._rebalance_count}")
            
            # Active symbols
            active_count = sum(1 for a in self._allocations.values() if a.is_active)
            lines.append("# HELP mm_allocator_active_symbols Number of active symbols")
            lines.append("# TYPE mm_allocator_active_symbols gauge")
            lines.append(f"mm_allocator_active_symbols {active_count}")
            
            # Blacklist size
            lines.append("# HELP mm_allocator_blacklist_size Number of blacklisted symbols")
            lines.append("# TYPE mm_allocator_blacklist_size gauge")
            lines.append(f"mm_allocator_blacklist_size {len(self.blacklist)}")
            
            return "\n".join(lines) + "\n"
    
    def get_summary(self) -> Dict[str, Any]:
        """Get summary statistics."""
        with self._lock:
            return {
                "rebalance_count": self._rebalance_count,
                "last_rebalance_ms": self._last_rebalance_ms,
                "active_symbols": self.get_active_symbols(),
                "blacklist": list(self.blacklist),
                "whitelist": list(self.whitelist) if self.whitelist else None,
                "allocations": {
                    symbol: {
                        "weight": a.weight,
                        "size_multiplier": a.size_multiplier,
                        "is_active": a.is_active
                    }
                    for symbol, a in self._allocations.items()
                }
            }

