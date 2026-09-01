# ADR-009 — Semantic Axis Cross-Capture Row Identity

Status: ACCEPTED

## Context

`container_id`、`table_block_id`、`block_order`、`block_role` 与 `block_terminal_type` 是单次 Capture 的物理 lineage。不同年度对同一附注表重新 Capture 时，这些 ID 必然不同。把它们编入 Canonical key 或 wide pivot index，会把同一经济项目按年度拆成多行。

## Decision

- 跨 Capture 的行身份使用 `table_family + member_table + member_table_role + classification_axis + canonical section/item + row_path` 及观察维度。
- 已解析的 `classification_axis` 是稳定语义块维度；物理 Block 字段不参与跨 Capture 对齐。
- 当 `classification_axis=UNRESOLVED` 时，继续使用 `table_block_id` 隔离，禁止证据不足时自动合并。
- 物理 Block 字段保留在 Canonical Long 的 `source_provenance`；机器宽表若包含多个来源，显示聚合的 `MULTIPLE[...]` lineage，不伪装成单一来源。
- 同一文档维度、同一语义身份出现不同值时必须产生阻断性 `VALUE_CONFLICT`，不得以 pivot `first` 隐藏。
- 语义轴优先来自 Research Definition 成员合同，并必须沿 Discovery/Plan/CaptureRequest
  进入 Capture。Capture 仍可使用明确的行内 SECTION_HEADER 等表内证据补充解析；
  但不得仅凭成员名、同值、存在“合计”或硬编码行标签把一般 `UNRESOLVED` Block 提升为
  稳定语义轴。

## Consequences

旧 Merge Project 可由正式 refresh 非破坏性重新物化；无需重抓 PDF 或 Capture。Mapping Queue 的旧 Block-scoped source key 可继续读取，Canonical key 会按新合同重新生成。
