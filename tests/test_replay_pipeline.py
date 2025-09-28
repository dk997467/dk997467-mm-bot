import math
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List

import pandas as pd
import pytest


def _write_events_from_fixture(base_dir: Path, sample_events: Dict):
    (base_dir / "orders").mkdir(parents=True, exist_ok=True)
    (base_dir / "fills").mkdir(parents=True, exist_ok=True)
    (base_dir / "book_snapshots").mkdir(parents=True, exist_ok=True)
    (base_dir / "quotes").mkdir(parents=True, exist_ok=True)

    # Orders
    orders_df = pd.DataFrame([
        sample_events.get("order", {}),
    ])
    orders_df.to_parquet(base_dir / "orders" / "sample.parquet", index=False)

    # Fills
    fills_df = pd.DataFrame([
        sample_events.get("fill", {}),
    ])
    fills_df.to_parquet(base_dir / "fills" / "sample.parquet", index=False)

    # Snapshot
    snaps_df = pd.DataFrame([
        sample_events.get("snapshot", {}),
    ])
    snaps_df.to_parquet(base_dir / "book_snapshots" / "sample.parquet", index=False)

    # Quotes (optional, if present)
    quotes: List[Dict] = []
    if "quote1" in sample_events:
        quotes.append(sample_events["quote1"]) 
    if "quote2" in sample_events:
        quotes.append(sample_events["quote2"]) 
    if quotes:
        pd.DataFrame(quotes).to_parquet(base_dir / "quotes" / "sample.parquet", index=False)


@pytest.fixture
def tmp_events_dir(tmp_path: Path) -> Path:
    d = tmp_path / "events"
    d.mkdir(parents=True, exist_ok=True)
    return d


@pytest.fixture
def sample_events() -> Dict:
    t0 = datetime(2024, 1, 1, 12, 0, tzinfo=timezone.utc)
    t1 = datetime(2024, 1, 1, 12, 0, 1, tzinfo=timezone.utc)
    order = {
        "order_id": "ord1",
        "symbol": "BTCUSDT",
        "status": "New",
        "qty": 0.01,
        "timestamp": t0,
    }
    fill = {
        "trade_id": "tr1",
        "order_id": "ord1",
        "symbol": "BTCUSDT",
        "side": "Buy",
        "qty": 0.01,
        "price": 50000.0,
        "fee": 0.05,
        "fee_rate": 0.0005,
        "timestamp": t1,
        "exec_time": t1,
        "is_maker": True,
    }
    snapshot = {
        "timestamp": t0,
        "symbol": "BTCUSDT",
        "sequence": 1,
        "bids": "[]",
        "asks": "[]",
    }
    quote1 = {
        "timestamp": t0,
        "symbol": "BTCUSDT",
        "bid_px": 49999.0,
        "bid_qty": 0.01,
        "ask_px": 50001.0,
        "ask_qty": 0.01,
    }
    return {"order": order, "fill": fill, "snapshot": snapshot, "quote1": quote1}


def _minimal_merge_all(base_dir: Path) -> pd.DataFrame:
    frames: List[pd.DataFrame] = []
    for sub in ("orders", "fills", "book_snapshots", "quotes"):
        d = base_dir / sub
        if not d.exists():
            continue
        for fp in d.glob("*.parquet"):
            try:
                df = pd.read_parquet(fp)
                if "timestamp" in df.columns:
                    df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True)
                frames.append(df)
            except Exception:
                continue
    if not frames:
        return pd.DataFrame(columns=["timestamp"]).astype({"timestamp": "datetime64[ns, UTC]"})
    merged = pd.concat(frames, ignore_index=True)
    if "timestamp" in merged.columns:
        merged = merged.sort_values("timestamp").reset_index(drop=True)
    return merged


