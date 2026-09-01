# Financial Metric Resolver v6.9

v6.9 采用金融提取引擎 V2：附注容器、多逻辑表块、Statement Anchor、表头拓扑与勾稽质量门。独立 release 位于 `releases/v6.9`，与 v6.8 共享 DATA_HOME，绝不覆盖 v6.8 源码。

完整设计见 `docs/V6_9_ARCHITECTURE.md`。

v6.8 采用统一抓取编排与逻辑资产治理。代码位于独立 `releases/v6.8`，
与 v6.7 共享 DATA_HOME，但不会覆盖 v6.7 源码。

架构和迁移边界见 `ARCHITECTURE_V6_8.md` 与 `capture_function_audit.md`。

## v6.8：Unified Capture and Logical Asset Governance

- 新增 Research Definition Registry、Table Family Registry、Member Registry、Discovery Strategy Registry 与 Metric↔Family Mapping；指标语义与采集结构不再混用。
- 内置 `FINANCIAL_INVESTMENT_V1` 与 `INVESTMENT_PORTFOLIO_V1`。投资组合使用 `DIRECT_NOTE_TABLE_FAMILY`，其“按投资品种”和“按会计计量”是独立 member tables，不与金融投资附注混合。
- 新增 pattern-driven Generic Discovery Engine、历史模板分层回退及 ML Predictor-ready 接口；无高置信候选时只返回 `REVIEW_REQUIRED/UNRESOLVED`。
- Canonical Research Long 是主数据真相；CSV 宽表采用 `COL_00001` 等稳定列 ID 并输出 `column_dimensions.csv`，Excel 输出分层观察维度表头。
- Wide Header 使用 `VisibleHeaderDimensionPolicy`：常量公司、口径、期间、币种/单位进入元数据；变化维度才进入 Excel/GUI 表头。单公司年度资料默认仅显示报告年→数据年→必要的重述层。

## v6.6.x：财务报表上下文与规范化观察值热修复

- `DocumentContextResolver` 会从“除特别注明外，金额单位为人民币百万元”等声明页向后继承单位、币种、口径和重述状态；后续页面如出现新的声明则覆盖，并记录 `context_source_page`。
- 原始观测值的 `value` 按 PDF 声明单位保存；`value_yuan` 是独立、可追溯的派生换算，避免把“1733996 百万元”静默写成“1733996000000 元”。
- 研究观察值明确使用 `report_year`、`data_year`、`period_type`、`currency_unit`、`restated_flag`、`statement_scope`；宽表列头采用具名维度，避免年份/口径混写。
- 每项数值继续保留来源 PDF、页码、bbox 和上下文声明来源页；合表身份同时考虑来源主表、期间、单位和口径。
- 历史合表项目的旧 `merge_canonical_wide.csv` 不会被当作当前契约输出展示；在“Canonical宽表”页可按 v6.6 契约重建派生文件。该动作不修改 Capture；旧 Capture 已发生单位换算错误时必须重抓 PDF。

## v6.6.x：来源感知 Member Table 合并身份热修复

- Family Merge 的观察身份正式固定为 `table_family → member_table → member_table_role → row_path → column dimensions`；不同子表内同名的“政府债”“金融债”“合计”会并列保留，不能再互相触发 `VALUE_CONFLICT`。
- Guided Capture 将已认证计划的表族、子表、角色、附注号、来源表与顺序写入 Capture 元数据；合表同时兼容从旧 Job 载荷恢复这些来源身份。
- 合表输出新增 `merge_source_identity_qa.csv` 与 `source_identity_qa` 工作表；缺失 member 身份只进入 `REVIEW_REQUIRED_SOURCE_IDENTITY`，不比较数值。
- 最终研究宽表显式保留“表族、子表、子表角色、行路径”；结构顺序先按子表顺序，再按子表内部行顺序。

## v6.6.x：Table Boundary & Note Text Contamination Hotfix

