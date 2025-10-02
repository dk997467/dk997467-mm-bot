# ✅ Exit Code 143 - Diagnostic Toolkit Deployed

**Date:** 2025-10-02  
**Status:** 🟡 **DIAGNOSTIC TOOLS READY**  
**Commit:** 31c7fb0  
**Next:** Run diagnostics to identify problem test(s)

---

## 🎯 Situation Summary

**Problem:** BOTH `tests-unit` and `tests-e2e` jobs fail with exit code 143 (SIGTERM)

**Critical Finding:** Issue persists even with:
- ❌ Split test suite (85 → 42+38)
- ❌ Reduced parallelism (-n 2)
- ❌ Increased timeout (20 min)
- ❌ **Sequential mode (-n 0)** ← This is KEY!

**Conclusion:** One or more individual tests consume massive memory (>4-5 GB)

---

## 🛠️ Diagnostic Tools Deployed (5 Tools)

### **1. 🔍 Batch Runner** 
**File:** `tools/ci/test_batch_runner.py`

**Purpose:** Find which BATCH of tests causes OOM

**Usage:**
```bash
# Run unit tests in batches of 3
python tools/ci/test_batch_runner.py \
  --test-file test_selection_unit.txt \
  --batch-size 3 \
  --fail-fast

# Run E2E tests in batches of 3
python tools/ci/test_batch_runner.py \
  --test-file test_selection_e2e.txt \
  --batch-size 3 \
  --fail-fast
```

**Output:**
```
BATCH RUNNER SUMMARY
Total batches: 14
Passed: 12
Failed: 2

Failed batch IDs: [5, 9]

Batch 5:
  - tests/e2e/test_backtest_end2end.py
  - tests/e2e/test_virtual_balance_flow.py
  - tests/test_param_sweep_unit.py
```

---

### **2. 🎯 Isolated Runner**
**File:** `tools/ci/test_isolated_runner.py`

**Purpose:** Find EXACT test file causing OOM (each test = separate process)

**Usage:**
```bash
# Run each unit test in isolated process
python tools/ci/test_isolated_runner.py \
  --test-file test_selection_unit.txt \
  --fail-fast

# Run each E2E test in isolated process
python tools/ci/test_isolated_runner.py \
  --test-file test_selection_e2e.txt \
  --fail-fast
```

**Output:**
```
ISOLATED RUNNER SUMMARY
Total tests: 42
Passed: 40
Failed: 2

❌ FAILED TESTS:
  - tests/e2e/test_backtest_end2end.py (exit 143)
  - tests/test_param_sweep_unit.py (exit 143)

🚨 EXIT 143 (OOM) DETECTED IN:
  - tests/e2e/test_backtest_end2end.py
  - tests/test_param_sweep_unit.py

These tests are consuming too much memory!
```

---

### **3. 🔬 Memory Diagnostic Workflow**
**File:** `.github/workflows/ci-memory-diagnostic.yml`

**Purpose:** Run diagnostics in actual CI environment with memory profiling

**How to Trigger:**
1. Go to **GitHub Actions** tab
2. Select **"CI Memory Diagnostic"** workflow
3. Click **"Run workflow"** button
4. Fill in inputs:
   - **test_file:** `test_selection_unit.txt` (or `test_selection_e2e.txt`)
   - **batch_size:** `3` (smaller = more isolated)
5. Click **"Run workflow"**

**What It Does:**
- Runs batch runner in CI
- Captures system resources (memory, disk, CPU)
- Installs pytest-memray for memory profiling
- Uploads memory profiles as artifacts
- Shows exactly which batch fails

**Output Location:**
- GitHub Actions → Workflow run → Artifacts → `memory-diagnostic-<run_id>`

---

### **4. 📋 Investigation Plan**
**File:** `CI_EXIT_143_DEEP_INVESTIGATION_PLAN.md`

**Purpose:** Step-by-step protocol for investigation

**Contents:**
- Analysis of failed attempts
- 3-Phase investigation protocol:
  - Phase 1: Identify problem tests
  - Phase 2: Analyze problem tests
  - Phase 3: Implement fixes
- Fix strategies with code examples
- Success criteria
- Timeline estimates

---

### **5. ⚙️ Memory-Optimized Pytest Config**
**File:** `pytest_memory_optimized.ini`

**Purpose:** Minimal memory pytest configuration

