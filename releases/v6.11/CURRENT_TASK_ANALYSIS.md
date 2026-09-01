# Current Task Analysis

## Objective

修复阶段 B 的业务数据合同：主表 OCR 源行不能污染成员名称；阶段 B 必须以注册表标准成员名和别名检索子表；OCR 数字只能作为只读定位证据展示，不能进入认证金额通道。

## Task type

BUG_FIX / CONTRACT_CHANGE

## Relevant owner modules

- `statement_family_resolution.py`
- `generic_structure_parser.py`
- `hierarchical_child_discovery.py`
- `guided_workflow_ui.py`

## Planned files

以上模块、定向回归测试、阶段 B incident/Change Report。

## Upstream contracts

Canonical PDF、Statement Family Resolution、Research Definition Registry、Fast Index OCR token/geometry evidence。

## Downstream contracts

CertifiedChildTableLink、Capture Orchestrator、CaptureDecisionReducer。阶段 B 的标准成员 ID 和主表金额通道必须可追溯。

## Frozen rules at risk

规则 002、003、008、012、014：不得发明金额、OCR 数值隔离、期望成员来自定义、不得产生重复管道、修改必须有回归。

## Relevant incidents

- `docs/INC-20260803-stage-b-unresolved-period-gate.md`
- OCR 源行被显示层和严格标题检索误用，导致“有主表成员却无候选”。

## Required tests

- 标准成员名/别名驱动 Tier 2 标题匹配。
- OCR 金额候选只读显示，认证金额仍为空。
- 旧 discovery cache 因版本升级不再复用。

## Required real-PDF Canaries

中国平安 2023 年报阶段 B 子表候选可被正确检索；中国太保 2023 年报主表定位不回归。

## Required database/UI validation

无 schema migration；使用隔离 scratch registry 做真实 PDF Stage B 验证。

## Non-goals

不将 OCR 数字升级为认证主表金额；不改 Capture / Merge。

## Rollback plan

恢复阶段 B 结构字段与 discovery version；旧缓存不再由新版命中，生产证据不被删除。

---

# Current Task Analysis — 中国人寿 2023 Streamlit Golden 成员别名漏判

## Objective

修复 Stage-A Streamlit Golden 比较器对 `legacy_loans` / `loans` 的单侧规范化：
机器行与 Golden `member_id` 使用同一 lookup identity，展示和审计仍保留
Golden 原始 `legacy_loans`。

## Task type

BUG_FIX / QA

## Relevant owner modules

- `golden_acceptance.py::compare_statement_anchor()`
- `tests/test_v611_golden_streamlit_acceptance.py`

## Planned files

- `golden_acceptance.py`
- `tests/test_v611_golden_streamlit_acceptance.py`
- `docs/incidents/INC-015-china-life-loans-primary-supplementary-identity.md`
- 本任务 Change Report 与完成交付物

## Upstream contracts

Golden 当前期成员断言、Statement occurrence `child_rows`、显式且有界的成员别名表。

## Downstream contracts

Streamlit Stage-A Golden 门禁、Anchor 认证、后续 CertifiedChildTableLink 解析。

## Frozen rules at risk

- Golden 只读，不得为迁就 UI 修改认证事实。
- 别名只解决成员 lookup identity，不改附注、金额或人工裁决。
- 不创建第二条 Discovery/Capture 链路。

## Relevant incidents

- ADR-002：中国人寿保留隐式成员集，不伪造父行。
- INC-015：中国人寿 2023 贷款主表/补充表身份及 Golden parity。

## Required tests

- 中国人寿 2023 五个当前期成员全部 `MATCH`。
- 机器行 `legacy_loans` 通过 `loans` lookup 命中 Golden，返回行仍显示
  `member_id=legacy_loans`。
- 既有 Streamlit Golden acceptance 定向测试不回归。

## Required real-PDF Canaries

对正式库最新中国人寿 2023 occurrence 执行只读 comparator canary，确认
`603,639` / `附注十-8` 不再误报“未找到”。

## Required database/UI validation

无 schema migration；正式 `metadata.db` 仅以 `mode=ro` 读取。本子任务不代替完整浏览器 E2E。

## Non-goals

不修改 Golden、正式数据库、家族边界、Capture/Merge，不处理独立的
`period_recognized=false` 门禁。

## Rollback plan

