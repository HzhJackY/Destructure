@echo off
cd /d "%~dp0"
python tests\regression_v59.py
if errorlevel 1 goto :fail
python tests\regression_v60.py
if errorlevel 1 goto :fail
echo.
echo ALL V5.9 + V6.0 REGRESSION TESTS PASSED
pause
exit /b 0
:fail
echo.
echo REGRESSION FAILED
pause
exit /b 1
