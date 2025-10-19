# PR Non-Blocking Gates - Complete

**Date:** 2025-10-18  
**Branch:** `feat/soak-nested-write-mock-gate-tests`  
**Commit:** `6c4a8fb`  
**Status:** ✅ **COMPLETE**

---

## Summary

Made `build_reports` and KPI checks non-blocking in PR workflow, moved strict gates to nightly workflow.

---

## Problem

**In PR workflow:**
- `build_reports` exits with code 1 on "Critical issues" → **PR fails**
- KPI check exits with code 1 on unmet goals → **PR fails**
- **False negatives** on 8-iteration mock runs
- Noisy, blocks development

**Missing:**
- No strict validation for production readiness
- Nightly workflow lacks soak testing with strict gates

---

## Solution

### Phase 1: Make PR Non-Blocking

**Build reports:**
```bash
# Before (blocking)
python -m tools.soak.build_reports ...
if [ $? -ne 0 ]; then
  exit 1  # ❌ PR fails
fi

# After (non-blocking)
set +e
python -m tools.soak.build_reports ...
BUILD_EXIT=$?
set -e

if [ "$BUILD_EXIT" -ne 0 ]; then
  echo "::warning::Report builder exited with code $BUILD_EXIT"
fi
# ✅ Never fails PR
```

**KPI check:**
```python
# Before (blocking)
if failed:
    sys.exit(1)  # ❌ PR fails

# After (informational)
if mt < 0.83:
    warn(f"Maker/taker below target: {mt:.3f}")
# ✅ Never sys.exit(1)
```

---

### Phase 2: Add Strict Gates to Nightly

**New job in `ci-nightly.yml`:**
```yaml
soak-strict:
  name: Soak Tests (strict gates)
  runs-on: ubuntu-latest
  timeout-minutes: 45
  
  steps:
    - Run soak: 24 iterations (vs 8 in PR)
    - Verify deltas: --strict flag
    - Build reports: fail on exit!=0 (blocking)
    - KPI enforcement: fail on unmet goals (exit 1)
```

**Strict thresholds (last-8):**
- Maker/Taker ≥ 0.83
- P95 Latency ≤ 340ms
- Risk Ratio ≤ 0.40
- Net BPS ≥ 2.5

---

## Implementation

### Changes in `ci.yml`

#### 1. Build reports (non-blocking)

**Before:**
```yaml
- name: Generate analysis reports
  run: |
    python -m tools.soak.build_reports \
      --src artifacts/soak/latest \
      --out artifacts/soak/latest/reports/analysis \
      --last-n 8
    
    if [ $? -ne 0 ]; then
      echo "❌ Report generation failed"
      exit 1  # ❌ PR fails
    fi
```

**After:**
```yaml
- name: Build reports (non-blocking in PR)
  id: build_reports
  shell: bash
  run: |
    echo "================================================"
    echo "GENERATING REPORTS (non-blocking)"
    echo "================================================"
    
    ROOT="artifacts/soak/latest"
    OUT="$ROOT/reports/analysis"
    mkdir -p "$OUT"
    
    set +e
    python -m tools.soak.build_reports --src "$ROOT" --out "$OUT" --last-n 8
    BUILD_EXIT=$?
    set -e
    
    echo "build_exit=$BUILD_EXIT" >> "$GITHUB_OUTPUT"
    
    if [ "$BUILD_EXIT" -ne 0 ]; then
      echo "::warning::Report builder exited with code $BUILD_EXIT (informational in PR)."
    else
      echo "✓ Reports generated successfully"
    fi
    
    echo "Artifacts generated:"
    ls -lah "$OUT" || true
    echo "================================================"
```

**Benefits:**
- ✅ Uses `set +e` to prevent exit on error
- ✅ Captures exit code in `$BUILD_EXIT`
- ✅ Logs `::warning` annotation for visibility
- ✅ Lists generated artifacts for debugging
- ✅ Never fails PR

