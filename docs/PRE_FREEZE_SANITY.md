# Pre-Freeze Sanity Validator

**One-shot comprehensive check before production freeze.**

---

## Overview

The Pre-Freeze Sanity Validator is a comprehensive orchestrator that validates all critical systems before deploying to production. It runs 6 sequential checks and produces a clear PASS/FAIL verdict.

**Purpose:** Catch issues before they reach production by testing the full stack in one automated run.

---

## Quick Start

```bash
# Standard check (recommended)
python -m tools.release.pre_freeze_sanity \
  --src "artifacts/soak/latest" \
  --smoke-iters 6 \
  --post-iters 8 \
  --run-isolated

# Alternative source (with spaces in path)
python -m tools.release.pre_freeze_sanity \
  --src "artifacts/soak/latest 1" \
  --smoke-iters 6 \
  --post-iters 8 \
  --run-isolated
```

**Expected Duration:** ~15-20 minutes (depending on iteration counts)

---

## Validation Sections

### 1. Smoke Tests (6 iterations)

**What:** Fast smoke test to verify basic functionality

**Checks:**
- All 6 `ITER_SUMMARY_*.json` files created
- `TUNING_REPORT.json` exists with exactly 6 iterations
- Average maker/taker ratio >= 0.50

**Exit Code on Failure:** 3

---

### 2. Post-Soak Gates (8 iterations)

**What:** Full soak test with KPI validation

**Checks:**
- Last-8 KPIs meet thresholds:
  - Maker/Taker >= 0.83
  - P95 Latency <= 340ms
  - Risk Ratio <= 0.40
  - Net BPS >= 2.5
- Delta apply ratio >= 0.95
- Reports generated (SNAPSHOT, AUDIT, etc.)

**Exit Code on Failure:** 2

---

### 3. RUN Isolation (optional, with `--run-isolated`)

**What:** Tests isolated run directories

**Checks:**
- `RUN_<epoch>` directory created
- Key files materialized to `latest/`:
  - `TUNING_REPORT.json`
  - `ITER_SUMMARY_*.json` (all iterations)

**Exit Code on Failure:** 4

---

### 4. Guards Sanity

**What:** Tests guards module functionality

**Checks:**
- `Debounce` class: open after 2500ms, close after 4000ms
- `PartialFreezeState`: freezes `rebid` and `rescue_taker`, never freezes `edge`

**Exit Code on Failure:** 5

---

### 5. Prometheus Metrics

**What:** Validates metrics export

**Checks:**
- `maker_taker_ratio_hmean{window="8"}` present
- `maker_share_pct` present and reasonable
- `partial_freeze_active` is 0 or 1

**Exit Code on Failure:** 6

---

### 6. Release Bundle

**What:** Validates bundle completeness

**Required Files:**
- `POST_SOAK_SNAPSHOT.json`
- `POST_SOAK_AUDIT.md`
- `RECOMMENDATIONS.md`
- `FAILURES.md`
- `soak_profile.runtime_overrides.json`
- `CHANGELOG.md`
- `rollback_plan.md`

**Optional Files (warning only):**
- `DELTA_VERIFY_REPORT.json`
- `CANARY_CHECKLIST.md`

**Exit Code on Failure:** 7

---

## Exit Codes

| Code | Meaning | Action |
|------|---------|--------|
| 0 | All checks PASS | Proceed to production |
| 1 | Internal error | Check logs, retry |
| 2 | Post-soak KPI fail | Review KPIs, tune parameters |
| 3 | Smoke test fail | Fix basic functionality |
| 4 | Isolation fail | Check materialization logic |
| 5 | Guards fail | Review guards module |
| 6 | Metrics fail | Check exporter |
| 7 | Bundle fail | Check report generation |

---

## Output Artifacts

After running, you'll find:

