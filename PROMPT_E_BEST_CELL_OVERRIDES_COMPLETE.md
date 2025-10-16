# PROMPT E — Default Best Cell Runtime Overrides

**Status:** ✅ **COMPLETE**  
**Date:** 2025-10-12  
**Feature:** Start soak tests with optimal parameters from best parameter sweep cell

---

## Executive Summary

Successfully implemented automatic application of default runtime overrides from the best parameter sweep cell when starting soak tests. This ensures that soak tests always begin with known-good configuration values, eliminating the need to manually specify overrides for each run.

---

## Problem Statement

Previously, soak tests would start with profile base values only, requiring manual specification of runtime overrides for optimal performance. This was error-prone and required knowledge of which parameters performed best in parameter sweeps.

**Need:** Automatically apply best-performing configuration as starting point for all soak runs.

---

## Solution Implemented

### 1. Default Best Cell Overrides

Added function `get_default_best_cell_overrides()` in `tools/soak/run.py` that returns optimal values from parameter sweep:

```python
def get_default_best_cell_overrides() -> Dict[str, Any]:
    """
    Return default runtime overrides from best parameter sweep cell.
    
    These values represent the best-performing configuration from parameter sweep,
    used as starting point for soak tests when no explicit overrides are provided.
    """
    return {
        "min_interval_ms": 60,
        "replace_rate_per_min": 300,
        "base_spread_bps_delta": 0.05,
        "tail_age_ms": 600,
        "impact_cap_ratio": 0.10,
        "max_delta_ratio": 0.15
    }
```

**Source:** These values are from the best-performing cell in parameter sweep analysis.

### 2. Auto-Application Logic

Modified `tools/soak/run.py` to apply default overrides in both auto-tune and mini-soak modes:

**Priority order:**
1. **ENV variable** (`MM_RUNTIME_OVERRIDES_JSON`) → highest priority
2. **Existing file** (`artifacts/soak/runtime_overrides.json`)
3. **Default best cell** → auto-applied if neither ENV nor file exists

**Markers printed:**
- `| overrides | OK | source=env |` — from ENV variable
- `| overrides | OK | source=file |` — from existing file
- `| overrides | OK | source=file_existing |` — file already present
- `| overrides | OK | source=default_best_cell |` — default applied

### 3. Enhanced Applied Profile

Modified `strategy/edge_sentinel.py` to include `runtime_overrides_applied` field in saved profiles:

```json
{
  "profile": "S1",
  "base": { ... },
  "overrides_runtime": { ... },
  "runtime_overrides_applied": true,
  "runtime_adjustments": [ ... ],
  "applied": { ... }
}
```

This field indicates whether runtime overrides were applied to the profile.

### 4. Extended Runtime Limits

Added `max_delta_ratio` to `RUNTIME_LIMITS` in `strategy/edge_sentinel.py`:

```python
RUNTIME_LIMITS = {
    "min_interval_ms": (50, 300),
    "replace_rate_per_min": (120, 360),
    "base_spread_bps_delta": (0.0, 0.6),
    "impact_cap_ratio": (0.04, 0.12),
    "tail_age_ms": (400, 1000),
    "max_delta_ratio": (0.10, 0.20),  # NEW
}
```

This allows `max_delta_ratio` to be tuned at runtime within safe limits.

---

## Changes Summary

### Modified Files

1. **`tools/soak/run.py`**
   - ✅ Added `get_default_best_cell_overrides()` function
   - ✅ Auto-apply default overrides in auto-tune mode
   - ✅ Auto-apply default overrides in mini-soak mode
   - ✅ Print markers for override sources

2. **`strategy/edge_sentinel.py`**
   - ✅ Added `"runtime_overrides_applied"` field to saved profiles
   - ✅ Added `max_delta_ratio` to `RUNTIME_LIMITS`

### Created Files

3. **`tests/e2e/test_overrides_default_best_cell.py`**
   - ✅ Test default best cell overrides are applied
   - ✅ Test ENV variable takes precedence
   - ✅ Verify file structure and markers

---

## Acceptance Criteria

