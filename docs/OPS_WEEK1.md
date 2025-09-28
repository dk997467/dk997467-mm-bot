Ops Week 1 Checklist
====================

Daily routine:
1. Preflight: `python -m cli.preflight`
2. Edge audit refresh
3. FinOps reconcile refresh
4. Region compare refresh
5. Soak daily report
6. Daily check:
   - `python -m tools.ops.daily_check`
7. Snapshot artifacts:
   - `sh tools/ops/snapshot.sh`
8. Review dashboards and alerts
9. Record notes in changelog
10. Prepare next-day goals

Nightly (UTC):
- `python -m tools.soak.autopilot --hours 8 --mode shadow --econ yes`
- Cron example: `sh tools/soak/nightly.sh`
- Check outputs in `artifacts/REPORT_SOAK_*.json` and ledger JSONs

Rotation:
- `python -m tools.ops.rotate_artifacts --roots artifacts dist --keep-days 14 --max-size-gb 2.0 --archive-dir dist/archives`


