# Soak Reports Chain Fix

## Overview

Fixed Windows soak workflow crashes on reports step by replacing legacy `kpi_gate` (auto-detect) with robust artifact-based chain: `build_reports → readiness_gate → write_legacy_readiness_json`.

## Problem

1. **Auto-detect fails on first iteration**: `tools.soak.kpi_gate` auto-detect breaks when ITER_SUMMARY files don't exist yet (first iteration)
2. **No first-iteration guard**: Reports steps crash when no artifacts available
3. **Hard failures on HOLD**: HOLD verdict causes workflow failure for hourly/informational runs

## Solution

### 1. Created Legacy Bridge Script

**File**: `tools/soak/ci_gates/write_legacy_readiness_json.py`

- Reads `POST_SOAK_AUDIT_SUMMARY.json` or `POST_SOAK_SNAPSHOT.json`
- Writes `artifacts/reports/readiness.json` for backward compatibility
- Handles multiple schema versions (kpi_last_n, kpi_last_8, kpi_overall)
- Graceful fallback when snapshot missing

**Usage**:
```bash
python -m tools.soak.ci_gates.write_legacy_readiness_json \
    --src artifacts/soak/latest \
    --out artifacts/reports
```

### 2. Updated Windows Soak Workflow

**File**: `.github/workflows/soak-windows.yml`

Added three new steps:

1. **Guard Step**: Checks for `ITER_SUMMARY_1.json` before running reports
   - Sets `skip_reports=true` if not found (first iteration)
   - Prevents crashes on initial iteration

2. **Readiness Gate**: Validates KPI metrics from POST_SOAK_SNAPSHOT.json
   - Uses PR-mode thresholds (0.83, 2.9, 330ms, 0.40)
   - Non-blocking (`continue-on-error: true`) for hourly runs
   - HOLD verdict = warning, not failure

3. **Legacy Bridge**: Writes `artifacts/reports/readiness.json`
   - Ensures compatibility with any legacy consumers
   - Non-critical (failures logged as warnings)

### 3. Updated Full Stack Validator

**File**: `tools/ci/full_stack_validate.py`

Replaced `run_reports()` implementation:

**Before**:
```python
result = run_step_with_retries('reports_kpi_gate', [sys.executable, '-m', 'tools.soak.kpi_gate'])
```

**After**:
```python
# Guard: Skip if no ITER_SUMMARY_1.json yet
if not iter_summary_1.exists():
    return {'name': 'reports', 'ok': True, 'details': 'SKIP: no ITER_SUMMARY yet'}

# Chain: build_reports → readiness_gate → write_legacy_readiness_json
build_reports(...)
readiness_gate(...)  # Non-blocking for hourly runs
write_legacy_readiness_json(...)
```

## Benefits

1. **No more first-iteration crashes**: Guard protection skips reports when no data available
2. **Robust artifact handling**: Uses POST_SOAK_SNAPSHOT.json instead of auto-detect
3. **Non-blocking HOLD**: Hourly runs treat HOLD as informational, not fatal
4. **Backward compatibility**: Legacy readiness.json maintained for any consumers
5. **Better observability**: Clear logging at each step

## Testing

### Local Test (PowerShell)

```powershell
# Run test script
pwsh test_soak_reports_chain.ps1
```

**Test script validates**:
- Guard protection on first iteration
- Minimal artifact creation (8 iterations)
- build_reports execution and POST_SOAK_SNAPSHOT.json generation
- readiness_gate execution (non-blocking)
- write_legacy_readiness_json execution and readiness.json output

### Manual Test Commands

```powershell
# 1. Create minimal test artifacts
New-Item -ItemType Directory -Force artifacts/soak/latest | Out-Null
Set-Content artifacts/soak/latest/ITER_SUMMARY_1.json '{}'

# 2. Build reports
python -m tools.soak.build_reports --src artifacts/soak/latest --out artifacts/soak/latest/reports/analysis --last-n 8

# 3. Readiness Gate
python -m tools.soak.ci_gates.readiness_gate --path artifacts/soak/latest --min_maker_taker 0.83 --min_edge 2.9 --max_latency 330 --max_risk 0.40

# 4. Legacy bridge
python -m tools.soak.ci_gates.write_legacy_readiness_json --src artifacts/soak/latest --out artifacts/reports
```

