# Warm-up Monitoring & Alerting

**Purpose:** Track warm-up/ramp-down health, detect issues early, avoid noisy alerts.

---

## 📊 **Metrics Exported**

### **Phase Indicators**

```promql
warmup_active{iteration}          # 1=warmup active, 0=not active
warmup_iter_idx{iteration}         # Current iteration within warmup (0-4)
rampdown_active{iteration}         # 1=rampdown active, 0=not active
soak_phase_name{iteration,phase}   # 0=warmup, 1=rampdown, 2=steady
```

### **KPI Metrics (enriched with phase)**

```promql
soak_maker_taker_ratio{iteration,phase}   # Maker/taker ratio per iteration
soak_net_bps{iteration,phase}             # Net BPS per iteration
soak_risk_ratio{iteration,phase}          # Risk ratio per iteration
soak_p95_latency_ms{iteration,phase}      # P95 latency per iteration
```

### **Guard Activity**

```promql
guard_triggers_total{type}         # Total triggers by guard type
                                   # types: velocity, latency_soft, latency_hard,
                                   #        oscillation, freeze, cooldown
```

### **Tuner Activity**

```promql
tuner_keys_changed_total{iteration}   # Number of keys changed per iteration
```

### **Last-8 Window Summary**

```promql
maker_taker_ratio_hmean{window="8"}   # Harmonic mean for last 8 iterations
risk_ratio_mean{window="8"}           # Mean risk for last 8
p95_latency_ms_max{window="8"}        # Max p95 for last 8
p95_latency_ms_mean{window="8"}       # Mean p95 for last 8
```

---

## 🎯 **Grafana Dashboard**

**File:** `grafana_warmup_health.json`

### **Panels:**

1. **Warm-up Phase Progress** — Track warmup/rampdown/steady transitions
2. **KPI by Phase (Iterations 1-8)** — Maker/taker evolution by phase
3. **P95 Latency by Phase** — Latency trends with thresholds (340ms warn, 360ms critical)
4. **Risk Ratio by Phase** — Risk evolution (40% warn, 50% critical)
5. **Guard Triggers (Total)** — Total guard activity (3 warn, 5 critical)
6. **Velocity Guards (Warmup)** — Velocity guard activity (2 warn, 4 critical)
7. **Oscillation Guards** — Should be 0 (1+ is red)
8. **Tuner Activity (Keys Changed)** — Bar chart (≤2 green, >2 yellow/red)
9. **Last-8 Summary Metrics** — Final verdict KPIs

### **Annotations:**

- **Phase Transitions:** Automatically annotated when warmup_active changes

---

## 🚨 **Alert Rules**

**File:** `prometheus_warmup_alerts.yml`

### **Critical Alerts (only after warmup)**

| Alert | Condition | Duration | Severity |
|---|---|---|---|
| **SoakP95LatencyHigh** | p95 > 360ms after warmup | 3min | critical |
| **SoakRiskRatioHigh** | risk > 45% after warmup | 3min | critical |
| **SoakLast8KPIFailure** | Last-8 goals not met | 1min | critical |
| **SoakWarmupStuck** | Warmup iter unchanged 5min | 5min | critical |

### **Warning Alerts**

| Alert | Condition | Duration | Severity |
|---|---|---|---|
| **SoakMakerTakerLow** | maker/taker < 75% after warmup | 5min | warning |
| **SoakVelocityGuardTriggered** | velocity guard >2x in 5min after warmup | 1min | warning |
| **SoakOscillationDetected** | oscillation guard triggered | 1min | warning |
| **SoakTunerOveractive** | >2 keys changed per iter | 1min | warning |

### **Info Alerts**

| Alert | Condition | Duration | Severity |
|---|---|---|---|
| **SoakFreezeActivated** | Partial freeze active | 5min | info |
| **SoakTunerSilent** | No tuner activity 15min | 15min | info |

### **Warmup-specific Alerts**

| Alert | Condition | Duration | Severity |
|---|---|---|---|
| **SoakWarmupP95Critical** | p95 > 400ms *during* warmup | 3min | warning |

**Note:** Most alerts **don't fire during warmup** (iterations 1-4) to avoid noise.

---

## 🔧 **Usage**

### **1. Export Metrics (Local)**

```bash
# After soak run
python -m tools.soak.export_warmup_metrics \
  --path artifacts/soak/latest \
  --output artifacts/soak/latest/reports/analysis/warmup_metrics.prom
```

### **2. Import Dashboard**

```bash
# In Grafana UI
1. Go to Dashboards > Import
2. Upload monitoring/grafana_warmup_health.json
3. Select Prometheus datasource
4. Save
```

### **3. Configure Alerts**

