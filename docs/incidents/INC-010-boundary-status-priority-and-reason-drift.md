# Incident Report INC-010: 边界状态推导优先级缺失与 reason 契约漂移

## 1. 事发现象 (Symptom)

- 债权投资 2024/2025：解析器已找到真实下一条附注（`next_note` HIGH），
  但 `BOUNDARY:REVIEW_REQUIRED` 仍存在。
- 交易性金融资产 2024/2025：`same_page_footer_fallback` 已生效，但
  `BOUNDARY:REVIEW_REQUIRED` 仍存在；表尾页码杂音行（85）破坏拓扑与列数判定。

## 2. 根本原因分析 (Root Causes)

- `derive_boundary_status` 先处理“显式 REVIEW_REQUIRED 复评”，安全辅助不通过即
  `return explicit`，强证据分支（next_note HIGH → HARD）永远执行不到。
- 解析器把 reason 从 `boundary_unresolved` 换成 `same_page_footer_fallback`，
  消费端仍只识别旧 reason/method，契约漂移。
- 表尾“85”页码杂音行无语义分类，进入拓扑（MISSING_SLOTS）、列数复核
  （VALUE_COLUMN_COUNT_MISMATCH）与终止行判定。

## 3. 正式修复

- 状态优先级：人工 > 强空间证据 > 复合完整性证据 > 机器默认；新增
  `boundary_status_source`（HUMAN_ADJUDICATION / MACHINE_DERIVED / MACHINE_DEFAULT）。
- `BoundaryReason` 枚举统一 reason 契约，消费端归一化旧字符串。
- footer fallback 复合证据：`terminal_row_status` / `continuation_status` /
  `post_terminal_noise_only` / `capture_completeness` / `confidence_basis=
  COMPOSITE_EVIDENCE` → `SOFT_BOUNDARY_CONFIRMED`（MEDIUM 置信度不抬高）。
- 表尾页码杂音复合分类（含印刷页码匹配），原始行保留并标记排除；
  拓扑、数据列复核、合表输出跳过被排除行。

## 4. 验证结论 (Verification Results)

- 新回归 14/14；相关既有 137 passed / 2 skipped。
- 债权投资 2024/2025 → `HARD_BOUNDARY_CONFIRMED`，PDF_BOUNDARY_UNCERTAIN 消除。
- 交易性金融资产 2024/2025 → `SOFT_BOUNDARY_CONFIRMED` + COMPOSITE_EVIDENCE，
  杂音行标记排除，拓扑 ALL_SLOTS_PARSED，PDF_BOUNDARY/HEADER_TOPOLOGY/VALUE_COUNT 消除。

## 5. 后续注意

- 交易性金融资产 2024/2025 仍保留 `V69_RECONCILIATION_WARNING`（独立勾稽复核项）。
- 人工边界裁决路径已写入 `boundary_status_source=HUMAN_ADJUDICATION`，不会被自动逻辑覆盖。
