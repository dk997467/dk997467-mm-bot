# Shadow Mode Guide

**Status:** ✅ Production Ready  
**Version:** 1.0.0  
**Purpose:** Live feed monitoring with local order simulation

---

## 🎯 What is Shadow Mode?

**Shadow Mode** is a live-feed monitoring phase that bridges the gap between soak testing (mock data) and live trading:

- ✅ **Real market data** from Bybit/KuCoin WebSocket feeds
- ✅ **Local order simulation** (no API writes, no real trades)
- ✅ **KPI tracking** (maker/taker, net_bps, latency, risk)
- ✅ **Same analytics** as soak tests (ITER_SUMMARY, snapshots, audits)
- ✅ **CI/CD integration** with strict gates

**Use cases:**
- Validate strategy stability on real market conditions
- Compare shadow vs soak KPIs (expect within ±15%)
- Pre-production validation before dry-run (sandbox trading)

---

## 📦 Architecture

### **Module Structure**

```
tools/shadow/
├── __init__.py                    # Package initialization
├── run_shadow.py                  # Core runner (WS feed + simulation)
├── build_shadow_reports.py        # Report generator (snapshot + summary)
├── audit_shadow_artifacts.py      # Audit tool (readiness check)
└── ci_gates/
    ├── __init__.py
    └── shadow_gate.py             # CI gate (KPI validation)
```

### **Artifacts Structure**

```
artifacts/shadow/latest/
├── ITER_SUMMARY_1.json            # Per-iteration KPIs
├── ITER_SUMMARY_2.json
├── ...
├── SHADOW_RUN_SUMMARY.json        # Full run metadata
└── reports/
    └── analysis/
        ├── POST_SHADOW_SNAPSHOT.json         # KPI aggregates
        └── POST_SHADOW_AUDIT_SUMMARY.json    # Readiness report
```

---

## 🚀 Usage

### **1. Run Shadow Mode (Local)**

```bash
# Basic run (6 iterations, 60s each, mock mode)
python -m tools.shadow.run_shadow

# Custom configuration
python -m tools.shadow.run_shadow \
  --iterations 12 \
  --duration 120 \
  --profile aggressive \
  --exchange bybit \
  --mock

# Real feed (requires live WS connection)
python -m tools.shadow.run_shadow --mock false
```

**Parameters:**
- `--iterations`: Number of monitoring windows (default: 6)
- `--duration`: Duration per iteration in seconds (default: 60)
- `--exchange`: Exchange to monitor (bybit/kucoin, default: bybit)
- `--symbols`: Symbols to monitor (default: BTCUSDT ETHUSDT)
- `--profile`: Trading profile (moderate/aggressive, default: moderate)
- `--mock`: Use synthetic data for testing (default: True)
- `--output`: Output directory (default: artifacts/shadow/latest)
- `--min_lot`: Minimum lot size for volume check (default: 0.0, from profile)
- `--touch_dwell_ms`: Dwell time at touch price in ms (default: 25.0, from profile)
- `--require_volume`: Require last_qty >= min_lot for fills (default: False)

**Per-Symbol Profiles:**

Shadow Mode supports per-symbol parameter profiles in `profiles/shadow_profiles.json`:

```json
{
  "BTCUSDT": {
    "touch_dwell_ms": 25,
    "min_lot": 0.001,
    "comment": "Baseline - highly liquid"
  },
  "ETHUSDT": {
    "touch_dwell_ms": 25,
    "min_lot": 0.01,
    "comment": "Baseline - high volume"
  }
}
```

**Priority:** CLI args > Profile > Defaults

If CLI arg is at default value, profile value is used. Explicit CLI args override profile.

**Output:**
- `ITER_SUMMARY_N.json` — Per-iteration KPIs (with rich notes)
- `SHADOW_RUN_SUMMARY.json` — Full run metadata

---

### **2. Build Reports**

```bash
# Generate snapshot and summary
python -m tools.shadow.build_shadow_reports \
  --src artifacts/shadow/latest \
  --last-n 8
```

