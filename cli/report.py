#!/usr/bin/env python3
"""
Daily trading report generator.
"""

import argparse
import asyncio
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Dict, List, Optional

import polars as pl

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from src.common.config import Config


class DailyReporter:
    """Generate daily trading reports from recorded events."""
    
    def __init__(self, config: Config, data_dir: Path):
        """Initialize reporter."""
        self.config = config
        self.data_dir = data_dir
        
    async def generate_report(self, date: datetime, symbols: Optional[List[str]] = None) -> Dict:
        """Generate report for a specific date."""
        try:
            # Load events for the date
            events = await self._load_daily_events(date, symbols)
            
            # Calculate metrics
            metrics = self._calculate_metrics(events, date)
            
            # Generate report
            report = {
                "date": date.strftime("%Y-%m-%d"),
                "symbols": symbols or self.config.trading.symbols,
                "metrics": metrics,
                "generated_at": datetime.now(timezone.utc).isoformat()
            }
            
            return report
            
        except Exception as e:
            print(f"Error generating report: {e}")
            return {}
    
    async def _load_daily_events(self, date: datetime, symbols: Optional[List[str]] = None) -> Dict[str, pl.DataFrame]:
        """Load all events for a specific date."""
        events = {}
        date_str = date.strftime("%Y-%m-%d")
        
        # Load orders
        try:
            orders_path = self.data_dir / "orders" / f"{date_str}_orders.parquet"
            if orders_path.exists():
                events["orders"] = pl.read_parquet(orders_path)
            else:
                events["orders"] = pl.DataFrame()
        except Exception:
            events["orders"] = pl.DataFrame()
        
        # Load fills
        try:
            fills_path = self.data_dir / "fills" / f"{date_str}_fills.parquet"
            if fills_path.exists():
                events["fills"] = pl.read_parquet(fills_path)
            else:
                events["fills"] = pl.DataFrame()
        except Exception:
            events["fills"] = pl.DataFrame()
        
        # Load quotes
        try:
            quotes_path = self.data_dir / "quotes" / f"{date_str}_quotes.parquet"
            if quotes_path.exists():
                events["quotes"] = pl.read_parquet(quotes_path)
            else:
                events["quotes"] = pl.DataFrame()
        except Exception:
            events["quotes"] = pl.DataFrame()
        
        # Load custom events
        try:
            custom_path = self.data_dir / "custom_events" / f"{date_str}_custom_events.parquet"
            if custom_path.exists():
                events["custom_events"] = pl.read_parquet(custom_path)
            else:
                events["custom_events"] = pl.DataFrame()
        except Exception:
            events["custom_events"] = pl.DataFrame()
        
        return events
    
    def _calculate_metrics(self, events: Dict[str, pl.DataFrame], date: datetime) -> Dict:
        """Calculate trading metrics from events."""
        metrics = {}
        
        # P&L metrics
        if not events["fills"].is_empty():
            fills = events["fills"]
            metrics["pnl_realized"] = float(fills.select("fee").sum().item() * -1)  # Fees are negative P&L
            metrics["volume"] = float(fills.select("qty").sum().item())
            metrics["fees"] = float(fills.select("fee").sum().item())
        else:
            metrics["pnl_realized"] = 0.0
            metrics["volume"] = 0.0
            metrics["fees"] = 0.0
        
        # Order metrics
        if not events["orders"].is_empty():
            orders = events["orders"]
            metrics["orders_placed"] = len(orders)
            metrics["orders_filled"] = len(orders.filter(pl.col("status") == "Filled"))
            metrics["fill_rate"] = metrics["orders_filled"] / metrics["orders_placed"] if metrics["orders_placed"] > 0 else 0.0
        else:
            metrics["orders_placed"] = 0
            metrics["orders_filled"] = 0
            metrics["fill_rate"] = 0.0
        
        # Quote metrics
        if not events["quotes"].is_empty():
            metrics["quotes_generated"] = len(events["quotes"])
        else:
            metrics["quotes_generated"] = 0
        
        # Default values for missing metrics
        metrics["pnl_mtm"] = 0.0  # Mark-to-market P&L would need current prices
        metrics["avg_spread_bps"] = 0.0
        metrics["latency_p50"] = 0.0
        metrics["latency_p95"] = 0.0
        
        return metrics
    
    def write_markdown_report(self, report: Dict, output_dir: Path) -> Path:
        """Write markdown report to file."""
        output_dir.mkdir(parents=True, exist_ok=True)
        
        markdown_content = f"""# Daily Trading Report - {report['date']}

## Summary
- **Date**: {report['date']}
- **Symbols**: {', '.join(report['symbols'])}
- **Generated**: {report['generated_at']}

## Performance Metrics
- **Realized P&L**: ${report['metrics']['pnl_realized']:.2f}
- **Volume**: {report['metrics']['volume']:.4f}
- **Fees**: ${report['metrics']['fees']:.4f}
- **Orders Placed**: {report['metrics']['orders_placed']}
- **Orders Filled**: {report['metrics']['orders_filled']}
- **Fill Rate**: {report['metrics']['fill_rate']:.2%}
- **Quotes Generated**: {report['metrics']['quotes_generated']}

## Trading Activity
- **Total Trades**: {report['metrics']['orders_filled']}
- **Average Spread**: {report['metrics']['avg_spread_bps']:.2f} bps
- **Latency P50**: {report['metrics']['latency_p50']:.2f}ms
- **Latency P95**: {report['metrics']['latency_p95']:.2f}ms

---
*Report generated by Market Maker Bot*
"""
        
        filepath = output_dir / f"report_{report['date']}.md"
        with open(filepath, 'w') as f:
            f.write(markdown_content)
        
        return filepath
    
    def write_csv_report(self, report: Dict, output_dir: Path) -> Path:
        """Write CSV report to file."""
        output_dir.mkdir(parents=True, exist_ok=True)
        
        # Flatten metrics for CSV
        csv_data = {
            "date": [report['date']],
            "symbols": [', '.join(report['symbols'])],
            "pnl_realized": [report['metrics']['pnl_realized']],
            "pnl_mtm": [report['metrics']['pnl_mtm']],
            "volume": [report['metrics']['volume']],
            "fees": [report['metrics']['fees']],
            "orders_placed": [report['metrics']['orders_placed']],
            "orders_filled": [report['metrics']['orders_filled']],
            "fill_rate": [report['metrics']['fill_rate']],
            "quotes_generated": [report['metrics']['quotes_generated']],
            "avg_spread_bps": [report['metrics']['avg_spread_bps']],
            "latency_p50": [report['metrics']['latency_p50']],
            "latency_p95": [report['metrics']['latency_p95']]
        }
        
        df = pl.DataFrame(csv_data)
        filepath = output_dir / f"report_{report['date']}.csv"
        df.write_csv(filepath)
        
        return filepath


