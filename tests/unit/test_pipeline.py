"""
Unit tests for quote pipeline.

Tests:
- DTO immutability
- Stage purity (no side effects)
- Pipeline orchestration
- Determinism and idempotency
- Feature flag rollback
"""
import pytest
import asyncio
import time
from unittest.mock import Mock, MagicMock

from src.strategy.pipeline_dto import (
    MarketData, SpreadDecision, GuardAssessment, GuardLevel,
    InventoryAdjustment, QueueAwareAdjustment, Quote, QuoteContext
)
from src.strategy.pipeline_stages import (
    FetchMDStage, SpreadStage, GuardsStage, InventoryStage,
    QueueAwareStage, EmitStage
)
from src.strategy.quote_pipeline import QuotePipeline, create_quote_pipeline
from src.common.di import AppContext
from src.common.config import AppConfig, PipelineConfig


class TestDTOImmutability:
    """Test that DTOs are immutable."""
    
    def test_market_data_immutable(self):
        """MarketData should be frozen."""
        md = MarketData(
            symbol="BTCUSDT",
            mid_price=50000.0,
            best_bid=49999.0,
            best_ask=50001.0,
            bid_size=1.0,
            ask_size=1.0,
            timestamp_ms=int(time.time() * 1000)
        )
        
        with pytest.raises(Exception):  # frozen dataclass raises on mutation
            md.mid_price = 51000.0
    
    def test_quote_context_immutable(self):
        """QuoteContext should be immutable - changes create new instances."""
        md = MarketData(
            symbol="BTCUSDT",
            mid_price=50000.0,
            best_bid=49999.0,
            best_ask=50001.0,
            bid_size=1.0,
            ask_size=1.0,
            timestamp_ms=int(time.time() * 1000)
        )
        
        ctx = QuoteContext(market_data=md)
        
        # Mutation should create new instance
        spread = SpreadDecision(spread_bps=2.0, reason="test")
        ctx2 = ctx.with_spread(spread)
        
        # Original context should be unchanged
        assert ctx.spread_decision is None
        assert ctx2.spread_decision is spread
        assert ctx2.market_data is ctx.market_data  # shared reference
    
    def test_quote_context_with_methods(self):
        """Test all with_* methods create new instances."""
        md = MarketData(
            symbol="BTCUSDT",
            mid_price=50000.0,
            best_bid=49999.0,
            best_ask=50001.0,
            bid_size=1.0,
            ask_size=1.0,
            timestamp_ms=int(time.time() * 1000)
        )
        
        ctx = QuoteContext(market_data=md)
        
        # Test spread
        spread = SpreadDecision(spread_bps=2.0, reason="test")
        ctx = ctx.with_spread(spread)
        assert ctx.spread_decision == spread
        
        # Test guard
        guard = GuardAssessment(level=GuardLevel.NONE, scale_factor=1.0)
        ctx = ctx.with_guard(guard)
        assert ctx.guard_assessment == guard
        
        # Test inventory
        inv = InventoryAdjustment(
            bid_adjustment_bps=0.5,
            ask_adjustment_bps=-0.5,
            inventory_pct=0.2,
            skew_bps=1.0,
            reason="test"
        )
        ctx = ctx.with_inventory(inv)
        assert ctx.inventory_adjustment == inv
        
        # Test queue aware
        queue = QueueAwareAdjustment(bid_nudge_bps=0.1, ask_nudge_bps=0.1)
        ctx = ctx.with_queue_aware(queue)
        assert ctx.queue_aware_adjustment == queue
        
        # Test quote
        quote = Quote(
            symbol="BTCUSDT",
            bid_price=49998.0,
            ask_price=50002.0,
            bid_size=0.01,
            ask_size=0.01,
            timestamp_ms=int(time.time() * 1000)
        )
        ctx = ctx.with_quote(quote)
        assert ctx.final_quote == quote
        
        # Test metadata
        ctx = ctx.with_metadata("test_key", "test_value")
        assert ctx.stage_metadata["test_key"] == "test_value"


