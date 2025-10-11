"""
Pipeline stages for quote generation.

Each stage is a pure function: QuoteContext -> QuoteContext
No side effects except in EmitStage.
"""
from abc import ABC, abstractmethod
from typing import Optional, Dict, Any
from dataclasses import dataclass

from src.strategy.pipeline_dto import (
    QuoteContext, SpreadDecision, GuardAssessment, GuardLevel,
    InventoryAdjustment, QueueAwareAdjustment, Quote
)
from src.common.di import AppContext


class PipelineStage(ABC):
    """
    Base class for pipeline stages.
    
    Each stage:
    - Receives immutable QuoteContext
    - Returns new QuoteContext (no mutation)
    - Can be disabled via feature flag
    """
    
    def __init__(self, ctx: AppContext, enabled: bool = True):
        """
        Initialize stage.
        
        Args:
            ctx: Application context with config
            enabled: Feature flag for this stage
        """
        self.ctx = ctx
        self.enabled = enabled
    
    @abstractmethod
    async def process(self, context: QuoteContext) -> QuoteContext:
        """
        Process context and return new context.
        
        Args:
            context: Input context
        
        Returns:
            New context with stage results
        """
        pass
    
    def get_name(self) -> str:
        """Get stage name for tracing."""
        return self.__class__.__name__


class FetchMDStage(PipelineStage):
    """
    Stage 1: Fetch market data with MD-Cache integration.
    
    Freshness modes:
    - guards: fresh_only (synchronous refresh if stale)
    - pricing: fresh_ms_for_pricing threshold
    - other: stale_ok (return stale, async refresh)
    """
    
    def __init__(self, ctx: AppContext, enabled: bool = True, md_cache=None):
        """
        Initialize fetch MD stage.
        
        Args:
            ctx: Application context
            enabled: Feature flag
            md_cache: Optional MD cache instance
        """
        super().__init__(ctx, enabled)
        self.md_cache = md_cache
        
        # Load MD cache config
        md_cache_cfg = getattr(ctx.cfg, 'md_cache', None)
        self.md_cache_enabled = md_cache_cfg and md_cache_cfg.enabled if md_cache_cfg else False
        self.fresh_ms_for_pricing = md_cache_cfg.fresh_ms_for_pricing if md_cache_cfg else 60
    
    async def process(self, context: QuoteContext) -> QuoteContext:
        """Fetch/validate market data with caching."""
        if not self.enabled:
            return context
        
        md = context.market_data
        
        # Validate
        if md.mid_price <= 0:
            raise ValueError(f"Invalid mid_price: {md.mid_price}")
        
        # MD-Cache integration: fetch orderbook if cache is enabled
        cache_metadata = {}
        if self.md_cache_enabled and self.md_cache:
            # Determine freshness mode based on use case
            use_case = "general"
            fresh_only = False
            max_age_ms = None
            
            # Check if we're in guards assessment phase (heuristic: check metadata)
            if context.metadata.get("guard_assessment_needed"):
                use_case = "guards"
                fresh_only = True  # Guards need fresh data
            elif context.metadata.get("spread_calculation_needed"):
                use_case = "pricing"
                max_age_ms = self.fresh_ms_for_pricing
            
            # Fetch from cache
            orderbook, cache_meta = await self.md_cache.get_orderbook(
                symbol=md.symbol,
                depth=50,  # Default depth
                max_age_ms=max_age_ms,
                fresh_only=fresh_only,
                use_case=use_case
            )
            
            cache_metadata = cache_meta
            
            # Update context with orderbook if available
            if orderbook:
                context = context.with_metadata("orderbook", orderbook)
                context = context.with_metadata("cache_hit", cache_meta.get("cache_hit", False))
                context = context.with_metadata("cache_age_ms", cache_meta.get("age_ms", 0))
                context = context.with_metadata("used_stale", cache_meta.get("used_stale", False))
        
        # Add validation metadata
        context = context.with_metadata("fetch_md_validated", True)
        context = context.with_metadata("md_cache_meta", cache_metadata)
        
        return context


