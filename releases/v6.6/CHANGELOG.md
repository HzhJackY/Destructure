# Changelog

## v6.6.x — Financial Statement Context & Canonical Observation Hotfix

- 新增 `DocumentContextResolver`：从文档声明页继承金额单位、币种、报表口径和重述状态；后续显式声明可覆盖，并为每项数值保留 `context_source_page`。
- 修复附注续页将“人民币百万元”误判为“元”的问题；主值保留 PDF 原始计量单位，`value_yuan` 仅作为可审计的派生换算值。
- Canonical Observation Contract 明确拆分 `report_year`、`data_year`、`period_type`、`currency_unit`、`restated_flag` 与 `statement_scope`；宽表列头改为具名维度，避免将 `2023/2022` 混成复合字段。
- 合表观察身份加入来源主表和完整期间/单位/口径维度；每个已解析值保留 PDF、页码、bbox 与上下文来源页的 provenance。
- 仅以中国平安 2023 年报附注 9—12 进行了定向验收；未运行全历史回归。
- 合表 UI 会识别旧版 `merge_canonical_wide.csv`，不再把旧复合列头伪装成 v6.6 Canonical 输出；可在保留来源 Capture 与映射审核的前提下重建派生合表。历史 Capture 若已写错金额单位，仍必须重抓原 PDF，不会被合表静默篡改。

## v6.6.x — Source-Aware Member Table Merge Identity

- 修复实际 Guided Capture 经 `MergeService → table_merge.py` 旧路径时丢失 `member_table` 身份的问题；不再只按 `canonical_item/row_path` 比较不同附注明细表。
- Capture 元数据、作业载荷和合表元数据恢复链统一保存/恢复 `table_family`、`member_table`、`member_table_role`、来源主表、附注号、来源 PDF 和子表顺序。
- `VALUE_CONFLICT` 仅在同表族、同子表、同角色、同行路径、同完整列维度下且金额不同才阻断；来源身份缺失改为可审计 `REVIEW_REQUIRED_SOURCE_IDENTITY`。
- 新增来源身份 QA 输出、合表宽表可见的表族/子表字段、源感知结构顺序和中国平安 2023 真实年报验收。

## v6.6.x — 当前 Capture 质量、审核证据与注册一致性收口

- 修复 `HARD_BOUNDARY_CONFIRMED` 但结果审核显示 `REVIEW_REQUIRED`：当前质量不再继承历史 Job 状态；边界、表头与行语义由 `capture_readiness` 实时合成。
- `raw_item=NULL` 且已认证为 `IMPLICIT_TOTAL` 的空标签合计行视为已恢复结构；只有 `IMPLICIT_ROW_CANDIDATE` 或旧 schema 中未认证的匿名数值行阻断合表。
- 人工边界截断后仅对保留行重新计算 `MIXED` 与隐式行质量，已排除的机器证据仍保留但不再污染当前质量。
- 恢复发现结果审核与 Capture 结构审核的 PDF 预览；支持主表/附注双页、bbox 高亮、PDF页/印刷页，并为缺失、越界、加密和渲染失败提供非崩溃状态。
- 修复并发抓取注册竞争：同步串行化并重试，实时质量回写 `capture_metadata.json`，失败写入 `runtime/registry_sync_errors.jsonl`；CaptureService 在注册缺失时不再把 Job 标成成功。
- 增加 MergeService 实时质量硬门禁；数据库中过期的 `merge_ready` 无法绕过当前机器证据。
- 精化边界：只有相邻附注编号的高置信 `NEXT_NOTE_ORDINAL` 可自动成为硬边界；非相邻同级标题保持中置信待审，含多个数值的普通数据行不会被识别为附注边界。
- 中国平安 2023—2025 三份真实 PDF 完成 12 个明细首次抓取和 12 个认证重跑，全部 `SUCCESS`，并验证当前质量投影、注册持久化与合表门禁。

## v6.5.1 — 多 PDF Anchor 批量计划与 Streamlit 状态修复

