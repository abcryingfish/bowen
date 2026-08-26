param(
    [switch]$DryRun,
    [string]$Staging = "D:\database\sector_information\_staging\gold_885530_20260821"
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
$Script = Join-Path $Root "import_gold_graph.py"
$Python = Join-Path $env:LOCALAPPDATA "Programs\Python\Python310\python.exe"
if (-not (Test-Path -LiteralPath $Python)) {
    $Python = (Get-Command python.exe -ErrorAction Stop).Source
}
if (-not (Test-Path -LiteralPath $Script)) { throw "未找到导入脚本：$Script" }
if (-not (Test-Path -LiteralPath $Staging)) { throw "未找到 staging 目录：$Staging" }

$env:NEO4J_URI = if ($env:NEO4J_URI) { $env:NEO4J_URI } else { "bolt://127.0.0.1:7687" }
$env:NEO4J_USER = if ($env:NEO4J_USER) { $env:NEO4J_USER } else { "neo4j" }
$env:NEO4J_PASSWORD = if ($env:NEO4J_PASSWORD) { $env:NEO4J_PASSWORD } else { "password123" }
$env:NEO4J_DATABASE = if ($env:NEO4J_DATABASE) { $env:NEO4J_DATABASE } else { "neo4j" }

$arguments = @("-S", $Script, "--staging", $Staging)
if ($DryRun) { $arguments += "--dry-run" }
# The system Python installation contains an old non-UTF-8 iFinDPy.pth file.
# -S skips site initialization; import_gold_graph.py then adds only the two
# explicitly required project environments.
& $Python -S @arguments
exit $LASTEXITCODE
