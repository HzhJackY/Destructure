# AXA_research Data Contracts

## Observation layers

### Source Observation

A fact directly supported by the PDF.

Required identity:

- `pdf_sha256`
- `page_number`
- `bbox`
- `raw_table_title`
- `raw_item`
- `raw_period_label`
- `raw_unit`
- `raw_value`
- `capture_id`
- `capture_version_id`

### Derived Observation

A deterministic result created from certified source observations.

It must identify derivation contract, source observation IDs, derivation version, and blocking/non-blocking status.

### Human Adjudication

Separate from machine evidence.

Required: reviewer, timestamp, decision, reason, before, after, and evidence references.

## Machine Discovery identity and replay contract

`machine_discoveries` 是不可覆盖的机器证据快照。稳定身份由 PDF、公司/报告年度、
声明类型、表族/成员、源表标题和主表页组成；相同稳定身份的重放若所有持久化证据相同，
必须幂等返回原记录。置信度、候选页集合、证据 JSON、bbox、状态和候选聚类等机器推导
字段属于可版本化证据，不得覆盖旧记录；它们变化时追加同一稳定候选的确定性
`<base_discovery_id>__R<sha256>` 版本，并将新版本 ID 传给后续 occurrence/审核对象。

稳定身份字段发生冲突仍必须以 `MACHINE_DISCOVERY_IDENTITY_CONFLICT` fail-closed；证据版本
冲突仍必须以 `MACHINE_DISCOVERY_EVIDENCE_REVISION_CONFLICT` fail-closed。任何重放路径不得
通过忽略差异字段、更新旧行或生成第二条 Capture 管线来消除冲突。

## Amount contract

A financial amount is valid only when linked to a certified row, certified data column, period header, unit, source geometry, and Capture Version.

The following are not amounts:

- note references;
- row numbers;
- section numbers;
- page numbers;
- OCR confidence;
- table indexes.

## Financial-investment Stage-A Hybrid evidence contract

`StatementAnchorEvidenceV2` 可将 Native PDF 身份与 Fast Index OCR 词级几何组合，
但组合只在 `HYBRID_NATIVE_IDENTITY_OCR_VALUES` 合同下成立：

- Native 固定拥有 scope、标题、单位、父项、`member_table`、`raw_label`、`source_row_id`
  和标签 BBox；OCR 不得改写这些字段。
- OCR 只能补充已认证期间 lane 的金额/合法占位、期间 BBox 与行绑定 BBox。每个 OCR
  BBox 必须有坐标空间、渲染尺寸和到 PDF points 的转换证据。
- Native/OCR 行映射必须一对一、行序单调，并由纵向重叠、附注审计与数值 lane 共同认证。
  OCR 标签是 lineage audit，不是成员身份来源。
- OCR 附注号可支持行对齐，但 Native 未认证附注时仍为
  `NOTE_REFERENCE_UNRESOLVED`，不得创建正式 Child Link。
- 缺坐标元数据、行映射歧义、期间/金额/附注冲突均 fail-closed；OCR 不能直接成为
  Capture 或认证金额来源。

## Period contract

Distinguish report year, data year, current period, comparative period, restated period, and scope.

Do not silently mix `CURRENT_REPORT_CURRENT_PERIOD` with `LATEST_CERTIFIED_RESTATEMENT`.

每个数值 observation 必须保留 `source_period_label`、`period_label`、可空的
`period_year/month/day`、`period_precision`、`period_date`、`period_identity` 和
`period_kind`。正式期间身份为 `period_identity`：完整日期使用 `DATE:YYYY-MM-DD`，月精度
使用 `MONTH:YYYY-MM`，年精度使用 `YEAR:YYYY`。`report_year` 仅表示 Filing 所属年份，
`data_year` 仅为兼容筛选字段，不得参与 Canonical 唯一身份或冲突判定。

只有原文年份时，月、日必须为空，不得推断为 12 月 31 日；完整日期必须通过日历校验。
`年末/年初` 可确定性派生为 12 月 31 日/1 月 1 日并保存推导证据。季度和半年报的相对期间
只有取得 Filing Registry 认证的报告期末日后才能物化为完整日期，否则以
`PERIOD_DATE_UNRESOLVED` 阻断。历史 V3 Capture 可从原有完整 `period_label` 只读派生 V4
字段，不得改写源资产。同一经济行同时出现 `YEAR:2023` 与 `DATE:2023-12-31` 时分别保留，
以非阻断 `PERIOD_PRECISION_MISMATCH` 审计提示，不自动视为等价。

