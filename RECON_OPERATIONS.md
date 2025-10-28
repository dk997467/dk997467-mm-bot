# Reconciliation Operations Guide

## Overview

Reconciliation (recon) is the process of comparing local state (orders, fills, positions) with exchange state to detect divergences. This is critical for detecting:

- **Order divergences**: Orders that exist locally but not on exchange (or vice versa)
- **Position drift**: Mismatch between local and remote position quantities
- **Fee/rebate accounting**: Actual trading costs vs. expected

## When Recon Runs

- **Periodic**: Every `recon_interval_s` seconds (default: 60s)
- **On demand**: Before shutdown or after recovery
- **Manual**: Via API/CLI command (future)

## Recon Report Fields

### JSON Structure

```json
{
  "timestamp_ms": 1698765432000,
  "symbols": ["BTCUSDT", "ETHUSDT"],
  "orders_local_only": ["order_123", "order_456"],
  "orders_remote_only": ["order_789"],
  "position_deltas": {
    "BTCUSDT": 0.001
  },
  "fees_report": {
    "gross_notional": 10000.0,
    "maker_notional": 8500.0,
    "taker_notional": 1500.0,
    "maker_count": 85,
    "taker_count": 15,
    "fees_absolute": 1.75,
    "rebates_absolute": 1.70,
    "net_absolute": 0.05,
    "fees_bps": 1.75,
    "rebates_bps": 1.70,
    "net_bps": 0.05,
    "maker_taker_ratio": 0.85
  },
  "divergence_count": 3
}
```

### Field Descriptions

| Field | Type | Description |
|-------|------|-------------|
| `timestamp_ms` | int | UTC timestamp when recon ran |
| `symbols` | list[str] | Symbols included in reconciliation |
| `orders_local_only` | list[str] | Order IDs present locally but not on exchange |
| `orders_remote_only` | list[str] | Order IDs present on exchange but not locally |
| `position_deltas` | dict | Position mismatches by symbol (qty delta) |
| `fees_report` | dict | Fee/rebate accounting summary |
| `divergence_count` | int | Total number of divergences detected |

## Interpreting Divergences

### orders_local_only

**Meaning**: Orders that we think are open, but exchange doesn't have.

**Possible Causes**:
1. Order was filled but fill event not processed yet (timing issue)
2. Order was canceled by exchange (e.g., post-only rejected)
3. Network issue during order placement (order never reached exchange)
4. Exchange internal issue (rare)

**Actions**:
- If small count (<5): Wait for next recon cycle
- If persistent: Cancel locally via `order_store.cancel(order_id)`
- If large count (>10): **ALERT** - possible systemic issue

### orders_remote_only

**Meaning**: Orders that exchange has, but we don't have locally.

**Possible Causes**:
1. Restart/recovery incomplete (missed some open orders)
2. Manual order placement outside bot
3. Duplicate order due to retry logic bug

**Actions**:
- If after restart: Expected - recovery will pick them up
- If during normal operation: **ALERT** - investigate immediately
- Cancel remotely if not recognized: `exchange.cancel(order_id)`

### position_deltas

**Meaning**: Mismatch between local position tracking and exchange position.

**Possible Causes**:
1. Missed fill events
2. Fill quantity rounding differences
3. Manual trades outside bot
4. Accounting bug in position tracker

**Actions**:
- If delta < 0.001: Ignore (rounding tolerance)
- If delta >= 0.001 and < 0.01: Log warning, monitor
- If delta >= 0.01: **ALERT** - manual intervention required
- **Never auto-correct** - requires manual review

## Fee/Rebate Accounting

### Key Metrics

| Metric | Target | Threshold |
|--------|--------|-----------|
| `maker_taker_ratio` | ≥ 0.85 | < 0.80 → WARN |
| `net_bps` | < 0 (rebate > fees) | > 0.5 → WARN |
| `fees_bps` | ≤ 2.0 | > 3.0 → WARN |

### Typical Values (Bybit USDT Perpetuals)

- **Maker fee**: 1.0 BPS (0.01%)
- **Taker fee**: 7.0 BPS (0.07%)
- **Maker rebate**: 2.0 BPS (0.02%)
- **Target maker ratio**: 85-90%
- **Expected net BPS**: -0.5 to +0.5 (near-zero or slight rebate)