async def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(description="Generate daily trading reports")
    parser.add_argument("--date", default=(datetime.now(timezone.utc) - timedelta(days=1)).strftime("%Y-%m-%d"), help="Report date (YYYY-MM-DD)")
    parser.add_argument("--symbols", nargs="+", help="Specific symbols to include")
    parser.add_argument("--out", default="./reports", help="Output directory")
    parser.add_argument("--config", default="config.yaml", help="Configuration file")
    parser.add_argument("--upload", action="store_true", help="Upload reports to S3/DO Spaces")
    
    args = parser.parse_args()
    
    try:
        # Load configuration
        if not Path(args.config).exists():
            print(f"Configuration file not found: {args.config}")
            sys.exit(1)
        
        config = Config.from_yaml(args.config)
        config.validate()
        
        # Parse date
        report_date = datetime.strptime(args.date, "%Y-%m-%d").replace(tzinfo=timezone.utc)
        
        # Create reporter
        data_dir = Path(config.storage.parquet_path)
        reporter = DailyReporter(config, data_dir)
        
        # Generate report
        print(f"Generating report for {args.date}...")
        report = await reporter.generate_report(report_date, args.symbols)
        
        if not report:
            print("Failed to generate report")
            sys.exit(1)
        
        # Write reports
        output_dir = Path(args.out)
        md_path = reporter.write_markdown_report(report, output_dir)
        csv_path = reporter.write_csv_report(report, output_dir)
        
        print(f"Reports written:")
        print(f"  Markdown: {md_path}")
        print(f"  CSV: {csv_path}")
        
        # Upload if requested
        if args.upload:
            print("Upload functionality not implemented yet")
            # TODO: Implement S3/DO Spaces upload
        
        print("Report generation complete!")
        
    except Exception as e:
        print(f"Error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
