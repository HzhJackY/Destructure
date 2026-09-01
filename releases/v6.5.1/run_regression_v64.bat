@echo off
cd /d "%~dp0"
call run_regression_v63.bat || goto :fail
python tests\regression_v64.py || goto :fail
echo ALL V6.4 REGRESSION GATES PASSED
exit /b 0
:fail
echo V6.4 REGRESSION FAILED
exit /b 1

