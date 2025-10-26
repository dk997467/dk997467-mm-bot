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


def _agg_symbols(rows: List[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    """
    Aggregate rows by symbol.
    
    Args:
        rows: List of dicts with 'symbol' and numeric fields
    
    Returns:
        Dictionary mapping symbol to aggregated stats
    """
    agg = {}
    
    for row in rows:
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
        
        # Try to aggregate numeric value (look for common field names)
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
