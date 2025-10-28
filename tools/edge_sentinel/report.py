#!/usr/bin/env python3
"""Edge Sentinel Report: Monitors edge degradation and provides actionable advice."""
import json
import sys
import os
import argparse
from pathlib import Path
from datetime import datetime, timezone
from typing import List, Dict, Any


def _bucketize(trades: List[Dict], quotes: List[Dict], bucket_ms: int = 60000) -> List[Dict[str, Any]]:
    """
    Bucketize trades and quotes into time windows.
    
    Args:
        trades: List of trade dicts with 'ts', 'symbol', 'net_bps'
        quotes: List of quote dicts with 'ts', 'symbol', 'spread_bps'
        bucket_ms: Bucket size in milliseconds
    
    Returns:
        List of bucket dicts with aggregated metrics
    """
    if not trades and not quotes:
        return []
    
    # Group by bucket_ts
    buckets_map = {}
    
    for trade in trades:
        ts = trade.get('ts', 0)
        bucket_ts = (ts // bucket_ms) * bucket_ms
        symbol = trade.get('symbol', 'unknown')
        
        key = (bucket_ts, symbol)
        if key not in buckets_map:
            buckets_map[key] = {
                'bucket_ts': bucket_ts,
                'symbol': symbol,
                'net_bps_sum': 0.0,
                'trade_count': 0
            }
        
        buckets_map[key]['net_bps_sum'] += trade.get('net_bps', 0)
        buckets_map[key]['trade_count'] += 1
    
    # Average net_bps per bucket
    buckets = []
    for (bucket_ts, symbol), data in sorted(buckets_map.items()):
        avg_net_bps = data['net_bps_sum'] / data['trade_count'] if data['trade_count'] > 0 else 0.0
        buckets.append({
            'bucket_ts': bucket_ts,
            'symbol': symbol,
            'net_bps': avg_net_bps,
            'trade_count': data['trade_count']
        })
    
    return buckets


def _rank_symbols(buckets: List[Dict]) -> List[Dict[str, Any]]:
    """
    Rank symbols by total net_bps drop (lowest first).
    
    Args:
        buckets: List of bucket dicts with 'symbol', 'net_bps'
    
    Returns:
        List of symbol dicts with 'symbol', 'total_net_bps', sorted by total_net_bps asc
    """
    if not buckets:
        return []
    
    # Group by symbol
    symbols_map = {}
    for bucket in buckets:
        symbol = bucket.get('symbol', 'unknown')
        net_bps = bucket.get('net_bps', 0.0)
        
        if symbol not in symbols_map:
            symbols_map[symbol] = {'symbol': symbol, 'total_net_bps': 0.0, 'bucket_count': 0}
        
        symbols_map[symbol]['total_net_bps'] += net_bps
        symbols_map[symbol]['bucket_count'] += 1
    
    # Sort by total_net_bps asc (worst first), then by symbol name for stability
    ranked = sorted(symbols_map.values(), key=lambda x: (x['total_net_bps'], x['symbol']))
    
    return ranked


def _build_report(buckets: List[Dict], ranked_symbols: List[Dict], utc_iso: str) -> Dict[str, Any]:
    """
    Build final report structure.
    
    Args:
        buckets: List of bucket dicts
        ranked_symbols: List of ranked symbol dicts
        utc_iso: UTC timestamp in ISO format
    
    Returns:
        Report dict with 'summary', 'top', 'advice', 'runtime'
    """
    # Determine advice
    advice = []
    if not ranked_symbols:
        advice = ["HOLD"]
    elif ranked_symbols[0]['total_net_bps'] < -5.0:
        advice = ["BLOCK", "Severe edge degradation detected"]
    elif ranked_symbols[0]['total_net_bps'] < -2.0:
        advice = ["WARN", "Edge degradation detected"]
    else:
        advice = ["READY"]
    
    # Top contributors by component (for now, just symbols)
    top_buckets = sorted(buckets, key=lambda x: x.get('net_bps', 0))[:5]
    top_symbols = ranked_symbols[:5]
    
    report = {
        "advice": advice,
        "runtime": {
            "utc": utc_iso,
            "version": "0.1.0"
        },
        "summary": {
            "buckets": len(buckets),
            "symbols": {s['symbol']: s['total_net_bps'] for s in ranked_symbols}
        },
        "top": {
            "contributors_by_component": {
                "edge": [s['symbol'] for s in top_symbols]
            },
            "top_buckets_by_net_drop": [
                {
                    "bucket_ts": b['bucket_ts'],
                    "net_bps": b['net_bps'],
                    "symbol": b['symbol']
                } for b in top_buckets
            ],
            "top_symbols_by_net_drop": [
                {
                    "symbol": s['symbol'],
                    "total_net_bps": s['total_net_bps']
                } for s in top_symbols
            ]
        }
    }
    
    return report


def _render_md(report: Dict[str, Any]) -> str:
    """
    Render report as Markdown (deterministic, stable order).
    
    Args:
        report: Report dict
    
    Returns:
        Markdown string (with trailing newline)
    """
    lines = []
    lines.append("# Edge Sentinel Report\n")
    lines.append(f"**Advice:** {', '.join(report.get('advice', ['N/A']))}\n")
    lines.append(f"**Buckets:** {report['summary']['buckets']}\n")
    lines.append("\n## Top Symbols by Net Drop\n")
    
    top_symbols = report['top']['top_symbols_by_net_drop']
    if top_symbols:
        lines.append("| Symbol | Total Net BPS |\n")
        lines.append("|--------|---------------|\n")
        for s in top_symbols:
            lines.append(f"| {s['symbol']} | {s['total_net_bps']:.2f} |\n")
    else:
        lines.append("No data available.\n")
    
    return "".join(lines)


def main(argv=None):
    parser = argparse.ArgumentParser(description="Edge Sentinel Report Generator")
    parser.add_argument("--trades", help="Path to trades JSONL file")
    parser.add_argument("--quotes", help="Path to quotes JSONL file")
    parser.add_argument("--out-json", default="artifacts/EDGE_SENTINEL.json", help="Output JSON path")
    parser.add_argument("--out-md", default="artifacts/EDGE_SENTINEL.md", help="Output Markdown path")
    parser.add_argument("--bucket-ms", type=int, default=60000, help="Bucket size in milliseconds")
    parser.add_argument("--update-golden", action="store_true", help="Update golden file for tests")
    args = parser.parse_args(argv)
    
    # Load input data
    trades = []
    quotes = []
    
    if args.trades and Path(args.trades).exists():
        with open(args.trades, 'r', encoding='utf-8') as f:
            for line in f:
                if line.strip():
                    trades.append(json.loads(line))
    
    if args.quotes and Path(args.quotes).exists():
        with open(args.quotes, 'r', encoding='utf-8') as f:
            for line in f:
                if line.strip():
                    quotes.append(json.loads(line))
    
    # Bucketize and rank
    buckets = _bucketize(trades, quotes, args.bucket_ms)
    ranked_symbols = _rank_symbols(buckets)
    
    # Build report
    utc_iso = os.environ.get('MM_FREEZE_UTC_ISO', datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"))
    report = _build_report(buckets, ranked_symbols, utc_iso)
    
    # Write JSON output
    out_json = Path(args.out_json)
    out_json.parent.mkdir(parents=True, exist_ok=True)
    with open(out_json, 'w', encoding='utf-8', newline='') as f:
        json.dump(report, f, ensure_ascii=True, sort_keys=True, separators=(",", ":"))
        f.write('\n')
    
    # Write MD output
    out_md = Path(args.out_md)
    out_md.parent.mkdir(parents=True, exist_ok=True)
    md_content = _render_md(report)
    with open(out_md, 'w', encoding='utf-8', newline='') as f:
        f.write(md_content)
    
    # Update golden files if requested
    if args.update_golden:
        import shutil
        golden_dir = Path("tests/golden")
        golden_dir.mkdir(parents=True, exist_ok=True)
        shutil.copy(out_json, golden_dir / "EDGE_SENTINEL_case1.json")
        shutil.copy(out_md, golden_dir / "EDGE_SENTINEL_case1.md")
        print(f"[OK] Updated golden files: {golden_dir}/EDGE_SENTINEL_case1.{{json,md}}")
    
    return 0


if __name__ == "__main__":
    sys.exit(main())
