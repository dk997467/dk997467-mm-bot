OPS One-Pager (Daily)
=====================

Morning ritual (2 minutes):
1. Run CI sanity:
   - `python tools/ci/run_bug_bash.py` → expect `RESULT=OK`
2. Daily soak check:
   - `python -m tools.ops.daily_check` → expect `RESULT=OK`
3. Generate daily digest:
   - `python -m tools.ops.daily_digest --out artifacts/DAILY_DIGEST.md`

Where to look:
- EDGE: `artifacts/EDGE_REPORT.{json,md}`
- SOAK: `artifacts/REPORT_SOAK_YYYYMMDD.{json,md}`
- LEDGER: `artifacts/LEDGER_*.json`
- Weekly rollup: `artifacts/WEEKLY_ROLLUP.{json,md}`

If WARN/FAIL:
- See runbooks: silence/rollback, drift guard, regression guard
- Drift guard: `artifacts/DRIFT_STOP.{json,md}`
- Regression guard: `artifacts/REG_GUARD_STOP.{json,md}`


