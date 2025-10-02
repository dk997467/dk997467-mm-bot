# 🔬 CI Deep Diagnostic Plan - Implementation Complete

**Date:** 2025-10-02  
**Status:** 🟡 DIAGNOSTIC MODE ENABLED  
**Goal:** Find root cause of persistent CI failures in `full_stack_validate.py`

---

## 🎯 Problem Statement

Despite all previous fixes (linters, timeout, secrets scanner), CI continues to fail with:
- ❌ `linters` - FAIL
- ❌ `tests_whitelist` - FAIL  
- ❌ `dry_runs` - FAIL
- ❌ `dashboards` - FAIL
- ❌ `secrets` - FAIL

This indicates a **fundamental environment issue** in the CI runner, not just configuration problems.

---

## ✅ Implemented Diagnostic Enhancements

### 📊 Step 1: Enhanced Logging in `full_stack_validate.py`

**Modified:** `tools/ci/full_stack_validate.py` → `run_step()` function

**Changes:**

#### 1.1 Pre-Execution Diagnostic (BEFORE running each step):
```python
print("=" * 80, file=sys.stderr)
print(f"[DEBUG] STARTING STEP: {label}", file=sys.stderr)
print(f"[DEBUG] Working directory: {os.getcwd()}", file=sys.stderr)
print(f"[DEBUG] Command: {' '.join(safe_cmd)}", file=sys.stderr)
print(f"[DEBUG] Timeout: {TIMEOUT_SECONDS}s", file=sys.stderr)
print(f"[DEBUG] Python executable: {sys.executable}", file=sys.stderr)
print("=" * 80, file=sys.stderr)
```

**Benefits:**
- ✅ Shows exact command being executed
- ✅ Reveals current working directory
- ✅ Confirms Python interpreter path
- ✅ Shows timeout configuration

#### 1.2 Post-Execution Diagnostic (AFTER running each step):
```python
print("=" * 80, file=sys.stderr)
print(f"[DEBUG] FINISHED STEP: {label}", file=sys.stderr)
print(f"[DEBUG] Return code: {p.returncode}", file=sys.stderr)
print(f"[DEBUG] Duration: {duration_ms}ms", file=sys.stderr)
print(f"[DEBUG] Status: {'✓ OK' if p.returncode == 0 else '✗ FAIL'}", file=sys.stderr)
print("-" * 80, file=sys.stderr)
print(f"[DEBUG] STDOUT (full output):", file=sys.stderr)
print(stdout if stdout else "(empty)", file=sys.stderr)
print("-" * 80, file=sys.stderr)
print(f"[DEBUG] STDERR (full output):", file=sys.stderr)
print(stderr if stderr else "(empty)", file=sys.stderr)
print("=" * 80, file=sys.stderr)
```

**Benefits:**
- ✅ **FULL stdout/stderr output** (not just last line summary)
- ✅ Clear success/failure indication
- ✅ Execution time tracking
- ✅ Easy to grep in CI logs

---

### 🧪 Step 2: Isolated Test Case

**Created:** `tools/ci/debug_whitelist_test.py`

**Purpose:**
- Run **ONLY** the failing `tests_whitelist` step
- Maximum verbosity (`-vv`)
- Isolated from `full_stack_validate.py` complexity
- Real-time output streaming

**Features:**
```python
# Environment diagnostics
- Print root directory
- Print working directory  
- Print Python version & executable
- Print filtered environment variables (PYTEST*, PYTHON*, PATH, etc.)
- Check if run_selected.py exists

# Execution
- Run with subprocess.run(stdout=None, stderr=None) for real-time output
- Return exit code directly
```

**Benefits:**
- ✅ Isolates problem from other validation steps
- ✅ Easier to debug than full stack validation
- ✅ Shows environment state at execution time

---

### 🔍 Step 3: CI Environment Snapshot

**Modified:** `.github/workflows/ci.yml`

**Added 3 new diagnostic steps:**

#### 3.1 Pre-Install Environment Snapshot
```yaml
- name: "[DEBUG] Environment Snapshot (Pre-Install)"
  shell: bash
  run: |
    pwd                    # Working directory
    ls -la                 # Files in workspace
    python --version       # Python version
    python -c "import sys; print('Executable:', sys.executable); print('Path:', sys.path)"
    pip --version          # Pip version
    env | sort             # All environment variables (sorted)
    df -h .                # Disk space
```

**When:** After checkout, BEFORE installing dependencies  
**Purpose:** Capture baseline CI environment

#### 3.2 Post-Install Environment Snapshot
```yaml
- name: "[DEBUG] Environment Snapshot (Post-Install)"
  shell: bash
  run: |
    pip freeze             # All installed packages with versions
    pip show pytest pytest-xdist pytest-timeout  # Pytest plugins
    echo "PYTHONPATH=${PYTHONPATH:-<not set>}"  # Python path
```

**When:** After `pip install -r requirements_ci.txt`  
**Purpose:** Verify dependencies installed correctly

#### 3.3 Isolated Whitelist Test
```yaml
- name: "[DEBUG] Run Isolated Whitelist Test"
  continue-on-error: true
  run: |
    python tools/ci/debug_whitelist_test.py
```

**When:** After post-install snapshot, BEFORE full test suite  
**Purpose:** Test the failing component in isolation  
**Note:** `continue-on-error: true` allows CI to continue even if this fails

---

## 📋 What We'll Learn from CI Logs

### From Pre-Install Snapshot:
1. **Is the workspace clean?**
   - Are there leftover files from previous runs?
   - Is `.github/workflows/` present?

2. **Is Python configured correctly?**
   - Python 3.11 as expected?
   - Correct sys.path?

