Param(
  [string]$Version = "v0.1.0",
  [switch]$Validate
)
$ErrorActionPreference = "Stop"
$ok = $true

Write-Host "[final-check] fast validator"
$env:CI_FAST="1"
$env:PYTEST_DISABLE_PLUGIN_AUTOLOAD="1"
try {
  python tools/ci/full_stack_validate.py --fast
} catch {
  $ok = $false
}

Write-Host "[final-check] soak-smoke"
try {
  python -m tools.ops.soak_run --shadow-hours 0.01 --canary-hours 0.01 --live-hours 0.02 --tz Europe/Berlin --out artifacts/soak_reports/smoke.json
} catch {
  $ok = $false
}

Write-Host "[final-check] morning"
try {
  powershell -ExecutionPolicy Bypass -File tools/ops/morning.ps1
} catch {
  $ok = $false
}

Write-Host "[final-check] release dry-run (fast)"
$argsList = @("scripts/release.py","--version",$Version,"--dry-run")
if ($Validate) { $argsList += "--validate" }
try {
  python @argsList
} catch {
  $ok = $false
}

if ($ok) { Write-Host "FINAL CHECK: GREEN"; exit 0 } else { Write-Host "FINAL CHECK: RED"; exit 1 }