- 引导式抓取的 Anchor 从单选改为多选；每份 PDF 保留独立的 `StatementOccurrence`、Anchor Adjudication 和 Capture Plan。
- 批量认证只是一键操作：仍逐份写入审计记录，避免把 2023–2025 年报混成一个跨文档 Anchor。
- 一次认证多份报告后生成多张独立计划；每份计划均为 `1 个主报表构成 + N 个附注明细`，一键抓取也按各自来源 PDF 提交。
- 修复 Streamlit widget key 冲突：按钮 key 不再与 session-state 计划对象共用 `v65_plan`，避免 `StreamlitAPIException`。
- 新增中国平安 2023–2025 真实年报回归：三份合并资产负债表均定位到金融投资 Anchor，每份生成 5 表计划，合计 15 表。

## v6.5 — Statement-Anchored Table Family

- 新增独立 release 目录策略；v6.4 源码快照冻结，DATA_HOME 保持共享、迁移只追加。
- 公司筛选从文件存储名剥离 SHA 前缀，按规范化公司名聚合。
- 新增 `StatementOccurrence`、Anchor Arbitration、Statement Anchor Table、Capture Plan 和引导式一键抓取服务。
- 新增列头附注 section + 行编号组合、附注状态、候选/确认页和 PDF/印刷页双页码合同。
- Discovery 证据先聚类，再审核；新增批量审核与逐条审计写入。
- 继续保留手工/高级抓取入口，避免与引导式主流程混用。

## v6.4 — Generic Discovery Review + Certified Knowledge

### 新增
- 任意 `display_name` 进入 Generic Statement-Guided Family Discovery；preset 改为可选知识包，不再是功能开关。
- 新增不可变机器发现、人工审核、认证发现、快速路径及训练样本的分层 SQLite 证据链。
- 新增审核中心和发现规则与学习库；审核支持 ACCEPTED/REJECTED/OVERRIDDEN/UNRESOLVED，并保留操作者、理由、旧值和新值。
- 新增 company → filing type → statement type → table family → member table 的分层回退契约。
- 公司选择器按规范化公司聚合，避免 asset hash + 公司名重复显示。
- 新增 `version.py` 作为运行时版本单一来源；BAT、launcher、页面统一读取 v6.4。

### 迁移与兼容
- SQLite schema 从 2 增量迁移到 3，仅新增 discovery/adjudication/certified/training 表；不改写既有 PDF、Capture、Merge、Notes 或机器证据。
- v6.3 Family Merge 身份合同继续使用 `table_family/member_table/source_table_title/note_reference`，研究宽表仍隐藏内部 `canonical_key/order_source`。

## v6.3 — Statement-Guided Navigation + Family Merge

### 新增
- 增加 PDF Selection Workspace v2：来源模式、公司/年份多选、文件名包含/排除、筛选结果全选和持久化选择集合。
- 增加可缓存、文本优先的 PDF Index、主报表定位、附注引用抽取、主表—附注导航图与保守回退路径。
- 增加表族三级身份和双轴 Family Merge：成员表保持并列结构，相同列维度合并，行路径含 member table 语义。
- 增加 Research Output Contract v2 和 `column_dimensions` 映射；最终宽表默认隐藏 `canonical_key`、`order_source`。
- 增加独立 Table Notes / Footnote Evidence Layer，原始备注、页码、bbox、来源链与辅助分类可审计保存。

### 兼容与迁移
- **非破坏性 schema 迁移**：SQLite 从 v1 升至 v2，仅新增 `capture_semantics`、`statement_note_edges`、`table_notes`；原 Capture、PDF、JSON、CSV/Parquet 不被回写或重写。
- 旧的单表 Merge 保持可用。Family Merge 是新的派生研究层；完全相同观测键但不同数值仍是阻断性 `VALUE_CONFLICT`。
- FastAPI/React 不属于 v6.3；本版仅固定 API-ready 的结构化数据合同。

## v6.2 — Multi-PDF Table Family + Financial Structure Resolver

### 批量任务与表族
- 增加受控并发的多 PDF 整表抓取、持久化 Job 状态、失败隔离与 retry lineage。
- 增加 `TableFamily`：同一年度可独立抓取多个目标表，并判定 LEGACY_COMBINED / SPLIT_COMPONENTS / PARTIAL_COMPONENTS_REVIEW_REQUIRED 等结构版本。
- 每个批次保留 job manifest 和 schema variant summary，不拼接、不覆盖来源 Capture。

