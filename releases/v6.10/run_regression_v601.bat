@echo off
cd /d "%~dp0"
python tests\regression_v59.py
if errorlevel 1 exit /b 1
python tests\regression_v60.py
if errorlevel 1 exit /b 1
python tests\regression_v601.py
if errorlevel 1 exit /b 1
echo ALL_V601_REGRESSIONS_PASS
pause
