# AXA_research Architecture

## Architecture objective

The system separates source evidence, machine interpretation, human adjudication, certification, canonical data, research aggregation, and user presentation.

No downstream layer may silently repair or reinterpret upstream facts.

## Formal data flow

```text
PDF Registry
→ Filing Identity
→ Document Context
→ Main Statement Discovery
→ Statement Family Resolution
→ Required Member Contract
→ Child Table Candidate Discovery
→ CertifiedChildTableLink
→ Stage B Execution Session (persisted Capture scope)
→ CaptureRequest
→ Capture Orchestrator
→ Persistent Job
→ Capture Version
→ Capture Inspection
→ Machine Evidence
→ Human Adjudication
→ CaptureDecisionReducer
→ Canonical Long
→ Merge Eligibility
→ Company Merge
→ Cross-company Research Merge
→ User Research Workbook Exporter
```

## Module ownership

### Filing Registry

Owns PDF identity, SHA256, company/year/report type, page count, and modality metadata.

Must not resolve amounts, members, or Capture rows.

### Discovery Service

Owns bounded statement and child-table candidates, evidence, and scores.

Every child-table candidate page must be strictly greater than the authoritative main-statement amount-source page. The same `candidate_page <= main_statement_page` gate applies before Tier 1, Tier 2, and Tier 3 retrieval.

Logical inventory groups repeated current/comparative period blocks on one page into one table when they share the same disclosure purpose and amount-axis topology. A period reset is evidence, but is not sufficient by itself to create another logical table.

垂直堆叠的本期/比较期区块在 Capture 中保留独立的逻辑 `block_id` 与列 ordinal；若它们共享同一页、同一披露边界和金额轴，则必须同时登记一个覆盖整段物理 bbox 的 `physical_segment_id`。逻辑块通过该字段回指同一物理段，Scope/manifest 校验使用物理段，而列拓扑与子表 materialization 使用各自逻辑块，不能把两个身份混为一列。

Must not certify candidates, write amounts, or redefine Research Definition.

投资组合 Discovery 后必须生成同一个纯投影 `PortfolioTopologyExecutionPlan` 供离线调用方和
Streamlit 使用。五类拓扑显式声明 Direct/Note 必需来源与 Stage B 认证目标；UI 不得按
`statement_type` 自行推断路由。该计划不持久化业务结果，也不替代
`CertifiedChildTableLink`。Hybrid 同时包含 direct 物理 ROI 与 note 子表链接，任一必需
分支缺失时不得进入 Capture Plan。

`ChildCaptureExecutionService` 是 UI/离线共用的第二道拓扑门禁：它从持久化
`StatementOccurrence` 重新构造 plan，并使用同一批 `CertifiedChildTableLink` 校验全部
required target，不能信任 Streamlit session state。`DIRECT_COMPOUND_TABLE` 只提交一个
物理 Capture 请求，但认证证据保留全部 member/logical-block/classification-axis；既有
compound segmentation 再物化为两个独立逻辑 Capture，共享一个 physical asset lineage。

已认证矩形 ROI 的行归属由 Capture 解析与运行后治理共同调用同一个无状态合同：纵向使用
source bbox 的中心锚点，横向使用矩形相交。PDF 字形框可略微穿过认证上下边界，不能因此在
解析已纳入该行后又由治理以完整 bbox 包含规则否决。页面、标题、物理资产、分类与行页码
身份仍独立 fail-closed。该合同不负责生成 ROI，也不等同于物理底线识别。

### Conditional OCR Service

Owns OCR routing, rendering profile, cache, and token/line/bbox evidence.

Must not write certified amounts or bypass Capture.

Fast Index 的认证 profile 同时拥有 DPI、Tesseract PSM 与图像预处理版本；三者都必须进入
页级缓存身份。红章清理只能去除紧凑红色区域，不得抹除跨越页面宽度的彩色表头带。
投资组合 Direct Discovery 只有在 Native 标题、分类轴、单位和总额身份已经锁定、但数值层
不足时，才可对该候选页调用同一 Conditional OCR Service；Native 保留表身份，OCR 只补
数值/期间证据。由 OCR 词级 BBox 重建跨基线日期时必须满足同一视觉带和严格横向次序，
禁止对全文文本跨行拼接或根据报告年度推测缺失日期。

