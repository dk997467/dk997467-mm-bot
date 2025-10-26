#!/usr/bin/env python3
"""
FinOps Reconcile: Aggregate and reconcile financial metrics.

Functions:
    reconcile(base_dir: str) -> dict
    render_reconcile_md(summary: dict) -> str
"""
from __future__ import annotations
from pathlib import Path
from typing import Dict, Any

from tools.finops.exporter import load_artifacts


def reconcile(base_dir: str) -> Dict[str, Any]:
    """
    Reconcile financial metrics from artifacts.
    
    Args:
        base_dir: Base directory containing artifacts
    
    Returns:
        Summary dictionary with aggregated metrics
    """
    data = load_artifacts(base_dir)
    
    summary = {
        "pnl": {
            "total": 0.0,
            "realized": 0.0,
            "unrealized": 0.0,
            "count": len(data.get("pnl", []))
        },
        "fees": {
            "maker": 0.0,
            "taker": 0.0,
            "total": 0.0,
            "count": len(data.get("fees", []))
        },
        "turnover": {
            "volume": 0.0,
            "turnover": 0.0,
            "count": len(data.get("turnover", []))
        },
        "latency": {
            "p50_avg": 0.0,
            "p95_avg": 0.0,
            "p99_avg": 0.0,
            "count": len(data.get("latency", []))
        },
        "edge": {
            "edge_avg": 0.0,
            "spread_avg": 0.0,
            "count": len(data.get("edge", []))
        }
    }
    
    # Aggregate PnL
    for row in data.get("pnl", []):
        summary["pnl"]["total"] += row.get("pnl", 0.0)
        summary["pnl"]["realized"] += row.get("realized_pnl", 0.0)
        summary["pnl"]["unrealized"] += row.get("unrealized_pnl", 0.0)
    
    # Aggregate fees
    for row in data.get("fees", []):
        summary["fees"]["maker"] += row.get("maker_fee", 0.0)
        summary["fees"]["taker"] += row.get("taker_fee", 0.0)
        summary["fees"]["total"] += row.get("total_fee", 0.0)
    
    # Aggregate turnover
    for row in data.get("turnover", []):
        summary["turnover"]["volume"] += row.get("volume", 0.0)
        summary["turnover"]["turnover"] += row.get("turnover", 0.0)
    
    # Aggregate latency (averages)
    lat_count = summary["latency"]["count"]
    if lat_count > 0:
        for row in data.get("latency", []):
            summary["latency"]["p50_avg"] += row.get("p50_ms", 0.0)
            summary["latency"]["p95_avg"] += row.get("p95_ms", 0.0)
            summary["latency"]["p99_avg"] += row.get("p99_ms", 0.0)
        
        summary["latency"]["p50_avg"] /= lat_count
        summary["latency"]["p95_avg"] /= lat_count
        summary["latency"]["p99_avg"] /= lat_count
    
    # Aggregate edge (averages)
    edge_count = summary["edge"]["count"]
    if edge_count > 0:
        for row in data.get("edge", []):
            summary["edge"]["edge_avg"] += row.get("edge_bps", 0.0)
            summary["edge"]["spread_avg"] += row.get("spread_bps", 0.0)
        
        summary["edge"]["edge_avg"] /= edge_count
        summary["edge"]["spread_avg"] /= edge_count
    
    return summary


def render_reconcile_md(summary: Dict[str, Any]) -> str:
    """
    Render reconciliation summary as Markdown.
    
    Args:
        summary: Summary dictionary from reconcile()
    
    Returns:
        Markdown formatted string
    """
    lines = [
        "# FinOps Reconciliation Summary",
        "",
        "## PnL",
        "",
        f"- **Total PnL:** ${summary['pnl']['total']:.2f}",
        f"- **Realized PnL:** ${summary['pnl']['realized']:.2f}",
        f"- **Unrealized PnL:** ${summary['pnl']['unrealized']:.2f}",
        f"- **Count:** {summary['pnl']['count']}",
        "",
        "## Fees",
        "",
        f"- **Maker Fees:** ${summary['fees']['maker']:.2f}",
        f"- **Taker Fees:** ${summary['fees']['taker']:.2f}",
        f"- **Total Fees:** ${summary['fees']['total']:.2f}",
        f"- **Count:** {summary['fees']['count']}",
        "",
        "## Turnover",
        "",
        f"- **Volume:** {summary['turnover']['volume']:.2f}",
        f"- **Turnover:** ${summary['turnover']['turnover']:.2f}",
        f"- **Count:** {summary['turnover']['count']}",
        "",
        "## Latency",
        "",
        f"- **P50 Avg:** {summary['latency']['p50_avg']:.2f}ms",
        f"- **P95 Avg:** {summary['latency']['p95_avg']:.2f}ms",
        f"- **P99 Avg:** {summary['latency']['p99_avg']:.2f}ms",
        f"- **Count:** {summary['latency']['count']}",
        "",
        "## Edge",
        "",
        f"- **Edge Avg:** {summary['edge']['edge_avg']:.2f} bps",
        f"- **Spread Avg:** {summary['edge']['spread_avg']:.2f} bps",
        f"- **Count:** {summary['edge']['count']}",
        ""
    ]
    
    return "\n".join(lines)


if __name__ == "__main__":
    # Smoke test
    import tempfile
    import json
    
    with tempfile.TemporaryDirectory() as tmpdir:
        # Create test artifacts
        test_pnl = [{"pnl": 100.5, "realized_pnl": 50.0, "unrealized_pnl": 50.5}]
        Path(tmpdir, "PNL.json").write_text(json.dumps(test_pnl))
        
        summary = reconcile(tmpdir)
        assert summary["pnl"]["total"] == 100.5
        
        md = render_reconcile_md(summary)
        assert "# FinOps Reconciliation Summary" in md
        assert "$100.50" in md
        
        print("[OK] FinOps reconcile smoke test passed")
