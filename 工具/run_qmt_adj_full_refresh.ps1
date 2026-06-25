param(
    [string]$ProjectRoot = "C:\Users\Administrator\Desktop\python_venv",
    [string]$AdjEnd = (Get-Date -Format "yyyy-MM-dd"),
    [string]$RawBaseDir = "D:\database\stock_adj_daily_raw",
    [string]$FinalBaseDir = "D:\database\stock_adj_daily",
    [string]$StagingBaseDir = "D:\database\stock_adj_daily_qmt_staging"
)

$ErrorActionPreference = "Stop"

function Assert-ExactPath {
    param(
        [string]$Actual,
        [string]$Expected
    )
    $actualFull = [System.IO.Path]::GetFullPath($Actual).TrimEnd('\')
    $expectedFull = [System.IO.Path]::GetFullPath($Expected).TrimEnd('\')
    if (-not [string]::Equals($actualFull, $expectedFull, [System.StringComparison]::OrdinalIgnoreCase)) {
        throw "Unsafe path. Actual=$actualFull Expected=$expectedFull"
    }
}

function Invoke-Native {
    param(
        [scriptblock]$Command,
        [string]$StepName
    )
    & $Command
    if ($LASTEXITCODE -ne 0) {
        throw "$StepName failed with exit code $LASTEXITCODE"
    }
}

$Py = Join-Path $ProjectRoot ".venv\Scripts\python.exe"
$ToolsDirName = "$([char]0x5de5)$([char]0x5177)"
$AdjNamePart = "$([char]0x590d)$([char]0x6743)"
$ToolsDir = Join-Path $ProjectRoot $ToolsDirName
$QmtScriptItem = Get-ChildItem -LiteralPath $ToolsDir -Filter "qmt*.py" |
    Where-Object { $_.Name.Contains($AdjNamePart) } |
    Select-Object -First 1
$QmtScript = if ($null -eq $QmtScriptItem) { Join-Path $ToolsDir "qmt_adj_script_not_found.py" } else { $QmtScriptItem.FullName }
$ValidateScript = Join-Path $ToolsDir "validate_qmt_adj_output.py"

if (-not (Test-Path -LiteralPath $Py)) { throw "Python not found: $Py" }
if (-not (Test-Path -LiteralPath $QmtScript)) { throw "QMT script not found: $QmtScript" }
if (-not (Test-Path -LiteralPath $ValidateScript)) { throw "Validator not found: $ValidateScript" }

Assert-ExactPath -Actual $FinalBaseDir -Expected "D:\database\stock_adj_daily"
Assert-ExactPath -Actual $StagingBaseDir -Expected "D:\database\stock_adj_daily_qmt_staging"

Write-Host "[1/5] Checking Python dependencies..."
Invoke-Native -StepName "dependency check" -Command {
    & $Py -c "import pandas, polars, duckdb; from xtquant import xtdata; print('[OK] deps import passed')"
}

Write-Host "[2/5] Clearing staging output..."
if (Test-Path -LiteralPath $StagingBaseDir) {
    Remove-Item -LiteralPath $StagingBaseDir -Recurse -Force
}

Write-Host "[3/5] Running QMT full refresh into staging..."
Invoke-Native -StepName "QMT full refresh" -Command {
    & $Py $QmtScript `
        --raw-base-dir $RawBaseDir `
        --final-base-dir $StagingBaseDir `
        --default-start 2010-01-01 `
        --adj-end $AdjEnd `
        --no-incremental
}

Write-Host "[4/5] Validating staging output..."
Invoke-Native -StepName "staging validation" -Command {
    & $Py $ValidateScript --base-dir $StagingBaseDir --raw-base-dir $RawBaseDir
}
if (-not (Test-Path -LiteralPath $StagingBaseDir)) {
    throw "Staging output is missing after validation: $StagingBaseDir"
}

Write-Host "[5/5] Replacing official stock_adj_daily..."
if (Test-Path -LiteralPath $FinalBaseDir) {
    Remove-Item -LiteralPath $FinalBaseDir -Recurse -Force
}
Move-Item -LiteralPath $StagingBaseDir -Destination $FinalBaseDir

Write-Host "[OK] Official output replaced. Running final validation..."
Invoke-Native -StepName "final validation" -Command {
    & $Py $ValidateScript --base-dir $FinalBaseDir --raw-base-dir $RawBaseDir
}
