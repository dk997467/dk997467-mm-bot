#!/usr/bin/env pwsh
<#
.SYNOPSIS
    Pre-freeze sanity validator (PowerShell wrapper)

.DESCRIPTION
    Runs comprehensive pre-freeze sanity checks before production deployment.
    
    Validates:
    - Smoke tests (6 iterations)
    - Post-soak gates (8 iterations)
    - RUN isolation
    - Guards functionality
    - Prometheus metrics
    - Release bundle

.PARAMETER Src
    Source directory for soak artifacts (default: "artifacts/soak/latest")

.PARAMETER SmokeIters
    Number of smoke test iterations (default: 6)

.PARAMETER PostIters
    Number of post-soak test iterations (default: 8)

.PARAMETER RunIsolated
    Enable RUN isolation testing (creates RUN_<epoch> directories)

.EXAMPLE
    .\scripts\pre_freeze.ps1
    
    Runs with default parameters

.EXAMPLE
    .\scripts\pre_freeze.ps1 -Src "artifacts/soak/latest 1" -RunIsolated
    
    Runs with custom source and isolation enabled

.EXAMPLE
    .\scripts\pre_freeze.ps1 -SmokeIters 3 -PostIters 4
    
    Runs with reduced iteration counts (faster)

.NOTES
    Exit codes:
    0 = All checks PASS
    1 = Internal error
    2 = Post-soak KPI fail
    3 = Smoke test fail
    4 = Isolation fail
    5 = Guards fail
    6 = Metrics fail
    7 = Bundle fail
#>

param(
    [Parameter(Mandatory=$false)]
    [string]$Src = "artifacts/soak/latest",
    
    [Parameter(Mandatory=$false)]
    [int]$SmokeIters = 6,
    
    [Parameter(Mandatory=$false)]
    [int]$PostIters = 8,
    
    [Parameter(Mandatory=$false)]
    [switch]$RunIsolated
)

# Print banner
Write-Host ""
Write-Host ("=" * 80)
Write-Host "PRE-FREEZE SANITY VALIDATOR (PowerShell)"
Write-Host ("=" * 80)
Write-Host ""
Write-Host "Parameters:"
Write-Host "  Source:          $Src"
Write-Host "  Smoke iters:     $SmokeIters"
Write-Host "  Post-soak iters: $PostIters"
Write-Host "  RUN isolation:   $RunIsolated"
Write-Host ""
Write-Host ("=" * 80)
Write-Host ""

# Build command args
$pythonArgs = @(
    "-m", "tools.release.pre_freeze_sanity",
    "--src", $Src,
    "--smoke-iters", $SmokeIters,
    "--post-iters", $PostIters
)

if ($RunIsolated) {
    $pythonArgs += "--run-isolated"
}

# Run validator
try {
    & python $pythonArgs
    
    $exitCode = $LASTEXITCODE
    
    Write-Host ""
    Write-Host ("=" * 80)
    
    if ($exitCode -eq 0) {
        Write-Host "✅ PRE-FREEZE SANITY: PASS" -ForegroundColor Green
        Write-Host ""
        Write-Host "Ready for production freeze!" -ForegroundColor Green
    } else {
        Write-Host "❌ PRE-FREEZE SANITY: FAIL (exit code: $exitCode)" -ForegroundColor Red
        Write-Host ""
        
        switch ($exitCode) {
            1 {
                Write-Host "Internal error - check logs and retry" -ForegroundColor Yellow
            }
            2 {
                Write-Host "Post-soak KPI failure - review KPI thresholds" -ForegroundColor Yellow
            }
            3 {
                Write-Host "Smoke test failure - fix basic functionality" -ForegroundColor Yellow
            }
            4 {
                Write-Host "Isolation failure - check materialization logic" -ForegroundColor Yellow
            }
            5 {
                Write-Host "Guards failure - review guards module" -ForegroundColor Yellow
            }
            6 {
                Write-Host "Metrics failure - check Prometheus exporter" -ForegroundColor Yellow
            }
            7 {
                Write-Host "Bundle failure - check report generation" -ForegroundColor Yellow
            }
            default {
                Write-Host "Unknown exit code" -ForegroundColor Yellow
            }
        }
        
        Write-Host ""
        Write-Host "See: $Src/PRE_FREEZE_SANITY_SUMMARY.md" -ForegroundColor Cyan
    }
    
    Write-Host ("=" * 80)
    Write-Host ""
    
    exit $exitCode
}
catch {
    Write-Host ""
    Write-Host ("=" * 80)
    Write-Host "❌ FATAL ERROR" -ForegroundColor Red
    Write-Host ("=" * 80)
    Write-Host ""
    Write-Host $_.Exception.Message -ForegroundColor Red
    Write-Host ""
    exit 1
}

