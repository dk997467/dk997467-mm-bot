# Warm-up/Ramp-down Implementation Progress

**Date:** 2025-10-18  
**Branch:** `feat/maker-bias-uplift`  
**Status:** 🚧 **IN PROGRESS** (Infrastructure 70% complete)

---

## ✅ Completed (Steps 1-2)

### Step 1: Baseline Snapshot ✅
- **Created:** `artifacts/baseline/baseline-12-maker-bias/`
- **Contents:** All artifacts from 12-iteration run with maker_bias preset
- **README:** KPI summary and identified issues
- **Problems documented:**
  - First 4 iterations: FAIL (negative net_bps, high risk)
  - Convergence time: 5-6 iterations
  - Risk spikes: 17% → 68%

### Step 2: Warm-up Preset ✅
- **Created:** `tools/soak/presets/warmup_conservative_v1.json`
- **Changes:**
  - Quoting: +0.03 spread, +25ms min_interval, ×0.75 replace_rate
  - Impact: ×0.85 impact_cap, ×0.85 max_delta
  - Engine: +100ms tail_age
  - Taker rescue: ×0.70 rescue_max, +0.8 min_edge, +400ms cooldown
  - Risk: ×0.80 position_limit
- **Target:** Status WARN max (not FAIL) on iterations 1-4

### Infrastructure: Warm-up Manager ✅
- **Created:** `tools/soak/warmup_manager.py` (300+ lines)
- **Features implemented:**
  - Phase detection (warmup/rampdown/steady)
  - Preset application with add/mul operations
  - Linear interpolation for ramp-down
  - Adaptive velocity guard thresholds
  - Tuner micro-steps filter (≤2 keys, cooldown tracking)
  - Latency pre-buffer logic
  - Risk/inventory limits
  - Rescue taker blocking conditions

### CLI Integration ✅
- **Added to `run.py`:**
  - Import `WarmupManager`
  - CLI flags: `--warmup`, `--warmup-preset`
  - Default preset: `warmup_conservative_v1`

---

## 🚧 Remaining Work (Steps 3-7)

### Step 3: Integration into run.py Iteration Loop
**Status:** NOT STARTED  
**Estimate:** 2-3 hours

**Tasks:**
1. Initialize `WarmupManager` in main() when `--warmup` flag set
2. Apply warmup overrides at start of each iteration:
   ```python
   if warmup_manager:
       current_overrides = warmup_manager.apply_warmup_overrides(
           current_overrides, iteration
       )
   ```
3. Log phase transitions
4. Pass phase info to iter_watcher

**Files to modify:**
- `tools/soak/run.py` (main iteration loop)

---

### Step 4: Tuner Micro-Steps Integration
**Status:** NOT STARTED  
**Estimate:** 1-2 hours

**Tasks:**
1. After `iter_watcher.process_iteration()`, filter deltas:
   ```python
   if warmup_manager:
       proposed_deltas, skip_reason = warmup_manager.filter_tuner_deltas(
           proposed_deltas, iteration, max_keys=2
       )
   ```
2. Update `TUNING_REPORT` with filtered deltas
3. Track cooldown state

**Files to modify:**
- `tools/soak/run.py` (after iter_watcher call)

---

### Step 5: Adaptive KPI Gate
**Status:** NOT STARTED  
**Estimate:** 1 hour

**Tasks:**
1. Get gate mode from warmup_manager:
   ```python
   gate_mode = warmup_manager.get_kpi_gate_mode(iteration)
   ```
2. Pass to KPI gate logic:
   - WARN mode: log warnings but don't fail
   - NORMAL mode: standard enforcement
3. Update KPI gate output

**Files to modify:**
- `tools/soak/run.py` (KPI gate logic)
- `tools/soak/iter_watcher.py` (if gate is there)

---

### Step 6: Guards Integration
**Status:** NOT STARTED  
**Estimate:** 1 hour

**Tasks:**
1. Update velocity guard threshold:
   ```python
   velocity_threshold = warmup_manager.get_velocity_threshold(iteration)
   ```
2. Apply latency pre-buffer to spread:
   ```python
   buffer = warmup_manager.get_latency_prebuffer(iteration, current_p95)
   current_overrides['base_spread_bps_delta'] += buffer
   ```
