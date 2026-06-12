@echo off
setlocal EnableDelayedExpansion

call "%~dp0lan_config.bat"

if not defined LAN_IP (
    for /f "usebackq delims=" %%i in (`powershell -NoProfile -Command "$wifi = Get-NetAdapter | Where-Object { $_.Status -eq 'Up' -and ($_.InterfaceDescription -match 'Wi-Fi|Wireless|WLAN|无线') } | Select-Object -First 1; if ($wifi) { Get-NetIPAddress -InterfaceIndex $wifi.ifIndex -AddressFamily IPv4 -ErrorAction SilentlyContinue | Where-Object { $_.IPAddress -notlike '127.*' -and $_.PrefixOrigin -ne 'WellKnown' } | Select-Object -First 1 -ExpandProperty IPAddress } else { Get-NetIPAddress -AddressFamily IPv4 | Where-Object { $_.IPAddress -notlike '127.*' -and $_.PrefixOrigin -ne 'WellKnown' -and $_.IPAddress -match '^192\.168\.' } | Select-Object -First 1 -ExpandProperty IPAddress }"`) do set "LAN_IP=%%i"
)

if not defined WEB_PORT set "WEB_PORT=8086"
if not defined API_PORT set "API_PORT=8000"

endlocal & set "LAN_IP=%LAN_IP%" & set "WEB_PORT=%WEB_PORT%" & set "API_PORT=%API_PORT%"
