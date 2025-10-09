# Adaptive Spread + Risk Guards

**Status**: ✅ Production Ready  
**Version**: 1.0  
**Date**: 2025-01-08

---

## 📋 Table of Contents

1. [Overview](#overview)
2. [Architecture](#architecture)
3. [Adaptive Spread](#adaptive-spread)
4. [Risk Guards](#risk-guards)
5. [Configuration](#configuration)
6. [Integration](#integration)
7. [Metrics & Monitoring](#metrics--monitoring)
8. [Debugging Guide](#debugging-guide)
9. [Tuning Guide](#tuning-guide)
10. [FAQ](#faq)

---

## Overview

### Purpose

The **Adaptive Spread + Risk Guards** system provides production-grade risk management and dynamic edge optimization for market making strategies.

### Key Benefits

- **Adaptive Spread**: Automatically adjusts spread based on:
  - Volatility (EMA of mid-price changes)
  - Liquidity (order book depth)
  - Latency (p95 execution times)
  - PnL deviation (rolling z-score)

- **Risk Guards**: Three-level protection system:
  - `NONE`: Normal operation
  - `SOFT`: Scale size, widen spread
  - `HARD`: Halt quoting temporarily

### Expected Impact

| Metric | Before | After | Change |
|--------|--------|-------|--------|
| `slippage_bps` | 2.5 | 1.8-2.2 | ↓0.3-0.7 ✓ |
| `net_bps` | 1.5 | 2.0-2.5 | ↑0.5-1.0 ✓ |
| `taker_share_pct` | ~10% | ≤10% | Maintain ✓ |
| `order_age_p95_ms` | 350 | <350 | ↓ ✓ |

---

## Architecture

### Component Hierarchy

```
quote_loop.py (orchestrator)
    ├─ adaptive_spread.py (spread estimator)
    │   ├─ Volatility EMA tracker
    │   ├─ Liquidity analyzer
    │   ├─ Latency p95 buffer
    │   └─ PnL z-score calculator
    │
    └─ risk_guards.py (protection system)
        ├─ Volatility guard
        ├─ Latency guard
        ├─ PnL drawdown guard
        ├─ Inventory guard
        └─ Taker fills guard
```

### Data Flow

```
Market Data → update_market_state() → [Adaptive Spread] → compute_spread_bps()
                                    └→ [Risk Guards] → assess()
                                                          ↓
                                            [NONE/SOFT/HARD] → Quote Generation
```

---

## Adaptive Spread

### Formula

```python
# 1. Compute individual scores (0..1)
vol_score = normalize(vol_ema_bps, soft=10, hard=20)
liq_score = normalize(liquidity, baseline=10)
lat_score = normalize(latency_p95, soft=150ms, hard=400ms)
pnl_score = normalize(pnl_z_score, soft=0, hard=-2.0)

# 2. Weighted combination
total_score = (
    vol_sensitivity * vol_score +
    liq_sensitivity * liq_score +
    lat_sensitivity * lat_score +
    pnl_sensitivity * pnl_score
)

# 3. Apply to base spread
target_spread = base_spread_bps * (1 + total_score)

# 4. Clamp and smooth
clamped = clamp(target_spread, min_spread_bps, max_spread_bps)
final = apply_step_limit(clamped, prev_spread, clamp_step_bps)

# 5. Cooloff (prevent rapid changes)
if (now_ms - last_change_ms) < cooloff_ms:
    return prev_spread
else:
    return final
```

### Volatility Tracking

- **Method**: EMA (Exponential Moving Average) of mid-price changes
- **Window**: 60 seconds (configurable)
- **Formula**:
  ```python
  alpha = 2 / (window_sec + 1)
  vol_ema = alpha * current_vol + (1 - alpha) * vol_ema
  ```

### Liquidity Scoring

- **Method**: Sum volume in top N book levels
- **Baseline**: 10.0 (normalized reference)
- **Score**: `max(0, 1 - liquidity / baseline)`
  - Low liquidity → high score → wider spread
  - High liquidity → low score → tighter spread

### Latency Scoring

- **Method**: p95 from ring buffer (last 100 samples)
- **Soft Threshold**: 150ms
- **Hard Threshold**: 400ms
- **Score**: Linear interpolation between thresholds

### PnL Deviation Scoring

- **Method**: Rolling z-score (last 60 samples)
- **Formula**:
  ```python
  mean = sum(pnl_window) / n
  std = sqrt(variance)
  z_score = (current_pnl - mean) / std
  ```
- **Score**: `max(0, -z_score / 2)` for negative z-scores
  - Profits (z > 0) → score = 0
  - Drawdown (z < -2) → score = 1

### Protection Mechanisms

1. **Min/Max Clamps**: `[0.6, 2.5] bps` (default)
2. **Step Limit**: Max change per tick = 0.2 bps (default)
3. **Cooloff**: 200ms pause after change (prevents oscillation)

---

## Risk Guards

### Three-Level System

| Level | Trigger | Actions |
|-------|---------|---------|
| **NONE** | All metrics within safe range | Normal operation |
| **SOFT** | One or more SOFT thresholds exceeded | • Scale order size × 0.5<br>• Force widen spread +0.2-0.4 bps<br>• Log warning |
| **HARD** | One or more HARD thresholds exceeded | • Cancel all active orders<br>• Halt quoting for 2s<br>• Log critical alert |

### Trigger Matrix

| Condition | SOFT | HARD | Unit |
|-----------|------|------|------|
| **Volatility** | 15 | 25 | bps |
| **Latency p95** | 300 | 450 | ms |
| **PnL z-score** | -1.5σ | -2.5σ | std dev |
| **Inventory** | 6% | 10% | % of max position |
| **Taker fills/15min** | 12 | 20 | count |

### Halt Mechanism (HARD)

When HARD guard triggers:

1. `halt_until_ms = now_ms + halt_ms_hard` (default 2000ms)
2. All active orders canceled
3. No new quotes generated until halt expires
4. After expiry, conditions re-assessed:
   - Still risky → HARD again (re-halt)
   - Improved → SOFT or NONE

### Multi-Trigger Behavior

- If **multiple** conditions trigger:
  - Any HARD → Overall level = HARD
  - Multiple SOFT, no HARD → Overall level = SOFT
- **Reason list** includes all active triggers:
  ```
  [GUARD] level=HARD reason=vol:27.1bps p95:480ms inv=11.2%
  ```

---

## Configuration

### `config.yaml` Settings

```yaml
# Adaptive Spread (dynamic spread based on market conditions)
adaptive_spread:
  enabled: true
  base_spread_bps: 1.0  # Base spread
  min_spread_bps: 0.6  # Minimum spread
  max_spread_bps: 2.5  # Maximum spread
  vol_window_sec: 60  # EMA window for volatility
  depth_levels: 5  # Book levels for liquidity analysis
  liquidity_sensitivity: 0.4  # Weight for liquidity score (0..1)
  vol_sensitivity: 0.6  # Weight for volatility score (0..1)
  latency_sensitivity: 0.3  # Weight for latency score (0..1)
  pnl_dev_sensitivity: 0.3  # Weight for PnL deviation score (0..1)
  clamp_step_bps: 0.2  # Max spread change per tick
  cooloff_ms: 200  # Cooldown after rapid change

# Risk Guards (SOFT/HARD protection)
risk_guards:
  enabled: true
  # Volatility guards
  vol_ema_sec: 60
  vol_hard_bps: 25.0  # Hard stop if vol > 25 bps
  vol_soft_bps: 15.0  # Soft warning if vol > 15 bps
  # Latency guards
  latency_p95_hard_ms: 450  # Hard stop if p95 > 450ms
  latency_p95_soft_ms: 300  # Soft warning if p95 > 300ms
  # PnL drawdown guards
  pnl_window_min: 60  # Rolling window (minutes)
  pnl_soft_z: -1.5  # Soft if z-score < -1.5σ
  pnl_hard_z: -2.5  # Hard if z-score < -2.5σ
  # Inventory guards
  inventory_pct_soft: 6.0  # Soft if |inv| > 6%
  inventory_pct_hard: 10.0  # Hard if |inv| > 10%
  # Taker series guard
  taker_fills_window_min: 15  # Rolling window (minutes)
  taker_fills_soft: 12  # Soft if ≥12 taker fills
  taker_fills_hard: 20  # Hard if ≥20 taker fills
  # Actions
  size_scale_soft: 0.5  # Scale order size by 0.5x in SOFT
  halt_ms_hard: 2000  # Halt quoting for 2s in HARD
```

### Validation Rules

- `base_spread_bps`: [0.1, 10.0]
- `min_spread_bps`: [0.1, ∞), must be < `max_spread_bps`
- Sensitivities: [0.0, 1.0] (normalized weights)
- `clamp_step_bps`: [0.01, 5.0]
- Thresholds: SOFT < HARD (automatically enforced)

---

## Integration

### In `quote_loop.py`

```python
# 1. Initialize (in __init__)
self.adaptive_spread = AdaptiveSpreadEstimator(cfg.adaptive_spread)
self.risk_guards = RiskGuards(cfg.risk_guards)

# 2. Update market state (on every tick)
quote_loop.update_market_state(
    symbol='BTCUSDT',
    mid_price=50000.0,
    orderbook=book_snapshot,
    latency_ms=120.0,
    pnl_delta=5.0,
    inventory_pct=3.2,
    ts_ms=now_ms
)

# 3. Assess guards BEFORE quoting
level, reasons = quote_loop.assess_risk_guards()

if level == GuardLevel.HARD:
    # Cancel all, sleep halt_ms_hard
    await cancel_all_orders()
    await asyncio.sleep(2.0)
    continue

# 4. Compute adaptive spread
base_spread_bps = 1.0
spread_bps = quote_loop.compute_adaptive_spread(
    base_spread_bps=base_spread_bps,
    orderbook=book_snapshot,
    now_ms=now_ms
)

# 5. Apply spread to quotes
half_spread = spread_bps / 2
bid_price = mid - (mid * half_spread / 10000)
ask_price = mid + (mid * half_spread / 10000)

# 6. If SOFT: scale size
if level == GuardLevel.SOFT:
    order_size *= 0.5  # From config: size_scale_soft

# 7. Generate quotes
await place_orders(bid_price, ask_price, order_size)
```

### Compatibility with Existing Features

- **Fast-cancel**: Independent, works alongside guards
- **Taker-cap**: Tracked separately, but HARD guard blocks all orders
- **Queue-aware**: Applies after adaptive spread determines base prices
- **Inventory-skew**: Applies after adaptive spread, before queue-aware

**Order of Operations**:
```
1. Assess guards → [NONE/SOFT/HARD]
2. Compute adaptive spread → [0.6..2.5 bps]
3. Apply inventory skew → [±max_skew_bps]
4. Apply queue-aware nudge → [±max_reprice_bps]
5. Generate final quotes
```

---

## Metrics & Monitoring

### Prometheus Metrics

```python
# Adaptive Spread
mm_adaptive_spread_bps          # Current spread in bps
mm_adaptive_score{type="vol"}   # Individual scores
mm_adaptive_score{type="liq"}
mm_adaptive_score{type="lat"}
mm_adaptive_score{type="pnl"}

# Risk Guards
mm_guard_level                  # 0=NONE, 1=SOFT, 2=HARD
mm_guard_reason_total{reason}   # Counter per reason
mm_guard_soft_seconds_total     # Time in SOFT
mm_guard_hard_seconds_total     # Time in HARD
```

### Grafana Dashboards

**Panel 1: Adaptive Spread Over Time**
```
Query: mm_adaptive_spread_bps
Viz: Time series, with bands for min/max
```

**Panel 2: Guard Level Heatmap**
```
Query: mm_guard_level
Viz: Heatmap (0=green, 1=yellow, 2=red)
```

**Panel 3: Guard Triggers by Reason**
```
Query: rate(mm_guard_reason_total[5m])
Viz: Stacked bar chart
```

### Log Examples

```
[ADSPREAD] base=1.00 vol=0.15 liq=0.30 lat=0.05 pnl=0.00 total=0.23 final=1.23
[GUARD] level=SOFT reason=vol:16.2bps inv:7.3%
[GUARD] level=HARD reason=vol:28.5bps p95:512ms takers:22/15min
```

---

## Debugging Guide

### Problem: Spread Too Wide

**Symptoms**: `adaptive_spread_bps` consistently > 2.0

**Diagnosis**:
1. Check individual scores:
   ```python
   metrics = estimator.get_metrics()
   print(f"Vol: {metrics['vol_score']:.2f}")
   print(f"Liq: {metrics['liq_score']:.2f}")
   print(f"Lat: {metrics['lat_score']:.2f}")
   print(f"PnL: {metrics['pnl_score']:.2f}")
   ```

2. Identify dominant factor (highest score)

**Solutions**:
- **High vol_score**: Normal in volatile markets. Consider increasing `vol_soft_bps` threshold if too sensitive.
- **High liq_score**: Order book thin. Increase `depth_levels` or adjust baseline in code.
- **High lat_score**: Network/exchange issues. Investigate latency sources.
- **High pnl_score**: Consistent losses. Review strategy fundamentals.

### Problem: Guards Trigger Too Often

**Symptoms**: Frequent SOFT/HARD alerts, low fill rate

**Diagnosis**:
1. Check reason counts:
   ```python
   counts = guards.get_reason_counts()
   print(f"Vol: {counts['vol']}")
   print(f"Latency: {counts['latency']}")
   print(f"PnL: {counts['pnl']}")
   print(f"Inventory: {counts['inventory']}")
   print(f"Takers: {counts['takers']}")
   ```

2. Identify most frequent trigger

**Solutions**:
- **Vol**: Increase `vol_soft_bps` / `vol_hard_bps` thresholds
- **Latency**: Improve infrastructure or increase `latency_p95_soft_ms`
- **PnL**: Review strategy profitability or adjust `pnl_soft_z`
- **Inventory**: Increase `inventory_pct_soft` or improve inventory management
- **Takers**: Increase `taker_fills_soft` or reduce taker order frequency

### Problem: Guards Never Trigger

**Symptoms**: Always `GuardLevel.NONE`, even in volatile markets

**Diagnosis**:
1. Verify `enabled: true` in `config.yaml`
2. Check if updates are being called:
   ```python
   print(f"Vol EMA: {guards.vol_ema_bps:.2f}")
   print(f"Latency p95: {guards.metrics['latency_p95_ms']:.0f}")
   ```

**Solutions**:
- If vol_ema = 0: `update_vol()` not being called
- If latency_p95 = 0: `update_latency()` not being called
- Review integration in `quote_loop.update_market_state()`

---

## Tuning Guide

### Conservative Settings (Lower Risk)

```yaml
adaptive_spread:
  base_spread_bps: 1.2  # Start wider
  min_spread_bps: 0.8
  max_spread_bps: 3.0
  vol_sensitivity: 0.8  # More reactive to vol
  clamp_step_bps: 0.1  # Slower changes

risk_guards:
  vol_soft_bps: 12.0  # Tighter thresholds
  vol_hard_bps: 20.0
  latency_p95_soft_ms: 250
  latency_p95_hard_ms: 400
  inventory_pct_soft: 5.0
  inventory_pct_hard: 8.0
  taker_fills_soft: 10
  taker_fills_hard: 15
```

### Aggressive Settings (Higher Edge)

```yaml
adaptive_spread:
  base_spread_bps: 0.8  # Start tighter
  min_spread_bps: 0.5
  max_spread_bps: 2.0
  vol_sensitivity: 0.4  # Less reactive
  clamp_step_bps: 0.3  # Faster changes

risk_guards:
  vol_soft_bps: 18.0  # Looser thresholds
  vol_hard_bps: 30.0
  latency_p95_soft_ms: 350
  latency_p95_hard_ms: 500
  inventory_pct_soft: 8.0
  inventory_pct_hard: 12.0
  taker_fills_soft: 15
  taker_fills_hard: 25
```

### Tuning Process

1. **Start with defaults** (as in `config.yaml`)
2. **Run 24h soak test**, collect metrics
3. **Analyze**:
   - Too many guard triggers? → Loosen thresholds
   - Spread too volatile? → Increase `cooloff_ms`, decrease `clamp_step_bps`
   - Slippage still high? → Increase sensitivities or tighten `min_spread_bps`
4. **Iterate** with A/B testing

---

## FAQ

### Q: Does adaptive spread replace manual spread config?
**A**: No, it *augments* it. `base_spread_bps` is your baseline, adaptive spread adjusts dynamically around it.

### Q: Can I disable guards but keep adaptive spread?
**A**: Yes. Set `risk_guards.enabled: false` in `config.yaml`.

### Q: What happens if both SOFT and HARD triggers activate?
**A**: HARD takes precedence. System halts quoting.

### Q: How do I test locally without live trading?
**A**: Use unit tests (`test_adaptive_spread.py`, `test_risk_guards.py`) or sim tests (`test_adaptive_spread_and_guards.py`).

### Q: Can I customize sensitivity weights at runtime?
**A**: Config is loaded at startup. Restart required for changes (by design, to avoid accidental mid-session changes).

### Q: Does this work with multiple symbols?
**A**: Yes, but `AdaptiveSpreadEstimator` and `RiskGuards` instances are per-symbol. Create one pair per symbol.

### Q: What if latency samples aren't available?
**A**: System gracefully degrades. Latency score defaults to 0 if <5 samples in buffer.

---

## Appendix: Score Curves

### Volatility Score Curve

```
1.0 |                  ████████
    |                ██
    |              ██
0.5 |            ██
    |          ██
    |        ██
0.0 |████████
    +---|---|---|---|---
       0  10  20  30  40 (vol_ema_bps)
```

### Liquidity Score Curve

```
1.0 |████
    |    ██
    |      ██
0.5 |        ██
    |          ██
    |            ████████
0.0 |                    
    +---|---|---|---|---
       0   5  10  15  20 (liquidity)
```

---

**End of Documentation**
