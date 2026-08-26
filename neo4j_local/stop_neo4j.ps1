$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
$Server = Join-Path $Root "server"
$JavaHome = Join-Path $Root "runtime\java"
$Admin = Join-Path $Server "bin\neo4j-admin.bat"
$env:NEO4J_HOME = $Server
$env:JAVA_HOME = $JavaHome
$env:Path = "$JavaHome\bin;$env:Path"
Write-Host "正在停止项目内 Neo4j..."

# `server console` is used by start_neo4j.ps1 because this copied distribution
# is not installed as a Windows service. Try Neo4j's graceful stop first; if
# no daemon PID exists, fall back to only the bundled-Java processes that own
# this instance's HTTP/Bolt ports.
& $Admin server stop 2>$null
$adminExitCode = $LASTEXITCODE
Start-Sleep -Seconds 2

$connections = @(
    Get-NetTCPConnection -State Listen -LocalAddress 127.0.0.1 -LocalPort 7474 -ErrorAction SilentlyContinue
    Get-NetTCPConnection -State Listen -LocalAddress 127.0.0.1 -LocalPort 7687 -ErrorAction SilentlyContinue
)
if ($connections) {
    $portProcessIds = @($connections.OwningProcess) | Sort-Object -Unique
    $javaPath = (Join-Path $JavaHome "bin\java.exe").ToLowerInvariant()
    $neo4jProcesses = Get-CimInstance Win32_Process -ErrorAction SilentlyContinue | Where-Object {
        $image = if ($_.ExecutablePath) { $_.ExecutablePath.ToLowerInvariant() } else { "" }
        $commandLine = if ($_.CommandLine) { $_.CommandLine } else { "" }
        ($portProcessIds -contains $_.ProcessId) -and
        ($image -eq $javaPath -or $commandLine -like "*$Server*")
    }
    foreach ($process in $neo4jProcesses) {
        Stop-Process -Id $process.ProcessId -Force -ErrorAction SilentlyContinue
    }
}

for ($attempt = 1; $attempt -le 15; $attempt++) {
    $remaining = Get-NetTCPConnection -State Listen -LocalAddress 127.0.0.1 -LocalPort 7687 -ErrorAction SilentlyContinue
    if (-not $remaining) {
        Write-Host "Neo4j 已停止。"
        exit 0
    }
    Start-Sleep -Seconds 1
}

Write-Host "Neo4j 停止命令已执行，但 7687 端口仍在监听。请检查 logs\neo4j.log。"
exit 1
