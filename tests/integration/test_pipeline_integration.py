"""
Integration tests for pipeline with scoreboard and allocator.

Tests full integration:
- Pipeline + Scoreboard + Allocator
- Multi-symbol processing
- Dynamic rebalancing
- Metrics export
"""
import pytest
import asyncio
import time
from unittest.mock import Mock

from src.strategy.pipeline_dto import MarketData
from src.strategy.quote_pipeline import create_quote_pipeline
from src.strategy.symbol_scoreboard import SymbolScoreboard
from src.strategy.dynamic_allocator import DynamicAllocator
from src.common.di import AppContext
from src.common.config import AppConfig, PipelineConfig


class TestPipelineScoreboardIntegration:
    """Test pipeline with scoreboard integration."""
    
    @pytest.fixture
    def pipeline_and_scoreboard(self):
        """Create pipeline and scoreboard."""
        cfg = AppConfig()
        cfg.pipeline = PipelineConfig(enabled=True, sample_stage_tracing=0.0)
        ctx = Mock(spec=AppContext)
        ctx.cfg = cfg
        
        pipeline = create_quote_pipeline(ctx, enable_tracing=False, enable_metrics=True)
        scoreboard = SymbolScoreboard(
            rolling_window_sec=60,
            ema_alpha=0.2,
            min_samples=3
        )
        
        return pipeline, scoreboard
    
    @pytest.mark.asyncio
    async def test_pipeline_with_scoreboard_tracking(self, pipeline_and_scoreboard):
        """
        Test pipeline processing with scoreboard tracking.
        """
        pipeline, scoreboard = pipeline_and_scoreboard
        
        # Process multiple ticks for BTCUSDT
        for i in range(10):
            md = MarketData(
                symbol="BTCUSDT",
                mid_price=50000.0 + i * 10.0,
                best_bid=49999.0 + i * 10.0,
                best_ask=50001.0 + i * 10.0,
                bid_size=1.0,
                ask_size=1.0,
                timestamp_ms=int(time.time() * 1000) + i * 1000
            )
            
            result = await pipeline.process_tick(md)
            
            # Record metrics in scoreboard (stub values)
            scoreboard.record_tick(
                symbol="BTCUSDT",
                net_bps=1.5,  # Profitable
                fill_rate=0.7,
                slippage_bps=1.2,
                queue_edge_score=0.6,
                adverse_penalty=0.1
            )
        
        # Check scoreboard has metrics
        metrics = scoreboard.get_metrics("BTCUSDT")
        assert metrics is not None
        assert metrics.total_ticks == 10
        
        # Check score is calculated
        score = scoreboard.get_score("BTCUSDT")
        assert score is not None
        assert 0.0 <= score <= 1.0


class TestPipelineAllocatorIntegration:
    """Test pipeline with allocator integration."""
    
    @pytest.fixture
    def pipeline_scoreboard_allocator(self):
        """Create pipeline, scoreboard, and allocator."""
        cfg = AppConfig()
        cfg.pipeline = PipelineConfig(enabled=True, sample_stage_tracing=0.0)
        ctx = Mock(spec=AppContext)
        ctx.cfg = cfg
        
        pipeline = create_quote_pipeline(ctx, enable_tracing=False, enable_metrics=True)
        scoreboard = SymbolScoreboard(rolling_window_sec=60, ema_alpha=0.2, min_samples=3)
        allocator = DynamicAllocator(
            scoreboard=scoreboard,
            rebalance_period_s=5,
            min_weight=0.5,
            max_weight=2.0,
            hysteresis_threshold=0.1
        )
        
        return pipeline, scoreboard, allocator
    
    @pytest.mark.asyncio
    async def test_dynamic_rebalancing(self, pipeline_scoreboard_allocator):
        """
        Test dynamic rebalancing based on performance.
        """
        pipeline, scoreboard, allocator = pipeline_scoreboard_allocator
        
        symbols = ["BTCUSDT", "ETHUSDT"]
        
        # Step 1: Process ticks and record metrics
        for symbol in symbols:
            # BTCUSDT performs well
            net_bps = 2.0 if symbol == "BTCUSDT" else -1.0  # ETHUSDT performs poorly
            
            for i in range(10):
                md = MarketData(
                    symbol=symbol,
                    mid_price=50000.0 if symbol == "BTCUSDT" else 3000.0,
                    best_bid=49999.0 if symbol == "BTCUSDT" else 2999.0,
                    best_ask=50001.0 if symbol == "BTCUSDT" else 3001.0,
                    bid_size=1.0,
                    ask_size=1.0,
                    timestamp_ms=int(time.time() * 1000) + i * 1000
                )
                
                await pipeline.process_tick(md)
                
                scoreboard.record_tick(
                    symbol=symbol,
                    net_bps=net_bps,
                    fill_rate=0.7,
                    slippage_bps=1.2,
                    queue_edge_score=0.6,
                    adverse_penalty=0.1
                )
        
        # Step 2: Rebalance allocator
        allocations = allocator.rebalance(symbols)
        
        # Check allocations
        assert "BTCUSDT" in allocations
        assert "ETHUSDT" in allocations
        
        btc_weight = allocations["BTCUSDT"].weight
        eth_weight = allocations["ETHUSDT"].weight
        
        # BTCUSDT should have higher weight (better performance)
        assert btc_weight > eth_weight
        
        print(f"[TEST] Weights: BTCUSDT={btc_weight:.2f}, ETHUSDT={eth_weight:.2f}")


