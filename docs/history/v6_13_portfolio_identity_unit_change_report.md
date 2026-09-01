# v6.13 Direct 投资组合名称身份与多计量单位修复报告

## 变更

- 将 PDF 原始项目名与 Canonical 名称身份分离，数字脚注采用几何/同页注释双证据认证。
- 将金额单位从表级默认值下沉到 observation/列级，比例类 measure 固定为 `%`。
- Merge 以 `normalized_item` 对齐名称，只在同 measure 内检查单位冲突。
- 研究宽表固定列改为“附注表名、项目”，导出合同升级为 v3。
- Golden Capture 验收以 `row_item_raw` 比较逻辑原文，`raw_item` 仅作旧数据兼容回退。
- “项目”列宽从 30 调整为 48，确保 Direct 会计计量长名称完整显示。

## 保持不变

- 仍走既有 Whole-table Capture → CaptureDecisionReducer → Canonical Long → Merge → XLSX。
- 一个 Direct 物理作业及其逻辑分表/bundle 结构不变。
- 历史 Capture、生产 DATA_HOME、Golden 金额和原始 PDF 均不改写。

## 验证

- 受影响定向测试 45/45 通过，覆盖脚注证据、名称 identity、逐 observation 单位、
  单位冲突、Golden 逻辑原文和研究宽表。
- 隔离新华 2023–2025 真实 PDF 3/3 通过。每份报告均为 1 个物理 Capture 作业和
  `portfolio_summary`、`portfolio_by_category`、`portfolio_by_measurement` 三个逻辑
  Capture；Capture 行级 Golden 均为 `MATCH`，OCR 为 0。
- 三年 244 个非空数值 observation 中，金额均为 `百万元/CNY_MILLION`，占比及增减率
  均为 `%/PERCENT`；无空金额单位、无跨 measure 单位冲突，非金额 observation 不生成
  `value_yuan`。
- 三份研究宽表固定列仅为 `member_table`、`canonical_item`，导出合同版本为 3；
  公式错误扫描为 0，渲染检查确认长项目名未截断。
- 扩大相关回归 134 passed / 1 failed；唯一失败为既有同页分离表拓扑 Resolver
  `selected_topology` 缺失，与本次改动路径无关。
- 浏览器 E2E 按用户要求跳过。

## 回退

代码修改集中于 v6.13 的 Capture、Direct 分块、Merge 与导出模块；恢复这些模块及对应合同、
测试即可回退。新字段均为可选，旧 Capture 仍可读取，但不会自动获得新身份和单位合同。
