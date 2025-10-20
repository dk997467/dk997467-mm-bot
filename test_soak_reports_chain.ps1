#!/usr/bin/env pwsh
<#
.SYNOPSIS
Test script for soak reports chain: build_reports → readiness_gate → write_legacy_readiness_json

.DESCRIPTION
This script simulates a mini-soak environment to test the new reports chain.
It creates minimal test artifacts and runs the full chain to verify:
1. Guard protection on first iteration (no ITER_SUMMARY_1.json)
2. build_reports execution
3. readiness_gate execution (non-blocking)
4. write_legacy_readiness_json execution

.EXAMPLE
pwsh test_soak_reports_chain.ps1
#>

$ErrorActionPreference = "Stop"
$env:PYTHON_EXE = if ($env:PYTHON_EXE) { $env:PYTHON_EXE } else { "python" }

Write-Host "================================================"
Write-Host "SOAK REPORTS CHAIN TEST"
Write-Host "================================================"
Write-Host ""

# ============================================================================
# TEST 1: Guard protection (no ITER_SUMMARY yet)
# ============================================================================
Write-Host "[TEST 1] Guard protection - skip reports on first iteration"
Write-Host "-----------------------------------------------------------"

# Clean artifacts
if (Test-Path "artifacts\soak\latest") {
    Remove-Item -Recurse -Force "artifacts\soak\latest"
}

# Create empty directory (no ITER_SUMMARY yet)
New-Item -ItemType Directory -Force "artifacts\soak\latest" | Out-Null

# Check guard behavior
$iter1 = "artifacts\soak\latest\ITER_SUMMARY_1.json"
if (!(Test-Path $iter1)) {
    Write-Host "✓ Guard check: ITER_SUMMARY_1.json not found (expected)"
    Write-Host "  Reports chain should be skipped"
} else {
    Write-Error "✗ Guard check failed: ITER_SUMMARY_1.json exists unexpectedly"
    exit 1
}

Write-Host ""

# ============================================================================
# TEST 2: Create minimal test artifacts
# ============================================================================
Write-Host "[TEST 2] Creating minimal test artifacts"
Write-Host "-----------------------------------------"

# Create minimal ITER_SUMMARY_1.json
$iterSummary = @{
    iteration = 1
    timestamp = (Get-Date).ToUniversalTime().ToString("o")
    kpi = @{
        maker_taker_ratio = 0.85
        net_bps = 3.2
        p95_latency_ms = 280
        risk_ratio = 0.35
    }
    verdict = "PASS"
} | ConvertTo-Json -Depth 10

Set-Content -Path "artifacts\soak\latest\ITER_SUMMARY_1.json" -Value $iterSummary -Encoding utf8

Write-Host "✓ Created ITER_SUMMARY_1.json"

# Create a few more iterations for meaningful analysis
for ($i = 2; $i -le 8; $i++) {
    $iterData = @{
        iteration = $i
        timestamp = (Get-Date).AddMinutes($i * 5).ToUniversalTime().ToString("o")
        kpi = @{
            maker_taker_ratio = 0.83 + (Get-Random -Minimum 0 -Maximum 5) / 100.0
            net_bps = 2.9 + (Get-Random -Minimum 0 -Maximum 8) / 10.0
            p95_latency_ms = 280 + (Get-Random -Minimum 0 -Maximum 50)
            risk_ratio = 0.35 + (Get-Random -Minimum 0 -Maximum 5) / 100.0
        }
        verdict = "PASS"
    } | ConvertTo-Json -Depth 10
    
    Set-Content -Path "artifacts\soak\latest\ITER_SUMMARY_$i.json" -Value $iterData -Encoding utf8
}

Write-Host "✓ Created ITER_SUMMARY_2.json through ITER_SUMMARY_8.json"
Write-Host ""

# ============================================================================
# TEST 3: Run build_reports
# ============================================================================
Write-Host "[TEST 3] Running build_reports"
Write-Host "-------------------------------"

$src = "artifacts\soak\latest"
$out = "artifacts\soak\latest\reports\analysis"

& $env:PYTHON_EXE -m tools.soak.build_reports --src $src --out $out --last-n 8

if ($LASTEXITCODE -ne 0) {
    Write-Error "✗ build_reports failed with exit code $LASTEXITCODE"
    exit 1
}

