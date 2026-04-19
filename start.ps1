$ErrorActionPreference = "Stop"

$projectRoot = (Resolve-Path (Split-Path -Parent $MyInvocation.MyCommand.Path)).Path
$pythonPath = Join-Path $projectRoot ".venv\Scripts\python.exe"
$pythonwPath = Join-Path $projectRoot ".venv\Scripts\pythonw.exe"
$outLog = Join-Path $projectRoot "run.out.log"
$errLog = Join-Path $projectRoot "run.err.log"
$pidFile = Join-Path $projectRoot "data\web_console.pid"

function Stop-OpaiReProcessById {
    param(
        [int]$ProcessId
    )

    if (-not $ProcessId) {
        return
    }

    try {
        Stop-Process -Id $ProcessId -Force -ErrorAction Stop
    } catch {
    }
}

if (-not (Test-Path $pythonPath)) {
    throw "未找到虚拟环境解释器: $pythonPath"
}

$launcherPath = if (Test-Path $pythonwPath) { $pythonwPath } else { $pythonPath }

$existingPids = @()

if (Test-Path $pidFile) {
    $pidText = Get-Content $pidFile -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($pidText -and ($pidText -as [int])) {
        $existingPids += [int]$pidText
    }
}

$listener = Get-NetTCPConnection -LocalPort 8000 -State Listen -ErrorAction SilentlyContinue | Select-Object -First 1
if ($listener) {
    try {
        $proc = Get-CimInstance Win32_Process -Filter "ProcessId = $($listener.OwningProcess)"
        if ($proc -and $proc.CommandLine -like "*wfxl_openai_regst.py*") {
            $existingPids += [int]$listener.OwningProcess
        }
    } catch {
    }
}

$existingPids = $existingPids | Sort-Object -Unique
foreach ($procId in $existingPids) {
    Stop-OpaiReProcessById -ProcessId $procId
}

$allOpaiReProcesses = Get-CimInstance Win32_Process -ErrorAction SilentlyContinue |
    Where-Object {
        $_.CommandLine -and $_.CommandLine -like "*wfxl_openai_regst.py*"
    }

foreach ($proc in $allOpaiReProcesses) {
    Stop-OpaiReProcessById -ProcessId $proc.ProcessId
}

Start-Sleep -Seconds 2
Remove-Item -LiteralPath $outLog, $errLog -ErrorAction SilentlyContinue

$proc = Start-Process -FilePath $launcherPath `
    -ArgumentList "wfxl_openai_regst.py" `
    -WorkingDirectory $projectRoot `
    -WindowStyle Hidden `
    -PassThru

Start-Sleep -Seconds 4
$listener = Get-NetTCPConnection -LocalPort 8000 -State Listen -ErrorAction SilentlyContinue | Select-Object -First 1
$listenPid = if ($listener) { $listener.OwningProcess } else { $proc.Id }

New-Item -ItemType Directory -Path (Split-Path -Parent $pidFile) -Force | Out-Null
Set-Content -LiteralPath $pidFile -Value $listenPid -Encoding ascii

Write-Output "STARTED_PID=$listenPid"
Write-Output "URL=http://127.0.0.1:8000"
