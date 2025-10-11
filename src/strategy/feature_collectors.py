"""
Feature collectors for spread/queue calibration.

Tracks per-symbol features needed for auto-calibration:
- vol_realized: Realized volatility
- liq_top_depth: Top-of-book depth
- latency_p95: Pipeline latency (p95)
- pnl_dev: PnL deviation from target
- fill_rate: Fill rate (fills / posted quotes)
- taker_share: Taker fills percentage
- queue_absorb_rate: Queue consumption rate
- queue_eta_ms: Estimated time-to-fill
- slippage_bps: Per-symbol slippage
- adverse_move_bps: Adverse selection metric
"""
import time
import logging
from typing import Dict, List, Optional, Any, Deque
from dataclasses import dataclass, field
from collections import deque, defaultdict
import threading

logger = logging.getLogger(__name__)


@dataclass
class CalibrationFeatures:
    """Per-symbol calibration features."""
    symbol: str
    
    # Volatility metrics
    vol_realized_ema: float = 0.0  # Realized vol (EMA)
    vol_samples: Deque[float] = field(default_factory=lambda: deque(maxlen=1000))
    
    # Liquidity metrics
    liq_top_depth_ema: float = 0.0  # Top-of-book depth (both sides)
    liq_samples: Deque[float] = field(default_factory=lambda: deque(maxlen=1000))
    
    # Latency metrics
    latency_p95_ema: float = 0.0  # p95 pipeline latency
    latency_samples: Deque[float] = field(default_factory=lambda: deque(maxlen=1000))
    
    # PnL metrics
    pnl_dev_ema: float = 0.0  # PnL deviation from target
    pnl_samples: Deque[float] = field(default_factory=lambda: deque(maxlen=1000))
    
    # Fill metrics
    fill_rate_ema: float = 0.0  # Fill rate
    taker_share_ema: float = 0.0  # Taker fills percentage
    fills_total: int = 0
    fills_maker: int = 0
    fills_taker: int = 0
    quotes_total: int = 0
    
    # Queue metrics
    queue_absorb_rate_ema: float = 0.0  # Queue consumption rate (qty/sec)
    queue_eta_ms_ema: float = 0.0  # Estimated time to fill (ms)
    queue_samples: Deque[tuple] = field(default_factory=lambda: deque(maxlen=1000))
    
    # Slippage metrics
    slippage_bps_ema: float = 0.0  # Per-fill slippage
    slippage_samples: Deque[float] = field(default_factory=lambda: deque(maxlen=1000))
    
    # Adverse selection metrics
    adverse_move_bps_ema: float = 0.0  # Post-fill adverse move
    adverse_samples: Deque[float] = field(default_factory=lambda: deque(maxlen=1000))
    
    # Timestamps
    first_seen_ms: int = 0
    last_updated_ms: int = 0
    
    def __post_init__(self):
        """Initialize timestamps."""
        if self.first_seen_ms == 0:
            self.first_seen_ms = int(time.time() * 1000)
        if self.last_updated_ms == 0:
            self.last_updated_ms = self.first_seen_ms


