#!/usr/bin/env bash
set -euo pipefail
export TZ="${TZ:-Europe/Berlin}"
echo "[morning] TZ=${TZ}"

echo "[morning] 1/4 daily_check"
python -m tools.ops.daily_check || true

echo "[morning] 2/4 cron_sentinel"
python -m tools.ops.cron_sentinel --tz "${TZ}" --window-hours 24

echo "[morning] 3/4 daily digest"
out="artifacts/digest/$(date +%F).json"
mkdir -p artifacts/digest
python -m tools.ops.daily_digest --out "${out}" 2>/dev/null || python -m tools.ops.digest --out "${out}"

echo "[morning] 4/4 archive"
python -m tools.ops.artifacts_archive --src artifacts --fast true

echo "[morning] done"


