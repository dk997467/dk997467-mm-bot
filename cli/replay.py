#!/usr/bin/env python3
"""
Replay CLI for market maker bot analysis.
Reads recorded events and replays them chronologically to analyze performance.
"""

try:
    import uvloop
    uvloop.install()
except Exception:
    pass
import argparse
import asyncio
import json
import sys
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from uuid import uuid4

import pandas as pd

# Add project root to path (so we can import src.*)
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.common.config import Config
from src.common.models import Order, Trade, OrderBook, QuoteRequest, Side, OrderType, TimeInForce
from src.strategy.quoting import MarketMakingStrategy
from src.risk.risk_manager import RiskManager


class ReplayEngine:
    """Engine for replaying recorded trading events."""
    
    def __init__(self, config: Config, symbols: List[str]):
        """Initialize replay engine."""
        self.config = config
        self.symbols = symbols
        
        # Initialize components (without connectors)
        self.strategy = MarketMakingStrategy(config, recorder=None)
        self.risk_manager = RiskManager(config, recorder=None)
        
        # Event storage
        self.events: List[Dict] = []
        self.event_index = 0
        
        # Performance tracking
        self.performance_metrics = {
            'total_pnl': Decimal(0),
            'realized_pnl': Decimal(0),
            'unrealized_pnl': Decimal(0),
            'total_turnover': Decimal(0),
            'total_fees': Decimal(0),
            'orders_placed': 0,
            'orders_filled': 0,
            'orders_cancelled': 0,
            'quotes_generated': 0,
            'avg_spread_bps': Decimal(0),
            'avg_fill_latency_ms': Decimal(0),
            'max_drawdown': Decimal(0),
            'peak_pnl': Decimal(0),
            'inventory_drift': Decimal(0)
        }
        
        # Per-symbol tracking
        self.symbol_metrics = {}
        for symbol in symbols:
            self.symbol_metrics[symbol] = {
                'position': Decimal(0),
                'avg_entry_price': Decimal(0),
                'realized_pnl': Decimal(0),
                'unrealized_pnl': Decimal(0),
                'quotes_generated': 0,
                'orders_filled': 0,
                'total_volume': Decimal(0),
                'avg_spread_bps': Decimal(0),
                'last_mid_price': None
            }
        
        # Event timing
        self.start_time = None
        self.end_time = None
        self.replay_speed = 1.0
        
        # Order tracking
        self.active_orders: Dict[str, Order] = {}
        self.order_timestamps: Dict[str, datetime] = {}
    
    def load_events(self, data_dir: Path, from_time: Optional[datetime] = None, 
                   to_time: Optional[datetime] = None, limit: Optional[int] = None):
        """Load events from recorded data."""
        print(f"Loading events from {data_dir}...")
        
        # Load different event types
        event_types = ['orders', 'fills', 'quotes', 'book_snapshots', 'custom_events']
        
        for event_type in event_types:
            event_dir = data_dir / event_type
            if not event_dir.exists():
                continue
            
            # Find all parquet files
            parquet_files = list(event_dir.glob("*.parquet"))
            if not parquet_files:
                continue
            
            print(f"  Loading {event_type} from {len(parquet_files)} files...")
            
            for file_path in parquet_files:
                try:
                    df = pd.read_parquet(file_path)
                    if df.empty:
                        continue
                    
                    # Convert timestamp to datetime if needed
                    if 'timestamp' in df.columns:
                        df['timestamp'] = pd.to_datetime(df['timestamp'])
                    
                    # Filter by time range
                    if from_time:
                        df = df[df['timestamp'] >= from_time]
                    if to_time:
                        df = df[df['timestamp'] <= to_time]
                    
                    # Add event type
                    df['event_type'] = event_type
                    
                    # Convert to events
                    for _, row in df.iterrows():
                        event = {
                            'type': event_type,
                            'timestamp': row['timestamp'],
                            'data': row.to_dict()
                        }
                        self.events.append(event)
                        
                except Exception as e:
                    print(f"    Warning: Could not load {file_path}: {e}")
        
        # Sort events by timestamp
        self.events.sort(key=lambda x: x['timestamp'])
        
        # Apply limit if specified
        if limit:
            self.events = self.events[:limit]
        
        # Set time range
        if self.events:
            self.start_time = self.events[0]['timestamp']
            self.end_time = self.events[-1]['timestamp']
        
        print(f"Loaded {len(self.events)} events from {self.start_time} to {self.end_time}")
    
    async def replay_events(self, speed: float = 1.0):
        """Replay events chronologically."""
        if not self.events:
            print("No events to replay")
            return
        
        print(f"Starting replay at {speed}x speed...")
        print("=" * 80)
        
        self.replay_speed = speed
        last_event_time = None
        
        for i, event in enumerate(self.events):
            try:
                # Process event
                self._process_event(event)
                
                # Update progress
                if i % 100 == 0:
                    progress = (i + 1) / len(self.events) * 100
                    print(f"Progress: {progress:.1f}% ({i + 1}/{len(self.events)})")
                
                # Simulate timing if speed > 0
                if speed > 0 and last_event_time:
                    time_diff = (event['timestamp'] - last_event_time).total_seconds()
                    if time_diff > 0:
                        await asyncio.sleep(time_diff / speed)
                
                last_event_time = event['timestamp']
                
            except Exception as e:
                print(f"Error processing event {i}: {e}")
                continue
        
        print("=" * 80)
        print("Replay completed")
    
    def _process_event(self, event: Dict):
        """Process a single event."""
        event_type = event['type']
        data = event['data']
        timestamp = event['timestamp']
        
        try:
            if event_type == 'book_snapshots':
                self._process_orderbook_snapshot(data, timestamp)
            elif event_type == 'quotes':
                self._process_quote(data, timestamp)
            elif event_type == 'orders':
                self._process_order(data, timestamp)
            elif event_type == 'fills':
                self._process_fill(data, timestamp)
            elif event_type == 'custom_events':
                self._process_custom_event(data, timestamp)
                
        except Exception as e:
            print(f"Error processing {event_type} event: {e}")
    
    def _process_orderbook_snapshot(self, data: Dict, timestamp: datetime):
        """Process orderbook snapshot event."""
        symbol = data.get('symbol', 'unknown')
        if symbol not in self.symbols:
            return
        
        # Create OrderBook object
        try:
            orderbook = OrderBook(
                symbol=symbol,
                timestamp=timestamp,
                sequence=data.get('sequence', 0),
                bids=[],  # Would need to parse bids/asks from data
                asks=[]
            )
            
            # Update strategy with orderbook
            self.strategy.update_orderbook(symbol, orderbook)
            
            # Update symbol metrics
            if orderbook.mid_price:
                self.symbol_metrics[symbol]['last_mid_price'] = orderbook.mid_price
                if orderbook.spread_bps:
                    self._update_avg_spread(symbol, orderbook.spread_bps)
                    
        except Exception as e:
            print(f"Error processing orderbook snapshot: {e}")
    
    def _process_quote(self, data: Dict, timestamp: datetime):
        """Process quote event."""
        symbol = data.get('symbol', 'unknown')
        if symbol not in self.symbols:
            return
        
        self.performance_metrics['quotes_generated'] += 1
        self.symbol_metrics[symbol]['quotes_generated'] += 1
        
        # Update strategy state if needed
        # This would depend on the specific quote data structure
    
    def _process_order(self, data: Dict, timestamp: datetime):
        """Process order event."""
        symbol = data.get('symbol', 'unknown')
        if symbol not in self.symbols:
            return
        
        order_id = data.get('order_id', '')
        status = data.get('status', '')
        
        if status == 'New':
            self.performance_metrics['orders_placed'] += 1
            self.symbol_metrics[symbol]['total_volume'] += Decimal(str(data.get('qty', 0)))
            
            # Track order timestamp for latency calculation
            self.order_timestamps[order_id] = timestamp
            
        elif status == 'Filled':
            self.performance_metrics['orders_filled'] += 1
            self.symbol_metrics[symbol]['orders_filled'] += 1
            
            # Calculate fill latency
            if order_id in self.order_timestamps:
                latency = (timestamp - self.order_timestamps[order_id]).total_seconds() * 1000
                self._update_avg_fill_latency(latency)
                del self.order_timestamps[order_id]
                
        elif status == 'Cancelled':
            self.performance_metrics['orders_cancelled'] += 1
    
    def _process_fill(self, data: Dict, timestamp: datetime):
        """Process fill event."""
        symbol = data.get('symbol', 'unknown')
        if symbol not in self.symbols:
            return
        
        try:
            # Create Trade object
            trade = Trade(
                trade_id=data.get('trade_id', str(uuid4())),
                order_id=data.get('order_id', ''),
                symbol=symbol,
                side=Side(data.get('side', 'Buy')),
                qty=Decimal(str(data.get('qty', 0))),
                price=Decimal(str(data.get('price', 0))),
                fee=Decimal(str(data.get('fee', 0))),
                fee_rate=Decimal(str(data.get('fee_rate', 0))),
                timestamp=timestamp,
                exec_time=timestamp,
                is_maker=data.get('is_maker', True)
            )
            
            # Update strategy inventory
            self.strategy.update_inventory(
                symbol, trade.side, trade.qty, trade.price
            )
            
            # Update risk manager
            self.risk_manager.update_position(
                symbol, trade.side, trade.qty, trade.price
            )
            
            # Calculate P&L
            self._calculate_trade_pnl(trade)
            
            # Update fees
            self.performance_metrics['total_fees'] += trade.fee
            
        except Exception as e:
            print(f"Error processing fill: {e}")
    
    def _process_custom_event(self, data: Dict, timestamp: datetime):
        """Process custom event."""
        event_type = data.get('event_type', '')
        
        if 'pnl' in event_type.lower():
            # Extract P&L information if available
            if 'realized_pnl' in data:
                self.performance_metrics['realized_pnl'] = Decimal(str(data['realized_pnl']))
            if 'unrealized_pnl' in data:
                self.performance_metrics['unrealized_pnl'] = Decimal(str(data['unrealized_pnl']))
    
    def _calculate_trade_pnl(self, trade: Trade):
        """Calculate P&L for a trade."""
        symbol = trade.symbol
        metrics = self.symbol_metrics[symbol]
        
        if trade.side == Side.BUY:
            # Buying increases position
            if metrics['position'] == 0:
                # New position
                metrics['avg_entry_price'] = trade.price
                metrics['position'] = trade.qty
            else:
                # Add to existing position
                total_cost = (metrics['position'] * metrics['avg_entry_price']) + (trade.qty * trade.price)
                metrics['position'] += trade.qty
                metrics['avg_entry_price'] = total_cost / metrics['position']
        else:
            # Selling decreases position
            if metrics['position'] > 0:
                # Realize P&L
                pnl = (trade.price - metrics['avg_entry_price']) * min(trade.qty, metrics['position'])
                metrics['realized_pnl'] += pnl
                self.performance_metrics['realized_pnl'] += pnl
                
                # Update position
                metrics['position'] -= trade.qty
                if metrics['position'] <= 0:
                    metrics['position'] = Decimal(0)
                    metrics['avg_entry_price'] = Decimal(0)
        
        # Update total turnover
        self.performance_metrics['total_turnover'] += trade.qty * trade.price
        
        # Update P&L tracking
        self._update_pnl_tracking()
    
    def _update_pnl_tracking(self):
        """Update P&L tracking metrics."""
        total_pnl = self.performance_metrics['realized_pnl'] + self.performance_metrics['unrealized_pnl']
        self.performance_metrics['total_pnl'] = total_pnl
        
        # Track peak P&L and drawdown
        if total_pnl > self.performance_metrics['peak_pnl']:
            self.performance_metrics['peak_pnl'] = total_pnl
        
        current_drawdown = self.performance_metrics['peak_pnl'] - total_pnl
        if current_drawdown > self.performance_metrics['max_drawdown']:
            self.performance_metrics['max_drawdown'] = current_drawdown
    
    def _update_avg_spread(self, symbol: str, spread_bps: Decimal):
        """Update average spread for a symbol."""
        metrics = self.symbol_metrics[symbol]
        current_avg = metrics['avg_spread_bps']
        quote_count = metrics['quotes_generated']
        
        if quote_count == 0:
            metrics['avg_spread_bps'] = spread_bps
        else:
            # Exponential moving average
            alpha = 0.1
            metrics['avg_spread_bps'] = (alpha * spread_bps) + ((1 - alpha) * current_avg)
    
    def _update_avg_fill_latency(self, latency_ms: float):
        """Update average fill latency."""
        current_avg = self.performance_metrics['avg_fill_latency_ms']
        order_count = self.performance_metrics['orders_filled']
        
        if order_count == 0:
            self.performance_metrics['avg_fill_latency_ms'] = Decimal(str(latency_ms))
        else:
            # Exponential moving average
            alpha = 0.1
            new_avg = (alpha * latency_ms) + ((1 - alpha) * float(current_avg))
            self.performance_metrics['avg_fill_latency_ms'] = Decimal(str(new_avg))
    
    def calculate_inventory_drift(self):
        """Calculate inventory drift across all symbols."""
        total_drift = Decimal(0)
        
        for symbol, metrics in self.symbol_metrics.items():
            if metrics['last_mid_price']:
                position_value = metrics['position'] * metrics['last_mid_price']
                total_drift += position_value
        
        self.performance_metrics['inventory_drift'] = total_drift
        return total_drift
    
    def print_performance_report(self):
        """Print comprehensive performance report."""
        print("\n" + "=" * 80)
        print("PERFORMANCE REPORT")
        print("=" * 80)
        
        # Overall metrics
        print(f"Replay Period: {self.start_time} to {self.end_time}")
        print(f"Duration: {(self.end_time - self.start_time).total_seconds() / 3600:.2f} hours")
        print(f"Replay Speed: {self.replay_speed}x")
        print()
        
        # P&L Summary
        print("P&L SUMMARY:")
        print(f"  Total P&L: ${self.performance_metrics['total_pnl']:,.2f}")
        print(f"  Realized P&L: ${self.performance_metrics['realized_pnl']:,.2f}")
        print(f"  Unrealized P&L: ${self.performance_metrics['unrealized_pnl']:,.2f}")
        print(f"  Peak P&L: ${self.performance_metrics['peak_pnl']:,.2f}")
        print(f"  Max Drawdown: ${self.performance_metrics['max_drawdown']:,.2f}")
        print()
        
        # Trading Activity
        print("TRADING ACTIVITY:")
        print(f"  Orders Placed: {self.performance_metrics['orders_placed']:,}")
        print(f"  Orders Filled: {self.performance_metrics['orders_filled']:,}")
        print(f"  Orders Cancelled: {self.performance_metrics['orders_cancelled']:,}")
        print(f"  Fill Rate: {self.performance_metrics['orders_filled'] / max(self.performance_metrics['orders_placed'], 1) * 100:.1f}%")
        print(f"  Quotes Generated: {self.performance_metrics['quotes_generated']:,}")
        print()
        
        # Financial Metrics
        print("FINANCIAL METRICS:")
        print(f"  Total Turnover: ${self.performance_metrics['total_turnover']:,.2f}")
        print(f"  Total Fees: ${self.performance_metrics['total_fees']:,.2f}")
        print(f"  Net P&L (after fees): ${self.performance_metrics['total_pnl'] - self.performance_metrics['total_fees']:,.2f}")
        print()
        
        # Performance Metrics
        print("PERFORMANCE METRICS:")
        print(f"  Average Spread: {self.performance_metrics['avg_spread_bps']:.2f} bps")
        print(f"  Average Fill Latency: {self.performance_metrics['avg_fill_latency_ms']:.2f} ms")
        print(f"  Inventory Drift: ${self.performance_metrics['inventory_drift']:,.2f}")
        print()
        
        # Per-symbol breakdown
        print("PER-SYMBOL BREAKDOWN:")
        print("-" * 80)
        for symbol, metrics in self.symbol_metrics.items():
            print(f"  {symbol}:")
            print(f"    Position: {metrics['position']}")
            print(f"    Avg Entry Price: ${metrics['avg_entry_price']:,.2f}")
            print(f"    Realized P&L: ${metrics['realized_pnl']:,.2f}")
            print(f"    Quotes Generated: {metrics['quotes_generated']:,}")
            print(f"    Orders Filled: {metrics['orders_filled']:,}")
            print(f"    Total Volume: {metrics['total_volume']}")
            print(f"    Avg Spread: {metrics['avg_spread_bps']:.2f} bps")
            print()
        
        # Strategy state
        print("STRATEGY STATE:")
        strategy_state = self.strategy.get_strategy_state()
        print(f"  Last Quote Times: {strategy_state.get('last_quote_times', {})}")
        print(f"  Performance: {strategy_state.get('performance', {})}")
        print()
        
        # Risk metrics
        print("RISK METRICS:")
        risk_state = self.risk_manager.get_risk_state()
        print(f"  Kill Switch: {risk_state.get('kill_switch_triggered', False)}")
        print(f"  Daily P&L: ${risk_state.get('daily_pnl', 0)}")
        print(f"  Max Drawdown: ${risk_state.get('max_drawdown', 0)}")
        print(f"  Total Exposure: ${risk_state.get('total_exposure', 0)}")
        print()
        
        print("=" * 80)


