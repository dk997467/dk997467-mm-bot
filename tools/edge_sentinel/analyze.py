#!/usr/bin/env python3
"""Edge sentinel analysis functions."""
from __future__ import annotations
import json
from pathlib import Path
from typing import Dict, Any
from collections import defaultdict


def analyze(trades_path: str, quotes_path: str, bucket_ms: int) -> Dict[str, Any]:
    """
    Analyze trades and quotes by bucketing and ranking symbols.
    
    Args:
        trades_path: Path to trades JSONL file
        quotes_path: Path to quotes JSONL file (currently unused)
        bucket_ms: Bucket size in milliseconds
    
    Returns:
        Dictionary with buckets and ranking:
        {
          "buckets": [{"bucket": int, "symbols": [{"symbol": str, "edge_bps": float, "latency_ms": float}]}],
          "ranking": [{"symbol": str, "score": float}]
        }
    """
    # Load trades
    trades = []
    trades_file = Path(trades_path)
    if trades_file.exists():
        with open(trades_file, 'r', encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if line:
                    try:
                        trades.append(json.loads(line))
                    except json.JSONDecodeError:
                        continue
    
    if not trades:
        return {
            "buckets": [],
            "ranking": []
        }
    
    # Bucket trades by ts_ms // bucket_ms
    buckets_dict = defaultdict(lambda: defaultdict(list))
    symbol_scores = defaultdict(float)
    
    for trade in trades:
        ts_ms = trade.get("ts_ms", 0)
        bucket_id = ts_ms // bucket_ms if bucket_ms > 0 else 0
        symbol = trade.get("symbol", "UNKNOWN")
        
        # Extract metrics
        edge_bps = trade.get("edge_bps", 0.0)
        latency_ms = trade.get("latency_ms", trade.get("p95_latency_ms", 0.0))
        
        buckets_dict[bucket_id][symbol].append({
            "edge_bps": edge_bps,
            "latency_ms": latency_ms
        })
        
        # Accumulate score (simple: sum of edge_bps)
        symbol_scores[symbol] += edge_bps
    
    # Build bucket output
    buckets = []
    for bucket_id in sorted(buckets_dict.keys()):
        symbol_data = []
        for symbol, metrics_list in buckets_dict[bucket_id].items():
            # Average metrics for this bucket
            avg_edge = sum(m["edge_bps"] for m in metrics_list) / len(metrics_list)
            avg_latency = sum(m["latency_ms"] for m in metrics_list) / len(metrics_list)
            
            symbol_data.append({
                "symbol": symbol,
                "edge_bps": round(avg_edge, 2),
                "latency_ms": round(avg_latency, 2)
            })
        
        buckets.append({
            "bucket": bucket_id,
            "symbols": symbol_data
        })
    
    # Build ranking (sorted by score desc)
    ranking = [
        {"symbol": symbol, "score": round(score, 2)}
        for symbol, score in sorted(symbol_scores.items(), key=lambda x: x[1], reverse=True)
    ]
    
    return {
        "buckets": buckets,
        "ranking": ranking
    }
