"""
Immutable DTOs for quote pipeline stages.

All DTOs are frozen dataclasses for immutability and thread-safety.
"""
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Any
from enum import Enum


class GuardLevel(str, Enum):
    """Risk guard severity level."""
    NONE = "none"
    SOFT = "soft"  # Scale down positions/spreads
    HARD = "hard"  # Halt new orders


@dataclass(frozen=True)
class MarketData:
    """
    Market data snapshot for a symbol.
    
    Immutable input to pipeline stages.
    """
    symbol: str
    mid_price: float
    best_bid: float
    best_ask: float
    bid_size: float
    ask_size: float
    timestamp_ms: int
    orderbook: Optional[Dict[str, Any]] = None  # Full orderbook if available
    
    def __post_init__(self):
        """Validate market data."""
        if self.mid_price <= 0:
            raise ValueError(f"Invalid mid_price: {self.mid_price}")
        if self.best_bid <= 0 or self.best_ask <= 0:
            raise ValueError(f"Invalid bid/ask: {self.best_bid}/{self.best_ask}")


@dataclass(frozen=True)
class SpreadDecision:
    """
    Spread calculation result from adaptive spread stage.
    """
    spread_bps: float
    reason: str  # "adaptive", "vol_adjusted", "default"
    volatility: Optional[float] = None
    liquidity_score: Optional[float] = None
    base_spread_bps: Optional[float] = None


@dataclass(frozen=True)
class GuardAssessment:
    """
    Risk guard assessment result.
    """
    level: GuardLevel
    scale_factor: float = 1.0  # 0.0-1.0 multiplier for SOFT guards
    reasons: List[str] = field(default_factory=list)
    should_halt: bool = False
    
    def __post_init__(self):
        """Validate guard assessment."""
        if not (0.0 <= self.scale_factor <= 1.0):
            object.__setattr__(self, 'scale_factor', max(0.0, min(1.0, self.scale_factor)))


@dataclass(frozen=True)
class InventoryAdjustment:
    """
    Inventory skew adjustment for bid/ask spreads.
    """
    bid_adjustment_bps: float
    ask_adjustment_bps: float
    inventory_pct: float
    skew_bps: float
    reason: str


@dataclass(frozen=True)
class QueueAwareAdjustment:
    """
    Queue-aware micro-repositioning adjustment.
    """
    bid_nudge_bps: float
    ask_nudge_bps: float
    estimated_queue_pos: Optional[int] = None
    reason: str = "queue_aware"


@dataclass(frozen=True)
class Quote:
    """
    Final quote with bid/ask prices and sizes.
    """
    symbol: str
    bid_price: float
    ask_price: float
    bid_size: float
    ask_size: float
    timestamp_ms: int
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    def spread_bps(self) -> float:
        """Calculate spread in basis points."""
        mid = (self.bid_price + self.ask_price) / 2
        if mid <= 0:
            return 0.0
        return (self.ask_price - self.bid_price) / mid * 10000.0


@dataclass(frozen=True)
class QuoteContext:
    """
    Immutable context passed through pipeline stages.
    
    Each stage reads from this context and returns a new modified copy.
    No mutation of existing context allowed.
    """
    # Input data
    market_data: MarketData
    
    # Stage results (populated as pipeline progresses)
    spread_decision: Optional[SpreadDecision] = None
    guard_assessment: Optional[GuardAssessment] = None
    inventory_adjustment: Optional[InventoryAdjustment] = None
    queue_aware_adjustment: Optional[QueueAwareAdjustment] = None
    final_quote: Optional[Quote] = None
    
    # Metadata
    trace_id: str = ""
    stage_metadata: Dict[str, Any] = field(default_factory=dict)
    
    def with_spread(self, spread: SpreadDecision) -> 'QuoteContext':
        """Return new context with spread decision."""
        return QuoteContext(
            market_data=self.market_data,
            spread_decision=spread,
            guard_assessment=self.guard_assessment,
            inventory_adjustment=self.inventory_adjustment,
            queue_aware_adjustment=self.queue_aware_adjustment,
            final_quote=self.final_quote,
            trace_id=self.trace_id,
            stage_metadata=self.stage_metadata
        )
    
    def with_guard(self, guard: GuardAssessment) -> 'QuoteContext':
        """Return new context with guard assessment."""
        return QuoteContext(
            market_data=self.market_data,
            spread_decision=self.spread_decision,
            guard_assessment=guard,
            inventory_adjustment=self.inventory_adjustment,
            queue_aware_adjustment=self.queue_aware_adjustment,
            final_quote=self.final_quote,
            trace_id=self.trace_id,
            stage_metadata=self.stage_metadata
        )
    
    def with_inventory(self, inventory: InventoryAdjustment) -> 'QuoteContext':
        """Return new context with inventory adjustment."""
        return QuoteContext(
            market_data=self.market_data,
            spread_decision=self.spread_decision,
            guard_assessment=self.guard_assessment,
            inventory_adjustment=inventory,
            queue_aware_adjustment=self.queue_aware_adjustment,
            final_quote=self.final_quote,
            trace_id=self.trace_id,
            stage_metadata=self.stage_metadata
        )
    
    def with_queue_aware(self, queue: QueueAwareAdjustment) -> 'QuoteContext':
        """Return new context with queue-aware adjustment."""
        return QuoteContext(
            market_data=self.market_data,
            spread_decision=self.spread_decision,
            guard_assessment=self.guard_assessment,
            inventory_adjustment=self.inventory_adjustment,
            queue_aware_adjustment=queue,
            final_quote=self.final_quote,
            trace_id=self.trace_id,
            stage_metadata=self.stage_metadata
        )
    
    def with_quote(self, quote: Quote) -> 'QuoteContext':
        """Return new context with final quote."""
        return QuoteContext(
            market_data=self.market_data,
            spread_decision=self.spread_decision,
            guard_assessment=self.guard_assessment,
            inventory_adjustment=self.inventory_adjustment,
            queue_aware_adjustment=self.queue_aware_adjustment,
            final_quote=quote,
            trace_id=self.trace_id,
            stage_metadata=self.stage_metadata
        )
    
    def with_metadata(self, key: str, value: Any) -> 'QuoteContext':
        """Return new context with updated metadata."""
        new_metadata = dict(self.stage_metadata)
        new_metadata[key] = value
        return QuoteContext(
            market_data=self.market_data,
            spread_decision=self.spread_decision,
            guard_assessment=self.guard_assessment,
            inventory_adjustment=self.inventory_adjustment,
            queue_aware_adjustment=self.queue_aware_adjustment,
            final_quote=self.final_quote,
            trace_id=self.trace_id,
            stage_metadata=new_metadata
        )

