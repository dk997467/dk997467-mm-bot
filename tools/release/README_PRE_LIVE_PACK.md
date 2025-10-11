# Pre-Live Pack - Dry-Run Orchestrator

**Purpose:** Orchestrates pre-deployment validation checks in dry-run mode.

## Overview

The `pre_live_pack.py` script runs a suite of validation steps before deployment:

1. `param_sweep_dry` - Parameter sweep validation
2. `tuning_apply_dry` - Tuning configuration check
3. `chaos_failover_dry` - Chaos engineering failover test
4. `rotate_artifacts_dry` - Artifact rotation check
5. `scan_secrets_dry` - Secrets scanner validation

All checks run in **dry-run mode** (no actual changes made).

## Usage

```bash
# Run pre-live pack dry-run
python -m tools.release.pre_live_pack --dry-run
```

## Exit Codes

- **0**: All checks passed
- **1**: One or more checks failed

## Output Format

The script produces deterministic ASCII output with:

1. Individual step results table
2. Final status marker: `| pre_live_pack | OK | PRE_LIVE_PACK=DRYRUN |`

Example output:

```
============================================================
PRE-LIVE PACK DRY-RUN RESULTS
============================================================

| param_sweep_dry           | OK   |
| tuning_apply_dry          | OK   |
| chaos_failover_dry        | OK   |
| rotate_artifacts_dry      | OK   |
| scan_secrets_dry          | OK   |

------------------------------------------------------------
| pre_live_pack             | OK   | PRE_LIVE_PACK=DRYRUN |
------------------------------------------------------------
```

## Testing

### E2E Test

```bash
# Set PYTHONPATH and run E2E test
$env:PYTHONPATH = "$PWD"
python tests/e2e/test_pre_live_pack_dry.py
```

Expected: Exit code 0, output contains `PRE_LIVE_PACK=DRYRUN`

### Unit Tests

```bash
# Set PYTHONPATH and run unit tests
$env:PYTHONPATH = "$PWD"
python tests/unit/test_pre_live_pack.py
```

Tests include:
- Subprocess success/failure handling
- Timeout handling
- Aggregated status logic

## Implementation Notes

- **stdlib-only**: No external dependencies
- **Deterministic output**: ASCII-only, consistent formatting
- **Timeout protection**: 30-second timeout per subprocess
- **Exit code guarantee**: Always returns 0 or 1

## Integration

This script is designed to be called by:
- CI/CD pipelines
- Pre-deployment validation workflows
- Manual pre-release checks

## Acceptance Criteria

✅ Output contains final marker: `| pre_live_pack | OK | PRE_LIVE_PACK=DRYRUN |`  
✅ Process exits with code 0 when all checks pass  
✅ E2E test passes  
✅ Unit tests pass  
✅ Deterministic, ASCII-only output