## Migration Notes

### Removed

- ❌ Direct calls to `python -m tools.soak.kpi_gate` in workflows
- ❌ Auto-detect mode dependency in full_stack_validate.py

### Kept

- ✅ `tools/soak/kpi_gate.py` (Python API still available)
- ✅ `tools/soak/integration_layer.py` (uses kpi_gate_check function)
- ✅ Unit tests for kpi_gate

### Legacy Consumers

If any script/workflow reads `artifacts/reports/readiness.json`, it will continue to work via the bridge script.

**Schema**:
```json
{
  "status": "ok" | "hold",
  "maker_taker_ratio": <float>,
  "net_bps": <float>,
  "p95_latency_ms": <float>,
  "risk_ratio": <float>,
  "failures": [<string>, ...]
}
```

## Workflow Changes

### Mini-Soak Mode (--iterations)

```yaml
# Before
- name: Build reports
  run: python -m tools.soak.build_reports ...

# After
- name: Guard - Skip reports if no ITER_SUMMARY yet
  run: Check for ITER_SUMMARY_1.json → set skip_reports env var

- name: Build reports
  if: env.skip_reports != 'true'
  run: python -m tools.soak.build_reports ...

- name: Readiness Gate
  if: env.skip_reports != 'true'
  continue-on-error: true
  run: python -m tools.soak.ci_gates.readiness_gate ...

- name: Write legacy readiness.json
  if: env.skip_reports != 'true'
  continue-on-error: true
  run: python -m tools.soak.ci_gates.write_legacy_readiness_json ...
```

### Legacy Mode (hourly loop)

Uses updated `full_stack_validate.py` which:
1. Guards on first iteration
2. Runs build_reports
3. Runs readiness_gate (non-blocking)
4. Writes legacy readiness.json

## Commit Messages

```
ci(windows-soak): replace kpi_gate with artifact-based readiness; guard first-iter; write legacy readiness.json

- Add guard step to skip reports when no ITER_SUMMARY_1.json (first iteration)
- Replace kpi_gate auto-detect with explicit chain: build_reports → readiness_gate
- Set readiness_gate to non-blocking (continue-on-error) for hourly runs
- Update Post-Soak Audit condition to respect skip_reports guard
```

```
feat(ci_gates): add write_legacy_readiness_json bridge

- Create tools/soak/ci_gates/write_legacy_readiness_json.py
- Reads POST_SOAK_AUDIT_SUMMARY.json or POST_SOAK_SNAPSHOT.json
- Writes artifacts/reports/readiness.json for backward compatibility
- Handles multiple schema versions (kpi_last_n, kpi_last_8, kpi_overall)
- Graceful fallback when snapshot missing
```

```
chore(ci): remove old kpi_gate auto-detect from full_stack_validate

- Replace run_reports() kpi_gate call with guarded chain
- Guard: skip if no ITER_SUMMARY_1.json yet (first iteration)
- Chain: build_reports → readiness_gate → write_legacy_readiness_json
- Readiness gate non-blocking for hourly/legacy mode (HOLD = informational)
```

## References

- **Workflows**: `.github/workflows/soak-windows.yml`
- **Scripts**:
  - `tools/soak/ci_gates/write_legacy_readiness_json.py`
  - `tools/soak/ci_gates/readiness_gate.py`
  - `tools/soak/build_reports.py`
  - `tools/ci/full_stack_validate.py`
- **Tests**: `test_soak_reports_chain.ps1`

## Next Steps

1. Run local test: `pwsh test_soak_reports_chain.ps1`
2. Trigger mini-soak CI run (6 iterations) to validate guard behavior
3. Monitor hourly soak logs for proper chain execution
4. Verify legacy readiness.json compatibility with any consumers

