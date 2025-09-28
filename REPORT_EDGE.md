Edge Audit Report

Components (bps):
- gross_bps: average signed (fill_price - mid_before)/mid_before*1e4
- fees_eff_bps: effective fees bps (from trade.fee_bps if present; else 0.0)
- adverse_bps: average signed (mid_after_1s - mid_before)/mid_before*1e4
- slippage_bps: average signed (fill_price - quote_at_ts(side))/quote_at_ts*1e4; quote is closest<=ts_ms
- inventory_bps: proxy penalty 1.0bps * avg(|inventory|)/avg(notional)
- net_bps: gross - fees - adverse - slippage - inventory

Structure:
{
  "symbols": {"BTCUSDT": {"gross_bps":..., ...}},
  "total": {...},
  "runtime": {"utc":"...","version":"..."}
}

Serialization:
- ASCII, LF, deterministic JSON (ensure_ascii, sort_keys, separators=(",", ":"), trailing "\n").

