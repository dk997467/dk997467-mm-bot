Param()
$ErrorActionPreference = "Stop"
if (-not $env:TZ) { $env:TZ = "Europe/Berlin" }
Write-Host "[morning] TZ=$($env:TZ)"

Write-Host "[morning] 1/4 daily_check"
try { python -m tools.ops.daily_check | Out-Null } catch { }

Write-Host "[morning] 2/4 cron_sentinel"
python -m tools.ops.cron_sentinel --tz $env:TZ --window-hours 24

Write-Host "[morning] 3/4 daily digest"
$outDir = "artifacts/digest"
New-Item -ItemType Directory -Force -Path $outDir | Out-Null
$date = (Get-Date).ToString("yyyy-MM-dd")
$out = "$outDir/$date.json"
try {
  python -m tools.ops.daily_digest --out $out
} catch {
  try { python -m tools.ops.digest --out $out } catch {}
}

Write-Host "[morning] 4/4 archive"
python -m tools.ops.artifacts_archive --src artifacts

Write-Host "[morning] done"