回退 comparator lookup 规范化与对应回归测试；Golden 和数据库无需回滚。

---

# Current Task Analysis — Streamlit Stage B P0

## Objective

在允许人工选择财务主报表锚点的前提下，使当前 Streamlit Stage B 会话完成 inventory
认证、逻辑表选择、Capture Plan、scope、Capture 与 Merge；隔离历史计划和失效批次。

## Task type

BUG_FIX / USER_JOURNEY / CONTRACT_ALIGNMENT / QA

## Owner modules

- `guided_workflow_ui.py`
- `components/child_capture_execution_panel.py`
- `services/child_capture_execution_service.py`
- `services/batch_service.py`
- `app.py`

## Required invariants

- 当前页面只消费当前 session plan IDs 与 certified logical IDs。
- `DRAFT` 可编辑、`SUBMITTED` 只读；变化创建新版本，不修改提交事实。
- 正常路径不依赖 legacy 显式附注审核；仅 unresolved 进入异常审核。
- zero-active、TRASHED、REVIEW_REQUIRED 不得开放 Merge。
- UI 使用“财务主报表锚点 / 附注主明细表 / 附注分页续段 / 附注补充分析表”。

## Required tests

当前计划过滤、inventory→plan、scope 版本化、批次 readiness、术语映射、人寿 alias、
Streamlit headless/component 集成、空壳 unresolved 映射过滤、preview 不落库、
重启后最新 session 恢复。Browser skill 保持暂停。

## Non-goals

Anchor 自动选择和太保 period gate 延期；不修改正式数据库或内部枚举。

---

# Current Task Analysis — Streamlit Stage B 首次提交持久化断点（resume 019fcad8）

## Objective

恢复会话 `019fcad8-7a52-7b82-b74d-d482d063202e`（2026-08-05 02:39 因配额中断）
未完成的 Stage B P0 收口：Stage B 面板“确认逻辑表并抓取”必须把同一份
certified inventory/plan 回传执行服务，使首次使用（无既有 session 行）也能在显式
提交中原子落库并执行，而不是落入 `persist_capture_scope` 的
`STAGE_B_EXECUTION_SESSION_NOT_FOUND`。同时完成面板术语切换
（“主表/补充表”→“附注主明细表/附注补充分析表”，仅展示层，不改持久化枚举）。

## Task type

BUG_FIX / CONTRACT_ALIGNMENT / QA

## Relevant owner modules

- `components/child_capture_execution_panel.py`
- `services/child_capture_execution_service.py`（只读确认，不回改服务合同）
- `tests/test_v611_stage_b_persistence_integration.py`
- `presentation_labels.py`

## Planned files

- `components/child_capture_execution_panel.py`
- `tests/test_v611_stage_b_persistence_integration.py`
- `docs/incidents/INC-016-stage-b-first-use-submit-not-persisted.md`
- 本任务 Change Report 与完成交付物

## Upstream contracts

Stage A 认证后的 `v610_certified_child_links` / `v66_certified_plans`；
`preview_capture_plans`（只读预览，persist=False）；`create_execution_batch`
（`certified_links or plans` 存在时走 `prepare_capture_plans(persist=True)`）。

## Downstream contracts

`stage_b_execution_sessions`、`capture_plans`、research batch lineage、
Capture Plan 唯一回调 `GuidedCaptureService.execute`；scope 版本化
（v1 冻结 / v2 logical-table）不被破坏。

## Frozen rules at risk

规则 011（UI 渲染不改业务状态，仅显式提交持久化）、规则 014（修复必须回归）、
ADR-008（scope 选择由显式用户操作写入持久化 CaptureRequest）。

## Relevant incidents

- ADR-008：Stage B 抓取范围与同附注多子表分类。
- INC-013：Capture 完成元数据投影漂移（只读投影与执行态分离）。
- 本任务新建 INC-016。

## Required tests

- 面板源码回归：按钮调用 `create_execution_batch` 时回传
  `certified_links` / `source_pdf_map` / `plans`（文本不变式）。
- 既有 service 级首次使用原子落库用例继续通过（`test_both_entry_adapters_*`）。
- 面板复选框使用新展示术语，持久化枚举不变（`test_v611_presentation_labels.py`）。

## Required real-PDF Canaries

