"""
Simple stochastic simulator for queue-aware and inventory-skew effects.

Simulates trading with pseudo-random book updates and fill probability
based on queue position and inventory skew.
"""
import random
import time
from typing import Dict, List, Any, Tuple
from dataclasses import dataclass
from src.strategy.queue_aware import estimate_queue_position, Quote
from src.risk.inventory_skew import compute_skew_bps, get_inventory_pct


@dataclass
class SimResult:
    """Simulation result metrics."""
    duration_sec: float
    fills_total: int
    fills_maker: int
    fills_taker: int
    taker_share_pct: float
    avg_slippage_bps: float
    avg_order_age_ms: float
    net_bps: float
    final_inventory: float


class SimpleMarketSim:
    """
    Simple market simulator with stochastic fills.
    
    Features:
    - Pseudo-random book with jitter
    - Fill probability based on queue position
    - Inventory tracking
    - Configurable queue-aware and inventory-skew
    """
    
    def __init__(self, 
                 base_price: float = 50000.0,
                 spread_bps: float = 2.0,
                 tick_interval_ms: int = 100,
                 max_position: float = 10.0):
        """Initialize simulator."""
        self.base_price = base_price
        self.spread_bps = spread_bps
        self.tick_interval_ms = tick_interval_ms
        self.max_position = max_position
        
        self.position = 0.0
        self.fills: List[Dict] = []
        self.orders: List[Dict] = []
        
        # Randomizer
        random.seed(42)  # Deterministic for testing
    
    def generate_book(self, volatility: float = 0.5) -> Dict[str, Any]:
        """Generate synthetic order book with random jitter."""
        # Add random walk to base price
        price_jitter_bps = random.gauss(0, volatility)
        mid = self.base_price * (1 + price_jitter_bps / 10000.0)
        
        # Generate levels
        spread_half = (self.spread_bps / 2.0 / 10000.0) * mid
        best_bid = mid - spread_half
        best_ask = mid + spread_half
        
        # Random quantities
        bids = [
            [best_bid, random.uniform(5, 15)],
            [best_bid - mid * 0.0001, random.uniform(3, 10)],
            [best_bid - mid * 0.0002, random.uniform(2, 8)]
        ]
        
        asks = [
            [best_ask, random.uniform(5, 15)],
            [best_ask + mid * 0.0001, random.uniform(3, 10)],
            [best_ask + mid * 0.0002, random.uniform(2, 8)]
        ]
        
        return {'bids': bids, 'asks': asks, 'mid': mid}
    
    def calculate_fill_probability(self, quote: Quote, book: Dict,
                                   use_queue_aware: bool = False) -> float:
        """
        Calculate fill probability based on queue position.
        
        Better queue position = higher fill probability.
        """
        queue_pos = estimate_queue_position(book, quote.side, quote.price, quote.size)
        
        # Base probability depends on percentile
        # Top of queue (0%) = high prob, back of queue (100%) = low prob
        base_prob = 0.8 - (queue_pos['percentile'] / 100.0) * 0.6  # 0.8 to 0.2
        
        if use_queue_aware:
            # Queue-aware improves probability slightly
            base_prob = min(1.0, base_prob * 1.2)
        
        return base_prob
    
    def apply_inventory_skew_to_quotes(self, bid: float, ask: float,
                                      use_inv_skew: bool = False) -> Tuple[float, float]:
        """Apply inventory skew to quotes."""
        if not use_inv_skew:
            return bid, ask
        
        inv_pct = get_inventory_pct(self.position, self.max_position)
        
        # Simple skew: shift both prices
        skew_bps = compute_skew_bps(
            cfg=type('Config', (), {
                'enabled': True, 'target_pct': 0.0, 'max_skew_bps': 0.6,
                'slope_bps_per_1pct': 0.1, 'clamp_pct': 5.0
            })(),
            inventory_pct=inv_pct
        )
        
        if skew_bps != 0.0:
            # Shift prices to encourage rebalancing
            shift = -(skew_bps / 2.0 / 10000.0)  # Convert to price shift
            bid_adj = bid * (1 + shift)
            ask_adj = ask * (1 + shift)
            return bid_adj, ask_adj
        
        return bid, ask
    
    def run_simulation(self, duration_sec: float = 60.0,
                      use_queue_aware: bool = False,
                      use_inv_skew: bool = False) -> SimResult:
        """
        Run market simulation.
        
        Args:
            duration_sec: Simulation duration
            use_queue_aware: Enable queue-aware quoting
            use_inv_skew: Enable inventory-skew
        
        Returns:
            SimResult with metrics
        """
        start_time = time.time()
        end_time = start_time + duration_sec
        
        fills_total = 0
        fills_maker = 0
        fills_taker = 0
        slippage_sum = 0.0
        order_age_sum = 0.0
        fees_sum = 0.0
        
        self.position = 0.0
        self.fills = []
        self.orders = []
        
        tick_count = 0
        current_time = start_time
        
        while current_time < end_time:
            tick_count += 1
            
            # Generate book
            book = self.generate_book()
            mid = book['mid']
            
            # Generate quotes
            spread_half_bps = self.spread_bps / 2.0
            bid_price = mid * (1 - spread_half_bps / 10000.0)
            ask_price = mid * (1 + spread_half_bps / 10000.0)
            
            # Apply inventory skew
            bid_price, ask_price = self.apply_inventory_skew_to_quotes(
                bid_price, ask_price, use_inv_skew
            )
            
            # Create quotes
            bid_quote = Quote(symbol="SIM", side="bid", price=bid_price, size=1.0)
            ask_quote = Quote(symbol="SIM", side="ask", price=ask_price, size=1.0)
            
            # Calculate fill probabilities
            bid_fill_prob = self.calculate_fill_probability(bid_quote, book, use_queue_aware)
            ask_fill_prob = self.calculate_fill_probability(ask_quote, book, use_queue_aware)
            
            # Simulate fills
            if random.random() < bid_fill_prob * 0.1:  # Scale down to ~10% per tick
                # Bid filled (bought)
                self.position += 1.0
                fills_total += 1
                fills_maker += 1
                fees_sum -= 2.0  # Maker rebate
                order_age_sum += self.tick_interval_ms
            
            if random.random() < ask_fill_prob * 0.1:
                # Ask filled (sold)
                self.position -= 1.0
                fills_total += 1
                fills_maker += 1
                fees_sum -= 2.0
                order_age_sum += self.tick_interval_ms
            
            # Advance time
            current_time += self.tick_interval_ms / 1000.0
        
        # Calculate metrics
        duration_actual = time.time() - start_time
        taker_share_pct = (fills_taker / fills_total * 100.0) if fills_total > 0 else 0.0
        avg_slippage_bps = (slippage_sum / fills_total) if fills_total > 0 else 0.0
        avg_order_age_ms = (order_age_sum / fills_total) if fills_total > 0 else 0.0
        net_bps = -fees_sum  # Simplified: just fees, no PnL modeling
        
        return SimResult(
            duration_sec=duration_actual,
            fills_total=fills_total,
            fills_maker=fills_maker,
            fills_taker=fills_taker,
            taker_share_pct=taker_share_pct,
            avg_slippage_bps=avg_slippage_bps,
            avg_order_age_ms=avg_order_age_ms,
            net_bps=net_bps,
            final_inventory=self.position
        )
