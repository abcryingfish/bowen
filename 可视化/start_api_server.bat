@echo off
setlocal EnableDelayedExpansion

chcp 65001 >nul

cd /d "%~dp0"

call "%~dp0resolve_lan_ip.bat"

echo [market-data-api] Releasing port %API_PORT% if needed...
for /f "usebackq delims=" %%i in (`powershell -NoProfile -ExecutionPolicy Bypass -Command "$port = %API_PORT%; $p = @(Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue | ForEach-Object { $_.OwningProcess } | Select-Object -Unique); if (-not $p) { $p = @(netstat -ano | Select-String (':' + $port + '\s+.*LISTENING') | ForEach-Object { ($_ -split '\s+')[-1] } | Select-Object -Unique) }; foreach ($id in $p) { if ($id -match '^\d+$') { Write-Output $id } }"`) do (
    echo   stopping PID %%i
    powershell -NoProfile -ExecutionPolicy Bypass -Command "Stop-Process -Id %%i -Force -ErrorAction SilentlyContinue" >nul 2>nul
)

timeout /t 2 /nobreak >nul

echo.
echo [market-data-api] Starting server. Keep this window open.
echo Local API: http://127.0.0.1:%API_PORT%/api/health
if defined LAN_IP (
    echo LAN API: http://!LAN_IP!:%API_PORT%/api/health
    echo LAN page: http://!LAN_IP!:%WEB_PORT%/量化因子/index.html
) else (
    echo LAN page: http://your-ip:%WEB_PORT%/量化因子/index.html
)
echo.

"%~dp0..\.venv\Scripts\python.exe" "%~dp0api_server.py" --host 0.0.0.0 --port %API_PORT%

if errorlevel 1 pause
