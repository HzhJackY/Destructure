@echo off
cd /d "%~dp0"
python tests\regression_v59.py
if errorlevel 1 goto :fail
python tests\regression_v60.py
if errorlevel 1 goto :fail
python tests\regression_v601.py
if errorlevel 1 goto :fail
python tests\regression_v61.py
if errorlevel 1 goto :fail
echo.
echo ALL V6.1 REGRESSION GATES PASSED
pause
exit /b 0
:fail
echo.
echo V6.1 REGRESSION FAILED
pause
exit /b 1