金融投资附注的候选页恢复若以 OCR 通过 Stage B 结构门禁，必须把该物理分段使用的
PDF-point 词级几何、合同版本和缓存审计冻结在 segment evidence 中。正式 Whole-table
Capture 只重放这份已认证几何，并与 Native 标签行组合；不得重新 OCR，也不得退回缺字的
Native 数值行。Stage B 与 Capture 的物理段下界共同采用“最后一个有认证数值 lane 的表格
行”语义：合计后的说明文字即使含日期或数字，也不能扩展主表 BBox。

### Statement Family Resolver

Owns explicit-parent/implicit-member resolution, member classification, presentation regime, and expected-vs-discovered comparison.

Must not define expected from discovered count or fabricate parents.

### Certified Child Link Service

Owns persistent certified primary/supplementary table targets.

Must not parse full table values or manufacture links from the Manifest alone.

Guided Stage B materialization is self-selecting against this certified inventory. A
`PRIMARY_ONLY` request carries `selected_logical_table_ids=[]`; a
`SELECTED_NOTE_TABLES` request carries only its own certified `logical_table_id`.
Filing-level union validation covers only the supplementary logical tables explicitly
selected by the user; it must not copy that union back into each request or treat the
primary table as a supplementary selection.

### Capture Orchestrator / Capture Library

Owns ROI, boundary, headers, periods, units, rows, multi-block structure, and immutable source evidence.

Must not reinterpret Research Definition or create research Merge outputs.

v6.13 行身份由 Spatial Capture 单一写入者负责。pending 标签解析同时决定组标题、续行和
同级无值明细，并创建稳定 `source_row_id`；数值父项推断在同一层写入 `parent_row_id` 和
闭合证据。Direct 原生恢复只能作为只读审计，不得覆盖已认证层级。Canonical/Merge 不再
重新按 `parent_section`、`row_level` 或行顺序推断父子关系。

The Stage B scope travels only through `ChildCaptureExecutionService → GuidedCaptureService → CaptureRequest → CaptureOrchestrator → CaptureService`. The request owns the user's policy; `capture_scope_limited`, policy truncation, and excluded-segment evidence must be derived from machine boundary/segment evidence, never inferred by the UI alone. `PRIMARY_WITH_CONTINUATIONS` includes only the primary table continuation chain; `ALL_NOTE_TABLES` also includes supplementary tables and their own continuation chains.

Stage B 的同一 plan/scope 首次提交保持幂等：已提交且仍在执行时不得重复建批。
当该执行已进入终态时，UI 只能通过明确的“重新抓取”操作建立新的
execution-attempt session、Research Batch 和 source batches；新尝试复用认证 plan/scope
快照，但不覆盖历史 Capture lineage。预览和 rerun 仍然无业务写入。

Each immutable CaptureBundle version is identified by its note-container identity,
certified logical-table identity, normalized scope signature, originating
CaptureRequest identity, and root Capture identity. Replaying the same bundle version
replaces its child rows in one transaction and rebuilds a unique, continuous
`child_order=0..n-1`; a partial old/new child set must never become visible.

LogicalAsset identity includes the certified `logical_table_id` so independent tables
inside one note container cannot collide. Scope policy is deliberately excluded from
LogicalAsset identity: policy changes produce distinct bundle/Capture versions while
preserving the stable logical asset.

### Review Service

Owns structured review issues and human decisions.

Must not mutate machine evidence, fabricate human confirmation, or recompute state during rendering.

### CaptureDecisionReducer

Is the only owner of final quality, blocking, review, certification-readiness, and merge-eligibility state.

### Canonical Materializer

Owns normalized observations, stable keys, periods, units, raw/canonical labels, and source lineage.

Must not reparse PDFs, fill missing with zero, or collapse unsafe regimes.

Canonical 同一来源内的物理行追溯使用
`physical_table_id + logical_block_id + source_row_id`；这不是跨年度经济身份。
跨年度 Canonical/Merge 使用由认证父子图派生的 `semantic_row_key`：
`member_table + classification_axis + normalized_item + semantic_parent_path + occurrence`，
数值身份再追加 `period_identity + measure + scope + restated`。`row_path` 仅是展示投影，
不得作为独立主键。

金融投资 V6 在 Canonical 中同时保留来源列报身份、制度内分析身份和显式桥接成员关系。
附注、期间和金额在 Stage A 已按 `source_row_id` 原子绑定；Canonical 不得用
`member_table` 或桥接组重新关联物理行。`analysis_bridge_groups`、成员合同版本及认证拆分
字段必须穿过 Canonical，供正式 Merge owner 投影，不能由导出端补写。

