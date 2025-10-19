#!/bin/bash
#
# Mini-Soak 24 Iterations — Full Pipeline
#
# Runs:
# 1. Mini-soak 24 iterations with auto-tuning (mock mode)
# 2. Post-soak analysis + snapshot
# 3. Delta verification (strict mode)
# 4. Soak gate with Prometheus metrics
#
# Expected results:
# - maker_taker_ratio.mean ≥ 0.80 (target: ≥0.85)
# - risk_ratio.mean ≤ 0.40
# - net_bps.mean ≥ 2.9
# - p95_latency_ms.mean ≤ 340
# - full_apply_ratio ≥ 0.95
# - signature_stuck_count ≤ 1
# - freeze_ready = true

set -euo pipefail

echo "========================================================================"
echo "MINI-SOAK 24 ITERATIONS — FULL PIPELINE"
echo "========================================================================"
echo "Start time: $(date -Iseconds)"
echo ""

# Step 0: Clean old artifacts
echo "[0/5] Cleaning old artifacts..."
if [ -d "artifacts/soak/latest" ]; then
    rm -rf artifacts/soak/latest
    echo "  ✓ Removed artifacts/soak/latest"
fi
echo ""

# Step 1: Run mini-soak
echo "[1/5] Running mini-soak (24 iterations, auto-tune, mock)..."
python -m tools.soak.run --iterations 24 --auto-tune --mock

if [ $? -ne 0 ]; then
    echo "❌ Mini-soak FAILED"
    exit 1
fi

echo "  ✓ Mini-soak completed"
echo ""

# Step 2: Run soak gate (analyzer + extractor + delta verify + metrics)
echo "[2/5] Running soak gate (full analysis + Prometheus, mock mode)..."
python -m tools.soak.soak_gate --path "artifacts/soak/latest" --prometheus --strict --mock

GATE_EXIT=$?
echo "  Soak gate exit code: $GATE_EXIT"

if [ $GATE_EXIT -ne 0 ]; then
    echo "⚠️  Soak gate returned non-zero (may indicate KPI/delta issues)"
fi
echo ""

# Step 3: Delta verification (explicit check)
echo "[3/5] Running delta verifier (strict, JSON output)..."
python -m tools.soak.verify_deltas_applied --path "artifacts/soak/latest" --strict --json > artifacts/soak/latest/DELTA_VERIFY.json

VERIFY_EXIT=$?
echo "  Delta verifier exit code: $VERIFY_EXIT"

if [ $VERIFY_EXIT -eq 0 ]; then
    echo "  ✓ Delta verification PASSED"
else
    echo "  ❌ Delta verification FAILED"
fi
echo ""

# Step 4: Extract snapshot (pretty print for review)
echo "[4/5] Extracting post-soak snapshot (pretty mode)..."
python -m tools.soak.extract_post_soak_snapshot --path "artifacts/soak/latest" --pretty > artifacts/soak/latest/POST_SOAK_SNAPSHOT_PRETTY.json

echo "  ✓ Snapshot extracted"
echo ""

# Step 5: Display summary
echo "[5/5] Displaying summary..."
echo ""
echo "========================================================================"
echo "RESULTS SUMMARY"
echo "========================================================================"

# Parse key metrics from snapshot
SNAPSHOT_FILE="artifacts/soak/latest/POST_SOAK_SNAPSHOT.json"
DELTA_FILE="artifacts/soak/latest/DELTA_VERIFY.json"

if [ -f "$SNAPSHOT_FILE" ]; then
    echo "KPI Metrics (last 8 iterations):"
    python3 << 'PYEOF'
import json
with open("artifacts/soak/latest/POST_SOAK_SNAPSHOT.json") as f:
    snap = json.load(f)

kpi = snap.get("kpi_last8", {})
print(f"  • maker_taker_ratio: {kpi.get('maker_taker_ratio', {}).get('mean', 'N/A'):.3f}")
print(f"  • risk_ratio:        {kpi.get('risk_ratio', {}).get('mean', 'N/A'):.3f}")
print(f"  • net_bps:           {kpi.get('net_bps', {}).get('mean', 'N/A'):.2f}")
print(f"  • p95_latency_ms:    {kpi.get('p95_latency_ms', {}).get('mean', 'N/A'):.1f}")
print()
print(f"Verdict:      {snap.get('verdict', 'UNKNOWN')}")
print(f"Freeze Ready: {snap.get('freeze_ready', False)}")
print(f"Pass Count:   {snap.get('pass_count_last8', 0)}/8")
PYEOF
fi

echo ""

if [ -f "$DELTA_FILE" ]; then
    echo "Delta Quality:"
    python3 << 'PYEOF'
import json
with open("artifacts/soak/latest/DELTA_VERIFY.json") as f:
    delta = json.load(f)

print(f"  • full_apply_ratio:       {delta.get('full_apply_ratio', 0):.3f}")
print(f"  • full_apply_count:       {delta.get('full_apply_count', 0)}")
print(f"  • partial_ok_count:       {delta.get('partial_ok_count', 0)}")
print(f"  • fail_count:             {delta.get('fail_count', 0)}")
print(f"  • signature_stuck_count:  {delta.get('signature_stuck_count', 0)}")
PYEOF
fi

echo ""
echo "========================================================================"
echo "ARTIFACTS GENERATED"
echo "========================================================================"
echo "  • POST_SOAK_AUDIT.md          — Human-readable audit"
echo "  • POST_SOAK_SNAPSHOT.json     — Machine-readable snapshot"
echo "  • POST_SOAK_METRICS.prom      — Prometheus metrics"
echo "  • DELTA_VERIFY_REPORT.md      — Delta verification report"
echo "  • DELTA_VERIFY.json           — Delta metrics (JSON)"
echo "  • ITER_SUMMARY_*.json         — Per-iteration summaries"
echo "  • TUNING_REPORT.json          — Cumulative tuning report"
echo ""

# Final exit code
if [ $VERIFY_EXIT -eq 0 ] && [ $GATE_EXIT -eq 0 ]; then
    echo "✅ PIPELINE PASSED"
    echo ""
    echo "End time: $(date -Iseconds)"
    exit 0
elif [ $VERIFY_EXIT -eq 0 ]; then
    echo "⚠️  PIPELINE: Delta OK, but gate issues detected"
    echo ""
    echo "End time: $(date -Iseconds)"
    exit 1
else
    echo "❌ PIPELINE FAILED"
    echo ""
    echo "End time: $(date -Iseconds)"
    exit 1
fi

