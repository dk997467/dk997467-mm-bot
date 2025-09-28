"""
Backtest runner CLI and main execution logic.

Provides command-line interface for running backtests and generating reports.
"""

import argparse
import json
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Any
from decimal import Decimal

from src.backtest.orderbook_replay import OrderBookReplay
from src.backtest.queue_sim import QueueSimulator, SimulatedOrder, CalibrationParams
from src.marketdata.orderbook import OrderBookAggregator
from src.metrics.pnl import PnLAttributor
from src.common.config import AppConfig, get_git_sha, cfg_hash_sanitized
from src.common.models import Side

logger = logging.getLogger(__name__)


class BacktestRunner:
    """Main backtest execution engine."""
    
    def __init__(self, config: AppConfig, data_dir: str, symbol: str, 
                 calibration: Optional[CalibrationParams] = None):
        """Initialize backtest runner."""
        self.config = config
        self.data_dir = Path(data_dir)
        self.symbol = symbol
        self.calibration = calibration
        
        # Initialize components
        self.orderbook_aggregator = OrderBookAggregator()
        self.orderbook_aggregator.add_symbol(symbol)
        
        self.orderbook_replay = OrderBookReplay(str(self.data_dir))
        # E1: Pass calibration to queue simulator
        self.queue_simulator = QueueSimulator(self.orderbook_aggregator, calibration)
        self.pnl_attributor = PnLAttributor(config)
        
        # Backtest state
        self.start_time: Optional[datetime] = None
        self.end_time: Optional[datetime] = None
        self.total_pnl = 0.0
        self.total_fees = 0.0
        self.total_trades = 0
        
        # Performance metrics
        self.returns: List[float] = []
        self.drawdowns: List[float] = []
        self.max_drawdown = 0.0
        self.peak_value = 0.0
        
        logger.info(f"Backtest runner initialized for {symbol} with calibration: {calibration}")
    
    def run_backtest(self, start_time: Optional[datetime] = None, 
                    end_time: Optional[datetime] = None,
                    use_synthetic: bool = False) -> Dict[str, Any]:
        """Run the backtest."""
        self.start_time = start_time or datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
        self.end_time = end_time or datetime.now(timezone.utc)
        
        logger.info(f"Starting backtest: {self.symbol} from {self.start_time} to {self.end_time}")
        
        try:
            # Generate or load order book data
            if use_synthetic:
                orderbooks = self.orderbook_replay.generate_synthetic_data(
                    self.symbol, self.start_time, self.end_time
                )
            else:
                orderbooks = self.orderbook_replay.replay_symbol(
                    self.symbol, self.start_time, self.end_time
                )
            
            # Run simulation
            for orderbook in orderbooks:
                self._process_orderbook(orderbook)
            
            # Calculate final metrics
            results = self._calculate_results()
            
            logger.info(f"Backtest completed: {self.total_trades} trades, PnL: {self.total_pnl:.2f}")
            return results
            
        except Exception as e:
            logger.error(f"Error during backtest: {e}")
            raise
    
    def _process_orderbook(self, orderbook):
        """Process a single order book snapshot."""
        # Update orderbook aggregator
        self.orderbook_aggregator.update_orderbook(orderbook)
        
        # Simulate market moves and get fills
        fills = self.queue_simulator.simulate_market_moves(orderbook)
        
        # Process fills
        for fill in fills:
            self._process_fill(fill, orderbook)
        
        # Update PnL
        if orderbook.mid_price:
            current_price = float(orderbook.mid_price)
            self._update_pnl_metrics(current_price)
    
    def _process_fill(self, fill, orderbook):
        """Process a simulated fill."""
        # Record fill in PnL attributor
        self.pnl_attributor.record_fill(
            symbol=fill.symbol,
            side=fill.side.value,
            fill_qty=float(fill.fill_qty),
            fill_price=float(fill.fill_price),
            is_maker=fill.is_maker,
            order_id=fill.order_id
        )
        
        # Update statistics
        self.total_trades += 1
        fill_value = float(fill.fill_price * fill.fill_qty)
        
        if fill.is_maker:
            # Maker rebate
            rebate = self.pnl_attributor.calculate_maker_rebate(
                float(fill.fill_qty), float(fill.fill_price), fill.symbol
            )
            self.total_pnl += rebate
        else:
            # Taker fees
            fees = self.pnl_attributor.calculate_taker_fees(
                float(fill.fill_qty), float(fill.fill_price), fill.symbol
            )
            self.total_fees += fees
            self.total_pnl -= fees
        
        logger.debug(f"Processed fill: {fill.order_id} {fill.side} {fill.fill_qty} @ {fill.fill_price}")
    
    def _update_pnl_metrics(self, current_price: float):
        """Update PnL metrics for performance calculation."""
        # Get current PnL
        pnl_breakdown = self.pnl_attributor.get_total_pnl(self.symbol, current_price)
        current_pnl = pnl_breakdown.total_pnl
        
        # Calculate return
        if self.peak_value > 0:
            return_pct = (current_pnl - self.peak_value) / self.peak_value
            self.returns.append(return_pct)
        
        # Update peak value and drawdown
        if current_pnl > self.peak_value:
            self.peak_value = current_pnl
        
        if self.peak_value > 0:
            drawdown = (self.peak_value - current_pnl) / self.peak_value
            self.drawdowns.append(drawdown)
            self.max_drawdown = max(self.max_drawdown, drawdown)
    
    def _calculate_results(self) -> Dict[str, Any]:
        """Calculate final backtest results."""
        # Calculate Sharpe ratio
        if len(self.returns) > 1:
            avg_return = sum(self.returns) / len(self.returns)
            return_std = (sum((r - avg_return) ** 2 for r in self.returns) / len(self.returns)) ** 0.5
            sharpe_ratio = avg_return / return_std if return_std > 0 else 0.0
        else:
            sharpe_ratio = 0.0
        
        # Calculate hit rate (percentage of profitable trades)
        profitable_trades = sum(1 for r in self.returns if r > 0)
        hit_rate = profitable_trades / len(self.returns) if self.returns else 0.0
        
        # Calculate average queue time (simplified)
        avg_queue_time = 0.0  # Would need more sophisticated tracking
        
        # Calculate CVaR95 (Conditional Value at Risk at 95%)
        if self.returns:
            sorted_returns = sorted(self.returns)
            var_95_index = int(len(sorted_returns) * 0.05)
            cvar_95 = sum(sorted_returns[:var_95_index]) / max(var_95_index, 1)
        else:
            cvar_95 = 0.0
        
        results = {
            'symbol': self.symbol,
            'start_time': self.start_time.isoformat() if self.start_time else None,
            'end_time': self.end_time.isoformat() if self.end_time else None,
            'total_trades': self.total_trades,
            'net_pnl': self.total_pnl,
            'total_fees': self.total_fees,
            'sharpe_ratio': sharpe_ratio,
            'hit_rate': hit_rate,
            'max_drawdown': self.max_drawdown,
            'avg_queue_time': avg_queue_time,
            'cvar_95': cvar_95,
            'fill_statistics': self.queue_simulator.get_fill_statistics(),
            'inventory_summary': self.pnl_attributor.get_inventory_summary(),
            # E1: Include calibration parameters if used
            'calibration_used': {
                'latency_ms_mean': self.calibration.latency_ms_mean if self.calibration else 0.0,
                'latency_ms_std': self.calibration.latency_ms_std if self.calibration else 0.0,
                'amend_latency_ms': self.calibration.amend_latency_ms if self.calibration else 0.0,
                'cancel_latency_ms': self.calibration.cancel_latency_ms if self.calibration else 0.0,
                'toxic_sweep_prob': self.calibration.toxic_sweep_prob if self.calibration else 0.0,
                'extra_slippage_bps': self.calibration.extra_slippage_bps if self.calibration else 0.0
            },
            'metadata': {
                'git_sha': get_git_sha(),
                'cfg_hash': cfg_hash_sanitized(self.config)
            }
        }
        
        return results
    
    def add_test_order(self, side: Side, price: Decimal, qty: Decimal) -> str:
        """Add a test order to the simulation."""
        order = SimulatedOrder(
            order_id=f"test_{len(self.queue_simulator.fills)}",
            symbol=self.symbol,
            side=side,
            price=price,
            qty=qty,
            timestamp=datetime.now(timezone.utc)
        )
        
        self.queue_simulator.add_order(order)
        return order.order_id
    
    def generate_report_md(self, results: Dict[str, Any], output_path: Optional[Path] = None) -> str:
        """Generate markdown report from results."""
        calibration = results.get('calibration_used', {})
        metadata = results.get('metadata', {})
        
        # Build report content
        report_lines = [
            f"# Backtest Report for {results['symbol']}",
            "",
            f"**Git SHA:** {metadata.get('git_sha', 'unknown')}  ",
            f"**Config Hash:** {metadata.get('cfg_hash', 'unknown')}  ",
            f"**Period:** {results.get('start_time', 'N/A')} to {results.get('end_time', 'N/A')}  ",
            "",
            "## Performance Metrics",
            "",
            f"- **Net PnL (USD):** {results.get('net_pnl', 0):.2f}",
            f"- **Total Fees (USD):** {results.get('total_fees', 0):.2f}",
            f"- **Total Trades:** {results.get('total_trades', 0)}",
            f"- **Sharpe Ratio:** {results.get('sharpe_ratio', 0):.3f}",
            f"- **Hit Rate (%):** {results.get('hit_rate', 0) * 100:.1f}",
            f"- **Max Drawdown (%):** {results.get('max_drawdown', 0) * 100:.1f}",
            f"- **CVaR95:** {results.get('cvar_95', 0):.3f}",
            "",
            "## Fill Statistics",
            ""
        ]
        
        fill_stats = results.get('fill_statistics', {})
        report_lines.extend([
            f"- **Total Fills:** {fill_stats.get('total_fills', 0)}",
            f"- **Maker Fills:** {fill_stats.get('maker_fills', 0)}",
            f"- **Taker Fills:** {fill_stats.get('taker_fills', 0)}",
            f"- **Maker Ratio (%):** {fill_stats.get('maker_ratio', 0) * 100:.1f}",
            f"- **Total Fill Value (USD):** {fill_stats.get('total_fill_value', 0):.2f}",
            ""
        ])
        
        # E1: Add calibration section if parameters were used
        if any(v != 0 for v in calibration.values()):
            report_lines.extend([
                "## Calibration Parameters",
                "",
                f"- **Latency Mean (ms):** {calibration.get('latency_ms_mean', 0):.1f}",
                f"- **Latency Std (ms):** {calibration.get('latency_ms_std', 0):.1f}",
                f"- **Amend Latency (ms):** {calibration.get('amend_latency_ms', 0):.1f}",
                f"- **Cancel Latency (ms):** {calibration.get('cancel_latency_ms', 0):.1f}",
                f"- **Toxic Sweep Probability:** {calibration.get('toxic_sweep_prob', 0):.3f}",
                f"- **Extra Slippage (bps):** {calibration.get('extra_slippage_bps', 0):.1f}",
                ""
            ])
        
        # Add inventory summary if available
        inventory = results.get('inventory_summary', {})
        if inventory:
            report_lines.extend([
                "## Inventory Summary",
                "",
                f"- **Current Position:** {inventory.get('current_position', 0):.4f}",
                f"- **Unrealized PnL (USD):** {inventory.get('unrealized_pnl', 0):.2f}",
                ""
            ])
        
        report_lines.extend([
            "---",
            "",
            "*Report generated by MM-Bot backtest engine*"
        ])
        
        report_content = "\n".join(report_lines)
        
        # Write to file if path provided
        if output_path:
            output_path.parent.mkdir(parents=True, exist_ok=True)
            with open(output_path, 'w', encoding='utf-8') as f:
                f.write(report_content)
            logger.info(f"Report written to {output_path}")
        
        return report_content


