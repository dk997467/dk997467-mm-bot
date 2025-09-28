"""
Market Maker Bot - High-Frequency Trading Bot for Bybit V5 USDT Perpetuals
"""

__version__ = "2.0.0"
__author__ = "MM Bot Team"

# Import core modules
from .common.config import Config, get_config, reload_config, ConfigLoader
from .common.models import Order, OrderBook, QuoteRequest, Side, Trade, OrderStatus, TimeInForce
from .strategy.quoting import MarketMakingStrategy
from .execution.order_manager import OrderManager
from .risk.risk_manager import RiskManager
from .storage.recorder import Recorder
from .metrics.exporter import MetricsExporter

# Load configuration on import
try:
    config = get_config()
except Exception as e:
    print(f"Warning: Failed to load configuration: {e}")
    config = None

__all__ = [
    # Core classes
    "MarketMakingStrategy",
    "OrderManager", 
    "RiskManager",
    "Recorder",
    "MetricsExporter",
    
    # Models
    "Order",
    "OrderBook", 
    "QuoteRequest",
    "Side",
    "Trade",
    "OrderStatus",
    "TimeInForce",
    
    # Configuration
    "Config",
    "get_config",
    "reload_config",
    "ConfigLoader",
    
    # Version
    "__version__",
]
