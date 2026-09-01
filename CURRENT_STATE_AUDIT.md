# CURRENT_STATE_AUDIT

## 1. 当前版本 (Current Version)

- 代码基线：`releases/v6.11`（CHANGELOG 截至 2026-08-03，版本 v6.11）
- 平台状态：`V6_11_STABILIZATION_AND_CERTIFICATION_COMPLETE`

## 2. 当前目标 (Current Target)

- 修复中国太保 2023–2025 单位声明解析（“金额单位均为人民币X”），消除误报的
  HIGH「单位不确定」，支持四家公司真实数据交付（FOUR_COMPANY_RESEARCH_DATA_DELIVERY_V1）。

## 3. 不可修改规则 (Non-Modifiable Rules)

- Rule 001：最终研究值必须走 CertifiedChildTableLink → Whole-table Capture → Canonical → Merge → XLSX。
- Rule 002：不得发明/修复/推断金额；OCR 只做候选与证据。
- Rule 003：OCR 数值隔离；金额必须关联列几何、期间、单位、行标签与来源溯源。
- Rule 004：金融投资家族边界不自动纳入投资收益/长期股权投资/定期存款等。
- Rule 005：中国人寿隐式成员集不得伪造“金融投资”父行。

## 4. 相关模块与 Owner (Relevant Modules & Owners)

- `document_context_resolver.py`：Capture 域（Capture Orchestrator / Library 使用）
- `services/capture_decision_reducer.py`：State 域（只读消费，本次不改）
- `spatial_table_capture.py` / `table_capture.py`：Capture 域（消费方，本次不改）

## 5. 已知风险与注意事项 (Identified Risks & Notes)

- 正则放宽后需防误匹配普通正文中的“金额/单位”字样——以负例测试锁定。
- `unit_source_text` 为新增审计字段，属增量变更；不覆盖既有机器证据。
- 真实 PDF 验证依赖上传目录中的太保 2023 年报，缺失时测试跳过（fixture 集成测试始终运行）。