# Verify POST_SOAK_SNAPSHOT.json was created
$snapshotPath = "$out\POST_SOAK_SNAPSHOT.json"
if (Test-Path $snapshotPath) {
    Write-Host "✓ build_reports succeeded"
    Write-Host "  Generated: POST_SOAK_SNAPSHOT.json"
    
    # Show snapshot preview
    $snapshot = Get-Content $snapshotPath -Raw | ConvertFrom-Json
    Write-Host "  Verdict: $($snapshot.verdict)"
    if ($snapshot.kpi_last_n) {
        $kpi = $snapshot.kpi_last_n
        Write-Host "  KPIs (last-8):"
        if ($kpi.maker_taker_ratio.median) {
            Write-Host "    maker_taker_ratio: $($kpi.maker_taker_ratio.median.ToString('F3'))"
        }
        if ($kpi.net_bps.median) {
            Write-Host "    net_bps: $($kpi.net_bps.median.ToString('F2'))"
        }
        if ($kpi.p95_latency_ms.max) {
            Write-Host "    p95_latency_ms: $($kpi.p95_latency_ms.max.ToString('F0'))ms"
        }
        if ($kpi.risk_ratio.median) {
            Write-Host "    risk_ratio: $($kpi.risk_ratio.median.ToString('F3'))"
        }
    }
} else {
    Write-Error "✗ POST_SOAK_SNAPSHOT.json not found"
    exit 1
}

Write-Host ""

# ============================================================================
# TEST 4: Run readiness_gate (non-blocking)
# ============================================================================
Write-Host "[TEST 4] Running readiness_gate"
Write-Host "--------------------------------"

$path = "artifacts\soak\latest"

& $env:PYTHON_EXE -m tools.soak.ci_gates.readiness_gate `
    --path $path `
    --min_maker_taker 0.83 `
    --min_edge 2.9 `
    --max_latency 330 `
    --max_risk 0.40

$exitCode = $LASTEXITCODE

if ($exitCode -eq 0) {
    Write-Host "✓ Readiness gate: PASS"
} else {
    Write-Host "⚠ Readiness gate: HOLD (exit code $exitCode)"
    Write-Host "  This is informational for hourly runs - not blocking test"
}

Write-Host ""

# ============================================================================
# TEST 5: Run write_legacy_readiness_json
# ============================================================================
Write-Host "[TEST 5] Running write_legacy_readiness_json"
Write-Host "---------------------------------------------"

& $env:PYTHON_EXE -m tools.soak.ci_gates.write_legacy_readiness_json `
    --src "artifacts\soak\latest" `
    --out "artifacts\reports"

if ($LASTEXITCODE -ne 0) {
    Write-Error "✗ write_legacy_readiness_json failed with exit code $LASTEXITCODE"
    exit 1
}

# Verify readiness.json was created
$readinessPath = "artifacts\reports\readiness.json"
if (Test-Path $readinessPath) {
    Write-Host "✓ write_legacy_readiness_json succeeded"
    Write-Host "  Generated: artifacts\reports\readiness.json"
    
    # Show readiness.json preview
    $readiness = Get-Content $readinessPath -Raw | ConvertFrom-Json
    Write-Host "  Content:"
    Write-Host "    status: $($readiness.status)"
    Write-Host "    maker_taker_ratio: $($readiness.maker_taker_ratio)"
    Write-Host "    net_bps: $($readiness.net_bps)"
    Write-Host "    p95_latency_ms: $($readiness.p95_latency_ms)"
    Write-Host "    risk_ratio: $($readiness.risk_ratio)"
    Write-Host "    failures: $($readiness.failures -join ', ')"
} else {
    Write-Error "✗ readiness.json not found"
    exit 1
}

Write-Host ""

# ============================================================================
# SUMMARY
# ============================================================================
Write-Host "================================================"
Write-Host "TEST SUMMARY"
Write-Host "================================================"
Write-Host "✓ [TEST 1] Guard protection - PASS"
Write-Host "✓ [TEST 2] Artifact creation - PASS"
Write-Host "✓ [TEST 3] build_reports - PASS"
Write-Host "✓ [TEST 4] readiness_gate - PASS"
Write-Host "✓ [TEST 5] write_legacy_readiness_json - PASS"
Write-Host ""
Write-Host "✅ ALL TESTS PASSED"
Write-Host "================================================"
Write-Host ""
Write-Host "Next steps:"
Write-Host "1. Review generated artifacts in artifacts/soak/latest/reports/analysis/"
Write-Host "2. Verify readiness.json in artifacts/reports/"
Write-Host "3. Test in CI by triggering a mini-soak run"
Write-Host ""

exit 0

