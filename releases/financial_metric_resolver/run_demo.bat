@echo off
setlocal
python financial_metric_resolver.py --input sample_financial.xlsx --metrics 营业收入 净利润 归母净利润 货币资金 保险合同负债 --rules metric_aliases.json --output demo_result.json --audit demo_audit.jsonl
if errorlevel 1 (
  echo.
  echo Run failed. Please install dependencies first: python -m pip install -r requirements.txt
  exit /b 1
)
echo.
echo Demo completed.
endlocal