### Alerting Rules

```
# Prometheus alerts (example)

# Low maker ratio (too many taker fills)
mm_maker_taker_ratio < 0.80 for 30m
  Severity: WARN
  Action: Review maker-only policy settings

# High net cost (losing money to fees)
mm_net_bps > 0.5 for 30m
  Severity: WARN
  Action: Review fee schedule, check for taker fills

# Negative net BPS is GOOD (earning rebates)
mm_net_bps < -0.5 for 30m
  Severity: INFO
  Action: None (expected with high maker ratio)
```

## Runbook Actions

### Divergence Detected

1. **Check logs**: Look for `recon_complete` events with `divergence_count > 0`
2. **Review divergence types**: Check `orders_local_only`, `orders_remote_only`, `position_deltas`
3. **Correlate with events**: Did restart/freeze/network issue occur?
4. **Manual verification**: Use exchange UI to verify open orders and positions
5. **Decide action**:
   - Wait for auto-resolution (next recon cycle)
   - Manual cancel/correction
   - Escalate if systemic issue

### High Fees / Low Maker Ratio

1. **Check `maker_only` setting**: Ensure `maker_only=True` in config
2. **Review recent fills**: Check for taker fills (should be rare)
3. **Inspect price offset**: Verify `post_only_offset_bps` is sufficient
4. **Market conditions**: High volatility can cause more taker fills
5. **Adjust parameters**: Increase offset or reduce trading frequency

### Position Drift

1. **STOP trading**: Freeze system immediately
2. **Manual audit**: Compare local DB vs exchange UI
3. **Identify root cause**: Missed fills? Manual trades? Bug?
4. **Correct position**: Manual trade to reconcile if needed
5. **Fix bug**: Update code if accounting error found
6. **Resume trading**: Only after full investigation

## Metrics

### Recon Metrics (Prometheus)

```
# Divergence counter
mm_recon_divergence_total{type="orders_local_only"} 5
mm_recon_divergence_total{type="orders_remote_only"} 2
mm_recon_divergence_total{type="position_delta"} 1

# Fee accounting
mm_maker_taker_ratio 0.87
mm_net_bps -0.3  # Negative = profit

# Fetch status
mm_symbol_filters_source_total{source="cached"} 145
mm_symbol_filters_source_total{source="fetched"} 23
mm_symbol_filters_source_total{source="default"} 2
mm_symbol_filters_fetch_errors_total 0
```

## CLI Usage

```bash
# Manual recon (future)
python -m tools.live.exec_demo --shadow --recon-now

# View last recon report
cat artifacts/state/last_recon.json | jq .

# Set recon interval
python -m tools.live.exec_demo --shadow --recon-interval-s 300  # 5 minutes
```

## FAQ

**Q: What is acceptable divergence_count?**  
A: 0-2 is normal (timing/latency). 3-5 is borderline. >5 needs investigation.

**Q: Should I auto-correct position drift?**  
A: **NO**. Always manual review. Auto-correction can compound bugs.

**Q: How often should recon run?**  
A: Default 60s is good. Increase to 300s (5min) for lower overhead. Decrease to 30s for high-frequency ops.

**Q: What if recon itself fails?**  
A: Check logs for `recon_failed` event. Common causes: network timeout, exchange API down, invalid symbol. Recon failure is logged but non-fatal.

**Q: Can I disable recon?**  
A: Not recommended. Set `recon_interval_s` to very large value (e.g., 3600) if needed, but keep it enabled.

## VIP Fees & Per-Symbol Schedules (P0.11)

**New in P0.11**: Reconciliation now supports per-symbol VIP fee profiles for accurate fee/rebate accounting across different trading tiers.

### Overview

Previously, all symbols used a single global fee schedule (CLI flags: `--fee-maker-bps`, `--fee-taker-bps`, `--rebate-maker-bps`). Now, you can specify different fee rates per symbol or per tier.

### Usage

Pass `profile_map` to `calc_fees_and_rebates()`:

