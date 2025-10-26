#!/usr/bin/env python3
"""Edge sentinel analysis functions."""
from __future__ import annotations
from typing import List, Dict, Any


def analyze(rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    """
    Analyze edge/sentinel rows.
    
    Args:
        rows: List of dicts with edge/latency metrics
    
    Returns:
        Dictionary with analysis results
    """
    if not rows:
        return {
            "count": 0,
            "edge_avg": 0.0,
            "latency_avg": 0.0,
            "symbols": []
        }
    
    edge_sum = 0.0
    latency_sum = 0.0
    symbols = set()
    
    for row in rows:
        if "edge" in row or "edge_bps" in row:
            edge_sum += row.get("edge", row.get("edge_bps", 0.0))
        
        if "latency" in row or "p95_latency_ms" in row:
            latency_sum += row.get("latency", row.get("p95_latency_ms", 0.0))
        
        if "symbol" in row:
            symbols.add(row["symbol"])
    
    count = len(rows)
    
    return {
        "count": count,
        "edge_avg": edge_sum / count if count > 0 else 0.0,
        "latency_avg": latency_sum / count if count > 0 else 0.0,
        "symbols": sorted(list(symbols))
    }
