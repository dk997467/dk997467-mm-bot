# 🚨 Exit Code 143 - Deep Investigation Plan

**Date:** 2025-10-02  
**Status:** 🔴 CRITICAL - Both jobs failing with exit 143  
**Investigator:** Senior SRE Team

---

## 🎯 Problem Statement

**Symptom:** BOTH `tests-unit` and `tests-e2e` jobs fail with exit code 143 (SIGTERM)  
**Severity:** CRITICAL - CI completely blocked  
**Persistence:** Issue survives ALL attempted fixes

---

## ❌ Failed Attempts (What Didn't Work)

| Attempt | Action | Result | Conclusion |
|---------|--------|--------|------------|
| 1 | Split tests (85 → 42+38) | ❌ Both jobs still fail | Not just about total count |
| 2 | Reduce parallelism (-n auto → -n 2) | ❌ Still fails | Not about worker count |
| 3 | Increase timeout (20 min) | ❌ Still fails | Not a timeout issue |
| 4 | Disable parallelism (-n 0) | ❌ Still fails | **CRITICAL FINDING** |

---

## 🔬 Critical Analysis

### **Key Finding: Exit 143 Even in Sequential Mode**

If exit 143 occurs even with `-n 0` (no parallelism), this means:

**Hypothesis A: Single Test Memory Bomb** (HIGH PROBABILITY)
- One or more tests consume >4-5 GB RAM individually
- Examples:
  - Loading huge datasets
  - Creating large in-memory structures
  - Memory leak in test fixture
  - Subprocess spawning

**Hypothesis B: Cumulative Memory Leak** (MEDIUM PROBABILITY)
- Fixtures not releasing memory between tests
- Pytest holds references to test objects
- Even sequential execution accumulates memory

**Hypothesis C: System Resource Limit** (LOW PROBABILITY)
- Not OOM but CPU time limit
- Disk I/O exhaustion
- File descriptor limit

**Hypothesis D: GitHub Actions Issue** (VERY LOW)
- Runner instability
- Network issues causing hangs

---

## 🛠️ Investigation Tools Deployed

### **1. Batch Runner** (`tools/ci/test_batch_runner.py`)

**Purpose:** Identify which GROUP of tests causes OOM

**Strategy:**
```python
# Run tests in batches of 3-5
# If batch 3 fails → problem is in those 3-5 tests
python tools/ci/test_batch_runner.py --test-file test_selection_unit.txt --batch-size 3
```

**Output:** Exact batch ID that triggers exit 143

### **2. Isolated Runner** (`tools/ci/test_isolated_runner.py`)

**Purpose:** Run EACH test in separate process for maximum isolation

**Strategy:**
```python
# Each test = new pytest process
# Memory completely freed between tests
python tools/ci/test_isolated_runner.py --test-file test_selection_unit.txt
```

**Output:** Exact test file that triggers exit 143

### **3. Memory Diagnostic Workflow** (`.github/workflows/ci-memory-diagnostic.yml`)

**Purpose:** Profile memory usage in CI environment

**Features:**
- Runs batch runner with configurable batch size
- Captures system resources before/after
- Uploads memory profiles for analysis

**Usage:**
```
GitHub Actions → CI Memory Diagnostic → Run workflow
- Test file: test_selection_unit.txt
- Batch size: 3
```

---

## 📋 Investigation Protocol

### **Phase 1: Identify Problem Tests (URGENT)**

**Step 1.1: Run Isolated Runner Locally (if possible)**
```bash
# Unit tests
python tools/ci/test_isolated_runner.py --test-file test_selection_unit.txt --fail-fast

# E2E tests
python tools/ci/test_isolated_runner.py --test-file test_selection_e2e.txt --fail-fast
```

**Expected Output:**
- If local run succeeds: GitHub Actions specific issue
- If local run fails: Identifies exact problematic test

**Step 1.2: Run Memory Diagnostic in CI**
```
Trigger: .github/workflows/ci-memory-diagnostic.yml
Input: test_selection_unit.txt, batch_size=3
```

**Expected Output:**
- Failing batch ID
- System memory stats
- Memory profiles (.bin files)

**Step 1.3: Narrow Down to Specific Test**
```bash
# If batch 5 failed (tests 13-15), run isolated on those:
python tools/ci/test_isolated_runner.py \
  --test-file <create temp file with tests 13-15> \
  --fail-fast
```

---

### **Phase 2: Analyze Problem Tests**

**Step 2.1: Manual Code Review**

For each identified problem test:
1. Check for large data loading
2. Check fixtures for cleanup
3. Check for subprocess spawning
4. Check for infinite loops or recursion

