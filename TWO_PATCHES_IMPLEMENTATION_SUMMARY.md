# Two Patches Implementation Summary

**Date:** 2025-10-11  
**Status:** ✅ COMPLETE

## Overview

Implemented two critical patches for production readiness:

1. **PATCH A**: Readiness Score - Deterministic JSON + Fixable UTC
2. **PATCH B**: Scan Secrets - Artifacts Criticality → Exit 2

---

## PATCH A — Readiness Score: Deterministic JSON + Fixable UTC

### Changes Made

**File:** `tools/release/readiness_score.py`

1. ✅ Added `read_version()` function to read from VERSION file (fallback: "0.1.0")
2. ✅ Added `get_deterministic_runtime()` for CI_FAKE_UTC support
3. ✅ Modified JSON output to use `json.dumps(..., sort_keys=True, separators=(",",":"))`
4. ✅ Simplified verdict: `"GO"` if `score == 100.0`, else `"HOLD"`
5. ✅ Removed dependency on `src.common.runtime.get_runtime_info()`

### Features

- **Deterministic JSON**: No whitespace, sorted keys, consistent format
- **Time Fixation**: 
  - Priority 1: `CI_FAKE_UTC` env var
  - Priority 2: `MM_FREEZE_UTC_ISO` env var
  - Priority 3: Real UTC time
- **Version Reading**: Reads from `VERSION` file, falls back to "0.1.0"

### Output Format

```json
{"runtime":{"utc":"1970-01-01T00:00:00Z","version":"0.1.0"},"score":60.0,"sections":{"chaos":10.0,"edge":0.0,"guards":0.0,"latency":25.0,"taker":15.0,"tests":10.0},"verdict":"HOLD"}
```

### Testing

**E2E Test:** `tests/e2e/test_readiness_score_e2e.py`

- ✅ `test_readiness_json_deterministic()` - Verifies deterministic output with `CI_FAKE_UTC`
- ✅ `test_readiness_json_format()` - Verifies compact JSON format (no spaces)

**Results:**
```
✓ Readiness score deterministic test passed
  UTC: 1970-01-01T00:00:00Z
  Score: 60.0
  Verdict: HOLD
✓ Readiness JSON format test passed
```

### Usage

```bash
# Run with fake UTC
CI_FAKE_UTC="1970-01-01T00:00:00Z" python -m tools.release.readiness_score

# In CI pipeline
CI_FAKE_UTC="1970-01-01T00:00:00Z" python -m tools.release.readiness_score > artifacts/reports/readiness.json
```

---

## PATCH B — Scan Secrets: Artifacts Criticality → Exit 2

### Changes Made

**File:** `tools/ci/scan_secrets.py`

1. ✅ Added detection of `WORK_DIR/artifacts/` path
2. ✅ Added `critical_findings` list for secrets in `artifacts/**`
3. ✅ Modified scanning logic to classify findings:
   - **Critical**: Any secret in `artifacts/**` (bypasses allowlist)
   - **Real**: Secrets in repo (not allowlisted)
   - **Allowlisted**: Secrets in repo (allowlisted)
4. ✅ Modified exit code logic:
   - Exit 2: Critical findings in `artifacts/**`
   - Exit 1: Real findings in repo
   - Exit 0: Clean or allowlisted only
5. ✅ Added `artifacts/` to scan directories if it exists

### Priority Logic

```
PRIORITY 1: critical_findings (artifacts/**) → exit 2
PRIORITY 2: real_findings (repo, not allowlisted) → exit 1
PRIORITY 3: allowlisted_findings (strict mode) → exit 1
PRIORITY 4: clean → exit 0
```

### Output Format

**Critical findings:**
```
[CRITICAL] Secrets found in artifacts/** (bypasses allowlist):
  artifacts/leaky_logs.txt:1: API_KEY=sk_****...
| scan_secrets | FAIL | RESULT=CRITICAL |
[CRITICAL] Found 1 secret(s) in artifacts/
Exit Code: 2
```

**Clean repo:**
```
| scan_secrets | OK | RESULT=CLEAN |
[OK] No secrets found
Exit Code: 0
```

### Testing

**Unit Test:** `tests/test_scan_secrets_ci.py`

- ✅ `test_scan_secrets_finds_fixture()` - Verifies exit 2 for secrets in `artifacts/**`
- ✅ `test_scan_secrets_clean_repo()` - Verifies exit 0 for clean repo

**Results:**
```
✓ scan_secrets detects artifacts leak → exit 2 (CRITICAL)
✓ scan_secrets clean repo → exit 0
```

### Usage

