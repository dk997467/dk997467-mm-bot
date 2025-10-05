# ==============================================================================
# KEEP_AWAKE.PS1
# ==============================================================================
# Purpose: Prevent Windows sleep/hibernation during long-running Soak tests
#          by manipulating power settings and using WinAPI SetThreadExecutionState
#
# Features:
#   - WinAPI stay-awake (P/Invoke SetThreadExecutionState)
#   - Power settings normalization (AC/DC profiles)
#   - Health diagnostics (powercfg /requests, /lastwake, event log)
#   - Idempotent and safe for repeated calls
#   - Optional disable via env flag
#
# Usage:
#   Import-Module .\tools\soak\keep_awake.ps1
#   Enable-StayAwake -Verbose
#   # ... run long test ...
#   Disable-StayAwake -Verbose
#
# ==============================================================================

# ==============================================================================
# WINAPI: SetThreadExecutionState
# ==============================================================================

Add-Type -TypeDefinition @"
using System;
using System.Runtime.InteropServices;

public class PowerUtil {
    [FlagsAttribute]
    public enum EXECUTION_STATE : uint {
        ES_SYSTEM_REQUIRED   = 0x00000001,
        ES_DISPLAY_REQUIRED  = 0x00000002,
        ES_USER_PRESENT      = 0x00000004,
        ES_AWAYMODE_REQUIRED = 0x00000040,
        ES_CONTINUOUS        = 0x80000000
    }

    [DllImport("kernel32.dll", CharSet = CharSet.Auto, SetLastError = true)]
    public static extern EXECUTION_STATE SetThreadExecutionState(EXECUTION_STATE esFlags);
}
"@ -ErrorAction SilentlyContinue

# ==============================================================================
# FUNCTION: Enable-StayAwake
# ==============================================================================
function Enable-StayAwake {
    [CmdletBinding()]
    param()
    
    Write-Host ""
    Write-Host "================================================"
    Write-Host "[STAY-AWAKE] Arming anti-sleep protection"
    Write-Host "================================================"
    
    try {
        # Request system + display to stay awake continuously
        $flags = [PowerUtil+EXECUTION_STATE]::ES_SYSTEM_REQUIRED -bor `
                 [PowerUtil+EXECUTION_STATE]::ES_DISPLAY_REQUIRED -bor `
                 [PowerUtil+EXECUTION_STATE]::ES_CONTINUOUS
        
        $result = [PowerUtil]::SetThreadExecutionState($flags)
        
        if ($result -eq 0) {
            Write-Host "[WARN] SetThreadExecutionState returned 0 (may have failed)"
            Write-Host "[WARN] GetLastError: $([System.Runtime.InteropServices.Marshal]::GetLastWin32Error())"
        } else {
            Write-Host "[OK] Stay-awake armed: SYSTEM_REQUIRED | DISPLAY_REQUIRED | CONTINUOUS"
        }
    } catch {
        Write-Host "[ERROR] Failed to arm stay-awake: $($_.Exception.Message)"
        Write-Host "[WARN] Continuing without WinAPI protection (system may sleep)"
    }
    
    Write-Host "================================================"
    Write-Host ""
}

# ==============================================================================
# FUNCTION: Disable-StayAwake
# ==============================================================================
function Disable-StayAwake {
    [CmdletBinding()]
    param()
    
    Write-Host ""
    Write-Host "================================================"
    Write-Host "[STAY-AWAKE] Disarming anti-sleep protection"
    Write-Host "================================================"
    
    try {
        # Return to normal power management
        $flags = [PowerUtil+EXECUTION_STATE]::ES_CONTINUOUS
        $result = [PowerUtil]::SetThreadExecutionState($flags)
        
        if ($result -eq 0) {
            Write-Host "[WARN] SetThreadExecutionState returned 0 (may have failed)"
        } else {
            Write-Host "[OK] Stay-awake disarmed (system can sleep normally)"
        }
    } catch {
        Write-Host "[ERROR] Failed to disarm stay-awake: $($_.Exception.Message)"
        Write-Host "[INFO] This is non-critical; system will return to normal on process exit"
    }
    
    Write-Host "================================================"
    Write-Host ""
}

