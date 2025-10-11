# 🎯 MEGAPROMPT WORKFLOW — TL;DR

**Date:** 2025-10-11
**Status:** ✅ **STEP 1 COMPLETE, READY FOR STEP 2**

---

## ⚡ Quick Summary

| Step | Name | Status | Duration | Next Action |
|------|------|--------|----------|-------------|
| 1 | Prep & Overrides | ✅ **DONE** | 5s | — |
| 2 | Shadow 60m | 🟡 **READY** | 60min | **RUN THIS NEXT** |
| 3 | Soak 24-72h | 🟡 **READY** | 24-72h | After Step 2 |
| 4 | Dataset Aggregation | 🟡 **READY** | 5-10min | After Step 3 |
| 5 | A/B Testing | 🟡 **READY** | 72-216h | After Step 4 |
| 6 | CI Baseline Lock | 🟡 **READY** | <1min | After Step 5 |
| 7 | Daily Ops Pack | 🟡 **READY** | <1min | After Step 6 |

---

## 📦 What Was Delivered

### ✅ Step 1: Prep & Overrides (COMPLETED)

**Executed:** `python tools/soak/megaprompt_workflow.py --step 1`
**Status:** 🟢 **PASS**

**Artifacts Created:**
- ✅ `artifacts/release/FEATURE_FLAGS_SNAPSHOT.json` - Rollback snapshot
- ✅ `artifacts/reports/PREP_LOG.md` - Preparation checklist
- ✅ `artifacts/reports/FINISH_LINE_REPORT.md` - Workflow status
- ✅ All required directories created

**Validation Results:**
- ✅ `pipeline.enabled = true`
- ✅ `md_cache.enabled = true`
- ✅ `taker_cap.max_taker_share_pct = 9.0`
- ✅ `trace.enabled = true` (sample_rate: 0.2)
- ✅ `async_batch.enabled = true`

**Config Files Validated:**
- ✅ `config.yaml` - Main configuration
- ✅ `config.soak_overrides.yaml` - Soak test overrides

---

### 🟡 Automation Scripts Created (READY TO USE)

| Script | Purpose | Command |
|--------|---------|---------|
| **Main Orchestrator** | Run steps 1-3 | `python tools/soak/megaprompt_workflow.py --step N` |
| **Dataset Aggregator** | Create calibration dataset | `python tools/calibration/dataset_aggregator.py --from ISO --to ISO` |
| **A/B Harness** | Run A/B tests with gates | `python tools/ab/ab_harness.py --rollout-pct 10` |
| **Baseline Lock** | Lock baseline & CI gates | `python tools/ci/baseline_lock.py --lock` |
| **Daily Ops Report** | Generate daily reports | `python tools/ops/daily_report.py` |

---

## 🚀 Next Steps (In Order)

### **NEXT: Run Shadow 60m** ⏱️ 60 minutes

```bash
python tools/soak/megaprompt_workflow.py --step 2
```

**What this does:**
- Runs a 60-minute production-grade shadow test
- Collects performance baseline: stage latencies, md-cache metrics
- Validates 4 critical gates:
  - `hit_ratio >= 0.7`
  - `fetch_md p95 <= 35ms`
  - `tick_total p95 <= 150ms`
  - `deadline_miss < 2%`

**Artifacts generated:**
- `artifacts/baseline/stage_budgets.json` (updated with 60m data)
- `artifacts/md_cache/shadow_report.md`

**If all gates PASS:** → Proceed to Step 3 (Soak Test)
**If any gate FAILS:** → Review report, tune config, re-run

---

### **Then: Launch Soak Test** ⏱️ 24-72 hours

```bash
# Generate instructions first
python tools/soak/megaprompt_workflow.py --step 3

# Then manually launch (see generated instructions)
python main.py \
  --config config.yaml \
  --config-override config.soak_overrides.yaml \
  --mode soak \
  --duration 72
```

**What this does:**
- Runs bot in soak mode for 24-72 hours
- Collects fills and pipeline tick logs (daily rotation)
- Monitors for critical failures (auto-alerts)

**Artifacts generated:**
- `artifacts/reports/SOAK_START.md` - Instructions & stop criteria
- `artifacts/edge/feeds/fills_YYYYMMDD.jsonl`
- `artifacts/edge/feeds/pipeline_ticks_YYYYMMDD.jsonl`