3. **Are environment variables set?**
   - `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1` present?
   - `PYTHONPATH` set correctly?

### From Post-Install Snapshot:
1. **Are dependencies installed?**
   - Is `pytest` present?
   - Is `pytest-xdist` present (for `-n auto`)?
   - Version conflicts?

2. **Is PYTHONPATH correct?**
   - Can Python find `src/` module?
   - Can Python find `tools/` module?

### From Isolated Test:
1. **Does `run_selected.py` exist?**
2. **What is the exact error message?**
3. **Is it a pytest issue or environment issue?**

### From Enhanced `run_step()` Logs:
1. **Exact command being run** (reveals typos, wrong paths)
2. **Working directory** (are we in the right place?)
3. **Full stdout/stderr** (not just summary - see ACTUAL error)

---

## 🔬 Expected Diagnostic Flow

```
1. CI starts
   ↓
2. [DEBUG] Pre-Install Snapshot
   → Captures: pwd, ls -la, python --version, env
   ↓
3. Install dependencies (requirements_ci.txt)
   ↓
4. [DEBUG] Post-Install Snapshot  
   → Captures: pip freeze, pytest versions, PYTHONPATH
   ↓
5. [DEBUG] Isolated Whitelist Test
   → Runs: debug_whitelist_test.py
   → Shows: Environment vars, command, full output
   ↓
6. Run full_stack_validate.py
   → Each step now logs:
      - [DEBUG] STARTING STEP: <name>
      - [DEBUG] Command: <exact command>
      - [DEBUG] Working directory: <path>
      - [DEBUG] FINISHED STEP: <name>
      - [DEBUG] STDOUT (full output): <...>
      - [DEBUG] STDERR (full output): <...>
```

---

## 🎯 Hypothesis Checklist

Based on diagnostic data, we can confirm/reject these hypotheses:

| Hypothesis | Check Via | Likely? |
|------------|-----------|---------|
| **Missing pytest-xdist** | `pip show pytest-xdist` in post-install | 🟡 HIGH |
| **Wrong PYTHONPATH** | `env \| grep PYTHONPATH` in pre/post-install | 🟡 MEDIUM |
| **Missing src/ module** | `ls -la` + `python -c "import src"` | 🟡 MEDIUM |
| **Wrong working directory** | `[DEBUG] Working directory:` in run_step logs | 🟢 LOW |
| **File permission issues** | `ls -la` + stderr logs | 🟢 LOW |
| **Timeout too short** | `[DEBUG] Duration:` + timeout errors | 🔴 FIXED |
| **Python version mismatch** | `python --version` | 🔴 UNLIKELY |

---

## 📊 Success Criteria

After pushing these changes and reviewing CI logs, we should be able to:

1. ✅ **Identify exact error** from full stdout/stderr
2. ✅ **Confirm environment state** (packages, paths, vars)
3. ✅ **Isolate problem** (is it pytest? imports? missing files?)
4. ✅ **Formulate fix** based on concrete evidence

---

## 🚀 Next Steps

### Immediate (Now):
1. ✅ Commit diagnostic changes
2. ✅ Push to `feature/implement-audit-fixes`
3. ⏳ Trigger CI build
4. ⏳ Review CI logs with new diagnostic data

### After Reviewing Logs:
1. 📊 Analyze diagnostic output
2. 🔍 Identify root cause
3. 🛠️ Implement targeted fix
4. ✅ Verify fix in CI
5. 🧹 Remove diagnostic logging (or keep for production debugging)

---

## 📁 Modified Files (3 files)

1. **`tools/ci/full_stack_validate.py`**
   - Enhanced `run_step()` with pre/post execution diagnostics
   - Full stdout/stderr logging

2. **`tools/ci/debug_whitelist_test.py`** (NEW)
   - Isolated test case for `tests_whitelist`
   - Environment diagnostics
   - Real-time output

3. **`.github/workflows/ci.yml`**
   - Added pre-install environment snapshot
   - Added post-install environment snapshot  
   - Added isolated whitelist test step

---

## 🎓 SRE Best Practices Applied

✅ **Observability First:** Enhanced logging before attempting fixes  
✅ **Isolation:** Created minimal test case to isolate problem  
✅ **Evidence-Based:** Collect data before making hypotheses  
✅ **Non-Invasive:** Diagnostic steps don't break existing workflow  
✅ **Fail-Safe:** `continue-on-error: true` prevents blocking CI  
✅ **Comparison:** Pre vs Post snapshots reveal delta  
✅ **Full Context:** Complete stdout/stderr, not just summaries

---

## 💡 Expected Outcome

After CI run completes, we will have:

```
CI Logs:
├── Pre-Install Snapshot (baseline environment)
├── Post-Install Snapshot (verify dependencies)
├── Isolated Test Output (whitelist test in isolation)
└── Full Stack Validation (with enhanced per-step diagnostics)
    ├── [DEBUG] STARTING STEP: linters
    │   └── Command: /usr/bin/python3 -X faulthandler /home/runner/work/.../lint_*.py
    ├── [DEBUG] STDOUT (full output): <actual error here>
    ├── [DEBUG] STDERR (full output): <actual error here>
    └── ... (repeat for each step)
```

**This will give us a complete picture of:**
- What environment CI actually has
- What exact commands are being run
- What actual errors are occurring (not just "FAIL")

**Then we can implement a TARGETED fix instead of guessing.**

---

**Status:** 🟢 **READY FOR DIAGNOSTIC RUN**  
**Confidence:** 🔬 **High - we'll get actionable data**

*Prepared by: SRE Team*  
*Date: 2025-10-02*

