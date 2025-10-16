# ✅ Delta-Apply Verifier — COMPLETE

## Executive Summary

Created `tools/soak/verify_deltas_applied.py` — a tool to verify that proposed parameter deltas are correctly applied between soak test iterations.

**Purpose:** Detect delta application failures, signature stuck issues, and guard-related partial applications.

---

## 🎯 Features

### 1. **Delta Application Verification**
- Compares proposed deltas (from `TUNING_REPORT.json`) with observed parameters (from `ITER_SUMMARY_*.json`)
- Detects full applications, partial applications, and failures
- Float comparison with tolerance (1e-9)

### 2. **Guard-Aware Analysis**
- Recognizes guard activations: cooldown, velocity, oscillation, freeze
- Explains partial applications when guards are active
- Distinguishes between acceptable (guarded) and problematic (unguarded) mismatches

### 3. **Signature Tracking**
- Checks if parameter signature changed after delta application
- Detects "signature stuck" events (proposed + applied but no signature change)
- Helps identify configuration bugs

### 4. **Detailed Reporting**
- Markdown report with summary table
- Per-iteration analysis: proposed keys, applied status, guards, signature change, params match
- Detailed mismatch table with proposed vs observed values
- Problematic parameters ranking
- Final verdict with metrics

### 5. **Configurable Thresholds**
- Default mode: >=90% full applications OR (>=80% + 0 signature_stuck)
- Strict mode (`--strict`): >=95% full applications
- Exit code 0 (pass) or 1 (fail)

---

## 📖 Usage

### Basic Usage
```bash
python -m tools.soak.verify_deltas_applied --path "artifacts/soak/latest"
```

### Strict Mode
```bash
python -m tools.soak.verify_deltas_applied --path "artifacts/soak/latest" --strict
```

### Output
- **Report:** `artifacts/soak/latest/DELTA_VERIFY_REPORT.md`
- **Exit Code:** 0 (pass) or 1 (fail)

---

## 📊 Report Structure

### Summary Table

| Iter (i-1 → i) | Proposed Keys | Applied | Guards | Sig Changed | Params Match | Reason |
|----------------|---------------|---------|--------|-------------|--------------|--------|
| 1 → 2 | max_delta_ratio, base_spread_bps_delta, tail_age_ms | Y | none | N | Y | full_apply |
| 2 → 3 | max_delta_ratio, base_spread_bps_delta, tail_age_ms | N | none | N | N | mismatch_no_guards |
| 3 → 4 | min_interval_ms, impact_cap_ratio, tail_age_ms | Y | cooldown_active | N | partial | partial_apply_guards: cooldown_active |

**Columns:**
- **Proposed Keys:** Parameters proposed in delta
- **Applied:** Was delta application attempted? (Y/N)
- **Guards:** Active guards preventing full application
- **Sig Changed:** Did signature change? (Y/N)
- **Params Match:** Y (full match), partial (guarded mismatch), N (unguarded mismatch)
- **Reason:** Explanation for the status

### Metrics

```
Total iteration pairs: 11
Pairs with proposed deltas: 4
Full applications: 1 (25.0%)
Partial applications: 0 (0.0%)
Failed applications: 3 (75.0%)
Signature stuck events: 3
```

### Detailed Mismatches

For each failed application:
- Parameter name
- Proposed value
- Observed value
- Delta (difference)
- Reason (not found / value mismatch)

### Problematic Parameters

Ranking of parameters with most mismatches:
```
- min_interval_ms: 2 mismatches
- impact_cap_ratio: 2 mismatches
- max_delta_ratio: 1 mismatches
```

### Verdict

```
✅ PASS - 92.0% full applications (threshold: >=90%)
```

or

```
❌ FAIL - 25.0% full applications (threshold: >=90% or >=80% with no signature_stuck)
```

---

## 🔍 Analysis Logic

### Step 1: Load Data
1. `TUNING_REPORT.json` — proposed deltas per iteration
2. `ITER_SUMMARY_*.json` — actual applied deltas per iteration

### Step 2: Analyze Pairs (i-1 → i)

For each iteration pair:

1. **Extract proposed deltas** from iteration i-1 (TUNING_REPORT)
   - Keys: `proposed_deltas` or `suggested_deltas`
   - Guards: `cooldown_active`, `velocity_violation`, `oscillation_detected`, `freeze_triggered`