- `HARD_BOUNDARY_CONFIRMED`、表头状态和行语义现在由单一 `capture_readiness` 口径生成当前 Capture 质量；历史 Job 状态仅作为执行记录，不再把已恢复的 `IMPLICIT_TOTAL(raw_item=NULL)` 误显示成 `REVIEW_REQUIRED`。
- Certified Note Target 后强制经过 `Table Boundary Resolver`，以下一同级附注标题的页码和纵向坐标裁切表格区域。
- 完整引用（如 `附注八-9`）会先解析为附注 ordinal；支持阿拉伯数字、中文数字及括号形式。
- 低置信边界统一标记 `REVIEW_REQUIRED`，认证抓取禁止静默回退到绕过边界的 legacy extractor。
- 表内说明文字分类为 `MEMO_TEXT` / `NOTE_TEXT`，不会再作为 `DETAIL` 金额行。
- 单元格增加 `TEXT` / `NUMERIC` / `MIXED` 角色；`MIXED` 强制进入审核。
- 研究任务审核页展示主报表页、附注页、起始页、终止边界证据与置信度；PDF 缺失、损坏或页码越界只显示证据不可用，不再使 Streamlit 页面崩溃。
- Capture 注册采用并发串行化、重试和结构化错误事件，避免“Job SUCCESS 但数据资产缺少 Capture”；最终失败不会再被静默吞掉。
- Family Merge 在 UI/Repository 过滤之外增加 Service 级实时质量门禁，任何非活动或当前 `merge_ready=False` 的 Capture 均无法进入合表。

## v6.6：Authoritative Anchor-Driven Capture

- 只有已认证的 Statement Anchor 才能生成 Capture Plan；未选口径保持机器证据但不会产生表、作业或抓取。
- Note Detail 必须先经由 `Statement Child → note_reference → CERTIFIED_NOTE_TARGET`；候选页不再自动放行。
- 新增 Section → Ordinal → Semantic 的附注候选解析器，支持 `10/十/（十）/(10)/10、/10.` 与跨行标题。
- 认证后的 Note Target 以独立审计记录保存；计划项只消费认证目标。
- v6.6 为独立 release，继续共享 DATA_HOME；迁移仅新增 `certified_note_targets` 与 `research_batches` 相关表。
- 审核中心以研究任务为入口，按“来源 PDF → 已选主表 Anchor → 全部已认证子表”展示；主表页和附注页预览均带可用 bbox 高亮。
- 研究任务可归档至回收站并恢复：计划恢复其认证状态，已完成 Capture 同步进入/离开资产回收站。
- 合表候选以 SQLite 中活动 Capture 为唯一来源；未注册的旧目录不再伪装成“待认证”抓取，可在合表页执行安全索引对账。
- 支持 `IMPLICIT_TOTAL`：保留 PDF 空标签数值行，以 `row_item_raw=NULL` 和可审计的 `SUM_CHILDREN` 推导链表示隐式总额。

## v6.5.1：多 PDF 独立 Anchor 与批量计划

选择多份年报后，主报表 Anchor 可多选认证。系统会对每份 PDF 分别保存 Anchor Decision，并各自生成 `1 个主报表构成 + N 个附注明细` 的 Capture Plan；批量操作不再将不同年度或不同来源 PDF 合并成一条锚点。修复了认证计划时复用 `v65_plan` widget key 导致的 Streamlit 状态异常。

## v6.5：Statement-Anchored Table Family

主路径为：选择 PDF → 输入研究目标 → 发现主报表 occurrence → 锚点/成员审核 → 附注页审核 → 认证 Capture Plan → 一键抓取。认证计划会保存 1 个主报表构成锚点及 N 个附注明细，之后不会再要求重复选择目标表或表族。

代码发布在 `releases/v6.6`；`releases/v6.5.1` 与 `releases/v6.4` 均为冻结快照。各 release 共享 DATA_HOME，迁移仅追加 SQLite 结构。详细设计见 [docs/architecture_v6_6.md](docs/architecture_v6_6.md) 与 [docs/release_policy.md](docs/release_policy.md)。

## v6.4：通用发现、人工审核与认证知识

`display_name` 不再依赖预设：输入“金融投资”“保险合同负债”“投资收益”等任意研究目标后，可先运行通用的主表→附注发现并进入预览。预设只提供候选、历史变体和优先报表等可选知识。

工作流为：`Machine Discovery → Discovery Review → Certified Discovery → Fast Path / Training Examples`。机器发现不可变；审核动作、理由和覆盖结果独立记录。认证结果只在同公司、同 filing type、同 statement type 下作为下一年候选，仍需重新验证，绝不复用固定页码或附注号。

