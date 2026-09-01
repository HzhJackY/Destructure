# ADR-011 — v6.13 精简身份架构与单一父子裁判

状态：ACCEPTED（v6.13）

## 背景

Capture 历史上同时存在 `row_id`、`row_order`、`parent_section`、`row_level`、`row_role`、
`extractor_row_role` 和下游重新构造的 `row_path`。部分下游流程（如 Direct 原生恢复、宽表导出、
Semantic Graph）会根据旧文本字段重新推断层级，造成同一行的角色、层级和父项身份不一致。

## 决策

1. **唯一写入者（Single-Writer）**：
   - `source_row_id` 是单份 PDF 内的唯一源行身份，由 PDF、物理表、页码、block、bbox 和 occurrence 生成，不依赖 `row_order`；
   - `parent_row_id` 是唯一父子边，由 Spatial Capture 在几何缩进和金额闭合认证后唯一写入；
   - `parent_section`、`row_level`、`parent_row_order` 降级为只读展示/审计字段，下游消费者严禁利用这些字段反向补写正式边；
   - Direct 原生恢复降级为纯只读冲突审计（`AUDIT_ONLY_NO_IDENTITY_MUTATION`），严禁注入新行或改写正式 ID。

2. **全端消费一致图（Single Truth Graph）**：
   - UI、Canonical Long、Wide、Merge、Semantic Graph 统一消费 `project_certified_row_hierarchy()`；
   - 废除生产导出端旧启发式 `infer_row_structure` 的层级重推。

3. **严格版本门禁与失败关闭（Fail-Closed Gating）**：
   - `producer_version >= v6.13` 默认执行严格模式（`allow_legacy_compatibility=False`）；
   - 只有显式登记为 `identity_schema=LEGACY` 或在迁移清单内的旧数据才允许进入 Legacy Adapter；
   - 新 Capture 缺 ID 或元数据缺失时，统一标记 `REVIEW_REQUIRED_SOURCE_IDENTITY`，阻断跨表合并。

4. **受控缺失语义（Controlled Cell Missingness）**：
   - 数值勾稽判定引入 `VALUE`、`PRINTED_DASH`、`NOT_APPLICABLE`、`EXTRACTION_MISSING`、`UNRESOLVED` 5 态受控模型；
   - 纯空白/空 raw 不视作破折号；金额列漏值时严禁通过数值闭合。

5. **统一图完整性校验器与治理联动**：
   - Capture 冻结前执行 `validate_hierarchy_graph()`，校验缺失/重复 ID、悬空边、自引用、环、跨物理表及跨 Block 异常；
   - 校验异常记录机器证据并接入 `CaptureDecisionReducer` 阻断进入 Canonical/Merge。

## 后果

- 补入组标题或重新排序不会改变源行身份。
- 同名子项通过 `parent_row_id` 和 `source_row_id` 保持独立。
- 彻底消除多写者冲突与多端层级显示歧义。
- 严格失败关闭保障未审核身份缺陷无法静默渗透进入 Merge。