### 财务结构与合表安全
- 增加多证据行结构派生：显式 parent_section、row_level、顺序和小计/合计语义共同形成置信度；缩进/层级不是唯一规则。
- 导出 `row_path`、`parent_row_order`、`structure_confidence`、`structure_evidence`，防止不同父节点下的同名明细相互覆盖。
- 增加单位/四舍五入敏感的小计核对：`PASS` / `PASS_WITH_ROUNDING` / `WARNING`。
- 维度缺失 + 多物理列造成的多值结果改为 `REVIEW_REQUIRED_DIMENSION_AMBIGUITY` 警告；完全同键的不同数值仍为 `VALUE_CONFLICT` 阻断。

### 模板与 LLM 配置
- 增加历史结构模板存储、相似度检索和可替换 `StructurePredictor` 接口，为后续 ML 排序模型预留契约。
- 增加 `config/llm_config.example.yaml` 与本地加载器；本地密钥文件被 `.gitignore` 和交付打包排除。

## v6.1 — Backend Decoupling + SQLite Metadata Registry

### Backend architecture
- Added SQLite metadata control plane at `DATA_HOME/metadata.db`.
- Added `MetadataRegistry` with WAL mode, foreign keys, indexed Capture/Batch/Merge/Job tables.
- Added Repository Layer for Captures, Batches, Merges, PDFs, and Jobs.
- Added Service Layer for Capture, Review, Asset, Batch, Merge, PDF, Registry, and Jobs.
- Added `backend_context.py` dependency container with no Streamlit dependency.
- Added headless `service_cli.py`.

### Metadata registry
- First v6.1 launch bootstraps existing DATA_HOME into SQLite once.
- Registry is rebuildable from filesystem evidence.
- New Capture/review/merge write paths include best-effort registry synchronization hooks.
- Added manual full-sync from UI and CLI.

### Data Asset Management
- Capture asset list now uses SQL-backed filtering and pagination.
- Dependency impact uses indexed `merge_sources` rather than rescanning every Merge for each selection.
- Batch main list excludes fully trashed batches.
- Added Batch aggregate status and dedicated Batch Trash view.
- Lifecycle operations use Service Layer and dual-write to legacy metadata/evidence + SQLite index.

### Job foundation
- Added persistent jobs table and `JobService`.
- Status contract: `QUEUED / RUNNING / SUCCESS / REVIEW_REQUIRED / FAILED / CANCELLED`.
- Heavy multi-PDF worker orchestration remains scheduled for the next workflow release.

### Project cleanup
- Historical per-version README/CHANGELOG files moved from project root to `docs/history/<version>/`.
- Root now uses consolidated `README.md` + `CHANGELOG.md`.
- Current guides live in `docs/current/`.

### Preserved
- v5.7 relative-period/wrapped-row fixes.
- v5.8 absolute-year resolution.
- v5.9 Classic + Generalized dual-header arbitration and topology review.
- v6.0 asset lifecycle, batch invalidation, stale Merge protection, and single-instance launcher.
- v6.0.1 Batch ID callback hotfix.

## v6.0.1
- Fixed Streamlit Session State exception when generating a new Capture Batch ID.

## v6.0
- Added Data Asset Management Center.
- Added Capture lifecycle: ACTIVE / INVALIDATED / TRASHED.
- Added bulk invalidation, trash/restore, batch rerun, Merge dependency stale marking.
- Added single-instance launcher and graceful restart/exit control.

## v5.9
- Added Classic + v5.7 Generalized dual-header parsers.
- Added independent numeric-column referee and parser arbitration.
- Fixed 4-real-column → 8-machine-column header regression.
- Added manual parser selection and safe KEEP/DROP topology review.

Older detailed notes are archived under `docs/history/`.
# v6.2

- 新增 Multi-PDF Parallel Capture、Table Family Capture 与持久化 Batch Job 监控；
- 新增受控 Worker、失败隔离、可重试 FAILED 作业及批次审计汇总；
- 保持 v5.9 / v6.0 / v6.1 回归门槛，并新增 `regression_v62.py`。
