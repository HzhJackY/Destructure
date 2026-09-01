# Changelog

## v6.9 — Financial Extraction Engine V2 and Research Definition Registry

- Hotfix：修复 Anchor 已人工认证后，被下一次歧义候选重新评分批量降级为 `ANCHOR_SELECTION_REQUIRED`；认证审计现为持久真源，机器推荐刷新不得覆盖人工认证，且可自动修复漂移的物化状态。
- Hotfix：修复新一轮 Discovery 后阶段 B 继续引用上一轮未认证 occurrence、生成计划时触发 `UNSELECTED_ANCHOR_NEVER_MATERIALIZES`；新发现会清空下游会话状态，认证后从 Registry 重新加载正式 Anchor。
- Hotfix：阶段 A 默认展示候选主报表 PDF 原页、父子项金额/附注编号和中文人工核对点；机器评分权重与硬门禁降至折叠的高级信息。
- Hotfix：Statement Anchor 候选先去重、再按可审计证据评分并按 PDF/口径保守单选；低分或歧义候选不预选，预选与人工认证严格分离。
- Hotfix：统一检查中心新增结构化 Review Issue/Task、审核进度、表头交互复核、最终数据列与末列专项检查；普通用户不再依赖手写 JSON。
- Hotfix：人工任务裁决、Anchor 认证与正负 ML 标签均追加保存审计记录；最终认证和 Merge 增加研究定义、定义版本、表族、口径与 current 身份硬门禁。
- SQLite schema 升级至 11；迁移为幂等增量，不修改历史机器证据。
- 新增 NoteContainer、TableBlock、CaptureBundle 及独立子 Capture 审计模型。
- 新增主报表 Statement Anchor 几何抓取，父行允许无金额并保留连续子项附注入口。
- 新增布局证据图、保守多表分段、表头拓扑及勾稽质量门。
- 将“逻辑资产工作区”收口为唯一单资产详情与审核中心；审核收件箱仅负责队列、筛选和路由，旧“附注多表检查”降级为兼容跳转。
- 新增稳定 InspectionRoute、统一 CaptureInspectionPanel、统一 PDF 证据面板与统一审核动作服务；合表来源也直接路由到同一检查中心。
- 人工确认、驳回、未解决与覆盖裁决采用版本级原子事务，并同步当前版本、收件箱、生命周期、Bundle 聚合状态及合表资格。
- 结构修改创建不可变的新 Capture Version；旧版本保留为只读历史，认证新版本后旧 current 自动 supersede。
- 新增版本化 ML 标签合同及可解释的层级回退排序；不涉及金额生成。
- v6.9 初始发布使用 schema 10，当前 hotfix 使用 schema 11。

## v6.8

- 修复研究引导抓取页面仍访问已移除 `generic_discovery.PRESETS` 的启动错误；可选知识包现完全来自 Research Definition / Table Family Registry，并以不可变 `discovery_context` 传入通用发现服务。
- 所有抓取入口统一为 CaptureRequest / CaptureOrchestrator。
- 移除 PRESETS 运行时变异，改为依赖注入策略。
- 新增逻辑资产、不可变 Capture 版本、生命周期审计、审核收件箱和归档恢复。
- 合表默认只接受 current certified active 版本。
- Runner 新增显式 join/shutdown，成功状态要求注册确认。
- 新增抓取中心、审核收件箱和逻辑资产工作区。

## v6.7.x — Adaptive Research Wide Preview & Legacy Upgrade Hotfix

