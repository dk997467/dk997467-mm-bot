"""Enhanced quoting logic with volatility, inventory skew, and adverse selection guard."""

import math
import time
from collections import deque
from typing import Dict, List, Tuple, Optional
from decimal import Decimal

from src.common.di import AppContext
from src.common.models import QuoteRequest


class VolatilityTracker:
    """Track EWMA volatility per symbol."""
    
    def __init__(self, half_life_s: int = 60):
        self.half_life_s = half_life_s
        self.alpha = 1 - math.exp(-math.log(2) / half_life_s)
        self.ewma_var: Dict[str, float] = {}
        self.last_mid: Dict[str, float] = {}
        self.mid_buffer: Dict[str, deque] = {}
        self.buffer_maxlen = 600
    
    def update(self, symbol: str, mid_price: float) -> float:
        """Update volatility and return vola_1m_bps."""
        now = time.time()
        
        if symbol not in self.ewma_var:
            self.ewma_var[symbol] = 0.0
            self.last_mid[symbol] = mid_price
            self.mid_buffer[symbol] = deque(maxlen=self.buffer_maxlen)
            self.mid_buffer[symbol].append(mid_price)
            return 0.0
        
        self.mid_buffer[symbol].append(mid_price)
        
        if self.last_mid[symbol] > 0:
            log_return = math.log(mid_price / self.last_mid[symbol])
            self.ewma_var[symbol] = (1 - self.alpha) * self.ewma_var[symbol] + self.alpha * (log_return ** 2)
        
        self.last_mid[symbol] = mid_price
        return math.sqrt(self.ewma_var[symbol]) * 1e4


class OrderBookAnalyzer:
    """Analyze order book for imbalance and microprice."""
    
    def __init__(self, imbalance_levels: int = 5):
        self.imbalance_levels = imbalance_levels
    
    def compute_imbalance(self, bids: List[List[float]], asks: List[List[float]]) -> float:
        """Compute order book imbalance."""
        if not bids or not asks:
            return 0.5
        
        bid_vol = sum(qty for _, qty in bids[:self.imbalance_levels])
        ask_vol = sum(qty for _, qty in asks[:self.imbalance_levels])
        
        total_vol = bid_vol + ask_vol
        if total_vol == 0:
            return 0.5
        
        return bid_vol / total_vol
    
    def compute_microprice(self, bids: List[List[float]], asks: List[List[float]]) -> Tuple[float, float]:
        """Compute microprice and drift."""
        if not bids or not asks:
            return 0.0, 0.0
        
        bid_price, bid_qty = bids[0]
        ask_price, ask_qty = asks[0]
        
        total_qty = bid_qty + ask_qty
        if total_qty == 0:
            return 0.0, 0.0
        
        microprice = (ask_price * bid_qty + bid_price * ask_qty) / total_qty
        mid_price = (bid_price + ask_price) / 2
        
        if mid_price > 0:
            drift_bps = (microprice - mid_price) / mid_price * 1e4
        else:
            drift_bps = 0.0
        
        return microprice, drift_bps


