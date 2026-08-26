$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
$Server = Join-Path $Root "server"
$JavaHome = Join-Path $Root "runtime\java"
$env:NEO4J_HOME = $Server
$env:JAVA_HOME = $JavaHome
$env:Path = "$JavaHome\bin;$env:Path"
$httpListener = Get-NetTCPConnection -State Listen -LocalAddress 127.0.0.1 -LocalPort 7474 -ErrorAction SilentlyContinue
$boltListener = Get-NetTCPConnection -State Listen -LocalAddress 127.0.0.1 -LocalPort 7687 -ErrorAction SilentlyContinue

Write-Host ("127.0.0.1:7474 listening={0}" -f [bool]$httpListener)
Write-Host ("127.0.0.1:7687 listening={0}" -f [bool]$boltListener)

if ($httpListener -and $boltListener) {
    $processIds = @($httpListener.OwningProcess, $boltListener.OwningProcess) | Sort-Object -Unique
    $processes = foreach ($processId in $processIds) {
        Get-CimInstance Win32_Process -Filter "ProcessId = $processId" -ErrorAction SilentlyContinue
    }
    if ($processes) {
        Write-Host "Neo4j 正在运行："
        $processes | Select-Object ProcessId, Name, CommandLine | Format-List
    } else {
        Write-Host "Neo4j 端口正在监听。"
    }
    exit 0
}

Write-Host "Neo4j 未完全运行。请检查 logs\neo4j.log。"
exit 1
