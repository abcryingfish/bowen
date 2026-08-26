param(
    [string]$Password = $(if ($env:NEO4J_PASSWORD) { $env:NEO4J_PASSWORD } else { "password123" }),
    [switch]$AcceptEvaluationLicense
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
$Server = Join-Path $Root "server"
$JavaHome = Join-Path $Root "runtime\java"
$Admin = Join-Path $Server "bin\neo4j-admin.bat"

if (-not (Test-Path -LiteralPath $Admin)) { throw "未找到 Neo4j 管理脚本：$Admin" }
if (-not (Test-Path -LiteralPath (Join-Path $JavaHome "bin\java.exe"))) { throw "未找到 Java 21 运行时：$JavaHome" }
if ([string]::IsNullOrWhiteSpace($Password) -or $Password.Length -lt 8) { throw "Neo4j 密码至少需要 8 个字符。" }

$env:NEO4J_HOME = $Server
$env:JAVA_HOME = $JavaHome
$env:Path = "$JavaHome\bin;$env:Path"

$licenseMarker = Join-Path $Server "licenses\ACCEPT_LICENSE_AGREEMENT"
if ($AcceptEvaluationLicense -and -not (Test-Path -LiteralPath $licenseMarker)) {
    Write-Host "你显式指定了 -AcceptEvaluationLicense，接受 Neo4j Enterprise 评估许可..."
    & $Admin server license --accept-evaluation
    if ($LASTEXITCODE -ne 0) { throw "Neo4j 评估许可接受失败，退出码：$LASTEXITCODE" }
}
if (-not (Test-Path -LiteralPath $licenseMarker)) {
    throw "当前复制的是 Neo4j Enterprise，需要许可确认。请在确认许可条款后执行：.\start_neo4j.ps1 -AcceptEvaluationLicense"
}

New-Item -ItemType Directory -Force -Path @(
    (Join-Path $Root "data"),
    (Join-Path $Root "logs"),
    (Join-Path $Root "run"),
    (Join-Path $Root "import"),
    (Join-Path $Root "backups\dumps"),
    (Join-Path $Root "backups\transactions")
) | Out-Null

& $Admin server validate-config
if ($LASTEXITCODE -ne 0) { throw "Neo4j 配置校验失败，退出码：$LASTEXITCODE" }

$authFile = Join-Path $Root "data\dbms\auth.ini"
if (-not (Test-Path -LiteralPath $authFile)) {
    Write-Host "首次初始化 Neo4j 管理密码..."
    & $Admin dbms set-initial-password $Password --require-password-change=false
    if ($LASTEXITCODE -ne 0) { throw "Neo4j 初始密码设置失败，退出码：$LASTEXITCODE" }
}

Write-Host "启动 Neo4j（Java 21，localhost:7474/7687）..."
$consoleLog = Join-Path $Root "logs\neo4j-console.log"
$existingListener = Get-NetTCPConnection -State Listen -LocalAddress 127.0.0.1 -LocalPort 7687 -ErrorAction SilentlyContinue
if (-not $existingListener) {
    # The copied distribution is not installed as a Windows service. Run the
    # supported console command in a hidden child process instead.
    $consoleArgs = @("server", "console")
    Start-Process -FilePath $Admin -ArgumentList $consoleArgs -WorkingDirectory $Server -WindowStyle Hidden | Out-Null
}
$listenerAfterStart = $null
for ($attempt = 1; $attempt -le 30; $attempt++) {
    $listenerAfterStart = Get-NetTCPConnection -State Listen -LocalAddress 127.0.0.1 -LocalPort 7687 -ErrorAction SilentlyContinue
    if ($listenerAfterStart) { break }
    Start-Sleep -Seconds 1
}
if (-not $listenerAfterStart) {
    $neo4jLog = Join-Path $Root "logs\neo4j.log"
    $tail = if (Test-Path -LiteralPath $neo4jLog) { (Get-Content -LiteralPath $neo4jLog -Tail 40 -ErrorAction SilentlyContinue) -join "`n" } else { "无启动日志" }
    throw "Neo4j 启动失败。日志：$neo4jLog`n$tail"
}
& (Join-Path $Root "status_neo4j.ps1")
