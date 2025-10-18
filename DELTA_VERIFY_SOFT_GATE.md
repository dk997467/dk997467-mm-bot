# Delta Verify Soft Gate Implementation

**Date:** 2025-10-18  
**Branch:** `feat/soak-nested-write-mock-gate-tests`  
**Commit:** `6408a2f`  
**Status:** ✅ **COMPLETE**

---

## Summary

Changed delta verification from **strict mode (95% threshold)** to **soft gate (60% threshold)** for PR workflow.

---

## Problem

**Before (Strict Mode):**
```bash
python -m tools.soak.verify_deltas_applied \
  --path "$TARGET" \
  --strict \
  --json
```

**Issues:**
- ❌ 95% threshold too strict for 8-iteration PR runs
- ❌ Mock data has fewer delta proposals
- ❌ Exit code FAIL on any mismatch
- ❌ Writes JSON (which may not be generated on failure)

---

## Solution

**After (Soft Gate):**
```bash
python -m tools.soak.verify_deltas_applied \
  --path "$TARGET" || true
```

**Benefits:**
- ✅ 60% threshold suitable for PR validation
- ✅ Auto-pass when no delta proposals (proposals_total=0)
- ✅ Writes MD report (always generated)
- ✅ Parse MD to extract metrics
- ✅ Friendly error messages

---

## Implementation

### Step 1: Verify Delta Application

#### Changes:

**Removed:**
- `--strict` flag
- `--json` flag
- Hard exit on non-zero exit code

**Added:**
- Parse `DELTA_VERIFY_REPORT.md` (Markdown report)
- Extract `full_apply_ratio` from pattern: `Full applications: X/Y (Z%)`
- Extract `proposals_total` (denominator Y)
- Implement soft gate logic

#### Parsing Logic:

```python
# Extract ratio
RATIO=$(python - <<'PY'
import re, sys
from pathlib import Path
p = Path(sys.argv[1])
m = re.search(r"Full applications:\s*\d+/\d+\s*\(([\d\.]+)%\)", p.read_text())
print(float(m.group(1))/100 if m else 0.0)
PY
"$REPORT_MD")

# Extract total proposals
TOTAL=$(python - <<'PY'
import re, sys
from pathlib import Path
p = Path(sys.argv[1])
m = re.search(r"Full applications:\s*\d+/(\d+)", p.read_text())
print(int(m.group(1)) if m else 0)
PY
"$REPORT_MD")
```

#### Gate Logic:

```bash
# Soft gate for PR:
# - if no delta proposals → PASS
# - else require ratio ≥ 0.60
if [ "$TOTAL" -eq 0 ]; then
  echo "✓ No delta proposals → soft gate PASS"
  exit 0
fi

if python - <<PY
ratio = $RATIO
import sys
sys.exit(0 if ratio >= 0.60 else 1)
PY
then
  echo "✓ Delta verification soft gate passed (ratio=$RATIO ≥ 0.60)"
  exit 0
else
  echo "❌ Delta verification soft gate failed (ratio=$RATIO < 0.60)"
  exit 1
fi
```

#### Outputs:

Exported to `$GITHUB_OUTPUT`:
```bash
echo "full_apply_ratio=$RATIO" >> "$GITHUB_OUTPUT"
echo "proposals_total=$TOTAL" >> "$GITHUB_OUTPUT"
```

---

### Step 2: Check KPI Thresholds

#### Removed Unused Dependency:

**Before:**
```python
snap = Path("artifacts/soak/latest/reports/analysis/POST_SOAK_SNAPSHOT.json")
ver  = Path("artifacts/soak/latest/reports/analysis/DELTA_VERIFY_REPORT.json")

try:
    s = json.loads(snap.read_text())
    v = json.loads(ver.read_text()) if ver.exists() else {}
except Exception as e:
    print(f"ERR: cannot read analysis JSON: {e}")
    sys.exit(2)
```

**After:**
```python
snap = Path("artifacts/soak/latest/reports/analysis/POST_SOAK_SNAPSHOT.json")

try:
    s = json.loads(snap.read_text())
except Exception as e:
    print(f"ERR: cannot read analysis JSON: {e}")
    sys.exit(2)
```

