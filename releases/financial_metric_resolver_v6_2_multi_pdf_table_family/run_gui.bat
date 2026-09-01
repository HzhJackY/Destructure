@echo off
setlocal
cd /d "%~dp0"
echo ===============================================
echo Financial Metric Resolver v6.1 - Backend Registry + Single Instance
echo ===============================================
python launcher.py
if errorlevel 1 pause