**Red Flags to Look For:**
```python
# Large data structures
data = [0] * 100_000_000  # 800 MB!

# No fixture cleanup
@pytest.fixture
def heavy_fixture():
    big_data = load_huge_dataset()
    yield big_data
    # MISSING: del big_data, gc.collect()

# Subprocess without cleanup
def test_something():
    proc = subprocess.Popen(...)
    # MISSING: proc.terminate(), proc.wait()

# Pandas/NumPy without cleanup
def test_dataframe():
    df = pd.read_csv("huge_file.csv")  # 2 GB
    # MISSING: del df, gc.collect()
```

**Step 2.2: Memory Profiling (if possible)**

```bash
# Install memray
pip install pytest-memray

# Profile specific test
pytest --memray --memray-bin-path=test.bin tests/problem_test.py

# Analyze
python -m memray stats test.bin
python -m memray flamegraph test.bin
```

---

### **Phase 3: Implement Fixes**

**Fix Strategy A: Optimize Problem Tests**

**For Large Data Tests:**
```python
# BEFORE
def test_heavy():
    data = load_huge_dataset()  # 2 GB
    result = process(data)
    assert result

# AFTER
def test_heavy():
    data = load_huge_dataset()
    result = process(data)
    assert result
    del data, result
    gc.collect()  # Force garbage collection
```

**For Fixture Tests:**
```python
# BEFORE
@pytest.fixture
def heavy_fixture():
    data = create_large_structure()
    yield data

# AFTER
@pytest.fixture
def heavy_fixture():
    data = create_large_structure()
    yield data
    del data
    gc.collect()
```

**For Subprocess Tests:**
```python
# BEFORE
def test_subprocess():
    proc = subprocess.Popen([...])
    output = proc.communicate()
    
# AFTER  
def test_subprocess():
    proc = None
    try:
        proc = subprocess.Popen([...])
        output = proc.communicate()
    finally:
        if proc:
            proc.kill()
            proc.wait()
```

**Fix Strategy B: Skip/Mark Heavy Tests**

```python
# Mark as slow/memory-intensive
@pytest.mark.slow
@pytest.mark.memory_intensive
def test_heavy():
    ...

# Then in CI:
pytest -m "not memory_intensive"  # Skip heavy tests in fast CI
```

**Fix Strategy C: Split Further**

If can't optimize, split into even smaller batches:
```yaml
jobs:
  tests-unit-batch-1:  # Tests 1-10
  tests-unit-batch-2:  # Tests 11-20
  tests-unit-batch-3:  # Tests 21-30
  # etc.
```

---

## 🎯 Immediate Actions

### **Action 1: Trigger Memory Diagnostic (NOW)**

```
1. Go to GitHub Actions
2. Select "CI Memory Diagnostic" workflow
3. Click "Run workflow"
4. Input:
   - test_file: test_selection_unit.txt
   - batch_size: 3
5. Click "Run"
```

### **Action 2: Create Suspect Test List**

Based on test names, identify likely suspects:
```
Likely heavy tests:
- test_backtest_*.py (loads backtest data)
- test_*_e2e.py (integration tests)
- test_param_sweep*.py (generates many combinations)
- test_virtual_balance*.py (financial calculations)
```

### **Action 3: Quick Manual Check**

```bash
# Check for obvious memory hogs
grep -r "pd.read_csv" tests/
grep -r "np.zeros.*[0-9]{6,}" tests/
grep -r "range(10" tests/
```

---

## 📊 Success Criteria

**Phase 1 Complete When:**
- ✅ Identified exact test(s) causing exit 143
- ✅ Confirmed via isolated runner
- ✅ Memory profile captured

**Phase 2 Complete When:**
- ✅ Understood WHY test uses too much memory
- ✅ Identified optimization strategy

**Phase 3 Complete When:**
- ✅ Tests optimized or marked appropriately
- ✅ CI runs green
- ✅ Memory usage < 3 GB per job

---

## 🚀 Estimated Timeline

- **Phase 1 (Identify):** 1-2 hours
  - Run diagnostic workflow: 15 min
  - Analyze results: 15 min
  - Narrow down to specific test: 30 min

- **Phase 2 (Analyze):** 30-60 min
  - Code review: 15 min
  - Memory profiling: 30 min

- **Phase 3 (Fix):** 1-3 hours
  - Implement optimization: 30 min - 2 hours
  - Test locally: 15 min
  - Verify in CI: 30 min

**Total:** 2.5 - 6 hours

---

## 📝 Next Steps (Priority Order)

1. ✅ **Run memory diagnostic workflow in CI** (trigger now)
2. ⏳ **Review diagnostic results** (identify failing batch)
3. ⏳ **Run isolated runner on failing batch** (find exact test)
4. ⏳ **Code review of problem test** (understand memory usage)
5. ⏳ **Implement fix** (optimize or mark/skip)
6. ⏳ **Verify fix in CI** (confirm green)

---

**Status:** 🟡 **INVESTIGATION IN PROGRESS**  
**Tools:** Ready  
**Plan:** Documented  
**Next:** Trigger diagnostic workflow

*Investigation by: Senior SRE Team*