def main():
    """Main CLI entry point."""
    parser = argparse.ArgumentParser(description='Run market making strategy backtest')
    parser.add_argument('--data', required=True, help='Data directory path')
    parser.add_argument('--symbol', required=True, help='Trading symbol (e.g., BTCUSDT)')
    parser.add_argument('--params', help='Strategy parameters JSON file')
    parser.add_argument('--out', help='Output report JSON file')
    parser.add_argument('--start', help='Start time (ISO format)')
    parser.add_argument('--end', help='End time (ISO format)')
    parser.add_argument('--synthetic', action='store_true', help='Use synthetic data')
    parser.add_argument('--config', help='Configuration file path')
    # E1: Add calibration flag
    parser.add_argument('--calibration', help='Calibration parameters JSON file')
    
    # E2 Part 2/2: Add seed and fast mode for parameter search
    parser.add_argument('--seed', type=int, default=42,
                       help='Random seed for deterministic results')
    parser.add_argument('--fast', action='store_true',
                       help='Enable fast mode for parameter search (shorter evaluation)')
    parser.add_argument('--max-trades', type=int, default=0,
                       help='Maximum trades to process (0=unlimited, for fast evaluation)')
    
    args = parser.parse_args()
    
    # E2 Part 2/2: Set deterministic seed
    import random
    import numpy as np
    random.seed(args.seed)
    np.random.seed(args.seed)
    
    # Load configuration
    if args.config:
        # Load config from file
        config = AppConfig.from_file(args.config)
    else:
        # Use default config
        from src.common.config import load_config
        config = load_config()
    
    # Parse time arguments
    start_time = None
    end_time = None
    
    if args.start:
        start_time = datetime.fromisoformat(args.start.replace('Z', '+00:00'))
    if args.end:
        end_time = datetime.fromisoformat(args.end.replace('Z', '+00:00'))
    
    # Load strategy parameters if provided
    strategy_params = {}
    if args.params:
        with open(args.params, 'r') as f:
            strategy_params = json.load(f)
    
    # E1: Load calibration parameters if provided
    calibration = None
    if args.calibration:
        try:
            with open(args.calibration, 'r') as f:
                calibration_data = json.load(f)
            calibration = CalibrationParams(**calibration_data)
            logger.info(f"Loaded calibration parameters: {calibration}")
        except Exception as e:
            logger.error(f"Failed to load calibration parameters: {e}")
            return 1
    
    try:
        # Initialize and run backtest
        # E1: Pass calibration to BacktestRunner
        runner = BacktestRunner(config, args.data, args.symbol, calibration)
        
        # Apply strategy parameters if provided
        if strategy_params:
            # Update config with strategy parameters
            for key, value in strategy_params.items():
                if hasattr(config.strategy, key):
                    setattr(config.strategy, key, value)
        
        # Run backtest
        results = runner.run_backtest(
            start_time=start_time,
            end_time=end_time,
            use_synthetic=args.synthetic
        )
        
        # E2 Part 2/2: Add metadata for fast mode and seed
        results["backtest_metadata"] = {
            "seed": args.seed,
            "fast_mode": args.fast,
            "max_trades": args.max_trades
        }
        
        # Output results
        if args.out:
            # Save JSON report
            with open(args.out, 'w') as f:
                json.dump(results, f, indent=2, sort_keys=True, ensure_ascii=False)
            print(f"Results saved to {args.out}")
            
            # E1: Generate and save markdown report
            out_path = Path(args.out)
            md_path = out_path.with_suffix('.md')
            runner.generate_report_md(results, md_path)
            print(f"Markdown report saved to {md_path}")
        else:
            print(json.dumps(results, indent=2, sort_keys=True, ensure_ascii=False))
        
        return 0
        
    except Exception as e:
        logger.error(f"Backtest failed: {e}")
        return 1