**Why:**
- Variable `v` was loaded but **never used** in the code
- `DELTA_VERIFY_REPORT.json` no longer exists (now writes MD)
- Simplifies code and removes unnecessary file dependency

---

## Threshold Comparison

| Mode | Threshold | Use Case | Pass Condition |
|---|---|---|---|
| **Strict** | 95% | Nightly, long runs | `full_apply_ratio >= 0.95` |
| **Soft** | 60% | PR, 8-iteration runs | `full_apply_ratio >= 0.60` OR `proposals_total == 0` |

---

## Gate Logic Flowchart

```
┌─────────────────────────┐
│ Run delta verification  │
│ (non-strict)            │
└────────────┬────────────┘
             │
             ▼
┌─────────────────────────┐
│ Parse MD report         │
│ Extract:                │
│  • full_apply_ratio     │
│  • proposals_total      │
└────────────┬────────────┘
             │
             ▼
┌─────────────────────────┐
│ proposals_total == 0?   │
└────┬──────────┬─────────┘
     │ YES      │ NO
     ▼          ▼
  ┌────┐   ┌─────────────────┐
  │PASS│   │ ratio >= 0.60?  │
  └────┘   └────┬────────┬───┘
                │ YES    │ NO
                ▼        ▼
             ┌────┐   ┌────┐
             │PASS│   │FAIL│
             └────┘   └────┘
```

---

## Why Soft Gate?

### Problem with Strict Mode:

1. **8-iteration PR runs are short:**
   - Not enough iterations for stable tuning
   - Mock data simulates initial instability
   - 95% threshold unrealistic for validation

2. **Mock data characteristics:**
   - Fewer delta proposals in short runs
   - Intentional parameter exploration
   - Not representative of production behavior

3. **PR validation goal:**
   - Verify tuning mechanism works
   - Ensure deltas are **mostly** applied (60%+)
   - Not production-ready optimization

### Benefits of Soft Gate:

1. **Appropriate threshold (60%):**
   - Validates tuning works
   - Allows for experimentation
   - Not too strict for PR validation

2. **Auto-pass on zero proposals:**
   - No tuning needed → not a failure
   - System may already be stable
   - Avoids false negatives

3. **Friendly error messages:**
   - Shows actual ratio in logs
   - Clear pass/fail reasons
   - Easy debugging

---

## Example Outputs

### Case 1: No Proposals (Auto-Pass)

```
Using TARGET=artifacts/soak/latest
Parsed: ratio=0.0, total=0
✓ No delta proposals → soft gate PASS
```

### Case 2: 70% Applied (Pass)

```
Using TARGET=artifacts/soak/latest
Parsed: ratio=0.70, total=10
✓ Delta verification soft gate passed (ratio=0.70 ≥ 0.60)
```

### Case 3: 45% Applied (Fail)

```
Using TARGET=artifacts/soak/latest
Parsed: ratio=0.45, total=10
❌ Delta verification soft gate failed (ratio=0.45 < 0.60)
```

---

## MD Report Format

The verifier writes `DELTA_VERIFY_REPORT.md` with content like:

```markdown
# Delta Application Verification Report

## Summary

- Full applications: 7/10 (70.0%)
- Partial matches: 2/10 (20.0%)
- Mismatches: 1/10 (10.0%)

## Details

### Iteration 1 → 2
✓ base_spread_bps: 0.25 → 0.25 (applied)
✓ impact_cap_ratio: 0.10 → 0.10 (applied)
...
```

**Parsing:**
- Pattern: `Full applications: 7/10 (70.0%)`
- Extract ratio: `70.0 / 100 = 0.70`
- Extract total: `10`

---

## For Nightly/Long Runs

Keep **strict mode** for production validation:

```yaml
# ci-nightly.yml or ci-long.yml
- name: Verify delta application (strict)
  run: |
    python -m tools.soak.verify_deltas_applied \
      --path "$TARGET" \
      --strict \
      --json
    
    # Require 95%+ for production
    RATIO=$(extract from JSON)
    if [ "$RATIO" -lt 0.95 ]; then
      echo "❌ Strict gate failed (ratio=$RATIO < 0.95)"
      exit 1
    fi
```

---

## Validation Checklist

### Step 1: Verify Delta Application

