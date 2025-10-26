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


def _agg_symbols(trades: List[Dict[str, Any]], qidx: Dict[str, List[Dict[str, Any]]] | None = None) -> Dict[str, Dict[str, Any]]:
    """
    Aggregate trades by symbol, optionally using quote index.
    
    Args:
        trades: List of trade dicts with 'symbol' and numeric fields
        qidx: Optional quote index (symbol -> list of quotes), currently unused
    
    Returns:
        Dictionary mapping symbol to aggregated stats
    """
    agg = {}
    
    for row in trades:
        symbol = row.get("symbol")
        if not symbol:
            continue
        
        if symbol not in agg:
            agg[symbol] = {
                "count": 0,
                "sum": 0.0,
                "values": []
            }
        
        agg[symbol]["count"] += 1
        
        # Try to calculate net edge if trade fields available
        if all(k in row for k in ["mid_before", "mid_after_1s", "fee_bps"]):
            mid_before = row.get("mid_before", 0.0)
            mid_after = row.get("mid_after_1s", 0.0)
            fee_bps = row.get("fee_bps", 0.0)
            
            if mid_before != 0:
                # net_edge_bps ~ ((mid_after - mid_before) / mid_before) * 10000 - fee_bps
                price_move_bps = ((mid_after - mid_before) / mid_before) * 10000
                net_edge = price_move_bps - fee_bps
                agg[symbol]["sum"] += net_edge
                agg[symbol]["values"].append(net_edge)
                continue
        
        # Fallback: Try to aggregate numeric value (look for common field names)
        for key in ["value", "edge", "spread", "price", "quantity"]:
            if key in row and _finite(row[key]):
                val = float(row[key])
                agg[symbol]["sum"] += val
                agg[symbol]["values"].append(val)
                break
    
    # Calculate averages
    for symbol, stats in agg.items():
        if stats["count"] > 0 and stats["sum"] != 0:
            stats["avg"] = stats["sum"] / stats["count"]
        else:
            stats["avg"] = 0.0
    
    return agg
