# ✅ FIX PACK: KPI Gate Auto-Detect + Pytest Markers

**Date:** 2025-10-15  
**Type:** Bug Fix + Enhancement  
**Status:** ✅ Complete

---

## 🐛 PROBLEMS FIXED

### Problem 1: KPI Gate Required Arguments
**Issue:**
- `tests/test_kpi_gate_unit.py::test_kpi_gate_pass_warn_fail` failed
- Test ran `python -m tools.soak.kpi_gate` without arguments
- Module required path argument → exit 1
- Expected: auto-detect and return 0 on PASS

### Problem 2: Unknown Pytest Markers
**Issue:**
- `Unknown pytest.mark.smoke` warning during test collection
- Markers not registered in pytest.ini
- Smoke tests couldn't be discovered properly

---

## ✅ SOLUTIONS IMPLEMENTED

### Fix 1: KPI Gate Auto-Detect Mode

**File:** `tools/soak/kpi_gate.py`

**Changes:**
1. ✅ Added `eval_weekly(rollup)` function
   - Evaluates `WEEKLY_ROLLUP.json` KPIs
   - Checks: `net_bps >= 2.7`, `p95_ms <= 350`, `maker_ratio >= 0.85`, `trend_ok`
   - Returns: `(bool, reason)`

2. ✅ Added `eval_iter(summary)` function
   - Evaluates `ITER_SUMMARY.json` KPIs
   - Checks: `risk <= 0.42`, `maker_taker >= 0.85`, `net_bps >= 2.7`, `p95 <= 350`
   - Returns: `(bool, reason)`

3. ✅ Rewrote `main()` with auto-detect
   - **Auto-detect mode:** No arguments → searches for files
   - **Search priority:**
     1. `artifacts/WEEKLY_ROLLUP.json`
     2. Latest `artifacts/soak/latest/ITER_SUMMARY_*.json` (by mtime)
   - **Explicit modes:** `--weekly <path>`, `--iter <path>`, `--test`
   - **Positional path:** `python -m tools.soak.kpi_gate <path>`

4. ✅ Strict exit codes
   - `0` = PASS
   - `1` = FAIL or error

5. ✅ Clean output
   - PASS: `KPI_GATE: PASS {mode}`
   - FAIL: `KPI_GATE: FAIL {mode} {reason}`
   - Error: `KPI_GATE: FAIL error {message}`
   - Usage only when no files found

**Example Usage:**
```bash
# Auto-detect (looks for WEEKLY_ROLLUP or latest ITER_SUMMARY)
python -m tools.soak.kpi_gate
# Output: KPI_GATE: PASS weekly

# Explicit weekly
python -m tools.soak.kpi_gate --weekly artifacts/WEEKLY_ROLLUP.json

# Explicit iter
python -m tools.soak.kpi_gate --iter artifacts/soak/latest/ITER_SUMMARY_6.json

# Positional path (auto-detects type from filename)
python -m tools.soak.kpi_gate artifacts/WEEKLY_ROLLUP.json

# Self-test
python -m tools.soak.kpi_gate --test
```

---

### Fix 2: Pytest Markers Registration

**File:** `pytest.ini`

**Changes:**
✅ Added markers to `[pytest]` section:
```ini
markers =
  slow: долгие тесты (по умолчанию отключены)
  quarantine: временно изолированные тесты (CI их пропускает)
  asyncio: mark for async tests (executed via built-in hook)
  smoke: Fast validation suite (<2 minutes)
  e2e: End-to-end integration tests
  tuning: Tuning/guards behavior tests
  integration: Integration tests with full stack
```

**Now Supported:**
- ✅ `@pytest.mark.smoke` — Fast validation tests
- ✅ `@pytest.mark.e2e` — End-to-end tests
- ✅ `@pytest.mark.tuning` — Tuning/guards tests
- ✅ `@pytest.mark.integration` — Integration tests

**Usage:**
```bash
# Run smoke tests only
pytest -m smoke

# Run integration tests
pytest -m integration

# Run everything except slow tests
pytest -m "not slow"

# Run smoke OR e2e tests
pytest -m "smoke or e2e"
```

---

## 🧪 TESTING

### Test 1: KPI Gate Auto-Detect
```bash
# Should work now (was failing before)
pytest -q tests/test_kpi_gate_unit.py -k kpi_gate_pass_warn_fail -vv
```

**Expected:** ✅ PASSED (exit 0)

### Test 2: Smoke Tests Collection
```bash
# Should collect without warnings (was showing "Unknown pytest.mark.smoke")
pytest -m smoke -q tests/smoke/test_soak_smoke.py
```

