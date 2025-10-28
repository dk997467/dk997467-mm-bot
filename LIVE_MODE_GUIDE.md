# Live Mode Guide 🚀

**Version:** 1.0.0  
**Status:** Production-Ready  
**Last Updated:** 2025-10-26

---

## Overview

Live Mode is a cautious, automated system for ramping live trading up/down based on real-time KPI monitoring, with built-in auto-freeze, hysteresis, and alerts.

**Key Features:**
- **FSM Controller:** ACTIVE → COOLDOWN → FROZEN transitions
- **Hysteresis:** Prevents rapid freeze/unfreeze cycles
- **Per-Symbol Throttling:** Granular control per trading pair
- **Auto-Freeze:** Immediate halt on CRIT violations
- **Redis Integration:** Real-time state/throttle export
- **Grafana Alerts:** Proactive monitoring & notifications
- **CI Gate:** KPI validation before deployment

---

## Architecture

```
┌─────────────────┐
│   Redis/WS      │  (Live KPI feed)
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│   run_live.py   │  (Runner)
│  - Fetch KPI    │
│  - Aggregate    │
│  - Call FSM     │
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│  controller.py  │  (FSM)
│  - ACTIVE       │
│  - COOLDOWN     │
│  - FROZEN       │
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│  Throttle Out   │
│  - Redis keys   │
│  - Artifacts    │
│  - Alerts       │
└─────────────────┘
```

---

## FSM States

| State | Throttle | Description | Exit Condition |
|-------|----------|-------------|----------------|
| **ACTIVE** | 1.0 | Full trading, all systems go | WARN count ≥ min_warn_windows |
| **COOLDOWN** | 0.3-0.6 | Reduced trading, monitoring closely | CRIT violation OR stable OK |
| **FROZEN** | 0.0 | Trading halted | Hysteresis: N consecutive OK windows |

### State Transitions

**ACTIVE → COOLDOWN:**
```
if warn_count >= min_warn_windows:
    state = COOLDOWN
    throttle = 0.5
```

**COOLDOWN → FROZEN:**
```
if crit_count > 0:
    state = FROZEN
    throttle = 0.0
```

**FROZEN → ACTIVE (Hysteresis):**
```
if ok_count >= unfreeze_after_ok_windows AND warn_count == 0 AND crit_count == 0:
    ok_counter++
    if ok_counter >= unfreeze_after_ok_windows:
        state = ACTIVE
        throttle = 1.0
```

**Hysteresis:** Prevents "flapping" (rapid freeze/unfreeze). Requires `unfreeze_after_ok_windows` (default: 24) consecutive OK windows before unfreezing.

---

## KPI Thresholds

| KPI | Threshold | Action |
|-----|-----------|--------|
| `edge_bps` | < 2.5 | **CRIT** (freeze) |
| `maker_taker_ratio` | < 0.83 | **WARN** (cooldown) |
| `risk_ratio` | > 0.40 | **CRIT** (freeze) |
| `p95_latency_ms` | > 350 | **WARN** (cooldown) |
| `anomaly_score` | > 2.0 | **CRIT** (freeze) |

**Per-Symbol vs Overall:**
- **Per-symbol:** Each symbol evaluated independently
- **Overall:** If any symbol triggers CRIT, global state → FROZEN

---

## Ramp Profiles

Located in `profiles/live_profiles.json`:

| Profile | Max Notional | Max Symbols | Description |
|---------|--------------|-------------|-------------|
| **A** | $100 | 1 | Ultra-conservative |
| **B** | $300 | 2 | Moderate |
| **C** | $500 | 5 | Aggressive |

**Usage:**
```bash
python -m tools.live.run_live --ramp-profile A
```

---

## Redis Keys

**Namespace:** `{env}:{exchange}:live:`

| Key | Type | Value | TTL | Description |
|-----|------|-------|-----|-------------|
| `state` | String | `ACTIVE\|COOLDOWN\|FROZEN` | 3600s | Global state |
| `throttle:{symbol}` | String | `0.0` to `1.0` | 3600s | Per-symbol throttle |
| `summary` | Hash | KPI aggregates | 3600s | Summary stats |

**Example:**
```bash
# Check global state
redis-cli GET prod:bybit:live:state
# → "ACTIVE"

# Check per-symbol throttle
redis-cli GET prod:bybit:live:throttle:BTCUSDT
# → "1.0"
```

---

## Quick Start

### 1. Local Dry-Run

```bash
# Run once with mock data
make live-run
```

**Output:**
- `artifacts/live/latest/LIVE_SUMMARY.json`
- `artifacts/live/latest/LIVE_REPORT.md`
- `artifacts/live/latest/LIVE_DECISION.json`

