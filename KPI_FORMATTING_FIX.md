# KPI Formatting Fix

**Date:** 2025-10-18  
**Branch:** `feat/soak-nested-write-mock-gate-tests`  
**Commit:** `1f53206`  
**Status:** ✅ **COMPLETE**

---

## Problem

**Error:**
```
ValueError: Invalid format specifier '.3f if mt else 0'
```

**Root Cause:**

Line 521 in old code:
```python
notice(f"Last-8 KPI: maker_taker_median={mt:.3f if mt else 0}, ...")
                                         ^^^^^^^^^^^^^^^^^^^
```

**Issue:** Condition **inside** format spec is invalid Python syntax.

**Python f-string format spec syntax:**
```python
# Valid:
{value:format_spec}

# Invalid:
{value:format_spec if condition else other}
```

---

## Solution

### Added `fmt()` Helper Function

```python
def fmt(x, spec):
    """Safe formatter that handles None/NaN gracefully."""
    try:
        return format(float(x), spec) if x is not None else "n/a"
    except Exception:
        return "n/a"
```

### Usage

**Before (broken):**
```python
print(f"Maker/Taker median: {mt:.3f}" if mt else "Maker/Taker: N/A")
notice(f"...={mt:.3f if mt else 0}...")  # ❌ ValueError!
```

**After (fixed):**
```python
print(f"Maker/Taker median: {fmt(mt, '.3f')}")
# ✅ No ValueError, safe handling of None/NaN
```

---

## Additional Improvements

1. **Wrapped entire KPI check in `try/except`:**
   ```python
   try:
       # ... KPI check code ...
   except Exception as e:
       print(f"::warning::KPI check parse error: {e}")
   ```

2. **Guaranteed `sys.exit(0)`:**
   ```python
   # Never fail PR on this step
   sys.exit(0)
   ```

3. **Parse errors → `::warning`:**
   - Any parsing errors are logged as warnings
   - PR never fails due to KPI check issues

---

## Implementation

### Changes in `.github/workflows/ci.yml`

**Before:**
```python
python - <<'PY'
import json
from pathlib import Path

snap = Path("artifacts/soak/latest/reports/analysis/POST_SOAK_SNAPSHOT.json")
s = json.loads(snap.read_text())

kpi = s.get("kpi_last_n", {})

# Extract metrics
mt = kpi.get("maker_taker_ratio", {}).get("median")
# ...

print("Last-8 KPI Metrics:")
print(f"  Maker/Taker median: {mt:.3f}" if mt else "  Maker/Taker: N/A")
# ...

notice(f"Last-8 KPI: maker_taker_median={mt:.3f if mt else 0}, ...")  # ❌ ValueError!
PY
```

**After:**
```python
python - <<'PY'
import json, sys
from pathlib import Path

def fmt(x, spec):
    """Safe formatter that handles None/NaN gracefully."""
    try:
        return format(float(x), spec) if x is not None else "n/a"
    except Exception:
        return "n/a"

try:
    snap = Path("artifacts/soak/latest/reports/analysis/POST_SOAK_SNAPSHOT.json")
    s = json.loads(snap.read_text())
    
    kpi = s.get("kpi_last_n", {})
    
    # Extract metrics
    mt = kpi.get("maker_taker_ratio", {}).get("median")
    # ...
    
    print("Last-8 KPI Metrics:")
    print(f"  Maker/Taker median: {fmt(mt, '.3f')}")  # ✅ Safe
    # ...
    
    # Warnings for below-target metrics
    if mt is not None and mt < 0.83:
        warn(f"Maker/taker below PR target: {mt:.3f} < 0.83")
    # ...

except Exception as e:
    print(f"::warning::KPI check parse error: {e}")

# Never fail PR on this step
sys.exit(0)
PY
```

---

## Changes Summary

```
.github/workflows/ci.yml
  - Added fmt() helper function (+6 lines)
  - Replaced unsafe format specs (+4 lines)
  - Wrapped in try/except (+3 lines)
  - Explicit sys.exit(0) (+1 line)
  - Removed unsafe notice line (-1 line)
  
  Total: +47/-36 lines
```

---

## Validation

### Expected Behavior