无代码路径变更至 Capture/Merge；本次为 UI 提交链路与展示层修复，
真实 PDF Canary 不属于本子任务范围（浏览器验收仍按用户约定暂停）。

## Required database/UI validation

测试仅使用临时 SQLite；正式库只读不触碰。

## Non-goals

不修改 `create_execution_batch` 服务合同；不删除兼容流程入口；
不做浏览器 E2E；不初始化 git 仓库（引擎升级选项未选择）。

## Rollback plan

回退面板回传参数与展示术语补丁；删除新增文本不变式与 INC-016；
服务层与数据库无需回滚。

---

# Current Task Analysis — 中国人寿 Stage B 只显示/抓取 2023 修复

## Objective

修复用户复测中国人寿三年年报时 Stage B“抓取逻辑表”只显示 2023、且实际只抓取
2023 的问题。根因链为：

1. 对同一 PDF/附注容器重复执行阶段 A 认证时，系统创建全新的 candidate /
   inventory / logical candidate 树（新 ID），与今晨已认证的 inventory/links
   （旧 ID）在同一附注容器上冲突，`_auto_certify_inventory_links` 抛
   `NOTE_TABLE_INVENTORY_ID_MISMATCH`，`assign_global` 对所有子表返回
   `AUTOMATION_REPAIR_REQUIRED`，认证链接数为 0。
2. UI 在“有已认证 occurrence、但 0 条 certified links、且无未决映射”时静默
   回退到 restore-only 分支，展示数据库中的历史会话计划（太保 + 国寿2023），
   其中旧格式计划（缺 certified_note_target/segment manifest）被“抓取逻辑表”
   过滤，仅国寿2023 新格式计划可见 → 表现为“只有2023”。
3. 用户点击“确认逻辑表并抓取”执行了该历史会话 → 仅生成国寿2023 抓取作业。

## Task type

BUG_FIX / CONTRACT_ALIGNMENT / QA

## Relevant owner modules

- `hierarchical_child_discovery.py`（`_auto_certify_inventory_links` /
  `_adopt_existing_container_links`）
- `guided_workflow_ui.py`（认证零产出时 fail-closed，不回退历史会话）
- `tests/test_v611_certified_child_segments.py`
- `tests/test_v611_stage_b_persistence_integration.py`

## Required tests

- 同附注容器重复认证（新 candidate/inventory/logical ID、同 PDF digest、同成员/
  分类）采用既有 certified links，不新建 inventory/link，状态 `AUTO_CERTIFIED`。
- UI 源码不变式：认证零产出时显示明确错误，不再调用历史会话面板。
- 既有 inventory/链接不变式（同一附注只能有一个 inventory）继续成立。

## Non-goals

不修改 certified 证据行；不删除历史会话；不做浏览器 E2E。

---

# Current Task Analysis — 系统与迁移页「旧数据完全清除」功能

## Objective

在 `app.py` 的“系统与迁移”页新增“旧数据完全清除”功能：用户显式确认后，清空
SQLite Registry 中的业务/运行数据并归档 DATA_HOME 派生产物到时间戳备份目录；
保留 schema、Research Definition、表族/成员、config/Taxonomy、Golden 与
`metadata.db` 文件本身。清除前强制备份并输出清除报告。

## Task type

FEATURE / DATA_LIFECYCLE

## Relevant owner modules

- `services/data_cleanup_service.py`（新增）
- `app.py`（系统与迁移页）
- `tests/test_v611_data_cleanup_service.py`（新增）

## Frozen rules at risk

- 规则 007：不得伪造认证状态；清除功能不产生任何认证。
- 规则 015：机器证据不可变——清除前必须备份，删除动作可恢复。
- 规则 017：报告不能证明完成——清除报告必须包含数据库行数与文件数证据。
- UI 规则 011：预览为只读，只有显式确认后才写状态。

## Required tests

- 业务表行清零、保留表（definitions/families/schema_meta）不受影响。
- 未输入确认 token 时拒绝执行。
- 备份存在且包含 DB 副本 + SHA256；归档目录被移动并重建为空目录。
- `include_pdfs` 时 `pdf_assets` 与 uploads 被清除/归档。
- 重复执行幂等无异常。

## Non-goals

不删除 `metadata.db`、schema、Research Definition、config/Taxonomy、Golden；
不自动触发清除（仅页面显式操作）；不做浏览器 E2E。

