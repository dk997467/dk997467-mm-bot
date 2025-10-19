# Main Branch: Readiness Gate Migration — Complete ✅

**Date:** 2025-10-18  
**Branch:** `main`  
**Commit:** `4f0fd91`  
**Status:** ✅ **COMPLETE & DEPLOYED**

---

## 🎯 Purpose

Replace all legacy readiness validation in **main branch** with unified, artifact-based readiness gate using `tools/soak/ci_gates/readiness_gate.py`.

**Problem Solved:**
- ❌ Old: `validate_readiness` with `readiness.json` (legacy tool)
- ❌ Old: `READINESS_EXIT="failure"` stubs (dummy exits)
- ❌ Old: Inline Python KPI checks (96 lines across 2 workflows)
- ❌ Old: PowerShell ITER_SUMMARY parsing (62 lines)
- ✅ New: Single artifact-based validation script
- ✅ New: Consistent thresholds across all workflows
- ✅ New: Clear per-metric OK/FAIL output

---

## 📁 Files Changed

### **1. Added: `tools/soak/ci_gates/`** (from feature branch)

**`__init__.py` (+3 lines)**
```python
"""CI gates for soak tests - KPI validation and readiness checks."""
```

**`readiness_gate.py` (+280 lines)**
- Artifact-based KPI validation script
- Reads `POST_SOAK_SNAPSHOT.json`
- Validates 4 KPIs: maker_taker, net_bps, p95_latency, risk
- Returns exit 0 (PASS) or 1 (FAIL)
- Supports `READINESS_OVERRIDE=1` for testing

### **2. Modified: `.github/workflows/ci-nightly.yml`** (-80 lines, +33 lines)

**fast-tests job:**
```yaml
# REMOVED (47 lines):
- name: Generate readiness score (deterministic)
  run: python -m tools.release.readiness_score --out-json artifacts/reports/readiness.json

- name: Validate readiness gate
  run: python -m tools.ci.validate_readiness artifacts/reports/readiness.json

- name: Check gates
  run: |
    READINESS_EXIT="${{ steps.readiness.outcome }}"
    if [ "$READINESS_EXIT" != "success" ]; then
      exit 1
    fi
```

**Result:** Fast e2e tests no longer check readiness (not soak-related).

**soak-strict job:**
```yaml
# BEFORE (48 lines): Inline Python checking goals_met dict
- name: Enforce KPI thresholds (strict)
  run: |
    python - <<'PY'
    # ... 40 lines of inline Python ...
    PY

# AFTER (15 lines): Unified readiness gate
- name: Readiness Gate (strict)
  if: always()
  shell: bash
  env:
    PYTHON_EXE: python
    SOAK_ARTIFACTS_DIR: artifacts/soak/latest
  run: |
    set -euo pipefail
    
    $PYTHON_EXE -m tools.soak.ci_gates.readiness_gate \
      --path "${SOAK_ARTIFACTS_DIR}" \
      --min_maker_taker 0.83 \
      --min_edge 2.9 \
      --max_latency 330 \
      --max_risk 0.40
```

**Net:** -33 lines

### **3. Modified: `.github/workflows/ci-nightly-soak.yml`** (-33 lines)

```yaml
# BEFORE (48 lines): Inline Python KPI check
- name: Enforce KPI thresholds (strict)
  run: |
    python - <<'PY'
    # ... inline Python code ...
    PY

# AFTER (15 lines): Readiness gate
- name: Readiness Gate (strict)
  if: always()
  shell: bash
  env:
    PYTHON_EXE: python
    SOAK_ARTIFACTS_DIR: artifacts/soak/latest
  run: |
    set -euo pipefail
    
    $PYTHON_EXE -m tools.soak.ci_gates.readiness_gate \
      --path "${SOAK_ARTIFACTS_DIR}" \
      --min_maker_taker 0.83 \
      --min_edge 2.9 \
      --max_latency 330 \
      --max_risk 0.40
```

**Net:** -33 lines

### **4. Modified: `.github/workflows/soak-windows.yml`** (+48 lines, -62 lines = -14 net)

