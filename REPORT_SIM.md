# SIM Report format

JSON fields:
- fills_total: int
- net_bps: float
- taker_share_pct: float
- order_age_p95_ms: float
- fees_bps: float
- turnover_usd: float
- runtime.utc/version/mode

Acceptance thresholds:
- net_bps ≥ 2.5
- taker_share_pct ≤ 15
- order_age_p95_ms ≤ 350

MD report is a fixed table with values formatted as %.6f.