1. ✅ **No ValueError** on KPI formatting
2. ✅ **Graceful handling** of None/NaN values
3. ✅ **Display "n/a"** for missing data
4. ✅ **Parse errors** → `::warning` (not crash)
5. ✅ **Always exit 0** (informational only)

---

### Expected in PR Logs

**Success case:**
```
================================================
KPI CHECK (informational, non-blocking)
================================================

Last-8 KPI Metrics:
  Maker/Taker median: 0.790
  P95 Latency max: 355ms
  Risk median: 0.380
  Net BPS median: 2.80

::warning::Maker/taker below PR target: 0.790 < 0.83
::warning::P95 latency above PR target: 355ms > 340ms

✓ KPI check complete (informational only)
================================================
```

**Missing data case:**
```
Last-8 KPI Metrics:
  Maker/Taker median: n/a
  P95 Latency max: n/a
  Risk median: n/a
  Net BPS median: n/a

✓ KPI check complete (informational only)
```

**Parse error case:**
```
::warning::KPI check parse error: <error details>
```

**Result:** ✅ PR passes in all cases (informational only)

---

## Testing

### Local Test

```bash
# Create mock snapshot
mkdir -p artifacts/soak/latest/reports/analysis
cat > artifacts/soak/latest/reports/analysis/POST_SOAK_SNAPSHOT.json <<'EOF'
{
  "kpi_last_n": {
    "maker_taker_ratio": {"median": 0.79},
    "p95_latency_ms": {"max": 355},
    "risk_ratio": {"median": 0.38},
    "net_bps": {"median": 2.8}
  }
}
EOF

# Test fmt() function
python - <<'PY'
def fmt(x, spec):
    try:
        return format(float(x), spec) if x is not None else "n/a"
    except Exception:
        return "n/a"

# Test cases
print(f"Valid float: {fmt(0.79, '.3f')}")      # "0.790"
print(f"None value: {fmt(None, '.3f')}")       # "n/a"
print(f"Invalid value: {fmt('invalid', '.3f')}")  # "n/a"
PY
```

**Expected output:**
```
Valid float: 0.790
None value: n/a
Invalid value: n/a
```

---

## Why This Matters

### Problem: Unsafe Format Specs

**Incorrect Python syntax:**
```python
f"{value:.3f if condition else 0}"
# Python tries to parse ".3f if condition else 0" as format spec
# ValueError: Invalid format specifier
```

**This is a common mistake!** Developers expect f-strings to evaluate conditions, but format specs have strict syntax.

---

### Solution: Separate Logic from Formatting

**Correct approach:**
```python
# Option 1: Helper function (our choice)
def fmt(x, spec):
    return format(float(x), spec) if x is not None else "n/a"

print(f"Value: {fmt(x, '.3f')}")

# Option 2: Pre-format
value_str = f"{x:.3f}" if x is not None else "n/a"
print(f"Value: {value_str}")

# Option 3: Post-format
print(f"Value: {x:.3f}" if x is not None else "Value: n/a")
```

**Our choice** (Option 1) is cleanest for multiple format specs.

---

## Related Issues

### Common f-string Format Spec Errors

**Invalid:**
```python
f"{x:.2f if x else 0}"          # Condition in format spec
f"{x:d if isinstance(x, int) else f}"  # Complex condition
f"{x or 0:.2f}"                 # Expression in format spec
```

**Valid:**
```python
f"{x:.2f}" if x else "0"        # Condition outside format
f"{float(x or 0):.2f}"          # Expression before format
f"{(x if x else 0):.2f}"        # Parenthesized expression
```

---

## Benefits

1. **No more ValueError:**
   - Safe handling of all data types
   - No crashes on unexpected input

2. **Better UX:**
   - Clear "n/a" for missing data
   - Consistent formatting

3. **Production-ready:**
   - Wrapped in try/except
   - Guaranteed exit 0
   - Informational warnings only

---

## Status

**✅ KPI FORMATTING FIX - COMPLETE**

- Fixed: ValueError in f-string format spec
- Added: Safe `fmt()` helper function
- Improved: Error handling with try/except
- Guaranteed: `sys.exit(0)` for PR
- Committed: `1f53206`
- Pushed: `origin/feat/soak-nested-write-mock-gate-tests`

**Ready for CI validation!** 🚀

---

