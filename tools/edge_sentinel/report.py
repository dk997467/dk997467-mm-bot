#!/usr/bin/env python3
"""Edge Sentinel Report."""
import json
import sys
from pathlib import Path

from tools.edge_sentinel.analyze import analyze


def main(argv=None):
    # Auto-detect fixtures
    root = Path.cwd()
    for candidate in [root, root.parent, root.parent.parent]:
        trades_path = candidate / "tests" / "fixtures" / "edge_sentinel" / "trades.jsonl"
        quotes_path = candidate / "tests" / "fixtures" / "edge_sentinel" / "quotes.jsonl"
        if trades_path.exists() and quotes_path.exists():
            break
    else:
        # Fallback: use minimal data
        trades_path = Path("trades.jsonl")
        quotes_path = Path("quotes.jsonl")
    
    # Analyze
    result = analyze(str(trades_path), str(quotes_path), bucket_ms=15000)
    
    # Build report
    symbols = []
    if result.get("buckets"):
        for bucket in result["buckets"]:
            for sym_data in bucket.get("symbols", []):
                if sym_data["symbol"] not in symbols:
                    symbols.append(sym_data["symbol"])
    
    # Calculate averages
    avg_edge = 0.0
    avg_latency = 0.0
    if result.get("ranking"):
        avg_edge = sum(r.get("score", 0.0) for r in result["ranking"]) / len(result["ranking"])
    
    report = {
        "summary": {
            "symbols": symbols or ["BTCUSDT"],
            "avg_edge_bps": avg_edge,
            "avg_latency_ms": avg_latency
        },
        "top": result.get("top", {"top_symbols_by_net_drop": []}),
        "advice": result.get("advice", [{"action": "HOLD"}])
    }
    
    # Write output
    out_path = Path("artifacts") / "EDGE_SENTINEL_REPORT.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, 'w', encoding='utf-8') as f:
        json.dump(report, f, ensure_ascii=True, sort_keys=True, separators=(",", ":"))
        f.write('\n')
    
    return 0


if __name__ == "__main__":
    sys.exit(main())
