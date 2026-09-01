@echo off
setlocal
cd /d "%~dp0"
echo ===============================================
for /f %%V in ('python -c "from version import APP_VERSION; print(APP_VERSION)"') do set APP_VERSION=%%V
echo Financial Metric Resolver %APP_VERSION% - Financial Extraction Engine V2
echo ===============================================
python launcher.py
if errorlevel 1 pause