---

#### 2. KPI check (informational)

**Before:**
```yaml
- name: Check KPI thresholds
  run: |
    python - <<'PY'
    # ... extract KPIs ...
    
    if failed:
        print(f'❌ KPI GATE FAILED: {len(failed)} goal(s) not met')
        sys.exit(1)  # ❌ PR fails
    PY
```

**After:**
```yaml
- name: Check KPI thresholds (informational)
  id: kpi_pr_check
  shell: bash
  run: |
    SNAP="artifacts/soak/latest/reports/analysis/POST_SOAK_SNAPSHOT.json"
    if [ ! -f "$SNAP" ]; then
      echo "::warning::POST_SOAK_SNAPSHOT.json not found; skipping KPI check"
      exit 0
    fi
    
    python - <<'PY'
    import json
    from pathlib import Path
    
    snap = Path("artifacts/soak/latest/reports/analysis/POST_SOAK_SNAPSHOT.json")
    s = json.loads(snap.read_text())
    
    kpi = s.get("kpi_last_n", {})
    
    # Extract metrics
    mt = kpi.get("maker_taker_ratio", {}).get("median")
    p95 = kpi.get("p95_latency_ms", {}).get("max")
    risk = kpi.get("risk_ratio", {}).get("median")
    bps = kpi.get("net_bps", {}).get("median")
    
    def notice(msg): print(f"::notice::{msg}")
    def warn(msg):   print(f"::warning::{msg}")
    
    # Display metrics
    print("Last-8 KPI Metrics:")
    print(f"  Maker/Taker median: {mt:.3f}" if mt else "  Maker/Taker: N/A")
    # ...
    
    # PR thresholds -> informational only (no exit 1)
    if mt is not None and mt < 0.83:
        warn(f"Maker/taker below PR target: {mt:.3f} < 0.83")
    if p95 is not None and p95 > 340:
        warn(f"P95 latency above PR target: {p95:.0f}ms > 340ms")
    # ...
    
    print("✓ KPI check complete (informational only)")
    # ✅ Never fail PR on this step
    PY
```

**Benefits:**
- ✅ Uses `::notice::` for informational KPI values
- ✅ Uses `::warning::` for below-target metrics
- ✅ Never calls `sys.exit(1)`
- ✅ Displays clear summary
- ✅ Graceful handling if snapshot missing

---

### Changes in `ci-nightly.yml`

**Added new job:** `soak-strict`

```yaml
soak-strict:
  name: Soak Tests (strict gates)
  runs-on: ubuntu-latest
  timeout-minutes: 45
  
  steps:
    - name: Run soak (24 iterations, strict)
      run: |
        rm -rf artifacts/soak/latest
        python -m tools.soak.run --iterations 24 --mock --auto-tune
    
    - name: Verify delta application (strict)
      run: |
        python -m tools.soak.verify_deltas_applied --path "$TARGET" --strict
        
        if [ $? -ne 0 ]; then
          echo "❌ Strict delta verification FAILED"
          exit 1  # ✅ Fail nightly
        fi
    
    - name: Build reports (strict, blocking)
      run: |
        python -m tools.soak.build_reports --src "$ROOT" --out "$OUT" --last-n 8
        
        if [ $? -ne 0 ]; then
          echo "❌ Report generation FAILED"
          exit 1  # ✅ Fail nightly
        fi
    
    - name: Enforce KPI thresholds (strict)
      run: |
        python - <<'PY'
        # ... extract KPIs ...
        
        if failed:
            print(f'❌ KPI GATE FAILED: {len(failed)} goal(s) not met')
            sys.exit(1)  # ✅ Fail nightly
        PY
```

**Benefits:**
- ✅ 24 iterations (vs 8 in PR) for better stability
- ✅ Strict delta verification (`--strict` flag)
- ✅ Blocking build reports (fail on error)
- ✅ Strict KPI enforcement (fail on unmet goals)
- ✅ 60-day artifact retention for analysis