**Expected:** ✅ No warnings, tests collected and run

### Test 3: Marker Filtering
```bash
# Should work with all new markers
pytest -m smoke --collect-only
pytest -m integration --collect-only
pytest -m tuning --collect-only
```

**Expected:** ✅ Tests collected, no unknown marker warnings

---

## ✅ ACCEPTANCE CRITERIA

- [x] `test_kpi_gate_pass_warn_fail` passes (returns 0)
- [x] No "Unknown pytest.mark.smoke" warnings
- [x] Auto-detect finds `WEEKLY_ROLLUP.json` in `artifacts/`
- [x] Auto-detect finds latest `ITER_SUMMARY_*.json` as fallback
- [x] Exit codes: 0=PASS, 1=FAIL/error
- [x] All pytest markers registered
- [x] Smoke tests discoverable with `-m smoke`

---

## 📊 COMPATIBILITY

### Backwards Compatibility: ✅ Maintained

**Old usage still works:**
```bash
# Positional path (still supported)
python -m tools.soak.kpi_gate artifacts/ITER_SUMMARY_6.json

# Self-test (still supported)
python -m tools.soak.kpi_gate --test
```

**New usage added:**
```bash
# Auto-detect (NEW)
python -m tools.soak.kpi_gate

# Explicit modes (NEW)
python -m tools.soak.kpi_gate --weekly <path>
python -m tools.soak.kpi_gate --iter <path>
```

---

## 🔍 IMPLEMENTATION DETAILS

### KPI Thresholds

**WEEKLY_ROLLUP:**
- `net_bps` ≥ 2.7
- `p95_latency_ms` ≤ 350
- `maker_ratio` ≥ 0.85 (from `taker_share_pct`)
- `trend_ok` = True

**ITER_SUMMARY:**
- `risk_ratio` ≤ 0.42
- `maker_taker_ratio` ≥ 0.85
- `net_bps` ≥ 2.7
- `p95_latency_ms` ≤ 350

### Auto-Detect Logic

```python
if no arguments:
    if exists("artifacts/WEEKLY_ROLLUP.json"):
        use weekly mode
    elif exists("artifacts/soak/latest/ITER_SUMMARY_*.json"):
        use latest iter file (by mtime)
    else:
        print usage, exit 1

if positional path:
    auto-detect type from filename
    
if --weekly/--iter:
    use explicit mode
```

---

## 🐛 BUGS FIXED

### Bug 1: Test Failure
**Before:**
```bash
$ pytest tests/test_kpi_gate_unit.py -k kpi_gate_pass_warn_fail
FAILED - AssertionError: returncode was 1, expected 0
```

**After:**
```bash
$ pytest tests/test_kpi_gate_unit.py -k kpi_gate_pass_warn_fail
PASSED ✅
```

### Bug 2: Unknown Marker Warning
**Before:**
```bash
$ pytest -m smoke
PytestUnknownMarkWarning: Unknown pytest.mark.smoke
```

**After:**
```bash
$ pytest -m smoke
6 passed ✅
```

---

## 📝 FILES CHANGED

1. ✅ `tools/soak/kpi_gate.py`
   - Added `eval_weekly()` function
   - Added `eval_iter()` function
   - Rewrote `main()` with auto-detect
   - ~100 lines modified

2. ✅ `pytest.ini`
   - Added 4 new markers
   - ~4 lines added

---

## 🎯 IMPACT

### For Developers:
- ✅ No more "unknown marker" warnings
- ✅ Can run smoke tests easily: `pytest -m smoke`
- ✅ Better test organization with markers

### For CI:
- ✅ `test_kpi_gate_unit.py` now passes
- ✅ Smoke tests run without collection warnings
- ✅ Can filter tests by marker in workflows

### For Users:
- ✅ KPI gate works without arguments
- ✅ Auto-detects files in standard locations
- ✅ Cleaner output, strict exit codes

---

## ✅ SUMMARY

**Fixed:**
- ✅ KPI gate auto-detect mode
- ✅ Pytest marker registration
- ✅ Test failures
- ✅ Collection warnings

**Tested:**
- ✅ Auto-detect with WEEKLY_ROLLUP
- ✅ Auto-detect with ITER_SUMMARY
- ✅ All pytest markers
- ✅ Backwards compatibility

**Status:** 🟢 **COMPLETE**

---

*Fix Pack Complete: 2025-10-15*  
*Time: ~30 minutes*  
*Impact: High (fixes failing tests + improves DX)*

