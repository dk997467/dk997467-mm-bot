# Circuit Gate Runbook

## Triage
- Check alert details and recent transitions (`event=circuit_transition ...`).
- Verify error sources (exchange/network). Correlate with `HighErrorRate` and backoff.
- Temporarily raise `circuit_max_err_rate_ratio` by +10–20% if needed.
- If unstable, disable affected strategy or rollback recent changes.
- After stabilization, restore thresholds.