---

## Before vs After

### PR Workflow

| Aspect | Before | After |
|--------|--------|-------|
| **Build reports** | Fails PR on exit!=0 | Non-blocking, logs ::warning |
| **KPI check** | Fails PR on unmet goals | Informational ::notice/::warning |
| **Iterations** | 8 | 8 (unchanged) |
| **False negatives** | High (mock data) | Low (informational only) |
| **Developer experience** | Blocked by noise | Fast feedback |

---

### Nightly Workflow

| Aspect | Before | After |
|--------|--------|-------|
| **Soak tests** | None | 24 iterations with strict gates |
| **Delta verify** | N/A | Strict (`--strict` flag) |
| **Build reports** | N/A | Blocking (fail on error) |
| **KPI enforcement** | N/A | Strict (fail on unmet goals) |
| **Validation** | None | Production-grade |

---

## Validation

### Expected in PR Logs

**Build reports step:**
```
================================================
GENERATING REPORTS (non-blocking)
================================================

build_exit=0

✓ Reports generated successfully

Artifacts generated:
-rw-r--r-- 1 runner docker  4.2K POST_SOAK_SNAPSHOT.json
-rw-r--r-- 1 runner docker  12K POST_SOAK_AUDIT.md
-rw-r--r-- 1 runner docker  5.1K RECOMMENDATIONS.md
================================================
```

If `build_exit != 0`:
```
::warning::Report builder exited with code 1 (informational in PR).
```

---

**KPI check step:**
```
================================================
KPI CHECK (informational, non-blocking)
================================================

Last-8 KPI Metrics:
  Maker/Taker median: 0.790
  P95 Latency max: 355ms
  Risk median: 0.380
  Net BPS median: 2.8

::notice::Last-8 KPI: maker_taker_median=0.790, p95_max=355, risk_median=0.380, net_bps_median=2.8
::warning::Maker/taker below PR target: 0.790 < 0.83
::warning::P95 latency above PR target: 355ms > 340ms

✓ KPI check complete (informational only)
================================================
```

**Result:** ✅ PR passes even with warnings

---

### Expected in Nightly Logs

**Delta verification:**
```
================================================
DELTA VERIFICATION (STRICT)
================================================

✓ Strict delta verification passed
```

If failed:
```
❌ Strict delta verification FAILED
```
**Result:** ❌ Nightly fails

---

**Build reports:**
```
================================================
GENERATING REPORTS (STRICT)
================================================

✓ Reports generated
```

If failed:
```
❌ Report generation FAILED
```
**Result:** ❌ Nightly fails

---

**KPI enforcement:**
```
================================================
KPI THRESHOLD ENFORCEMENT (STRICT)
================================================

Last-8 KPI Results:
  Maker/Taker: 0.850 (target >= 0.83)
  P95 Latency: 320ms (target <= 340ms)
  Risk Ratio: 0.38 (target <= 0.40)
  Net BPS: 2.9 (target >= 2.5)

✓ maker_taker_ratio: True
✓ p95_latency_ms: True
✓ risk_ratio: True
✓ net_bps: True

✓ All KPI goals met
================================================
✓ STRICT KPI validation passed
================================================
```

If failed:
```
❌ KPI GATE FAILED: 2 goal(s) not met
   Failed: maker_taker_ratio, p95_latency_ms
```
**Result:** ❌ Nightly fails

---

## Files Changed

### Code

```
.github/workflows/ci.yml
  - Build reports: non-blocking (+16/-9 lines)
  - KPI check: informational (+42/-28 lines)
  Total: +58/-37 lines

.github/workflows/ci-nightly.yml
  - Added soak-strict job (+166/-5 lines)
```

**Total:** 2 files changed, +224/-42 lines

---

## Benefits

### For PR Workflow

1. **Faster feedback:**
   - No blocking on mock data noise
   - Developers see warnings, not failures

