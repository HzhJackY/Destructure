@echo off
cd /d "%~dp0"
call run_regression_v62.bat || goto :fail
python tests\regression_v63.py || goto :fail
echo ALL V6.3 REGRESSION GATES PASSED
exit /b 0
:fail
echo V6.3 REGRESSION FAILED
exit /b 1