**How to Use:**
```bash
# Use optimized config
pytest -c pytest_memory_optimized.ini tests/

# Or in runner scripts
python -m pytest -c pytest_memory_optimized.ini -q tests/problem_test.py
```

**What It Does:**
- Disables caching (`-p no:cacheprovider`)
- Disables warnings (`-p no:warnings`)
- Minimal output (`-q`, `--tb=short`)
- No assertion rewriting (`--assert=plain`)
- **Saves ~50-100 MB per pytest session**

---

## 🚀 Immediate Action Plan (3 Steps)

### **Step 1: Run Memory Diagnostic in CI** (5 minutes)

```
1. Go to: https://github.com/<your-org>/<repo>/actions
2. Click: "CI Memory Diagnostic" workflow
3. Click: "Run workflow" (top right)
4. Input:
   - test_file: test_selection_unit.txt
   - batch_size: 3
5. Click: "Run workflow"
6. Wait: ~10-15 minutes
7. Review: Workflow logs
```

**What to Look For:**
- Which batch ID failed
- Exit code (should be 143 if OOM)
- System memory stats

---

### **Step 2: Run Isolated Runner Locally** (10 minutes)

If you have access to local environment:

```bash
# Clone repo
cd mm-bot

# Install deps
pip install -r requirements_ci.txt

# Run isolated runner on unit tests
python tools/ci/test_isolated_runner.py \
  --test-file test_selection_unit.txt \
  --fail-fast

# Wait for first failure (will stop immediately)
```

**Expected Output:**
```
[1/42] ✅ PASS - 2.3s - tests/test_throttle_unit.py
[2/42] ✅ PASS - 1.8s - tests/test_fill_models_unit.py
[3/42] ✅ PASS - 3.1s - tests/test_backtest_loader.py
...
[15/42] ❌ FAIL (exit 143) - 45.2s - tests/e2e/test_backtest_end2end.py
                                    ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
                                    FOUND THE CULPRIT!
```

---

### **Step 3: Analyze Problem Test** (15-30 minutes)

Once you've identified the problem test (e.g., `tests/e2e/test_backtest_end2end.py`):

**3.1: Code Review**

Open the test file and look for:
```python
# ❌ RED FLAGS:
- Large data loading: pd.read_csv(), np.load()
- Loops creating large objects: [obj() for _ in range(10000)]
- Missing cleanup: fixtures without `del` or `gc.collect()`
- Subprocess without termination
- In-memory databases without cleanup
```

**3.2: Memory Profiling (optional)**

```bash
# Install memray
pip install pytest-memray

# Profile the problem test
pytest --memray --memray-bin-path=problem.bin tests/e2e/test_backtest_end2end.py

# Analyze
python -m memray stats problem.bin
python -m memray flamegraph problem.bin  # Creates HTML flamegraph
```

**3.3: Implement Fix**

See `CI_EXIT_143_DEEP_INVESTIGATION_PLAN.md` for detailed fix strategies.

**Common fixes:**
```python
# Strategy A: Add explicit cleanup
def test_heavy():
    data = load_large_dataset()
    result = process(data)
    assert result
    
    # ADD THIS:
    del data, result
    import gc
    gc.collect()

# Strategy B: Use fixture cleanup
@pytest.fixture
def large_fixture():
    data = create_data()
    yield data
    # ADD THIS:
    del data
    import gc
    gc.collect()

# Strategy C: Mark as slow/skip in fast CI
@pytest.mark.memory_intensive
def test_heavy():
    ...
```

---

## 📊 Expected Timeline

| Phase | Duration | Action |
|-------|----------|--------|
| **Diagnostic** | 15-30 min | Run memory diagnostic + isolated runner |
| **Identification** | 5-10 min | Review results, identify problem test(s) |
| **Analysis** | 15-30 min | Code review, understand memory usage |
| **Fix** | 30-120 min | Implement optimization or workaround |
| **Validation** | 15-30 min | Test locally + CI verification |
| **TOTAL** | **1.5-4 hours** | From diagnosis to green CI |

---

## 🎯 Success Criteria

**Phase 1: Diagnosis Complete**
- [ ] Identified exact test(s) causing exit 143
- [ ] Confirmed via isolated runner or batch runner
- [ ] Understand memory pattern (single test vs cumulative)

**Phase 2: Fix Implemented**
- [ ] Problem test optimized OR marked to skip in fast CI
- [ ] Local tests pass without OOM
- [ ] Memory usage < 2-3 GB per test

