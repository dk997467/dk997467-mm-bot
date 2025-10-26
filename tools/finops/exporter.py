#!/usr/bin/env python3
"""
FinOps Exporter: Load artifacts and export to CSV for external analysis.

Functions:
    load_artifacts(base_dir: str) -> dict
    export_pnl_csv(data: dict, out_path: str) -> None
    export_fees_csv(data: dict, out_path: str) -> None
    export_turnover_csv(data: dict, out_path: str) -> None
    export_latency_csv(data: dict, out_path: str) -> None
    export_edge_csv(data: dict, out_path: str) -> None
"""
from __future__ import annotations
import csv
import json
from pathlib import Path
from typing import Any, Dict, List


def load_artifacts(base_dir: str) -> Dict[str, Any]:
    """
    Load artifacts from base directory.
    
    Args:
        base_dir: Base directory containing artifacts
    
    Returns:
        Dictionary with loaded data:
        {
            "pnl": [{...}],
            "fees": [{...}],
            "turnover": [{...}],
            "latency": [{...}],
            "edge": [{...}]
        }
    """
    base_path = Path(base_dir)
    
    result = {
        "pnl": [],
        "fees": [],
        "turnover": [],
        "latency": [],
        "edge": []
    }
    
    if not base_path.exists():
        return result
    
    # Try to load from common artifact files
    for artifact_type in result.keys():
        artifact_file = base_path / f"{artifact_type.upper()}.json"
        if artifact_file.exists():
            try:
                with open(artifact_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    if isinstance(data, list):
                        result[artifact_type] = data
                    elif isinstance(data, dict) and "data" in data:
                        result[artifact_type] = data["data"]
            except Exception:
                pass
    
    return result


def export_pnl_csv(data: Dict[str, Any], out_path: str) -> None:
    """
    Export PnL data to CSV.
    
    Expected columns: timestamp, symbol, pnl, realized_pnl, unrealized_pnl
    """
    rows = data.get("pnl", [])
    
    with open(out_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["timestamp", "symbol", "pnl", "realized_pnl", "unrealized_pnl"])
        
        for row in rows:
            writer.writerow([
                row.get("timestamp", ""),
                row.get("symbol", ""),
                row.get("pnl", 0.0),
                row.get("realized_pnl", 0.0),
                row.get("unrealized_pnl", 0.0)
            ])


def export_fees_csv(data: Dict[str, Any], out_path: str) -> None:
    """
    Export fees data to CSV.
    
    Expected columns: timestamp, symbol, maker_fee, taker_fee, total_fee
    """
    rows = data.get("fees", [])
    
    with open(out_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["timestamp", "symbol", "maker_fee", "taker_fee", "total_fee"])
        
        for row in rows:
            writer.writerow([
                row.get("timestamp", ""),
                row.get("symbol", ""),
                row.get("maker_fee", 0.0),
                row.get("taker_fee", 0.0),
                row.get("total_fee", 0.0)
            ])


def export_turnover_csv(data: Dict[str, Any], out_path: str) -> None:
    """
    Export turnover data to CSV.
    
    Expected columns: timestamp, symbol, volume, turnover
    """
    rows = data.get("turnover", [])
    
    with open(out_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["timestamp", "symbol", "volume", "turnover"])
        
        for row in rows:
            writer.writerow([
                row.get("timestamp", ""),
                row.get("symbol", ""),
                row.get("volume", 0.0),
                row.get("turnover", 0.0)
            ])


def export_latency_csv(data: Dict[str, Any], out_path: str) -> None:
    """
    Export latency data to CSV.
    
    Expected columns: timestamp, symbol, p50_ms, p95_ms, p99_ms
    """
    rows = data.get("latency", [])
    
    with open(out_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["timestamp", "symbol", "p50_ms", "p95_ms", "p99_ms"])
        
        for row in rows:
            writer.writerow([
                row.get("timestamp", ""),
                row.get("symbol", ""),
                row.get("p50_ms", 0.0),
                row.get("p95_ms", 0.0),
                row.get("p99_ms", 0.0)
            ])


def export_edge_csv(data: Dict[str, Any], out_path: str) -> None:
    """
    Export edge data to CSV.
    
    Expected columns: timestamp, symbol, edge_bps, spread_bps
    """
    rows = data.get("edge", [])
    
    with open(out_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["timestamp", "symbol", "edge_bps", "spread_bps"])
        
        for row in rows:
            writer.writerow([
                row.get("timestamp", ""),
                row.get("symbol", ""),
                row.get("edge_bps", 0.0),
                row.get("spread_bps", 0.0)
            ])


if __name__ == "__main__":
    # Smoke test
    import tempfile
    
    test_data = {
        "pnl": [{"timestamp": "2025-01-01", "symbol": "BTCUSDT", "pnl": 100.5}],
        "fees": [],
        "turnover": [],
        "latency": [],
        "edge": []
    }
    
    with tempfile.TemporaryDirectory() as tmpdir:
        out_path = Path(tmpdir) / "test_pnl.csv"
        export_pnl_csv(test_data, str(out_path))
        
        assert out_path.exists()
        content = out_path.read_text()
        assert "timestamp" in content
        assert "BTCUSDT" in content
        
        print("[OK] FinOps exporter smoke test passed")
