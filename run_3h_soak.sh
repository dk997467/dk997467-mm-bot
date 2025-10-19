#!/bin/bash
# Run 3-hour mini-soak with auto-tuning to achieve net_bps >= 3.0
#
# Usage:
#   ./run_3h_soak.sh

set -euo pipefail

# ============================================================================
# CONFIGURATION
# ============================================================================

# Environment
export MM_PROFILE="S1"
export SOAK_HOURS="3"
export PYTHONPATH="$PWD:$PWD/src"
export PYTEST_DISABLE_PLUGIN_AUTOLOAD="1"

# Python executable
PYTHON="${PYTHON_EXE:-python}"

# ============================================================================
# PRE-FLIGHT CHECKS
# ============================================================================

echo "============================================="
echo "3-HOUR SOAK TEST: Path to net_bps >= 3.0"
echo "============================================="
echo ""

# Check Python
echo -n "[CHECK] Python..."
if PYTHON_VERSION=$($PYTHON --version 2>&1); then
  echo " OK ($PYTHON_VERSION)"
else
  echo " ERROR"
  echo "  Python not found or not working"
  exit 1
fi

# Check profile exists
echo -n "[CHECK] Profile S1..."
if [ -f "config/profiles/market_maker_S1.json" ]; then
  echo " OK"
else
  echo " ERROR"
  echo "  config/profiles/market_maker_S1.json not found"
  exit 1
fi

# Check runtime overrides
echo -n "[CHECK] Runtime overrides..."
if [ -f "artifacts/soak/runtime_overrides.json" ]; then
  echo " OK"
  
  # Display current overrides
  echo "  Baseline overrides:"
  jq -r 'to_entries[] | "    \(.key) = \(.value)"' artifacts/soak/runtime_overrides.json
else
  echo " WARN"
  echo "  artifacts/soak/runtime_overrides.json not found (will use defaults)"
fi

echo ""

# ============================================================================
# RUN 3-HOUR SOAK
# ============================================================================

echo "============================================="
echo "STARTING 3-HOUR SOAK (6 iterations x 30min)"
echo "============================================="
echo ""

START_TIME=$(date +%s)

set +e  # Don't exit on error (capture exit code)
$PYTHON -m tools.soak.run \
  --hours 3 \
  --iterations 6 \
  --auto-tune \
  --export-json artifacts/reports/soak_metrics.json \
  --export-md artifacts/reports/SOAK_RESULTS.md \
  --gate-summary artifacts/reports/gates_summary.json

EXIT_CODE=$?
set -e

END_TIME=$(date +%s)
DURATION=$((END_TIME - START_TIME))
DURATION_MIN=$((DURATION / 60))

echo ""
echo "============================================="
echo "SOAK TEST COMPLETED"
echo "============================================="
echo ""
echo "Duration: ${DURATION_MIN}m"
echo "Exit code: $EXIT_CODE"
echo ""

# ============================================================================
# POST-SOAK ANALYSIS
# ============================================================================

if [ $EXIT_CODE -ne 0 ]; then
  echo "============================================="
  echo "SOAK TEST FAILED"
  echo "============================================="
  echo ""
  echo "Check artifacts/soak/summary.txt for details"
  exit $EXIT_CODE
fi

# Generate EDGE_REPORT if not already generated
if [ ! -f "artifacts/reports/EDGE_REPORT.json" ]; then
  echo "[POST-SOAK] Generating EDGE_REPORT with diagnostics..."
  
  if $PYTHON -m tools.reports.edge_report \
      --inputs artifacts/EDGE_REPORT.json \
      --audit artifacts/soak/audit.jsonl \
      --out-json artifacts/reports/EDGE_REPORT.json; then
    echo "  [OK] EDGE_REPORT.json generated"
  else
    echo "  [WARN] EDGE_REPORT generation failed (non-critical)"
  fi
fi

# ============================================================================
# RESULTS SUMMARY
# ============================================================================

echo ""
echo "============================================="
echo "RESULTS SUMMARY"
echo "============================================="
echo ""

