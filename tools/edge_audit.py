#!/usr/bin/env python3
"""Edge audit utilities for quote and trade analysis."""
from __future__ import annotations
import math
from typing import Dict, List, Any


def _finite(x: Any) -> bool:
    """Check if value is finite (not NaN, not inf)."""
    if x is None:
        return False
    try:
        return math.isfinite(float(x))
    except (ValueError, TypeError):
        return False


def _index_quotes(quotes: List[Dict[str, Any]]) -> Dict[str, List[Dict[str, Any]]]:
    """
    Index quotes by symbol.
    
    Args:
        quotes: List of quote dicts with 'symbol' key
    
    Returns:
        Dictionary mapping symbol to list of quotes
    """
    indexed = {}
    for quote in quotes:
        symbol = quote.get("symbol")
        if symbol:
            if symbol not in indexed:
                indexed[symbol] = []
            indexed[symbol].append(quote)
    
    return indexed


def _agg_symbols(trades: List[Dict[str, Any]], qidx: Dict[str, Any] | None = None) -> Dict[str, Dict[str, Any]]:
    """
    Aggregate trades by symbol, computing edge components.
    
    Args:
        trades: List of trade dicts with symbol, side, price, qty, mid_before, mid_after_1s, fee_bps, ts_ms
        qidx: Optional quote index from _index_quotes(quotes), mapping symbol to list of quotes
    
    Returns:
        Dictionary mapping symbol to edge components:
        {
          "BTCUSDT": {
            "gross_bps": float,
            "fees_eff_bps": float,
            "adverse_bps": float,
            "slippage_bps": float,
            "inventory_bps": float,
            "net_bps": float (= gross + fees + slippage + inventory),
            "fills": float,
            "turnover_usd": float
          }
        }
    """
    # Group trades by symbol
    by_symbol = {}
    
    for trade in trades:
        symbol = trade.get("symbol")
        if not symbol:
            continue
        
        if symbol not in by_symbol:
            by_symbol[symbol] = []
        by_symbol[symbol].append(trade)
    
    # Calculate components per symbol
    result = {}
    
    for symbol, symbol_trades in by_symbol.items():
        # Per-trade component lists
        gross_list = []
        fees_list = []
        adverse_list = []
        slippage_list = []
        inv_signed_list = []
        notional_list = []
        
        for trade in symbol_trades:
            side = trade.get("side", "B")
            price = trade.get("price", 0.0)
            qty = trade.get("qty", 0.0)
            mid_before = trade.get("mid_before", 0.0)
            mid_after_1s = trade.get("mid_after_1s", 0.0)
            fee_bps = trade.get("fee_bps", 0.0)
            ts_ms = trade.get("ts_ms", 0)
            
            # Side sign: +1 for BUY, -1 for SELL
            side_sign = 1.0 if side == "B" else -1.0
            
            # 1. Gross BPS: side_sign * ((price - mid_before) / mid_before) * 1e4
            if mid_before != 0:
                gross_bps = side_sign * ((price - mid_before) / mid_before) * 1e4
            else:
                gross_bps = 0.0
            gross_list.append(gross_bps)
            
            # 2. Fees (always negative cost): -abs(fee_bps)
            fees_eff_bps = -abs(fee_bps)
            fees_list.append(fees_eff_bps)
            
            # 3. Adverse BPS: side_sign * ((mid_after_1s - mid_before) / mid_before) * 1e4
            if mid_before != 0:
                adverse_bps = side_sign * ((mid_after_1s - mid_before) / mid_before) * 1e4
            else:
                adverse_bps = 0.0
            adverse_list.append(adverse_bps)
            
            # 4. Slippage BPS (using quotes from qidx)
            slip_bps = 0.0
            if qidx and symbol in qidx:
                # Find quote with matching ts_ms
                matching_quote = None
                for q in qidx[symbol]:
                    if q.get("ts_ms") == ts_ms:
                        matching_quote = q
                        break
                
                if matching_quote:
                    best_bid = matching_quote.get("best_bid", 0.0)
                    best_ask = matching_quote.get("best_ask", 0.0)
                    
                    if side == "B" and best_ask != 0:
                        # BUY: (price - best_ask) / best_ask * 1e4
                        slip_bps = (price - best_ask) / best_ask * 1e4
                    elif side == "S" and best_bid != 0:
                        # SELL: -1 * ((price - best_bid) / best_bid) * 1e4
                        slip_bps = -1.0 * ((price - best_bid) / best_bid) * 1e4
            
            slippage_list.append(slip_bps)
            
            # 5. Inventory tracking (signed qty and notional)
            inv_signed = qty if side == "B" else -qty
            inv_signed_list.append(inv_signed)
            notional_list.append(price * qty)
        
        # Calculate averages
        fills = len(symbol_trades)
        gross_avg = sum(gross_list) / fills if fills > 0 else 0.0
        fees_avg = sum(fees_list) / fills if fills > 0 else 0.0
        adverse_avg = sum(adverse_list) / fills if fills > 0 else 0.0
        slippage_avg = sum(slippage_list) / fills if fills > 0 else 0.0
        
        # 6. Inventory BPS: -abs(avg_inv_signed / avg_notional)
        avg_inv_signed = sum(inv_signed_list) / fills if fills > 0 else 0.0
        avg_notional = sum(notional_list) / fills if fills > 0 else 0.0
        
        if avg_notional != 0:
            inventory_bps = -abs(avg_inv_signed / avg_notional)
        else:
            inventory_bps = 0.0
        
        # 7. Net BPS = gross + fees + slippage + inventory (NO adverse!)
        net_bps = gross_avg + fees_avg + slippage_avg + inventory_bps
        
        # 8. Turnover USD
        turnover_usd = sum(notional_list)
        
        result[symbol] = {
            "gross_bps": gross_avg,
            "fees_eff_bps": fees_avg,
            "adverse_bps": adverse_avg,
            "slippage_bps": slippage_avg,
            "inventory_bps": inventory_bps,
            "net_bps": net_bps,
            "fills": float(fills),
            "turnover_usd": turnover_usd
        }
    
    return result