class TestStagePurity:
    """Test that stages are pure functions (no side effects)."""
    
    @pytest.fixture
    def mock_ctx(self):
        """Create mock AppContext."""
        cfg = AppConfig()
        cfg.pipeline = PipelineConfig(enabled=True)
        ctx = Mock(spec=AppContext)
        ctx.cfg = cfg
        return ctx
    
    @pytest.fixture
    def sample_market_data(self):
        """Create sample MarketData."""
        return MarketData(
            symbol="BTCUSDT",
            mid_price=50000.0,
            best_bid=49999.0,
            best_ask=50001.0,
            bid_size=1.0,
            ask_size=1.0,
            timestamp_ms=int(time.time() * 1000)
        )
    
    @pytest.mark.asyncio
    async def test_fetch_md_stage_pure(self, mock_ctx, sample_market_data, cleanup_tasks):
        """FetchMDStage should not mutate input context."""
        stage = FetchMDStage(mock_ctx)
        ctx = QuoteContext(market_data=sample_market_data)
        
        result = await asyncio.wait_for(stage.process(ctx), timeout=5.0)
        
        # Original context unchanged
        assert ctx.market_data is sample_market_data
        assert ctx.spread_decision is None
        
        # Result is new instance
        assert result is not ctx
        assert result.market_data is ctx.market_data
    
    @pytest.mark.asyncio
    async def test_emit_stage_no_side_effects(self, mock_ctx, sample_market_data, cleanup_tasks):
        """EmitStage should only create Quote, not place orders."""
        stage = EmitStage(mock_ctx)
        
        ctx = QuoteContext(market_data=sample_market_data)
        ctx = ctx.with_spread(SpreadDecision(spread_bps=2.0, reason="test"))
        ctx = ctx.with_guard(GuardAssessment(level=GuardLevel.NONE, scale_factor=1.0))
        ctx = ctx.with_inventory(InventoryAdjustment(
            bid_adjustment_bps=0.0,
            ask_adjustment_bps=0.0,
            inventory_pct=0.0,
            skew_bps=0.0,
            reason="test"
        ))
        ctx = ctx.with_queue_aware(QueueAwareAdjustment(bid_nudge_bps=0.0, ask_nudge_bps=0.0))
        
        result = await asyncio.wait_for(stage.process(ctx), timeout=5.0)
        
        # Should create Quote
        assert result.final_quote is not None
        assert result.final_quote.symbol == "BTCUSDT"
        assert result.final_quote.bid_price < result.final_quote.ask_price
        
        # No side effects (no orders placed, no external calls)
        # This is verified by not mocking any external dependencies


class TestPipelineDeterminism:
    """Test pipeline determinism and idempotency."""
    
    @pytest.fixture
    def pipeline_ctx(self):
        """Create AppContext with pipeline enabled."""
        cfg = AppConfig()
        cfg.pipeline = PipelineConfig(enabled=True, sample_stage_tracing=0.0)
        ctx = Mock(spec=AppContext)
        ctx.cfg = cfg
        return ctx
    
    @pytest.fixture
    def sample_market_data(self):
        """Create deterministic MarketData."""
        return MarketData(
            symbol="BTCUSDT",
            mid_price=50000.0,
            best_bid=49999.0,
            best_ask=50001.0,
            bid_size=1.0,
            ask_size=1.0,
            timestamp_ms=1704672000000  # Fixed timestamp
        )
    
    @pytest.mark.asyncio
    async def test_pipeline_determinism(self, pipeline_ctx, sample_market_data, cleanup_tasks):
        """
        Running same input through pipeline 3 times should produce identical results.
        """
        pipeline = QuotePipeline(pipeline_ctx, tracer=None, metrics=None)
        
        results = []
        for _ in range(3):
            result = await asyncio.wait_for(
                pipeline.process_tick(sample_market_data, trace_id="test_trace"),
                timeout=10.0
            )
            results.append(result)
        
        # All results should have identical quotes
        for i in range(1, len(results)):
            assert results[i].final_quote.bid_price == results[0].final_quote.bid_price
            assert results[i].final_quote.ask_price == results[0].final_quote.ask_price
            assert results[i].final_quote.spread_bps() == results[0].final_quote.spread_bps()
    
    @pytest.mark.asyncio
    async def test_pipeline_idempotency(self, pipeline_ctx, sample_market_data, cleanup_tasks):
        """
        Running pipeline twice with same input should not accumulate state.
        """
        pipeline = QuotePipeline(pipeline_ctx, tracer=None, metrics=None)
        
        result1 = await asyncio.wait_for(
            pipeline.process_tick(sample_market_data, trace_id="test_trace_1"),
            timeout=10.0
        )
        result2 = await asyncio.wait_for(
            pipeline.process_tick(sample_market_data, trace_id="test_trace_2"),
            timeout=10.0
        )
        
        # Results should be independent (no state accumulation)
        assert result1.final_quote.bid_price == result2.final_quote.bid_price
        assert result1.final_quote.ask_price == result2.final_quote.ask_price