### Merge Service

Owns company/cross-company aggregation, conflict detection, comparability, and source membership.

Must not parse PDFs, perform OCR, silently overwrite conflicts, or force legacy/new mappings.

金融投资跨准则研究视图是正式 Merge 的纯投影。每次 Merge 同时保存原始口径与显式桥接，
桥接身份使用 bridge group、分类轴、规范项目、认证父路径、occurrence 和完整 observation
维度。相同桥接身份/期间存在多个有效来源时禁止求和；需要拆分的旧准则成员缺少匹配认证时
仅阻断桥接值，不影响原始口径来源事实。两类视图及审计写入同一个 Merge manifest/XLSX，
不得建立独立 bridge Merge 管线。

合表 UI 的来源筛选只投影 Registry 已判定为 `ACTIVE + merge_ready` 的 Capture。公司、
`document_year`、Logical Asset `member_table_id` 与 Capture 的 `research_batch_ids` 只用于
缩小候选视图；物理子块身份须折叠到所属 member table，旧记录缺少逻辑身份时才兼容回退
`table_query`。研究批次按多值成员关系匹配。筛选不得重算资格或改写业务状态；切换筛选
必须保留用户已经显式选择且仍有效的 Capture ID。

当请求中的 Capture 是 `CaptureBundle` 根节点时，Merge Service 必须先从 registry 按
`child_order` 展开同 bundle 的全部 `CAPTURED` 资产，再交给 Canonical Materializer；根
Capture 只是调用入口，不代表只合并根资产。bundle/child 状态、认证逻辑表、PDF 身份和
`table_block_id` 任一漂移都必须 fail-closed。所有 Capture 资产保留在 source lineage；仅
允许按持久化证据在 row/cell 层排除明确的非 SOURCE 派生观察，并将排除键和理由写入
Merge manifest，禁止通过丢弃整个 child Capture 来修正数据。

每个 bundle 必须严格存在且只存在一个 `child_order=0` 根，调用方请求的 root 必须与其
一致；重复根、缺根、非连续顺序或同一 child 多次出现均在 Canonical 物化前 fail-closed。

跨年度/跨 Capture 的 Canonical 行身份使用稳定 `semantic_row_key`，不使用
Capture-local `source_row_id`、`container_id/table_block_id/block_order/block_role/`
`block_terminal_type`。已解析的 `classification_axis` 参与身份；`UNRESOLVED` 轴继续按
`table_block_id` 隔离。物理块字段和 `source_row_id` 只作为 lineage 保留，不得使同一
member、同一语义轴、同一认证父链的年度值拆行。UI 与 Merge 必须调用同一个认证父子图
投影，不得各自从旧 `parent_section/row_level/row_type` 重建层级。

### UserResearchWorkbookExporter

Owns readable wide workbooks, Chinese display names, previews, source index, and explanations.

Must not rerun discovery, mutate Merge, or certify data.

## Compatibility adapters

Compatibility or legacy entry points may translate parameters, invoke formal services, and display the same persistent results.

They may not contain independent filtering, boundary, member mapping, status, Capture, certification, Canonical, or Merge logic.

## Change impact requirements

A change to an owner module requires review of upstream/downstream contracts, affected incidents, Golden patterns, Canaries, database compatibility, and user-facing lineage.

## Current certified acceptance boundary (2026-08-05)

- Certified scope 当前无 Stage B、Review 或 Merge 阻断。fresh `PRIMARY_ONLY` 正式 Merge
  从 49 个 bundle roots 展开 90 个 Capture assets，current Golden v3 为 883/883 cells。
- fresh supplementary 正式 Merge 从 14 个 roots 展开 18 个 assets，Golden 为 322/322
  cells，冲突为 0。
- 上述结果不等于 12 份年报的 `ALL_NOTE_TABLES` 全覆盖：当前仅新华 2024 为 `CLEAR`，
  其余 11/12 仍为 `PENDING`；认证 corpus 中 true `CONTINUATION_SEGMENT` 数量为 0。
- Streamlit 用户路径尚未执行，状态为 `NOT_RUN`；离线认证结果不得替代 UI 验收。

## Repository artifact placement

