# INC-031 — 投资组合期间表头原生空白导致 Stage A 假阴性

状态：`RESOLVED_TARGETED_AND_REAL_PDF_VERIFIED`

## 现象

中国太保 2025 上市母公司年报的投资组合候选正确定位到 PDF 第 48 页，且页面原生文本
包含当前期和比较期；Stage A 仍以 `period_recognized=false` 阻断。

## 根因

Fast Index 的 PyMuPDF 原生文本把表头输出为 `2025 年12 月31 日` 与
`2024 年12 月31 日`。`InvestmentPortfolioTopologyResolver` 原正则只接受无空白的
`2025年12月31日`，因此产生空 `period_headers`。硬门禁本身按合同正确 fail-closed，
错误位于上游期间证据解析。

## 修复

- 在既有 resolver 内增加唯一的中文期间提取 helper，允许日期字形之间的水平空白；
- 不跨换行匹配，避免把不同行的年份和月日拼成期间；
- 输出去重后的规范化期间字符串；
- `period_header_complete` 仍要求至少两个不同期间，不放宽 Stage A 硬门禁；
- 增加原生空白、重复期间和 Stage A gate 回归。

## 边界

未修改 Golden、页码、ROI、OCR、Capture、数据库或 UI。已冻结的 joint ROI/row-ownership
shadow A/B 目录未读取、未写入、未执行。

## 验证

- 投资组合相关定向 pytest：66 passed，0 failed/error/skipped；
- 太保 2025 第 48 页原生文本 Canary：两个期间规范化成功；
- Stage A：`period_recognized=true`、全部硬门禁通过、Anchor score 0.91；
- 投资组合 Golden：`MATCH`；OCR 未使用。
