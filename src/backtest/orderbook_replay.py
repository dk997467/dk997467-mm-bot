"""
Order book replay module for backtesting.

Provides functionality to replay L2 order book data from recorded files
or generate synthetic data for testing purposes.
"""

import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Generator, Any
from decimal import Decimal

import polars as pl

from src.common.models import OrderBook, PriceLevel
from src.storage.research_recorder import ResearchRecord

logger = logging.getLogger(__name__)


class OrderBookReplay:
    """Replay order book data from recorded research files."""
    
    def __init__(self, data_dir: str = "./data/research"):
        """Initialize order book replay."""
        self.data_dir = Path(data_dir)
        self.data_dir.mkdir(parents=True, exist_ok=True)
        
        # Data files cache
        self.data_files: Dict[str, List[Path]] = {}  # symbol -> list of file paths
        self.current_file_index: Dict[str, int] = {}  # symbol -> current file index
        
        logger.info(f"Order book replay initialized: {data_dir}")
    
    def load_symbol_data(self, symbol: str, start_time: Optional[datetime] = None, 
                        end_time: Optional[datetime] = None) -> bool:
        """Load data files for a symbol within time range."""
        try:
            # Find all research files for the symbol
            pattern = f"research_*.parquet"
            all_files = list(self.data_dir.glob(pattern))
            
            if not all_files:
                logger.warning(f"No research data files found in {self.data_dir}")
                return False
            
            # Filter by symbol if data contains symbol column
            # For now, assume all files contain data for all symbols
            self.data_files[symbol] = sorted(all_files)
            self.current_file_index[symbol] = 0
            
            logger.info(f"Loaded {len(self.data_files[symbol])} data files for {symbol}")
            return True
            
        except Exception as e:
            logger.error(f"Error loading data for {symbol}: {e}")
            return False
    
    def replay_symbol(self, symbol: str, start_time: Optional[datetime] = None,
                     end_time: Optional[datetime] = None) -> Generator[OrderBook, None, None]:
        """Replay order book data for a symbol."""
        if symbol not in self.data_files:
            if not self.load_symbol_data(symbol, start_time, end_time):
                return
        
        for file_path in self.data_files[symbol]:
            try:
                # Read parquet file
                df = pl.read_parquet(file_path)
                
                # Filter by symbol and time range if specified
                if 'symbol' in df.columns:
                    df = df.filter(pl.col('symbol') == symbol)
                
                if start_time and 'ts' in df.columns:
                    df = df.filter(pl.col('ts') >= start_time)
                
                if end_time and 'ts' in df.columns:
                    df = df.filter(pl.col('ts') <= end_time)
                
                # Sort by timestamp
                if 'ts' in df.columns:
                    df = df.sort('ts')
                
                # Yield order book snapshots
                for row in df.iter_rows(named=True):
                    orderbook = self._row_to_orderbook(row)
                    if orderbook:
                        yield orderbook
                        
            except Exception as e:
                logger.error(f"Error reading file {file_path}: {e}")
                continue
    
    def _row_to_orderbook(self, row: Dict[str, Any]) -> Optional[OrderBook]:
        """Convert data row to OrderBook object."""
        try:
            # Extract basic order book data
            if 'ts' not in row or 'mid' not in row:
                return None
            
            timestamp = row['ts']
            if isinstance(timestamp, str):
                timestamp = datetime.fromisoformat(timestamp.replace('Z', '+00:00'))
            
            # Create synthetic order book from mid price and spread
            mid_price = float(row['mid'])
            spread_bps = float(row.get('spread', 10.0))  # Default 10 bps spread
            
            # Calculate bid/ask prices
            spread = spread_bps / 10000
            best_bid = mid_price * (1 - spread / 2)
            best_ask = mid_price * (1 + spread / 2)
            
            # Create price levels
            bids = [PriceLevel(price=Decimal(str(best_bid)), size=Decimal("1.0"), sequence=1)]
            asks = [PriceLevel(price=Decimal(str(best_ask)), size=Decimal("1.0"), sequence=1)]
            
            # Add additional levels if available
            if row.get('our_bid_1') and row.get('our_bid_1_size'):
                bid_1 = float(row['our_bid_1'])
                bid_1_size = float(row['our_bid_1_size'])
                if bid_1 < best_bid:
                    bids.append(PriceLevel(price=Decimal(str(bid_1)), size=Decimal(str(bid_1_size)), sequence=2))
            
            if row.get('our_ask_1') and row.get('our_ask_1_size'):
                ask_1 = float(row['our_ask_1'])
                ask_1_size = float(row['our_ask_1_size'])
                if ask_1 > best_ask:
                    asks.append(PriceLevel(price=Decimal(str(ask_1)), size=Decimal(str(ask_1_size)), sequence=2))
            
            return OrderBook(
                symbol=row.get('symbol', 'UNKNOWN'),
                timestamp=timestamp,
                sequence=1,
                bids=bids,
                asks=asks
            )
            
        except Exception as e:
            logger.error(f"Error converting row to order book: {e}")
            return None
    
    def generate_synthetic_data(self, symbol: str, start_time: datetime, 
                               end_time: datetime, interval_ms: int = 1000) -> Generator[OrderBook, None, None]:
        """Generate synthetic order book data for testing."""
        current_time = start_time
        sequence = 1
        
        while current_time <= end_time:
            # Generate synthetic mid price with some volatility
            base_price = 50000.0  # Base price for BTCUSDT
            volatility = 0.001  # 0.1% volatility per tick
            
            # Simple random walk
            import random
            price_change = random.gauss(0, volatility)
            mid_price = base_price * (1 + price_change)
            
            # Generate spread
            spread_bps = random.uniform(5, 20)  # 5-20 bps spread
            spread = spread_bps / 10000
            
            best_bid = mid_price * (1 - spread / 2)
            best_ask = mid_price * (1 + spread / 2)
            
            # Generate synthetic order book
            bids = []
            asks = []
            
            # Add multiple levels
            for i in range(3):
                bid_price = best_bid * (1 - i * 0.001)  # Each level 0.1% lower
                ask_price = best_ask * (1 + i * 0.001)  # Each level 0.1% higher
                
                bid_size = random.uniform(0.1, 2.0)
                ask_size = random.uniform(0.1, 2.0)
                
                bids.append(PriceLevel(
                    price=Decimal(str(bid_price)),
                    size=Decimal(str(bid_size)),
                    sequence=sequence + i
                ))
                
                asks.append(PriceLevel(
                    price=Decimal(str(ask_price)),
                    size=Decimal(str(ask_size)),
                    sequence=sequence + i
                ))
            
            orderbook = OrderBook(
                symbol=symbol,
                timestamp=current_time,
                sequence=sequence,
                bids=bids,
                asks=asks
            )
            
            yield orderbook
            
            current_time = current_time.replace(microsecond=0)
            current_time = current_time.replace(microsecond=interval_ms * 1000)
            sequence += 1
    
    def get_data_summary(self, symbol: str) -> Dict[str, Any]:
        """Get summary of available data for a symbol."""
        if symbol not in self.data_files:
            return {'error': 'Symbol not loaded'}
        
        summary = {
            'symbol': symbol,
            'total_files': len(self.data_files[symbol]),
            'file_paths': [str(f) for f in self.data_files[symbol]],
            'current_file_index': self.current_file_index.get(symbol, 0)
        }
        
        # Try to get time range from first and last files
        try:
            if self.data_files[symbol]:
                first_file = self.data_files[symbol][0]
                last_file = self.data_files[symbol][-1]
                
                first_df = pl.read_parquet(first_file)
                last_df = pl.read_parquet(last_file)
                
                if 'ts' in first_df.columns and 'ts' in last_df.columns:
                    summary['start_time'] = first_df['ts'].min()
                    summary['end_time'] = last_df['ts'].max()
                    summary['total_records'] = sum(len(pl.read_parquet(f)) for f in self.data_files[symbol])
        except Exception as e:
            summary['error'] = f"Error reading data: {e}"
        
        return summary
    
    def reset_symbol(self, symbol: str):
        """Reset replay state for a symbol."""
        if symbol in self.data_files:
            del self.data_files[symbol]
        if symbol in self.current_file_index:
            del self.current_file_index[symbol]
        
        logger.info(f"Reset replay state for {symbol}")