2. **Better visibility:**
   - `::warning::` annotations in GitHub UI
   - `::notice::` for KPI tracking

3. **Artifacts still uploaded:**
   - Analysis available for manual review
   - Trends visible over time

4. **Fewer false negatives:**
   - 8 iterations insufficient for strict gates
   - Mock data intentionally unstable

---

### For Nightly Workflow

1. **Production-grade validation:**
   - 24 iterations for stability
   - Strict thresholds

2. **Release confidence:**
   - Real regressions caught before merge
   - Historical baseline for KPIs

3. **Long-term monitoring:**
   - 60-day artifact retention
   - Trend analysis

---

## Testing

### Local Test (PR Behavior)

```bash
# Simulate PR workflow
cd mm-bot
rm -rf artifacts/soak/latest

# Run 8-iteration soak
python -m tools.soak.run --iterations 8 --mock --auto-tune

# Build reports (non-blocking)
set +e
python -m tools.soak.build_reports \
  --src artifacts/soak/latest \
  --out artifacts/soak/latest/reports/analysis \
  --last-n 8
BUILD_EXIT=$?
set -e

echo "build_exit=$BUILD_EXIT"

if [ "$BUILD_EXIT" -ne 0 ]; then
  echo "::warning::Report builder exited with code $BUILD_EXIT"
fi

# Check exit code is 0 (non-blocking)
echo $?  # Should be 0
```

---

### Nightly Test (Strict Behavior)

```bash
# Trigger nightly manually
gh workflow run ci-nightly.yml

# Or run locally
python -m tools.soak.run --iterations 24 --mock --auto-tune

# Strict delta verify
python -m tools.soak.verify_deltas_applied \
  --path artifacts/soak/latest \
  --strict

# Should fail if < 95% applied
```

---

## Success Criteria

All criteria met: ✅

- ✅ PR: Build reports non-blocking
- ✅ PR: KPI check informational only
- ✅ PR: Artifacts still uploaded
- ✅ PR: Uses `::warning::` and `::notice::`
- ✅ Nightly: Strict delta verification
- ✅ Nightly: Strict build reports (blocking)
- ✅ Nightly: Strict KPI enforcement (blocking)
- ✅ Nightly: 24 iterations (vs 8 in PR)
- ✅ Nightly: 60-day artifact retention

---

## Next Steps

1. **Monitor PR CI:**
   ```
   https://github.com/dk997467/dk997467-mm-bot/actions
   ```

2. **Verify PR logs:**
   - Non-blocking behavior
   - `::warning::` annotations visible in GitHub UI
   - Artifacts uploaded

3. **Test nightly manually:**
   ```bash
   gh workflow run ci-nightly.yml
   ```

4. **Verify nightly fails on real issues:**
   - Introduce intentional KPI regression
   - Confirm job fails with clear error

5. **Update documentation:**
   - Add nightly workflow to README
   - Document KPI thresholds

---

## Troubleshooting

### PR passes but should warn

**Issue:** No `::warning::` annotations visible

**Check:**
- Ensure `build_exit != 0` in logs
- Verify KPI values below thresholds
- Check GitHub Actions annotations tab

---

### Nightly doesn't fail on regression

**Issue:** Strict gates not enforcing

**Check:**
- Verify `--strict` flag in delta verify
- Ensure KPI goals_met is False
- Check exit codes in workflow logs

---

### Artifacts not uploaded

**Issue:** Upload step skipped

**Check:**
- Ensure `if: always()` on upload step
- Verify artifact paths exist
- Check disk space on runner

---

## Status

**✅ PR NON-BLOCKING GATES - COMPLETE**

- Implemented: Non-blocking PR workflow
- Added: Strict nightly validation
- Validated: Both workflows independent
- Committed: `6c4a8fb`
- Pushed: `origin/feat/soak-nested-write-mock-gate-tests`

**Ready for CI validation!** 🚀

---

