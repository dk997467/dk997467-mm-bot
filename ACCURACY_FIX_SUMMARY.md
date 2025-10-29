# Accuracy Workflow Fix Summary

## ✅ STATUS: COMPLETED

**Branch:** `fix/ci-artifact-v4`  
**Commit:** `ab5fbb4 ci(accuracy): resolve conflicts + fix mock flag + v4 artifacts`

---

## 🔧 CHANGES APPLIED

### 1. `.github/workflows/accuracy.yml`

**Updated to clean version with:**
- ✅ Lint-step with `shell: bash` (anti-regression protection)
- ✅ All artifact actions updated to `@v4`
- ✅ Replaced deprecated `--mock` with `--source mock`
- ✅ Added `::error::` prefix for lint failures
- ✅ Simplified PR comment script
- ✅ Fixed final gate logic to use comparison exit code

**Key changes:**
```yaml
# Guard against deprecated artifact actions
- name: Lint - forbid artifact v3
  shell: bash
  run: |
    set -euo pipefail
    if git grep -nE 'actions/(upload|download)-artifact\s*[@:]\s*v3(\b|[^0-9])' .github | tee /dev/stderr; then
      echo "::error::Found deprecated artifact actions v3 — must use @v4"
      exit 1
    fi
```

```yaml
# Run Shadow Mode with --source mock (not --mock)
python -m tools.shadow.run_shadow \
  --iterations 24 \
  --duration 60 \
  --profile moderate \
  --exchange bybit \
  --source mock \
  --output artifacts/shadow/latest
```

```yaml
# Upload artifacts with v4
- name: Upload Accuracy Artifacts
  if: always()
  uses: actions/upload-artifact@v4
  with:
    name: accuracy-gate-${{ github.run_id }}
    path: |
      reports/analysis/ACCURACY_*.md
      reports/analysis/ACCURACY_*.json
      artifacts/shadow/latest/ITER_SUMMARY_*.json
      artifacts/dryrun/latest/ITER_SUMMARY_*.json
    if-no-files-found: warn
    retention-days: 30
```

### 2. `tools/shadow/run_shadow.py`

**Removed deprecated flag:**
- ❌ Deleted `--mock` flag (lines 576-581)
- ✅ Use `--source mock` instead

**Before:**
```python
# Back-compat: deprecated flag (no-op)
parser.add_argument(
    "--mock",
    action="store_true",
    help="(deprecated) no-op; use --source mock instead"
)
```

**After:**
```python
# Removed - use --source parameter instead
```

### 3. `tools/shadow/baseline_autotune.py`

**Replaced mock flag with source parameter:**

**Before:**
```python
parser.add_argument(
    "--mock",
    action="store_true",
    help="Use mock data (default: False, use real feed)"
)

def run_shadow(..., mock: bool):
    if mock:
        cmd.extend(["--source", "mock"])
```

**After:**
```python
parser.add_argument(
    "--source",
    default="ws",
    choices=["mock", "ws", "redis"],
    help="Data source: mock (synthetic), ws (WebSocket), redis (Redis Streams)"
)

def run_shadow(..., source: str):
    cmd.extend(["--source", source])
```

---

## 📊 STATISTICS

```
 .github/workflows/accuracy.yml    | 210 ++++++++------------------------------
 tools/shadow/baseline_autotune.py |  19 ++--
 tools/shadow/run_shadow.py        |   7 --
 3 files changed, 52 insertions(+), 184 deletions(-)
```

- **accuracy.yml:** Simplified by 158 lines (removed verbose PR comment logic)
- **baseline_autotune.py:** Updated to use `--source` parameter
- **run_shadow.py:** Removed deprecated `--mock` flag

---

## ✅ VERIFICATION CHECKLIST

### Before Merge:
- [x] All changes committed
- [x] Changes pushed to `origin/fix/ci-artifact-v4`
- [x] No `--mock` flags in shadow tools
- [x] All workflows use `artifact@v4`
- [x] Lint-step present in accuracy.yml

### After Merge to Main:
- [ ] Run **Accuracy Gate** workflow manually
- [ ] Run **Testnet Smoke** workflow manually
- [ ] Verify NO error: "deprecated version of actions/upload-artifact: v3"
- [ ] Verify step "Run Shadow Mode" succeeds (no --mock error)
- [ ] Verify artifacts upload successfully (no warnings)

---

## 🧪 TEST WORKFLOWS

### 1. Accuracy Gate
```bash
# Go to: https://github.com/dk997467/dk997467-mm-bot/actions/workflows/accuracy.yml
# Click "Run workflow"
# Select branch: main (after merge)
# Run with default parameters
```

**Expected results:**
- ✅ Lint step passes (no v3 found)
- ✅ Shadow mode runs with `--source mock`
- ✅ Artifacts upload with v4
- ✅ PR comment posted (if in PR context)

### 2. Testnet Smoke
```bash
# Go to: https://github.com/dk997467/dk997467-mm-bot/actions/workflows/testnet-smoke.yml
# Click "Run workflow"
# Select branch: main (after merge)
# Run with default parameters
```

**Expected results:**
- ✅ No "deprecated v3" error in "Prepare actions" stage
- ✅ All test steps execute normally
- ✅ Artifacts upload successfully

---

## 🚀 NEXT STEPS

1. **Merge PR:**
   - Go to: https://github.com/dk997467/dk997467-mm-bot/compare/main...fix/ci-artifact-v4
   - Review changes
   - Approve and merge (recommend: Squash and merge)

2. **Run Test Workflows:**
   - Accuracy Gate (manual dispatch from main)
   - Testnet Smoke (manual dispatch from main)

3. **Monitor:**
   - Watch for any CI failures
   - Verify artifact uploads work correctly
   - Check that lint-step catches any v3 regressions

---

## 📝 ADDITIONAL NOTES

### Why These Changes?

1. **artifact@v4:** GitHub deprecated v3, causing CI failures
2. **--source mock:** Cleaner API, replaces confusing `--mock` flag
3. **Lint-step:** Prevents accidental reintroduction of deprecated actions
4. **shell: bash:** Ensures consistent shell behavior across all steps

### Related Commits

```
ab5fbb4 ci(accuracy): resolve conflicts + fix mock flag + v4 artifacts (NEW!)
ff14a66 docs(ci): add next steps guide for PR creation
60db621 docs(ci): add comprehensive artifact v3->v4 migration report
12b2ff7 fix(workflows): resolve 5 additional context access validation errors
b13ee08 fix(workflows): resolve 10 context access validation errors
52e6325 ci: migrate to actions/{upload,download}-artifact@v4
ecda9d9 ci(workflows): bump artifact actions to v4 (fix deprecation blocker)
```

---

**Prepared by:** AI Assistant  
**Date:** 2025-10-29  
**Branch:** `fix/ci-artifact-v4`

