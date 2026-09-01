# ADR-013：金融投资列报制度身份与跨准则桥接

- 状态：ACCEPTED
- 日期：2026-08-25
- 范围：`FINANCIAL_INVESTMENT_V1`

## 背景

同一主报表可能同时列示当前期新准则成员与比较期旧准则成员。规范成员名不是物理行主键，
分析桥接组也不是来源事实；若用任一者关联附注、期间或金额，会把不同物理行合成为不存在的
“附注 + 金额”组合。旧准则与新准则直接折叠，还会隐藏分类口径差异或造成重复计算。

## 决策

1. 金融投资采用三层身份：`presentation_member_id` 保存来源列报成员，
   `canonical_analysis_bucket` 保存本制度内分析身份，`analysis_bridge_group` 只用于显式研究桥接。
2. Stage A 的附注、期间和金额必须先按 `source_row_id` 原子绑定，再根据整页期间状态裁决
   新旧制度身份；`member_table`、alias 或 bridge group 均不得充当物理关联键。
3. 原始口径 Canonical/Merge 始终保留，不允许桥接覆盖来源值。桥接只由正式 Merge owner
   从 resolved Canonical 投影，禁止建立第二条 Canonical/Merge 管线。
4. 同一桥接身份与期间存在多个有效来源时 fail-closed，禁止求和或按顺序取值。需要债务/
   权益或摊余成本拆分的旧准则来源，只有匹配 `certified_bridge_rule_id` 的认证拆分可放行。
5. 桥接身份包含公司、桥接组、分类轴、规范项目、认证父路径、同名 occurrence、报告年度、
   完整期间、口径、measure、unit 与 restated。`UNRESOLVED` 轴继续按物理 block 隔离。
6. 正式 Merge 同时输出原始口径、桥接长表、桥接宽表和桥接审计，并在两份研究 XLSX 中提供
   `金融投资_原始口径`、`金融投资_跨准则桥接`、`金融投资_桥接审计` 工作表。
7. 双 Registry 验收在既有七阶段内增加金融投资 V6 门禁：Discovery 消费只读 Evidence V2
   Shadow，Merge 校验四产物与禁止同期间求和，UI parity 比较列报成员/制度/V6 合同字段。
   没有桥接 membership 的成员仍须输出稳定空 schema，并只在审计中声明不参与桥接。

## 兼容与后果

- 历史 Capture 不改写；缺少 V6 字段时由 Registry 只读补充列报身份与桥接规则。
- 精确中文族名“金融投资”作为旧正式 Capture 的兼容身份，但不扩大金融投资 family 边界。
- 桥接警告不阻断原始口径 Merge；桥接值本身仍严格 fail-closed。
- `FINANCIAL_INVESTMENT_MEMBER_CONTRACT_V6` 是本决策的 Registry 合同版本。

## 验证

- v6.14 完整非浏览器测试 576/576 通过。
- 15 份真实 PDF Stage-A Shadow：15/15 PASS，`SHADOW_WORSE=0`。
- 隔离正式金融投资验收与 FakeStreamlit/Offline parity：12/12 PASS。
- 30 个正式 Merge 全部生成 V6 双视图，增强 schema/fail-closed 验收 30/30；首次发现的
  `time_deposits` 零行桥接无 schema 问题已由 INC-044 修复并复验。
- 国寿 2023–2025 真实 FVTPL 跨准则 Merge 同时保留新旧制度，53/53 桥接值进入显式
  `FVTPL_ASSETS` 视图，仅标记部分可比，不产生歧义求和或宽表身份冲突。