- 自适应多层表头预览改为两种共享同一维度策略的视图：交互式预览直接复用数据资产管理的原生 `st.dataframe` 工具栏（查看、下载、搜索、全屏）；严格多层表头视图作为展示版 Excel 的视觉基准。原生组件的单层可读列名仅是交互呈现，不改变 Canonical Long 或 CSV 的机器身份。
- 修复下载的展示版 Excel 仍显示 `COL_00001` 等机器列 ID：`canonical_wide` 工作表现在只写人类可读的多层/合并表头和数据；稳定列 ID 仅保留在机器 CSV 与 `column_dimensions` 映射中。
- 已存在的合表若由旧展示版导出器生成，Canonical 宽表页会要求先“重新生成展示版 Excel 与宽表派生产物”，避免下载到与预览不一致的旧文件；新增当前预览 HTML 下载。
- 在“Canonical宽表 → 自适应多层表头预览”内直接增加下载入口：可下载含真实多行/合并表头的 `merge_project.xlsx`、机器稳定列 ID 的宽表 CSV，以及 `column_dimensions.csv` 维度映射；不再要求用户切换到独立下载页才能导出当前预览。
- 修复 Research Wide GUI 仍以旧式平面 CSV 方式显示的问题：现在直接读取 `COL_xxxxx + column_dimensions.csv`，使用与 Excel 导出一致的自适应表头策略渲染多层预览。
- 单公司、单口径、单单位、年度数据会将公司/口径/单位/期间移至元数据区，主表默认显示“报告年 → 数据年（已重述）”。多公司、混合口径、混合单位或必须区分原始/重述的同年份数据会自动提升相应表头层级。
- 新增明确的“升级旧合表为 v6.7 自适应宽表”入口：仅重建派生 Long/Wide/Excel/维度映射，不修改原始 Capture、机器证据或人工审核。
- 旧版宽表不再被误判为可用 Canonical Research Wide；若源 Capture 已有历史单位错误，升级仍会提示必须重抓原 PDF，绝不猜测金额。
- 修复旧合表升级时 `document_year` 被 CSV 读为 `int64`、随后写入规范化字符串年份而触发 Pandas 3 `TypeError` 的问题；升级器现在仅预先规范化期间身份字段，金额列保持原样。
- 修复旧合表升级在 Pandas nullable string / `pd.NA` 场景下清洗期间字段、scope、restated 标记时触发 `boolean value of NA is ambiguous` 的问题。

## v6.7.x — 新华保险 2023 附注 11—14 Capture Quality Hotfix

- 修复同一附注页“主余额表 + 后续信用损失变动表”被误视为一张表、进而触发表头列数冲突的问题；空间表头裁判现在只以首个已闭合主表的数据窗口为依据。
- 主表在合计/小计后出现独立说明文字时，自动截断为可审计的首表边界；不再把后续不同列拓扑的披露块混入同一 Note Detail Capture。主表后的“其中”拆分行仍会保留。
- 修复脚注文本中出现“本集团/本公司”被误识别为表头口径、使真实数据行被跳过的问题；表头上下文仅在紧邻表头的区域内生效。
- 新华保险 2023 年报附注 11、12、13、14 的首表均可完成空间抓取，并取得 `HARD_BOUNDARY_CONFIRMED + AUTO_CONFIRMED`；附注 12、13 的后续信用损失准备变动表不再污染主明细表的列结构。

## v6.7.x — Direct Ordinal Note Reference Hotfix

- 支持“附注八 + 11”章节式引用与“附注 + 11”直接序号引用；后者标准化为 `附注11` 并标记 `EXPLICIT_ORDINAL_COLUMN`。
- `NoteReferenceResolver` 可在没有 section 的情况下，以“附注序号 + 科目语义 + 表格特征”生成 `ORDINAL_SEMANTIC` 候选；认证前仍不允许执行抓取。
- `8/59(1)` 等交叉引用标记为 `CROSS_REFERENCE_REVIEW_REQUIRED`，保留原始证据且不伪造单一附注目标。
- 移除 `pdf_evidence.py` 中对“附注八”的固定假设，改为读取主报表实际附注列头。
- 修复 Generic Statement Discovery 未处理“项目行与附注序号分行提取”的问题；新华保险 2023 年报 PDF 109 的 `11—14` 现可生成可认证候选，目标明细页为 PDF 187—190。
- 修复 `GenericStructureParser` 未向审核 UI 物化 `note_target_candidates` 及主表策略变量遗漏，避免出现“未找到可认证附注目标”。

## v6.7 — Registry-Driven Generic Research Data

- 新增可持久化、可审计、可版本化的 Research Definition / Table Family / Member / Discovery Strategy / Metric Mapping Registry。
- 新增 pattern-driven Generic Discovery Engine，支持主表多附注、单项附注、直接附注表族和直接披露策略；金融投资不再是 UI 中的独占特判。
- 新增 `investment_portfolio` 第二个 Golden Family，包含“按投资品种”和“按会计计量”两个独立直接披露 member tables。
- 新增 Accounting Semantic Parser v2：统一 `SECTION/DETAIL/SUBTOTAL/TOTAL/IMPLICIT_TOTAL/ADJUSTMENT/MEMO_TEXT` 等 row-role ontology，推导语义不覆盖机器证据。
- Canonical Wide CSV 切换为稳定 `COL_xxxxx` 列 ID + `column_dimensions.csv`；Excel 输出观察维度分层表头。
- 新增 `VisibleHeaderDimensionPolicy`：按数据实际唯一值自适应区分元数据与可见列头；混合公司、口径、单位或期间不会静默折叠。

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