### 2. With Redis (Dev)

```bash
python -m tools.live.run_live \
  --symbols BTCUSDT,ETHUSDT \
  --ramp-profile A \
  --redis-url rediss://dev-redis.example.com:6379/0 \
  --env dev \
  --iterations 5 \
  --interval-sec 60
```

### 3. Production (Supervised)

```bash
# PRODUCTION: No --dry-run flag
python -m tools.live.run_live \
  --symbols BTCUSDT \
  --ramp-profile A \
  --redis-url $REDIS_URL_PROD \
  --env prod \
  --exchange bybit \
  --iterations 0  # Infinite loop
```

**⚠️ Production Checklist:**
- [ ] Shadow/Dry-run stable for 48+ windows
- [ ] Accuracy PASS in last 3 sanity runs
- [ ] Redis live keys visible and TTL refreshing
- [ ] Debounce/alert-policy configured (`prod=CRIT`)
- [ ] Profile A limits reviewed ($100 notional, 1 symbol)
- [ ] Runbook distributed to team
- [ ] Grafana dashboard accessible
- [ ] Rollback plan documented

---

## CI Gate

**Purpose:** Validate KPI before deployment.

**Usage:**
```bash
make live-gate
```

**Thresholds:**
```bash
python -m tools.live.ci_gates.live_gate \
  --path artifacts/live/latest \
  --min_edge 2.5 \
  --min_maker_taker 0.83 \
  --max_risk 0.40 \
  --max_latency 350
```

**Exit Codes:**
- `0`: PASS (all thresholds met)
- `1`: FAIL (violations detected)

---

## Alerts & Dashboard

### Grafana Alerts

Located in `ops/alerts/live_alerts.yml`:

| Alert | Condition | Severity | For |
|-------|-----------|----------|-----|
| **LiveStateFrozen** | `state == FROZEN` | CRIT | 10min |
| **LiveThrottleLow** | `avg(throttle) < 0.4` | WARN | 15min |
| **LiveSymbolFrozen** | `symbol_throttle == 0` | WARN | 5min |
| **LiveKPIViolation** | `crit_violations > 0` | CRIT | Immediate |
| **LiveRedisDown** | `redis_up == 0` | CRIT | 2min |

### Dashboard Panels

**Panel 1: Live State (Gauge)**
```
Query: live_state{env="prod"}
Thresholds: 0=FROZEN (red), 1=COOLDOWN (yellow), 2=ACTIVE (green)
```

**Panel 2: Throttle Factor (Time Series)**
```
Query: live_throttle_factor{env="prod"}
```

**Panel 3: Per-Symbol Throttle (Table)**
```
Query: live_symbol_throttle{env="prod"}
```

**Panel 4: Violations Count (Stat)**
```
Query: sum(increase(live_violations_total{env="prod"}[1h]))
```

---

## Runbook

### Scenario 1: CRIT Alert - State FROZEN

**Symptoms:**
- Alert: `LiveStateFrozen` fires
- Slack/Telegram: "Live mode is FROZEN for >10 minutes"

**Investigation:**
1. Check `LIVE_DECISION.json` for reasons:
   ```bash
   cat artifacts/live/latest/LIVE_DECISION.json | jq '.reasons'
   # → ["edge_bps=2.0 < 2.5", "risk=0.45 > 0.40"]
   ```

2. Check which symbol triggered:
   ```bash
   jq '.triggered_by' artifacts/live/latest/LIVE_DECISION.json
   # → "BTCUSDT"
   ```

3. Check Redis state:
   ```bash
   redis-cli GET prod:bybit:live:state
   # → "FROZEN"
   ```

**Root Causes:**
- **Market volatility:** Edge < 2.5 BPS (spread too tight)
- **Risk spike:** Risk ratio > 0.40 (inventory imbalance)
- **Latency:** P95 > 350ms (exchange lag)
- **Anomaly:** Anomaly score > 2.0 (unusual pattern)

**Resolution:**
1. **If market issue:** Wait for stability, monitor hysteresis progress
2. **If config issue:** Adjust thresholds in `KPIThresholds` (not recommended in prod)
3. **If bug:** Investigate logs, rollback if necessary

**Manual Unfreeze (ONLY if safe):**
```bash
# Set Redis state to ACTIVE (bypass controller)
redis-cli SET prod:bybit:live:state "ACTIVE" EX 3600

# ⚠️ WARNING: This bypasses safety checks!
# Only use if controller is malfunctioning AND KPIs are healthy
```

---

### Scenario 2: WARN Alert - Throttle Low

**Symptoms:**
- Alert: `LiveThrottleLow` fires
- Average throttle < 0.4 for 15+ minutes

