@echo off
setlocal EnableDelayedExpansion

chcp 65001 >nul

cd /d "%~dp0"

call "%~dp0resolve_lan_ip.bat"

echo [all] Starting API and static web services...

start "market-data-api" cmd /k ""%~dp0start_api_server.bat""
timeout /t 2 /nobreak >nul
start "web-server-8086" cmd /k ""%~dp0start_web_server.bat""

echo.
echo Both services were started in new windows.
echo Local page: http://127.0.0.1:%WEB_PORT%/量化因子/index.html
if defined LAN_IP (
    echo LAN page: http://!LAN_IP!:%WEB_PORT%/量化因子/index.html
)
echo.
pause
