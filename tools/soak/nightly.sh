#!/bin/sh
set -e
export TZ=UTC
export MM_FREEZE_UTC=1
python -m tools.soak.autopilot --hours 8 --mode shadow --econ yes


