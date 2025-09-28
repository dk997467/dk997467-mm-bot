"""
Order book aggregation and processing.
"""

from typing import Any, Dict, Optional


class OrderBookAggregator:
    """Order book aggregator."""
    
    def __init__(self, data_recorder):
        """Initialize aggregator with data recorder."""
        self.data_recorder = data_recorder
        self.symbols = set()
    
    def add_symbol(self, symbol: str):
        """Add symbol to track."""
        self.symbols.add(symbol)
    
    def remove_symbol(self, symbol: str):
        """Remove symbol from tracking."""
        self.symbols.discard(symbol)