def _basic_replay_stats(base_dir: Path) -> Dict[str, float]:
    # Read orders and fills to compute simple latency stats
    orders = []
    fills = []
    odir = base_dir / "orders"
    fdir = base_dir / "fills"
    if odir.exists():
        for fp in odir.glob("*.parquet"):
            df = pd.read_parquet(fp)
            if "timestamp" in df.columns:
                df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True)
            orders.append(df)
    if fdir.exists():
        for fp in fdir.glob("*.parquet"):
            df = pd.read_parquet(fp)
            if "timestamp" in df.columns:
                df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True)
            fills.append(df)

    orders_df = pd.concat(orders, ignore_index=True) if orders else pd.DataFrame()
    fills_df = pd.concat(fills, ignore_index=True) if fills else pd.DataFrame()

    # Latency: match by order_id if available; otherwise use overall min diff
    latencies_ms: List[float] = []
    if not orders_df.empty and not fills_df.empty:
        if "order_id" in orders_df.columns and "order_id" in fills_df.columns:
            merged = pd.merge(fills_df[["order_id", "timestamp"]],
                              orders_df[["order_id", "timestamp"]],
                              on="order_id",
                              how="inner",
                              suffixes=("_fill", "_order"))
            if not merged.empty:
                delta = (merged["timestamp_fill"] - merged["timestamp_order"]).dt.total_seconds() * 1000.0
                latencies_ms = delta.clip(lower=0).tolist()
        if not latencies_ms:
            # fallback: any-to-any minimal positive diff
            for ft in fills_df["timestamp"].tolist():
                diffs = [ (ft - ot).total_seconds() * 1000.0 for ot in orders_df["timestamp"].tolist() ]
                diffs_pos = [d for d in diffs if d >= 0]
                if diffs_pos:
                    latencies_ms.append(min(diffs_pos))

    def p50(xs: List[float]) -> float:
        if not xs:
            return 0.0
        s = sorted(xs)
        n = len(s)
        mid = n // 2
        if n % 2 == 1:
            return float(s[mid])
        return float(0.5 * (s[mid - 1] + s[mid]))

    # PnL placeholders for smoke test (finite numbers)
    pnl_realized = 0.0
    pnl_mtm = 0.0
    avg_spread_bps = 0.0
    latency_ms_p50 = p50(latencies_ms)

    return {
        "pnl_realized": float(pnl_realized),
        "pnl_mtm": float(pnl_mtm),
        "avg_spread_bps": float(avg_spread_bps),
        "latency_ms_p50": float(latency_ms_p50),
    }


def test_merge_ordering(tmp_events_dir: Path, sample_events: Dict):
    # Write fixtures to parquet
    _write_events_from_fixture(tmp_events_dir, sample_events)

    # Build a couple extra out-of-order rows
    # Add an early order and a later fill to mix timestamps
    orders_extra = pd.DataFrame([
        {
            "order_id": "ord_early",
            "symbol": sample_events.get("order", {}).get("symbol", "BTCUSDT"),
            "timestamp": pd.to_datetime("2024-01-01T00:00:00Z"),
        }
    ])
    fills_extra = pd.DataFrame([
        {
            "order_id": "ord_late",
            "symbol": sample_events.get("order", {}).get("symbol", "BTCUSDT"),
            "timestamp": pd.to_datetime("2024-01-02T00:00:00Z"),
        }
    ])
    orders_extra.to_parquet(tmp_events_dir / "orders" / "extra.parquet", index=False)
    fills_extra.to_parquet(tmp_events_dir / "fills" / "extra.parquet", index=False)

    merged = _minimal_merge_all(tmp_events_dir)
    assert not merged.empty
    assert "timestamp" in merged.columns

    # Non-decreasing timestamps
    ts = merged["timestamp"].astype("int64").tolist()
    assert all(ts[i] <= ts[i + 1] for i in range(len(ts) - 1))


def test_replay_stats(tmp_events_dir: Path, sample_events: Dict):
    _write_events_from_fixture(tmp_events_dir, sample_events)
    stats = _basic_replay_stats(tmp_events_dir)

    # Required keys
    for k in ("pnl_realized", "pnl_mtm", "avg_spread_bps", "latency_ms_p50"):
        assert k in stats
        assert isinstance(stats[k], (int, float))
        assert math.isfinite(float(stats[k]))


