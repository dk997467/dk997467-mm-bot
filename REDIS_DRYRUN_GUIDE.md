# Redis KPI Export & Dry-Run Validation Guide

**Version:** 1.0  
**Last Updated:** 2025-10-19

## Table of Contents

1. [Overview](#overview)
2. [Redis KPI Export](#redis-kpi-export)
3. [Dry-Run Validation](#dry-run-validation)
4. [CI Integration](#ci-integration)
5. [Accuracy Report Interpretation](#accuracy-report-interpretation)
6. [Troubleshooting](#troubleshooting)
7. [FAQ](#faq)

---

## Overview

This guide covers two integrated features for Shadow Mode monitoring and validation:

1. **Redis KPI Export:** Publishes Shadow Mode KPIs to Redis for downstream consumption
2. **Dry-Run Validation:** Validates Shadow predictions against live market behavior

### Architecture

```
┌─────────────────┐
│  Shadow Mode    │ --redis-export--> ┌───────────┐
│  (Mock/WS/Redis)│                   │   Redis   │
└─────────────────┘                   │  Hash/    │
                                      │  Stream   │
                                      └─────┬─────┘
                                            │
                                            v
                                      ┌─────────────┐
                                      │  Dry-Run    │
                                      │  Validator  │
                                      └──────┬──────┘
                                             │
                                             v
                                      ┌─────────────────┐
                                      │ Accuracy Report │
                                      │  (MAPE, Drift)  │
                                      └─────────────────┘
```

### Key Features

- **Real-time KPI export** to Redis (hash or stream mode)
- **Per-symbol and aggregated** predictions
- **Accuracy metrics** (MAPE, median comparison)
- **Drift detection** (prediction vs. reality)
- **CI/CD integration** with automatic gating

---

## Redis KPI Export

### Purpose

Shadow Mode can export KPIs to Redis after each iteration, allowing downstream consumers (e.g., Dry-Run validators, dashboards) to access predictions in real-time.

### Export Modes

#### 1. Hash Mode (Latest Snapshot)

Stores the latest KPIs in a Redis hash. Ideal for quick lookups and real-time dashboards.

```bash
# Run Shadow Mode with Redis export (hash mode)
python -m tools.shadow.run_shadow \
  --source mock \
  --symbols BTCUSDT ETHUSDT \
  --iterations 6 \
  --duration 60 \
  --redis-export \
  --redis-export-url redis://localhost:6379
```

**Redis Keys:**
- `shadow:kpi:all` - Aggregated KPIs across all symbols
- `shadow:kpi:btcusdt` - Per-symbol KPIs (if `--per-symbol` used)
- `shadow:kpi:ethusdt` - Per-symbol KPIs (if `--per-symbol` used)

**Verify Export:**

```bash
# Check keys
redis-cli KEYS "shadow:kpi:*"

# Get aggregated KPIs
redis-cli HGETALL shadow:kpi:all

# Output:
# timestamp                   2025-10-19T14:30:00Z
# maker_taker_ratio           0.862
# net_bps                     3.12
# p95_latency_ms              228
# risk_ratio                  0.34
# maker_count                 186
# taker_count                 30
# total_fills                 216
```

#### 2. Stream Mode (Time-Series)

Appends KPIs to a Redis stream, preserving historical data.

```bash
# Standalone export (from existing artifacts)
python -m tools.shadow.export_to_redis \
  --src artifacts/shadow/latest \
  --mode stream \
  --per-symbol

# Or via Make target
make shadow-redis-export-stream
```

**Redis Streams:**
- `shadow:kpi:stream:all` - Aggregated time-series
- `shadow:kpi:stream:btcusdt` - Per-symbol time-series

**Verify Stream:**

```bash
# Read last 10 entries
redis-cli XREAD COUNT 10 STREAMS shadow:kpi:stream:all 0

# Count entries
redis-cli XLEN shadow:kpi:stream:all
```

### Schema

Each exported KPI entry contains:

| Field | Type | Description |
|-------|------|-------------|
| `timestamp` | ISO 8601 string | UTC timestamp |
| `timestamp_unix` | int | Unix timestamp |
| `symbol` | string | Symbol (or "ALL" for aggregated) |
| `maker_taker_ratio` | float | Maker fills / total fills |
| `net_bps` | float | Net edge in basis points |
| `p95_latency_ms` | float | 95th percentile latency (ms) |
| `risk_ratio` | float | Risk ratio (0-1) |
| `slippage_p95` | float | 95th percentile slippage |
| `adverse_p95` | float | 95th percentile adverse selection |
| `maker_count` | int | Number of maker fills |
| `taker_count` | int | Number of taker fills |
| `total_fills` | int | Total fills |
| `mode` | string | Always "shadow" |

### Makefile Shortcuts

```bash
# Export to hash (latest snapshot)
make shadow-redis-export

# Export to stream (time-series)
make shadow-redis-export-stream
```

### TTL Configuration

Hash keys have a default TTL of 24 hours. Customize with `--ttl`:

```bash
python -m tools.shadow.export_to_redis \
  --src artifacts/shadow/latest \
  --mode hash \
  --ttl 3600  # 1 hour
```

---

## Dry-Run Validation

### Purpose

Dry-Run Mode validates Shadow Mode predictions by re-simulating market behavior and comparing predicted vs. actual KPIs.

### How It Works

1. **Reads Shadow predictions** from Redis (e.g., `shadow:kpi:all`)
2. **Re-simulates market behavior** using same logic as Shadow Mode
3. **Compares predicted vs. actual KPIs** for each symbol
4. **Computes accuracy metrics:**
   - **MAPE** (Mean Absolute Percentage Error)
   - **Median comparison** (predicted vs. actual)
5. **Generates accuracy report** with PASS/WARN/FAIL status

### Usage

#### Basic Run

```bash
# Run Dry-Run validation (6 iterations)
python -m tools.dryrun.run_dryrun \
  --redis-url redis://localhost:6379 \
  --symbols BTCUSDT ETHUSDT \
  --iterations 6 \
  --duration 60
```

#### Extended Validation

```bash
# Longer run for statistical significance
python -m tools.dryrun.run_dryrun \
  --symbols BTCUSDT ETHUSDT \
  --iterations 12 \
  --duration 60
```

#### Makefile Shortcuts

```bash
# Quick validation (6 iterations)
make dryrun

# Extended validation (12 iterations)
make dryrun-validate
```

### Output Artifacts

- **`DRYRUN_ACCURACY_REPORT.md`** - Human-readable accuracy report
- **`DRYRUN_ACCURACY_REPORT.json`** - Machine-readable accuracy data

---

## CI Integration

### Workflow: `.github/workflows/dryrun.yml`

The CI workflow automates the entire Shadow → Redis → Dry-Run pipeline.

#### Trigger

Manually via GitHub Actions UI:

1. Go to **Actions** → **Dry-Run Validation (Shadow vs Reality)**
2. Click **Run workflow**
3. Select parameters:
   - **Iterations:** 6, 12, or 24
   - **Symbols:** Space-separated (default: BTCUSDT ETHUSDT)
   - **Duration:** Seconds per iteration (default: 60)

#### Phases

**Phase 1: Shadow Mode + Redis Export**
- Runs Shadow Mode with `--redis-export` enabled
- Exports KPIs to Redis (hash mode)
- Verifies artifacts and Redis export

**Phase 2: Dry-Run Validation**
- Reads predictions from Redis
- Re-simulates market behavior
- Generates accuracy report

**Phase 3: Accuracy Gating**
- Checks MAPE thresholds:
  - **MAPE < 15%:** ✅ PASS
  - **MAPE 15-30%:** ⚠️ WARN
  - **MAPE > 30%:** ❌ FAIL
- Workflow fails if MAPE > 30% for any KPI

#### Artifacts

- `shadow-artifacts` - Shadow Mode output (ITER_SUMMARY_*.json, etc.)
- `dryrun-artifacts` - Dry-Run output (accuracy reports)

#### Example Run

```bash
# Trigger via GitHub CLI
gh workflow run dryrun.yml \
  -f iterations=12 \
  -f symbols="BTCUSDT ETHUSDT SOLUSDT" \
  -f duration=60
```

---

## Accuracy Report Interpretation

### Report Structure

```markdown
# Dry-Run Accuracy Report

**Generated:** 2025-10-19T14:35:00Z

## Summary

| Symbol | KPI | Predicted | Actual (Median) | MAPE (%) | Status |
|--------|-----|-----------|-----------------|----------|--------|
| BTCUSDT | Maker/Taker | 0.862 | 0.871 | 1.0 | ✅ PASS |
| BTCUSDT | Net BPS | 3.12 | 3.05 | 2.2 | ✅ PASS |
| BTCUSDT | P95 Latency (ms) | 228 | 235 | 3.1 | ✅ PASS |
| BTCUSDT | Risk Ratio | 0.34 | 0.35 | 2.9 | ✅ PASS |
```

### Status Definitions

| Status | MAPE Range | Interpretation | Action |
|--------|------------|----------------|--------|
| ✅ **PASS** | < 15% | Excellent prediction accuracy | Monitor, no action needed |
| ⚠️ **WARN** | 15-30% | Acceptable but monitor drift | Investigate if trend continues |
| ❌ **FAIL** | > 30% | Poor accuracy, unreliable predictions | Re-calibrate Shadow Mode parameters |

### Example: Good Accuracy

```
Symbol: BTCUSDT
- Maker/Taker: Predicted 0.862, Actual 0.871 (MAPE 1.0%) ✅
- Net BPS: Predicted 3.12, Actual 3.05 (MAPE 2.2%) ✅
- P95 Latency: Predicted 228ms, Actual 235ms (MAPE 3.1%) ✅
- Risk Ratio: Predicted 0.34, Actual 0.35 (MAPE 2.9%) ✅

**Verdict:** All KPIs passed with MAPE < 15%. Predictions are highly accurate.
```

### Example: Warning State

```
Symbol: ETHUSDT
- Maker/Taker: Predicted 0.850, Actual 0.780 (MAPE 8.2%) ✅
- Net BPS: Predicted 2.80, Actual 2.35 (MAPE 16.1%) ⚠️
- P95 Latency: Predicted 250ms, Actual 265ms (MAPE 6.0%) ✅
- Risk Ratio: Predicted 0.38, Actual 0.42 (MAPE 10.5%) ✅

**Verdict:** Net BPS in WARN range. Monitor for continued drift. If MAPE increases beyond 30%, recalibrate.
```

### Example: Failure State

```
Symbol: SOLUSDT
- Maker/Taker: Predicted 0.800, Actual 0.550 (MAPE 31.3%) ❌
- Net BPS: Predicted 3.50, Actual 2.10 (MAPE 40.0%) ❌
- P95 Latency: Predicted 280ms, Actual 310ms (MAPE 10.7%) ✅
- Risk Ratio: Predicted 0.40, Actual 0.55 (MAPE 37.5%) ❌

**Verdict:** Multiple KPIs failed with MAPE > 30%. Predictions are unreliable. Possible causes:
- Market regime change (volatility spike, liquidity drop)
- Shadow Mode parameter drift
- Data source issues (stale feeds, gaps)

**Action Required:** Re-run Shadow Mode baseline with updated parameters.
```

---

## Troubleshooting

### Issue: Redis Connection Failed

**Symptoms:**
```
✗ Failed to connect to Redis: Error 111 connecting to localhost:6379. Connection refused.
```

**Solution:**
1. Start Redis: `redis-server`
2. Verify connection: `redis-cli ping` → should return `PONG`
3. Check Redis URL: `--redis-url redis://localhost:6379`

---

### Issue: No Predictions Found in Redis

**Symptoms:**
```
⚠ No predictions found at key: shadow:kpi:all
✗ No predictions found in Redis
```

**Solution:**
1. Verify Shadow Mode ran with `--redis-export`:
   ```bash
   python -m tools.shadow.run_shadow --redis-export ...
   ```
2. Check Redis keys:
   ```bash
   redis-cli KEYS "shadow:kpi:*"
   ```
3. If empty, re-run Shadow Mode with export enabled

---

### Issue: High MAPE (> 30%)

**Symptoms:**
```
❌ FAIL: BTCUSDT net_bps MAPE = 42.3% (> 30%)
```

**Possible Causes:**
1. **Market regime change:** Volatility spike, liquidity drop
2. **Shadow Mode drift:** Parameters need recalibration
3. **Data source issues:** Stale feeds, sequence gaps
4. **Simulation mismatch:** Dry-Run logic differs from Shadow

**Solution:**
1. **Re-baseline Shadow Mode:**
   ```bash
   python -m tools.shadow.run_shadow --iterations 48 --duration 60
   ```
2. **Check market conditions:** Compare vs. historical volatility
3. **Verify data quality:** Check for `seq_gaps`, `reordered`, `bp_drops` in Shadow notes
4. **Adjust parameters:** Review `touch_dwell_ms`, `min_lot` in `profiles/shadow_profiles.json`

---

### Issue: Workflow Fails on Accuracy Gate

**Symptoms:**
```
❌ Accuracy check FAILED - predictions are unreliable
Error: Process completed with exit code 1.
```

**Solution:**
1. Download artifacts: **Actions** → **Dry-Run Validation** → **Artifacts** → `dryrun-artifacts`
2. Review `DRYRUN_ACCURACY_REPORT.md` for specific KPI failures
3. Investigate root cause (see "High MAPE" above)
4. Re-run workflow after recalibration

---

## FAQ

### Q: When should I use hash vs. stream mode?

**A:** 
- **Hash mode:** For real-time dashboards and quick lookups (latest snapshot only)
- **Stream mode:** For time-series analysis, historical comparisons, and audit trails

### Q: How often should I run Dry-Run validation?

**A:**
- **Daily:** For stable production systems
- **After Shadow baseline:** Always validate after re-running Shadow Mode
- **Before deployment:** As part of pre-release checks

### Q: What MAPE threshold should I use?

**A:**
- **< 15%:** Production-ready, high confidence
- **15-30%:** Acceptable for staging, monitor for drift
- **> 30%:** Not production-ready, requires investigation

### Q: Can I run Dry-Run without Shadow Mode?

**A:** Yes, if predictions are already in Redis:
```bash
# Manually insert predictions
redis-cli HSET shadow:kpi:all maker_taker_ratio 0.85 net_bps 3.0 ...

# Run Dry-Run
python -m tools.dryrun.run_dryrun --baseline-key shadow:kpi:all
```

### Q: How do I export per-symbol KPIs?

**A:**
```bash
# In Shadow Mode
python -m tools.shadow.run_shadow --redis-export ...

# Or standalone
python -m tools.shadow.export_to_redis --per-symbol
```

### Q: Can I customize Dry-Run simulation logic?

**A:** Yes, edit `tools/dryrun/run_dryrun.py` → `simulate_iteration()` method. The current implementation uses mock data with variance. Replace with real WebSocket/Redis feed for production.

---

## Summary

| Feature | Command | Output |
|---------|---------|--------|
| Shadow + Redis Export | `python -m tools.shadow.run_shadow --redis-export` | Redis hash: `shadow:kpi:all` |
| Standalone Export (Hash) | `make shadow-redis-export` | Redis hash per symbol |
| Standalone Export (Stream) | `make shadow-redis-export-stream` | Redis streams |
| Dry-Run Validation | `make dryrun` | `DRYRUN_ACCURACY_REPORT.md` |
| CI Workflow | GitHub Actions → Dry-Run Validation | Artifacts + accuracy gate |

---

**Questions?** Check the [Shadow Mode Guide](SHADOW_MODE_GUIDE.md) for more details on Shadow Mode itself.

**Contributing:** Found an issue or want to improve this guide? Submit a PR or open an issue.