# Check if EDGE_REPORT exists
if [ -f "artifacts/reports/EDGE_REPORT.json" ]; then
  # Extract key metrics
  NET_BPS=$(jq -r '.totals.net_bps' artifacts/reports/EDGE_REPORT.json)
  GROSS_BPS=$(jq -r '.totals.gross_bps' artifacts/reports/EDGE_REPORT.json)
  FEES_BPS=$(jq -r '.totals.fees_eff_bps' artifacts/reports/EDGE_REPORT.json)
  SLIPPAGE_P95=$(jq -r '.totals.slippage_bps_p95' artifacts/reports/EDGE_REPORT.json)
  ADVERSE_P95=$(jq -r '.totals.adverse_bps_p95' artifacts/reports/EDGE_REPORT.json)
  CANCEL_RATIO=$(jq -r '.totals.cancel_ratio' artifacts/reports/EDGE_REPORT.json)
  ORDER_AGE_P95=$(jq -r '.totals.order_age_p95_ms' artifacts/reports/EDGE_REPORT.json)
  MAKER_SHARE=$(jq -r '.totals.maker_share_pct' artifacts/reports/EDGE_REPORT.json)
  
  # Display metrics
  echo "Core Metrics:"
  echo "  net_bps:          $NET_BPS"
  echo "  gross_bps:        $GROSS_BPS"
  echo "  fees_eff_bps:     $FEES_BPS"
  echo ""
  
  echo "Performance Metrics:"
  echo "  slippage_p95:     $SLIPPAGE_P95 bps"
  echo "  adverse_p95:      $ADVERSE_P95 bps"
  echo "  cancel_ratio:     $CANCEL_RATIO"
  echo "  order_age_p95:    $ORDER_AGE_P95 ms"
  echo "  maker_share:      $MAKER_SHARE%"
  echo ""
  
  # Drivers
  NEG_DRIVERS=$(jq -r '.totals.neg_edge_drivers[]?' artifacts/reports/EDGE_REPORT.json)
  if [ -n "$NEG_DRIVERS" ]; then
    echo "Negative Edge Drivers:"
    echo "$NEG_DRIVERS" | sed 's/^/  - /'
    echo ""
  fi
  
  # Block reasons
  echo "Block Reasons:"
  jq -r '.totals.block_reasons | to_entries[] | "  \(.key): \(.value.ratio) (\(.value.count) blocks)"' \
    artifacts/reports/EDGE_REPORT.json
  echo ""
  
  # Final verdict
  echo "============================================="
  if (( $(echo "$NET_BPS >= 3.0" | bc -l) )); then
    echo "VERDICT: SUCCESS ✅"
    echo "  net_bps >= 3.0 achieved!"
    echo "  Next: Run 24h stability soak"
  elif (( $(echo "$NET_BPS >= 2.8" | bc -l) )); then
    echo "VERDICT: OK ⚠️"
    echo "  net_bps >= 2.8 (close to target)"
    echo "  Next: Review drivers, apply 1-2 adjustments, re-run 3h"
  elif (( $(echo "$NET_BPS >= 2.5" | bc -l) )); then
    echo "VERDICT: WARN ⚠️"
    echo "  net_bps >= 2.5 (needs tuning)"
    echo "  Next: Apply targeted package based on drivers"
  else
    echo "VERDICT: FAIL ❌"
    echo "  net_bps < 2.5 (significant issue)"
    echo "  Next: Review block reasons and component breakdown"
  fi
  echo "============================================="
else
  echo "WARN: EDGE_REPORT.json not found"
  echo "  Cannot display detailed metrics"
fi

# Display final overrides
echo ""
if [ -f "artifacts/soak/runtime_overrides.json" ]; then
  echo "Final Runtime Overrides:"
  jq -r 'to_entries[] | "  \(.key) = \(.value)"' artifacts/soak/runtime_overrides.json
fi

echo ""
echo "Artifacts saved to:"
echo "  artifacts/reports/EDGE_REPORT.json"
echo "  artifacts/reports/KPI_GATE.json"
echo "  artifacts/soak/runtime_overrides.json"
echo "  artifacts/soak/summary.txt"
echo ""

# Exit with soak test exit code
exit $EXIT_CODE

