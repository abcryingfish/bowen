@echo off
cd /d "%~dp0"
..\.venv\Scripts\python.exe eastmoney_baofeng_monitor.py
if errorlevel 1 pause
