"""
Reconciliation of orders, fills, and positions.

Compares local state (order_store) with exchange state to detect:
- Missing orders (local vs remote)
- Position drift
- Fee/rebate accounting
"""

import json
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any, Callable, Protocol

from tools.live import fees as fees_module
from tools.obs import metrics


class IExchangeClient(Protocol):
    """Protocol for exchange client providing reconciliation data."""
    
    def list_open_orders(self, symbol: str | None = None) -> list[dict[str, Any]]:
        """List open orders from exchange."""
        ...
    
    def get_position(self, symbol: str) -> dict[str, Any]:
        """Get position for symbol."""
        ...


class IOrderStore(Protocol):
    """Protocol for order store providing local state."""
    
    def list_open_orders(self, symbol: str | None = None) -> list[dict[str, Any]]:
        """List open orders from local store."""
        ...
    
    def list_fills(self, symbol: str | None = None) -> list[dict[str, Any]]:
        """List fills from local store."""
        ...
    
    def get_position(self, symbol: str) -> dict[str, Any]:
        """Get local position for symbol."""
        ...


@dataclass
class ReconReport:
    """
    Reconciliation report.
    
    Attributes:
        timestamp_ms: Report timestamp
        symbols: List of symbols reconciled
        orders_local_only: Order IDs present locally but not remotely
        orders_remote_only: Order IDs present remotely but not locally
        position_deltas: Position differences by symbol (qty delta)
        fees_report: Fees and rebates summary
        divergence_count: Total number of divergences
    """
    
    timestamp_ms: int
    symbols: list[str]
    orders_local_only: list[str] = field(default_factory=list)
    orders_remote_only: list[str] = field(default_factory=list)
    position_deltas: dict[str, Decimal] = field(default_factory=dict)
    fees_report: dict[str, Any] = field(default_factory=dict)
    divergence_count: int = 0
    
    def to_dict(self) -> dict[str, Any]:
        """Convert to JSON-serializable dict."""
        return {
            "timestamp_ms": self.timestamp_ms,
            "symbols": sorted(self.symbols),
            "orders_local_only": sorted(self.orders_local_only),
            "orders_remote_only": sorted(self.orders_remote_only),
            "position_deltas": {
                sym: float(delta) for sym, delta in sorted(self.position_deltas.items())
            },
            "fees_report": {
                k: float(v) if isinstance(v, Decimal) else v
                for k, v in self.fees_report.items()
            },
            "divergence_count": self.divergence_count,
        }
    
    def to_json(self) -> str:
        """Serialize to compact JSON with sorted keys."""
        return json.dumps(self.to_dict(), sort_keys=True, separators=(",", ":")) + "\n"