3. Check rescue taker blocking:
   ```python
   should_block, reason = warmup_manager.should_block_rescue_taker(
       iteration, current_risk, current_p95
   )
   ```

**Files to modify:**
- `tools/soak/run.py` (guards section)
- `tools/soak/guards.py` (if velocity threshold is there)

---

### Step 7: Validation Run
**Status:** NOT STARTED  
**Estimate:** 1-2 hours (runtime: 2 hours)

**Tasks:**
1. Run 24-iteration soak with warmup:
   ```bash
   python -m tools.soak.run \
     --iterations 24 \
     --mock \
     --auto-tune \
     --warmup \
     --preset maker_bias_uplift_v1
   ```
2. Generate reports
3. Verify success criteria

---

## 📊 Success Criteria

### First 4 Iterations (Warmup)
- [ ] Status: WARN max (no FAIL)
- [ ] net_bps: ≥ 1.0 (vs -1.5 baseline)
- [ ] risk: ≤ 50% (vs 68% baseline)
- [ ] p95: ≤ 350ms

### Iterations 5-6 (Ramp-down)
- [ ] Gradual transition to baseline parameters
- [ ] Status: WARN → PASS transition

### Iterations 7-24 (Steady)
- [ ] All PASS
- [ ] Last-8 KPI targets met:
  - maker_taker ≥ 0.83
  - net_bps ≥ 2.8
  - p95 ≤ 340ms
  - risk ≤ 0.40

### Tuner Discipline
- [ ] Max 2 keys changed per iteration
- [ ] Cooldown respected (1 iteration per key)
- [ ] Velocity guard: ≤2 triggers in warmup, 0 in steady

### Guards
- [ ] No false positives
- [ ] Rescue taker blocked correctly when risk/p95 spike

---

## 📁 Files Created/Modified

### New Files
```
tools/soak/presets/warmup_conservative_v1.json   (+60 lines)
tools/soak/warmup_manager.py                     (+300 lines)
artifacts/baseline/baseline-12-maker-bias/       (snapshot)
WARMUP_RAMPDOWN_PROGRESS.md                      (this file)
```

### Modified Files
```
tools/soak/run.py                                (+10 lines, imports + CLI)
```

**Total so far:** ~370 lines

---

## 🔧 Implementation Strategy

### Minimal Invasive Approach
- Don't rewrite existing logic
- Add warmup_manager as optional wrapper
- Preserve backward compatibility (warmup is opt-in via `--warmup`)
- Use manager for filtering/adjustments, not for core logic

### Integration Points
1. **Startup:** Initialize manager, apply warmup to initial overrides
2. **Per-iteration:** Apply phase-specific overrides
3. **After tuner:** Filter deltas (micro-steps + cooldown)
4. **KPI gate:** Use phase-specific mode
5. **Guards:** Use phase-specific thresholds

---

## ⏱️ Time Estimate

| Task | Status | Estimate |
|---|---|---|
| Steps 1-2 (Done) | ✅ | - |
| Step 3: Loop integration | 🚧 | 2-3h |
| Step 4: Micro-steps | 🚧 | 1-2h |
| Step 5: KPI gate | 🚧 | 1h |
| Step 6: Guards | 🚧 | 1h |
| Step 7: Validation | 🚧 | 1-2h + 2h runtime |
| **Total remaining** | | **6-9 hours** |

---

## 🎯 Next Steps

1. **Complete integration** (steps 3-6)
2. **Run validation** (24 iterations)
3. **Compare against baseline**
4. **Document results**
5. **Create PR**

---

## 💡 Quick Start (When Complete)

```bash
# With warmup (recommended for production)
python -m tools.soak.run \
  --iterations 24 \
  --mock \
  --auto-tune \
  --warmup \
  --preset maker_bias_uplift_v1

# Without warmup (baseline for comparison)
python -m tools.soak.run \
  --iterations 24 \
  --mock \
  --auto-tune \
  --preset maker_bias_uplift_v1
```

---

**Status:** Infrastructure complete, integration pending  
**Ready for:** Continued development in next session

---