class SpreadStage(PipelineStage):
    """
    Stage 2: Calculate spread using adaptive spread estimator.
    """
    
    def __init__(self, ctx: AppContext, enabled: bool = True):
        super().__init__(ctx, enabled)
        
        # Load adaptive spread config
        from src.strategy.adaptive_spread import AdaptiveSpreadEstimator
        adaptive_cfg = getattr(ctx.cfg, 'adaptive_spread', None)
        if adaptive_cfg and adaptive_cfg.enabled:
            self.estimator = AdaptiveSpreadEstimator(adaptive_cfg)
        else:
            self.estimator = None
    
    async def process(self, context: QuoteContext) -> QuoteContext:
        """Calculate optimal spread."""
        if not self.enabled or not self.estimator:
            # Fallback: use default spread
            default_spread = getattr(self.ctx.cfg, 'base_spread_bps', 2.0)
            spread = SpreadDecision(
                spread_bps=default_spread,
                reason="default_no_estimator"
            )
            return context.with_spread(spread)
        
        md = context.market_data
        
        # Calculate adaptive spread
        spread_bps = self.estimator.compute_spread_bps(
            symbol=md.symbol,
            mid_price=md.mid_price,
            orderbook=md.orderbook
        )
        
        spread = SpreadDecision(
            spread_bps=spread_bps,
            reason="adaptive",
            base_spread_bps=getattr(self.ctx.cfg, 'base_spread_bps', 2.0)
        )
        
        return context.with_spread(spread)


class GuardsStage(PipelineStage):
    """
    Stage 3: Assess risk guards.
    """
    
    def __init__(self, ctx: AppContext, enabled: bool = True):
        super().__init__(ctx, enabled)
        
        # Load risk guards config
        from src.risk.risk_guards import RiskGuards
        guards_cfg = getattr(ctx.cfg, 'risk_guards', None)
        if guards_cfg and guards_cfg.enabled:
            self.risk_guards = RiskGuards(guards_cfg)
        else:
            self.risk_guards = None
    
    async def process(self, context: QuoteContext) -> QuoteContext:
        """Assess risk guards."""
        if not self.enabled or not self.risk_guards:
            # No guards active
            assessment = GuardAssessment(
                level=GuardLevel.NONE,
                scale_factor=1.0,
                reasons=["guards_disabled"]
            )
            return context.with_guard(assessment)
        
        md = context.market_data
        
        # Assess guards
        level, reason = self.risk_guards.assess(
            symbol=md.symbol,
            mid_price=md.mid_price
        )
        
        # Convert level to scale factor
        if level == "HARD":
            guard_level = GuardLevel.HARD
            scale_factor = 0.0
            should_halt = True
        elif level == "SOFT":
            guard_level = GuardLevel.SOFT
            scale_factor = 0.5  # Scale down to 50%
            should_halt = False
        else:
            guard_level = GuardLevel.NONE
            scale_factor = 1.0
            should_halt = False
        
        assessment = GuardAssessment(
            level=guard_level,
            scale_factor=scale_factor,
            reasons=[reason] if reason else [],
            should_halt=should_halt
        )
        
        return context.with_guard(assessment)


class InventoryStage(PipelineStage):
    """
    Stage 4: Apply inventory skew adjustments.
    """
    
    def __init__(self, ctx: AppContext, enabled: bool = True):
        super().__init__(ctx, enabled)
        
        # Load inventory skew config
        self.inventory_cfg = getattr(ctx.cfg, 'inventory_skew', None)
        self.inventory_enabled = self.inventory_cfg and self.inventory_cfg.enabled if self.inventory_cfg else False
    
    async def process(self, context: QuoteContext) -> QuoteContext:
        """Apply inventory skew."""
        if not self.enabled or not self.inventory_enabled:
            # No inventory adjustment
            adjustment = InventoryAdjustment(
                bid_adjustment_bps=0.0,
                ask_adjustment_bps=0.0,
                inventory_pct=0.0,
                skew_bps=0.0,
                reason="inventory_disabled"
            )
            return context.with_inventory(adjustment)
        
        md = context.market_data
        
        # Get current inventory (stub - would come from position tracker)
        from src.risk.inventory_skew import compute_skew_bps, apply_inventory_skew, get_inventory_pct
        
        inventory_pct = get_inventory_pct(
            symbol=md.symbol,
            position=0.0,  # Placeholder
            target=0.0,
            max_position=100.0
        )
        
        skew_bps = compute_skew_bps(inventory_pct, self.inventory_cfg)
        
        # Apply skew to spreads
        bid_adj, ask_adj = apply_inventory_skew(skew_bps)
        
        adjustment = InventoryAdjustment(
            bid_adjustment_bps=bid_adj,
            ask_adjustment_bps=ask_adj,
            inventory_pct=inventory_pct,
            skew_bps=skew_bps,
            reason="inventory_skew"
        )
        
        return context.with_inventory(adjustment)


