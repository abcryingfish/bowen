@echo off
setlocal

cd /d "%~dp0"

set "PY=%~dp0.venv\Scripts\python.exe"
set "RUNNER=%~dp0run_all_data_and_signals.py"

if not exist "%PY%" (
    echo [ERROR] Python not found: %PY%
    pause
    exit /b 1
)

if not exist "%RUNNER%" (
    echo [ERROR] Runner not found: %RUNNER%
    pause
    exit /b 1
)

"%PY%" "%RUNNER%"
set "EXIT_CODE=%ERRORLEVEL%"

echo.
if "%EXIT_CODE%"=="0" (
    echo [OK] Finished.
) else (
    echo [ERROR] Failed with exit code %EXIT_CODE%.
)
pause
exit /b %EXIT_CODE%