**Parameters:**
- `--src`: Source directory with ITER_SUMMARY files
- `--out`: Output directory (default: <src>/reports/analysis)
- `--last-n`: Use last N iterations for snapshot (default: 8)

**Output:**
- `POST_SHADOW_SNAPSHOT.json` — KPI aggregates (median, min, max)

---

### **3. Audit Artifacts**

```bash
# Informational audit
python -m tools.shadow.audit_shadow_artifacts

# Strict mode (fail on HOLD)
python -m tools.shadow.audit_shadow_artifacts --fail-on-hold
```

**Parameters:**
- `--base`: Base directory for artifacts (default: artifacts/shadow/latest)
- `--fail-on-hold`: Exit with code 1 if readiness is HOLD

**Output:**
- `POST_SHADOW_AUDIT_SUMMARY.json` — Readiness report
- Console: KPI table with pass/fail status
- Exit code: 0 (OK) or 1 (HOLD, if --fail-on-hold)

---

### **4. CI Gate (Strict)**

```bash
# Validate KPIs against thresholds
python -m tools.shadow.ci_gates.shadow_gate \
  --path artifacts/shadow/latest \
  --min_maker_taker 0.83 \
  --min_edge 2.5 \
  --max_latency 350 \
  --max_risk 0.40
```

**Parameters:**
- `--path`: Path to shadow artifacts
- `--min_maker_taker`: Min maker/taker ratio (default: 0.83)
- `--min_edge`: Min net_bps (default: 2.5)
- `--max_latency`: Max p95 latency in ms (default: 350)
- `--max_risk`: Max risk ratio (default: 0.40)

**Exit codes:**
- `0`: All KPIs passed
- `1`: One or more KPIs failed

**Override:** Set `SHADOW_OVERRIDE=1` to force pass (debugging only)

---

## 📊 KPI Thresholds

| Metric | Shadow Threshold | Soak Threshold | Note |
|--------|------------------|----------------|------|
| **maker_taker_ratio** | ≥ 0.83 | ≥ 0.83 | Same (strategy target) |
| **net_bps** | ≥ 2.5 | ≥ 2.9 | Relaxed (real feed volatility) |
| **p95_latency_ms** | ≤ 350 | ≤ 330 | Relaxed (network latency) |
| **risk_ratio** | ≤ 0.40 | ≤ 0.40 | Same (max risk limit) |

**Rationale for relaxed thresholds:**
- Real feeds have higher latency than mock data
- Market conditions are less predictable than mock
- Shadow mode validates strategy stability, not perfection

### **Min-Windows Gate**

Shadow audit requires a minimum number of iterations for statistical significance:

```bash
python -m tools.shadow.audit_shadow_artifacts \
  --base artifacts/shadow/latest \
  --min_windows 48  # Default: 48
```

**Gate behavior:**
- ❌ FAIL if `iterations < min_windows`
- Early exit before schema validation
- Default: 48 windows (recommended minimum)

**Rationale:** 48+ iterations ensure:
- Sufficient statistical power
- Coverage of different market conditions
- Reliable KPI estimates

### **Winsorized p95 Latency**

Shadow reports include **winsorized p95** (1% trim) alongside raw p95:

| Symbol | Windows | p95 Latency | p95_w (1%) | Difference |
|--------|---------|-------------|------------|------------|
| BTCUSDT | 48 | 228ms | 210ms | -18ms (outliers) |

**Winsorization:**
- Trim 1% from each tail (2% total)
- Compute p95 on remaining 98% of data
- Reduces outlier impact on latency measurement
- **Display only** (not stored in JSON artifacts)

**Benefits:**
- More robust latency estimate
- Less sensitive to transient network spikes
- Comparable across runs

---

## 🛠️ Makefile Shortcuts

### **Added Targets**

```makefile
make shadow-run        # Run shadow mode (default: 6 iters, mock)
make shadow-audit      # Audit artifacts (min_windows=48, informational)
make shadow-ci         # Run strict gate (min_windows=48, fail on HOLD)
make shadow-report     # Build reports + audit (one-shot)
make shadow-archive    # Rotate old artifacts (keep last 300)
```

