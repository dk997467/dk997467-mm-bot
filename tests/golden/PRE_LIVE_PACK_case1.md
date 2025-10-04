PRE-LIVE DRY RUN PACK

Result: FAIL

| step | ok | details |
|------|----|---------|
| bug_bash | OK | skipped |
| autopilot_dry | OK | AUTOPILOT=OK |
| daily_check | FAIL | {"daily_check":"GREEN","issues":[]} |
| edge_sentinel | FAIL | analyze.py: error: unrecognized arguments: --out-json artifacts/EDGE_SENTINEL.json |
| param_sweep | OK | PARAM_SWEEP WROTE artifacts/PARAM_SWEEP.json |
| apply_from_sweep | OK | TUNING WROTE artifacts/TUNING_REPORT.json tools/tuning/overlay_profile.yaml |
| chaos_failover_dry | OK | CHAOS_RESULT=OK |
| rotate_artifacts_dry | OK | ROTATION=DRYRUN |
| scan_secrets | FAIL | RESULT=FOUND |