class QueueAwareStage(PipelineStage):
    """
    Stage 5: Apply queue-aware micro-repositioning.
    """
    
    def __init__(self, ctx: AppContext, enabled: bool = True):
        super().__init__(ctx, enabled)
        
        # Load queue-aware config
        from src.strategy.queue_aware import QueueAwareRepricer
        queue_cfg = getattr(ctx.cfg, 'queue_aware', None)
        if queue_cfg and queue_cfg.enabled:
            self.repricer = QueueAwareRepricer(queue_cfg)
        else:
            self.repricer = None
    
    async def process(self, context: QuoteContext) -> QuoteContext:
        """Apply queue-aware adjustments."""
        if not self.enabled or not self.repricer:
            # No queue-aware adjustment
            adjustment = QueueAwareAdjustment(
                bid_nudge_bps=0.0,
                ask_nudge_bps=0.0,
                reason="queue_aware_disabled"
            )
            return context.with_queue_aware(adjustment)
        
        md = context.market_data
        
        # Estimate queue position and nudge
        from src.strategy.queue_aware import estimate_queue_position
        
        # Placeholder: would use actual orderbook
        bid_nudge = 0.0
        ask_nudge = 0.0
        
        adjustment = QueueAwareAdjustment(
            bid_nudge_bps=bid_nudge,
            ask_nudge_bps=ask_nudge,
            reason="queue_aware"
        )
        
        return context.with_queue_aware(adjustment)


class EmitStage(PipelineStage):
    """
    Stage 6: Emit final quote (calculate prices and create Quote object).
    
    This stage has NO side effects - it just constructs the Quote.
    Actual order placement happens outside pipeline.
    """
    
    async def process(self, context: QuoteContext) -> QuoteContext:
        """Calculate final bid/ask prices and create quote."""
        if not self.enabled:
            return context
        
        md = context.market_data
        
        # Get all adjustments
        spread_bps = context.spread_decision.spread_bps if context.spread_decision else 2.0
        guard_scale = context.guard_assessment.scale_factor if context.guard_assessment else 1.0
        bid_adj = context.inventory_adjustment.bid_adjustment_bps if context.inventory_adjustment else 0.0
        ask_adj = context.inventory_adjustment.ask_adjustment_bps if context.inventory_adjustment else 0.0
        bid_nudge = context.queue_aware_adjustment.bid_nudge_bps if context.queue_aware_adjustment else 0.0
        ask_nudge = context.queue_aware_adjustment.ask_nudge_bps if context.queue_aware_adjustment else 0.0
        
        # Apply guard scale to spread
        effective_spread_bps = spread_bps * guard_scale
        
        # Calculate half-spread in bps
        half_spread_bps = effective_spread_bps / 2.0
        
        # Calculate bid/ask spreads with adjustments
        bid_spread_bps = half_spread_bps + bid_adj + bid_nudge
        ask_spread_bps = half_spread_bps + ask_adj + ask_nudge
        
        # Convert bps to prices
        mid = md.mid_price
        bid_price = mid * (1.0 - bid_spread_bps / 10000.0)
        ask_price = mid * (1.0 + ask_spread_bps / 10000.0)
        
        # Size calculation (stub - would use actual sizing logic)
        default_size = 0.01  # Placeholder
        
        # Create quote
        quote = Quote(
            symbol=md.symbol,
            bid_price=bid_price,
            ask_price=ask_price,
            bid_size=default_size,
            ask_size=default_size,
            timestamp_ms=md.timestamp_ms,
            metadata={
                "spread_bps": effective_spread_bps,
                "guard_scale": guard_scale,
                "bid_adj_bps": bid_adj,
                "ask_adj_bps": ask_adj
            }
        )
        
        return context.with_quote(quote)