**Stop Criteria (immediate halt):**
- 🚨 `deadline_miss > 5%` for 10+ min
- 🚨 `md_cache.hit_ratio < 50%` for 30+ min
- 🚨 `taker_share > 15%` for 1+ hour
- 🚨 Memory leak: +100MB/hour
- 🚨 Circuit breaker open > 5 min

---

### **Then: Aggregate Dataset** ⏱️ 5-10 minutes

```bash
python tools/calibration/dataset_aggregator.py \
  --from 2025-01-15T00:00:00Z \
  --to 2025-01-17T00:00:00Z \
  --interval-min 5
```

**What this does:**
- Aggregates soak test logs into calibration dataset
- Applies sanity filters (removes NaN/inf, spikes, low hit ratio)
- Generates summary report

**Artifacts generated:**
- `artifacts/edge/datasets/calib_YYYYMMDD_YYYYMMDD.json`
- `artifacts/edge/reports/calib_summary_YYYYMMDD_YYYYMMDD.md`

**Acceptance:**
- ✅ Duration >= 24h (minimum 12h)
- ✅ No NaN/inf values
- ✅ < 10% intervals filtered out

---

### **Then: A/B Testing** ⏱️ 72-216 hours (3 stages)

```bash
# Stage 1: 10% rollout (24-72h)
python tools/ab/ab_harness.py --rollout-pct 10 --duration-hours 24

# Stage 2: 50% rollout (24-72h) - if stage 1 passes
python tools/ab/ab_harness.py --rollout-pct 50 --duration-hours 24

# Stage 3: 100% rollout (24-72h) - if stage 2 passes
python tools/ab/ab_harness.py --rollout-pct 100 --duration-hours 24
```

**What this does:**
- Tests Auto-Calibrate Spread Weights + Queue-ETA Nudge
- Runs A vs B comparison with safety gates
- Auto-rollback if gates violated for 10+ minutes

**Safety Gates:**
- ✅ `Δslippage_bps(B-A) <= 0`
- ✅ `taker_share_B <= 9%`
- ✅ `tick_total p95 regression <= +10%`
- ✅ `deadline_miss < 2%`

**Acceptance (proceed to next stage):**
- ✅ `Δnet_bps >= +0.2 bps`
- ✅ All safety gates PASS

**Artifacts generated:**
- `artifacts/edge/reports/ab_run_online_YYYYMMDD_HHMMSS.md`

---

### **Then: Lock Baseline** ⏱️ < 1 minute

```bash
python tools/ci/baseline_lock.py --lock
```

**What this does:**
- Locks performance baseline for CI
- Activates CI gates on PRs
- Generates feature flags registry

**CI Gates Activated:**
- ✅ Stage p95 regression > +3% → FAIL
- ✅ Tick total p95 > +10% → FAIL
- ✅ MD-cache hit ratio < 60% → FAIL
- ✅ Deadline miss > 2% → FAIL

**Artifacts generated:**
- `artifacts/baseline/stage_budgets.locked.json`
- `artifacts/reports/BASELINE_LOCK_REPORT.md`
- `artifacts/reports/CI_GATES_STATUS.md`
- `docs/FEATURE_FLAGS_REGISTRY.md`

---

### **Finally: Daily Ops** ⏱️ < 1 minute (daily)

```bash
python tools/ops/daily_report.py
```

**What this does:**
- Generates daily operations report
- Tracks PnL, latency, errors, top/bottom symbols
- Provides alert rules and runbook links

**Artifacts generated:**
- `artifacts/reports/daily/YYYY-MM-DD.md`
- `artifacts/reports/ALERT_RULES.md`

**Automation:**
```bash
# Add to crontab for daily 9am UTC report:
0 9 * * * cd /path/to/mm-bot && python tools/ops/daily_report.py
```

---

## 📊 Current Artifact Status

### ✅ Existing Artifacts

- ✅ `config.soak_overrides.yaml`
- ✅ `artifacts/release/FEATURE_FLAGS_SNAPSHOT.json`
- ✅ `artifacts/reports/PREP_LOG.md`
- ✅ `artifacts/reports/FINISH_LINE_REPORT.md`
- ✅ `artifacts/baseline/stage_budgets.json` (from earlier 2-min shadow)
- ✅ `artifacts/md_cache/shadow_report.md` (from earlier 2-min shadow)

### 🟡 Pending Artifacts (generated by subsequent steps)