# ==============================================================================
# FUNCTION: Set-PowerSettingsForSoak
# ==============================================================================
function Set-PowerSettingsForSoak {
    [CmdletBinding()]
    param()
    
    Write-Host ""
    Write-Host "================================================"
    Write-Host "[POWER] Normalizing power settings for Soak"
    Write-Host "================================================"
    
    # Get active power scheme
    try {
        $activeScheme = (powercfg /getactivescheme) -replace '.*GUID: ([a-f0-9\-]+).*', '$1'
        Write-Host "[INFO] Active power scheme: $activeScheme"
    } catch {
        Write-Host "[WARN] Could not detect active power scheme"
        $activeScheme = $null
    }
    
    # Helper function to set power setting (AC and DC)
    function Set-PowerSetting {
        param($SubGroup, $Setting, $Value, $Description)
        
        try {
            # AC (plugged in)
            powercfg /setacvalueindex $activeScheme $SubGroup $Setting $Value 2>&1 | Out-Null
            # DC (battery)
            powercfg /setdcvalueindex $activeScheme $SubGroup $Setting $Value 2>&1 | Out-Null
            Write-Host "[OK] $Description = $Value (AC/DC)"
        } catch {
            Write-Host "[SKIP] $Description (not supported or failed)"
        }
    }
    
    Write-Host ""
    Write-Host "--- Disabling sleep/hibernation timeouts ---"
    
    # Sleep timeout = 0 (never)
    Set-PowerSetting "SUB_SLEEP" "STANDBYIDLE" 0 "Sleep timeout"
    
    # Hibernate timeout = 0 (never)
    Set-PowerSetting "SUB_SLEEP" "HIBERNATEIDLE" 0 "Hibernate timeout"
    
    # Monitor timeout = 0 (never turn off display)
    Set-PowerSetting "SUB_VIDEO" "VIDEOIDLE" 0 "Monitor timeout"
    
    # Disk timeout = 0 (never spin down)
    Set-PowerSetting "SUB_DISK" "DISKIDLE" 0 "Disk timeout"
    
    Write-Host ""
    Write-Host "--- USB power settings ---"
    
    # USB selective suspend = Disabled
    Set-PowerSetting "SUB_USB" "USBSELECTIVESUSPEND" 0 "USB selective suspend"
    
    Write-Host ""
    Write-Host "--- Button/lid actions ---"
    
    # Lid close action = Do nothing (0)
    Set-PowerSetting "SUB_BUTTONS" "LIDACTION" 0 "Lid close action"
    
    # Power button action = Do nothing (0)
    Set-PowerSetting "SUB_BUTTONS" "PBUTTONACTION" 0 "Power button action"
    
    # Sleep button action = Do nothing (0)
    Set-PowerSetting "SUB_BUTTONS" "SBUTTONACTION" 0 "Sleep button action"
    
    # Apply changes
    try {
        powercfg /setactive $activeScheme 2>&1 | Out-Null
        Write-Host ""
        Write-Host "[OK] Power settings applied and activated"
    } catch {
        Write-Host "[WARN] Could not reactivate power scheme (changes may not be live)"
    }
    
    Write-Host "================================================"
    Write-Host ""
}

