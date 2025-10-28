"""
Live Trading Module — Real-time order execution and position management.

This module provides the core trading engine for live market making:
- Exchange connectivity (Bybit, with mock support)
- Order routing and lifecycle management
- Position tracking and reconciliation
- Prometheus metrics export

Components:
- exchange_client: Exchange API client (place/cancel orders)
- order_router: Order routing with retry/backoff
- state_machine: Order state FSM (pending→filled/canceled/rejected)
- positions: Position tracking and P&L calculation
- metrics: Prometheus metrics export

Usage:
    from tools.live import (
        create_client,
        create_router,
        create_fsm,
        create_tracker,
        LiveExecutionMetrics,
    )
    
    # Initialize components
    client = create_client(exchange="bybit", mock=True)
    router = create_router(exchange="bybit", mock=True)
    fsm = create_fsm()
    tracker = create_tracker()
    metrics = LiveExecutionMetrics()
    
    # Place order
    fsm.create_order("order-1", "BTCUSDT", "Buy", 0.01)
    
    with metrics.track_order_latency("BTCUSDT"):
        response = router.place_order(
            client_order_id="order-1",
            symbol="BTCUSDT",
            side="Buy",
            qty=0.01,
            price=50000.0,
        )
        metrics.increment_orders_placed("BTCUSDT", "Buy")
    
    # Handle fills
    fills = client.poll_fills("order-1")
    for fill in fills:
        tracker.apply_fill(fill)
    
    # Export metrics
    prom_text = metrics.export_prometheus()
"""

from tools.live.exchange_client import (
    ExchangeClient,
    OrderRequest,
    OrderResponse,
    FillEvent,
    create_client,
)

from tools.live.order_router import (
    OrderRouter,
    RouteMetrics,
    create_router,
)

from tools.live.state_machine import (
    OrderStateMachine,
    OrderState,
    EventType,
    OrderEvent,
    OrderStateRecord,
    create_fsm,
)

from tools.live.positions import (
    PositionTracker,
    Position,
    create_tracker,
)

from tools.live.metrics import (
    LiveExecutionMetrics,
    get_global_metrics,
    reset_global_metrics,
)

from tools.live.risk_monitor import (
    RuntimeRiskMonitor,
)

from tools.live.secrets import (
    SecretProvider,
    SecretStore,
    InMemorySecretStore,
    AwsSecretsStore,
    APICredentials,
    SecretMetadata,
    get_api_credentials,
    get_secret_provider,
    clear_cache,
)

from tools.live.exchange import (
    IExchangeClient,
    FakeExchangeClient,
    Side,
    OrderStatus,
    PlaceOrderRequest,
    PlaceOrderResponse,
    FillEvent as ExchangeFillEvent,
    OpenOrder,
    Position as ExchangePosition,
)

from tools.live.order_store import (
    Order,
    OrderState as OrderStoreState,
    InMemoryOrderStore,
)

from tools.live.execution_loop import (
    ExecutionLoop,
    ExecutionParams,
    Quote,
    run_shadow_demo,
)

__all__ = [
    # Exchange Client
    "ExchangeClient",
    "OrderRequest",
    "OrderResponse",
    "FillEvent",
    "create_client",
    
    # Order Router
    "OrderRouter",
    "RouteMetrics",
    "create_router",
    
    # State Machine
    "OrderStateMachine",
    "OrderState",
    "EventType",
    "OrderEvent",
    "OrderStateRecord",
    "create_fsm",
    
    # Positions
    "PositionTracker",
    "Position",
    "create_tracker",
    
    # Metrics
    "LiveExecutionMetrics",
    "get_global_metrics",
    "reset_global_metrics",
    
    # Risk Monitor
    "RuntimeRiskMonitor",
    
    # Secrets Management
    "SecretProvider",
    "SecretStore",
    "InMemorySecretStore",
    "AwsSecretsStore",
    "APICredentials",
    "SecretMetadata",
    "get_api_credentials",
    "get_secret_provider",
    "clear_cache",
    
    # P0.1 Execution Engine
    "IExchangeClient",
    "FakeExchangeClient",
    "Side",
    "OrderStatus",
    "PlaceOrderRequest",
    "PlaceOrderResponse",
    "ExchangeFillEvent",
    "OpenOrder",
    "ExchangePosition",
    "Order",
    "OrderStoreState",
    "InMemoryOrderStore",
    "ExecutionLoop",
    "ExecutionParams",
    "Quote",
    "run_shadow_demo",
]
