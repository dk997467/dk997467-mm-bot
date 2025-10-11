"""
Symbol Scoreboard - Per-symbol performance tracking with EMA smoothing.

Tracks key metrics for each symbol:
- net_bps: Net P&L in basis points
- fill_rate: Maker fill rate
- slippage_bps: Average slippage
- queue_edge_score: Queue position advantage
- adverse_penalty: Adverse selection penalty

Exports metrics to Prometheus and provides scoring for dynamic allocator.
"""
import time
from typing import Dict, List, Optional, Any
from dataclasses import dataclass, field
from collections import deque
import threading


@dataclass
class SymbolMetrics:
    """Per-symbol performance metrics."""
    symbol: str
    
    # Core metrics (EMA smoothed)
    net_bps_ema: float = 0.0
    fill_rate_ema: float = 0.0
    slippage_bps_ema: float = 0.0
    queue_edge_score_ema: float = 0.0
    adverse_penalty_ema: float = 0.0
    
    # Rolling window for raw samples
    net_bps_samples: deque = field(default_factory=lambda: deque(maxlen=1000))
    fill_rate_samples: deque = field(default_factory=lambda: deque(maxlen=1000))
    
    # Counters
    total_ticks: int = 0
    total_fills: int = 0
    total_quotes: int = 0
    
    # Timestamps
    first_seen_ms: int = 0
    last_updated_ms: int = 0
    
    def __post_init__(self):
        """Initialize timestamps."""
        if self.first_seen_ms == 0:
            self.first_seen_ms = int(time.time() * 1000)
        if self.last_updated_ms == 0:
            self.last_updated_ms = self.first_seen_ms