## Unit contract

Units must be explicit and inherited only from certified table context.

Never infer unit solely from magnitude.

## Statement-family contract

Modes:

- `EXPLICIT_PARENT`
- `IMPLICIT_MEMBER_SET`
- `HYBRID`

Presentation regimes:

- `LEGACY_FINANCIAL_ASSET_CLASSIFICATION`
- `NEW_FINANCIAL_INSTRUMENT_CLASSIFICATION`
- `MIXED_TRANSITION_PRESENTATION`
- `UNKNOWN`

Comparability:

- `EXACT`
- `BRIDGED`
- `PARTIALLY_COMPARABLE`
- `NON_COMPARABLE`
- `UNRESOLVED`

Unsafe legacy/new collapsing is forbidden.

### 金融投资 V6 三层身份与桥接合同

- `presentation_member_id`：PDF 列报成员身份，保持新旧准则分离；
- `canonical_analysis_bucket`：同一列报制度内的 Canonical 分析身份；
- `analysis_bridge_groups`：显式跨准则研究关系，不是物理行键，也不覆盖来源值。

同页重复列报概念必须保留独立 `source_row_id`。附注、金额、期间、BBox 和制度裁决先在物理
行内完成；合法破折号的当前/历史含义必须结合整页期间矩阵，不能按字符单独决定。

正式桥接 observation identity 为：

```text
company + analysis_bridge_group + classification_axis
+ canonical_item + semantic_parent_path + semantic_occurrence
+ report_year + period_identity + scope + measure + unit + restated
```

`classification_axis=UNRESOLVED` 时继续按物理 block 隔离。同一 identity/期间出现多个有效
来源时写 `BRIDGE_AMBIGUOUS_SOURCE_SET` 并清空桥接值，禁止求和。`DISAGGREGATION_REQUIRED`
只有 `bridge_certification_status=CERTIFIED_DISAGGREGATION` 且规则 ID 匹配时可放行。
原始口径 Canonical/Merge 始终保留，桥接失败不得删除或改写来源 observation。

正式 Merge 必须固定生成四个可机器读取的金融投资产物：

- `financial_investment_original_long.csv`
- `financial_investment_standards_bridge_long.csv`
- `financial_investment_standards_bridge_wide.csv`
- `financial_investment_standards_bridge_audit.csv`

即使某个来源成员没有任何 `analysis_bridge_groups`，bridge long/wide 仍必须保留 V1 列头；
“0 行”是合法业务结果，“无 schema 的空文件”不是合法交付。该成员保留在原始口径视图，
审计写 `NO_STANDARDS_BRIDGE`，不得制造桥接值。

## Capture contract

### 投资组合拓扑执行计划

`PortfolioTopologyExecutionPlan` 是 Discovery 证据到 Stage A/B 的只读路由合同。认证目标
类型只有 `DIRECT_PHYSICAL_TABLE` 与 `NOTE_CHILD_TABLE`；两者最终均须产生既有的
`CertifiedChildTableLink` 才可进入 Capture Plan。Direct 目标以物理资产/page/bbox 为门禁，
Note 目标以 Anchor/附注引用/子表链接为门禁。Hybrid 要求两类必需目标全部认证，并执行
`DIRECT_TOTAL_NOTE_COMPONENTS_NO_DOUBLE_COUNT`；缺失不得降级或从组件合成总额。

服务层适配 certified links 时必须重新读取持久化 occurrence 并运行同一 topology
readiness；缺 occurrence、拓扑冲突或缺 required target 均 fail-closed。复合直接表的一条
`DIRECT_PORTFOLIO_WHOLE_TABLE` link 还必须持久化 `member_table_ids`、
`logical_block_ids`、`classification_axes`、`conditional_logical_members` 和 period labels。
它对应一个物理请求而不是一个逻辑块；Capture 后按
`CLASSIFICATION_AXIS_TRANSITION` 物化多个逻辑子资产。条件成员
`portfolio_summary / PORTFOLIO_SUMMARY` 仅在首个已认证轴标题之前存在有效数值源行时物化，
不增加物理认证目标、不计入 required logical-block 数量，也不建立“期间总额必须存在”门禁。

