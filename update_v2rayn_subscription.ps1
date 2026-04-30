param(
    [string]$V2rayNDir = (Get-Location).Path,
    [int]$StartupWaitSeconds = 8,
    [int]$UpdateWaitSeconds = 6,
    [switch]$HideAfter
)

$ErrorActionPreference = "Stop"

$exePath = Join-Path $V2rayNDir "v2rayN.exe"
if (-not (Test-Path $exePath)) {
    throw "v2rayN.exe not found: $exePath"
}

Add-Type @"
using System;
using System.Runtime.InteropServices;
public static class Win32Native {
    [DllImport("user32.dll")] public static extern bool ShowWindowAsync(IntPtr hWnd, int nCmdShow);
    [DllImport("user32.dll")] public static extern bool SetForegroundWindow(IntPtr hWnd);
    [DllImport("user32.dll")] public static extern bool IsIconic(IntPtr hWnd);
}
"@

$proc = Get-Process v2rayN -ErrorAction SilentlyContinue | Select-Object -First 1
if (-not $proc) {
    $proc = Start-Process -FilePath $exePath -WorkingDirectory $V2rayNDir -PassThru
    Start-Sleep -Seconds $StartupWaitSeconds
}

$deadline = (Get-Date).AddSeconds([Math]::Max(5, $StartupWaitSeconds))
do {
    try {
        $proc.Refresh()
    } catch {
    }
    if ($proc.MainWindowHandle -and $proc.MainWindowHandle -ne 0) {
        break
    }
    Start-Sleep -Milliseconds 500
} while ((Get-Date) -lt $deadline)

if (-not $proc.MainWindowHandle -or $proc.MainWindowHandle -eq 0) {
    throw "v2rayN main window handle not found."
}

if ([Win32Native]::IsIconic($proc.MainWindowHandle)) {
    [Win32Native]::ShowWindowAsync($proc.MainWindowHandle, 9) | Out-Null
} else {
    [Win32Native]::ShowWindowAsync($proc.MainWindowHandle, 5) | Out-Null
}
[Win32Native]::SetForegroundWindow($proc.MainWindowHandle) | Out-Null

Add-Type -AssemblyName Microsoft.VisualBasic
$wshell = New-Object -ComObject WScript.Shell
$activated = $false
try {
    [Microsoft.VisualBasic.Interaction]::AppActivate($proc.Id)
    $activated = $true
} catch {
}
if (-not $activated -and $proc.MainWindowTitle) {
    try {
        [Microsoft.VisualBasic.Interaction]::AppActivate($proc.MainWindowTitle)
        $activated = $true
    } catch {
    }
}
if (-not $activated) {
    throw "Failed to activate v2rayN window."
}

Start-Sleep -Milliseconds 700

# F10 focuses the top menu, Right moves to the second top-level menu
# (Subscriptions), Down opens it, the second Down highlights
# "Update all subscriptions", and Enter triggers it.
$wshell.SendKeys('{F10}')
Start-Sleep -Milliseconds 250
$wshell.SendKeys('{RIGHT}')
Start-Sleep -Milliseconds 250
$wshell.SendKeys('{DOWN}')
Start-Sleep -Milliseconds 250
$wshell.SendKeys('{DOWN}')
Start-Sleep -Milliseconds 250
$wshell.SendKeys('{ENTER}')

Start-Sleep -Seconds $UpdateWaitSeconds

if ($HideAfter) {
    [Win32Native]::ShowWindowAsync($proc.MainWindowHandle, 6) | Out-Null
}

Write-Output "UPDATED_SUBSCRIPTIONS=1"
