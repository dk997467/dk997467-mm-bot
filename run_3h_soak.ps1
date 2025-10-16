#!/usr/bin/env pwsh
<#
.SYNOPSIS
    Run 3-hour mini-soak with auto-tuning to achieve net_bps >= 3.0

.DESCRIPTION
    This script runs a 3-hour soak test (6 iterations x 30min) with:
    - Profile S1 loaded
    - Auto-tuning enabled (driver-aware adjustments)
    - Conservative baseline overrides (see artifacts/soak/runtime_overrides.json)
    - Diagnostic artifacts saved per iteration

.EXAMPLE
    .\run_3h_soak.ps1
#>

[CmdletBinding()]
param()

# ============================================================================
# CONFIGURATION
# ============================================================================

$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"

# Environment
$env:MM_PROFILE = "S1"
$env:SOAK_HOURS = "3"
$env:PYTHONPATH = "$PWD;$PWD\src"
$env:PYTEST_DISABLE_PLUGIN_AUTOLOAD = "1"

# Python executable (auto-detect or use configured)
$python = if ($env:PYTHON_EXE) { $env:PYTHON_EXE } else { "python" }

# ============================================================================
# PRE-FLIGHT CHECKS
# ============================================================================

Write-Host "=============================================" -ForegroundColor Cyan
Write-Host "3-HOUR SOAK TEST: Path to net_bps >= 3.0" -ForegroundColor Cyan
Write-Host "=============================================" -ForegroundColor Cyan
Write-Host ""

# Check Python
Write-Host "[CHECK] Python..." -NoNewline
try {
    $pythonVersion = & $python --version 2>&1
    Write-Host " OK ($pythonVersion)" -ForegroundColor Green
} catch {
    Write-Host " ERROR" -ForegroundColor Red
    Write-Host "  Python not found or not working"
    exit 1
}

# Check profile exists
Write-Host "[CHECK] Profile S1..." -NoNewline
if (Test-Path "config/profiles/market_maker_S1.json") {
    Write-Host " OK" -ForegroundColor Green
} else {
    Write-Host " ERROR" -ForegroundColor Red
    Write-Host "  config/profiles/market_maker_S1.json not found"
    exit 1
}

# Check runtime overrides
Write-Host "[CHECK] Runtime overrides..." -NoNewline
if (Test-Path "artifacts/soak/runtime_overrides.json") {
    Write-Host " OK" -ForegroundColor Green
    
    # Display current overrides
    $overrides = Get-Content "artifacts/soak/runtime_overrides.json" | ConvertFrom-Json
    Write-Host "  Baseline overrides:" -ForegroundColor Gray
    $overrides.PSObject.Properties | ForEach-Object {
        Write-Host "    $($_.Name) = $($_.Value)" -ForegroundColor Gray
    }
} else {
    Write-Host " WARN" -ForegroundColor Yellow
    Write-Host "  artifacts/soak/runtime_overrides.json not found (will use defaults)"
}

Write-Host ""

# ============================================================================
# RUN 3-HOUR SOAK
# ============================================================================

Write-Host "=============================================" -ForegroundColor Cyan
Write-Host "STARTING 3-HOUR SOAK (6 iterations x 30min)" -ForegroundColor Cyan
Write-Host "=============================================" -ForegroundColor Cyan
Write-Host ""

$startTime = Get-Date

try {
    & $python -m tools.soak.run `
        --hours 3 `
        --iterations 6 `
        --auto-tune `
        --export-json artifacts/reports/soak_metrics.json `
        --export-md artifacts/reports/SOAK_RESULTS.md `
        --gate-summary artifacts/reports/gates_summary.json
    
    $exitCode = $LASTEXITCODE
} catch {
    Write-Host ""
    Write-Host "ERROR: Soak test crashed" -ForegroundColor Red
    Write-Host $_.Exception.Message -ForegroundColor Red
    exit 1
}

$endTime = Get-Date
$duration = $endTime - $startTime

