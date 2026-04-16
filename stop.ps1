$ErrorActionPreference = "SilentlyContinue"

$projectRoot = (Resolve-Path (Split-Path -Parent $MyInvocation.MyCommand.Path)).Path
$pidFile = Join-Path $projectRoot "data\web_console.pid"
$stopped = @()

if (Test-Path $pidFile) {
    $pidText = Get-Content $pidFile -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($pidText -and ($pidText -as [int])) {
        try {
            Stop-Process -Id ([int]$pidText) -Force -ErrorAction Stop
            $stopped += [int]$pidText
        } catch {
        }
    }
    Remove-Item $pidFile -Force -ErrorAction SilentlyContinue
}

$listener = Get-NetTCPConnection -LocalPort 8000 -State Listen -ErrorAction SilentlyContinue | Select-Object -First 1
if ($listener) {
    try {
        $proc = Get-CimInstance Win32_Process -Filter "ProcessId = $($listener.OwningProcess)"
        if ($proc -and $proc.CommandLine -like "*wfxl_openai_regst.py*") {
            Stop-Process -Id $listener.OwningProcess -Force -ErrorAction Stop
            $stopped += [int]$listener.OwningProcess
        }
    } catch {
    }
}

$stopped = $stopped | Sort-Object -Unique
if ($stopped.Count -gt 0) {
    Write-Output ("STOPPED_PID=" + ($stopped -join ","))
} else {
    Write-Output "STOPPED_PID=NONE"
}
