@echo off
cd /d "%~dp0"
python tests\regression_v59.py || goto :fail
python tests\regression_v60.py || goto :fail
python tests\regression_v601.py || goto :fail
python tests\regression_v61.py || goto :fail
python tests\regression_v62.py || goto :fail
echo ALL V6.2 REGRESSION GATES PASSED
exit /b 0
:fail
echo V6.2 REGRESSION FAILED
exit /b 1