```bash
# Add to prometheus.yml
rule_files:
  - "monitoring/prometheus_warmup_alerts.yml"

# Reload Prometheus
curl -X POST http://localhost:9090/-/reload
```

### **4. CI Integration**

Metrics are automatically exported in CI:
- **PR workflow:** `artifacts/soak/latest/reports/analysis/warmup_metrics.prom`
- **Nightly workflow:** same path, strict validation

Download artifacts from GitHub Actions to view metrics locally.

---

## 📈 **Interpretation Guide**

### **Healthy Warmup (Iterations 1-4)**

```
✅ warmup_active = 1
✅ soak_maker_taker_ratio: 0.50 → 0.75
✅ soak_p95_latency_ms: 250 → 310 (< 350ms)
✅ soak_risk_ratio: 0.17 → 0.56 (< 0.60)
✅ guard_triggers_total{type="velocity"}: 0-2
✅ tuner_keys_changed_total: 0-2 per iteration
```

### **Healthy Rampdown (Iterations 5-6)**

```
✅ rampdown_active = 1
✅ soak_maker_taker_ratio: 0.75 → 0.83
✅ soak_p95_latency_ms: 310 → 295 (decreasing)
✅ soak_risk_ratio: 0.56 → 0.39 (decreasing)
✅ guard_triggers_total{type="velocity"}: 2-4 (expected)
```

### **Healthy Steady (Iterations 7+)**

```
✅ warmup_active = 0
✅ rampdown_active = 0
✅ soak_phase_name = 2 (steady)
✅ soak_maker_taker_ratio: ≥ 0.83
✅ soak_p95_latency_ms: ≤ 340
✅ soak_risk_ratio: ≤ 0.40
✅ guard_triggers_total: stable (no new triggers)
✅ tuner_keys_changed_total: 0 (system stable)
```

### **Red Flags 🚩**

```
❌ soak_p95_latency_ms > 360ms for 3+ iterations after warmup
❌ soak_risk_ratio > 0.45 for 3+ iterations after warmup
❌ guard_triggers_total{type="oscillation"} > 0
❌ tuner_keys_changed_total > 2 consistently
❌ maker_taker_ratio_hmean{window="8"} < 0.83
❌ warmup_iter_idx stuck (same value 5+ min)
```

---

## 🎓 **Best Practices**

### **1. Don't Alert on Warmup**

```yaml
# ✅ Good: Only alert after warmup
expr: |
  soak_p95_latency_ms{iteration=~"[5-9]|[1-9][0-9]+"} > 360
  and warmup_active == 0

# ❌ Bad: Alerts fire during warmup
expr: soak_p95_latency_ms > 360
```

### **2. Use Sustained Conditions**

```yaml
# ✅ Good: Wait 3 minutes before alerting
for: 3m

# ❌ Bad: Alert immediately on spike
for: 0s
```

### **3. Use Last-8 Window for Final Verdict**

```yaml
# ✅ Good: Base decisions on last-8 aggregate
expr: maker_taker_ratio_hmean{window="8"} < 0.83

# ❌ Bad: React to single iteration
expr: soak_maker_taker_ratio < 0.83
```

### **4. Severity Levels**

- **critical:** Blocks production deployment (risk > 45%, p95 > 360ms, last-8 fail)
- **warning:** Needs attention but not blocking (maker/taker low, velocity guards)
- **info:** Informational only (freeze active, tuner silent)

---

## 📁 **Files**

```
monitoring/
├── grafana_warmup_health.json       # Dashboard definition
├── prometheus_warmup_alerts.yml     # Alert rules
└── WARMUP_MONITORING_README.md      # This file

tools/soak/
└── export_warmup_metrics.py         # Metrics exporter

.github/workflows/
├── ci.yml                           # PR workflow (exports metrics)
└── ci-nightly.yml                   # Nightly workflow (strict + metrics)
```

---

## 🚀 **Quick Start**

```bash
# 1. Run soak with warmup
python -m tools.soak.run \
  --iterations 24 \
  --mock \
  --auto-tune \
  --warmup

# 2. Export metrics
python -m tools.soak.export_warmup_metrics \
  --path artifacts/soak/latest \
  --output metrics.prom

# 3. View in Grafana
# Import grafana_warmup_health.json

# 4. Configure alerts
# Add prometheus_warmup_alerts.yml to Prometheus
```

---

## 📚 **References**

- **Implementation:** `WARMUP_VALIDATION_COMPLETE.md`
- **Baseline:** `artifacts/baseline/baseline-12-maker-bias/`
- **Preset:** `tools/soak/presets/warmup_conservative_v1.json`
- **Manager:** `tools/soak/warmup_manager.py`

---

**Last Updated:** 2025-10-18  
**Status:** ✅ Production Ready

