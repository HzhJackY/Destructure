@echo off
setlocal
cd /d "%~dp0"
echo ===============================================
echo Financial Metric Resolver v6.0 - Single Instance
echo ===============================================
python launcher.py
if errorlevel 1 pause