```bash
# Run with WORK_DIR set
WORK_DIR=/path/to/repo python -m tools.ci.scan_secrets

# In CI pipeline (auto-detects artifacts/)
python -m tools.ci.scan_secrets
```

---

## Files Modified/Created

### Patch A Files

| File | Status | Lines |
|------|--------|-------|
| `tools/release/readiness_score.py` | MODIFIED | +42 |
| `tests/e2e/test_readiness_score_e2e.py` | CREATED | 106 |

### Patch B Files

| File | Status | Lines |
|------|--------|-------|
| `tools/ci/scan_secrets.py` | MODIFIED | +67 |
| `tests/test_scan_secrets_ci.py` | CREATED | 105 |

---

## Test Results Summary

| Patch | Test Suite | Status | Details |
|-------|------------|--------|---------|
| A | E2E Tests | ✅ PASS | 2/2 tests passed |
| B | Unit Tests | ✅ PASS | 2/2 tests passed |

### Detailed Test Output

**Patch A:**
```bash
$ CI_FAKE_UTC="1970-01-01T00:00:00Z" python tests/e2e/test_readiness_score_e2e.py
✓ Readiness score deterministic test passed
✓ Readiness JSON format test passed
✓ All readiness score E2E tests passed
```

**Patch B:**
```bash
$ python tests/test_scan_secrets_ci.py
✓ scan_secrets detects artifacts leak → exit 2 (CRITICAL)
✓ scan_secrets clean repo → exit 0
✓ All scan_secrets tests passed
```

---

## Acceptance Criteria

### Patch A ✅

- [x] JSON only via `json.dumps(..., sort_keys=True, separators=(",",":"))`
- [x] CI_FAKE_UTC env var support
- [x] VERSION file reading
- [x] Deterministic output structure
- [x] E2E test passes

### Patch B ✅

- [x] Secrets in `artifacts/**` → exit 2
- [x] Normal allowlist logic for repo secrets
- [x] Output marker: `| scan_secrets | FAIL | RESULT=CRITICAL |`
- [x] Unit test for artifacts leak detection
- [x] Unit test for clean repo

---

## Integration Notes

### CI/CD Pipeline Integration

**Readiness Score:**
```yaml
- name: Generate readiness score
  run: |
    CI_FAKE_UTC="1970-01-01T00:00:00Z" \
    python -m tools.release.readiness_score > artifacts/reports/readiness.json
```

**Scan Secrets:**
```yaml
- name: Scan for secrets
  run: |
    python -m tools.ci.scan_secrets
    if [ $? -eq 2 ]; then
      echo "CRITICAL: Secrets found in artifacts/"
      exit 1
    fi
```

### Key Markers

For log parsing and monitoring:

1. **Readiness Score:**
   - JSON output on stdout (last line)
   - Compact format: `{"runtime":{"utc":"...","version":"..."},...}`

2. **Scan Secrets:**
   - Exit 2: `| scan_secrets | FAIL | RESULT=CRITICAL |`
   - Exit 1: `| scan_secrets | FAIL | RESULT=FOUND |`
   - Exit 0: `| scan_secrets | OK | RESULT=CLEAN |`

---

## Backward Compatibility

### Patch A

- ✅ Maintains file output to `artifacts/READINESS_SCORE.json`
- ✅ Maintains markdown output to `artifacts/READINESS_SCORE.md`
- ✅ Adds stdout JSON output (non-breaking)
- ✅ Falls back to `MM_FREEZE_UTC_ISO` if `CI_FAKE_UTC` not set

### Patch B

- ✅ Maintains normal scan behavior for repo files
- ✅ Allowlist logic unchanged for repo files
- ✅ New behavior only affects `artifacts/**` paths
- ✅ Backward compatible exit codes (0/1) for non-artifacts

---

## Known Limitations

### Patch A

- Verdict is now binary (`GO` or `HOLD`), removed `WARN` and `NO-GO`
- `GO` only if score exactly `100.0` (strict)

### Patch B

- Scans `artifacts/` only if `WORK_DIR/artifacts/` exists
- Large `artifacts/` directories may slow down scan (mitigated by EXCLUDE_DIRS)

---

## Next Steps

1. ✅ **Patch A**: Integrate into CI pipeline for deterministic readiness scores
2. ✅ **Patch B**: Add to CI pipeline as critical safety check
3. 🔄 **Documentation**: Update runbooks with new exit codes
4. 🔄 **Monitoring**: Add alerts for exit code 2 from scan_secrets

---

**Status:** ✅ BOTH PATCHES READY FOR INTEGRATION

All acceptance criteria met. Tests passing. Ready for production deployment.