# ==============================================================================
# FUNCTION: Get-PowerHealthDiagnostics
# ==============================================================================
function Get-PowerHealthDiagnostics {
    [CmdletBinding()]
    param(
        [switch]$PreTest,
        [switch]$PostTest
    )
    
    Write-Host ""
    Write-Host "================================================"
    if ($PreTest) {
        Write-Host "[HEALTH] Power diagnostics (PRE-TEST)"
    } elseif ($PostTest) {
        Write-Host "[HEALTH] Power diagnostics (POST-TEST)"
    } else {
        Write-Host "[HEALTH] Power diagnostics"
    }
    Write-Host "================================================"
    
    # Active power requests
    Write-Host ""
    Write-Host "--- Active power requests ---"
    try {
        $requests = powercfg /requests 2>&1
        if ($requests) {
            $requests | ForEach-Object { Write-Host $_ }
        } else {
            Write-Host "(no active requests)"
        }
    } catch {
        Write-Host "[WARN] Could not query power requests"
    }
    
    # Last wake source (POST-TEST only)
    if ($PostTest) {
        Write-Host ""
        Write-Host "--- Last wake source ---"
        try {
            $lastWake = powercfg /lastwake 2>&1
            if ($lastWake) {
                $lastWake | ForEach-Object { Write-Host $_ }
            } else {
                Write-Host "(no wake history)"
            }
        } catch {
            Write-Host "[WARN] Could not query last wake source"
        }
        
        # Recent power events from System log
        Write-Host ""
        Write-Host "--- Recent power events (last 10) ---"
        try {
            $powerEventIds = @(1, 41, 42, 107, 506, 507, 1074, 6006, 6008)
            $events = Get-WinEvent -FilterHashtable @{
                LogName = 'System'
                Id = $powerEventIds
            } -MaxEvents 10 -ErrorAction SilentlyContinue | Sort-Object TimeCreated -Descending
            
            if ($events) {
                foreach ($evt in $events) {
                    $time = $evt.TimeCreated.ToString("yyyy-MM-dd HH:mm:ss")
                    $id = $evt.Id
                    $source = $evt.ProviderName
                    $msg = ($evt.Message -split "`n")[0]
                    if ($msg.Length -gt 80) { $msg = $msg.Substring(0, 77) + "..." }
                    Write-Host "  [$time] ID=$id ($source): $msg"
                }
            } else {
                Write-Host "(no recent power events)"
            }
        } catch {
            Write-Host "[WARN] Could not query power events: $($_.Exception.Message)"
        }
    }
    
    # Active power scheme
    Write-Host ""
    Write-Host "--- Active power scheme ---"
    try {
        powercfg /getactivescheme
    } catch {
        Write-Host "[WARN] Could not query active power scheme"
    }
    
    Write-Host "================================================"
    Write-Host ""
}

# ==============================================================================
# FUNCTION: Test-RunnerService
# ==============================================================================
function Test-RunnerService {
    [CmdletBinding()]
    param()
    
    Write-Host ""
    Write-Host "================================================"
    Write-Host "[RUNNER] Checking GitHub Actions Runner service"
    Write-Host "================================================"
    
    try {
        # Find runner service (usually named "actions.runner.*")
        $runnerServices = Get-Service -Name "actions.runner.*" -ErrorAction SilentlyContinue
        
        if ($runnerServices) {
            foreach ($svc in $runnerServices) {
                Write-Host "[INFO] Service: $($svc.Name)"
                Write-Host "       Status: $($svc.Status)"
                Write-Host "       StartType: $($svc.StartType)"
                
                # Check recovery options
                $sc_qfailure = sc.exe qfailure $svc.Name 2>&1
                if ($sc_qfailure -match "RESTART") {
                    Write-Host "       Recovery: Configured (auto-restart on failure)"
                } else {
                    Write-Host "       Recovery: Not configured"
                    Write-Host "       [TIP] Consider: sc.exe failure $($svc.Name) reset= 86400 actions= restart/60000/restart/60000/restart/60000"
                }
            }
        } else {
            Write-Host "[INFO] No GitHub Actions Runner service found"
            Write-Host "[INFO] This may be a manual runner setup"
        }
    } catch {
        Write-Host "[WARN] Could not query runner service: $($_.Exception.Message)"
    }
    
    Write-Host "================================================"
    Write-Host ""
}

# ==============================================================================
# EXPORTS
# ==============================================================================
Export-ModuleMember -Function Enable-StayAwake, Disable-StayAwake, Set-PowerSettingsForSoak, Get-PowerHealthDiagnostics, Test-RunnerService