**Phase 3: CI Green**
- [ ] Both `tests-unit` and `tests-e2e` jobs pass
- [ ] No exit 143 in any job
- [ ] Total CI time reasonable (~10-15 min)

---

## 🔮 Likely Culprits (Educated Guesses)

Based on test names, these are high-probability suspects:

**Unit Tests:**
```
tests/test_param_sweep_unit.py       # Generates many param combinations
tests/test_backtest_scorer.py        # Loads backtest data
tests/test_backtest_loader.py        # Loads test data files
```

**E2E Tests:**
```
tests/e2e/test_backtest_end2end.py           # Full backtest pipeline
tests/e2e/test_virtual_balance_flow.py       # Financial calculations
tests/e2e/test_param_sweep_e2e.py            # Parameter grid search
tests/e2e/test_backtest_determinism_*.py     # Large test datasets
```

**Why These?**
- "backtest" tests load market data (can be MBs-GBs)
- "param_sweep" generates combinations (exponential growth)
- "virtual_balance" tracks many transactions

---

## 💡 Quick Wins (If Time-Constrained)

### **Option A: Skip Heavy Tests in Fast CI**

```python
# In problem test files, add:
import pytest

@pytest.mark.slow
@pytest.mark.memory_intensive
def test_heavy_test():
    ...

# Then in CI:
pytest -m "not memory_intensive"
```

### **Option B: Run Heavy Tests Separately**

```yaml
# .github/workflows/ci.yml
jobs:
  tests-fast:
    # Run lightweight tests (5-10 min)
    
  tests-memory-intensive:
    # Run heavy tests sequentially (15-20 min)
    # Only on main branch or nightly
```

### **Option C: Use Smaller Test Data**

```python
# Instead of loading full dataset:
data = load_full_backtest_data()  # 2 GB

# Use sample:
data = load_full_backtest_data().head(1000)  # 10 MB
```

---

## 📝 Next Steps (Priority Order)

1. **🚨 CRITICAL:** Run memory diagnostic workflow (15 min)
   - Action: GitHub Actions → CI Memory Diagnostic → Run workflow
   - Input: `test_selection_unit.txt`, batch_size `3`

2. **🎯 HIGH:** Run isolated runner locally (if possible)
   - Action: `python tools/ci/test_isolated_runner.py --test-file test_selection_unit.txt --fail-fast`
   - Expected: Identifies exact problematic test

3. **🔍 MEDIUM:** Analyze identified test(s)
   - Action: Code review + memory profiling
   - Expected: Understand why memory is high

4. **🛠️ HIGH:** Implement fix
   - Action: Optimize test or mark to skip
   - Expected: Local tests pass

5. **✅ CRITICAL:** Verify in CI
   - Action: Push fix, watch CI
   - Expected: Green builds

---

## 📞 Support Resources

**Documentation:**
- `CI_EXIT_143_DEEP_INVESTIGATION_PLAN.md` - Full investigation protocol
- `CI_EXIT_143_ROOT_CAUSE_ANALYSIS.md` - Previous analysis (test splitting)
- `CI_EXIT_143_SOLUTION_SUMMARY.md` - Summary of first fix attempt

**Tools:**
- `tools/ci/test_batch_runner.py` - Batch testing
- `tools/ci/test_isolated_runner.py` - Isolated testing
- `pytest_memory_optimized.ini` - Memory-optimized pytest config

**Workflows:**
- `.github/workflows/ci-memory-diagnostic.yml` - On-demand diagnostics
- `.github/workflows/ci.yml` - Main CI (currently failing)

---

## ✅ Summary

**What We Built:**
- 5 diagnostic tools for comprehensive memory investigation
- Manual workflow for on-demand CI diagnostics
- Step-by-step investigation protocol
- Fix strategies and examples

**What You Need to Do:**
1. Run memory diagnostic workflow (NOW)
2. Identify problem test(s)
3. Optimize or mark them
4. Verify CI is green

**Expected Outcome:**
- Exact test(s) causing OOM identified
- Tests optimized or excluded from fast CI
- CI pipeline restored to green status
- Memory usage < 3 GB per job

---

**Status:** 🟢 **TOOLKIT READY**  
**Commit:** 31c7fb0  
**Branch:** feature/implement-audit-fixes  
**Action Required:** Trigger memory diagnostic workflow

**Let's find that memory hog! 🔍**

*Toolkit by: Senior SRE Team*

