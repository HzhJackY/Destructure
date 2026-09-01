# INC-014 — 太保数值父行层级丢失

## 事发现象

12 份年报 fresh `PRIMARY_ONLY` Golden parity 中，太保 2023/2024 六张主子表共
33 个单元报 `CELL_NOT_FOUND`。Capture 已正确提取金额、期间、页码和 bbox，但把
“债券”及其缩进子项全部平铺为 `row_level=0`，导致“债券 - 金融债”等结构标签无法
从源事实匹配。

同时发现 Golden 中六个父数值行沿用了旧合成标签“债券小计”。直接核验 SHA 绑定
canonical PDF 原图确认：2023 p169/p170、2024 p151/p152 的原文均为“债券”，不存在
“小计”二字。

## 根本原因

- `spatial_table_capture` 只会把无金额的显式 section 行设为 parent；父行自身带金额时，
  没有消费 bbox 缩进与逐列金额勾稽证据。
- `compound_note_engine._semantic_graph()` 未投影已有 `parent_section` 关系。
- `capture_to_long_df()` 的 `parent_row_id` 只检索 `row_type == SECTION`，而实际 parser
  使用 `SECTION_HEADER`；数值父行也不可能命中该条件。
- Golden 旧 fixture 把结构含义写成非原文 raw label，掩盖了 source label 与 hierarchy
  应分开保存的事实。

## 正式修复

- 在空间 Capture owner 中加入通用数值父行推断：仅当至少两个连续数值行位于同页、
  同物理块，统一右缩进 6–72pt，且每个父金额列都与子项和在显示单位舍入容差内一致时，
  才写入 `parent_section` 与 `row_level`。
- 不改父子行的 raw label、normalized item、金额、bbox 或 source observation 身份；推断
  证据写入 Capture stats。
- Compound semantic graph 增加 `PARENT_OF` 关系；Capture Long 的 `parent_row_id` 改为
  指向同表内最近前置、标签一致的父行。
- 依据直接 PDF 证据把六个 Golden 父标签从“债券小计”更正为“债券”，变更 ID 为
  `ACL-1.1.5-CPIC-NUMERIC-PARENT-LABEL`；金额与其他事实不变。

## 永久回归

- 缩进 + 至少两子行 + 全金额列勾稽成立时建立层级。
- 金额不吻合、仅一个缩进行、跨页或跨物理块时不建立层级。
- bbox/raw/value 保持不变，semantic graph 与 Capture Long parent lineage 完整。
- 太保 2023/2024 六张真实 PDF 表与更正后的 Golden 逐项对账。

## 阻断语义

本修复只恢复结构事实，不改变 ADR-007：父子行或合计勾稽不一致仍为 warning，
不阻断合表；未满足严格结构证据时保持平铺，不发明 parent。
