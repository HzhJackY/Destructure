# INC-037 — 完整期间在 Canonical/Merge 被降维为年份

状态：`RESOLVED_OFFLINE_REAL_PDF_VERIFIED`

## 现象

太保 2023 投资组合原表同时披露 `2023年12月31日` 与 `2023年1月1日`。Capture 已读取两个
完整日期，但 Capture Long 到 Canonical/Merge 的列身份使用 `data_year=2023`，导致两个时点
可能碰撞、覆盖或进入错误冲突。

## 根因

- `period_label` 只用于展示，正式 key 仍以年份为主，丢失月日精度。
- Capture 表头门禁和 Merge observation key 使用两套期间身份规则。
- 历史兼容与研究宽表都默认“年度报告等于年份列”，未区分 Filing 年和 observation 时点。

## 修复

- 新增共享点期间正规化器，保存原文、正规标签、年月日、精度、日期、稳定身份和期间类型。
- V4 `period_signature` 在 V3 列组证据上加入结构化期间；完整日期标为 `ABSOLUTE_DATE`。
- Capture Long、Canonical、Merge、列冲突和宽表列身份统一使用 `period_identity`；`data_year`
  只保留兼容查询用途。
- 历史 V3 Capture 只从既有完整 `period_label` 派生，不改写源资产。季度/半年相对期间缺少
  认证报告期末日时以 `PERIOD_DATE_UNRESOLVED` 阻断。
- 年与更高精度同时出现时分别保留，并输出非阻断 `PERIOD_PRECISION_MISMATCH` 审计。
- 认证消费端允许 `V3` 几何签名与 `V4` 期间签名组合；V4 只升级期间合同，不要求无关的
  几何证据同步改版。
- Canonical 前期间门禁只约束含数值的 observation；无数值父组行和跨行标签证据可保留空
  期间，但不会进入 Canonical observation。

## 验证边界

- 新合同和受影响定向测试 58/58 通过。
- 新隔离 DATA_HOME 完成太保 2023–2025、国寿 2024、新华 2023、平安 2024 共 6/6
  真实 PDF 全链回归；全部 OCR=0、Capture SUCCESS、`merge_ready=1`，并生成 Canonical 与 XLSX。
- 太保 2023 的 `DATE:2023-12-31` 与 `DATE:2023-01-01` 已同时出现在三个 Capture Long、
  Canonical Long、Resolved Long、`column_dimensions.csv` 和研究宽表；两者 `data_year` 均为
  2023，但未碰撞。
- 太保三年 Golden 金额/占比匹配；旧 Golden 仍使用去脚注 raw label，因此记录为
  `MISMATCH_RAW_LABEL_AUDIT_ONLY`，未改写 Golden。平安 2024 无对应 Golden，明确记录为
  `NOT_RUN_NO_GOLDEN`。
- 浏览器 E2E 未运行，本状态不是生产 UI E2E 认证。
- 未修改历史 Capture、生产 DATA_HOME、Golden 金额、ROI、OCR 路由或物理资产身份。
