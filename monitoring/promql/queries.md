Edge Breakdown
--------------
- gross_bps: `sum by (symbol) (edge_gross_bps[5m])`
- fees_eff_bps: `sum by (symbol) (edge_fees_eff_bps[5m])`
- adverse_bps: `sum by (symbol) (edge_adverse_bps[5m])`
- slippage_bps: `sum by (symbol) (edge_slippage_bps[5m])`
- inventory_bps: `sum by (symbol) (edge_inventory_bps[5m])`
- net_bps: `sum by (symbol) (edge_net_bps[5m])`

Latency & Queue
---------------
- order_age_p50_ms: `avg_over_time(order_age_p50_ms[5m])`
- order_age_p95_ms: `avg_over_time(order_age_p95_ms[5m])`
- order_age_p99_ms: `histogram_quantile(0.99, sum(rate(order_age_seconds_bucket[5m])) by (le,symbol)) * 1000`
- replace_rate_per_min: `avg_over_time(replace_rate_per_min[5m])`
- cancel_batch_events_total: `increase(cancel_batch_events_total[5m])`

Guards & Alerts
---------------
- pos_skew_abs_p95: `avg_over_time(pos_skew_abs_p95[5m])`
- caps breaches: `increase(intraday_caps_breach_total[5m])`
- EffectiveFeeJump: `increase(effective_fee_jump_alerts_total[5m])`
- DriftGuardStops: `increase(drift_guard_stops_total[5m])`
- RegGuardStops: `increase(reg_guard_stops_total[5m])`

Region Compare
--------------
- region_net_bps: `sum by (region) (region_net_bps[5m])`
- region_order_age_p95_ms: `avg by (region) (region_order_age_p95_ms[5m])`
- winner: `last_over_time(region_winner[5m])`

Recording Rules (suggested)
---------------------------
- `record: edge_net_bps:5m` expr: `sum by (symbol) (edge_net_bps[5m])`
- `record: order_age_p95_ms:5m` expr: `avg_over_time(order_age_p95_ms[5m])`


