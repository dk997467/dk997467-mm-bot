#!/bin/sh
set -e
export MM_FREEZE_UTC=1
python -m tools.soak.runner --mode shadow --hours 24
python -m tools.soak.daily_report --out artifacts/REPORT_SOAK_$(date -u +%Y%m%d).json


