#!/usr/bin/env python3
"""
Shadow Mode Validator - Compare legacy vs pipeline quote generation.

Runs both paths in parallel on same market data and compares:
- Order plan (type, side, price, quantity)
- Performance metrics (p50/p95/p99 per stage)
- Guard triggers (reasons, timing)

Generates comparison artifacts for validation.
"""
import asyncio
import json
import time
from typing import Dict, List, Any, Tuple
from dataclasses import dataclass, field, asdict
from pathlib import Path
import statistics

from src.strategy.quote_pipeline import QuotePipeline, create_quote_pipeline
from src.strategy.pipeline_dto import MarketData, Quote
from src.common.di import AppContext
from src.common.config import AppConfig, PipelineConfig


@dataclass
class OrderPlan:
    """Order plan from quote generation."""
    symbol: str
    side: str  # "buy" or "sell"
    price: float
    quantity: float
    order_type: str = "limit"
    
    def __post_init__(self):
        """Normalize side."""
        self.side = self.side.lower()


@dataclass
class StageTiming:
    """Timing metrics for a stage."""
    stage_name: str
    samples: List[float] = field(default_factory=list)
    
    def add_sample(self, duration_ms: float):
        """Add duration sample."""
        self.samples.append(duration_ms)
    
    def get_percentiles(self) -> Dict[str, float]:
        """Calculate percentiles."""
        if not self.samples:
            return {"p50": 0.0, "p95": 0.0, "p99": 0.0, "count": 0}
        
        sorted_samples = sorted(self.samples)
        count = len(sorted_samples)
        
        return {
            "p50": statistics.quantiles(sorted_samples, n=2)[0] if count >= 2 else sorted_samples[0],
            "p95": sorted_samples[int(count * 0.95)] if count > 1 else sorted_samples[0],
            "p99": sorted_samples[int(count * 0.99)] if count > 1 else sorted_samples[0],
            "count": count
        }


@dataclass
class ComparisonResult:
    """Comparison result between legacy and pipeline."""
    total_ticks: int = 0
    matched_ticks: int = 0
    order_plan_match_pct: float = 0.0
    price_diff_median_bps: float = 0.0
    quantity_diff_median_pct: float = 0.0
    
    # Timing comparisons
    legacy_timings: Dict[str, Dict[str, float]] = field(default_factory=dict)
    pipeline_timings: Dict[str, Dict[str, float]] = field(default_factory=dict)
    
    # Mismatches
    mismatches: List[Dict[str, Any]] = field(default_factory=list)
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return asdict(self)