A required whole-table Capture preserves title, pages, bbox/region, header topology, leaf columns, current/comparative periods, unit, all required rows, row order, hierarchy, multiple blocks, multiple totals, and source evidence.

认证列上下文中的期间/measure 字符串不等于表头几何。任何 fallback 若使用已认证的列语义，
还必须在认证 ROI 内保存与各 leaf lane 对齐的真实表头文字 bbox，并以全部 leaf 表头的物理
下界确定数据起点。缺少该物理证据时必须 fail-closed；不得用合成的“金额/占比”等标签把
ROI 顶部伪装成完整表头，也不得把已识别的第二层表头物化为数据行。

`CERTIFIED_COLUMN_CONTEXT` 的 N-lane V2 leaf 证据仍是最低前提；新的 Direct 认证必须使用
V4 父期间列组扩展。V4 在 V3 几何证据上增加结构化期间身份；V3 仅只读兼容。
`period_signature`、`header_signature` 和 `amount_lane_signature` 的 leaf 数、bbox、顺序及
物理 lane 必须一致。每个 V4 `period_signature.column_groups` 必须保存
`period`、`period_anchor_bbox`、`period_group_bbox`、`period_header_row_band`、
`child_header_row_band`、`consumed_spans`、`column_group_id`、`confidence` 和 `evidence`。
列身份由 `period_identity + scope + restated + measure` 组成；
`period_kind=PERIOD_CHANGE` 可以使 `year=None`，但必须保留非空的 period label 和
measure。AUTO 仲裁仅在普通候选与认证 lane 数冲突时由完整认证拓扑接管；
缺失或不一致的 V2/V4 证据仍 fail-closed。

父期间与叶子 lane 同行时，期间传播采用同层左侧优先，右侧父期间仅作带惩罚回退；候选
接近时以 `PERIOD_PARENT_AMBIGUOUS` 进入审核。父期间位于上层时，不以左右距离作为主判据，
而按相邻期间、认证列边界、叶子中心聚类和表格边界建立连续 `period_group_bbox`，再将下层
leaf lane 按横向覆盖归属。父期间识别产生的 `consumed_spans` 必须先从叶子表头候选中删除，
再删除单位和结构前缀并识别 measure；`measure_label` 不得包含完整日期或 `年12`、`月31`、
`日` 等日期残片。残片未消除时以 `PERIOD_FRAGMENT_IN_MEASURE_LABEL` fail-closed，相关列不得
进入 Merge。

Direct 复合表的逻辑块标题归一必须使用已认证的 `classification_axis`，不得依赖
展示标题与物理轴标题字面相等。`DIRECT_PORTFOLIO_PHYSICAL_ROI` 边界只在 v2
认证/Runtime segment 一一对应、selected/physical manifest 一致、所有有效行属于
认证 ROI 且无 drift 时可判为硬边界。Merge 对 bundle 只接收 `child_order=0` 的根
Capture，并由既有 bundle graph 展开子块。

投资组合轴边界的 Discovery、分块与归一必须调用同一纯语义识别器。已知投资对象/会计
计量词与 `按…分类/分/划分/列示/构成` 结构可以解析为正式轴；语义不足的边界必须保留为
`UNRESOLVED` 块进入审核。独立无数值轴标题只删除自身；标题与数值行粘连时仅剥离已识别
前缀。Direct 逻辑归一前后的数值源行必须按 page、bbox 和源值身份一一守恒，丢失或重复以
`DIRECT_LOGICAL_AXIS_NUMERIC_ROW_CONSERVATION_FAILED` fail-closed。物理 `block_order`
保持来源顺序；bundle `child_order` 独立排序并继续以 `portfolio_by_category` 为根。

对于已经认证的矩形 ROI，运行时解析与 certified manifest 治理必须采用同一行归属语义：
候选行的纵向 bbox 中心位于 ROI 的 `y0..y1`，且候选 bbox 与 ROI 横向相交。不得由解析端按
相交纳入、再由治理端按完整字形 bbox 包含否决。该规则与行名、`TOTAL`/“合计”身份无关，
不会改变 Stage A 的 ROI 生成方法；无 bbox、页码/标题/物理身份漂移继续 fail-closed。

Every CaptureRequest has a typed `capture_scope_policy`: `PRIMARY_ONLY` (default), `PRIMARY_WITH_CONTINUATIONS`, or `ALL_NOTE_TABLES`. Optional `selected_block_roles` and `selected_block_ids` may narrow an already persisted manifest; block IDs must not be guessed before such a manifest exists.

