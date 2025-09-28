"""
Simple Dependency Injection context.
"""

from dataclasses import dataclass
from typing import Optional, TYPE_CHECKING, Dict

from .config import AppConfig

if TYPE_CHECKING:
    from src.storage.research_recorder import ResearchRecorder
    from src.metrics.pnl import PnLAttributor
    from src.metrics.exporter import Metrics
    from src.connectors.bybit_rest import BybitRESTConnector
    from src.connectors.bybit_websocket import BybitWebSocketConnector
    from src.execution.order_manager import OrderManager
    from src.execution.reconcile import OrderReconciler
    from src.portfolio.allocator import PortfolioAllocator
    from src.marketdata.vola import VolatilityManager


@dataclass
class AppContext:
    cfg: AppConfig
    # Extend later with: metrics, http server refs, etc.
    
    # Research pipeline components
    research_recorder: Optional['ResearchRecorder'] = None
    pnl_attributor: Optional['PnLAttributor'] = None
    
    # Metrics and monitoring
    metrics: Optional['Metrics'] = None
    
    # Exchange connectivity
    bybit_rest: Optional['BybitRESTConnector'] = None
    bybit_websocket: Optional['BybitWebSocketConnector'] = None
    
    # Order management and reconciliation
    order_manager: Optional['OrderManager'] = None
    order_reconciler: Optional['OrderReconciler'] = None
    
    # Portfolio allocation
    allocator: Optional['PortfolioAllocator'] = None
    vola_manager: Optional['VolatilityManager'] = None
    portfolio_targets: Optional[Dict[str, 'PortfolioTarget']] = None


