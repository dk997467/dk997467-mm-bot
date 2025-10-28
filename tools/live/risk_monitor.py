#!/usr/bin/env python3
"""
Runtime Risk Monitor: Pre-trade limits and auto-freeze on edge degradation.

Public API:
    RuntimeRiskMonitor: Main risk monitoring class
"""
from __future__ import annotations
from typing import Callable

from tools.obs import jsonlog, metrics

# Structured logger for observability
_structured_logger = jsonlog.get_logger("mm.risk", default_ctx={"component": "risk_monitor"})


class RuntimeRiskMonitor:
    """
    Runtime risk monitor for pre-trade limits and edge-based auto-freeze.
    
    Features:
    - Per-symbol inventory limits (USD notional)
    - Total portfolio notional limits (USD)
    - Auto-freeze on edge degradation below threshold
    - Position tracking and reconciliation
    
    Metrics (as instance attributes):
    - blocks_total: Total number of blocked orders
    - freezes_total: Total number of freeze events
    - last_freeze_reason: Last freeze reason string
    - last_freeze_symbol: Last symbol that triggered freeze
    
    Example:
        >>> monitor = RuntimeRiskMonitor(
        ...     max_inventory_usd_per_symbol=10000.0,
        ...     max_total_notional_usd=50000.0,
        ...     edge_freeze_threshold_bps=1.5
        ... )
        >>> 
        >>> # Check if order is allowed
        >>> can_place = monitor.check_before_order("BTCUSDT", "buy", 0.1, 50000.0)
        >>> 
        >>> # Update position after fill
        >>> monitor.on_fill("BTCUSDT", "buy", 0.1, 50000.0)
        >>> 
        >>> # Monitor edge and auto-freeze if degraded
        >>> monitor.on_edge_update("BTCUSDT", 1.2)  # Below threshold -> freeze
    """
    
    def __init__(
        self,
        *,
        max_inventory_usd_per_symbol: float,
        max_total_notional_usd: float,
        edge_freeze_threshold_bps: float,
        get_mark_price: Callable[[str], float] | None = None
    ):
        """
        Initialize runtime risk monitor.
        
        Args:
            max_inventory_usd_per_symbol: Maximum USD notional per symbol
            max_total_notional_usd: Maximum total USD notional across all positions
            edge_freeze_threshold_bps: Edge threshold in BPS (freeze if below)
            get_mark_price: Optional callable to get mark price for a symbol
                           Defaults to lambda symbol: 1.0
        """
        self.max_inventory_usd_per_symbol = max_inventory_usd_per_symbol
        self.max_total_notional_usd = max_total_notional_usd
        self.edge_freeze_threshold_bps = edge_freeze_threshold_bps
        self.get_mark_price = get_mark_price or (lambda symbol: 1.0)
        
        # Position tracking
        self._positions: dict[str, float] = {}  # symbol -> qty (signed)
        
        # Freeze state
        self._frozen = False
        
        # Metrics
        self.blocks_total = 0
        self.freezes_total = 0
        self.last_freeze_reason: str | None = None
        self.last_freeze_symbol: str | None = None
    
    def check_before_order(
        self,
        symbol: str,
        side: str,
        qty: float,
        price: float | None = None
    ) -> bool:
        """
        Check if order can be placed without violating limits.
        
        Args:
            symbol: Trading symbol (e.g., "BTCUSDT")
            side: Order side ("buy" or "sell")
            qty: Order quantity (absolute value)
            price: Order price (uses get_mark_price if None)
        
        Returns:
            True if order is allowed, False if blocked
        """
        # Frozen state blocks all orders
        if self._frozen:
            self.blocks_total += 1
            return False
        
        # Calculate effective price
        effective_price = price if price is not None else self.get_mark_price(symbol)
        
        # Calculate notional change
        qty_signed = qty if side.lower() == "buy" else -qty
        notional_change = abs(qty_signed * effective_price)
        
        # Calculate new position after this order
        current_pos = self._positions.get(symbol, 0.0)
        new_pos = current_pos + qty_signed
        new_notional = abs(new_pos * effective_price)
        
        # Check per-symbol limit
        if new_notional > self.max_inventory_usd_per_symbol:
            self.blocks_total += 1
            return False
        
        # Calculate total notional after this order
        # Use mark price for all symbols for consistency
        total_notional = 0.0
        
        # Calculate notional for all symbols with new position for this symbol
        all_symbols = set(self._positions.keys()) | {symbol}
        for sym in all_symbols:
            if sym == symbol:
                # Use new position for this symbol with mark price
                pos_notional = abs(new_pos * self.get_mark_price(sym))
            else:
                # Use existing position for other symbols
                pos_qty = self._positions.get(sym, 0.0)
                pos_notional = abs(pos_qty * self.get_mark_price(sym))
            
            total_notional += pos_notional
        
        # Check total notional limit
        if total_notional > self.max_total_notional_usd:
            self.blocks_total += 1
            return False
        
        # All checks passed
        return True
    
    def on_fill(self, symbol: str, side: str, qty: float, price: float) -> None:
        """
        Update position after order fill.
        
        Args:
            symbol: Trading symbol
            side: Fill side ("buy" or "sell")
            qty: Fill quantity (absolute value)
            price: Fill price
        """
        qty_signed = qty if side.lower() == "buy" else -qty
        current_pos = self._positions.get(symbol, 0.0)
        self._positions[symbol] = current_pos + qty_signed
    
    def on_edge_update(self, symbol: str, net_bps: float) -> None:
        """
        Process edge update and auto-freeze if below threshold.
        
        Args:
            symbol: Trading symbol
            net_bps: Current net edge in basis points
        """
        if net_bps < self.edge_freeze_threshold_bps:
            reason = f"Edge degradation: {net_bps:.2f} BPS < {self.edge_freeze_threshold_bps:.2f} BPS"
            self.freeze(reason, symbol)
    
    def get_positions(self) -> dict[str, float]:
        """
        Get current positions by symbol.
        
        Returns:
            Dictionary mapping symbol to signed quantity
        """
        return dict(self._positions)
    
    def is_frozen(self) -> bool:
        """
        Check if risk monitor is in frozen state.
        
        Returns:
            True if frozen, False otherwise
        """
        return self._frozen
    
    def freeze(self, reason: str, symbol: str | None = None) -> None:
        """
        Freeze trading and record reason.
        
        Args:
            reason: Freeze reason string
            symbol: Optional symbol that triggered freeze
        """
        if not self._frozen:
            self._frozen = True
            self.freezes_total += 1
            
            # Observability: log freeze event
            _structured_logger.warning(
                "risk_freeze",
                reason=reason,
                symbol=symbol,
                freezes_total=self.freezes_total,
            )
            metrics.FREEZE_EVENTS.inc()
        
        self.last_freeze_reason = reason
        self.last_freeze_symbol = symbol
    
    def reset(self) -> None:
        """
        Reset risk monitor state (for testing).
        
        Clears:
        - Frozen state
        - Positions
        - Freeze reason and symbol
        - Does NOT reset metrics (blocks_total, freezes_total)
        """
        self._frozen = False
        self._positions.clear()
        self.last_freeze_reason = None
        self.last_freeze_symbol = None


if __name__ == "__main__":
    # Quick smoke test
    monitor = RuntimeRiskMonitor(
        max_inventory_usd_per_symbol=10000.0,
        max_total_notional_usd=50000.0,
        edge_freeze_threshold_bps=1.5
    )
    
    # Test: order allowed
    can_place = monitor.check_before_order("BTCUSDT", "buy", 0.1, 50000.0)
    print(f"Order allowed: {can_place}")
    
    # Test: fill position
    monitor.on_fill("BTCUSDT", "buy", 0.1, 50000.0)
    print(f"Positions: {monitor.get_positions()}")
    
    # Test: edge degradation triggers freeze
    monitor.on_edge_update("BTCUSDT", 1.2)
    print(f"Frozen: {monitor.is_frozen()}")
    print(f"Freeze reason: {monitor.last_freeze_reason}")
    
    # Test: blocked after freeze
    can_place_after = monitor.check_before_order("ETHUSDT", "buy", 1.0, 3000.0)
    print(f"Order allowed after freeze: {can_place_after}")
    print(f"Blocks total: {monitor.blocks_total}")
