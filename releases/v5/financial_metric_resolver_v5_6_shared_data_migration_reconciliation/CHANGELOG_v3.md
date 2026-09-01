# v3 PDF First

- 主入口从 XLSX 改为 PDF。
- 使用 pdfplumber 提取结构化表格。
- 增加 `page.extract_words()` 坐标行重建作为召回层。
- 保留 L0 规则、L1 启发式、L2 DeepSeek/Gemini bounded-choice。
- LLM 不再允许直接输出金额；只选择 candidate_id。
- 新增确定性数值解析、单位检测、换算为元。
- 新增多期间数值选择置信度与人工 warning。
- 新增 `report.html` 人工可视化报告。
- 新增 `report.md` 人工/版本管理报告。
- 保留 `results.json` 与 `audit.jsonl` 机器与审计输出。
- 增加扫描页风险检测；OCR 保留为下一独立层。