### **Example Workflow**

```bash
# 1. Run shadow mode
make shadow-run

# 2. Audit results
make shadow-audit

# 3. Compare with soak baseline
make soak-compare
```

---

## 🔄 CI/CD Integration

### **GitHub Actions Workflow**

Workflow: `.github/workflows/shadow.yml`

**Trigger:** Manual (`workflow_dispatch`)

**Steps:**
1. Setup environment (Python, Rust, dependencies)
2. Run shadow mode (mock feed, 6 iterations)
3. Build reports (POST_SHADOW_SNAPSHOT)
4. Audit artifacts (strict mode, fail-on-hold)
5. CI gate (validate KPIs)
6. Upload artifacts (30 days retention)
7. Post PR comment (if PR exists)

**Usage:**
```
Actions → Shadow Mode → Run workflow
→ Select:
  - iterations: 6-24
  - duration: 60-300s
  - profile: moderate/aggressive
  - exchange: bybit/kucoin
→ Run workflow
```

**PR Comment Example:**

```markdown
### Shadow Mode Results

✅ READINESS: OK

**KPIs (last-8 window):**
- maker_taker_ratio: **0.871** (≥ 0.83)
- net_bps: **2.68** (≥ 2.5)
- p95_latency_ms: **328** (≤ 350)
- risk_ratio: **0.352** (≤ 0.40)
```

---

## 📈 Comparison with Soak

| Aspect | Soak Testing | Shadow Mode |
|--------|-------------|-------------|
| **Data Source** | Mock/synthetic | Real WS feeds |
| **Order Execution** | Simulated | Simulated |
| **Latency** | Predictable | Variable (real network) |
| **Market Conditions** | Controlled | Real-time |
| **Thresholds** | Strict (2.9, 330ms) | Relaxed (2.5, 350ms) |
| **Purpose** | Validate logic | Validate stability on real feeds |
| **Duration** | 24 iterations (2-4h) | 6-12 iterations (1-2h) |

**Expected delta:** ±15% between soak and shadow KPIs is acceptable.

---

## 🧪 Local Testing

### **Quick Test (6 iterations, mock mode)**

```bash
# 1. Run shadow
python -m tools.shadow.run_shadow --iterations 6 --duration 60

# 2. Build reports
python -m tools.shadow.build_shadow_reports

# 3. Audit
python -m tools.shadow.audit_shadow_artifacts

# 4. Compare with soak
python -m tools.soak.compare_runs \
  --a artifacts/soak/latest \
  --b artifacts/shadow/latest
```

### **Example Output**

```
================================================================================
SHADOW MODE: Live Feed Monitoring
================================================================================
[MOCK] Simulating bybit feed for ['BTCUSDT', 'ETHUSDT']
[ITER 1] Starting 60s shadow window...
[ITER 1] Completed: maker/taker=0.867, edge=3.12, latency=228ms, risk=0.340
[ITER 1] Saved: ITER_SUMMARY_1.json
...
================================================================================
[SHADOW] Run complete!
[SHADOW] Artifacts: artifacts/shadow/latest
================================================================================
```

---

## 🐛 Troubleshooting

### **Issue: "No ITER_SUMMARY files found"**

**Cause:** Shadow runner didn't write artifacts

**Fix:**
```bash
# Check if runner completed successfully
ls -la artifacts/shadow/latest/
# Should show ITER_SUMMARY_*.json files

# If missing, re-run with verbose output
python -m tools.shadow.run_shadow --iterations 6
```

### **Issue: "POST_SHADOW_SNAPSHOT.json not found"**

**Cause:** Report builder not run yet

**Fix:**
```bash
# Generate reports
python -m tools.shadow.build_shadow_reports --src artifacts/shadow/latest
```

### **Issue: "Shadow Gate FAIL: net_bps below threshold"**

**Cause:** Real feed edge is lower than expected

**Analysis:**
```bash
# Check individual iterations
cat artifacts/shadow/latest/ITER_SUMMARY_*.json | grep net_bps

# Compare with soak baseline
make soak-compare
```

