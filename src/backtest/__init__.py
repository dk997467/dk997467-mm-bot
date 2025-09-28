"""
Backtesting module for market making strategy evaluation.

Provides:
- Order book replay from recorded data
- Queue-based fill simulation
- Performance metrics calculation
- Parameter optimization
"""

from .orderbook_replay import OrderBookReplay
from .queue_sim import QueueSimulator
from .run import BacktestRunner

__all__ = ['OrderBookReplay', 'QueueSimulator', 'BacktestRunner']