def compute_sim_distributions(backtest_metrics: Dict, bins_max_bps: int, percentiles: List[float]) -> Dict:
    """
    Convert raw backtest metrics to SIM distributions compatible with calibration.
    
    Args:
        backtest_metrics: Raw metrics from backtest run
        bins_max_bps: Maximum price bin value
        percentiles: List of percentiles for CDF construction
        
    Returns:
        Dict with SIM distributions in calibration format:
        {
            "queue_wait_cdf_ms": [{"p": ..., "v": ...}, ...],
            "hit_rate_by_bin": {"0": {"count": n, "fills": f}, ...},
            "sim_hit": float,
            "sim_maker": float
        }
        
    Note: This is a stub for E2 Part 1. Full implementation in Part 2/2.
    """
    logger = logging.getLogger(__name__)
    logger.warning("compute_sim_distributions is a stub - full implementation in E2 Part 2/2")
    
    # Extract basic metrics (simplified for stub)
    total_orders = backtest_metrics.get("total_orders", 0)
    total_fills = backtest_metrics.get("total_fills", 0)
    
    # Create stub distributions that match expected format
    sim_hit = total_fills / total_orders if total_orders > 0 else 0.0
    sim_maker = sim_hit * 0.8  # Assume 80% maker for stub
    
    # Stub CDF (uniform distribution for now)
    queue_wait_cdf_ms = []
    base_wait = 150.0  # Base wait time in ms
    for p in percentiles:
        queue_wait_cdf_ms.append({
            "p": p,
            "v": base_wait + (p * 100.0)  # Simple linear distribution
        })
    
    # Stub bin distributions (uniform across bins)
    hit_rate_by_bin = {}
    orders_per_bin = max(1, total_orders // (bins_max_bps + 1))
    fills_per_bin = max(0, total_fills // (bins_max_bps + 1))
    
    for bin_bps in range(bins_max_bps + 1):
        hit_rate_by_bin[str(bin_bps)] = {
            "count": orders_per_bin,
            "fills": fills_per_bin
        }
    
    return {
        "queue_wait_cdf_ms": queue_wait_cdf_ms,
        "hit_rate_by_bin": hit_rate_by_bin,
        "sim_hit": sim_hit,
        "sim_maker": sim_maker
    }


if __name__ == '__main__':
    sys.exit(main())
