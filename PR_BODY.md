# ci: migrate to actions/{upload,download}-artifact@v4 on main + anti-regression lint

## 🎯 Why

- **GitHub blocks v3** (deprecation), failing workflows on main branch
- **Root cause:** `testnet-smoke.yml` using `@v3` in 3 locations
- **Impact:** CI completely blocked, unable to run workflows

## 📋 Changes

### `.github/workflows/testnet-smoke.yml`

**Replaced v3 → v4 (3 instances):**
- Line 53: `upload-artifact@v3` → `upload-artifact@v4`
- Line 146: `upload-artifact@v3` → `upload-artifact@v4`  
- Line 163: `download-artifact@v3` → `download-artifact@v4`

**Added anti-regression lint-steps (2 jobs):**
- Job `smoke-shadow`: Added lint check after checkout
- Job `smoke-testnet-sim`: Added lint check after checkout

**Lint-step protects against future v3:**
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

## ✅ Validation

### Before Fix:
```bash
$ git grep -nE 'actions/(upload|download)-artifact\s*[@:]\s*v3(\b|[^0-9])' -- .github
.github/workflows/testnet-smoke.yml:53:        uses: actions/upload-artifact@v3
.github/workflows/testnet-smoke.yml:146:        uses: actions/upload-artifact@v3
.github/workflows/testnet-smoke.yml:163:        uses: actions/download-artifact@v3
```

### After Fix:
```bash
$ git grep -nE 'actions/(upload|download)-artifact\s*[@:]\s*v3(\b|[^0-9])' -- .github
(no output - all v3 removed ✅)
```

### Statistics:
```diff
 .github/workflows/testnet-smoke.yml | 24 +++++++++++++++++++++---
 1 file changed, 21 insertions(+), 3 deletions(-)
```

## 🧪 Testing Plan

### After Merge:
1. **Run Testnet Smoke workflow** from main branch
2. **Verify:** "Prepare actions" stage succeeds (no deprecation error)
3. **Verify:** Artifacts upload/download successfully
4. **Verify:** Lint-step passes (no v3 detected)

### Acceptance Criteria:
- ✅ No "deprecated v3" errors in CI logs
- ✅ Workflows execute from "Prepare actions" stage onward
- ✅ Artifacts upload without warnings
- ✅ Lint-step prevents future v3 reintroduction

## 📝 Checklist

- [x] All v3 references replaced with v4
- [x] Lint-steps added to jobs with artifacts  
- [x] `git grep` returns no v3 matches
- [x] YAML syntax validated
- [x] Diff reviewed
- [x] Report generated (MAIN_V3_FIX_REPORT.md)

## 🔗 Related

- **Root Issue:** CI blocker on main branch
- **Deprecation Notice:** [GitHub Actions v3 deprecation](https://github.blog/changelog/2024-04-16-deprecation-notice-v3-of-artifact-actions/)
- **Migration Guide:** [Artifact v3 → v4 migration](https://github.com/actions/upload-artifact#breaking-changes)

## 🚀 Next Steps

After merge:
1. Manually dispatch **Testnet Smoke Tests** workflow
2. Confirm no deprecation errors
3. Close any related issues

---

**Prepared by:** AI Assistant  
**Branch:** `fix/main-artifact-v4` → `main`

