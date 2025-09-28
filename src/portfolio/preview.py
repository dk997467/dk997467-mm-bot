"""
Portfolio allocation preview CLI.
"""

import argparse
import sys
from typing import Dict, List, Tuple

from src.common.config import PortfolioConfig
from src.portfolio.allocator import PortfolioAllocator
from src.common.di import AppContext
from src.common.config import AppConfig


def create_mock_context(mode: str, budget_usd: float, alpha: float, 
                       min_weight: float, max_weight: float) -> AppContext:
    """Create mock AppContext for preview."""
    from dataclasses import dataclass
    
    @dataclass
    class MockPortfolioConfig:
        budget_usd: float
        mode: str
        manual_weights: Dict[str, float]
        min_weight: float
        max_weight: float
        rebalance_minutes: int = 5
        ema_alpha: float = 0.3
        levels_per_side_min: int = 1
        levels_per_side_max: int = 10
    
    @dataclass
    class MockAppConfig:
        portfolio: MockPortfolioConfig
    
    portfolio_cfg = MockPortfolioConfig(
        budget_usd=budget_usd,
        mode=mode,
        manual_weights={"BTCUSDT": 0.6, "ETHUSDT": 0.4} if mode == "manual" else {},
        min_weight=min_weight,
        max_weight=max_weight,
        ema_alpha=alpha
    )
    
    app_cfg = MockAppConfig(portfolio=portfolio_cfg)
    return AppContext(cfg=app_cfg)


def generate_mock_stats() -> Dict[str, Dict[str, float]]:
    """Generate mock volatility statistics."""
    return {
        "BTCUSDT": {"vol": 0.025},
        "ETHUSDT": {"vol": 0.035},
        "SOLUSDT": {"vol": 0.045},
        "ADAUSDT": {"vol": 0.055},
        "DOTUSDT": {"vol": 0.065}
    }


def format_table(weights: Dict[str, float], targets: Dict[str, 'PortfolioTarget'], 
                stats: Dict[str, Dict[str, float]]) -> str:
    """Format portfolio data as a table."""
    lines = []
    
    # Header
    header = f"{'Symbol':<12} {'Vol':<8} {'Weight':<8} {'Target USD':<12} {'Max Levels':<12}"
    lines.append(header)
    lines.append("-" * len(header))
    
    # Sort by weight descending
    sorted_items = sorted(weights.items(), key=lambda x: x[1], reverse=True)
    
    for symbol, weight in sorted_items:
        vol = stats[symbol]["vol"]
        target = targets[symbol]
        
        # Format values
        vol_str = f"{vol:.4f}"
        weight_str = f"{weight:.4f}"
        target_usd_str = f"${target.target_usd:.0f}"
        max_levels_str = str(target.max_levels)
        
        line = f"{symbol:<12} {vol_str:<8} {weight_str:<8} {target_usd_str:<12} {max_levels_str:<12}"
        lines.append(line)
    
    # Summary
    total_weight = sum(weights.values())
    total_target = sum(t.target_usd for t in targets.values())
    
    lines.append("-" * len(header))
    summary = f"{'TOTAL':<12} {'':<8} {total_weight:<8.4f} ${total_target:<11.0f} {'':<12}"
    lines.append(summary)
    
    return "\n".join(lines)


def main():
    """Main CLI entry point."""
    parser = argparse.ArgumentParser(description="Portfolio allocation preview")
    parser.add_argument("--mode", choices=["manual", "inverse_vol", "risk_parity"], 
                       default="inverse_vol", help="Allocation mode")
    parser.add_argument("--budget-usd", type=float, default=10000.0, 
                       help="Portfolio budget in USD")
    parser.add_argument("--alpha", type=float, default=0.3, 
                       help="EMA smoothing alpha")
    parser.add_argument("--min-weight", type=float, default=0.02, 
                       help="Minimum weight per symbol")
    parser.add_argument("--max-weight", type=float, default=0.5, 
                       help="Maximum weight per symbol")
    
    args = parser.parse_args()
    
    try:
        # Create mock context
        ctx = create_mock_context(
            mode=args.mode,
            budget_usd=args.budget_usd,
            alpha=args.alpha,
            min_weight=args.min_weight,
            max_weight=args.max_weight
        )
        
        # Create allocator
        allocator = PortfolioAllocator(ctx)
        
        # Generate mock stats
        stats = generate_mock_stats()
        
        # Compute allocation
        targets = allocator.update(ctx, stats)
        weights = allocator.get_current_weights()
        
        # Print results
        print(f"Portfolio Allocation Preview")
        print(f"Mode: {args.mode}")
        print(f"Budget: ${args.budget_usd:,.0f}")
        print(f"EMA Alpha: {args.alpha}")
        print(f"Weight Range: {args.min_weight:.1%} - {args.max_weight:.1%}")
        print()
        
        table = format_table(weights, targets, stats)
        print(table)
        
        # Print mode-specific info
        if args.mode == "manual":
            print(f"\nManual weights: {ctx.cfg.portfolio.manual_weights}")
        elif args.mode == "inverse_vol":
            print(f"\nInverse volatility allocation: higher vol → lower weight")
        elif args.mode == "risk_parity":
            print(f"\nRisk parity allocation: equal risk contribution per symbol")
        
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
