# Current Task Analysis

## 2026-08-24 双 Registry 通用完整验收收口

### Objective

在不建立平行 Discovery/Capture/Canonical/Merge 的前提下，完成
`INVESTMENT_PORTFOLIO_V2` 与 `FINANCIAL_INVESTMENT_V1` 的 4 公司 × 3 年
Offline/UI 非浏览器验收，并以当前 PDF、正式认证资产、Golden v1.2、正式 Merge
和稳定业务身份给出逐 Registry 完成状态。

### Current blockers

- 金融投资 UI Stage B 仅提交 38 个已认证成员请求，而正式 Offline lane 为 49 个；
  UI 尚未复用同一 Anchor 下已经正式认证但本次自动发现未重新产出的 primary links。
- 投资组合既有逐 filing 诊断库没有克隆正式 PDF/认证资产，不能作为最终
  `RegistryAcceptanceHarness` 的 Corpus/Certification 证据。
- UI/Offline Capture parity 已覆盖投资组合 12/12；金融投资仍为 6/12。
- Merge grouping parity、失败注入、全量测试与最终交付物尚未收口。

### Owner modules allowed in this phase

- `hierarchical_child_discovery.py`：只读恢复同 Anchor、同 Registry 的正式认证 links。
- `guided_workflow_ui.py`：Stage A 认证后将本次新 links 与正式已认证 links 做精确身份并集。
- `registry_acceptance.py`：消费离线/UI parity 证据，不执行抓取或伪造认证。
- `components/child_capture_execution_panel.py`：UI scope 呈现与提交语义。

### Frozen boundaries

- 生产 DATA_HOME 只读；所有执行使用 SQLite backup 创建的隔离 DATA_HOME。
- Golden 不由机器 Capture 生成或补值。
- 正式路径仍为 CertifiedChildTableLink → Whole-table Capture → Reducer →
  Canonical Long → Merge → Research XLSX。
- 浏览器 E2E 按用户要求跳过，只运行 FakeStreamlit Python 入口回放。

### Completion evidence

- 两个 Registry 各自 12/12 逐阶段矩阵；primary scope 身份和数据差异为零。
- UI/Offline 的稳定业务行、父子边、Canonical 与 Merge 分组一致。
- supplementary coverage 单列，不用 `NOT_AUDITED` 包装成成功。
- fail-closed 失败注入、完整 pytest、Change Report、完成卡、terminal summary、final QA。

## Objective

将 v6.13 UI、Canonical 与 Merge 的行层级消费统一到 Spatial Capture 认证的
`source_row_id` / `parent_row_id` 图；新增与物理来源身份分离的跨年度
`semantic_row_key`，消除 UI 与合表继续依赖旧字段而产生的口径漂移。

## Task type

CONTRACT_CHANGE / BUG_FIX / MIGRATION

## Relevant owner modules

- `components/capture_inspection_panel.py`：Capture 行结构复核投影。
- `financial_structure_resolver.py`：认证父子图的只读派生视图。
- `table_merge.py`：来源语义键、Canonical 行键与跨年度合并。
- `identity_migration.py`：历史资产兼容迁移与审计。

## Planned files

- 上述 owner modules 及定向测试。
- `ARCHITECTURE.md`、`DATA_CONTRACTS.md`、ADR-011、事故记录、Change Report。
- `output/_agent_runs/v613_identity_consumer_migration_20260817/` 任务证据。

## Upstream contracts

- Spatial Capture 是 `source_row_id`、`parent_row_id` 和 `row_role` 的唯一裁判。
- 原始 PDF、bbox、原生 span 与 Capture 证据不可被消费端改写。

## Downstream contracts

- UI 只从认证父子图派生展示路径和层级。
- `source_row_id` 只用于单份来源追溯和同 Capture 重复行消歧。
- `semantic_row_key` 使用 member、classification axis、normalized item、语义父链及必要 occurrence，负责跨年度对齐。
- Canonical observation 身份在 semantic row key 后追加 period/measure/scope/restated。

## Frozen rules at risk

- 禁止下游重新推断父子关系。
- 不得用物理 bbox/PDF 身份阻断相同经济行跨年度对齐。
- 未解析父项、循环父子图或重复语义行必须 fail-closed，不得静默折叠。

## Relevant incidents

- `docs/INC-20260817-identity-multi-writer.md`。
- 本轮新增 UI/Merge 旧字段消费导致身份口径漂移事故记录。

## Required tests

- 不同年度 `source_row_id` 的同一经济行生成相同 `semantic_row_key`。
- 同名行在不同父项下生成不同语义键。
- 同一父项下同名重复行使用 occurrence 消歧。
- UI 派生路径与 Merge 派生路径一致。
- 正式路径不依赖 `parent_section`、`row_level`、`row_type`。
- 旧 Capture 缺少新身份时明确进入兼容/审核路径。

## 2026-08-18 合表 dtype 回归修复

## Objective

修复旧 Capture Long 合表时空 `parent_row_id` 被 pandas 推断为 `float64`，
兼容投影写入字符串父 ID 触发 `TypeError` 的问题。

## Task type

BUG_FIX

## Relevant owner modules

- `financial_structure_resolver.py`：认证父子图的 UI/Merge 只读投影。
- `tests/test_v613_merge_parent_id_dtype.py`：旧 CSV 与 Arrow 字符串列回归。

## Planned files

- `financial_structure_resolver.py`
- `tests/test_v613_merge_parent_id_dtype.py`
- 本任务 `output/_agent_runs/v613_merge_parent_id_dtype_20260818/` 运行证据。

## Upstream and downstream contracts

- 不改变 Capture 身份、父子裁判、Canonical/Merge 键或历史数据。
- 投影入口必须接受旧 CSV 的空浮点列和 Arrow 字符串列，并保持 `parent_row_id`
  只来自认证/兼容证据。

## Required tests and validation

- `read_csv` 产生的全空 `float64` `parent_row_id` 能写入字符串父 ID。
- Arrow `string` 身份列能完成相同投影。
- 定向身份/Merge 测试；不运行浏览器 E2E，不修改生产 DATA_HOME。

## Rollback plan

回退投影入口新增的 object dtype 归一化和本轮测试文件即可；不涉及数据库迁移。

## Required real-PDF Canaries

- 使用最小可认证的 Direct 投资组合 Capture Plan 验证 Long → Canonical → Merge。
- 若现有 Header Topology 门禁仍阻断，记录为外部阻断，不绕过。

## Required database/UI validation

- 不修改生产 DATA_HOME。
- 不运行浏览器 E2E；仅运行组件纯投影测试与离线 Merge 回归。

## Non-goals

- 不改变 ROI、OCR、期间、单位、金额、Golden 或拓扑分类。
- 不删除历史字段，不执行破坏性 schema 迁移。
- 不建立平行 UI、Canonical 或 Merge 管线。

## Rollback plan

- 新语义键实现为既有 Merge 路径内的纯派生；回退时恢复旧 source-key 生成函数即可。
- 旧字段继续保留为 lineage/只读兼容，生产数据无需回滚。