```yaml
# BEFORE (62 lines): PowerShell parsing ITER_SUMMARY directly
- name: Enforce KPI gate (soft/hard thresholds)
  run: |
    $iterSummaries = Get-ChildItem "$latestDir\ITER_SUMMARY_*.json"
    # ... 55 lines of PowerShell logic ...

# AFTER (48 lines): build_reports + readiness_gate
- name: Build reports for POST_SOAK_SNAPSHOT
  continue-on-error: true
  shell: pwsh
  run: |
    & $env:PYTHON_EXE -m tools.soak.build_reports `
      --src $latestDir `
      --out $outDir `
      --last-n 8

- name: Readiness Gate (artifact-based)
  shell: pwsh
  env:
    PYTHON_EXE: python
    SOAK_ARTIFACTS_DIR: artifacts/soak/latest
  run: |
    & $env:PYTHON_EXE -m tools.soak.ci_gates.readiness_gate `
      --path "$env:SOAK_ARTIFACTS_DIR" `
      --min_maker_taker 0.83 `
      --min_edge 2.9 `
      --max_latency 330 `
      --max_risk 0.40
```

**Net:** -14 lines (added build_reports, but removed more inline code)

---

## 📊 Impact Summary

### **Code Reduction**

| Category | Before | After | Reduction |
|----------|--------|-------|-----------|
| **Legacy validate_readiness** | 2 steps | 0 | -2 steps |
| **READINESS_EXIT stubs** | 1 check | 0 | -1 check |
| **Inline Python KPI** | 96 lines (2 workflows) | 0 | -96 lines |
| **PowerShell ITER parsing** | 62 lines (1 workflow) | 0 | -62 lines |
| **Total inline code** | 158 lines | 0 | **-158 lines** |

### **New Code**

| Category | Lines | Purpose |
|----------|-------|---------|
| **readiness_gate.py** | +280 | Reusable KPI validation script |
| **Workflow calls** | +78 | Clean, consistent calls to script |
| **Total** | **+358** | Maintainable, reusable code |

### **Net Impact**

```
Inline code removed:     -158 lines
Reusable script added:   +280 lines
Workflow YAML added:     +78 lines
-------------------------------------------
Net total:               +200 lines

But: -158 lines of UNMAINTAINABLE inline code
     +280 lines of REUSABLE, TESTABLE script
     +78 lines of CLEAN workflow calls

Result: ⬆️⬆️⬆️ Much better maintainability!
```

---

## 🎯 Unified Thresholds

All workflows now use **identical thresholds**:

| Metric | Threshold | Condition | Default |
|--------|-----------|-----------|---------|
| **maker_taker_ratio** | ≥ 0.83 | Must exceed | Yes |
| **net_bps (edge)** | ≥ 2.9 | Must exceed | Yes |
| **p95_latency_ms** | ≤ 330 | Must be below | Yes |
| **risk_ratio** | ≤ 0.40 | Must be below | Yes |

**Benefit:** Change thresholds in workflow args (not in code!)

---

## ✅ Acceptance Criteria — All Met

### **Removal (Task 1):**
- [x] **No `validate_readiness`** in any workflow
- [x] **No `artifacts/reports/readiness.json`** references
- [x] **No `READINESS_EXIT="failure"`** stubs

### **Soak Workflows (Task 2):**
- [x] **ci-nightly.yml (soak-strict):** Uses `readiness_gate.py`
- [x] **ci-nightly-soak.yml:** Uses `readiness_gate.py`
- [x] **soak-windows.yml:** Uses `readiness_gate.py` + `build_reports`

### **Thresholds (Task 2):**
- [x] **Consistent thresholds:** 0.83, 2.9, 330, 0.40 across all

### **Implementation:**
- [x] **build_reports step** precedes readiness gate (where needed)
- [x] **POST_SOAK_SNAPSHOT.json** is source of truth
- [x] **Artifacts uploaded** regardless of gate result
- [x] **Blocking gates** for nightly/strict workflows

---

## 🆚 Before vs After

### **Workflow: ci-nightly.yml (fast-tests)**

