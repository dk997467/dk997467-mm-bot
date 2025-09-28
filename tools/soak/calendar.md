Long Soak Calendar
==================

Weekly cadence (2–4 weeks):

Daily:
- Nightly shadow soak: `sh tools/soak/nightly.sh`
- Check & digest: `python -m tools.ops.daily_check` → `python -m tools.ops.daily_digest --out artifacts/DAILY_DIGEST.md`
- Rotation: `python -m tools.ops.rotate_artifacts --roots artifacts dist --keep-days 14 --max-size-gb 2.0 --archive-dir dist/archives`

Weekly (Saturday):
- Weekly rollup: `python -m tools.soak.weekly_rollup --soak-dir artifacts --ledger artifacts/LEDGER_DAILY.json --out-json artifacts/WEEKLY_ROLLUP.json --out-md artifacts/WEEKLY_ROLLUP.md`
- KPI gate: `python -m tools.soak.kpi_gate`

References: [OPS One-Pager](../docs/OPS_ONE_PAGER.md)


