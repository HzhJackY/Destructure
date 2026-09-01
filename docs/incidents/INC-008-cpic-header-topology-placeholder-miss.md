# Incident Report INC-008: “-”破折号披露行被误判为表头拓扑歧义

## 1. 事发现象 (Symptom)

中国太保 2025 年报「债权投资」附注抓取（运行
`中国太保2025年报__债权投资__20260803T150547_938828`）在评审队列中误报
HIGH「表头拓扑需要复核」（`HEADER_TOPOLOGY_AMBIGUOUS`），阻塞认证。机器证据：

```json
{"numeric_widths": [1, 2], "consistent": false, "candidate_types": ["AMBIGUOUS"], "score": 0.55}
```

## 2. 根本原因分析 (Root Causes)

- 附注表第 3 行「企业债」2025 列为 `-`（PDF 第 156 页原文：企业债 / - / 98,265），
  是“本期无余额”的真实披露写法。
- `compound_note_engine._topology()` 旧逻辑按“每行可解析数值数”求宽度签名：
  该行只有 1 个数值，其余行 2 个 → 签名 `{1,2}` → 误判表头层级不确定。
- 破折号被当作“缺列”而非“已占用的金额列占位符”，信息丢失。

## 3. 正式修复

- 单元格状态分类：`NUMERIC / PLACEHOLDER / EMPTY / UNPARSEABLE`。
- 合法占位符 = 纯破折号 token（`^[-–—－]+$`）+ 已对齐金额列（`column_ordinal` 非空）。
- `_topology()` 优先按表头列数与“已占用金额槽位”判断；占位符计入占用槽位，
  真正缺列（无 token/无 bbox/无占位证据）仍判歧义。
- 拓扑证据扩展审计字段；`CaptureDecisionReducer` 门禁不放宽。

## 4. 验证结论 (Verification Results)

- 新增回归 14/14：正常双年度、单/双侧破折号、负数（`-98,265` 仍为 NUMERIC）、
  横线（UNPARSEABLE）、真缺失（保持歧义）、reducer 门禁。
- 真实资产：太保 2025 债权投资 → `consistent=true`、
  `TWO_PERIOD_COLUMNS`、`HEADER_ALIGNED_WITH_DISCLOSED_PLACEHOLDERS`；
  太保 2025 交易性金融资产（含页码杂音行）→ 仍 `consistent=false`，未被过度放宽。
- 既有相关回归 93/93 通过。

## 5. 后续注意

- 太保 2025 交易性金融资产仍被阻塞，根因是单槽杂音行（页码 token 被捕获为行），
  属另一上游问题（噪声行过滤），不在本修复范围。
- 破折号的数值语义（无余额/不适用/未披露）仍由后续披露语义规则决定，本修复不解释为零。
