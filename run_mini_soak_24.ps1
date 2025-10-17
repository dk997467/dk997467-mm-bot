#
# Mini-Soak 24 Iterations — Full Pipeline (Windows)
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

$ErrorActionPreference = "Stop"

Write-Host "========================================================================"
Write-Host "MINI-SOAK 24 ITERATIONS — FULL PIPELINE"
Write-Host "========================================================================"
Write-Host "Start time: $(Get-Date -Format s)Z"
Write-Host ""

# Step 0: Clean old artifacts
Write-Host "[0/5] Cleaning old artifacts..."
if (Test-Path "artifacts\soak\latest") {
    Remove-Item -Recurse -Force "artifacts\soak\latest"
    Write-Host "  [OK] Removed artifacts\soak\latest"
}
Write-Host ""

# Step 1: Run mini-soak
Write-Host "[1/5] Running mini-soak (24 iterations, auto-tune, mock)..."
python -m tools.soak.run --iterations 24 --auto-tune --mock

if ($LASTEXITCODE -ne 0) {
    Write-Host "[FAIL] Mini-soak FAILED"
    exit 1
}

Write-Host "  [OK] Mini-soak completed"
Write-Host ""

# Step 2: Run soak gate (analyzer + extractor + delta verify + metrics)
Write-Host "[2/5] Running soak gate (full analysis + Prometheus, mock mode)..."
python -m tools.soak.soak_gate --path "artifacts\soak\latest" --prometheus --strict --mock

$gateExit = $LASTEXITCODE
Write-Host "  Soak gate exit code: $gateExit"

if ($gateExit -ne 0) {
    Write-Host "  [WARN] Soak gate returned non-zero (may indicate KPI/delta issues)"
}
Write-Host ""

# Step 3: Delta verification (explicit check)
Write-Host "[3/5] Running delta verifier (strict, JSON output)..."
python -m tools.soak.verify_deltas_applied --path "artifacts\soak\latest" --strict --json | Out-File "artifacts\soak\latest\DELTA_VERIFY.json" -Encoding utf8

$verifyExit = $LASTEXITCODE
Write-Host "  Delta verifier exit code: $verifyExit"

if ($verifyExit -eq 0) {
    Write-Host "  [OK] Delta verification PASSED"
} else {
    Write-Host "  [FAIL] Delta verification FAILED"
}
Write-Host ""

# Step 4: Extract snapshot (pretty print for review)
Write-Host "[4/5] Extracting post-soak snapshot (pretty mode)..."
python -m tools.soak.extract_post_soak_snapshot --path "artifacts\soak\latest" --pretty | Out-File "artifacts\soak\latest\POST_SOAK_SNAPSHOT_PRETTY.json" -Encoding utf8

Write-Host "  [OK] Snapshot extracted"
Write-Host ""

# Step 5: Display summary
Write-Host "[5/5] Displaying summary..."
Write-Host ""
Write-Host "========================================================================"
Write-Host "RESULTS SUMMARY"
Write-Host "========================================================================"

# Parse key metrics from snapshot
$snapshotFile = "artifacts\soak\latest\POST_SOAK_SNAPSHOT.json"
$deltaFile = "artifacts\soak\latest\DELTA_VERIFY.json"

if (Test-Path $snapshotFile) {
    Write-Host "KPI Metrics (last 8 iterations):"
    
    $snap = Get-Content $snapshotFile | ConvertFrom-Json
    $kpi = $snap.kpi_last8
    
    $makerTaker = [math]::Round($kpi.maker_taker_ratio.mean, 3)
    $risk = [math]::Round($kpi.risk_ratio.mean, 3)
    $netBps = [math]::Round($kpi.net_bps.mean, 2)
    $latency = [math]::Round($kpi.p95_latency_ms.mean, 1)
    
    Write-Host "  • maker_taker_ratio: $makerTaker"
    Write-Host "  • risk_ratio:        $risk"
    Write-Host "  • net_bps:           $netBps"
    Write-Host "  • p95_latency_ms:    $latency"
    Write-Host ""
    Write-Host "Verdict:      $($snap.verdict)"
    Write-Host "Freeze Ready: $($snap.freeze_ready)"
    Write-Host "Pass Count:   $($snap.pass_count_last8)/8"
}

Write-Host ""

if (Test-Path $deltaFile) {
    Write-Host "Delta Quality:"
    
    $delta = Get-Content $deltaFile | ConvertFrom-Json
    
    Write-Host "  • full_apply_ratio:       $($delta.full_apply_ratio)"
    Write-Host "  • full_apply_count:       $($delta.full_apply_count)"
    Write-Host "  • partial_ok_count:       $($delta.partial_ok_count)"
    Write-Host "  • fail_count:             $($delta.fail_count)"
    Write-Host "  • signature_stuck_count:  $($delta.signature_stuck_count)"
}

Write-Host ""
Write-Host "========================================================================"
Write-Host "ARTIFACTS GENERATED"
Write-Host "========================================================================"
Write-Host "  • POST_SOAK_AUDIT.md          — Human-readable audit"
Write-Host "  • POST_SOAK_SNAPSHOT.json     — Machine-readable snapshot"
Write-Host "  • POST_SOAK_METRICS.prom      — Prometheus metrics"
Write-Host "  • DELTA_VERIFY_REPORT.md      — Delta verification report"
Write-Host "  • DELTA_VERIFY.json           — Delta metrics (JSON)"
Write-Host "  • ITER_SUMMARY_*.json         — Per-iteration summaries"
Write-Host "  • TUNING_REPORT.json          — Cumulative tuning report"
Write-Host ""

# Final exit code
if ($verifyExit -eq 0 -and $gateExit -eq 0) {
    Write-Host "[OK] PIPELINE PASSED"
    Write-Host ""
    Write-Host "End time: $(Get-Date -Format s)Z"
    exit 0
} elseif ($verifyExit -eq 0) {
    Write-Host "[WARN] PIPELINE: Delta OK, but gate issues detected"
    Write-Host ""
    Write-Host "End time: $(Get-Date -Format s)Z"
    exit 1
} else {
    Write-Host "[FAIL] PIPELINE FAILED"
    Write-Host ""
    Write-Host "End time: $(Get-Date -Format s)Z"
    exit 1
}