2. **Extract observed params** from iteration i (ITER_SUMMARY)
   - Source: `tuning.deltas` (actual applied values)
   - Fallback: `runtime_overrides`, `runtime`, `config`

3. **Check signature change**
   - Signature from `tuning.signature` or `tuning.state_hash`
   - If proposed + applied but sig unchanged → "signature_stuck"

4. **Compare params**
   - For each proposed param: check if observed value matches
   - Tolerance: abs(diff) <= 1e-9 for floats
   - Track mismatches (not found / value diff)

5. **Determine match status**
   - **Y (full):** All params match
   - **partial:** Mismatches but guards active (acceptable)
   - **N (fail):** Mismatches and no guards (problematic)

### Step 3: Calculate Metrics

- Full applications: `params_match == "Y"`
- Partial applications: `params_match == "partial"`
- Failed applications: `params_match == "N"`
- Signature stuck: proposed + applied but no sig change

### Step 4: Determine Exit Code

**Default mode:**
- PASS if: `full_apply_pct >= 90%` OR (`full_apply_pct >= 80%` AND `signature_stuck == 0`)
- FAIL otherwise

**Strict mode (`--strict`):**
- PASS if: `full_apply_pct >= 95%`
- FAIL otherwise

---

## 🧪 Testing

### Quick Test
```bash
python tools/soak/test_verify_deltas.py
```

Creates minimal test data and verifies:
- Report generation
- Exit code logic
- Metric calculation

### Real Data Test
```bash
# Run on actual soak test results
python -m tools.soak.verify_deltas_applied --path "artifacts/soak/latest"

# Check exit code
echo $?  # 0 = pass, 1 = fail
```

---

## 📝 Data Sources

### TUNING_REPORT.json

Expected structure (list or dict with "iterations" key):

```json
[
  {
    "iteration": 1,
    "suggested_deltas": {
      "param_a": 0.5,
      "param_b": 10
    },
    "applied": true,
    "cooldown_active": false,
    "velocity_violation": false,
    "oscillation_detected": false,
    "freeze_triggered": false
  },
  ...
]
```

**Alternative key:** `proposed_deltas` instead of `suggested_deltas`

### ITER_SUMMARY_*.json

Expected structure:

```json
{
  "iteration": 1,
  "tuning": {
    "deltas": {
      "param_a": 0.5,
      "param_b": 10
    },
    "applied": true,
    "signature": "abc123",
    "state_hash": "def456"
  },
  "summary": {
    "runtime_utc": "2025-01-01T00:00:00Z"
  }
}
```

**Fallback locations for params:**
- `runtime_overrides`
- `runtime`
- `config`

---

## 🔧 Implementation Details

### Key Functions

1. **`_load_tuning_report()`**
   - Loads TUNING_REPORT.json
   - Handles both list and dict formats

2. **`_load_iter_summaries()`**
   - Loads all ITER_SUMMARY_*.json files
   - Returns dict keyed by iteration number

3. **`_analyze_iteration_pair()`**
   - Core analysis logic for one pair (i-1 → i)
   - Returns analysis dict with all metrics

4. **`_compare_params()`**
   - Compares proposed vs observed params
   - Float tolerance: 1e-9
   - Returns (all_match, mismatches)

5. **`_generate_report()`**
   - Generates Markdown report
   - Calculates metrics and verdict

6. **`verify_deltas()`**
   - Main orchestrator
   - Returns exit code

### Float Comparison

```python
FLOAT_TOLERANCE = 1e-9

# Comparison
diff = abs(proposed_val - observed_val)
if diff > FLOAT_TOLERANCE:
    # Mismatch
```

### Guard Detection

```python
guards = {
    "cooldown_active": tuning.get("cooldown_active", False),
    "velocity_violation": tuning.get("velocity_violation", False),
    "oscillation_detected": tuning.get("oscillation_detected", False),
    "freeze_triggered": tuning.get("freeze_triggered", False),
}

guard_reasons = [k for k, v in guards.items() if v]
```

---

## 💡 Use Cases

### 1. CI/CD Validation
```yaml
- name: Run soak test
  run: python -m tools.soak.run --iterations 12

- name: Verify delta applications
  run: |
    python -m tools.soak.verify_deltas_applied \
      --path artifacts/soak/latest \
      --strict
    
    # Fail CI if deltas not applied correctly
```