新增“发现结果审核”和“发现规则与学习库”页面；训练样本保留 ACCEPTED、REJECTED、OVERRIDDEN、UNRESOLVED。分层知识模型为 Company → Filing Type → Statement Type → Table Family → Member Table，并按该层级回退。ML/LLM 只排序候选和提供置信度，不能生成或修改财务金额。

公司选择器已按规范化公司名去重，显示公司聚合标签而不是 asset hash。版本由 `version.py` 单一来源提供，BAT、launcher 与页面应统一显示当前 release。

## v6.3：主表导航、表族合并与研究输出合同

v6.3 以本目录中的 v6.2 工程为唯一基线；保留受控并发、多 PDF、表族、持久化 Job、结构解析、历史模板与本地 LLM 配置。本版不引入 FastAPI/React 全量迁移，只把数据合同固化为后续 API 可直接承接的形式。

### 新工作流

1. **PDF Selection Workspace v2**：整表批量工作台提供 `全部 / 按公司 / 按年份 / 手工选择`，以及公司、年份、文件名包含、排除关键词、全选当前结果与清空选择。筛选不会清除已选 PDF。
2. **Statement-Guided Note Navigation**：先建立轻量文本索引，再识别三大报表和附注引用；优先沿“主表科目 → 附注编号 → 细表”定位，无法确认时回退 Direct Search，并保留 `REVIEW_REQUIRED` 边界。
3. **Table Family Merge**：正式区分 `table_family`、`member_table`、`source_table_title`、`note_reference`。行轴按 member table + row path 对齐/并集，列轴按 `data_year/scope/restated/period_type/unit` 对齐/并集。
4. **Research Output Contract v2**：Research Long 保留 `company/report_year/data_year/.../value`；Research Wide 默认不显示 `canonical_key` 与 `order_source`，并使用 `column_dimensions` 映射保持 CSV 可解析。
5. **Table Notes Evidence**：表底注释及脚注以独立、不可变证据记录保存；Excel 交付建议分为 `Data`、`Table_Notes`、`Row_Notes`、`Source_Index`，不把长备注重复写入数值表。

### 核心身份合同

```text
来源：company, report_year, source_pdf, capture_id
观测：data_year, period_type, scope, restated, unit/currency
行：table_family, member_table, row_path, item, row_type
值：value
```

`report_year` 是来源年报年份，`data_year` 是数字实际对应的会计年度；两者绝不互相覆盖。相同 `data_year` 在较晚年报中重述时可以共存。

### 主表—附注对账

对账只产生状态和差异，不修改机器原值：`PASS_EXACT`、`PASS_WITH_ROUNDING`、`WARNING_STATEMENT_NOTE_MISMATCH`、`NOT_TESTABLE`。容差由展示单位和显示精度决定。

## v6.2：批量抓取与财务结构理解

- 多 PDF：一次选择多份 PDF；每个 PDF × 目标表创建独立、持久化 Job；默认 3 个 Worker，最多 8 个。
- 表族：内置“投资相关收益”（投资净收益 / 投资收益 / 利息收入），支持自定义多表、角色和 schema variant 判定。
- 失败隔离：单个 PDF 或表未匹配不会中断同批任务；`FAILED` 可安全创建新的 retry Job，原 Job 保留审计记录。
- 结构层：新增可审核的 `row_path`、父行、置信度与证据；重复行名只要父路径不同即不会静默冲突。
- 核对层：小计/会计等式核对采用金额单位和显示四舍五入容差，输出 `PASS` / `PASS_WITH_ROUNDING` / `WARNING`，不会篡改来源值。
- 合表层：维度缺失导致的多列歧义标记为 `REVIEW_REQUIRED_DIMENSION_AMBIGUITY`（警告）；完全相同经济键的不同数值仍是阻断性 `VALUE_CONFLICT`。
- 模板层：保存历史结构模板并作相似度检索；`StructurePredictor` 是后续 embedding/LightGBM 模型的稳定替换接口。
- LLM：可选本地 `config/llm_config.yaml`；密钥不写入 SQLite、审计文件、版本控制或项目包。

### 审计边界

`table_capture_result.json` 与既有 machine evidence 不会被 v6.2 结构层回写。行路径、结构置信度、结构审计是从导出的长表确定性派生的附加字段；人工复核仍是任何低置信结论进入研究层之前的唯一授权路径。

PDF-first financial / insurance statement extraction workbench.