Write-Host ""
Write-Host "=============================================" -ForegroundColor Cyan
Write-Host "SOAK TEST COMPLETED" -ForegroundColor Cyan
Write-Host "=============================================" -ForegroundColor Cyan
Write-Host ""
Write-Host "Duration: $($duration.ToString('hh\:mm\:ss'))"
Write-Host "Exit code: $exitCode"
Write-Host ""

# ============================================================================
# POST-SOAK ANALYSIS
# ============================================================================

if ($exitCode -ne 0) {
    Write-Host "=============================================" -ForegroundColor Red
    Write-Host "SOAK TEST FAILED" -ForegroundColor Red
    Write-Host "=============================================" -ForegroundColor Red
    Write-Host ""
    Write-Host "Check artifacts/soak/summary.txt for details" -ForegroundColor Yellow
    exit $exitCode
}

# Generate EDGE_REPORT if not already generated
if (-not (Test-Path "artifacts/reports/EDGE_REPORT.json")) {
    Write-Host "[POST-SOAK] Generating EDGE_REPORT with diagnostics..." -ForegroundColor Cyan
    
    try {
        & $python -m tools.reports.edge_report `
            --inputs artifacts/EDGE_REPORT.json `
            --audit artifacts/soak/audit.jsonl `
            --out-json artifacts/reports/EDGE_REPORT.json
        
        if ($LASTEXITCODE -eq 0) {
            Write-Host "  [OK] EDGE_REPORT.json generated" -ForegroundColor Green
        } else {
            Write-Host "  [WARN] EDGE_REPORT generation failed (non-critical)" -ForegroundColor Yellow
        }
    } catch {
        Write-Host "  [WARN] EDGE_REPORT generation failed (non-critical)" -ForegroundColor Yellow
    }
}

# ============================================================================
# RESULTS SUMMARY
# ============================================================================

Write-Host ""
Write-Host "=============================================" -ForegroundColor Cyan
Write-Host "RESULTS SUMMARY" -ForegroundColor Cyan
Write-Host "=============================================" -ForegroundColor Cyan
Write-Host ""

# Check if EDGE_REPORT exists
if (Test-Path "artifacts/reports/EDGE_REPORT.json") {
    try {
        $report = Get-Content "artifacts/reports/EDGE_REPORT.json" | ConvertFrom-Json
        $totals = $report.totals
        
        # Extract key metrics
        $net_bps = [math]::Round($totals.net_bps, 2)
        $gross_bps = [math]::Round($totals.gross_bps, 2)
        $fees_bps = [math]::Round($totals.fees_eff_bps, 2)
        $slippage_p95 = [math]::Round($totals.slippage_bps_p95, 2)
        $adverse_p95 = [math]::Round($totals.adverse_bps_p95, 2)
        $cancel_ratio = [math]::Round($totals.cancel_ratio, 3)
        $order_age_p95 = [math]::Round($totals.order_age_p95_ms, 0)
        $maker_share = [math]::Round($totals.maker_share_pct, 1)
        
        # Display metrics
        Write-Host "Core Metrics:" -ForegroundColor White
        Write-Host "  net_bps:          $net_bps" -ForegroundColor $(if ($net_bps -ge 3.0) { "Green" } elseif ($net_bps -ge 2.8) { "Yellow" } else { "Red" })
        Write-Host "  gross_bps:        $gross_bps" -ForegroundColor Gray
        Write-Host "  fees_eff_bps:     $fees_bps" -ForegroundColor Gray
        Write-Host ""
        
        Write-Host "Performance Metrics:" -ForegroundColor White
        Write-Host "  slippage_p95:     $slippage_p95 bps" -ForegroundColor $(if ($slippage_p95 -le 3.0) { "Green" } else { "Yellow" })
        Write-Host "  adverse_p95:      $adverse_p95 bps" -ForegroundColor $(if ($adverse_p95 -le 4.0) { "Green" } else { "Yellow" })
        Write-Host "  cancel_ratio:     $cancel_ratio" -ForegroundColor $(if ($cancel_ratio -le 0.55) { "Green" } else { "Yellow" })
        Write-Host "  order_age_p95:    $order_age_p95 ms" -ForegroundColor $(if ($order_age_p95 -le 330) { "Green" } else { "Yellow" })
        Write-Host "  maker_share:      $maker_share%" -ForegroundColor $(if ($maker_share -ge 85.0) { "Green" } else { "Yellow" })
        Write-Host ""
        
        # Drivers
        $drivers = $totals.neg_edge_drivers
        if ($drivers -and $drivers.Count -gt 0) {
            Write-Host "Negative Edge Drivers:" -ForegroundColor Yellow
            $drivers | ForEach-Object {
                Write-Host "  - $_" -ForegroundColor Yellow
            }
            Write-Host ""
        }
        
        # Block reasons
        $block_reasons = $totals.block_reasons
        if ($block_reasons) {
            Write-Host "Block Reasons:" -ForegroundColor White
            $block_reasons.PSObject.Properties | ForEach-Object {
                $ratio = [math]::Round($_.Value.ratio, 3)
                $count = $_.Value.count
                $color = if ($ratio -gt 0.4) { "Red" } elseif ($ratio -gt 0.3) { "Yellow" } else { "Gray" }
                Write-Host "  $($_.Name): $ratio ($count blocks)" -ForegroundColor $color
            }
            Write-Host ""
        }
        
        # Final verdict
        Write-Host "=============================================" -ForegroundColor Cyan
        if ($net_bps -ge 3.0) {
            Write-Host "VERDICT: SUCCESS ✅" -ForegroundColor Green
            Write-Host "  net_bps >= 3.0 achieved!" -ForegroundColor Green
            Write-Host "  Next: Run 24h stability soak" -ForegroundColor Cyan
        } elseif ($net_bps -ge 2.8) {
            Write-Host "VERDICT: OK ⚠️" -ForegroundColor Yellow
            Write-Host "  net_bps >= 2.8 (close to target)" -ForegroundColor Yellow
            Write-Host "  Next: Review drivers, apply 1-2 adjustments, re-run 3h" -ForegroundColor Cyan
        } elseif ($net_bps -ge 2.5) {
            Write-Host "VERDICT: WARN ⚠️" -ForegroundColor Yellow
            Write-Host "  net_bps >= 2.5 (needs tuning)" -ForegroundColor Yellow
            Write-Host "  Next: Apply targeted package based on drivers" -ForegroundColor Cyan
        } else {
            Write-Host "VERDICT: FAIL ❌" -ForegroundColor Red
            Write-Host "  net_bps < 2.5 (significant issue)" -ForegroundColor Red
            Write-Host "  Next: Review block reasons and component breakdown" -ForegroundColor Cyan
        }
        Write-Host "=============================================" -ForegroundColor Cyan
        
    } catch {
        Write-Host "ERROR: Failed to parse EDGE_REPORT.json" -ForegroundColor Red
        Write-Host $_.Exception.Message -ForegroundColor Red
    }
} else {
    Write-Host "WARN: EDGE_REPORT.json not found" -ForegroundColor Yellow
    Write-Host "  Cannot display detailed metrics" -ForegroundColor Yellow
}

# Display final overrides
Write-Host ""
if (Test-Path "artifacts/soak/runtime_overrides.json") {
    Write-Host "Final Runtime Overrides:" -ForegroundColor Cyan
    $finalOverrides = Get-Content "artifacts/soak/runtime_overrides.json" | ConvertFrom-Json
    $finalOverrides.PSObject.Properties | ForEach-Object {
        Write-Host "  $($_.Name) = $($_.Value)" -ForegroundColor Gray
    }
}

Write-Host ""
Write-Host "Artifacts saved to:" -ForegroundColor Cyan
Write-Host "  artifacts/reports/EDGE_REPORT.json" -ForegroundColor Gray
Write-Host "  artifacts/reports/KPI_GATE.json" -ForegroundColor Gray
Write-Host "  artifacts/soak/runtime_overrides.json" -ForegroundColor Gray
Write-Host "  artifacts/soak/summary.txt" -ForegroundColor Gray
Write-Host ""

# Exit with soak test exit code
exit $exitCode