**Resolution:**
- If delta < 15%: Acceptable variance (real vs mock)
- If delta > 15%: Investigate strategy parameters

### **Issue: "WS connection timeout (live mode)"**

**Cause:** Network/firewall blocking WS connection

**Fix:**
```bash
# Use mock mode for testing
python -m tools.shadow.run_shadow --mock

# For real feed, check network:
curl -I https://stream.bybit.com/
```

---

## 📚 Schema Reference

### **ITER_SUMMARY_N.json**

```json
{
  "iteration": 1,
  "timestamp": "2025-10-19T12:34:56Z",
  "duration_seconds": 60,
  "exchange": "bybit",
  "symbols": ["BTCUSDT", "ETHUSDT"],
  "profile": "moderate",
  "summary": {
    "maker_count": 52,
    "taker_count": 18,
    "maker_taker_ratio": 0.743,
    "net_bps": 2.87,
    "p95_latency_ms": 320.5,
    "risk_ratio": 0.362,
    "slippage_bps_p95": 1.12,
    "adverse_bps_p95": 2.15
  },
  "mode": "shadow"
}
```

### **POST_SHADOW_SNAPSHOT.json**

```json
{
  "mode": "shadow",
  "total_iterations": 6,
  "window_size": 6,
  "kpi_last_n": {
    "maker_taker_ratio": {
      "median": 0.871,
      "min": 0.812,
      "max": 0.903
    },
    "net_bps": {
      "median": 2.68,
      "min": 2.45,
      "max": 2.89
    },
    "p95_latency_ms": {
      "median": 328.0,
      "min": 298.0,
      "max": 345.0
    },
    "risk_ratio": {
      "median": 0.352,
      "min": 0.321,
      "max": 0.389
    }
  },
  "snapshot_kpis": {
    "maker_taker_ratio": 0.871,
    "net_bps": 2.68,
    "p95_latency_ms": 328.0,
    "risk_ratio": 0.352
  }
}
```

---

## 🎓 Best Practices

### **When to Run Shadow Mode**

1. **After soak tests pass** — Validate on real feeds
2. **Before dry-run** — Pre-production gate
3. **After strategy changes** — Verify stability impact
4. **Weekly regression** — Continuous validation

### **Iteration Count Recommendations**

| Purpose | Iterations | Duration | Total Time |
|---------|-----------|----------|------------|
| **Quick check** | 6 | 60s | 6 min |
| **Standard run** | 12 | 120s | 24 min |
| **Thorough validation** | 24 | 180s | 72 min |

### **Profile Selection**

- **moderate**: Conservative spread, lower risk, stable maker ratio
- **aggressive**: Tighter spread, higher taker ratio, higher edge (if successful)

### **Monitoring in Production**

Once shadow mode consistently passes:
1. Enable real WS feeds (`--mock false`)
2. Run nightly validation
3. Alert on KPI drift > 15% from baseline
4. Proceed to dry-run (sandbox trading)

---

## 🔗 Related Tools

| Tool | Purpose |
|------|---------|
| `tools.shadow.run_shadow` | Run shadow mode |
| `tools.shadow.build_shadow_reports` | Generate snapshot |
| `tools.shadow.audit_shadow_artifacts` | Audit artifacts |
| `tools.shadow.ci_gates.shadow_gate` | CI gate |
| `tools.soak.compare_runs` | Compare shadow vs soak |

---

## 🎯 Success Criteria

✅ **Shadow mode passes if:**
- maker_taker_ratio ≥ 0.83
- net_bps ≥ 2.5
- p95_latency_ms ≤ 350
- risk_ratio ≤ 0.40

✅ **Proceed to dry-run if:**
- Shadow mode passes consistently (3+ runs)
- Delta from soak KPIs < 15%
- No anomalies in ITER_SUMMARY files
- Strategy parameters stable

---

**Last Updated:** 2025-10-19  
**Version:** 1.0.0  
**Next Phase:** Dry-Run (Sandbox Trading)

