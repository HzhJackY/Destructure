@echo off
setlocal
cd /d "%~dp0"
echo ===============================================
echo Financial Metric Resolver v4 GUI
echo ===============================================
python -m streamlit run app.py
pause