Guided execution uses self-selection rather than filing-wide selection propagation:

- `PRIMARY_ONLY` requires `selected_logical_table_ids=[]`;
- each `SELECTED_NOTE_TABLES` request requires exactly its own certified
  `logical_table_id` in `selected_logical_table_ids`;
- filing-level union validation equals only the explicitly selected supplementary
  logical-table IDs and is never copied into an unrelated request.

The certified logical-table ID remains part of the request target even when the
selection list is empty; an empty `PRIMARY_ONLY` list therefore does not erase target
identity or weaken CertifiedChildTableLink validation.

Every physical table segment is classified as `PRIMARY_TABLE`, `CONTINUATION_SEGMENT`, `SUPPLEMENTARY_TABLE`, `PEER_TABLE`, or `UNRESOLVED`. A continuation records `continuation_of_segment_id`, page/bbox, confidence, and relation evidence. `UNRESOLVED` is never materialized automatically.

一个物理段可以承载多个垂直期间逻辑块。此时每个 `TableRow` 必须保留逻辑 `block_id`，并设置同一个 `physical_segment_id`；`stats.physical_table_segments` 只登记一次共享物理段，`stats.physical_segment_block_ids` 列出其逻辑块。逻辑块的 `source_column_ordinals` 仍按各自期间组解析，不能从共享物理段的首组列 ordinal 覆盖。Scope 选择和 certified manifest 只比较物理段，compound block 切分仍可依据逻辑 block。

Child-table discovery requires `candidate_page > authoritative_main_statement_page`; equality and earlier pages are rejected before every retrieval tier. Within an accepted note scope, repeated current/comparative period blocks on the same page remain one logical table when they share one disclosure purpose and amount-axis topology. Period reset alone does not create a second `SUPPLEMENTARY_TABLE`.

Golden 是独立验收与认证证据，不得反向生成或补写 runtime segment manifest。自动认证 `SUPPLEMENTARY_TABLE` 时，只能消费候选 inventory 中持久化的 page/bbox、period、header、amount-lane 四项 signature coverage；覆盖来源必须是有界 PDF 原生文字/坐标证据，并且 reset relation 明确。`consistency_audit=false` 本身不是补充表身份：任一覆盖缺失或 reset relation 未决时必须保持 `UNRESOLVED` / `REVIEW_REQUIRED`。

`PRIMARY_ONLY` may confirm a policy boundary only when machine evidence contains `capture_scope_limited=true`, `scope_boundary_decision=POLICY_TRUNCATION`, and a consistent `excluded_segment_manifest` with a confirmed continuation relation. Missing or contradictory evidence remains fail-closed. Supplementary tables retain independent header topology, Capture Version, reducer decision, and lineage; they are never horizontally appended to the primary table.

当 Merge 请求传入属于 `CaptureBundle` 的根 `capture_id` 时，执行层必须按 registry
`child_order` 展开该 bundle 的全部非 superseded child Capture。请求项必须是
`child_order=0` 的根，bundle 必须为 `READY`，每个 child 必须为 `CAPTURED`；重复 bundle、
重复 child、缺失资产或乱序 repository 返回均不得静默降级。展开时必须交叉核验
`capture_bundle_id`、认证 `logical_table_id`、family/member、PDF ID/SHA256 以及 graph、
metadata、result row 的 `table_block_id`。任一不一致必须 fail-closed。

CaptureBundle version identity 必须同时包含 note-container identity、认证
`logical_table_id`、规范化 scope signature、CaptureRequest identity 与 root Capture
identity。重放同一 version 时，旧 child 与新 child 必须在同一事务中完成替换，最终
`child_order` 唯一且连续为 `0..n-1`；事务失败必须保留原完整版本，不得留下混合 children。

LogicalAsset identity 必须包含认证 `logical_table_id`，但不得包含 scope policy/signature。
同一认证逻辑表在不同策略下仍投影为同一 LogicalAsset；不同策略、请求或 root 的不可变
执行事实由 CaptureBundle/Capture version identity 区分。

