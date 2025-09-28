SOAK Daily Report
=================

Fields:
- edge_net_bps: float
- order_age_p95_ms: float
- taker_share_pct: float
- fill_rate: float
- pos_skew_abs_p95: float
- caps_breach_count: int
- alerts: {critical:int, warning:int}
- verdict: OK|WARN|FAIL
- runtime: {utc, version}
- drift: {reason, ts}
- reg_guard: {reason, baseline}

Thresholds:
- OK if: edge_net_bps ≥ 2.5 AND order_age_p95_ms ≤ 350 AND taker_share_pct ≤ 15
- WARN if within ±10% band of any threshold; otherwise FAIL

Serialization:
- Deterministic JSON (ensure_ascii, sort_keys, separators), trailing "\n"
- Markdown ASCII table (%.6f), trailing "\n"

Usage:
```bash
python -m tools.soak.daily_report --out artifacts/REPORT_SOAK_$(date -u +%Y%m%d).json
```