class FeatureCollector:
    """
    Collects calibration features per symbol.
    
    Features:
    - Lightweight EMA smoothing
    - Rolling windows for percentiles
    - Thread-safe updates
    - Prometheus export
    """
    
    def __init__(
        self,
        ema_alpha: float = 0.1,
        rolling_window_sec: int = 300,
        min_samples: int = 10
    ):
        """
        Initialize feature collector.
        
        Args:
            ema_alpha: EMA smoothing factor (0.0-1.0)
            rolling_window_sec: Rolling window size in seconds
            min_samples: Minimum samples before metrics are valid
        """
        self.ema_alpha = ema_alpha
        self.rolling_window_sec = rolling_window_sec
        self.min_samples = min_samples
        
        # Per-symbol features
        self._features: Dict[str, CalibrationFeatures] = {}
        self._lock = threading.Lock()
        
        # Price tracking for volatility calculation
        self._last_price: Dict[str, float] = {}
        self._price_history: Dict[str, Deque[tuple]] = defaultdict(lambda: deque(maxlen=1000))
        
        logger.info(
            f"[FEATURE_COLLECTOR] Initialized: ema_alpha={ema_alpha}, "
            f"window={rolling_window_sec}s, min_samples={min_samples}"
        )
    
    def record_tick(
        self,
        symbol: str,
        mid_price: Optional[float] = None,
        bid_depth: Optional[float] = None,
        ask_depth: Optional[float] = None,
        latency_ms: Optional[float] = None,
        pnl_bps: Optional[float] = None,
        target_pnl_bps: Optional[float] = None
    ) -> None:
        """
        Record tick-level features.
        
        Args:
            symbol: Trading symbol
            mid_price: Current mid price
            bid_depth: Bid depth at top level
            ask_depth: Ask depth at top level
            latency_ms: Pipeline latency (ms)
            pnl_bps: Current PnL in bps
            target_pnl_bps: Target PnL in bps
        """
        with self._lock:
            # Get or create features
            if symbol not in self._features:
                self._features[symbol] = CalibrationFeatures(symbol=symbol)
            
            features = self._features[symbol]
            now_ms = int(time.time() * 1000)
            
            # Volatility: calculate from price changes
            if mid_price is not None:
                if symbol in self._last_price:
                    last_price = self._last_price[symbol]
                    price_change_bps = abs((mid_price - last_price) / last_price * 10000)
                    features.vol_realized_ema = self._update_ema(
                        features.vol_realized_ema, price_change_bps
                    )
                    features.vol_samples.append(price_change_bps)
                
                self._last_price[symbol] = mid_price
                self._price_history[symbol].append((now_ms, mid_price))
            
            # Liquidity: top-of-book depth
            if bid_depth is not None and ask_depth is not None:
                top_depth = bid_depth + ask_depth
                features.liq_top_depth_ema = self._update_ema(
                    features.liq_top_depth_ema, top_depth
                )
                features.liq_samples.append(top_depth)
            
            # Latency
            if latency_ms is not None:
                features.latency_p95_ema = self._update_ema(
                    features.latency_p95_ema, latency_ms
                )
                features.latency_samples.append(latency_ms)
            
            # PnL deviation
            if pnl_bps is not None and target_pnl_bps is not None:
                pnl_dev = abs(pnl_bps - target_pnl_bps)
                features.pnl_dev_ema = self._update_ema(
                    features.pnl_dev_ema, pnl_dev
                )
                features.pnl_samples.append(pnl_dev)
            
            features.last_updated_ms = now_ms
    
    def record_quote(self, symbol: str) -> None:
        """
        Record quote event.
        
        Args:
            symbol: Trading symbol
        """
        with self._lock:
            if symbol not in self._features:
                self._features[symbol] = CalibrationFeatures(symbol=symbol)
            
            self._features[symbol].quotes_total += 1
    
    def record_fill(
        self,
        symbol: str,
        is_maker: bool,
        fill_price: float,
        quote_price: float,
        qty: float,
        queue_position: Optional[int] = None,
        mid_at_quote: Optional[float] = None,
        mid_now: Optional[float] = None
    ) -> None:
        """
        Record fill event.
        
        Args:
            symbol: Trading symbol
            is_maker: True if maker fill, False if taker
            fill_price: Actual fill price
            quote_price: Our quoted price
            qty: Fill quantity
            queue_position: Estimated queue position when quoted
            mid_at_quote: Mid price when we quoted
            mid_now: Current mid price (for adverse selection)
        """
        with self._lock:
            if symbol not in self._features:
                self._features[symbol] = CalibrationFeatures(symbol=symbol)
            
            features = self._features[symbol]
            now_ms = int(time.time() * 1000)
            
            # Update fill counters
            features.fills_total += 1
            if is_maker:
                features.fills_maker += 1
            else:
                features.fills_taker += 1
            
            # Calculate fill rate and taker share
            if features.quotes_total > 0:
                fill_rate = features.fills_total / features.quotes_total
                features.fill_rate_ema = self._update_ema(
                    features.fill_rate_ema, fill_rate
                )
            
            if features.fills_total > 0:
                taker_share = features.fills_taker / features.fills_total
                features.taker_share_ema = self._update_ema(
                    features.taker_share_ema, taker_share
                )
            
            # Slippage: difference between fill and quote price
            slippage_bps = abs((fill_price - quote_price) / quote_price * 10000)
            features.slippage_bps_ema = self._update_ema(
                features.slippage_bps_ema, slippage_bps
            )
            features.slippage_samples.append(slippage_bps)
            
            # Adverse selection: mid move after fill
            if mid_at_quote is not None and mid_now is not None:
                # For buy: adverse if mid went up
                # For sell: adverse if mid went down
                # Simplified: use absolute move
                adverse_move_bps = abs((mid_now - mid_at_quote) / mid_at_quote * 10000)
                features.adverse_move_bps_ema = self._update_ema(
                    features.adverse_move_bps_ema, adverse_move_bps
                )
                features.adverse_samples.append(adverse_move_bps)
            
            # Queue metrics (if available)
            if queue_position is not None:
                features.queue_samples.append((now_ms, queue_position, qty))
            
            features.last_updated_ms = now_ms
    
    def record_queue_observation(
        self,
        symbol: str,
        queue_position: int,
        queue_depth_ahead: float,
        absorb_rate_qty_per_sec: float
    ) -> None:
        """
        Record queue observation for ETA calculation.
        
        Args:
            symbol: Trading symbol
            queue_position: Our position in queue (0 = first)
            queue_depth_ahead: Total quantity ahead of us
            absorb_rate_qty_per_sec: Observed absorption rate
        """
        with self._lock:
            if symbol not in self._features:
                self._features[symbol] = CalibrationFeatures(symbol=symbol)
            
            features = self._features[symbol]
            
            # Update absorb rate
            features.queue_absorb_rate_ema = self._update_ema(
                features.queue_absorb_rate_ema, absorb_rate_qty_per_sec
            )
            
            # Calculate ETA (ms)
            if absorb_rate_qty_per_sec > 0:
                eta_sec = queue_depth_ahead / absorb_rate_qty_per_sec
                eta_ms = eta_sec * 1000
                features.queue_eta_ms_ema = self._update_ema(
                    features.queue_eta_ms_ema, eta_ms
                )
    
    def _update_ema(self, current_ema: float, new_value: float) -> float:
        """Update EMA with new value."""
        if current_ema == 0.0:
            return new_value
        return self.ema_alpha * new_value + (1.0 - self.ema_alpha) * current_ema
    
    def get_features(self, symbol: str) -> Optional[CalibrationFeatures]:
        """Get features for a symbol."""
        with self._lock:
            return self._features.get(symbol)
    
    def get_all_features(self) -> Dict[str, CalibrationFeatures]:
        """Get features for all symbols."""
        with self._lock:
            return dict(self._features)
    
    def export_prometheus(self) -> str:
        """
        Export features in Prometheus format.
        
        Returns:
            Prometheus exposition format string
        """
        with self._lock:
            lines = []
            
            # Volatility
            lines.append("# HELP mm_symbol_vol_realized Symbol realized volatility (bps, EMA)")
            lines.append("# TYPE mm_symbol_vol_realized gauge")
            for symbol, f in self._features.items():
                lines.append(f'mm_symbol_vol_realized{{symbol="{symbol}"}} {f.vol_realized_ema:.6f}')
            
            # Liquidity
            lines.append("# HELP mm_symbol_liq_top_depth Symbol top-of-book depth (EMA)")
            lines.append("# TYPE mm_symbol_liq_top_depth gauge")
            for symbol, f in self._features.items():
                lines.append(f'mm_symbol_liq_top_depth{{symbol="{symbol}"}} {f.liq_top_depth_ema:.6f}')
            
            # Latency
            lines.append("# HELP mm_symbol_latency_p95 Symbol pipeline latency p95 (ms, EMA)")
            lines.append("# TYPE mm_symbol_latency_p95 gauge")
            for symbol, f in self._features.items():
                lines.append(f'mm_symbol_latency_p95{{symbol="{symbol}"}} {f.latency_p95_ema:.6f}')
            
            # PnL deviation
            lines.append("# HELP mm_symbol_pnl_dev Symbol PnL deviation from target (bps, EMA)")
            lines.append("# TYPE mm_symbol_pnl_dev gauge")
            for symbol, f in self._features.items():
                lines.append(f'mm_symbol_pnl_dev{{symbol="{symbol}"}} {f.pnl_dev_ema:.6f}')
            
            # Fill rate
            lines.append("# HELP mm_symbol_fill_rate Symbol fill rate (fills/quotes, EMA)")
            lines.append("# TYPE mm_symbol_fill_rate gauge")
            for symbol, f in self._features.items():
                lines.append(f'mm_symbol_fill_rate{{symbol="{symbol}"}} {f.fill_rate_ema:.6f}')
            
            # Taker share
            lines.append("# HELP mm_symbol_taker_share Symbol taker fills percentage (EMA)")
            lines.append("# TYPE mm_symbol_taker_share gauge")
            for symbol, f in self._features.items():
                lines.append(f'mm_symbol_taker_share{{symbol="{symbol}"}} {f.taker_share_ema:.6f}')
            
            # Queue absorb rate
            lines.append("# HELP mm_symbol_queue_absorb_rate Symbol queue absorption rate (qty/sec, EMA)")
            lines.append("# TYPE mm_symbol_queue_absorb_rate gauge")
            for symbol, f in self._features.items():
                lines.append(f'mm_symbol_queue_absorb_rate{{symbol="{symbol}"}} {f.queue_absorb_rate_ema:.6f}')
            
            # Queue ETA
            lines.append("# HELP mm_symbol_queue_eta_ms Symbol estimated time to fill (ms, EMA)")
            lines.append("# TYPE mm_symbol_queue_eta_ms gauge")
            for symbol, f in self._features.items():
                lines.append(f'mm_symbol_queue_eta_ms{{symbol="{symbol}"}} {f.queue_eta_ms_ema:.6f}')
            
            # Slippage
            lines.append("# HELP mm_symbol_slippage_bps Symbol per-fill slippage (bps, EMA)")
            lines.append("# TYPE mm_symbol_slippage_bps gauge")
            for symbol, f in self._features.items():
                lines.append(f'mm_symbol_slippage_bps{{symbol="{symbol}"}} {f.slippage_bps_ema:.6f}')
            
            # Adverse move
            lines.append("# HELP mm_symbol_adverse_move_bps Symbol adverse selection (bps, EMA)")
            lines.append("# TYPE mm_symbol_adverse_move_bps gauge")
            for symbol, f in self._features.items():
                lines.append(f'mm_symbol_adverse_move_bps{{symbol="{symbol}"}} {f.adverse_move_bps_ema:.6f}')
            
            # Fill counters
            lines.append("# HELP mm_symbol_fills_total Total fills for symbol")
            lines.append("# TYPE mm_symbol_fills_total counter")
            for symbol, f in self._features.items():
                lines.append(f'mm_symbol_fills_total{{symbol="{symbol}"}} {f.fills_total}')
            
            lines.append("# HELP mm_symbol_fills_maker Maker fills for symbol")
            lines.append("# TYPE mm_symbol_fills_maker counter")
            for symbol, f in self._features.items():
                lines.append(f'mm_symbol_fills_maker{{symbol="{symbol}"}} {f.fills_maker}')
            
            lines.append("# HELP mm_symbol_fills_taker Taker fills for symbol")
            lines.append("# TYPE mm_symbol_fills_taker counter")
            for symbol, f in self._features.items():
                lines.append(f'mm_symbol_fills_taker{{symbol="{symbol}"}} {f.fills_taker}')
            
            return "\n".join(lines) + "\n"
    
    def get_summary(self) -> Dict[str, Any]:
        """Get summary statistics."""
        with self._lock:
            return {
                "total_symbols": len(self._features),
                "features_by_symbol": {
                    symbol: {
                        "vol_realized_ema": f.vol_realized_ema,
                        "liq_top_depth_ema": f.liq_top_depth_ema,
                        "latency_p95_ema": f.latency_p95_ema,
                        "pnl_dev_ema": f.pnl_dev_ema,
                        "fill_rate_ema": f.fill_rate_ema,
                        "taker_share_ema": f.taker_share_ema,
                        "queue_absorb_rate_ema": f.queue_absorb_rate_ema,
                        "queue_eta_ms_ema": f.queue_eta_ms_ema,
                        "slippage_bps_ema": f.slippage_bps_ema,
                        "adverse_move_bps_ema": f.adverse_move_bps_ema,
                        "fills_total": f.fills_total,
                        "fills_maker": f.fills_maker,
                        "fills_taker": f.fills_taker,
                        "quotes_total": f.quotes_total
                    }
                    for symbol, f in self._features.items()
                }
            }