```python
from tools.live.fees import calc_fees_and_rebates
from tools.live.fees_profiles import build_profile_map

# Default schedule (fallback)
default_schedule = FeeSchedule(
    maker_bps=Decimal("1.0"),
    taker_bps=Decimal("7.0"),
    maker_rebate_bps=Decimal("2.0"),
)

# Build VIP2 profile (applies to all symbols via wildcard)
profile_map = build_profile_map("VIP2")

# Calculate fees with per-symbol profiles
fees_report = calc_fees_and_rebates(
    fills=fills,
    fee_schedule=default_schedule,
    profile_map=profile_map,
)
```

### Per-Symbol Custom Profiles

```python
from tools.live.fees_profiles import FeeProfile, VIP2_PROFILE, VIP0_PROFILE

# Custom per-symbol profiles
profile_map = {
    "BTCUSDT": VIP2_PROFILE,  # BTC gets VIP2 rates (maker=0.5, taker=5.0, rebate=2.5)
    "ETHUSDT": VIP0_PROFILE,  # ETH gets VIP0 rates (maker=1.0, taker=7.0, rebate=0.0)
    "*": VIP1_PROFILE,        # All other symbols get VIP1 rates
}

fees_report = calc_fees_and_rebates(fills, default_schedule, profile_map=profile_map)
```

### Pre-Defined VIP Tiers

| Tier | Maker BPS | Taker BPS | Rebate BPS | Use Case |
|------|-----------|-----------|------------|----------|
| VIP0 | 1.0 | 7.0 | 0.0 | Standard retail |
| VIP1 | 0.8 | 6.5 | 1.0 | Active trader |
| VIP2 | 0.5 | 5.0 | 2.5 | High-volume trader |
| VIP3 | 0.2 | 4.0 | 3.0 | Institutional |
| MM_Tier_A | 0.0 | 3.0 | 5.0 | Market maker (strong rebate) |

### Fallback Behavior

1. **Exact symbol match**: Use profile for that symbol (e.g., `profile_map["BTCUSDT"]`)
2. **Wildcard match (`*`)**: Use wildcard profile (e.g., `profile_map["*"]`)
3. **No match**: Fall back to global `fee_schedule` (from CLI flags)

### Reconciliation Integration

When recon runs with profiles, the `fees_report` in the recon JSON output reflects per-symbol calculations:

```json
{
  "recon": {
    "fees_report": {
      "gross_notional": 50000.0,
      "maker_notional": 45000.0,
      "taker_notional": 5000.0,
      "maker_count": 90,
      "taker_count": 10,
      "fees_absolute": 2.75,   # Calculated using per-symbol profiles
      "rebates_absolute": 11.25,
      "net_absolute": -8.50,   # Rebate > fees (good for MM)
      "maker_taker_ratio": 0.90
    }
  }
}
```

### Testing

Unit tests verify:
- Profile selection (exact, wildcard, fallback)
- Per-symbol override behavior
- Decimal exactness (no floating-point errors)

```bash
pytest tests/unit/test_fees_profiles_unit.py -v
```

### CLI Exposure (Future)

*Note: CLI flags for profiles coming in P0.12. Current usage is Python API only.*

Planned:
```bash
# Future: Apply VIP2 tier to all symbols
python -m tools.live.exec_demo --shadow --fee-tier VIP2 --symbols BTCUSDT,ETHUSDT

# Future: Per-symbol profiles via JSON config
python -m tools.live.exec_demo --shadow --fee-profiles fees_config.json
```

## References

- [RUNBOOK_SHADOW.md](RUNBOOK_SHADOW.md) - Shadow mode operations (P0.11 VIP fees section)
- [README_EXECUTION.md](README_EXECUTION.md) - Execution engine (VIP fees & per-symbol schedules)
- [tools/live/fees_profiles.py](tools/live/fees_profiles.py) - VIP profile definitions
- [tools/live/fees.py](tools/live/fees.py) - Fee/rebate calculation engine
- [LIVE_PREP_CHECKLIST.md](LIVE_PREP_CHECKLIST.md) - Pre-live checklist
- [OBSERVABILITY.md](OBSERVABILITY.md) - Metrics and alerting (future)