v6.1 is an **architecture foundation release**. It keeps the existing audited PDF parsing, table capture, review, lifecycle, and merge behavior, while separating metadata/business operations from the Streamlit UI.

## What changed in v6.1

- Added `DATA_HOME/metadata.db` as a rebuildable **SQLite Metadata Registry**.
- Added Repository Layer: `repositories/`.
- Added Service Layer: `services/`.
- Added `backend_context.py` dependency container shared by UI, CLI, tests, and future FastAPI.
- Added persistent Job Registry schema and `JobService`.
- Added headless `service_cli.py`.
- Data Asset Management now queries SQLite rather than rescanning all Capture/Merge folders on every interaction.
- Capture list supports SQL filtering + pagination.
- Batch main view separates normal batches from fully trashed batches.
- Recycle Bin has a dedicated **Batch Trash** view.
- Historical README/CHANGELOG files moved to `docs/history/`; project root now keeps only current entry documents.

## Data contract

SQLite is the **control plane**, not the financial-data store.

```text
DATA_HOME/
├─ metadata.db              # metadata / lifecycle / dependencies / jobs
├─ uploads/                 # source PDF evidence
├─ table_captures/          # immutable machine evidence + official outputs
├─ table_merges/            # merge projects
├─ batch_runs/
├─ reviews/
└─ ...
```

Large or auditable data stays in PDF / JSON / CSV / Parquet. `metadata.db` can be rebuilt from `DATA_HOME`.

## Launch

Recommended:

```bat
run_gui.bat
```

The v6.1 single-instance launcher safely manages the Streamlit process without killing unrelated Python processes.

Manual launch:

```powershell
python -m pip install -r requirements.txt
python -m streamlit run app.py
```

## Headless service API

The backend can be used without Streamlit:

```powershell
python service_cli.py registry-stats
python service_cli.py sync-registry
python service_cli.py list-captures --limit 50
python service_cli.py list-batches
```

Programmatic entry point:

```python
from data_home import resolve_data_home, ensure_data_home
from backend_context import build_backend_services

paths = ensure_data_home(data_home, bundled_rules)
backend = build_backend_services(paths)
backend.registry_service.bootstrap_if_needed()

captures = backend.capture_service.list(limit=100)
```

Headless service façades exist for:

- Capture creation / listing / registration
- Review adjudication
- Asset lifecycle operations
- Batch lifecycle operations
- Merge creation / refresh / lifecycle
- PDF metadata lookup
- Persistent Job Registry

## Migration from v6.0 / v6.0.1

No manual data migration is required.

On first v6.1 launch:

1. `metadata.db` is created.
2. Existing PDFs, Captures, Batches, and Merges are scanned once.
3. Metadata is indexed into SQLite.
4. Existing machine evidence is not rewritten.

A registry full-sync can be run from **系统与迁移** or:

```powershell
python service_cli.py sync-registry
```

## Regression gates

Run the full v6.4 chain:

```bat
run_regression_v64.bat
```

This executes v5.9, v6.0, v6.0.1, and v6.1 regression suites.

Current v6.1 architecture gates include:

```text
SQLITE_REGISTRY_BOOTSTRAP_PASS
HEADLESS_SERVICE_LAYER_PASS
SQL_FILTER_PAGINATION_PASS
BATCH_AGGREGATE_STATUS_PASS
SQL_DEPENDENCY_INDEX_PASS
SERVICE_INVALIDATE_DUAL_WRITE_PASS
SERVICE_REACTIVATE_DEPENDENCY_PASS
BATCH_ACTIVE_TRASH_SEPARATION_PASS
SERVICE_TRASH_RESTORE_PASS
PERSISTENT_JOB_REGISTRY_PASS
REGISTRY_REBUILD_FROM_DATA_HOME_PASS
HEADLESS_CAPTURE_REVIEW_MERGE_SERVICE_PASS
ALL_V61_BACKEND_ARCHITECTURE_TESTS_PASS
```

## Documentation

Current documentation: `docs/current/`

Historical version documentation: `docs/history/`

See also:

- `docs/current/ARCHITECTURE_V6_1.md`
- `docs/current/DATA_ASSET_MANAGEMENT.md`
- `docs/current/MIGRATION_V6_1.md`
- `docs/current/REGRESSION_CONTRACT.md`