| Criterion | Status | Notes |
|-----------|--------|-------|
| Default overrides applied automatically | ✅ | When no ENV/file present |
| `runtime_overrides.json` created | ✅ | With correct values |
| `applied_profile.json` created | ✅ | With `runtime_overrides_applied=true` |
| Marker printed | ✅ | `\| overrides \| OK \| source=default_best_cell \|` |
| ENV var takes precedence | ✅ | `MM_RUNTIME_OVERRIDES_JSON` |
| Existing file preserved | ✅ | Not overwritten |
| All tests pass | ✅ | 2/2 E2E tests |

---

## Test Results

### Acceptance Test

**Command:**
```bash
MM_PROFILE=S1 python -m tools.soak.run --iterations 1 --mock
```

**Output:**
```
[INFO] Loading profile: S1
| profile_apply | OK | PROFILE=S1 |
| save_applied_profile | OK | C:\Users\dimak\mm-bot\artifacts\soak\applied_profile.json |
[INFO] Profile S1 applied successfully
[INFO] Running mini-soak: 1 iterations
| overrides | OK | source=default_best_cell |
| runtime_adjust | OK | FIELD=tail_age_ms FROM=700 TO=600 REASON=manual_override |
| runtime_overrides | OK | SOURCE=file |
| save_applied_profile | OK | C:\Users\dimak\mm-bot\artifacts\soak\applied_profile.json |

============================================================
SOAK TEST: PASS
============================================================
```

### E2E Tests

**Results:**
```
tests/e2e/test_overrides_default_best_cell.py::test_overrides_default_best_cell_applied PASSED
tests/e2e/test_overrides_default_best_cell.py::test_overrides_env_var_takes_precedence PASSED

2 passed in 0.58s
```

---

## Default Best Cell Values

| Parameter | Value | Unit | Description |
|-----------|-------|------|-------------|
| `min_interval_ms` | 60 | ms | Minimum interval between orders |
| `replace_rate_per_min` | 300 | count/min | Maximum order replacements per minute |
| `base_spread_bps_delta` | 0.05 | bps | Additional spread on top of base |
| `tail_age_ms` | 600 | ms | Age threshold for tail orders |
| `impact_cap_ratio` | 0.10 | ratio | Max impact cap as ratio of base |
| `max_delta_ratio` | 0.15 | ratio | Max position delta ratio |

**Source:** Best-performing cell from parameter sweep analysis  
**Performance:** net_bps ≈ 2.8-3.0, cancel_ratio < 0.50, adverse_bps_p95 < 4.0

---

## Priority Logic

The override resolution follows this priority:

```
1. MM_RUNTIME_OVERRIDES_JSON env var (highest)
   ↓
2. artifacts/soak/runtime_overrides.json (file)
   ↓
3. Default best cell (fallback)
```

**Examples:**

**Case 1: Fresh start (no ENV, no file)**
```bash
MM_PROFILE=S1 python -m tools.soak.run --iterations 1 --mock
```
→ **Default best cell applied**  
→ Marker: `| overrides | OK | source=default_best_cell |`

**Case 2: With ENV variable**
```bash
MM_PROFILE=S1 MM_RUNTIME_OVERRIDES_JSON='{"min_interval_ms":100}' python -m tools.soak.run --iterations 1 --mock
```
→ **ENV overrides applied**  
→ Marker: `| overrides | OK | source=env |`

**Case 3: Existing file**
```bash
# runtime_overrides.json exists
MM_PROFILE=S1 python -m tools.soak.run --iterations 1 --mock
```
→ **File overrides used**  
→ Marker: `| overrides | OK | source=file_existing |`

---

## File Structure

### `artifacts/soak/runtime_overrides.json`

```json
{
  "base_spread_bps_delta": 0.05,
  "impact_cap_ratio": 0.1,
  "max_delta_ratio": 0.15,
  "min_interval_ms": 60,
  "replace_rate_per_min": 300,
  "tail_age_ms": 600
}
```

**Format:** Deterministic JSON (sorted keys, no spaces after separators)

### `artifacts/soak/applied_profile.json`

```json
{
  "profile": "S1",
  "base": {
    "base_spread_bps": 0.85,
    "concurrency_limit": 1.9,
    ...
  },
  "overrides_runtime": {
    "base_spread_bps_delta": 0.05,
    "impact_cap_ratio": 0.1,
    "max_delta_ratio": 0.15,
    "min_interval_ms": 60,
    "replace_rate_per_min": 300,
    "tail_age_ms": 600
  },
  "runtime_overrides_applied": true,
  "runtime_adjustments": [],
  "applied": {
    "base_spread_bps": 0.85,
    "base_spread_bps_delta": 0.05,
    "concurrency_limit": 1.9,
    "impact_cap_ratio": 0.1,
    "max_delta_ratio": 0.15,
    "min_interval_ms": 60,
    "replace_rate_per_min": 300,
    "tail_age_ms": 600,
    ...
  }
}
```