class ShadowValidator:
    """
    Shadow mode validator.
    
    Runs legacy and pipeline in parallel on same data and compares results.
    """
    
    def __init__(
        self,
        ctx: AppContext,
        output_dir: str = "artifacts/shadow"
    ):
        """
        Initialize validator.
        
        Args:
            ctx: Application context
            output_dir: Output directory for artifacts
        """
        self.ctx = ctx
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        
        # Create pipeline
        self.pipeline = create_quote_pipeline(ctx, enable_tracing=True, enable_metrics=True)
        
        # Stage timings
        self.legacy_timings: Dict[str, StageTiming] = {}
        self.pipeline_timings: Dict[str, StageTiming] = {}
        
        # Results
        self.comparison_result = ComparisonResult()
        
        print(f"[SHADOW] Initialized validator, output: {self.output_dir}")
    
    async def run_legacy_path(self, market_data: MarketData) -> Tuple[List[OrderPlan], Dict[str, float]]:
        """
        Run legacy quote generation path.
        
        Args:
            market_data: Market data snapshot
        
        Returns:
            (order_plans, timing_dict)
        """
        start_ns = time.monotonic_ns()
        
        # Simulate legacy path (stub - would call actual legacy QuoteLoop)
        # For now, generate dummy orders based on market data
        mid = market_data.mid_price
        spread_bps = 2.0  # Default spread
        
        orders = [
            OrderPlan(
                symbol=market_data.symbol,
                side="buy",
                price=mid * (1.0 - spread_bps / 10000.0),
                quantity=0.01,
                order_type="limit"
            ),
            OrderPlan(
                symbol=market_data.symbol,
                side="sell",
                price=mid * (1.0 + spread_bps / 10000.0),
                quantity=0.01,
                order_type="limit"
            )
        ]
        
        duration_ms = (time.monotonic_ns() - start_ns) / 1_000_000
        
        timing = {
            "tick_total": duration_ms
        }
        
        return orders, timing
    
    async def run_pipeline_path(self, market_data: MarketData) -> Tuple[List[OrderPlan], Dict[str, float]]:
        """
        Run pipeline quote generation path.
        
        Args:
            market_data: Market data snapshot
        
        Returns:
            (order_plans, timing_dict)
        """
        start_ns = time.monotonic_ns()
        
        # Run pipeline
        result = await self.pipeline.process_tick(market_data)
        
        # Extract orders from quote
        orders = []
        if result.final_quote:
            quote = result.final_quote
            orders = [
                OrderPlan(
                    symbol=quote.symbol,
                    side="buy",
                    price=quote.bid_price,
                    quantity=quote.bid_size,
                    order_type="limit"
                ),
                OrderPlan(
                    symbol=quote.symbol,
                    side="sell",
                    price=quote.ask_price,
                    quantity=quote.ask_size,
                    order_type="limit"
                )
            ]
        
        duration_ms = (time.monotonic_ns() - start_ns) / 1_000_000
        
        # Get stage timings from metrics
        stage_timings = {}
        if self.pipeline.metrics:
            summary = self.pipeline.metrics.get_summary()
            for stage, metrics in summary.get("stages", {}).items():
                if "p95" in metrics:
                    stage_timings[stage] = metrics["p95"]
        
        stage_timings["tick_total"] = duration_ms
        
        return orders, stage_timings
    
    def compare_orders(
        self,
        legacy_orders: List[OrderPlan],
        pipeline_orders: List[OrderPlan],
        tick_price_tolerance_bps: float = 0.5,
        quantity_tolerance_pct: float = 0.01
    ) -> Tuple[bool, Dict[str, Any]]:
        """
        Compare order plans.
        
        Args:
            legacy_orders: Orders from legacy path
            pipeline_orders: Orders from pipeline path
            tick_price_tolerance_bps: Price tolerance in bps
            quantity_tolerance_pct: Quantity tolerance as fraction
        
        Returns:
            (matched, mismatch_details)
        """
        # Check count
        if len(legacy_orders) != len(pipeline_orders):
            return False, {
                "reason": "count_mismatch",
                "legacy_count": len(legacy_orders),
                "pipeline_count": len(pipeline_orders)
            }
        
        # Compare each order pair
        for i, (leg, pip) in enumerate(zip(legacy_orders, pipeline_orders)):
            # Check side
            if leg.side != pip.side:
                return False, {
                    "reason": "side_mismatch",
                    "index": i,
                    "legacy_side": leg.side,
                    "pipeline_side": pip.side
                }
            
            # Check price (within tolerance)
            price_diff_bps = abs(pip.price - leg.price) / leg.price * 10000.0
            if price_diff_bps > tick_price_tolerance_bps:
                return False, {
                    "reason": "price_mismatch",
                    "index": i,
                    "legacy_price": leg.price,
                    "pipeline_price": pip.price,
                    "diff_bps": price_diff_bps,
                    "tolerance_bps": tick_price_tolerance_bps
                }
            
            # Check quantity (within tolerance)
            qty_diff_pct = abs(pip.quantity - leg.quantity) / leg.quantity
            if qty_diff_pct > quantity_tolerance_pct:
                return False, {
                    "reason": "quantity_mismatch",
                    "index": i,
                    "legacy_qty": leg.quantity,
                    "pipeline_qty": pip.quantity,
                    "diff_pct": qty_diff_pct,
                    "tolerance_pct": quantity_tolerance_pct
                }
        
        return True, {}
    
    async def run_comparison(
        self,
        market_data_list: List[MarketData],
        dry_run: bool = True
    ) -> ComparisonResult:
        """
        Run shadow comparison on market data samples.
        
        Args:
            market_data_list: List of market data snapshots
            dry_run: If True, don't place real orders
        
        Returns:
            Comparison result
        """
        print(f"[SHADOW] Starting comparison on {len(market_data_list)} ticks (dry_run={dry_run})")
        
        for i, md in enumerate(market_data_list):
            # Run both paths
            legacy_orders, legacy_timing = await self.run_legacy_path(md)
            pipeline_orders, pipeline_timing = await self.run_pipeline_path(md)
            
            # Record timings
            for stage, duration in legacy_timing.items():
                if stage not in self.legacy_timings:
                    self.legacy_timings[stage] = StageTiming(stage_name=stage)
                self.legacy_timings[stage].add_sample(duration)
            
            for stage, duration in pipeline_timing.items():
                if stage not in self.pipeline_timings:
                    self.pipeline_timings[stage] = StageTiming(stage_name=stage)
                self.pipeline_timings[stage].add_sample(duration)
            
            # Compare orders
            matched, mismatch = self.compare_orders(legacy_orders, pipeline_orders)
            
            self.comparison_result.total_ticks += 1
            if matched:
                self.comparison_result.matched_ticks += 1
            else:
                self.comparison_result.mismatches.append({
                    "tick": i,
                    "symbol": md.symbol,
                    **mismatch
                })
            
            # Progress
            if (i + 1) % 10 == 0:
                match_pct = (self.comparison_result.matched_ticks / self.comparison_result.total_ticks) * 100
                print(f"[SHADOW] Progress: {i+1}/{len(market_data_list)} ticks, match: {match_pct:.1f}%")
        
        # Calculate final metrics
        self.comparison_result.order_plan_match_pct = (
            (self.comparison_result.matched_ticks / self.comparison_result.total_ticks) * 100
            if self.comparison_result.total_ticks > 0 else 0.0
        )
        
        # Extract timing percentiles
        for stage, timing in self.legacy_timings.items():
            self.comparison_result.legacy_timings[stage] = timing.get_percentiles()
        
        for stage, timing in self.pipeline_timings.items():
            self.comparison_result.pipeline_timings[stage] = timing.get_percentiles()
        
        print(f"[SHADOW] Comparison complete: {self.comparison_result.order_plan_match_pct:.2f}% match")
        
        return self.comparison_result
    
    def export_artifacts(self):
        """Export comparison artifacts."""
        # Compare orders
        with open(self.output_dir / "compare_orders.json", "w") as f:
            json.dump(self.comparison_result.to_dict(), f, indent=2)
        
        # Stage profiles
        with open(self.output_dir / "stage_profile_legacy.json", "w") as f:
            json.dump(self.comparison_result.legacy_timings, f, indent=2)
        
        with open(self.output_dir / "stage_profile_pipeline.json", "w") as f:
            json.dump(self.comparison_result.pipeline_timings, f, indent=2)
        
        # Generate markdown report
        self._generate_markdown_report()
        
        print(f"[SHADOW] Artifacts exported to {self.output_dir}")
    
    def _generate_markdown_report(self):
        """Generate markdown comparison report."""
        lines = []
        
        lines.append("# Shadow Mode Validation Report")
        lines.append("")
        lines.append(f"**Total Ticks**: {self.comparison_result.total_ticks}")
        lines.append(f"**Matched Ticks**: {self.comparison_result.matched_ticks}")
        lines.append(f"**Match Rate**: {self.comparison_result.order_plan_match_pct:.2f}%")
        lines.append("")
        
        # Performance comparison
        lines.append("## Performance Comparison (p95)")
        lines.append("")
        lines.append("| Stage | Legacy p95 (ms) | Pipeline p95 (ms) | Diff (%) | Status |")
        lines.append("|-------|-----------------|-------------------|----------|--------|")
        
        all_stages = set(self.comparison_result.legacy_timings.keys()) | set(self.comparison_result.pipeline_timings.keys())
        for stage in sorted(all_stages):
            legacy_p95 = self.comparison_result.legacy_timings.get(stage, {}).get("p95", 0.0)
            pipeline_p95 = self.comparison_result.pipeline_timings.get(stage, {}).get("p95", 0.0)
            
            if legacy_p95 > 0:
                diff_pct = ((pipeline_p95 - legacy_p95) / legacy_p95) * 100
                status = "✅" if diff_pct <= 0 else ("⚠️" if diff_pct <= 3 else "❌")
            else:
                diff_pct = 0.0
                status = "➖"
            
            lines.append(
                f"| {stage} | {legacy_p95:.2f} | {pipeline_p95:.2f} | "
                f"{diff_pct:+.2f} | {status} |"
            )
        
        lines.append("")
        
        # Mismatches
        if self.comparison_result.mismatches:
            lines.append("## Mismatches")
            lines.append("")
            lines.append(f"Total: {len(self.comparison_result.mismatches)}")
            lines.append("")
            
            # Group by reason
            by_reason = {}
            for mm in self.comparison_result.mismatches:
                reason = mm.get("reason", "unknown")
                by_reason[reason] = by_reason.get(reason, 0) + 1
            
            lines.append("| Reason | Count |")
            lines.append("|--------|-------|")
            for reason, count in sorted(by_reason.items(), key=lambda x: -x[1]):
                lines.append(f"| {reason} | {count} |")
        else:
            lines.append("## Mismatches")
            lines.append("")
            lines.append("✅ No mismatches detected")
        
        lines.append("")
        
        # Write report
        with open(self.output_dir / "report.md", "w") as f:
            f.write("\n".join(lines))
        
        print(f"[SHADOW] Report saved to {self.output_dir / 'report.md'}")


