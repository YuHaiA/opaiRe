$ErrorActionPreference = "SilentlyContinue"

$projectRoot = (Resolve-Path (Split-Path -Parent $MyInvocation.MyCommand.Path)).Path
$pidFile = Join-Path $projectRoot "data\web_console.pid"
$stopped = @()

function Stop-OpaiReProcessById {
    param(
        [int]$ProcessId
    )

    if (-not $ProcessId) {
        return
    }

    try {
        Stop-Process -Id $ProcessId -Force -ErrorAction Stop
        $script:stopped += [int]$ProcessId
    } catch {
    }
}

if (Test-Path $pidFile) {
    $pidText = Get-Content $pidFile -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($pidText -and ($pidText -as [int])) {
        Stop-OpaiReProcessById -ProcessId ([int]$pidText)
    }
    Remove-Item $pidFile -Force -ErrorAction SilentlyContinue
}

$listener = Get-NetTCPConnection -LocalPort 8000 -State Listen -ErrorAction SilentlyContinue | Select-Object -First 1
if ($listener) {
    try {
        $proc = Get-CimInstance Win32_Process -Filter "ProcessId = $($listener.OwningProcess)"
        if ($proc -and $proc.CommandLine -like "*wfxl_openai_regst.py*") {
            Stop-OpaiReProcessById -ProcessId $listener.OwningProcess
        }
    } catch {
    }
}

$allOpaiReProcesses = Get-CimInstance Win32_Process -ErrorAction SilentlyContinue |
    Where-Object {
        $_.CommandLine -and $_.CommandLine -like "*wfxl_openai_regst.py*"
    }

foreach ($proc in $allOpaiReProcesses) {
    Stop-OpaiReProcessById -ProcessId $proc.ProcessId
}

Start-Sleep -Seconds 1

$stopped = $stopped | Sort-Object -Unique
if ($stopped.Count -gt 0) {
    Write-Output ("STOPPED_PID=" + ($stopped -join ","))
} else {
    Write-Output "STOPPED_PID=NONE"
}