async def main():
    """Main entry point for replay CLI."""
    parser = argparse.ArgumentParser(
        description='Replay recorded market maker bot events for analysis',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Replay all events from today
  python cli/replay.py --data-dir ./data

  # Replay specific time range
  python cli/replay.py --data-dir ./data --from "2024-01-01 09:00" --to "2024-01-01 17:00"

  # Replay specific symbols at 2x speed
  python cli/replay.py --data-dir ./data --symbols BTCUSDT ETHUSDT --speed 2.0

  # Replay with limit for testing
  python cli/replay.py --data-dir ./data --limit 1000
        """
    )
    
    parser.add_argument(
        '--data-dir',
        type=Path,
        default=Path('./data'),
        help='Directory containing recorded data (default: ./data)'
    )
    
    parser.add_argument(
        '--from',
        dest='from_time',
        type=str,
        help='Start time for replay (format: YYYY-MM-DD HH:MM or YYYY-MM-DD)'
    )
    
    parser.add_argument(
        '--to',
        dest='to_time',
        type=str,
        help='End time for replay (format: YYYY-MM-DD HH:MM or YYYY-MM-DD)'
    )
    
    parser.add_argument(
        '--symbols',
        nargs='+',
        help='Specific symbols to replay (default: all from config)'
    )
    
    parser.add_argument(
        '--speed',
        type=float,
        default=1.0,
        help='Replay speed multiplier (0 = instant, 1.0 = real-time, 2.0 = 2x)'
    )
    
    parser.add_argument(
        '--limit',
        type=int,
        help='Maximum number of events to replay'
    )
    
    parser.add_argument(
        '--config',
        type=Path,
        default=Path('config.yaml'),
        help='Configuration file path (default: config.yaml)'
    )
    
    args = parser.parse_args()
    
    try:
        # Load configuration
        if not args.config.exists():
            print(f"Configuration file not found: {args.config}")
            sys.exit(1)
        
        config = Config.from_yaml(str(args.config))
        config.validate()
        
        # Determine symbols to replay
        symbols = args.symbols if args.symbols else config.trading.symbols
        print(f"Replaying events for symbols: {', '.join(symbols)}")
        
        # Parse time range
        from_time = None
        to_time = None
        
        if args.from_time:
            try:
                if len(args.from_time) == 10:  # YYYY-MM-DD
                    from_time = datetime.strptime(args.from_time, '%Y-%m-%d').replace(tzinfo=timezone.utc)
                else:  # YYYY-MM-DD HH:MM
                    from_time = datetime.strptime(args.from_time, '%Y-%m-%d %H:%M').replace(tzinfo=timezone.utc)
            except ValueError:
                print(f"Invalid from_time format: {args.from_time}")
                sys.exit(1)
        
        if args.to_time:
            try:
                if len(args.to_time) == 10:  # YYYY-MM-DD
                    to_time = datetime.strptime(args.to_time, '%Y-%m-%d').replace(tzinfo=timezone.utc)
                else:  # YYYY-MM-DD HH:MM
                    to_time = datetime.strptime(args.to_time, '%Y-%m-%d %H:%M').replace(tzinfo=timezone.utc)
            except ValueError:
                print(f"Invalid to_time format: {args.to_time}")
                sys.exit(1)
        
        # Validate data directory
        if not args.data_dir.exists():
            print(f"Data directory not found: {args.data_dir}")
            print("Please ensure the data directory exists and contains recorded events")
            sys.exit(1)
        
        # Create replay engine
        engine = ReplayEngine(config, symbols)
        
        # Load events
        engine.load_events(args.data_dir, from_time, to_time, args.limit)
        
        if not engine.events:
            print("No events found in the specified time range")
            sys.exit(0)
        
        # Replay events
        await engine.replay_events(args.speed)
        
        # Calculate final metrics
        engine.calculate_inventory_drift()
        
        # Print performance report
        engine.print_performance_report()
        
    except KeyboardInterrupt:
        print("\nReplay interrupted by user")
    except Exception as e:
        print(f"Replay error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == '__main__':
    asyncio.run(main())

