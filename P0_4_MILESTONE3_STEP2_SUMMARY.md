# P0.4 Milestone 3 — Step 2: run_shadow.py (COMPLETED ✅)

**Date:** 2025-10-27  
**Goal:** Raise `tools/shadow/run_shadow.py` coverage from 0% → 35-45%

---

## ✅ Results

### Coverage Achievement
| Module | Before | After | Delta | Status |
|--------|--------|-------|-------|--------|
| `run_shadow.py` | 0% | **43%** | **+43%** | ✅ Target exceeded! |

### Tests Added (27 new test cases)
1. ✅ **`_git_sha_short` tests (3 tests)**
   - Success case with valid git output
   - Fallback to "unknown" on git errors
   - Handle empty git output

2. ✅ **`load_symbol_profile` tests (4 tests)**
   - Profile found and loaded from JSON
   - Profile file not found → empty dict
   - Symbol not in profiles → empty dict
   - Invalid JSON → empty dict (graceful fallback)

3. ✅ **`MiniLOB` tests (5 tests)**
   - Initialization with None values
   - `on_tick` updates bid/ask correctly
   - Partial tick updates (only bid, only ask, only last_qty)
   - Default size=0 when not provided in tick

4. ✅ **`ShadowSimulator._compute_p95` tests (5 tests)**
   - Empty list → 0.0
   - Single value → return value
   - Sorted values (100 elements)
   - Unsorted values
   - Small list (3 elements)
   - Negative values

5. ✅ **`ShadowSimulator._simulate_lob_fills` tests (7 tests)**
   - No ticks → zero fills
   - Incomplete LOB (no bid/ask) → skip ticks
   - Happy path with valid ticks → generates fills
   - `touch_dwell_ms` filtering
   - Volume requirement (`min_lot` + `require_volume`)
   - Determinism (fixed input → identical output)
   - Clock drift EWMA calculation

6. ✅ **`ShadowSimulator` initialization tests (3 tests)**
   - Default parameters
   - Custom parameters (exchange, symbols, profile, Redis config)
   - KPI tracking structures initialized

---

## 📊 Test Results

**Total tests:** 27 passed  
**Execution time:** 0.99s  
**Coverage:** 43% (245 statements, 140 missed)

### Covered Components (43%)
- ✅ `_git_sha_short()` — Git SHA extraction
- ✅ `load_symbol_profile()` — Profile loading with file I/O mocks
- ✅ `MiniLOB` class — LOB state management
- ✅ `ShadowSimulator._compute_p95()` — Percentile computation
- ✅ `ShadowSimulator._simulate_lob_fills()` — Core fill simulation logic
- ✅ `ShadowSimulator.__init__()` — Initialization

### Uncovered Lines (57% remaining)
- Lines 133-140: `connect_feed()` async method (Redis/WS connection)
- Lines 205-211, 217-223: Fill logic edge cases
- Lines 250-385: `simulate_iteration()` async method (requires async testing + Redis mocks)
- Lines 405-476: `run()` async loop (main orchestration)
- Lines 480-612: `main()` CLI function (argparse)
- Line 622: `if __name__ == "__main__"` block

*Async methods and CLI are lower ROI to test without major refactoring.*

---

## 🎯 Strategy Used

**Approach:** Test existing testable components without refactoring async code.

**Key techniques:**
- ✅ `unittest.mock.patch` for subprocess, file I/O, time
- ✅ `tmp_path` fixtures for file system isolation
- ✅ Determinism verification with fixed timestamps
- ✅ Edge case testing (empty inputs, invalid JSON, negative values)

**Avoided:**
- ❌ Refactoring async code (risk of breaking behavior)
- ❌ Testing Redis integration (requires Redis server + async mocks)
- ❌ Testing CLI (low ROI, complex mocking)

---

## 🎯 Impact on Overall Coverage

**Overall `tools/` coverage:** Currently **~9-10%** (estimated, Step 1 + Step 2)

---

## ✅ Step 2 Acceptance Criteria

- [x] `run_shadow.py` coverage ≥35-45% (achieved **43%**)
- [x] All new tests pass (27/27 passed)
- [x] No regressions in existing tests
- [x] Tests use mocks for time, subprocess, file I/O
- [x] Determinism verified for core logic

---

## 🚀 Next Steps (Milestone 3)

**Step 3:** `tools/chaos/soak_failover.py` (57% → 70%)  
**Step 4:** Small utilities (+1-2%)  
**Step 5:** Raise CI gate to 12%

---

**Status:** ✅ **COMPLETED**  
**Time spent:** ~20 minutes  
**Created by:** AI Assistant  
**Review:** Ready for Step 3