- 🟡 `artifacts/reports/SOAK_START.md` (Step 3)
- 🟡 `artifacts/edge/feeds/fills_YYYYMMDD.jsonl` (Step 3)
- 🟡 `artifacts/edge/feeds/pipeline_ticks_YYYYMMDD.jsonl` (Step 3)
- 🟡 `artifacts/edge/datasets/calib_*.json` (Step 4)
- 🟡 `artifacts/edge/reports/calib_summary_*.md` (Step 4)
- 🟡 `artifacts/edge/reports/ab_run_online_*.md` (Step 5)
- 🟡 `artifacts/baseline/stage_budgets.locked.json` (Step 6)
- 🟡 `docs/FEATURE_FLAGS_REGISTRY.md` (Step 6)
- 🟡 `artifacts/reports/daily/YYYY-MM-DD.md` (Step 7)

---

## 🔄 Rollback Plan ("Red Button")

If anything goes wrong:

```bash
# 1. Load snapshot
cat artifacts/release/FEATURE_FLAGS_SNAPSHOT.json

# 2. Edit config.yaml - set problematic flags to false:
#   pipeline.enabled: false
#   md_cache.enabled: false
#   async_batch.enabled: false

# 3. Restart service
# Ctrl+C + relaunch OR systemctl restart mm-bot

# 4. Verify stabilization in Prometheus/Grafana
```

---

## 📈 Timeline Estimate

| Phase | Duration | Status |
|-------|----------|--------|
| **Step 1: Prep** | 5 seconds | ✅ **DONE** |
| **Step 2: Shadow 60m** | 60 minutes | 🟡 **NEXT** |
| **Step 3: Soak** | 24-72 hours | 🟡 Pending |
| **Step 4: Dataset** | 5-10 minutes | 🟡 Pending |
| **Step 5: A/B (3 stages)** | 72-216 hours | 🟡 Pending |
| **Step 6: CI Lock** | < 1 minute | 🟡 Pending |
| **Step 7: Daily Ops** | < 1 minute | 🟡 Pending |
| **TOTAL** | **4-12 days** | — |

---

## 🎯 Final Acceptance Criteria

**Workflow is COMPLETE when:**

- ✅ Step 1: Config validated, snapshots created
- ✅ Step 2: Shadow 60m - all 4 gates PASS
- ✅ Step 3: Soak 24-72h - no critical stops, green metrics
- ✅ Step 4: Dataset >= 24h, sanity checks PASS
- ✅ Step 5: A/B 100% - Δnet_bps >= +0.2, no regressions
- ✅ Step 6: Baseline locked, CI gates active
- ✅ Step 7: Daily reports generated, alerts working

---

## 📚 Key Documents

| Document | Purpose |
|----------|---------|
| `FINISH_LINE_COMPLETE.md` | **Complete workflow guide** (this is the main doc) |
| `artifacts/reports/PREP_LOG.md` | Step 1 prep checklist |
| `artifacts/reports/PRE_SOAK_REPORT.md` | Pre-soak readiness assessment |
| `artifacts/reports/SOAK_DASHBOARD_CHECKLIST.md` | Monitoring dashboard links |
| `docs/FEATURE_FLAGS_REGISTRY.md` | Feature flags documentation |
| `artifacts/reports/ALERT_RULES.md` | Alert rules & runbooks |

---

## ⚡ One-Liner Commands

```bash
# Check workflow status
python tools/soak/megaprompt_workflow.py --status

# Run next step (Shadow 60m)
python tools/soak/megaprompt_workflow.py --step 2

# View prep log
cat artifacts/reports/PREP_LOG.md

# View feature flags snapshot
cat artifacts/release/FEATURE_FLAGS_SNAPSHOT.json

# Rollback config
cat artifacts/release/FEATURE_FLAGS_SNAPSHOT.json | grep enabled
```

---

## 🎉 Conclusion

**Current Status:** ✅ **READY FOR SHADOW 60M**

Step 1 (Prep & Overrides) has been completed successfully. All configuration overrides are validated, feature flag snapshots are created, and directories are set up.

**Next Action:** Run Step 2 (Shadow 60m) to establish production-grade performance baseline.

**Command:**
```bash
python tools/soak/megaprompt_workflow.py --step 2
```

**Estimated Time to Production:** 4-12 days

---

**Generated:** 2025-10-11T10:32:00Z
**Workflow Version:** 1.0
**Contact:** Principal Engineer / System Architect