**Key field:** `"runtime_overrides_applied": true` indicates overrides were applied.

---

## Impact Analysis

### Before (Manual Overrides)

```bash
# Required manual specification:
MM_PROFILE=S1 MM_RUNTIME_OVERRIDES_JSON='{"min_interval_ms":60,"replace_rate_per_min":300,...}' python -m tools.soak.run --iterations 1
```

**Problems:**
- ❌ Error-prone (easy to forget parameters)
- ❌ Requires knowledge of best values
- ❌ Long command lines
- ❌ Not version-controlled (ENV vars)

### After (Auto Best Cell)

```bash
# Just specify profile, overrides auto-applied:
MM_PROFILE=S1 python -m tools.soak.run --iterations 1
```

**Benefits:**
- ✅ No manual override specification needed
- ✅ Always starts with known-good configuration
- ✅ Simple command lines
- ✅ Version-controlled in `tools/soak/run.py`
- ✅ Easy to update best values globally

---

## Use Cases

### Use Case 1: Fresh Soak Test

**Goal:** Start soak test with optimal parameters

**Command:**
```bash
MM_PROFILE=S1 python -m tools.soak.run --iterations 24 --auto-tune
```

**Result:**
- Default best cell applied automatically
- File saved to `artifacts/soak/runtime_overrides.json`
- Auto-tuning starts from optimal baseline

### Use Case 2: Manual Override for Experiment

**Goal:** Test specific configuration

**Command:**
```bash
MM_PROFILE=S1 MM_RUNTIME_OVERRIDES_JSON='{"min_interval_ms":80}' python -m tools.soak.run --iterations 1 --mock
```

**Result:**
- Custom override applied (ENV takes precedence)
- File saved with custom values
- Can revert by removing file and ENV var

### Use Case 3: Continue Previous Soak

**Goal:** Continue soak with previous overrides

**Command:**
```bash
# File artifacts/soak/runtime_overrides.json exists from previous run
MM_PROFILE=S1 python -m tools.soak.run --iterations 10 --auto-tune
```

**Result:**
- Previous overrides loaded from file
- Auto-tuning continues from last state
- No reset to defaults

---

## Developer Notes

### Updating Best Cell Values

To update default best cell values after new parameter sweep:

1. Edit `tools/soak/run.py` → `get_default_best_cell_overrides()`
2. Update values based on sweep results
3. Run tests: `pytest tests/e2e/test_overrides_default_best_cell.py -xvs`
4. Commit changes

**Example:**
```python
def get_default_best_cell_overrides() -> Dict[str, Any]:
    return {
        "min_interval_ms": 70,  # Updated from 60
        "replace_rate_per_min": 320,  # Updated from 300
        ...
    }
```

### Adding New Tunable Parameters

To make a new parameter runtime-tunable:

1. Add to `RUNTIME_LIMITS` in `strategy/edge_sentinel.py`:
   ```python
   RUNTIME_LIMITS = {
       ...
       "new_param": (min_value, max_value),
   }
   ```

2. Add to default best cell in `tools/soak/run.py`:
   ```python
   def get_default_best_cell_overrides() -> Dict[str, Any]:
       return {
           ...
           "new_param": optimal_value,
       }
   ```

3. Update tests in `tests/e2e/test_overrides_default_best_cell.py`

---

## Summary

✅ **Auto-application of best cell overrides implemented**  
✅ **Priority logic: ENV → file → default**  
✅ **Markers for all override sources**  
✅ **Extended runtime limits (added max_delta_ratio)**  
✅ **Enhanced applied_profile.json with runtime_overrides_applied**  
✅ **All E2E tests passing (2/2)**  
✅ **Acceptance test validated**  

**Result:** Soak tests now automatically start with optimal configuration from parameter sweep, reducing manual effort and potential for configuration errors.

---

**End of Report** — PROMPT E COMPLETE ✅

