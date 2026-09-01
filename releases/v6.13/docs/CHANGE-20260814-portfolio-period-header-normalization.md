# CHANGE — 投资组合中文期间表头空白规范化

日期：2026-08-14

状态：`BUG_FIX_VERIFIED_TARGETED_AND_REAL_PDF`

## 变更

- `DIRECT_PORTFOLIO_TABLES` 在原 resolver 内解析含水平 PDF 字形空白的中文期间；
- 两个不同期间才形成 `period_header_complete=true`；
- Stage A、五拓扑执行计划及后续正式 Capture 主干保持不变。

## 验证边界

- 投资组合相关定向 pytest：66 passed，0 failed/error/skipped；
- 太保 2025 第 48 页原生文本 Canary：页码 48、`DIRECT_COMPOUND_TABLE`、OCR=false；
- 期间：`2025年12月31日`、`2024年12月31日`；
- Stage A：`period_recognized=true`、全部硬门禁通过、Anchor score 0.91；
- Golden：`MATCH`。

浏览器 E2E、OCR、生产 DATA_HOME、完整 Capture/Canonical/Merge 和冻结 shadow A/B 均未运行。