Capture 图中的每个资产和原始 observation 都是不可改写证据。只有
`DERIVED_OBSERVATION` 且状态为 `DERIVED_REJECTED_NON_BLOCKING` 或
`SUPPRESSED_BY_EXPLICIT_TOTAL` 的 observation 可以在 Canonical 输入前按
`(table_block_id, row_order, column_ordinal)` 排除；同时必须逐格核验
`normalized_item`、`value_raw` 与解析数值。不得以 asset-level exclusion 代替逐格排除，
所有应用的排除项及其 lineage 必须进入 Merge manifest。无 bundle、无排除证据的 legacy
Capture 保持兼容。

## v6.13 精简源行身份合同

Capture 的正式身份由单一 Spatial owner 生成：

```text
document_id
physical_table_id
logical_block_id + classification_axis + member_table_id
source_row_id + parent_row_id + row_role + row_origin
period_identity + measure + scope + restated + unit
```

`source_row_id` 必须由 PDF SHA、物理表、页码、block、原生 bbox 和 occurrence 生成，
不得依赖可变的 `row_order`。`parent_row_id` 只能指向同一物理表中已存在的
`source_row_id`；`hierarchy_evidence` 必须记录父子物理锚点、缩进和数值闭合证据。

`parent_section`、`row_level`、`row_type`、`extractor_row_role` 和 `row_path` 为迁移期
兼容投影，不得作为 Canonical/Merge 身份或再次裁决父子关系。`row_path` 只能由
`parent_row_id` 派生。`container_id`、`table_block_id`、`block_order` 和
`block_terminal_type` 只属于物理/逻辑块 lineage，不属于跨年度行主键。

Direct 原生组标题恢复必须在 Spatial pending 解析中完成。任何兼容恢复入口只能读取
原生证据并记录冲突，禁止清空或覆盖 `source_row_id`、`parent_row_id`、`row_role`。

`capture_to_long_df`、Canonical 和 Merge 只序列化或消费正式身份，不重新按标签、缩进或
行顺序推断父子关系。

### 物理来源身份与跨年度语义身份

`source_row_id` 是单份 PDF/物理 Capture 内的不可变来源锚点，允许用于来源追溯、同一
Capture 内重复行消歧和 `parent_row_id` 的目标引用；它包含 PDF/页码/bbox 证据，因此不同
年度即使是同一经济项目也通常不同。

`semantic_row_key` 是由认证父子图统一投影生成的跨年度身份：

```text
member_table + classification_axis + normalized_item
             + semantic_parent_path + occurrence
```

UI 行结构面板、`assign_semantic_row_keys`、Canonical/Merge 必须消费同一
`semantic_parent_path`。`parent_section`、`row_level`、`row_type` 和 `row_path` 只能作为
历史/展示兼容投影；新 Capture 不得用它们重新裁决父子关系。缺失或无法解析的
`parent_row_id` 会产生 `REVIEW_REQUIRED_SEMANTIC_ROW_IDENTITY`，并以来源 Capture
身份隔离，不能静默跨年度合并。

## Canonical identity contract

Canonical identity must not rely only on filtered line numbers.

Prefer PDF SHA, page, bbox, family, member, table, canonical row, classification axis, period, scope, and unit.

`raw_item`/`row_item_raw` 必须保留 PDF 原始文字及脚注号，不参与跨年度名称等价判断；
`normalized_item`/`row_item_normalized` 是 Canonical 行身份和 Merge source key 的名称部分。
完整“（附注…）”引用、行尾字母脚注和有边界的尾标“注”由共享正规化器处理。行尾独立
`(数字)`/`（数字）`、裸数字或“注+数字”必须由同一候选识别与正规化函数处理，且只有在
独立 span 的小字号/抬高基线证据，或同页表后“注：”区域存在对应编号时才能剥离；命中的
marker、page、bbox/span 和识别方法必须进入
`footnote_markers`/`footnote_evidence`。无证据候选必须保留原名称并标记
`ROW_LABEL_FOOTNOTE_UNRESOLVED`，不得自动跨年度合并。Direct 前缀拆分、原生父组拆分和
跨行标签拼接完成后均须调用同一正规化器。同一逻辑块内同名源行仍由 row path、父级和
occurrence 消歧，不得仅凭 normalized name 折叠。

独立文本父组由缩进子行和小计/合计闭合结构确认；小计闭合父组，最终总计不得错误继承
上一分类轴。证据不足时保留原身份或进入 review，不能按公司名补父级。

