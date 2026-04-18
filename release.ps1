param(
    [Parameter(Mandatory = $true)]
    [string]$Version,

    [string]$UpstreamVersion = "",

    [switch]$CreateCommit,
    [switch]$CreateTag,
    [switch]$Push
)

Set-StrictMode -Version 2.0
$ErrorActionPreference = "Stop"

function NormalizeVersion {
    param(
        [string]$Value
    )

    $text = ""
    if ($null -ne $Value) {
        $text = $Value.Trim()
    }
    if ([string]::IsNullOrWhiteSpace($text)) {
        throw "版本号不能为空。"
    }
    if (-not $text.StartsWith("v")) {
        $text = "v$text"
    }
    return $text
}

function ReadFileOrDefault {
    param(
        [string]$Path,
        [string]$Default = ""
    )

    if (Test-Path -LiteralPath $Path) {
        return (Get-Content -LiteralPath $Path -Raw -Encoding UTF8).Trim()
    }
    return $Default
}

function WriteUtf8File {
    param(
        [string]$Path,
        [string]$Content
    )

    Set-Content -LiteralPath $Path -Value $Content -Encoding UTF8
}

function ReplaceOrFail {
    param(
        [string]$Path,
        [string]$Pattern,
        [string]$Replacement,
        [string]$Label
    )

    $content = Get-Content -LiteralPath $Path -Raw -Encoding UTF8
    $updated = [regex]::Replace($content, $Pattern, $Replacement, 1)
    if ($updated -eq $content) {
        throw "未能在 $Path 中匹配到 $Label，请手动检查文件结构后再发版。"
    }
    Set-Content -LiteralPath $Path -Value $updated -Encoding UTF8
}

function InvokeGit {
    param(
        [string[]]$Args
    )

    & git @Args
    if ($LASTEXITCODE -ne 0) {
        throw "git $($Args -join ' ') 执行失败。"
    }
}

$repoRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $repoRoot

$versionFile = Join-Path $repoRoot "VERSION"
$upstreamVersionFile = Join-Path $repoRoot "UPSTREAM_VERSION"

$normalizedVersion = NormalizeVersion -Value $Version
$normalizedUpstreamVersion = ""
if (-not [string]::IsNullOrWhiteSpace($UpstreamVersion)) {
    $normalizedUpstreamVersion = NormalizeVersion -Value $UpstreamVersion
} else {
    $normalizedUpstreamVersion = ReadFileOrDefault -Path $upstreamVersionFile
}

if ([string]::IsNullOrWhiteSpace($normalizedUpstreamVersion)) {
    throw "未提供 UpstreamVersion，且仓库中也没有现成的 UPSTREAM_VERSION。"
}

$branch = (& git branch --show-current).Trim()
if ($LASTEXITCODE -ne 0) {
    throw "无法读取当前 git 分支。"
}
if ($branch -ne "main") {
    throw "当前分支是 '$branch'，请切到 main 后再发版。"
}

$dirty = & git status --porcelain
if ($LASTEXITCODE -ne 0) {
    throw "无法读取当前 git 状态。"
}
if (-not [string]::IsNullOrWhiteSpace(($dirty -join ""))) {
    throw "当前工作区存在未提交修改。请先提交或清理，再执行 release.ps1。"
}

WriteUtf8File -Path $versionFile -Content ($normalizedVersion + "`n")
WriteUtf8File -Path $upstreamVersionFile -Content ($normalizedUpstreamVersion + "`n")

ReplaceOrFail -Path (Join-Path $repoRoot "static\js\app.js") -Pattern "appVersion:\s*'[^']+'," -Replacement ("appVersion: '" + $normalizedVersion + "',") -Label "前端版本号"

ReplaceOrFail -Path (Join-Path $repoRoot "README.md") -Pattern '当前公开整理版本已对齐上游 `[^`]+` 注册流程更新[^`]*' -Replacement ('当前公开整理版本已对齐上游 `' + $normalizedUpstreamVersion + '` 注册流程更新，并保留了已经在实际环境中验证过的增强能力，重点优化了：') -Label "README 顶部上游版本说明"
ReplaceOrFail -Path (Join-Path $repoRoot "README.md") -Pattern '- 上游对齐基线：`[^`]+`' -Replacement ('- 上游对齐基线：`' + $normalizedUpstreamVersion + '`') -Label "README 上游基线"
ReplaceOrFail -Path (Join-Path $repoRoot "README.md") -Pattern '- 本仓库独立版本：`[^`]+`' -Replacement ('- 本仓库独立版本：`' + $normalizedVersion + '`') -Label "README 仓库版本"

ReplaceOrFail -Path (Join-Path $repoRoot "PR_DESCRIPTION.md") -Pattern '- 上游版本：`[^`]+`' -Replacement ('- 上游版本：`' + $normalizedUpstreamVersion + '`') -Label "PR 描述上游版本"
ReplaceOrFail -Path (Join-Path $repoRoot "PR_DESCRIPTION.md") -Pattern '- 当前公开热修版本：`[^`]+`' -Replacement ('- 当前公开热修版本：`' + $normalizedVersion + '`') -Label "PR 描述仓库版本"

ReplaceOrFail -Path (Join-Path $repoRoot "CHANGELOG.md") -Pattern '- 公共发布版本号更新为 `[^`]+`' -Replacement ('- 公共发布版本号更新为 `' + $normalizedVersion + '`') -Label "CHANGELOG 当前发布版本"

Write-Host "版本文件已更新：" -ForegroundColor Green
Write-Host ("  本仓库版本: " + $normalizedVersion)
Write-Host ("  上游基线:   " + $normalizedUpstreamVersion)

if ($CreateCommit) {
    InvokeGit -Args @("add", "VERSION", "UPSTREAM_VERSION", "static/js/app.js", "README.md", "CHANGELOG.md", "PR_DESCRIPTION.md")
    InvokeGit -Args @("commit", "-m", ("release: " + $normalizedVersion))
    Write-Host ("已创建提交 release: " + $normalizedVersion) -ForegroundColor Green
}

if ($CreateTag) {
    InvokeGit -Args @("tag", "-a", $normalizedVersion, "-m", $normalizedVersion)
    Write-Host ("已创建标签 " + $normalizedVersion) -ForegroundColor Green
}

if ($Push) {
    InvokeGit -Args @("push", "origin", "main")
    if ($CreateTag) {
        InvokeGit -Args @("push", "origin", $normalizedVersion)
    }
    Write-Host "已推送到 origin。" -ForegroundColor Green
}

Write-Host ""
Write-Host "下一步建议：" -ForegroundColor Cyan
if (-not $CreateCommit) {
    Write-Host "  1. git add VERSION UPSTREAM_VERSION static/js/app.js README.md CHANGELOG.md PR_DESCRIPTION.md"
    Write-Host ("  2. git commit -m ""release: " + $normalizedVersion + """")
} else {
    Write-Host "  1. 已完成提交"
}
if (-not $CreateTag) {
    Write-Host ("  3. git tag -a " + $normalizedVersion + " -m """ + $normalizedVersion + """")
}
if (-not $Push) {
    Write-Host "  4. git push origin main --follow-tags"
}
