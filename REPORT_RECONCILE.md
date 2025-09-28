FinOps Reconcile Report Specification

Fields (JSON):
- by_symbol: per symbol deltas
  - fees_bps_delta: float
  - pnl_delta: float
  - turnover_delta_usd: float
- totals: aggregated deltas
  - fees_bps_delta: float
  - pnl_delta: float
  - turnover_delta_usd: float
- runtime:
  - utc: ISO8601 UTC timestamp from artifacts
  - version: version string from artifacts

Acceptable tolerance:
- Absolute |delta| <= 1e-8 is considered acceptable.

Serialization rules:
- ASCII only, LF line endings, deterministic JSON: ensure_ascii=True, sort_keys=True, separators=(",", ":"), trailing "\n".
- Markdown summary is ASCII with fixed table and LF, trailing "\n".