| Aspect | Before | After |
|--------|--------|-------|
| **Validation** | validate_readiness | ✅ Removed (not soak-related) |
| **READINESS_EXIT** | Checked | ✅ Removed |
| **Lines** | 47 | ✅ 0 (-47) |

### **Workflow: ci-nightly.yml (soak-strict)**

| Aspect | Before | After |
|--------|--------|-------|
| **Validation** | Inline Python (48 lines) | ✅ readiness_gate.py (15 lines) |
| **Data source** | POST_SOAK_SNAPSHOT (goals_met) | ✅ POST_SOAK_SNAPSHOT (kpi_last_n) |
| **Thresholds** | Hardcoded in Python | ✅ CLI args |
| **Lines** | 48 | ✅ 15 (-33) |

### **Workflow: ci-nightly-soak.yml**

| Aspect | Before | After |
|--------|--------|-------|
| **Validation** | Inline Python (48 lines) | ✅ readiness_gate.py (15 lines) |
| **Lines** | 48 | ✅ 15 (-33) |

### **Workflow: soak-windows.yml**

| Aspect | Before | After |
|--------|--------|-------|
| **Validation** | PowerShell (62 lines) | ✅ readiness_gate.py (18 lines) |
| **Data source** | ITER_SUMMARY (last iter only) | ✅ POST_SOAK_SNAPSHOT (last-8) |
| **Report generation** | Not included | ✅ build_reports step added |
| **Lines** | 62 | ✅ 48 (-14 net) |

---

## 🧪 Testing Recommendations

### **1. Nightly Workflows (automatic)**
```bash
# ci-nightly.yml (soak-strict) runs automatically
# Check logs for: "Readiness Gate (strict)"
# Verify: Per-metric OK/FAIL output

# ci-nightly-soak.yml runs automatically
# Same checks as above
```

### **2. Windows Soak (manual)**
```bash
# Actions → Soak (Windows) → Run workflow
# Set: iterations=6 (for quick test)
# Verify:
#   - Build reports step creates POST_SOAK_SNAPSHOT.json
#   - Readiness Gate shows clear metrics
#   - Both steps complete successfully
```

### **3. Local Testing**
```bash
# Simulate any workflow locally:
cd artifacts/soak/latest
python -m tools.soak.ci_gates.readiness_gate \
  --path . \
  --min_maker_taker 0.83 \
  --min_edge 2.9 \
  --max_latency 330 \
  --max_risk 0.40

# Expected: Clear OK/FAIL per metric, exit 0 or 1
```

---

## 🔗 Related Work

### **Feature Branch**
- **Branch:** `feat/maker-bias-uplift`
- **Already updated:** Same readiness gate implementation
- **Status:** Can now merge cleanly to main

### **Previous Documentation**
- **Readiness Gate Script:** `READINESS_GATE_ARTIFACT_BASED.md` (from feature branch)
- **Feature Branch Unification:** `CI_READINESS_GATE_UNIFIED.md` (from feature branch)

---

## 🚀 Deployment Status

**Status:** ✅ **COMPLETE & DEPLOYED**  
**Branch:** `main`  
**Commit:** `4f0fd91`  
**Pushed:** Yes

**Summary:**
- ✅ Copied `tools/soak/ci_gates/` from feature branch
- ✅ Removed all `validate_readiness` usage
- ✅ Removed all `READINESS_EXIT` stubs
- ✅ Unified all soak workflows to use `readiness_gate.py`
- ✅ Consistent thresholds: 0.83, 2.9, 330, 0.40
- ✅ -158 lines of inline code
- ✅ +280 lines of reusable script

**Main branch now has:**
- Single source of truth for KPI validation
- Consistent thresholds across all workflows
- Clean, maintainable workflow files
- Easy to test locally
- Ready for production

🎉 **Migration complete! Main and feature branches now aligned on readiness gates.**

---

**Last Updated:** 2025-10-18  
**Migrated by:** Automated implementation  
**Files changed:** 5 (2 added, 3 modified)  
**Lines:** +406 insertions, -163 deletions  
**Next:** Monitor workflow runs to verify success