## 范围扩展（第二轮）

- 新增“仅抓取记录（保留认证）”作用域（`SCOPE_CAPTURE`）：只清
  capture/jobs/plans/sessions/审核/合并产物及其 DATA_HOME 目录，保留
  occurrence/Anchor/子表候选/认证清单/CertifiedChildTableLink/发现索引。
- UI 增加“清除范围”单选；预览缓存随 scope/include_pdfs 失效。

---

# Current Task Analysis — 合表输出新增「研究用宽表」下载

## Objective

现有 canonical_wide / 展示版 Excel 携带大量上下文固定列（row_path、canonical_key、
block 身份、source title 等），不适合直接做研究。新增独立“研究用宽表”产物：
仅保留 `member_table`、`canonical_item`、`unit` 与实际数据列（COL_xxxxx），
并复用原多层/合并表头架构输出独立 `research_wide.xlsx` 与 `research_wide.csv`。

## Task type

FEATURE / EXPORT_UPGRADE

## Relevant owner modules

- `table_merge.py`（`build_research_wide_frame`、`write_presentation_wide_sheet`
  sheet_name 参数化、`write_merge_outputs` 新增产物）
- `app.py`（合表区新增“下载研究用宽表 Excel/CSV”入口）
- `tests/test_v611_research_wide_export.py`

## Required tests

- 修剪函数只保留 member_table/canonical_item/unit + COL_* 列。
- `write_presentation_wide_sheet` 支持自定义 sheet_name。
- `write_merge_outputs` 产出 research_wide.csv/xlsx；xlsx 保持多层表头；
  原 canonical_wide 不受影响。

## Non-goals

不改动 canonical_wide 结构、不动 raw/canonical long；不改变映射与合并逻辑；
不做浏览器 E2E。

---

# Current Task Analysis — 合表顺序改为按所选年份附注号排序

## Objective

把合表 `canonical_order` 的排序策略从“单张基准 Capture 行序”升级为
“用户选择基准年份 → 按该年年报附注号（note ordinal）排序成员表 → 表内行序”。
旧策略保留为默认兼容；新策略通过 `NOTE_ORDINAL_REFERENCE_YEAR` +
`reference_report_year` 写入 manifest，合表页提供基准年份选择。

## Task type

CONTRACT_CHANGE / FEATURE

## Relevant owner modules

- `table_merge.py`（`_note_ordinal_base_order`、`build_structural_order`、
  `refresh_merge_project` 策略参数、structural order 增加 note_ordinal 列）
- `app.py`（合表页“合表顺序策略”基准年份选择）
- `tests/test_v611_note_ordinal_merge_order.py`

## Frozen rules at risk

- 合表身份/对齐/冲突规则不变；只改顺序基准来源。
- 附注号缺失/解析失败时回退旧策略并记录 warning，不阻断合表。

## Required tests

- 新策略：按 2023 附注号排序成员（6 前于 8），无 2023 来源成员追加末尾，
  note_ordinal 列正确。
- 旧策略默认不变（reference capture 优先，note_ordinal 为空）。
- refresh 持久化策略到 manifest 并生效。

---

# Current Task Analysis — 太保 Stage A Golden 门禁误报当前期缺失

## Objective

修复中国太保 2024/2025 Stage A Golden 门禁误报“当前期缺失或不吻合成员”
（2024: debt_investment；2025: fvtpl_assets、other_debt_investment）。

## 根因

扫描版主表 OCR 把千分位逗号误读为点（如 `4.986,274`、`611.682.378`、
`1.674.277.381`）；`CpicRowParser._spatial_amount_observations` 的数值正则
只接受 `\d[\d,]*`，带点 token 被丢弃，导致当前期列观察缺失，只剩比较期列，
Golden `amount_match=False`。

## Task type

BUG_FIX

## 修复

- `statement_family_resolution.py`：数值 token 正则改为接受 `.`/`,` 混合千分位
  分组（`\d{1,3}(?:[.,]\d{3})*`），带点 OCR 读数仍按列绑定为 Anchor 观察；
  比较端 `_amount` 本就剥离非数字，无需改动。

## Required tests

- 空间解析接受 `4.986,274` 并绑定到当前期列；
- 太保2024/2025 Golden 门禁在带点观察下全 MATCH。
