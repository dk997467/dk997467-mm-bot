"""
Quote Pipeline Orchestrator.

Orchestrates quote generation through pipeline stages with tracing and metrics.
"""
import time
import uuid
from typing import List, Dict, Any, Optional
from contextlib import asynccontextmanager

from src.strategy.pipeline_dto import QuoteContext, MarketData, GuardLevel
from src.strategy.pipeline_stages import (
    PipelineStage, FetchMDStage, SpreadStage, GuardsStage,
    InventoryStage, QueueAwareStage, EmitStage
)
from src.common.di import AppContext
from src.monitoring.tracer import PerformanceTracer, Trace
from src.monitoring.stage_metrics import StageMetrics


class QuotePipeline:
    """
    Pipeline orchestrator for quote generation.
    
    Features:
    - Stage-based processing (fetch_md → spread → guards → inventory → queue_aware → emit)
    - Immutable context passing (no side effects except in EmitStage)
    - Tracing and metrics integration
    - Feature flags for each stage
    - Rollback support (pipeline.enabled=false falls back to legacy)
    """
    
    # Stage names for metrics
    STAGE_FETCH_MD = "stage_fetch_md"
    STAGE_SPREAD = "stage_spread"
    STAGE_GUARDS = "stage_guards"
    STAGE_INVENTORY = "stage_inventory"
    STAGE_QUEUE_AWARE = "stage_queue_aware"
    STAGE_EMIT = "stage_emit"
    STAGE_TICK_TOTAL = "tick_total"
    
    def __init__(
        self,
        ctx: AppContext,
        tracer: Optional[PerformanceTracer] = None,
        metrics: Optional[StageMetrics] = None
    ):
        """
        Initialize pipeline.
        
        Args:
            ctx: Application context with configuration
            tracer: Performance tracer (optional)
            metrics: Stage metrics tracker (optional)
        """
        self.ctx = ctx
        self.tracer = tracer
        self.metrics = metrics
        
        # Load pipeline config
        pipeline_cfg = getattr(ctx.cfg, 'pipeline', None)
        self.enabled = pipeline_cfg.enabled if pipeline_cfg else False
        self.sample_stage_tracing = pipeline_cfg.sample_stage_tracing if pipeline_cfg else 0.2
        
        # Initialize stages
        self.stages: List[PipelineStage] = [
            FetchMDStage(ctx, enabled=True),
            SpreadStage(ctx, enabled=True),
            GuardsStage(ctx, enabled=True),
            InventoryStage(ctx, enabled=True),
            QueueAwareStage(ctx, enabled=True),
            EmitStage(ctx, enabled=True),
        ]
        
        # Stage name mapping for metrics
        self.stage_names = [
            self.STAGE_FETCH_MD,
            self.STAGE_SPREAD,
            self.STAGE_GUARDS,
            self.STAGE_INVENTORY,
            self.STAGE_QUEUE_AWARE,
            self.STAGE_EMIT,
        ]
        
        print(f"[PIPELINE] Initialized: enabled={self.enabled}, stages={len(self.stages)}, tracing={self.sample_stage_tracing}")
    
    async def process_tick(
        self,
        market_data: MarketData,
        trace_id: Optional[str] = None
    ) -> QuoteContext:
        """
        Process a single tick through the pipeline.
        
        Args:
            market_data: Market data snapshot
            trace_id: Optional trace ID for distributed tracing
        
        Returns:
            Final QuoteContext with quote and all stage results
        
        Raises:
            Exception: If any stage fails or guards trigger HARD halt
        """
        if not self.enabled:
            raise RuntimeError("Pipeline not enabled - use pipeline.enabled=true")
        
        # Generate trace ID if not provided
        if not trace_id:
            trace_id = f"tick_{market_data.symbol}_{uuid.uuid4().hex[:8]}"
        
        # Initialize context
        context = QuoteContext(
            market_data=market_data,
            trace_id=trace_id
        )
        
        # Start trace
        should_trace = self.tracer and self.tracer.should_trace() if self.tracer else False
        trace = None
        if should_trace:
            trace = self.tracer.start_trace(trace_id)
        
        tick_start_ns = time.monotonic_ns()
        
        try:
            # Process through each stage
            for stage, stage_name in zip(self.stages, self.stage_names):
                stage_start_ns = time.monotonic_ns()
                
                # Process stage
                context = await stage.process(context)
                
                stage_duration_ms = (time.monotonic_ns() - stage_start_ns) / 1_000_000
                
                # Record stage metrics
                if self.metrics:
                    self.metrics.record_stage_duration(stage_name, stage_duration_ms)
                
                # Record trace span
                if trace:
                    self.tracer.record_span(stage_name, stage_start_ns, time.monotonic_ns())
                
                # Check for HARD guard halt
                if context.guard_assessment and context.guard_assessment.should_halt:
                    if self.metrics:
                        self.metrics.record_guard_trip("hard_halt")
                    raise GuardHaltException(
                        f"HARD guard halt: {context.guard_assessment.reasons}"
                    )
            
            # Record total tick duration
            tick_duration_ms = (time.monotonic_ns() - tick_start_ns) / 1_000_000
            if self.metrics:
                self.metrics.record_stage_duration(self.STAGE_TICK_TOTAL, tick_duration_ms)
            
            # Finish trace
            if trace:
                self.tracer.finish_trace()
            
            return context
        
        except Exception as e:
            # Record error in metrics
            if self.metrics:
                self.metrics.record_guard_trip(f"pipeline_error_{type(e).__name__}")
            
            # Finish trace even on error
            if trace:
                self.tracer.finish_trace()
            
            raise
    
    async def process_batch(
        self,
        market_data_list: List[MarketData]
    ) -> List[QuoteContext]:
        """
        Process batch of ticks in parallel.
        
        Args:
            market_data_list: List of market data snapshots
        
        Returns:
            List of QuoteContexts
        """
        import asyncio
        
        tasks = [
            self.process_tick(md, trace_id=f"batch_{md.symbol}_{i}")
            for i, md in enumerate(market_data_list)
        ]
        
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        # Filter out exceptions
        valid_results = [r for r in results if isinstance(r, QuoteContext)]
        
        # Log exceptions
        for r in results:
            if isinstance(r, Exception):
                print(f"[PIPELINE] Batch error: {r}")
        
        return valid_results
    
    def get_metrics_summary(self) -> Dict[str, Any]:
        """Get metrics summary for all stages."""
        if not self.metrics:
            return {}
        
        return self.metrics.get_summary()
    
    def export_prometheus(self) -> str:
        """Export metrics in Prometheus format."""
        if not self.metrics:
            return ""
        
        return self.metrics.export_to_prometheus()


class GuardHaltException(Exception):
    """Exception raised when HARD guard triggers halt."""
    pass


# Factory function for easy instantiation
def create_quote_pipeline(
    ctx: AppContext,
    enable_tracing: bool = True,
    enable_metrics: bool = True
) -> QuotePipeline:
    """
    Create QuotePipeline with tracer and metrics.
    
    Args:
        ctx: Application context
        enable_tracing: Enable performance tracing
        enable_metrics: Enable metrics collection
    
    Returns:
        Configured QuotePipeline instance
    """
    # Create tracer if enabled
    tracer = None
    if enable_tracing:
        trace_cfg = getattr(ctx.cfg, 'trace', None)
        if trace_cfg and trace_cfg.enabled:
            tracer = PerformanceTracer(
                enabled=True,
                sample_rate=trace_cfg.sample_rate
            )
    
    # Create metrics if enabled
    metrics = None
    if enable_metrics:
        metrics = StageMetrics(deadline_ms=200.0)
    
    return QuotePipeline(ctx, tracer=tracer, metrics=metrics)