```
{src}/
├── soak/latest/
│   ├── ITER_SUMMARY_*.json
│   ├── TUNING_REPORT.json
│   └── runtime_overrides.json
├── reports/analysis/
│   ├── POST_SOAK_SNAPSHOT.json
│   ├── POST_SOAK_AUDIT.md
│   ├── RECOMMENDATIONS.md
│   ├── FAILURES.md
│   └── DELTA_VERIFY_REPORT.json
├── metrics.prom
├── PRE_FREEZE_SANITY_SUMMARY.md  ← Summary report
└── RUN_<epoch>/  (if --run-isolated)

release/soak-ci-chaos-release-toolkit/
├── POST_SOAK_SNAPSHOT.json
├── POST_SOAK_AUDIT.md
├── RECOMMENDATIONS.md
├── FAILURES.md
├── soak_profile.runtime_overrides.json
├── CHANGELOG.md
├── rollback_plan.md
└── CANARY_CHECKLIST.md
```

---

## Command-Line Options

```bash
python -m tools.release.pre_freeze_sanity [OPTIONS]
```

**Required:**
- `--src DIR` - Source directory for soak artifacts

**Optional:**
- `--alt-src DIR` - Alternative source (for comparison, not used in current version)
- `--smoke-iters N` - Number of smoke iterations (default: 6)
- `--post-iters N` - Number of post-soak iterations (default: 8)
- `--run-isolated` - Test RUN isolation (creates `RUN_<epoch>`)

---

## Typical Errors & Fixes

### Error: Smoke test fails (exit 3)

**Symptom:** Average maker/taker < 0.50

**Fix:**
```bash
# Check mock data generation in tools/soak/run.py
# Verify fills data is realistic
```

---

### Error: Post-soak KPI fail (exit 2)

**Symptom:** One or more KPIs below threshold

**Fix:**
```bash
# Review POST_SOAK_SNAPSHOT.json
cat artifacts/soak/latest/reports/analysis/POST_SOAK_SNAPSHOT.json

# Check specific KPI that failed
# Adjust parameters in runtime_overrides.json if needed
```

---

### Error: Delta apply ratio < 0.95 (exit 2)

**Symptom:** Parameters not being applied correctly

**Fix:**
```bash
# Check DELTA_VERIFY_REPORT.json for mismatches
cat artifacts/soak/latest/reports/analysis/DELTA_VERIFY_REPORT.json

# Review nested parameter resolution in params.py
```

---

### Error: Isolation fails (exit 4)

**Symptom:** Files not materialized to `latest/`

**Fix:**
```bash
# Check materialization logic in tools/soak/run.py
# Verify RUN_<epoch> directory was created
ls -lh artifacts/soak/latest/RUN_*/
```

---

### Error: Guards fail (exit 5)

**Symptom:** Debounce or PartialFreezeState not working

**Fix:**
```bash
# Run unit tests
pytest tests/pre_freeze/test_guards_sanity.py -v

# Check tools/soak/guards.py implementation
```

---

### Error: Metrics export fails (exit 6)

**Symptom:** Missing metrics in metrics.prom

**Fix:**
```bash
# Run exporter manually
python -m tools.soak.prometheus_exporter \
  --path artifacts/soak/latest/soak/latest

# Check for errors in stderr
```

---

### Error: Bundle generation fails (exit 7)

**Symptom:** Missing required files

**Fix:**
```bash
# Run bundle builder manually
python -m tools.release.build_release_bundle \
  --src artifacts/soak/latest \
  --out release/soak-ci-chaos-release-toolkit

# Check which files are missing
```

---

## Integration with CI/CD

### GitHub Actions

```yaml
- name: Pre-Freeze Sanity Check
  run: |
    python -m tools.release.pre_freeze_sanity \
      --src artifacts/soak/latest \
      --smoke-iters 6 \
      --post-iters 8 \
      --run-isolated
    
    EXIT_CODE=$?
    
    if [ $EXIT_CODE -ne 0 ]; then
      echo "❌ Pre-freeze sanity FAILED (exit $EXIT_CODE)"
      exit 1
    fi
    
    echo "✅ Pre-freeze sanity PASSED"
```

---

## Makefile Targets

Add to `Makefile`:

```makefile
.PHONY: pre-freeze pre-freeze-alt

pre-freeze:
	python -m tools.release.pre_freeze_sanity \
		--src "artifacts/soak/latest" \
		--smoke-iters 6 \
		--post-iters 8 \
		--run-isolated

pre-freeze-alt:
	python -m tools.release.pre_freeze_sanity \
		--src "artifacts/soak/latest 1" \
		--smoke-iters 6 \
		--post-iters 8 \
		--run-isolated
```

**Usage:**
```bash
make pre-freeze       # Standard check
make pre-freeze-alt   # Check artifacts in "latest 1"
```

---

## PowerShell Script (Windows)

Create `scripts/pre_freeze.ps1`:

```powershell
param(
    [string]$Src = "artifacts/soak/latest",
    [int]$SmokeIters = 6,
    [int]$PostIters = 8,
    [switch]$RunIsolated
)

$args = @(
    "-m", "tools.release.pre_freeze_sanity",
    "--src", $Src,
    "--smoke-iters", $SmokeIters,
    "--post-iters", $PostIters
)

if ($RunIsolated) {
    $args += "--run-isolated"
}

& python $args

$exitCode = $LASTEXITCODE

if ($exitCode -eq 0) {
    Write-Host "✅ Pre-freeze sanity PASSED" -ForegroundColor Green
} else {
    Write-Host "❌ Pre-freeze sanity FAILED (exit $exitCode)" -ForegroundColor Red
}

exit $exitCode
```

**Usage:**
```powershell
.\scripts\pre_freeze.ps1
.\scripts\pre_freeze.ps1 -Src "artifacts/soak/latest 1" -RunIsolated
```

---

## Acceptance Criteria

Pre-freeze sanity is considered **PASS** when:

1. ✅ Smoke (6 iters): Green, `len(TUNING_REPORT.iterations) == 6`
2. ✅ Post-soak (8 iters): All KPIs meet targets, `full_apply_ratio >= 0.95`
3. ✅ Isolation: `RUN_<epoch>` created, files materialized
4. ✅ Guards: Debounce and PartialFreezeState work correctly
5. ✅ Metrics: All required metrics present and valid
6. ✅ Bundle: All required files present

**Final Output:**
```
================================================================================
FINAL VERDICT
================================================================================
[OK]   smoke           PASS
[OK]   post_soak       PASS
[OK]   isolation       PASS
[OK]   guards          PASS
[OK]   metrics         PASS
[OK]   bundle          PASS
================================================================================
✅ PASS - Ready for production freeze
================================================================================
```

---

## Next Steps After PASS

1. **Review Summary:**
   ```bash
   cat artifacts/soak/latest/PRE_FREEZE_SANITY_SUMMARY.md
   ```

2. **Tag Release:**
   ```bash
   python -m tools.release.tag_and_canary \
     --bundle release/soak-ci-chaos-release-toolkit \
     --tag v1.0.0-soak-validated
   ```

3. **Deploy Canary:**
   ```bash
   cat release/soak-ci-chaos-release-toolkit/CANARY_CHECKLIST.md
   ```

4. **Production Freeze:**
   - Lock `runtime_overrides.json`
   - Tag in Git
   - Deploy to production

---

## Troubleshooting

### Validator hangs or takes too long

**Cause:** Large iteration counts or slow subprocess execution

**Fix:**
- Reduce `--smoke-iters` and `--post-iters` for faster validation
- Check system resources (CPU, memory)

---

### Path with spaces causes issues

**Cause:** Improper quoting in subprocess calls

**Fix:**
- Always quote paths: `--src "artifacts/soak/latest 1"`
- Validator handles this correctly, but check custom scripts

---

### Internal error (exit 1)

**Cause:** Unexpected exception in validator

**Fix:**
- Check traceback in console output
- Verify all tools are installed (`build_reports.py`, `verify_deltas_applied.py`, etc.)
- Retry with fresh artifacts

---

## Reference

- **Orchestrator:** `tools/release/pre_freeze_sanity.py`
- **Guards Tests:** `tests/pre_freeze/test_guards_sanity.py`
- **Documentation:** `docs/PRE_FREEZE_SANITY.md` (this file)

---

**Last Updated:** 2025-10-18  
**Version:** 1.0.0

