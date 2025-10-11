POSTMORTEM (DAY) 1970-01-01

Outcome: FAIL

Timeline:
- Drift guard stop: reason=DRIFT_EDGE
- Regression guard stop: reason=EDGE_REG
- Daily report verdict=OK
- Sentinel: Top symbols by net drop: BTCUSDT,ETHUSDT
- Sentinel: Top buckets by net drop: 1970-01-01T00:00Z

| net_bps | order_age_p95_ms | taker_share_pct | fill_rate |
|---------|-------------------|-----------------|-----------|
| 0.000000 | 0.000000 | 0.000000 | 0.000000 |

Action items:
- tune throttle: raise min_interval_ms
- increase vip tilt cap mildly
