# Main Branch v3 → v4 Migration Report

## 🎯 FOUND & FIXED

**Branch:** `main` → `fix/main-artifact-v4`  
**Problem:** CI failing with "deprecated actions/upload-artifact@v3"  
**Root Cause:** `testnet-smoke.yml` using v3 in 3 locations

---

## 📋 FILES CHANGED

| File | Lines Changed | v3 → v4 | Lint-Steps Added |
|------|---------------|---------|------------------|
| `.github/workflows/testnet-smoke.yml` | +21, -3 | 3 replacements | 2 jobs |

---

## 🔍 DETAILED FINDINGS

### `.github/workflows/testnet-smoke.yml`

**Found 3 instances of v3:**

| Line | Old | New | Status |
|------|-----|-----|--------|
| 53 | `uses: actions/upload-artifact@v3` | `uses: actions/upload-artifact@v4` | ✅ Fixed |
| 146 | `uses: actions/upload-artifact@v3` | `uses: actions/upload-artifact@v4` | ✅ Fixed |
| 163 | `uses: actions/download-artifact@v3` | `uses: actions/download-artifact@v4` | ✅ Fixed |

**Added lint-steps to 2 jobs:**

1. **Job: `smoke-shadow`** (line 33)
   - Added "Lint - forbid artifact v3" after checkout
   
2. **Job: `smoke-testnet-sim`** (line 79)
   - Added "Lint - forbid artifact v3" after checkout

**Lint-step code:**
```yaml
- name: Lint - forbid artifact v3
  shell: bash
  run: |
    set -euo pipefail
    if git grep -nE 'actions/(upload|download)-artifact\s*[@:]\s*v3(\b|[^0-9])' .github | tee /dev/stderr; then
      echo "::error::Found deprecated artifact actions v3 — must use @v4"
      exit 1
    fi
```

---

## ✅ VERIFICATION

### Before Fix (main branch):
```bash
$ git grep -nE 'actions/(upload|download)-artifact\s*[@:]\s*v3(\b|[^0-9])' -- .github
.github/workflows/testnet-smoke.yml:53:        uses: actions/upload-artifact@v3
.github/workflows/testnet-smoke.yml:146:        uses: actions/upload-artifact@v3
.github/workflows/testnet-smoke.yml:163:        uses: actions/download-artifact@v3
```

### After Fix (fix/main-artifact-v4):
```bash
$ git grep -nE 'actions/(upload|download)-artifact\s*[@:]\s*v3(\b|[^0-9])' -- .github
(no output - all v3 removed ✅)
```

### Artifact Actions Summary:
- ✅ `upload-artifact@v4`: 2 instances
- ✅ `download-artifact@v4`: 1 instance
- ❌ `*-artifact@v3`: **0 instances** (all removed)

---

## 📊 DIFF STATISTICS

```diff
 .github/workflows/testnet-smoke.yml | 24 +++++++++++++++++++++---
 1 file changed, 21 insertions(+), 3 deletions(-)
```

**Changes breakdown:**
- **+21 lines:** 2 lint-steps added (9 lines each) + 3 version updates
- **-3 lines:** 3 old v3 references removed

---

## 🚀 WHAT THIS FIXES

### Problem (before):
```
CI Error: "This request has been automatically failed because it uses 
a deprecated version of actions/upload-artifact: v3..."
```

**Failing stage:** "Prepare actions / Getting action download info"  
**Failed workflow:** Testnet Smoke Tests  
**Impact:** Unable to run any workflows on main branch

### Solution (after):
- ✅ All artifact actions updated to v4
- ✅ Lint-step prevents future v3 reintroduction
- ✅ CI will pass "Prepare actions" stage
- ✅ Workflows can execute normally

---

## 🔐 ANTI-REGRESSION PROTECTION

### How Lint-Step Protects:
1. **Early Detection:** Runs immediately after checkout
2. **Strict Check:** Uses `set -euo pipefail` for robust error handling
3. **Clear Errors:** Outputs `::error::` for GitHub UI visibility
4. **Comprehensive Scan:** Checks entire `.github/` directory
5. **Zero Tolerance:** Exits with code 1 on any v3 match

### Regex Pattern:
```regex
'actions/(upload|download)-artifact\s*[@:]\s*v3(\b|[^0-9])'
```

**Catches:**
- `upload-artifact@v3`
- `download-artifact@v3`
- `upload-artifact@v3.1`
- `download-artifact @ v3`
- And other variations

---

## 📝 COMMIT MESSAGE

```
ci: migrate artifact actions to v4 on main + add v3-lint in workflows

Why:
- GitHub blocks v3 (deprecation), failing workflows on main branch
- Root cause: testnet-smoke.yml using v3 in 3 locations

Changes:
- testnet-smoke.yml: replace all upload/download-artifact@v3 → @v4 (3 fixes)
- testnet-smoke.yml: add lint-step to 2 jobs (anti-regression protection)

Verification:
- grep for v3 → none found ✅
- lint-step validates .github/ recursively
- all workflows syntax-valid (YAML)

Fixes: CI blocker on main branch
```

---

## 🎯 ACCEPTANCE CRITERIA

### Before Merge:
- [x] All v3 references replaced with v4
- [x] Lint-steps added to all jobs with artifacts
- [x] `git grep` returns no v3 matches
- [x] YAML syntax validated

### After Merge:
- [ ] Re-run Testnet Smoke workflow from main branch
- [ ] Verify "Prepare actions" stage succeeds
- [ ] Verify no deprecation errors in logs
- [ ] Verify artifacts upload/download successfully

---

## 🔗 NEXT STEPS

1. **Merge PR:**
   ```bash
   gh pr create --title "ci: migrate artifact actions to v4 on main + anti-regression lint" \
                --body-file PR_BODY.md \
                --base main \
                --head fix/main-artifact-v4
   ```

2. **Test After Merge:**
   - Go to: https://github.com/YOUR_ORG/mm-bot/actions/workflows/testnet-smoke.yml
   - Click "Run workflow"
   - Select branch: `main`
   - Verify NO errors in "Prepare actions" stage

3. **Monitor:**
   - Watch for any other workflows that might fail
   - Verify lint-step catches any future v3 introductions

---

**Prepared by:** AI Assistant  
**Date:** 2025-10-29  
**Branch:** `fix/main-artifact-v4`  
**Status:** ✅ Ready for PR

