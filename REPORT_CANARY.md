CANARY REPORT (ASCII-only)

sha: 
utc: 
rc_summary: 

fill_rate: 
order_age_p95_ms: 
net_bps: 
taker_share_pct: 
replaces_per_order: 
cancel_batch_events: 

skew_caps:
  pos_skew_breach_total_10m: 
  intraday_caps_breached: 

fees:
  tier_level_now: 
  tier_level_next: 
  distance_usd: 
  effective_fee_bps_now: 

verdict: GO | NO-GO

GO/NO-GO rubric
- net_bps >= 2.5
- order_age_p95_ms <= 350
- taker_share_pct <= 15

Artifacts checklist
- Attach artifacts/metrics.json
- Attach prom_snapshot.txt
- Attach recent logs (ASCII-only)