- 项目根目录只保存 `PACKAGE_MANIFEST.json` 声明的入口、顶层合同、版本状态与当前任务/状态审计文件。
- Agent 运行日志、完成卡、终端摘要和 QA 结果必须写入 `output/_agent_runs/<task_name>/`。
- OCR、页面渲染和图像预处理诊断只能写入 `scratch/diagnostics/<diagnostic_name>/`，不得放入根目录或未经审定写入 Golden evidence。
- 已被规范副本替代的协议、安装报告和历史快照写入 `docs/archive/<topic>/`，并用 README 指向当前规范文件。
- 孤立、空白或身份不明但暂不应删除的文件写入 `scratch/root_cleanup_<date>/` 隔离区。

## Dual Registry acceptance harness (v6.14)

`RegistryAcceptanceHarness` 是正式服务图结果的只读验收器，不是第二条 Discovery、OCR、
Capture、Canonical 或 Merge 管线。`RegistryProfile` 只表达投资组合五拓扑与金融投资
主表成员/CertifiedChildTableLink 的前半段差异；Whole-table Capture 后共用正式链路。

Offline Lane 与 FakeStreamlit UI Lane 使用各自隔离的 metadata snapshot，并只读引用当前
canonical PDF。前置认证或 Capture 不完整时 Lane 必须保持 `BLOCKED/NOT_RUN`；禁止复制
生产成功状态、伪造人工认证或用静态 UI 测试宣称 parity。

Corpus Preflight 在读取 Registry snapshot 前调用 Golden 跨来源一致性门禁，防止内部合法
但仍指向旧 PDF 页码的 sidecar 进入绿色状态。正式 Stage B 执行必须以 `assign_global()` 为
唯一全局决策入口；任务脚本只能编排 owner services，不能在脚本内建立平行分配状态。

Discovery occurrence 采用 append-only 版本身份。Guided UI 恢复认证资产时，先按当前
Anchor ID 查询；若重放产生新 ID，只能通过正式认证审计支持的完整物理身份恢复旧
`CertifiedChildTableLink`。Capture Plan 的严格身份同时包含已认证 target 集合，因此链接
清单增加或减少会生成新 plan，而不会复用旧 items。机器几何门禁仍作为审计证据；同一物理
Anchor 已有正式认证时，其失败只影响 UI 提示等级，不撤销或伪造认证决定。

金融投资 V6 验收不改写旧认证快照，而是将同一 filing 的只读 Evidence V2 Shadow 作为
`DiscoveryAcceptance` 的附加证据。该证据必须证明 `source_row_id` 唯一、当前期必需成员
occurrence 唯一、附注/期间/金额未跨物理行绑定且 `SHADOW_WORSE=0`。缺少该证据返回
`NOT_RUN_FINANCIAL_V6_EVIDENCE_REQUIRED`，不能以旧 Anchor PASS 代替。

金融投资排名和 Guided UI 只消费已物化的 Evidence V2 occurrence revision。Native V2 与
OCR recovery 都以 append-only 修订写入隔离/生产对应的 Discovery Registry，再进入排名；
不得在内存中展示 V2 后让认证入口重新加载原始 V1 occurrence。内容哈希同时绑定 evidence
和 child rows，以确保同一物理页的证据修订可重复、可追溯且不会覆盖原始机器发现。

`MergeAcceptance` 对金融投资读取正式 Merge run path，并同时验证原始口径 long、桥接 long、
桥接 wide 与桥接 audit。零行桥接成员也必须输出稳定 schema；桥接阻断行只有在值为空且原因
进入 audit 时才算正确 fail-closed。验收 run 必须显式传入本轮 formal merge ID 清单，禁止把
同一隔离库中的旧 Merge 混入本轮结果。`UiParityAcceptance` 还须比较列报成员、列报制度、
V6 合同版本和 bridge memberships；仅比较数值与旧 semantic key 不足以通过。

## Portfolio Golden hierarchy and comparison boundary (v6.13)

投资组合 source Golden 可以用显式 `parent_row_order` 描述已独立审阅的父行；值为 `null`
表示从该行开始回到物理表 ROOT。该字段只供 sidecar builder 消费，不是 runtime Capture
父子边的第二写者。builder 对同级 GROUP、TOTAL 和显式 ROOT boundary 必须关闭此前的
active group，且 strict validator 必须检查父行与子行属于同一物理表、member/axis，父行
类型为 GROUP，`semantic_parent_path` 与 `parent_golden_row_id` 一致。

Golden comparator 以稳定业务身份比较正式语义；`raw_label` 只保留 lineage audit，不作为
阻断字段。稳定键无法直接连接但标签与四个期间值唯一对应时，只输出一条
`semantic_identity` 差异，不能把同一个父路径/occurrence 问题放大成多个数值差异。