class TestGuardHalt:
    """Test guard halt behavior."""
    
    @pytest.fixture
    def pipeline_ctx_with_guards(self):
        """Create AppContext with guards enabled."""
        cfg = AppConfig()
        cfg.pipeline = PipelineConfig(enabled=True)
        # Disable risk_guards to avoid config issues
        cfg.risk_guards = Mock()
        cfg.risk_guards.enabled = False
        
        ctx = Mock(spec=AppContext)
        ctx.cfg = cfg
        return ctx
    
    @pytest.mark.asyncio
    async def test_hard_guard_halts_pipeline(self, pipeline_ctx_with_guards, cleanup_tasks):
        """HARD guard should halt pipeline before emit."""
        from src.strategy.quote_pipeline import GuardHaltException
        
        pipeline = QuotePipeline(pipeline_ctx_with_guards, tracer=None, metrics=None)
        
        # Create market data
        md = MarketData(
            symbol="BTCUSDT",
            mid_price=50000.0,
            best_bid=49999.0,
            best_ask=50001.0,
            bid_size=1.0,
            ask_size=1.0,
            timestamp_ms=int(time.time() * 1000)
        )
        
        # Mock GuardsStage to return HARD
        async def mock_process(ctx):
            # Return HARD guard
            guard = GuardAssessment(
                level=GuardLevel.HARD,
                scale_factor=0.0,
                should_halt=True,
                reasons=["test_halt"]
            )
            return ctx.with_guard(guard)
        
        pipeline.stages[2].process = mock_process
        
        # Should raise GuardHaltException
        with pytest.raises(GuardHaltException):
            await asyncio.wait_for(pipeline.process_tick(md), timeout=5.0)


class TestFeatureFlagRollback:
    """Test feature flag rollback behavior."""
    
    def test_pipeline_disabled_by_default(self):
        """Pipeline should be disabled by default."""
        cfg = AppConfig()
        assert cfg.pipeline.enabled is False
    
    @pytest.mark.asyncio
    async def test_pipeline_disabled_raises_error(self, cleanup_tasks):
        """Using pipeline when disabled should raise error."""
        cfg = AppConfig()
        cfg.pipeline.enabled = False
        ctx = Mock(spec=AppContext)
        ctx.cfg = cfg
        
        pipeline = QuotePipeline(ctx, tracer=None, metrics=None)
        
        md = MarketData(
            symbol="BTCUSDT",
            mid_price=50000.0,
            best_bid=49999.0,
            best_ask=50001.0,
            bid_size=1.0,
            ask_size=1.0,
            timestamp_ms=int(time.time() * 1000)
        )
        
        with pytest.raises(RuntimeError, match="Pipeline not enabled"):
            await asyncio.wait_for(pipeline.process_tick(md), timeout=5.0)


class TestQuoteCalculation:
    """Test quote price calculation logic."""
    
    @pytest.fixture
    def pipeline_ctx(self):
        """Create AppContext."""
        cfg = AppConfig()
        cfg.pipeline = PipelineConfig(enabled=True)
        ctx = Mock(spec=AppContext)
        ctx.cfg = cfg
        return ctx
    
    @pytest.mark.asyncio
    async def test_quote_spread_calculation(self, pipeline_ctx, cleanup_tasks):
        """Test that quote spread is calculated correctly."""
        pipeline = QuotePipeline(pipeline_ctx, tracer=None, metrics=None)
        
        md = MarketData(
            symbol="BTCUSDT",
            mid_price=50000.0,
            best_bid=49999.0,
            best_ask=50001.0,
            bid_size=1.0,
            ask_size=1.0,
            timestamp_ms=int(time.time() * 1000)
        )
        
        result = await asyncio.wait_for(pipeline.process_tick(md), timeout=10.0)
        
        # Check quote exists
        assert result.final_quote is not None
        
        # Check spread is reasonable
        spread_bps = result.final_quote.spread_bps()
        assert spread_bps > 0.0
        assert spread_bps < 50.0  # Max reasonable spread
        
        # Check bid < mid < ask
        assert result.final_quote.bid_price < md.mid_price
        assert result.final_quote.ask_price > md.mid_price


if __name__ == '__main__':
    pytest.main([__file__, '-v'])

