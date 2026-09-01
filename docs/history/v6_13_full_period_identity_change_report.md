# v6.13 完整期间身份修复报告

## 变更

- 新增统一点期间合同，按证据保留日、月或年精度，并生成稳定 `period_identity`。
- Direct 期间签名升级为 V4；父期间列组几何仍沿用 V3，新增结构化期间字段。
- Capture Long、Canonical、Merge 和研究宽表统一消费同一期间身份；`data_year` 不再是主键。
- 历史 V3 Capture 通过只读适配器派生，季度/半年相对期间缺少认证期末日时 fail-closed。
- 新增非阻断 `merge_period_precision_audit.csv`，不折叠不同精度期间。
- 修复认证消费端误将 `V3 geometry + V4 period` 判为版本冲突。
- 修复无数值结构行被期间门禁误当 observation 的问题；真实数值 observation 缺期间仍阻断。
- 补充 Direct 物理表“有数值首行 + 无数值尾随续行”的标签拼接，保持原始 `raw_item`、
  bbox、数值和数值源行身份不变。

## 保持不变

- 正式路径仍为 Whole-table Capture → CaptureDecisionReducer → Canonical Long → Merge → XLSX。
- 不修改 ROI、历史 Capture、生产 DATA_HOME、Golden 金额、OCR 路由或物理资产身份。
- 不运行浏览器 E2E。

## 验证

- 期间合同和受影响定向测试：58/58 通过。
- 隔离真实 PDF 全链：太保 2023–2025、国寿 2024、新华 2023、平安 2024，6/6 通过；
  OCR 均为 0，所有 Capture 均 SUCCESS 且 `merge_ready=1`，Canonical/Merge/XLSX 成功。
- 太保 2023：三个逻辑 Capture 共 92 个有期间 observation；Capture Long、92 行 Canonical
  Long、88 行 Resolved Long、4 条 column dimensions 均同时保存 `DATE:2023-12-31` 与
  `DATE:2023-01-01`。研究宽表 `C3/E3` 分别显示两个完整日期。
- 太保 2024–2025 measurement 的物理跨行标签恢复为 5 行，金额与占比重新按 Golden 行序
  对齐。太保三年仅剩旧 Golden raw-label 脚注口径审计项，不是数值差异。
- 平安 2024 无 Golden，产品全链已执行，但 Golden 验收明确为 `NOT_RUN_NO_GOLDEN`。
- 未运行浏览器 E2E；未修改生产 DATA_HOME、历史 Capture 或 Golden 金额。
