"""
Backtest scorer: per-symbol and total metrics.

Deterministic formatting left to CLI writer; this module only computes floats.
"""

from typing import Dict, Any


def aggregate_scores(per_symbol: Dict[str, Dict[str, float]]) -> Dict[str, float]:
    if not per_symbol:
        return {
            "gross_bps": 0.0,
            "fees_bps": 0.0,
            "net_bps": 0.0,
            "taker_share_pct": 0.0,
            "order_age_p95_ms": 0.0,
        }
    syms = sorted(per_symbol.keys())
    n = float(len(syms))
    gross = sum(float(per_symbol[s]["gross_bps"]) for s in syms) / n
    fees = sum(float(per_symbol[s]["fees_bps"]) for s in syms) / n
    taker = sum(float(per_symbol[s]["taker_share_pct"]) for s in syms) / n
    p95 = sum(float(per_symbol[s]["order_age_p95_ms"]) for s in syms) / n
    net = gross - fees
    return {
        "gross_bps": float(f"{gross:.12f}"),
        "fees_bps": float(f"{fees:.12f}"),
        "net_bps": float(f"{net:.12f}"),
        "taker_share_pct": float(f"{taker:.12f}"),
        "order_age_p95_ms": float(f"{p95:.12f}"),
    }



