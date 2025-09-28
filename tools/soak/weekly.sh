#!/bin/sh
set -e
export TZ=UTC
export MM_FREEZE_UTC=1
python -m tools.soak.weekly_rollup --soak-dir artifacts --ledger artifacts/LEDGER_DAILY.json --out-json artifacts/WEEKLY_ROLLUP.json --out-md artifacts/WEEKLY_ROLLUP.md