class EnhancedQuoter:
    """Enhanced quoting with volatility, inventory skew, and adverse selection guard."""
    
    def __init__(self, ctx: AppContext):
        self.ctx = ctx
        self.cfg = ctx.cfg
        self.metrics = ctx.metrics
        
        self.vola_tracker = VolatilityTracker(self.cfg.strategy.vola_half_life_s)
        self.ob_analyzer = OrderBookAnalyzer(self.cfg.strategy.imbalance_levels)
        self.guard_paused: Dict[str, Dict[str, float]] = {}
        
        self.enable_dynamic_spread = self.cfg.strategy.enable_dynamic_spread
        self.enable_inventory_skew = self.cfg.strategy.enable_inventory_skew
        self.enable_adverse_guard = self.cfg.strategy.enable_adverse_guard
    
    def generate_quotes(self, symbol: str, orderbook: Dict, 
                       position_value_usd: float = 0.0, equity_usd: float = 10000.0) -> List[QuoteRequest]:
        """Generate quotes with enhanced logic."""
        bids = orderbook.get('bids', [])
        asks = orderbook.get('asks', [])
        
        if not bids or not asks:
            return []
        
        best_bid = bids[0][0] if bids else 0
        best_ask = asks[0][0] if asks else 0
        
        if best_bid <= 0 or best_ask <= 0 or best_bid >= best_ask:
            return []
        
        mid_price = (best_bid + best_ask) / 2
        vola_1m_bps = self.vola_tracker.update(symbol, mid_price)
        
        ob_imbalance = self.ob_analyzer.compute_imbalance(bids, asks)
        microprice, drift_bps = self.ob_analyzer.compute_microprice(bids, asks)
        
        if self.enable_dynamic_spread:
            base_spread_bps = self._compute_dynamic_spread(vola_1m_bps)
        else:
            base_spread_bps = self.cfg.strategy.min_spread_bps
        
        if self.enable_inventory_skew:
            price_shift_bps = self._compute_inventory_skew(position_value_usd, equity_usd)
        else:
            price_shift_bps = 0.0
        
        if self.enable_adverse_guard:
            base_spread_bps = self._apply_adverse_guard(
                symbol, base_spread_bps, ob_imbalance, drift_bps, position_value_usd
            )
        
        quotes = []
        for level in range(self.cfg.strategy.levels_per_side):
            level_offset = self.cfg.strategy.level_spacing_coeff * base_spread_bps * (level + 1)
            
            bid_spread = base_spread_bps / 2 + max(0, price_shift_bps) + level_offset
            bid_price = mid_price * (1 - bid_spread / 1e4)
            
            ask_spread = base_spread_bps / 2 - min(0, price_shift_bps) + level_offset
            ask_price = mid_price * (1 + ask_spread / 1e4)
            
            if bid_price < ask_price and (ask_price - bid_price) / mid_price * 1e4 >= self.cfg.strategy.min_spread_bps:
                if not self._is_side_paused(symbol, "bid", level):
                    quotes.append(QuoteRequest(
                        symbol=symbol, side="bid", price=Decimal(str(bid_price)),
                        size=Decimal("0.001"), level=level
                    ))
                
                if not self._is_side_paused(symbol, "ask", level):
                    quotes.append(QuoteRequest(
                        symbol=symbol, side="ask", price=Decimal(str(ask_price)),
                        size=Decimal("0.001"), level=level
                    ))
        
        self._update_metrics(symbol, base_spread_bps, vola_1m_bps, ob_imbalance)
        return quotes
    
    def _compute_dynamic_spread(self, vola_1m_bps: float) -> float:
        """Compute dynamic spread based on volatility."""
        spread_bps = self.cfg.strategy.k_vola_spread * vola_1m_bps
        spread_bps = max(self.cfg.strategy.min_spread_bps, spread_bps)
        spread_bps = min(self.cfg.strategy.max_spread_bps, spread_bps)
        return spread_bps
    
    def _compute_inventory_skew(self, position_value_usd: float, equity_usd: float) -> float:
        """Compute inventory-based price shift."""
        if equity_usd == 0:
            return 0.0
        
        inventory_pct = position_value_usd / equity_usd
        price_shift_bps = self.cfg.strategy.skew_coeff * inventory_pct * 1e4
        price_shift_bps = max(-self.cfg.strategy.max_spread_bps, price_shift_bps)
        price_shift_bps = min(self.cfg.strategy.max_spread_bps, price_shift_bps)
        return price_shift_bps
    
    def _apply_adverse_guard(self, symbol: str, base_spread_bps: float, 
                            ob_imbalance: float, drift_bps: float, 
                            position_value_usd: float) -> float:
        """Apply adverse selection guard."""
        imbalance_threshold = self.cfg.strategy.imbalance_cutoff
        
        if position_value_usd > 0 and ob_imbalance > imbalance_threshold:
            self._pause_side(symbol, "ask", self.cfg.strategy.guard_pause_ms)
            return base_spread_bps * 1.5
        
        if position_value_usd < 0 and ob_imbalance < (1 - imbalance_threshold):
            self._pause_side(symbol, "bid", self.cfg.strategy.guard_pause_ms)
            return base_spread_bps * 1.5
        
        if abs(drift_bps) > self.cfg.strategy.microprice_drift_bps:
            return base_spread_bps * 1.3
        
        return base_spread_bps
    
    def _pause_side(self, symbol: str, side: str, pause_ms: int):
        """Pause quoting on a side for specified duration."""
        if symbol not in self.guard_paused:
            self.guard_paused[symbol] = {}
        
        pause_until = time.time() * 1000 + pause_ms
        self.guard_paused[symbol][side] = pause_until
    
    def _is_side_paused(self, symbol: str, side: str, level: int) -> bool:
        """Check if a side is paused by guard."""
        if symbol not in self.guard_paused or side not in self.guard_paused[symbol]:
            return False
        
        pause_until = self.guard_paused[symbol][side]
        if time.time() * 1000 > pause_until:
            del self.guard_paused[symbol][side]
            return False
        
        return True
    
    def _update_metrics(self, symbol: str, spread_bps: float, vola_1m_bps: float, ob_imbalance: float):
        """Update metrics with current values."""
        if self.metrics:
            self.metrics.update_market_metrics(symbol, spread_bps, vola_1m_bps, ob_imbalance)
            self.metrics.update_quote_metrics(symbol, 1)
