#!/usr/bin/env python3
"""
FinOps Reconcile: Aggregate and reconcile financial metrics.

Functions:
    reconcile(artifacts_json_path: str, exchange_dir: str) -> dict
    render_reconcile_md(summary: dict) -> str
"""
from __future__ import annotations
import json
import csv
from pathlib import Path
from typing import Dict, Any

# Epsilon for tiny delta comparison
EPS = 1e-6


def _to_float(x, default=0.0):
    """
    Safe conversion to float with dict support.
    
    Args:
        x: Value to convert (int, float, str, dict)
        default: Default value if conversion fails
    
    Returns:
        Float value or default
    """
    if isinstance(x, (int, float)):
        return float(x)
    if isinstance(x, str):
        try:
            return float(x)
        except ValueError:
            return default
    if isinstance(x, dict):
        # Popular nested variants
        for k in ("value", "avg", "mean", "bps", "usd", "pnl"):
            if k in x and isinstance(x[k], (int, float, str)):
                try:
                    return float(x[k])
                except ValueError:
                    pass
        # If dict has exactly one numeric value - take it
        vals = [v for v in x.values() if isinstance(v, (int, float))]
        if len(vals) == 1:
            return float(vals[0])
    return default


def reconcile(artifacts_json_path: str, exchange_dir: str) -> Dict[str, Any]:
    """
    Reconcile financial metrics from artifacts vs exchange reports.
    
    Args:
        artifacts_json_path: Path to metrics.json with internal tracking (per-symbol)
        exchange_dir: Directory containing exchange CSV reports (pnl.csv, fees.csv, turnover.csv)
    
    Returns:
        Summary dictionary with per-symbol and total deltas (absolute values):
        {
          "by_symbol": {
            "BTCUSDT": {
              "pnl_delta_abs": float,
              "fees_bps_delta_abs": float,
              "turnover_usd_delta_abs": float
            }
          },
          "totals": {
            "pnl_delta_abs": float,
            "fees_bps_delta_abs": float,
            "turnover_usd_delta_abs": float
          },
          "status": "OK" | "WARN" | "FAIL"
        }
    """
    # Load internal metrics (per-symbol)
    metrics_path = Path(artifacts_json_path)
    if metrics_path.exists():
        with open(metrics_path, 'r', encoding='utf-8') as f:
            internal = json.load(f)
    else:
        internal = {}
    
    # Load exchange reports (per-symbol)
    exchange_path = Path(exchange_dir)
    exchange_by_symbol = {}
    
    # Read PnL from exchange
    pnl_csv = exchange_path / "pnl.csv"
    if pnl_csv.exists():
        with open(pnl_csv, 'r', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            for row in reader:
                symbol = row.get("symbol", "UNKNOWN")
                if symbol not in exchange_by_symbol:
                    exchange_by_symbol[symbol] = {"pnl": 0.0, "fees_bps": 0.0, "turnover_usd": 0.0}
                exchange_by_symbol[symbol]["pnl"] += _to_float(row.get("pnl", 0.0))
    
    # Read fees from exchange
    fees_csv = exchange_path / "fees.csv"
    if fees_csv.exists():
        with open(fees_csv, 'r', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            for row in reader:
                symbol = row.get("symbol", "UNKNOWN")
                if symbol not in exchange_by_symbol:
                    exchange_by_symbol[symbol] = {"pnl": 0.0, "fees_bps": 0.0, "turnover_usd": 0.0}
                exchange_by_symbol[symbol]["fees_bps"] += _to_float(row.get("fees_bps", 0.0))
    
    # Read turnover from exchange
    turnover_csv = exchange_path / "turnover.csv"
    if turnover_csv.exists():
        with open(turnover_csv, 'r', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            for row in reader:
                symbol = row.get("symbol", "UNKNOWN")
                if symbol not in exchange_by_symbol:
                    exchange_by_symbol[symbol] = {"pnl": 0.0, "fees_bps": 0.0, "turnover_usd": 0.0}
                exchange_by_symbol[symbol]["turnover_usd"] += _to_float(row.get("turnover_usd", 0.0))
    
    # Calculate deltas per symbol (absolute values)
    # Filter to only real trading symbols (exclude metadata keys like "runtime", "TOTAL", "fees", etc.)
    by_symbol = {}
    all_symbols = set(internal.keys()) | set(exchange_by_symbol.keys())
    
    # Filter: keep only uppercase symbols ending with common quote currencies
    real_symbols = {
        s for s in all_symbols
        if s.isupper() and any(s.endswith(quote) for quote in ["USDT", "USD", "BTC", "ETH"])
    }
    
    for symbol in sorted(real_symbols):  # Sort for determinism
        int_data = internal.get(symbol, {})
        exc_data = exchange_by_symbol.get(symbol, {"pnl": 0.0, "fees_bps": 0.0, "turnover_usd": 0.0})
        
        # Calculate deltas using _to_float for safe conversion
        pnl_delta = _to_float(int_data.get("pnl", 0.0)) - _to_float(exc_data.get("pnl", 0.0))
        fees_delta = _to_float(int_data.get("fees_bps", 0.0)) - _to_float(exc_data.get("fees_bps", 0.0))
        turn_delta = _to_float(int_data.get("turnover_usd", 0.0)) - _to_float(exc_data.get("turnover_usd", 0.0))
        
        # Store signed deltas (rounded, with EPS threshold)
        by_symbol[symbol] = {
            "pnl_delta": round(pnl_delta, 12) if abs(pnl_delta) > EPS else 0.0,
            "fees_bps_delta": round(fees_delta, 12) if abs(fees_delta) > EPS else 0.0,
            "turnover_delta_usd": round(turn_delta, 12) if abs(turn_delta) > EPS else 0.0,
        }
    
    # Calculate totals (sum of signed deltas)
    totals = {
        "pnl_delta": sum(v["pnl_delta"] for v in by_symbol.values()),
        "fees_bps_delta": sum(v["fees_bps_delta"] for v in by_symbol.values()),
        "turnover_delta_usd": sum(v["turnover_delta_usd"] for v in by_symbol.values()),
    }
    
    # Add runtime (deterministic if MM_FREEZE_UTC is set)
    import os
    from datetime import datetime, timezone
    
    if os.environ.get('MM_FREEZE_UTC') == '1':
        utc_iso = "1970-01-01T00:00:00Z"
    else:
        utc_iso = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    
    # Match golden format exactly: by_symbol, runtime, totals (alphabetical order)
    return {
        "by_symbol": by_symbol,
        "runtime": {
            "utc": utc_iso,
            "version": "0.1.0"
        },
        "totals": totals
    }


def write_json_atomic(path: str, data: Dict[str, Any]) -> None:
    """
    Write JSON atomically with sorted keys and trailing newline.
    
    Args:
        path: Output file path
        data: Data to serialize
    """
    import tempfile
    import os
    
    # Write to temp file first
    path_obj = Path(path)
    path_obj.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(dir=path_obj.parent, suffix=".tmp")
    try:
        with os.fdopen(fd, 'w', encoding='ascii', newline='') as f:
            json.dump(data, f, sort_keys=True, ensure_ascii=True, separators=(",", ":"))
            f.write('\n')  # Trailing newline (Unix-style)
        
        # Atomic rename
        os.replace(tmp_path, path)
    except Exception:
        # Clean up temp file on error
        try:
            os.unlink(tmp_path)
        except Exception:
            pass
        raise


def render_reconcile_md(summary: Dict[str, Any]) -> str:
    """
    Render reconciliation summary as Markdown table.
    
    Args:
        summary: Summary dictionary from reconcile() with by_symbol and totals
    
    Returns:
        Markdown formatted string with trailing newline
    """
    lines = [
        "Reconcile Report",
        "",
        "| symbol | pnl_delta | fees_bps_delta | turnover_delta_usd |",
        "|--------|-----------|----------------|--------------------|"
    ]
    
    # Sort symbols for determinism
    by_symbol = summary.get("by_symbol", {})
    for symbol in sorted(by_symbol.keys()):
        delta_info = by_symbol[symbol]
        pnl = delta_info.get('pnl_delta', 0.0)
        fees = delta_info.get('fees_bps_delta', 0.0)
        turn = delta_info.get('turnover_delta_usd', 0.0)
        lines.append(f"| {symbol} | {pnl:.6f} | {fees:.6f} | {turn:.6f} |")
    
    # Totals row
    totals = summary.get("totals", {})
    pnl_total = totals.get('pnl_delta', 0.0)
    fees_total = totals.get('fees_bps_delta', 0.0)
    turn_total = totals.get('turnover_delta_usd', 0.0)
    lines.append(f"| TOTAL | {pnl_total:.6f} | {fees_total:.6f} | {turn_total:.6f} |")
    
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