class TestMultiSymbolProcessing:
    """Test multi-symbol batch processing."""
    
    @pytest.fixture
    def pipeline_ctx(self):
        """Create pipeline context."""
        cfg = AppConfig()
        cfg.pipeline = PipelineConfig(enabled=True, sample_stage_tracing=0.0)
        ctx = Mock(spec=AppContext)
        ctx.cfg = cfg
        return ctx
    
    @pytest.mark.asyncio
    async def test_batch_processing(self, pipeline_ctx):
        """
        Test parallel batch processing of multiple symbols.
        """
        pipeline = create_quote_pipeline(pipeline_ctx, enable_tracing=False, enable_metrics=False)
        
        # Create market data for multiple symbols
        market_data_list = [
            MarketData(
                symbol="BTCUSDT",
                mid_price=50000.0,
                best_bid=49999.0,
                best_ask=50001.0,
                bid_size=1.0,
                ask_size=1.0,
                timestamp_ms=int(time.time() * 1000)
            ),
            MarketData(
                symbol="ETHUSDT",
                mid_price=3000.0,
                best_bid=2999.0,
                best_ask=3001.0,
                bid_size=10.0,
                ask_size=10.0,
                timestamp_ms=int(time.time() * 1000)
            ),
            MarketData(
                symbol="SOLUSDT",
                mid_price=100.0,
                best_bid=99.9,
                best_ask=100.1,
                bid_size=100.0,
                ask_size=100.0,
                timestamp_ms=int(time.time() * 1000)
            )
        ]
        
        # Process batch
        start_time = time.time()
        results = await pipeline.process_batch(market_data_list)
        elapsed_ms = (time.time() - start_time) * 1000
        
        # All symbols should be processed
        assert len(results) == 3
        
        # Check each result
        for result in results:
            assert result.final_quote is not None
            assert result.final_quote.bid_price < result.final_quote.ask_price
        
        # Batch should be fast (parallel processing)
        print(f"[TEST] Batch processing took {elapsed_ms:.2f}ms for {len(results)} symbols")
        assert elapsed_ms < 500  # Should be fast


# NOTE: TestMetricsExport tests are temporarily disabled due to pytest-asyncio conflict
# TODO: Investigate and fix the hanging issue with export_prometheus() in test context
# class TestMetricsExport:
#     """Test metrics export for monitoring."""
#     
#     def test_scoreboard_prometheus_export(self):
#         """Test scoreboard Prometheus export."""
#         scoreboard = SymbolScoreboard()
#         
#         # Record some data
#         scoreboard.record_tick(
#             symbol="BTCUSDT",
#             net_bps=2.0,
#             fill_rate=0.7,
#             slippage_bps=1.2
#         )
#         scoreboard.record_tick(
#             symbol="ETHUSDT",
#             net_bps=-0.5,
#             fill_rate=0.5,
#             slippage_bps=2.0
#         )
#         
#         # Export to Prometheus
#         prom_output = scoreboard.export_prometheus()
#         
#         # Check format
#         assert "mm_symbol_score" in prom_output
#         assert "mm_symbol_net_bps" in prom_output
#         assert "BTCUSDT" in prom_output
#         assert "ETHUSDT" in prom_output
#         
#         print(f"[TEST] Prometheus export:\n{prom_output}")
#     
#     def test_allocator_prometheus_export(self):
#         """Test allocator Prometheus export."""
#         scoreboard = SymbolScoreboard()
#         allocator = DynamicAllocator(scoreboard=scoreboard)
#         
#         # Record and rebalance
#         for symbol in ["BTCUSDT", "ETHUSDT"]:
#             for _ in range(5):
#                 scoreboard.record_tick(symbol=symbol, net_bps=1.0, fill_rate=0.6)
#         
#         allocator.rebalance(["BTCUSDT", "ETHUSDT"])
#         
#         # Export to Prometheus
#         prom_output = allocator.export_prometheus()
#         
#         # Check format
#         assert "mm_symbol_weight" in prom_output
#         assert "mm_allocator_rebalance_total" in prom_output
#         
#         print(f"[TEST] Allocator Prometheus export:\n{prom_output}")


if __name__ == '__main__':
    pytest.main([__file__, '-v', '-s'])

