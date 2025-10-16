# FIX PACK — pytest.mark.timeout (No External Dependencies)

## Problem

```
PytestUnknownMarkWarning: Unknown pytest.mark.timeout marker
```

Tests using `@pytest.mark.timeout()` were generating warnings, and there was no actual timeout enforcement without installing external plugins like `pytest-timeout`.

## Solution

Implemented custom timeout infrastructure using Python stdlib only (no external dependencies).

### ✅ What Was Implemented

1. **Marker Registration** (`pytest.ini`)
   - Added `timeout(duration): per-test timeout in seconds` to markers list
   - Prevents "unknown marker" warnings

2. **Timeout Infrastructure** (`tests/conftest.py`)
   - `pytest_configure()` — Registers all custom markers programmatically
   - `_alarm_timeout()` — POSIX-only context manager using `signal.SIGALRM`
   - `_apply_timeout_marker()` — Autouse fixture that applies timeout to marked tests

### 🎯 Features

- **POSIX (Linux/macOS)**: Hard timeout via `SIGALRM` → raises `TimeoutError`
- **Windows**: Graceful no-op (test runs normally, could extend with threading if needed)
- **No external dependencies**: Uses only Python stdlib (`signal`, `contextlib`)
- **Clean syntax**: `@pytest.mark.timeout(60)` or `@pytest.mark.timeout(seconds=60)`

### 📝 Usage

```python
import pytest

@pytest.mark.timeout(60)
def test_fast_operation():
    """Will timeout after 60 seconds on POSIX systems."""
    ...

@pytest.mark.timeout(seconds=120)
def test_slow_operation():
    """Alternative syntax with keyword argument."""
    ...
```

### ⚙️ Technical Details

**How it works (POSIX)**:
1. Autouse fixture `_apply_timeout_marker` inspects test for `@pytest.mark.timeout`
2. Extracts timeout duration from marker args/kwargs
3. Sets up `SIGALRM` signal handler via `signal.alarm(seconds)`
4. If test exceeds timeout, `SIGALRM` fires → raises `TimeoutError`
5. Cleanup: `signal.alarm(0)` cancels alarm, restores old handler

**How it works (Windows)**:
- Detects absence of `signal.SIGALRM`
- No-op context manager (test runs without hard timeout)
- Could be extended with `threading.Timer` if needed

### ✅ Verification

**Before Fix:**
```bash
$ pytest -q tests/integration/test_config_precedence_integration.py
PytestUnknownMarkWarning: Unknown pytest.mark.timeout marker
```

**After Fix:**
```bash
$ pytest -q tests/integration/test_config_precedence_integration.py
============================== 6 passed in 2.14s ==============================
```

**No warnings, clean output!**

### 📦 Files Changed

```
tests/conftest.py     (+75 lines)
  ✅ pytest_configure() — Register markers
  ✅ _alarm_timeout() — SIGALRM context manager  
  ✅ _apply_timeout_marker — Autouse fixture

pytest.ini            (+1 line)
  ✅ Added: timeout(duration): per-test timeout in seconds
```

### 🔍 Edge Cases Handled

- ✅ No timeout marker → fixture does nothing (yield immediately)
- ✅ Zero/negative timeout → no-op
- ✅ SIGALRM unavailable (Windows) → graceful fallback
- ✅ Both positional and keyword argument syntax supported
- ✅ Old signal handler restored after test (no side effects)

### 🚀 Benefits

1. **No external dependencies** — Uses only Python stdlib
2. **Works in Linux CI** — GitHub Actions runners support SIGALRM
3. **Clean test code** — Simple decorator syntax
4. **Prevents hanging tests** — Hard timeout enforcement on POSIX
5. **Windows-safe** — Graceful no-op (no crashes)
6. **Clear error messages** — `TimeoutError: Test exceeded timeout of 60s`

### 🎯 Acceptance Criteria

- [x] No "Unknown pytest.mark.timeout" warnings
- [x] Tests with `@pytest.mark.timeout(N)` run normally
- [x] POSIX: Hard timeout enforcement (SIGALRM)
- [x] Windows: Graceful fallback (no-op)
- [x] No external dependencies added
- [x] All smoke tests pass
- [x] Integration tests pass

### 📊 Test Results

```bash
# Config precedence integration tests
$ python -m pytest tests/integration/test_config_precedence_integration.py -v
============================== 6 passed in 2.14s ==============================

# Smoke tests
$ python -m pytest -m smoke -v
# No marker warnings detected ✅
```

### 🔗 Related

- Commit: `feat(tests): Add pytest.mark.timeout support without plugins`
- Branch: `feat/soak-ci-chaos-release-toolkit`
- Context: Part of soak test stability suite (14-prompt implementation)

---

**Status:** ✅ **COMPLETE**  
**Impact:** Prevents hanging tests in CI, improves test reliability  
**Breaking:** No breaking changes  
**Dependencies:** None (stdlib only)