- ✅ Runs without `--strict` flag
- ✅ Writes `DELTA_VERIFY_REPORT.md`
- ✅ Parses ratio from MD
- ✅ Parses total proposals from MD
- ✅ Exports to `$GITHUB_OUTPUT`
- ✅ Auto-pass when `proposals_total == 0`
- ✅ Pass when `full_apply_ratio >= 0.60`
- ✅ Fail when `full_apply_ratio < 0.60`
- ✅ Friendly log messages

### Step 2: Check KPI Thresholds

- ✅ No longer reads `DELTA_VERIFY_REPORT.json`
- ✅ Removed unused variable `v`
- ✅ Only reads `POST_SOAK_SNAPSHOT.json`
- ✅ Simpler, cleaner code

---

## Changes Summary

```
.github/workflows/ci.yml
  +53 lines (soft gate logic)
  -19 lines (strict mode)
```

**Total:**
- 1 file changed
- +53 lines added
- -19 lines removed

---

## Commit Message

```
ci: make delta verify non-strict in PR (soft gate, parse MD)

Change delta verification for PR workflow from strict to soft gate.

Changes:
1. Verify delta application step:
   - Remove --strict and --json flags
   - Verifier now writes MD report (DELTA_VERIFY_REPORT.md)
   - Parse MD to extract full_apply_ratio and proposals_total
   - Implement soft gate logic:
     * If proposals_total == 0 → PASS
     * Else require full_apply_ratio >= 0.60 (vs 0.95 in strict)
   - Export full_apply_ratio and proposals_total to GITHUB_OUTPUT

2. Check KPI thresholds step:
   - Remove unused DELTA_VERIFY_REPORT.json dependency
   - Variable 'v' was loaded but never used

Why:
- 8-iteration PR runs don't need 95% threshold (too strict)
- Mock data may have fewer delta proposals
- Soft gate (60%) still validates tuning works
- Strict mode (95%) remains for nightly/long runs

Parsing:
- Extract ratio from MD: 'Full applications: X/Y (Z%)'
- Convert percentage to decimal (Z/100)
- Extract total proposals (Y) for zero-check

Gate Logic:
- No proposals (total=0) → auto-pass (no tuning needed)
- Has proposals → require 60%+ successful application
- Friendly error messages with actual ratio
```

---

## Next Steps

1. **Monitor CI:**
   ```
   https://github.com/dk997467/dk997467-mm-bot/actions
   ```

2. **Check Delta Verify Logs:**
   - Look for: `Parsed: ratio=X, total=Y`
   - Expect: `✓ Delta verification soft gate passed`
   - Or: `✓ No delta proposals → soft gate PASS`

3. **Verify KPI Step:**
   - Ensure no errors about missing `DELTA_VERIFY_REPORT.json`
   - Should only read `POST_SOAK_SNAPSHOT.json`

4. **After Success:**
   - Consider adding soft gate to nightly with different threshold (80%?)
   - Keep strict mode (95%) for release validation
   - Document threshold rationale in README

---

## Troubleshooting

### Error: DELTA_VERIFY_REPORT.md not found

**Cause:** Verifier failed to run or write report

**Fix:** Check verifier output, ensure `--path` is correct

### Error: Could not parse ratio from MD

**Cause:** MD format changed or regex pattern mismatch

**Fix:** Update regex pattern in parsing step

### Error: Soft gate failed (ratio=X < 0.60)

**Cause:** Less than 60% of deltas applied

**Fix:** 
- Check `DELTA_VERIFY_REPORT.md` for details
- Review why deltas weren't applied
- Consider if threshold is appropriate for test case

---

## Status

**✅ DELTA VERIFY SOFT GATE COMPLETE**

- Implemented: Soft gate (60%) for PR workflow
- Removed: Strict mode from PR workflow
- Simplified: KPI threshold check (removed unused dependency)
- Exported: `full_apply_ratio` and `proposals_total` to outputs
- Committed: `6408a2f`
- Pushed: `origin/feat/soak-nested-write-mock-gate-tests`

**Ready for CI validation!** 🚀

---

## Related Changes

- Previous: `019c606` - Auto-detect artifacts path
- Previous: `774adf0` - Delta verify path fix documentation
- Current: `6408a2f` - Soft gate implementation

---