`container_id`、`table_block_id`、`block_order`、`block_role` 与
`block_terminal_type` 是 Capture-local 物理 lineage，不是跨年度 Canonical 行主键。
当 `classification_axis` 已解析时，跨 Capture 对齐必须使用 `semantic_row_key`；仅当轴为
`UNRESOLVED` 时，才保留 `table_block_id` 隔离以防止错误合并。机器宽表不得把物理块字段
作为 pivot 行索引；多来源物理身份应聚合展示，完整明细保留在 Canonical Long provenance。

## Merge contract

Merge may include only certified, merge-eligible observations with resolved period/unit identity.

It must not zero-fill, overwrite conflicts, collapse multiple totals, collapse classification axes, or hide incomparability.

Merge source count reports physical Capture assets after bundle expansion, not only caller-provided root IDs.
Manifest 必须同时报告 requested roots、discovered assets、raw graph numeric、row/cell exclusions
和 selected Canonical numeric，并保证 `raw = selected + excluded`；排除计数与实际应用计数
不一致时必须中止。

单位是 observation/列级属性。`TableCaptureResult.unit` 仅是向后兼容的默认金额单位，
不得代表整张表所有 observation。有效单位优先级为：单元格明确单位、认证列单位、
百分比类 measure 的 `%`、认证金额单位、页面/文档上下文、unresolved。金额 observation
写入认证金额单位和 `value_yuan`；占比与金额增减变动写入 `PERCENT/%` 且
`value_yuan=NULL`。无法解析的金额 observation 标记
`UNIT_UNRESOLVED_AMOUNT_OBSERVATION` 并禁止进入 Merge。单位冲突只在相同 Canonical
observation identity 和相同 `measure` 内判断；金额与占比不得组合为
`REVIEW_REQUIRED[%|百万元]`。同 measure 的不可换算来源单位冲突保留为
`REVIEW_REQUIRED_UNIT_CONFLICT`。

每个被请求 bundle 必须恰有一个 registry `child_order=0` root，且 requested root 必须与之
相同；其余 `child_order` 必须唯一、连续。缺根、双根、顺序空洞、重复 child 或跨 bundle
混入均为阻断性身份错误。

当前验收边界（2026-08-05）：fresh `PRIMARY_ONLY` 正式 Merge 为 49 roots → 90 assets，
Golden 883/883；fresh supplementary 正式 Merge 为 14 roots → 18 assets，Golden 322/322，
冲突 0。该证据仅证明 certified scope 无阻断。`ALL_NOTE_TABLES` 仅新华 2024 为 `CLEAR`，
其余 11/12 为 `PENDING`；认证 true `CONTINUATION_SEGMENT` 为 0，Streamlit 为 `NOT_RUN`。

## User workbook contract

The workbook is a projection of certified Merge data.

Do not expose by default:

- `row_type`
- `row_level`
- `canonical_key`
- `order_source`
- `source_identity_status`
- internal English member IDs
- 固定行级“单位”列

Preserve traceability through comments or a source-index sheet.

研究宽表固定列仅为“附注表名、项目”。每个数值列的单位由该列的
`currency_unit + measure` 多级表头表达；Canonical Long 与 Merge Long 继续逐 observation
保留 `unit`、`currency_unit`、`unit_source` 和 `unit_evidence`。期间表头使用
`period_label`：完整日期显示年月日，只有年精度时只显示年份。该导出合同版本为 4。

## Hierarchy and parent-child identity contract (v6.13)

1. **单一写者（Single-Writer）**：
   - 物理表内行父子边（`source_row_id -> parent_row_id`）的唯一写入阶段为 Spatial Capture 冻结前；
   - `parent_section`、`row_level`、`parent_row_order` 仅为辅助展示或审计证据字段，下游消费者（Long、Wide、UI、Merge、Semantic Graph）严禁利用这些旧字段补写或修改正式边；
   - 任何后处理流程（如 Direct 恢复函数）仅保留冲突审计（Audit-only），严禁注入新行或改写正式 ID。

2. **全端消费一致（Single Truth Graph）**：
   - UI、Canonical Long、Wide、Merge、Semantic Graph 统一消费 `project_certified_row_hierarchy()` 正式图投影；
   - 严禁宽表与导出端调用旧的启发式层级推断函数（如 `infer_row_structure`）重新推断父子关系。