### 2. Post-Soak Analysis
```bash
# After soak test, check if auto-tuning worked
python -m tools.soak.verify_deltas_applied --path "artifacts/soak/latest"

# Review DELTA_VERIFY_REPORT.md for issues
```

### 3. Debug Signature Stuck
```bash
# Find iterations where signature didn't change despite deltas
python -m tools.soak.verify_deltas_applied --path "artifacts/soak/latest"

# Check "signature_stuck" rows in report
grep "signature_stuck" artifacts/soak/latest/DELTA_VERIFY_REPORT.md
```

### 4. Identify Problematic Parameters
```bash
# Run verifier
python -m tools.soak.verify_deltas_applied --path "artifacts/soak/latest"

# Check "Problematic Parameters" section in report
# These params fail to apply most often
```

---

## 🚨 Common Issues

### Issue 1: Signature Not Found
**Symptom:** All signatures are "unknown"  
**Cause:** No `tuning.signature` or `tuning.state_hash` in data  
**Impact:** Cannot detect signature_stuck  
**Fix:** Add signature computation to iter_watcher.py

### Issue 2: Parameters Not Found
**Symptom:** Many "parameter not found in runtime" errors  
**Cause:** Deltas not stored in `tuning.deltas` on next iteration  
**Impact:** False negatives (applied but not detected)  
**Fix:** Ensure live-apply writes to `tuning.deltas` in ITER_SUMMARY

### Issue 3: High False Positives
**Symptom:** Many mismatches despite guards being active  
**Cause:** Guard flags not propagated to TUNING_REPORT  
**Impact:** Incorrectly classified as "mismatch_no_guards"  
**Fix:** Ensure guard flags are written to TUNING_REPORT.json

---

## 📈 Example Output

### Successful Run (90%+ applications)

```
[OK] Report written to: artifacts/soak/latest/DELTA_VERIFY_REPORT.md

Verification Summary:
  Full applications: 9/10 (90.0%)
  Signature stuck: 0
  Threshold: >=90.0%

✅ PASS
```

### Failed Run (below threshold)

```
[OK] Report written to: artifacts/soak/latest/DELTA_VERIFY_REPORT.md

Verification Summary:
  Full applications: 1/4 (25.0%)
  Signature stuck: 3
  Threshold: >=90.0%

❌ FAIL
```

---

## 🎯 Acceptance Criteria

- [x] Loads TUNING_REPORT.json (list or dict format)
- [x] Loads ITER_SUMMARY_*.json files
- [x] Analyzes each iteration pair (i-1 → i)
- [x] Compares proposed vs observed params
- [x] Detects guard activations
- [x] Tracks signature changes
- [x] Generates Markdown report
- [x] Calculates metrics (full/partial/fail %)
- [x] Determines exit code based on threshold
- [x] Supports --strict flag (95% threshold)
- [x] Stdlib-only implementation
- [x] Deterministic output
- [x] Tested on real soak data

---

## 📦 Files

```
tools/soak/
├── verify_deltas_applied.py    (~480 lines) [NEW]
└── test_verify_deltas.py        (~100 lines) [NEW]

artifacts/soak/latest/
└── DELTA_VERIFY_REPORT.md       [GENERATED]
```

---

## 🔗 Integration with Soak Tooling

The delta verifier complements existing soak tools:

1. **analyze_post_soak.py** — Deep analysis of KPI trends, guards, anomalies
2. **extract_post_soak_snapshot.py** — Compact JSON snapshot with metadata
3. **soak_gate.py** — Unified orchestrator for analyzer + extractor
4. **verify_deltas_applied.py** — Verifies delta application correctness ✅

**Typical workflow:**
```bash
# 1. Run soak test
python -m tools.soak.run --iterations 12 --auto-tune

# 2. Generate reports
python -m tools.soak.soak_gate --path artifacts/soak/latest

# 3. Verify delta applications
python -m tools.soak.verify_deltas_applied --path artifacts/soak/latest
```

---

## 🎉 Status

**Implementation:** ✅ COMPLETE  
**Testing:** ✅ Tested on real data  
**Documentation:** ✅ Complete  
**Ready for:** Production use, CI/CD integration  

---

**Total Lines:** ~480 (verify_deltas_applied.py) + ~100 (test_verify_deltas.py) = ~580 lines  
**Dependencies:** stdlib only  
**Exit Codes:** 0 (pass), 1 (fail)  
**Output:** DELTA_VERIFY_REPORT.md

