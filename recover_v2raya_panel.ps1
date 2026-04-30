param(
    [string]$PanelUrl = "",
    [string]$ConfigPath = ".\config.yaml",
    [int]$WaitSeconds = 10,
    [switch]$DiagnoseOnly,
    [switch]$OpenPanel
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

function Write-Step {
    param([string]$Message)
    Write-Host ("[{0}] {1}" -f (Get-Date -Format "HH:mm:ss"), $Message)
}

function Get-ProjectConfigValue {
    param(
        [string]$Path,
        [string]$Section,
        [string]$Key
    )

    if (-not (Test-Path -LiteralPath $Path)) {
        return ""
    }

    $lines = Get-Content -LiteralPath $Path
    $inSection = $false
    foreach ($rawLine in $lines) {
        $line = [string]$rawLine
        if ($line -match '^\s*#') {
            continue
        }
        if ($line -match '^(?<name>[A-Za-z0-9_]+)\s*:\s*$') {
            $inSection = ($Matches.name -eq $Section)
            continue
        }
        if (-not $inSection) {
            continue
        }
        if ($line -match '^[A-Za-z0-9_]+\s*:\s*$') {
            break
        }
        if ($line -match ('^\s{{2}}{0}\s*:\s*(?<value>.+?)\s*$' -f [regex]::Escape($Key))) {
            $value = [string]$Matches.value
            $value = $value.Trim()
            if (($value.StartsWith("'") -and $value.EndsWith("'")) -or ($value.StartsWith('"') -and $value.EndsWith('"'))) {
                $value = $value.Substring(1, $value.Length - 2)
            }
            return $value
        }
    }
    return ""
}

function Get-ProxyPort {
    param([string]$ProxyUrl)
    if (-not $ProxyUrl) {
        return $null
    }
    try {
        return ([uri]$ProxyUrl).Port
    } catch {
        return $null
    }
}

function Get-PanelHealth {
    param([string]$Url)
    if (-not $Url) {
        return @{
            ok = $false
            detail = "panel url not set"
        }
    }
    try {
        $response = Invoke-WebRequest -Uri $Url -Method Get -TimeoutSec 5
        return @{
            ok = $true
            detail = ("HTTP {0}" -f [int]$response.StatusCode)
        }
    } catch {
        return @{
            ok = $false
            detail = $_.Exception.Message
        }
    }
}

function Get-RelatedProcesses {
    Get-Process -ErrorAction SilentlyContinue |
        Where-Object { $_.ProcessName -match '^(v2raya|v2rayA-service|clash-core-service|v2ray|xray)$' } |
        Sort-Object ProcessName |
        Select-Object ProcessName, Id
}

function Get-RelatedListeners {
    $targets = Get-RelatedProcesses
    if (-not $targets) {
        return @()
    }

    $pidMap = @{}
    foreach ($item in $targets) {
        $pidMap[[int]$item.Id] = [string]$item.ProcessName
    }

    $results = @()
    $lines = netstat -ano -p tcp
    foreach ($line in $lines) {
        $text = [string]$line
        if ($text -notmatch '^\s*TCP\s+(?<local>\S+)\s+\S+\s+LISTENING\s+(?<pid>\d+)\s*$') {
            continue
        }
        $ownerPid = [int]$Matches.pid
        if (-not $pidMap.ContainsKey($ownerPid)) {
            continue
        }
        $local = [string]$Matches.local
        $portText = $local.Substring($local.LastIndexOf(':') + 1)
        $port = 0
        [void][int]::TryParse($portText, [ref]$port)
        $results += [pscustomobject]@{
            ProcessName = $pidMap[$ownerPid]
            Pid = $ownerPid
            LocalAddress = $local
            Port = $port
        }
    }
    return $results | Sort-Object Port, ProcessName
}

function Wait-ForListenerPort {
    param(
        [int]$Port,
        [int]$TimeoutSeconds
    )

    if (-not $Port -or $Port -le 0) {
        return $false
    }

    $deadline = (Get-Date).AddSeconds([Math]::Max(1, $TimeoutSeconds))
    while ((Get-Date) -lt $deadline) {
        $listeners = Get-RelatedListeners
        if ($listeners | Where-Object { $_.Port -eq $Port }) {
            return $true
        }
        Start-Sleep -Milliseconds 500
    }
    return $false
}

function Restart-V2rayAStack {
    param([int]$TimeoutSeconds)

    $service = Get-Service -Name "v2rayA" -ErrorAction SilentlyContinue
    if (-not $service) {
        throw "Windows service v2rayA was not found."
    }

    Write-Step "Stop v2rayA service"
    Stop-Service -Name "v2rayA" -Force -ErrorAction SilentlyContinue
    Start-Sleep -Seconds 2

    $coreNames = @("clash-core-service", "v2ray", "xray")
    $coreProcesses = Get-Process -ErrorAction SilentlyContinue | Where-Object { $coreNames -contains $_.ProcessName }
    foreach ($proc in $coreProcesses) {
        Write-Step ("Kill stale core process: {0} (PID {1})" -f $proc.ProcessName, $proc.Id)
        Stop-Process -Id $proc.Id -Force -ErrorAction SilentlyContinue
    }

    Write-Step "Start v2rayA service"
    Start-Service -Name "v2rayA"
    Start-Sleep -Seconds 2

    $service = Get-Service -Name "v2rayA" -ErrorAction Stop
    if ($service.Status -ne "Running") {
        throw ("v2rayA service failed to start. Current state: {0}" -f $service.Status)
    }

    if ($TimeoutSeconds -gt 0) {
        Write-Step ("Wait for listener recovery up to {0}s" -f $TimeoutSeconds)
        Start-Sleep -Seconds ([Math]::Min(2, $TimeoutSeconds))
    }
}

$resolvedConfigPath = Resolve-Path -LiteralPath $ConfigPath -ErrorAction SilentlyContinue
$configFile = if ($resolvedConfigPath) { $resolvedConfigPath.Path } else { $ConfigPath }

if (-not $PanelUrl) {
    $PanelUrl = Get-ProjectConfigValue -Path $configFile -Section "clash_proxy_pool" -Key "v2raya_url"
}

$defaultProxy = Get-ProjectConfigValue -Path $configFile -Section "clash_proxy_pool" -Key "test_proxy_url"
if (-not $defaultProxy) {
    if (Test-Path -LiteralPath $configFile) {
        $topLevelDefault = Select-String -Path $configFile -Pattern '^\s*default_proxy\s*:\s*(?<value>.+?)\s*$' | Select-Object -First 1
        if ($topLevelDefault) {
            $defaultProxy = [string]$topLevelDefault.Matches[0].Groups["value"].Value
            $defaultProxy = ($defaultProxy -replace "^[\s'`"]+|[\s'`"]+$", "")
        }
    }
}

$expectedProxyPort = Get-ProxyPort -ProxyUrl $defaultProxy

Write-Step ("Panel URL: {0}" -f ($(if ($PanelUrl) { $PanelUrl } else { "not set" })))
Write-Step ("Project default_proxy: {0}" -f ($(if ($defaultProxy) { $defaultProxy } else { "not set" })))

$beforeHealth = Get-PanelHealth -Url $PanelUrl
$beforeListeners = Get-RelatedListeners
$service = Get-Service -Name "v2rayA" -ErrorAction SilentlyContinue

Write-Step ("Panel probe: {0}" -f $beforeHealth.detail)
Write-Step ("v2rayA service state: {0}" -f ($(if ($service) { $service.Status } else { "not found" })))

if ($beforeListeners) {
    Write-Step "Current listener ports:"
    $beforeListeners | Format-Table ProcessName, Pid, LocalAddress, Port -AutoSize
} else {
    Write-Step "No related listener ports were found"
}

if ($DiagnoseOnly) {
    Write-Step "Diagnose-only mode finished. No restart was performed."
    exit 0
}

Restart-V2rayAStack -TimeoutSeconds $WaitSeconds

if ($expectedProxyPort) {
    if (Wait-ForListenerPort -Port $expectedProxyPort -TimeoutSeconds $WaitSeconds) {
        Write-Step ("default_proxy port {0} is listening again" -f $expectedProxyPort)
    } else {
        Write-Step ("default_proxy port {0} is still not listening. Check detected listeners below." -f $expectedProxyPort)
    }
}

$afterHealth = Get-PanelHealth -Url $PanelUrl
$afterListeners = Get-RelatedListeners
$service = Get-Service -Name "v2rayA" -ErrorAction SilentlyContinue

Write-Step ("Panel probe after restart: {0}" -f $afterHealth.detail)
Write-Step ("Service state after restart: {0}" -f ($(if ($service) { $service.Status } else { "not found" })))

if ($afterListeners) {
    Write-Step "Listener ports after restart:"
    $afterListeners | Format-Table ProcessName, Pid, LocalAddress, Port -AutoSize
} else {
    Write-Step "No related listener ports were found after restart"
}

if ($OpenPanel -and $PanelUrl) {
    Write-Step "Open v2rayA panel"
    Start-Process $PanelUrl
}

Write-Step "If the panel still stays in checking mode, refresh it once. If it still fails, go back to the project page and run align_proxy plus test_current."
