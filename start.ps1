$ErrorActionPreference = "Stop"

$projectRoot = (Resolve-Path (Split-Path -Parent $MyInvocation.MyCommand.Path)).Path
$uvCommand = (Get-Command uv -ErrorAction Stop).Source
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

& $uvCommand sync --frozen --no-dev --project $projectRoot
if ($LASTEXITCODE -ne 0) {
    throw "uv sync 执行失败，无法启动 Web 服务。"
}

$proc = Start-Process -FilePath $uvCommand `
    -ArgumentList @("run", "--frozen", "--no-dev", "--project", $projectRoot, "wfxl_openai_regst.py") `
    -WorkingDirectory $projectRoot `
    -WindowStyle Hidden `
    -PassThru

Start-Sleep -Seconds 4
$listener = Get-NetTCPConnection -LocalPort 8000 -State Listen -ErrorAction SilentlyContinue | Select-Object -First 1
if (-not $listener) {
    $alive = $false
    try {
        $null = Get-Process -Id $proc.Id -ErrorAction Stop
        $alive = $true
    } catch {
    }
    if (-not $alive) {
        throw "Web 服务启动失败：入口进程已退出，且 8000 端口未监听。"
    }
    throw "Web 服务启动失败：入口进程仍在，但 8000 端口未监听。"
}

$listenPid = $listener.OwningProcess

New-Item -ItemType Directory -Path (Split-Path -Parent $pidFile) -Force | Out-Null
Set-Content -LiteralPath $pidFile -Value $listenPid -Encoding ascii

Write-Output "STARTED_PID=$listenPid"
Write-Output "URL=http://127.0.0.1:8000"