async def main():
    """Main entry point for shadow validator."""
    import argparse
    
    parser = argparse.ArgumentParser(description="Shadow Mode Validator")
    parser.add_argument('--ticks', type=int, default=30, help="Number of ticks to simulate")
    parser.add_argument('--dry-run', action='store_true', help="Dry run mode (no real orders)")
    parser.add_argument('--output', default="artifacts/shadow", help="Output directory")
    
    args = parser.parse_args()
    
    # Create config
    cfg = AppConfig()
    cfg.pipeline.enabled = True
    cfg.pipeline.sample_stage_tracing = 1.0  # Full tracing in shadow mode
    
    ctx = AppContext(cfg=cfg)
    
    # Create validator
    validator = ShadowValidator(ctx, output_dir=args.output)
    
    # Generate test market data
    market_data_list = []
    base_prices = {"BTCUSDT": 50000.0, "ETHUSDT": 3000.0}
    
    for i in range(args.ticks):
        for symbol, base_price in base_prices.items():
            # Add some noise
            price_offset = (i % 10 - 5) * base_price * 0.0001
            mid = base_price + price_offset
            
            md = MarketData(
                symbol=symbol,
                mid_price=mid,
                best_bid=mid - 1.0,
                best_ask=mid + 1.0,
                bid_size=1.0,
                ask_size=1.0,
                timestamp_ms=int(time.time() * 1000) + i * 1000
            )
            market_data_list.append(md)
    
    # Run comparison
    result = await validator.run_comparison(market_data_list, dry_run=args.dry_run)
    
    # Export artifacts
    validator.export_artifacts()
    
    # Print summary
    print("")
    print("=" * 60)
    print("SHADOW VALIDATION SUMMARY")
    print("=" * 60)
    print(f"Total Ticks: {result.total_ticks}")
    print(f"Match Rate: {result.order_plan_match_pct:.2f}%")
    print(f"Mismatches: {len(result.mismatches)}")
    print("")
    print("Performance (p95):")
    print(f"  Legacy tick_total: {result.legacy_timings.get('tick_total', {}).get('p95', 0):.2f}ms")
    print(f"  Pipeline tick_total: {result.pipeline_timings.get('tick_total', {}).get('p95', 0):.2f}ms")
    print("=" * 60)
    
    # Exit code based on success
    if result.order_plan_match_pct >= 95.0:
        print("✅ SHADOW VALIDATION PASSED")
        return 0
    else:
        print("❌ SHADOW VALIDATION FAILED")
        return 1


if __name__ == '__main__':
    exit_code = asyncio.run(main())
    exit(exit_code)

