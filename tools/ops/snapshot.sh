#!/bin/sh
set -e
UTC_TS=$(date -u +%Y%m%dT%H%M%SZ)
OUT=dist/snapshots/$UTC_TS
mkdir -p "$OUT"

# Artifacts
for f in artifacts/EDGE_REPORT.json artifacts/EDGE_REPORT.md artifacts/REGION_COMPARE.json artifacts/REGION_COMPARE.md artifacts/metrics.json; do
  if [ -f "$f" ]; then cp "$f" "$OUT"; fi
done

# Soak reports
for f in artifacts/REPORT_SOAK_*.json artifacts/REPORT_SOAK_*.md; do
  for g in $f; do
    if [ -f "$g" ]; then cp "$g" "$OUT"; fi
  done
done

# Latest finops
latest_dir=$(ls -1dt dist/finops/* 2>/dev/null | head -n 1 || true)
if [ -n "$latest_dir" ] && [ -d "$latest_dir" ]; then
  mkdir -p "$OUT/finops"
  cp -r "$latest_dir" "$OUT/finops/"
fi

echo "SNAPSHOT $OUT"


