POSTMORTEM (DAY) 1970-01-01

Outcome: FAIL

Timeline:
- Drift guard stop: reason=DRIFT_EDGE
- Regression guard stop: reason=EDGE_REG
- Daily report verdict=FAIL
- Sentinel: Top symbols by net drop: BTCUSDT
- Sentinel: Top buckets by net drop: 1970-01-01T00:10Z

| net_bps | order_age_p95_ms | taker_share_pct | fill_rate |
|---------|-------------------|-----------------|-----------|
| 2.400000 | 350.000000 | 13.000000 | 0.620000 |

Action items:
- tune throttle: raise min_interval_ms
- lower micro impact_cap_ratio


