# Soak Test Anti-Sleep Protection

## Overview

This document describes the anti-sleep protection system for Windows Soak Tests, designed to prevent "runner lost communication" failures caused by Windows power management, sleep, or hibernation during long-running (24-72h) test runs.

## Problem Statement

Windows self-hosted runners may:
- Enter sleep (S3) or hibernation after inactivity timeout
- Disconnect network adapters (Wi-Fi power saving, USB selective suspend)
- Restart for Windows Update outside "active hours"
- Lose communication with GitHub Actions due to display/system power-down

This causes Soak Tests to fail intermittently with "runner lost communication" errors, even when tests themselves are passing.

## Solution

### Components

1. **`tools/soak/keep_awake.ps1`** - PowerShell module with:
   - WinAPI `SetThreadExecutionState` P/Invoke (prevent sleep/hibernation)
   - Power settings normalization via `powercfg` (AC/DC profiles)
   - Health diagnostics (`powercfg /requests`, `/lastwake`, Event Log)
   - Runner service health check

2. **`.github/workflows/soak-windows.yml`** - Integration:
   - Prologue: Enable anti-sleep, normalize power settings, pre-test diagnostics
   - Epilogue: Disable anti-sleep, post-test diagnostics (wake history, power events)
   - Env flag `SOAK_STAY_AWAKE` (default: 1) to enable/disable

### Features

#### WinAPI Stay-Awake

```powershell
# Arm (prevent sleep)
SetThreadExecutionState(ES_SYSTEM_REQUIRED | ES_DISPLAY_REQUIRED | ES_CONTINUOUS)

# Disarm (allow sleep)
SetThreadExecutionState(ES_CONTINUOUS)
```

#### Power Settings Normalization

```powershell
# All timeouts → 0 (never)
- Sleep timeout
- Hibernate timeout
- Monitor timeout
- Disk spin-down timeout

# USB settings
- USB selective suspend → Disabled

# Button/Lid actions
- Lid close → Do nothing
- Power button → Do nothing
- Sleep button → Do nothing
```

#### Health Diagnostics

**Pre-test:**
- Active power scheme
- Active power requests (`powercfg /requests`)
- Runner service status and recovery settings

**Post-test:**
- Last wake source (`powercfg /lastwake`)
- Recent power events (Event IDs: 1, 41, 42, 107, 506, 507, 1074, 6006, 6008)
- Wake history analysis

## Usage

### Default Behavior (Enabled)

```yaml
# Automatically enabled for all Soak runs
env:
  SOAK_STAY_AWAKE: "1"  # default
```

### Disable Anti-Sleep (Testing)

**Option 1: Manual workflow_dispatch**
```
Actions → Soak (Windows self-hosted, 24-72h) → Run workflow
  → stay_awake: 0
```

**Option 2: Modify workflow env**
```yaml
env:
  SOAK_STAY_AWAKE: "0"
```

## Verification

### Log Markers

**Successful initialization:**
```
###############################################
# ANTI-SLEEP INITIALIZATION
###############################################
[INFO] SOAK_STAY_AWAKE=1 - Anti-sleep protection ENABLED
[INFO] Loading keep_awake module...
[OK] Module loaded successfully

[STAY-AWAKE] Arming anti-sleep protection
[OK] Stay-awake armed: SYSTEM_REQUIRED | DISPLAY_REQUIRED | CONTINUOUS

[POWER] Normalizing power settings for Soak
[OK] Sleep timeout = 0 (AC/DC)
[OK] Monitor timeout = 0 (AC/DC)
...

[HEALTH] Power diagnostics (PRE-TEST)
--- Active power requests ---
DISPLAY:
  [PROCESS] pwsh.exe
SYSTEM:
  [PROCESS] pwsh.exe
...
```

**Successful cleanup:**
```
###############################################
# ANTI-SLEEP CLEANUP
###############################################
[HEALTH] Power diagnostics (POST-TEST)
--- Last wake source ---
Wake Source: Power Button

--- Recent power events (last 10) ---
  [2025-01-05 12:00:00] ID=1 (Power-Troubleshooter): System resumed from sleep
  [2025-01-05 06:00:00] ID=42 (Kernel-Power): System entering sleep

[STAY-AWAKE] Disarming anti-sleep protection
[OK] Stay-awake disarmed (system can sleep normally)
```

### Summary File

```
artifacts/soak/summary.txt:
  ...
  Duration: 24 hours
  Anti-sleep protection: ENABLED
  ...
```

## Idempotency & Error Handling

All operations are wrapped in try-catch blocks:
- Module load failure → Warning, continue without protection
- WinAPI failure → Warning, log GetLastError, continue
- powercfg unsupported setting → Skip with info message
- Missing diagnostics → Warn, continue

Repeated calls are safe (module re-import, state reset).

## Network Stability

**Recommendations (logged, not enforced):**
- Prefer Ethernet over Wi-Fi for runners
- For Wi-Fi: Disable "Allow computer to turn off device to save power" in adapter settings
- Ensure runner service has auto-recovery configured

**Service recovery setup (manual, if needed):**
```powershell
sc.exe failure actions.runner.YOUR_RUNNER `
  reset= 86400 `
  actions= restart/60000/restart/60000/restart/60000
```

## Troubleshooting

### Runner still loses connection

1. Check logs for "ANTI-SLEEP INITIALIZATION" block
2. Verify `SOAK_STAY_AWAKE=1` in summary.txt
3. Check pre-test diagnostics for active power requests
4. Review post-test wake history for unexpected wakes
5. Check Windows Event Log (System) for IDs 1, 41, 42, 107

### SetThreadExecutionState returns 0

```
[WARN] SetThreadExecutionState returned 0 (may have failed)
[WARN] GetLastError: 5
```
→ Likely insufficient permissions. Run runner as Administrator or Local System.

### Power settings not applying

```
[SKIP] Sleep timeout (not supported or failed)
```
→ Some settings may not be available on specific Windows editions (e.g., Home vs Pro).
→ Non-critical; WinAPI stay-awake still provides protection.

## References

- [SetThreadExecutionState (Microsoft Docs)](https://learn.microsoft.com/en-us/windows/win32/api/winbase/nf-winbase-setthreadexecutionstate)
- [powercfg Command-Line Options](https://learn.microsoft.com/en-us/windows-hardware/design/device-experiences/powercfg-command-line-options)
- [Windows Power Management Events](https://learn.microsoft.com/en-us/windows/win32/power/power-management-events)

## Acceptance Criteria

✅ Logs contain "[OK] Stay-awake armed: SYSTEM_REQUIRED | DISPLAY_REQUIRED | CONTINUOUS"  
✅ No "runner lost communication" during soak window  
✅ Iterations complete without power-related interruptions  
✅ Finalization completes with exit code 0  
✅ `SOAK_STAY_AWAKE=0` disables protection without errors  
✅ Post-test diagnostics show wake history and power events