**Investigation:**
1. Check per-symbol throttle:
   ```bash
   jq '.per_symbol_throttle' artifacts/live/latest/LIVE_SUMMARY.json
   # → {"BTCUSDT": 0.5, "ETHUSDT": 0.3}
   ```

2. Check `LIVE_REPORT.md` for reasons

**Resolution:**
- **Multiple symbols in COOLDOWN:** Normal during volatile periods, monitor
- **Persistent WARN:** Investigate KPI drift (maker/taker ratio, latency)

---

### Scenario 3: Symbol-Specific Freeze

**Symptoms:**
- Alert: `LiveSymbolFrozen` for specific symbol
- Other symbols still ACTIVE

**Investigation:**
```bash
# Check per-symbol status
jq '.per_symbol_throttle' artifacts/live/latest/LIVE_SUMMARY.json
# → {"BTCUSDT": 1.0, "ETHUSDT": 0.0, "SOLUSDT": 1.0}
```

**Resolution:**
- **If symbol is problematic:** Remove from symbols list, restart runner
- **If temporary:** Wait for hysteresis to unfreeze (24 OK windows)

---

## Files & Artifacts

| File | Location | Description |
|------|----------|-------------|
| **LIVE_SUMMARY.json** | `artifacts/live/latest/` | Machine-readable summary |
| **LIVE_REPORT.md** | `artifacts/live/latest/` | Human-readable report |
| **LIVE_DECISION.json** | `artifacts/live/latest/` | Controller decision details |
| **live_profiles.json** | `profiles/` | Ramp profile configs |
| **controller.py** | `tools/live/` | FSM implementation |
| **run_live.py** | `tools/live/` | Main runner |
| **export_live_summary.py** | `tools/live/` | Redis exporter |
| **live_gate.py** | `tools/live/ci_gates/` | CI gate |

---

## Testing

**Unit Tests:**
```bash
pytest tools/live/tests/test_controller.py -v
```

**Integration (Dry-Run):**
```bash
make live-run
make live-gate
```

**Coverage:**
- ✅ ACTIVE → COOLDOWN transition
- ✅ COOLDOWN → FROZEN transition
- ✅ FROZEN → ACTIVE hysteresis
- ✅ Per-symbol throttle calculation
- ✅ Anomaly score triggers

---

## FAQ

**Q: How long does it take to unfreeze?**  
A: `unfreeze_after_ok_windows` (default: 24) consecutive OK windows. At 60s/window = 24 minutes minimum.

**Q: Can I manually unfreeze?**  
A: Yes, but **NOT recommended**. Set Redis key `{env}:{exchange}:live:state = "ACTIVE"`. This bypasses safety checks.

**Q: What if Redis goes down?**  
A: Runner continues locally, writes artifacts, but cannot update Redis. Alert `LiveRedisDown` fires.

**Q: Can I run multiple instances?**  
A: **No**. Live mode runner is stateful (FSM counters). Only one instance per env/exchange.

**Q: How do I add a new symbol?**  
A: Add to `--symbols` flag, ensure profile allows (e.g., profile C max_symbols=5).

**Q: What's the difference between global throttle and per-symbol throttle?**  
A: **Global:** FSM state-based (ACTIVE=1.0, COOLDOWN=0.5, FROZEN=0.0). **Per-symbol:** KPI-based (OK=1.0, WARN=0.5, CRIT=0.0).

---

## References

- **Shadow Mode:** `SHADOW_MODE_GUIDE.md`
- **Accuracy Gate:** `ACCURACY_GATE_GUIDE.md`
- **Soak Tests:** `README.md` (Soak section)
- **Redis Export:** `tools/shadow/export_to_redis.py`
- **Alerts:** `ops/alerts/live_alerts.yml`

---

## Changelog

### v1.0.0 (2025-10-26)

**Initial Release:**
- FSM controller (ACTIVE/COOLDOWN/FROZEN)
- Hysteresis (unfreeze after N OK windows)
- Per-symbol throttling
- Redis integration (state/throttle/summary)
- CI gate (`live_gate.py`)
- Grafana alerts (`live_alerts.yml`)
- Ramp profiles (A/B/C)
- Makefile targets (`live-run`, `live-gate`, `live-report`)
- CI workflow (`.github/workflows/live.yml`)
- Full documentation (`LIVE_MODE_GUIDE.md`)
- Unit tests (`test_controller.py`)

---

## Support

**Issues:** GitHub Issues  
**Runbook:** This document (Runbook section)  
**Alerts:** Check Grafana dashboard  
**Logs:** `artifacts/live/latest/LIVE_REPORT.md`

🚀 **Happy Trading!**

