"""
Order reconciliation module for synchronizing local state with exchange.
"""

import asyncio
import time
from typing import Dict, List, Set, Optional, Tuple
from dataclasses import dataclass
from enum import Enum

import orjson

from src.common.di import AppContext
from src.connectors.bybit_rest import BybitRESTConnector
from src.metrics.exporter import Metrics


class ReconciliationAction(Enum):
    """Actions taken during reconciliation."""
    MARK_FILLED = "mark_filled"
    MARK_CANCELLED = "mark_cancelled"
    CLOSE_ORPHAN = "close_orphan"
    REATTACH_FILL = "reattach_fill"
    PAUSE_QUOTING = "pause_quoting"
    RESUME_QUOTING = "resume_quoting"


@dataclass
class ReconciliationResult:
    """Result of reconciliation operation."""
    actions_taken: List[ReconciliationAction]
    orders_fixed: int
    orphans_closed: int
    fills_reattached: int
    hard_desync_detected: bool
    risk_paused: bool


@dataclass
class OrderState:
    """Order state for reconciliation."""
    order_id: str
    client_order_id: str
    symbol: str
    side: str
    price: float
    qty: float
    status: str
    filled_qty: float
    remaining_qty: float
    created_time: float
    last_update_time: float


class OrderReconciler:
    """Reconciles local order state with exchange state."""
    
    def __init__(self, ctx: AppContext, rest_connector: BybitRESTConnector):
        """Initialize reconciler with AppContext and REST connector."""
        self.ctx = ctx
        self.rest_connector = rest_connector
        self.metrics: Optional[Metrics] = None
        if hasattr(ctx, 'metrics'):
            self.metrics = ctx.metrics
        
        # Reconciliation configuration
        self.reconciliation_interval = 25  # seconds
        self.max_recent_history = 100
        self.hard_desync_threshold = 0.1  # 10% of orders mismatched
        
        # Local state tracking
        self.local_orders: Dict[str, OrderState] = {}  # client_order_id -> OrderState
        self.last_reconciliation = 0
        self.consecutive_failures = 0
        self.max_consecutive_failures = 3
        
        # Risk management
        self.risk_paused_tmp = False
        self.risk_pause_reason = ""
    
    async def start_reconciliation_loop(self):
        """Start the reconciliation loop."""
        while True:
            try:
                await self._reconcile_once()
                self.consecutive_failures = 0
            except Exception as e:
                self.consecutive_failures += 1
                print(f"Reconciliation error: {e}")
                
                if self.consecutive_failures >= self.max_consecutive_failures:
                    self._pause_risk_management("Max consecutive reconciliation failures")
                
                # Continue loop even on errors
                pass
            
            await asyncio.sleep(self.reconciliation_interval)
    
    async def _reconcile_once(self) -> ReconciliationResult:
        """Perform one reconciliation cycle."""
        start_time = time.time()
        
        # Fetch exchange state
        exchange_active = await self._fetch_exchange_active_orders()
        exchange_recent = await self._fetch_exchange_recent_history()
        
        # Perform reconciliation
        result = await self._reconcile_orders(exchange_active, exchange_recent)
        
        # Update metrics
        if self.metrics:
            reconciliation_time_ms = int((time.time() - start_time) * 1000)
            self.metrics.latency_ms.observe({"stage": "reconcile"}, reconciliation_time_ms)
        
        # Log results
        self._log_reconciliation_result(result)
        
        self.last_reconciliation = time.time()
        return result
    
    async def _fetch_exchange_active_orders(self) -> Dict[str, OrderState]:
        """Fetch currently active orders from exchange."""
        try:
            response = await self.rest_connector.get_active_orders()
            
            if response.get('retCode') != 0:
                raise Exception(f"Failed to fetch active orders: {response.get('retMsg')}")
            
            orders = {}
            for order_data in response.get('result', {}).get('list', []):
                order = self._parse_exchange_order(order_data)
                if order:
                    orders[order.client_order_id] = order
            
            return orders
            
        except Exception as e:
            print(f"Error fetching active orders: {e}")
            return {}
    
    async def _fetch_exchange_recent_history(self) -> Dict[str, OrderState]:
        """Fetch recent order history from exchange."""
        try:
            response = await self.rest_connector.get_order_history(limit=self.max_recent_history)
            
            if response.get('retCode') != 0:
                raise Exception(f"Failed to fetch order history: {response.get('retMsg')}")
            
            orders = {}
            for order_data in response.get('result', {}).get('list', []):
                order = self._parse_exchange_order(order_data)
                if order:
                    orders[order.client_order_id] = order
            
            return orders
            
        except Exception as e:
            print(f"Error fetching order history: {e}")
            return {}
    
    def _parse_exchange_order(self, order_data: Dict) -> Optional[OrderState]:
        """Parse exchange order data into OrderState."""
        try:
            # Check required fields
            required_fields = ['orderId', 'orderLinkId', 'symbol', 'side', 'price', 'qty', 'orderStatus']
            for field in required_fields:
                if not order_data.get(field):
                    return None
            
            return OrderState(
                order_id=order_data.get('orderId', ''),
                client_order_id=order_data.get('orderLinkId', ''),
                symbol=order_data.get('symbol', ''),
                side=order_data.get('side', ''),
                price=float(order_data.get('price', 0)),
                qty=float(order_data.get('qty', 0)),
                status=order_data.get('orderStatus', ''),
                filled_qty=float(order_data.get('cumExecQty', 0)),
                remaining_qty=float(order_data.get('cumExecQty', 0)),
                created_time=float(order_data.get('createdTime', 0)) / 1000,
                last_update_time=float(order_data.get('updatedTime', 0)) / 1000
            )
        except (ValueError, KeyError) as e:
            print(f"Error parsing exchange order: {e}")
            return None
    
    async def _reconcile_orders(self, exchange_active: Dict[str, OrderState], 
                               exchange_recent: Dict[str, OrderState]) -> ReconciliationResult:
        """Reconcile local orders with exchange state."""
        actions_taken = []
        orders_fixed = 0
        orphans_closed = 0
        fills_reattached = 0
        
        # Combine exchange state
        exchange_all = {**exchange_active, **exchange_recent}
        
        # Check for hard desync
        total_local = len(self.local_orders)
        total_exchange = len(exchange_all)
        
        if total_local > 0:
            mismatch_ratio = abs(total_local - total_exchange) / total_local
            if mismatch_ratio > self.hard_desync_threshold:
                actions_taken.append(ReconciliationAction.PAUSE_QUOTING)
                self._pause_risk_management(f"Hard desync detected: {mismatch_ratio:.2%} mismatch")
                if self.metrics:
                    self.metrics.on_reconcile_action("pause_quoting")
        
        # Process each local order
        for client_order_id, local_order in list(self.local_orders.items()):
            exchange_order = exchange_all.get(client_order_id)
            
            if not exchange_order:
                # Order not found on exchange - mark as filled or cancelled
                if local_order.status in ['New', 'PartiallyFilled']:
                    actions_taken.append(ReconciliationAction.MARK_FILLED)
                    self._mark_order_filled(local_order)
                    orders_fixed += 1
                    if self.metrics:
                        self.metrics.on_reconcile_action("mark_filled")
                else:
                    actions_taken.append(ReconciliationAction.MARK_CANCELLED)
                    self._mark_order_cancelled(local_order)
                    orders_fixed += 1
                    if self.metrics:
                        self.metrics.on_reconcile_action("mark_canceled")
            else:
                # Order exists on exchange - update local state
                if self._should_update_local_state(local_order, exchange_order):
                    self._update_local_order(local_order, exchange_order)
                    orders_fixed += 1
                    if self.metrics:
                        self.metrics.on_reconcile_action("update_state")
        
        # Check for orphaned exchange orders
        for client_order_id, exchange_order in exchange_all.items():
            if client_order_id not in self.local_orders:
                actions_taken.append(ReconciliationAction.CLOSE_ORPHAN)
                await self._close_orphan_order(exchange_order)
                orphans_closed += 1
                if self.metrics:
                    self.metrics.on_reconcile_action("close")
        
        # Check if we can resume quoting
        if self.risk_paused_tmp and len(actions_taken) == 0:
            actions_taken.append(ReconciliationAction.RESUME_QUOTING)
            self._resume_risk_management()
            if self.metrics:
                self.metrics.on_reconcile_action("resume_quoting")
        
        return ReconciliationResult(
            actions_taken=actions_taken,
            orders_fixed=orders_fixed,
            orphans_closed=orphans_closed,
            fills_reattached=fills_reattached,
            hard_desync_detected=ReconciliationAction.PAUSE_QUOTING in actions_taken,
            risk_paused=self.risk_paused_tmp
        )
    
    def _should_update_local_state(self, local: OrderState, exchange: OrderState) -> bool:
        """Check if local state should be updated from exchange."""
        return (local.status != exchange.status or
                local.filled_qty != exchange.filled_qty or
                local.remaining_qty != exchange.remaining_qty)
    
    def _update_local_order(self, local: OrderState, exchange: OrderState):
        """Update local order state from exchange."""
        local.status = exchange.status
        local.filled_qty = exchange.filled_qty
        local.remaining_qty = exchange.remaining_qty
        local.last_update_time = exchange.last_update_time
    
    def _mark_order_filled(self, order: OrderState):
        """Mark order as filled."""
        order.status = 'Filled'
        order.filled_qty = order.qty
        order.remaining_qty = 0
        order.last_update_time = time.time()
    
    def _mark_order_cancelled(self, order: OrderState):
        """Mark order as cancelled."""
        order.status = 'Cancelled'
        order.last_update_time = time.time()
    
    async def _close_orphan_order(self, exchange_order: OrderState):
        """Close orphaned order on exchange."""
        try:
            await self.rest_connector.cancel_order(
                symbol=exchange_order.symbol,
                order_id=exchange_order.order_id
            )
        except Exception as e:
            print(f"Failed to close orphan order {exchange_order.order_id}: {e}")
    
    def _pause_risk_management(self, reason: str):
        """Pause risk management temporarily."""
        self.risk_paused_tmp = True
        self.risk_pause_reason = reason
        print(f"Risk management paused: {reason}")
        
        if self.metrics:
            self.metrics.risk_paused.set(1)
    
    def _resume_risk_management(self):
        """Resume risk management."""
        self.risk_paused_tmp = False
        self.risk_pause_reason = ""
        print("Risk management resumed")
        
        if self.metrics:
            self.metrics.risk_paused.set(0)
    
    def _log_reconciliation_result(self, result: ReconciliationResult):
        """Log reconciliation results."""
        print(f"Reconciliation completed: {result.orders_fixed} orders fixed, "
              f"{result.orphans_closed} orphans closed, "
              f"risk_paused={result.risk_paused}")
        
        for action in result.actions_taken:
            print(f"  Action: {action.value}")
    
    def add_local_order(self, order: OrderState):
        """Add order to local tracking."""
        self.local_orders[order.client_order_id] = order
    
    def remove_local_order(self, client_order_id: str):
        """Remove order from local tracking."""
        if client_order_id in self.local_orders:
            del self.local_orders[client_order_id]
    
    def get_local_order(self, client_order_id: str) -> Optional[OrderState]:
        """Get local order by client order ID."""
        return self.local_orders.get(client_order_id)
    
    def is_risk_paused(self) -> bool:
        """Check if risk management is paused."""
        return self.risk_paused_tmp
    
    def get_risk_pause_reason(self) -> str:
        """Get reason for risk management pause."""
        return self.risk_pause_reason
