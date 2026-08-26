@echo off
cd /d "%~dp0"
..\.venv\Scripts\python.exe gui.py
if errorlevel 1 pause