def reconcile_orders_fills_positions(
    exchange: IExchangeClient,
    store: IOrderStore,
    clock: Callable[[], int],
    symbols: list[str] | None = None,
    fee_schedule: fees_module.FeeSchedule | None = None,
) -> ReconReport:
    """
    Reconcile local state with exchange state.
    
    Args:
        exchange: Exchange client
        store: Local order store
        clock: Clock function returning current timestamp in ms
        symbols: List of symbols to reconcile (None = all)
        fee_schedule: Fee schedule for fee calculation (optional)
    
    Returns:
        ReconReport with divergences and fees summary
    """
    timestamp_ms = clock()
    symbols = symbols or []
    
    # Reconcile orders
    local_orders = store.get_open_orders() if hasattr(store, 'get_open_orders') else []
    
    # Get all remote orders for specified symbols
    remote_orders_by_symbol = {}
    if symbols:
        for symbol in symbols:
            try:
                remote_orders_by_symbol[symbol] = exchange.get_open_orders(symbol)
            except Exception:
                pass  # Skip symbols with errors
    
    # Build ID sets
    local_ids = {order.client_order_id for order in local_orders if hasattr(order, 'client_order_id')}
    remote_ids = set()
    for symbol_orders in remote_orders_by_symbol.values():
        for order in symbol_orders:
            if hasattr(order, 'client_order_id'):
                remote_ids.add(order.client_order_id)
    
    orders_local_only = sorted(list(local_ids - remote_ids))
    orders_remote_only = sorted(list(remote_ids - local_ids))
    
    # Reconcile positions
    position_deltas = {}
    
    # Get positions from exchange (dict[str, Decimal])
    remote_positions = exchange.get_positions() if hasattr(exchange, 'get_positions') else {}
    
    # Calculate local positions from fills (if available)
    local_positions = {}
    if hasattr(store, 'get_all_fills'):
        for fill in store.get_all_fills():
            symbol = fill.symbol if hasattr(fill, 'symbol') else None
            if symbol:
                qty = fill.qty if hasattr(fill, 'qty') else Decimal("0")
                side = fill.side if hasattr(fill, 'side') else None
                
                # Aggregate position (buy adds, sell subtracts)
                if side and hasattr(side, 'value'):
                    if side.value.lower() == "buy":
                        local_positions[symbol] = local_positions.get(symbol, Decimal("0")) + qty
                    elif side.value.lower() == "sell":
                        local_positions[symbol] = local_positions.get(symbol, Decimal("0")) - qty
    
    # Compare positions
    all_symbols = set(local_positions.keys()) | set(remote_positions.keys())
    for symbol in all_symbols:
        local_qty = local_positions.get(symbol, Decimal("0"))
        remote_qty = remote_positions.get(symbol, Decimal("0"))
        
        if local_qty != remote_qty:
            position_deltas[symbol] = {
                "local": local_qty,
                "remote": remote_qty,
                "delta": remote_qty - local_qty,
            }
    
    # Calculate fees and rebates
    fees_report = {}
    if fee_schedule is not None:
        try:
            # Get fills from store (may not exist in all implementations)
            all_fills = store.get_all_fills() if hasattr(store, 'get_all_fills') else []
            fills = []
            
            for fill_obj in all_fills:
                # Extract attributes from fill object or dict
                if hasattr(fill_obj, 'side'):
                    side_val = fill_obj.side.value if hasattr(fill_obj.side, 'value') else str(fill_obj.side)
                else:
                    side_val = fill_obj.get("side", "BUY")
                
                fills.append(fees_module.Fill(
                    symbol=getattr(fill_obj, 'symbol', fill_obj.get("symbol", "")),
                    side=side_val.lower() if isinstance(side_val, str) else "buy",
                    qty=Decimal(str(getattr(fill_obj, 'qty', fill_obj.get("qty", 0)))),
                    price=Decimal(str(getattr(fill_obj, 'price', fill_obj.get("price", 0)))),
                    is_maker=getattr(fill_obj, 'is_maker', fill_obj.get("is_maker", True)),
                    fee_currency=getattr(fill_obj, 'fee_currency', fill_obj.get("fee_currency", "USDT")),
                    fee_amount=Decimal(str(getattr(fill_obj, 'fee_amount', fill_obj.get("fee_amount", 0)))),
                ))
            
            fees_report = fees_module.calc_fees_and_rebates(fills, fee_schedule)
        except Exception:
            # Fallback if fee calculation fails
            fees_report = {}
    
    # Count divergences
    divergence_count = (
        len(orders_local_only) +
        len(orders_remote_only) +
        len(position_deltas)
    )
    
    # Emit metrics
    if orders_local_only:
        metrics.RECON_DIVERGENCE.inc(type="orders_local_only", amount=len(orders_local_only))
    if orders_remote_only:
        metrics.RECON_DIVERGENCE.inc(type="orders_remote_only", amount=len(orders_remote_only))
    if position_deltas:
        metrics.RECON_DIVERGENCE.inc(type="position_delta", amount=len(position_deltas))
    
    # Update fee metrics
    if fees_report and "maker_taker_ratio" in fees_report:
        metrics.MAKER_TAKER_RATIO.set(float(fees_report["maker_taker_ratio"]))
    if fees_report and "net_bps" in fees_report:
        metrics.NET_BPS.set(float(fees_report["net_bps"]))
    
    return ReconReport(
        timestamp_ms=timestamp_ms,
        symbols=symbols,
        orders_local_only=orders_local_only,
        orders_remote_only=orders_remote_only,
        position_deltas=position_deltas,
        fees_report=fees_report,
        divergence_count=divergence_count,
    )