3. **版本门禁与失败关闭（Fail-Closed Gating）**：
   - `producer_version >= v6.13` 的新 Capture 默认启用严格模式（`allow_legacy_compatibility=False`）；
   - 只有显式登记为 `identity_schema=LEGACY` 或存在迁移清单的历史不可变数据，才允许通过独立 Legacy Adapter 生成兼容投影；
   - 新 Capture 缺失 `source_row_id` 或元数据缺失时，统一标记为 `REVIEW_REQUIRED_SOURCE_IDENTITY`，阻断跨 Capture 合并；
   - 悬空父项（Dangling Parent）、自引用、环（Cycle）、跨物理表或非法跨 Block 边统一标记为 `REVIEW_REQUIRED`，保存 Capture 证据但阻断进入 Canonical/Merge。

4. **受控缺失语义（Controlled Missingness in Reconciliations）**：
   - 数值勾稽判定严格区分 `VALUE`、`PRINTED_DASH`、`NOT_APPLICABLE`、`EXTRACTION_MISSING`、`UNRESOLVED`；
   - 纯空白/空字符串不视作破折号；金额列漏值时严禁通过数值闭合。

## Golden Identity v1.2 sidecar contract

旧 v1.1 Golden 事实文件继续可读；严格双 Registry 验收要求同 filing 目录存在
`golden_identity_v1_2_<family>.yaml`。sidecar 必须包含：

- `filing_identity`：公司/法人主体/年度/口径/文件名/SHA-256/页数；
- `physical_tables`：物理页/打印页/标题/单位/表类型；
- `rows`：稳定 `golden_row_id`、`parent_golden_row_id`、row kind、逻辑 member/axis、
  规范标签、认证父路径、同名 occurrence 与 `period_values`；
- `period_values`：期间角色、期间身份、measure、unit 与独立审阅值。

Golden 行 ID 是业务验收身份，不等于 Capture-local `source_row_id`。验收先用 Golden 复合
身份连接，再检查 runtime 行 ID 唯一性、正式父子图、semantic key 与 lineage。缺 sidecar、
错误哈希、重复 ID、悬空/循环父项、未解析期间或跨 Registry 身份均 fail-closed。

内部 schema 通过不等于来源一致。Corpus Preflight 必须把 sidecar 与同目录 source Golden
及 `filing.yaml` 交叉校验：filing 身份字段必须逐项一致，current primary 物理表页码必须
等于 source Golden 的认证页码。矛盾时禁止继续读取生产认证资产。

Stage B 全局分配只有在 `HierarchicalChildTableDiscoveryService.assign_global()` 返回并由
owner repository 持久化后才成立。单独保存候选、局部 Certified Link 或脚本内 repair
清单，均不得计作全局分配完成；每个 AnchorChild 必须存在正式 assignment decision，自动
认证失败时也必须持久化 fail-closed 原因。

### 投资组合 Golden 父边来源与比较差异语义

`investment_portfolio_golden.yaml` 的 source row 可选 `parent_row_order`：整数表示已审阅
父行的 `row_order`，显式 `null` 表示 ROOT boundary；缺失字段继续采用兼容的 GROUP 状态
构建。此字段只控制 Golden Identity sidecar 的确定性生成，不得写回或覆盖 runtime
`parent_row_id`。同级 GROUP、TOTAL 与显式 ROOT boundary 均终止此前 active group。

严格 sidecar 校验必须同时满足：父 ID 存在且无环、父/子在同一 physical table、classification
axis、父类型为 GROUP、父路径与 `parent_golden_row_id` 一致。默认还要求同一 `member_table`；唯一
例外是明确的 `financial_investment_parent`，它只能作为同一主表、同一
`FINANCIAL_INVESTMENT_MEMBER_SET` 下多个金融投资成员的共享物理父行，不能跨页、跨轴或作为
任何其他 family 的父行。source Golden 显式声明的 `row_kind` / `parent_row_order` 必须与 sidecar
投影一致。

比较器的阻断事实为规范标签、row kind、父路径/occurrence 稳定身份及期间值。原始标签
`raw_label` 是 `LINEAGE_AUDIT_ONLY`：差异可记录但不得单独造成失败。无法直接按稳定键连接
的唯一行对只产生一条 `semantic_identity` 差异；不得把身份连接失败复制为四个期间数值
字段差异。无法唯一配对时才分别输出 `identity_presence` 缺失/多余事实并 fail-closed。