class SymbolScoreboard:
    """
    Symbol-level performance scoreboard with EMA smoothing.
    
    Features:
    - Per-symbol metrics tracking
    - EMA smoothing for stability
    - Rolling window for variance calculation
    - Thread-safe updates
    - Prometheus export
    """
    
    def __init__(
        self,
        rolling_window_sec: int = 300,
        ema_alpha: float = 0.1,
        min_samples: int = 10,
        weight_net_bps: float = 0.4,
        weight_fill_rate: float = 0.2,
        weight_slippage: float = 0.2,
        weight_queue_edge: float = 0.1,
        weight_adverse_penalty: float = 0.1
    ):
        """
        Initialize scoreboard.
        
        Args:
            rolling_window_sec: Rolling window size in seconds
            ema_alpha: EMA smoothing factor (0.0-1.0)
            min_samples: Minimum samples before score is valid
            weight_*: Weights for composite score calculation
        """
        self.rolling_window_sec = rolling_window_sec
        self.ema_alpha = ema_alpha
        self.min_samples = min_samples
        
        # Score weights
        self.weight_net_bps = weight_net_bps
        self.weight_fill_rate = weight_fill_rate
        self.weight_slippage = weight_slippage
        self.weight_queue_edge = weight_queue_edge
        self.weight_adverse_penalty = weight_adverse_penalty
        
        # Per-symbol metrics
        self._metrics: Dict[str, SymbolMetrics] = {}
        self._lock = threading.Lock()
        
        print(f"[SCOREBOARD] Initialized: window={rolling_window_sec}s, ema_alpha={ema_alpha}, min_samples={min_samples}")
    
    def record_tick(
        self,
        symbol: str,
        net_bps: Optional[float] = None,
        fill_rate: Optional[float] = None,
        slippage_bps: Optional[float] = None,
        queue_edge_score: Optional[float] = None,
        adverse_penalty: Optional[float] = None
    ) -> None:
        """
        Record metrics for a symbol tick.
        
        Args:
            symbol: Trading symbol
            net_bps: Net P&L in basis points (positive = profit)
            fill_rate: Maker fill rate (0.0-1.0)
            slippage_bps: Slippage in basis points (positive = cost)
            queue_edge_score: Queue position advantage (0.0-1.0)
            adverse_penalty: Adverse selection penalty (0.0-1.0)
        """
        with self._lock:
            # Get or create metrics
            if symbol not in self._metrics:
                self._metrics[symbol] = SymbolMetrics(symbol=symbol)
            
            metrics = self._metrics[symbol]
            now_ms = int(time.time() * 1000)
            
            # Update EMA for each metric
            if net_bps is not None:
                metrics.net_bps_ema = self._update_ema(metrics.net_bps_ema, net_bps)
                metrics.net_bps_samples.append((now_ms, net_bps))
            
            if fill_rate is not None:
                metrics.fill_rate_ema = self._update_ema(metrics.fill_rate_ema, fill_rate)
                metrics.fill_rate_samples.append((now_ms, fill_rate))
            
            if slippage_bps is not None:
                metrics.slippage_bps_ema = self._update_ema(metrics.slippage_bps_ema, slippage_bps)
            
            if queue_edge_score is not None:
                metrics.queue_edge_score_ema = self._update_ema(metrics.queue_edge_score_ema, queue_edge_score)
            
            if adverse_penalty is not None:
                metrics.adverse_penalty_ema = self._update_ema(metrics.adverse_penalty_ema, adverse_penalty)
            
            # Update counters
            metrics.total_ticks += 1
            metrics.last_updated_ms = now_ms
    
    def _update_ema(self, current_ema: float, new_value: float) -> float:
        """Update EMA with new value."""
        if current_ema == 0.0:
            # First sample - initialize to value
            return new_value
        
        return self.ema_alpha * new_value + (1.0 - self.ema_alpha) * current_ema
    
    def get_score(self, symbol: str) -> Optional[float]:
        """
        Get composite score for a symbol.
        
        Returns:
            Composite score (higher = better), or None if insufficient samples
        """
        with self._lock:
            if symbol not in self._metrics:
                return None
            
            metrics = self._metrics[symbol]
            
            # Check minimum samples
            if metrics.total_ticks < self.min_samples:
                return None
            
            # Normalize metrics to [0, 1] where 1 is best
            # net_bps: normalize around 0, cap at ±20 bps
            net_bps_norm = max(0.0, min(1.0, (metrics.net_bps_ema + 20.0) / 40.0))
            
            # fill_rate: already in [0, 1]
            fill_rate_norm = max(0.0, min(1.0, metrics.fill_rate_ema))
            
            # slippage_bps: invert (lower is better), cap at 5 bps
            slippage_norm = max(0.0, min(1.0, 1.0 - metrics.slippage_bps_ema / 5.0))
            
            # queue_edge_score: already in [0, 1]
            queue_edge_norm = max(0.0, min(1.0, metrics.queue_edge_score_ema))
            
            # adverse_penalty: invert (lower is better)
            adverse_norm = max(0.0, min(1.0, 1.0 - metrics.adverse_penalty_ema))
            
            # Weighted sum
            score = (
                self.weight_net_bps * net_bps_norm +
                self.weight_fill_rate * fill_rate_norm +
                self.weight_slippage * slippage_norm +
                self.weight_queue_edge * queue_edge_norm +
                self.weight_adverse_penalty * adverse_norm
            )
            
            return score
    
    def get_all_scores(self) -> Dict[str, float]:
        """
        Get scores for all symbols.
        
        Returns:
            Dict mapping symbol -> score
        """
        with self._lock:
            scores = {}
            for symbol in self._metrics.keys():
                score = self.get_score(symbol)
                if score is not None:
                    scores[symbol] = score
            return scores
    
    def get_metrics(self, symbol: str) -> Optional[SymbolMetrics]:
        """Get raw metrics for a symbol."""
        with self._lock:
            return self._metrics.get(symbol)
    
    def get_all_metrics(self) -> Dict[str, SymbolMetrics]:
        """Get raw metrics for all symbols."""
        with self._lock:
            return dict(self._metrics)
    
    def export_prometheus(self) -> str:
        """
        Export metrics in Prometheus format.
        
        Returns:
            Prometheus exposition format string
        """
        with self._lock:
            lines = []
            
            # Symbol scores
            lines.append("# HELP mm_symbol_score Symbol composite performance score (0-1, higher is better)")
            lines.append("# TYPE mm_symbol_score gauge")
            for symbol, metrics in self._metrics.items():
                score = self.get_score(symbol)
                if score is not None:
                    lines.append(f'mm_symbol_score{{symbol="{symbol}"}} {score:.6f}')
            
            # Net BPS
            lines.append("# HELP mm_symbol_net_bps Symbol net P&L in basis points (EMA)")
            lines.append("# TYPE mm_symbol_net_bps gauge")
            for symbol, metrics in self._metrics.items():
                lines.append(f'mm_symbol_net_bps{{symbol="{symbol}"}} {metrics.net_bps_ema:.6f}')
            
            # Fill rate
            lines.append("# HELP mm_symbol_fill_rate Symbol maker fill rate (EMA)")
            lines.append("# TYPE mm_symbol_fill_rate gauge")
            for symbol, metrics in self._metrics.items():
                lines.append(f'mm_symbol_fill_rate{{symbol="{symbol}"}} {metrics.fill_rate_ema:.6f}')
            
            # Slippage
            lines.append("# HELP mm_symbol_slippage_bps Symbol slippage in basis points (EMA)")
            lines.append("# TYPE mm_symbol_slippage_bps gauge")
            for symbol, metrics in self._metrics.items():
                lines.append(f'mm_symbol_slippage_bps{{symbol="{symbol}"}} {metrics.slippage_bps_ema:.6f}')
            
            # Total ticks
            lines.append("# HELP mm_symbol_total_ticks Total ticks processed for symbol")
            lines.append("# TYPE mm_symbol_total_ticks counter")
            for symbol, metrics in self._metrics.items():
                lines.append(f'mm_symbol_total_ticks{{symbol="{symbol}"}} {metrics.total_ticks}')
            
            return "\n".join(lines) + "\n"
    
    def get_summary(self) -> Dict[str, Any]:
        """Get summary statistics."""
        with self._lock:
            return {
                "total_symbols": len(self._metrics),
                "scores": self.get_all_scores(),
                "metrics_by_symbol": {
                    symbol: {
                        "net_bps_ema": m.net_bps_ema,
                        "fill_rate_ema": m.fill_rate_ema,
                        "slippage_bps_ema": m.slippage_bps_ema,
                        "total_ticks": m.total_ticks
                    }
                    for symbol, m in self._metrics.items()
                }
            }

