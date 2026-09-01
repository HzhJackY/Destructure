@echo off
python financial_metric_pdf_resolver.py sample_financial_report.pdf ^
  --metrics 营业收入 净利润 归母净利润 保险合同负债 ^
  --rules metric_aliases.json ^
  --output-dir demo_output
pause
