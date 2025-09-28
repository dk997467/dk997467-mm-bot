"""
Walk-forward backtest over ticks by indices (train/test window sizes).
Deterministic JSON-friendly aggregates.
"""

from typing import Dict, Any, List

from .loader import iter_ticks
from .simulator import run_sim


def _slice_ticks(ticks: List[Dict[str, Any]], start: int, end: int) -> List[Dict[str, Any]]:
    return ticks[start:end]


def run_walkforward(path: str, mode: str, train: int, test: int, params: Dict[str, Any]) -> Dict[str, Any]:
    all_ticks = list(iter_ticks(path))
    if train <= 0 or test <= 0:
        return {"windows": [], "mean": {}, "median": {}}
    windows: List[Dict[str, Any]] = []
    i = 0
    while i + train + test <= len(all_ticks):
        train_slice = _slice_ticks(all_ticks, i, i + train)
        test_slice = _slice_ticks(all_ticks, i + train, i + train + test)
        # params could be tuned by train_slice; for now we just run test_slice with params as-is
        agg = run_sim(iter(test_slice), mode, params)
        windows.append({
            "i": i,
            "train": len(train_slice),
            "test": len(test_slice),
            "fills_total": agg["fills_total"],
            "net_bps": agg["net_bps"],
            "taker_share_pct": agg["taker_share_pct"],
            "order_age_p95_ms": agg["order_age_p95_ms"],
            "fees_bps": agg["fees_bps"],
            "turnover_usd": agg["turnover_usd"],
        })
        i += test

    def _mean(key: str) -> float:
        if not windows:
            return 0.0
        return float(f"{(sum(float(w[key]) for w in windows) / float(len(windows))):.6f}")

    def _median(key: str) -> float:
        if not windows:
            return 0.0
        vs = sorted(float(w[key]) for w in windows)
        m = len(vs)
        if m % 2 == 1:
            return float(f"{vs[m//2]:.6f}")
        return float(f"{((vs[m//2-1] + vs[m//2]) / 2.0):.6f}")

    summary_mean = {
        "fills_total": int(round(sum(int(w["fills_total"]) for w in windows) / float(len(windows))) if windows else 0),
        "net_bps": _mean("net_bps"),
        "taker_share_pct": _mean("taker_share_pct"),
        "order_age_p95_ms": _mean("order_age_p95_ms"),
        "fees_bps": _mean("fees_bps"),
        "turnover_usd": _mean("turnover_usd"),
    }
    summary_median = {
        "fills_total": int(sorted(int(w["fills_total"]) for w in windows)[len(windows)//2]) if windows else 0,
        "net_bps": _median("net_bps"),
        "taker_share_pct": _median("taker_share_pct"),
        "order_age_p95_ms": _median("order_age_p95_ms"),
        "fees_bps": _median("fees_bps"),
        "turnover_usd": _median("turnover_usd"),
    }

    return {"windows": windows, "mean": summary_mean, "median": summary_median}



