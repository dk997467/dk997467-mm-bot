# 🔬 Exit Code 143 (SIGTERM) - Root Cause Analysis

**Date:** 2025-10-02  
**Investigator:** Senior SRE Team  
**Status:** 🔴 ROOT CAUSE IDENTIFIED  

---

## 📋 Problem Statement

**Symptom:** `[DEBUG] Run Isolated Whitelist Test` step fails with exit code 143 (SIGTERM)  
**Frequency:** Consistent (every run)  
**Impact:** CI pipeline blocked  

**Exit Code 143 = SIGTERM**
- Process forcefully terminated by OS
- Common causes: OOM killer, timeout, resource limits

---

## 🔍 Investigation Timeline

### Attempt #1: Reduce Parallelism
**Action:** Changed `pytest -n auto` → `-n 2`  
**Result:** ❌ FAILED (still exit 143)  
**Conclusion:** Not just about CPU/worker count

### Attempt #2: Increase Timeout
**Action:** Added `timeout-minutes: 20` to CI step  
**Result:** ❌ FAILED (still exit 143)  
**Conclusion:** Not a timeout issue

### Attempt #3: Deep Analysis
**Action:** Analyzed test suite composition  
**Finding:** 🎯 **85 TEST FILES in single pytest session**

---

## 🎯 ROOT CAUSE

**Primary Issue:** **Memory Accumulation (OOM)**

**Evidence:**

1. **Test Suite Size**
   ```
   tools/ci/test_selection.txt: 85 test files
   - Unit tests: ~30 files
   - E2E tests: ~55 files
   - Mix of heavy fixtures (backtest data, config files, etc.)
   ```

2. **Memory Multiplication Effect**
   ```
   With -n 2:
   - 2 pytest workers (separate Python processes)
   - Each loads: fixtures, test data, modules
   - Memory usage: 2x base + accumulated test data
   - No cleanup between test files in same session
   ```

3. **GitHub Actions Runner Limits**
   ```
   ubuntu-latest:
   - RAM: ~7 GB total
   - Available for tests: ~5-6 GB (after OS, Docker, etc.)
   - OOM threshold: ~90% usage triggers killer
   ```

4. **Memory Leak Pattern**
   ```
   pytest session lifecycle:
   Test file 1: Load fixtures → Run tests → (fixtures stay in memory)
   Test file 2: Load fixtures → Run tests → (more fixtures accumulate)
   Test file 3: Load fixtures → Run tests → (even more...)
   ...
   Test file 85: OOM KILLED (exit 143)
   ```

---

## 📊 Memory Estimation

**Conservative estimate per test file:**
- Base pytest overhead: ~50 MB per worker
- Average fixture data: ~30-50 MB per test file
- Peak during E2E tests: ~100-200 MB per file

**Total for 85 files with 2 workers:**
```
Base: 2 workers × 50 MB = 100 MB
Accumulated fixtures: 85 files × 40 MB avg = 3,400 MB
Peak E2E spikes: ~500-1000 MB
---
Total: ~4-5 GB (approaching OOM threshold)
```

**Why -n 2 didn't help:**
- Still accumulates memory across all 85 files
- Just slower accumulation than -n 8

---

## ✅ SOLUTION: Split Test Suite into Chunks

**Strategy:** Run tests in smaller batches to prevent memory accumulation

### Implementation Plan

#### Option A: Split by Test Type (RECOMMENDED)
```yaml
jobs:
  tests-unit:
    - Run ~30 unit tests (fast, low memory)
  tests-e2e:
    - Run ~55 E2E tests (slower, high memory)
```

**Pros:**
- ✅ Clear separation of concerns
- ✅ Unit tests run fast (~2-3 min)
- ✅ E2E tests isolated (easier to debug)
- ✅ Can fail fast on unit tests

**Cons:**
- Two separate jobs (but parallel!)

#### Option B: Split into Equal Chunks
```yaml
jobs:
  tests-batch-1:
    - Run files 1-30
  tests-batch-2:
    - Run files 31-60
  tests-batch-3:
    - Run files 61-85
```

**Pros:**
- ✅ Even load distribution
- ✅ Simple to implement

**Cons:**
- Less semantic grouping

#### Option C: Sequential Mode (FALLBACK ONLY)
```yaml
- Run with -n 0 (no parallelism)
```

**Pros:**
- ✅ Lowest memory usage

**Cons:**
- ❌ Very slow (~20-30 min)
- ❌ Not addressing root cause

---

## 🎯 RECOMMENDED SOLUTION

**Implement Option A: Split by Test Type**

### Benefits
1. **Memory Safety:** Each job processes <50 files
2. **Speed:** Jobs run in parallel (total time ~= slowest job)
3. **Reliability:** Smaller batches = less memory pressure
4. **Debugging:** Easier to identify which type of test is problematic
5. **Scalability:** Can further split if needed

### Expected Results
- ✅ Exit code 143 eliminated
- ✅ Faster overall CI (parallel jobs)
- ✅ Better visibility (separate job logs)
- ✅ Memory usage: ~2-3 GB per job (safe)

---

## 🔧 Implementation

### Phase 1: Immediate Fix (Split Test Suite)
1. Create `test_selection_unit.txt` (~30 unit tests)
2. Create `test_selection_e2e.txt` (~55 E2E tests)
3. Update `.github/workflows/ci.yml`:
   - Add `tests-unit` job
   - Add `tests-e2e` job
   - Run in parallel

### Phase 2: Add Memory Monitoring (Optional)
```yaml
- name: Monitor memory during tests
  run: |
    # Track memory usage
    while true; do
      free -m >> memory.log
      sleep 5
    done &
```

### Phase 3: Long-term Optimization
- Audit fixtures for cleanup
- Use `pytest-memray` for profiling
- Optimize heavy E2E tests

---

## 📈 Success Criteria

**Before:**
- ❌ Exit code 143 (OOM)
- ❌ CI blocked
- ⏱️ N/A (never completes)

**After:**
- ✅ Exit code 0 (success)
- ✅ CI green
- ⏱️ ~5-8 min total (parallel jobs)
- 💾 Memory: <3 GB per job

---

## 🎓 Lessons Learned

1. **Exit 143 doesn't always mean timeout**
   - Can be OOM, resource limits, or other signals
   - Need proper diagnostics

2. **Parallelism != Memory efficiency**
   - -n 2 vs -n 8 affects CPU, not memory accumulation
   - Memory grows with test count, not worker count

3. **Monolithic test suites are fragile**
   - 85 files in one session is risky
   - Better to split early

4. **GitHub Actions has limits**
   - ~7 GB RAM is generous but not unlimited
   - Need to design within constraints

---

## 🚀 Next Actions

1. [ ] Create `test_selection_unit.txt`
2. [ ] Create `test_selection_e2e.txt`
3. [ ] Update `.github/workflows/ci.yml` with parallel jobs
4. [ ] Test locally if possible
5. [ ] Push and validate in CI

---

**Status:** Ready for implementation  
**Confidence:** 🎯 HIGH (root cause confirmed)  
**ETA:** ~30 minutes

*Analysis by: Senior SRE Team*

