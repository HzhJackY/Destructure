# ADR-008 — Stage B 抓取范围与同附注多子表分类

Status: ACCEPTED

## Context

保险年报同一附注内可能同时存在：主余额表、跨页续表、信用减值/公允价值等补充表，
以及下一同级附注。续表不一定出现“续表”标题；同一附注号和表名也不代表后续物理表
一定是主表续页。例如新华 2024「债权投资」在同页先披露两年余额表，随后以新的四阶段
表头披露信用损失准备变动表。

用户需要在 Stage B 执行前选择抓取范围，且当前版本默认允许只抓主片段。该选择改变
Capture 完整性、边界 warning 和 child materialization 语义，必须进入正式合同。

## Decision

### Capture scope policy

- `PRIMARY_ONLY`：仅抓主表首个物理片段；已识别续表作为用户选择的范围边界，产生
  非阻断 `CONTINUATION_EXCLUDED_BY_POLICY`，不得声称 PDF 中整张逻辑表自然结束。
- `PRIMARY_WITH_CONTINUATIONS`：抓取主表及所有已确认续表；任一 continuation relation
  未解决时，以 `CONTINUATION_UNRESOLVED` 阻断“完整续表”声明。
- `ALL_NOTE_TABLES`：抓取主表、已确认续表及同附注补充子表；每个独立子表仍分别形成
  child capture，不横向拼接。

默认策略为 `PRIMARY_ONLY`。选择由显式用户操作写入持久化 CaptureRequest；Streamlit
渲染本身不得改变业务状态。

### Guided self-selection

Guided 执行按 request 自选择，不能把 filing 级选择集合复制给每个作业：

- `PRIMARY_ONLY` 的 `selected_logical_table_ids` 必须为空数组；认证主表身份仍由 request
  target 中的 certified `logical_table_id` 保存。
- `SELECTED_NOTE_TABLES` 的每个 request 只携带自身 certified `logical_table_id`，不得携带
  同 filing 的其他 supplementary ID。
- filing 级 union 只验证用户显式选择的 supplementary logical-table IDs；主表不进入该
  union，未选择的 supplementary 也不得因同附注关系被隐式加入。

因此 `PRIMARY_ONLY` 只改变执行范围，不改变认证 inventory 事实；显式补充表选择也不会
放宽 CertifiedChildTableLink 或 segment manifest 校验。

### Bundle and LogicalAsset identity

不可变 CaptureBundle version identity 同时包含 note-container identity、certified
`logical_table_id`、scope signature、CaptureRequest identity 和 root Capture identity。
同一 version 重放时，bundle children 必须在一个事务内先替换后重建，并形成唯一连续的
`child_order=0..n-1`；任何部分更新都必须回滚。

LogicalAsset identity 包含 certified `logical_table_id`，但不包含 scope policy/signature。
这使逻辑资产跨策略稳定，同时由不可变 bundle/Capture version 保留每次策略执行事实。
Merge 对每个 bundle 严格要求唯一 `child_order=0` root，并拒绝缺根、双根、乱序、空洞或
requested root 与 registry root 不一致。

### Segment relation

NoteContainer 内每个物理片段必须分类为：

- `PRIMARY_TABLE`
- `CONTINUATION_SEGMENT`
- `SUPPLEMENTARY_TABLE`
- `PEER_TABLE`
- `UNRESOLVED`

续表关系至少保存 `continuation_of_segment_id`、页码/bbox、置信度和证据。相同附注号、
相同表名仅是证据之一，不能单独决定 continuation。通用判断还包括页面连续性、表头及
金额列拓扑、period/measure/unit、行分类轴、叙述性分隔语和新同级附注证据。

PDF 标题中的“续”或“（续）”只表示附注排版延续，是弱证据。分类轴或表意维度重置，
并且存在独立披露边界时，即使附注号和标题仍带“续”，也分类为新的
`SUPPLEMENTARY_TABLE`。period 重置本身只是一项证据：同页、同披露目的、同金额轴下
依次列示的本期与比较期区块属于一张逻辑表。只有同一逻辑表因分页截断、表头/期间/
分类轴延续且数据行未自然完结时，才分类为 `CONTINUATION_SEGMENT`。

垂直期间重叠需要同时保存逻辑与物理两层身份：同一物理 bbox 内的本期/比较期区块可以保留两个逻辑 block；若共享披露边界和金额轴，认证清单只登记一个物理段。Capture 必须在每行保留 `physical_segment_id` 回指该段，同时保留各逻辑 block 的独立列 ordinal。不得采用“一个逻辑 block 等于一个物理段”的简化，也不得把垂直期间区块横向串接为错误金额列。

候选页必须严格晚于主表金额来源页；`candidate_page <= main_statement_page` 在 Tier 1/2/3
之前统一拒绝，不能由后续 fallback 重新引入。

### Generic classification only

生产代码不得按公司名分支。公司差异只允许作为声明式 alias、Research Definition 或
Golden evidence；核心分类器只消费通用结构证据。

### Merge and lineage

- `PRIMARY_ONLY` 的输出必须标记 `capture_scope_limited=true`，保留排除续表的证据与 warning。
- `SUPPLEMENTARY_TABLE` 独立拥有 block role、列拓扑、Capture Version、reducer 决策和 lineage。
- `UNRESOLVED` 不得被自动归为续表或补充表。
- 任何策略都不得绕过 CertifiedChildTableLink、伪造金额或创建第二套 Capture/Review/Merge 管线。

## Consequences

CaptureRequest、Stage B UI、compound segmentation、CaptureDecisionReducer、artifact metadata
和测试需同步扩展。Whole-table 完整性解释为“用户明确选择的持久化范围内完整”；范围受限
结果必须在 lineage 中显式披露，不能被报告为完整附注全量抓取。

截至 2026-08-05，certified scope 已无 Stage B/Review/Merge 阻断：fresh
`PRIMARY_ONLY` 正式 Merge 为 49 roots → 90 assets，current Golden v3 883/883；fresh
supplementary 正式 Merge 为 14 roots → 18 assets，Golden 322/322，冲突 0。该结论不得
扩张为 `ALL_NOTE_TABLES` 全覆盖：仅新华 2024 为 `CLEAR`，其余 11/12 为 `PENDING`；
认证 corpus 中 true `CONTINUATION_SEGMENT` 为 0，Streamlit 状态为 `NOT_RUN`。
