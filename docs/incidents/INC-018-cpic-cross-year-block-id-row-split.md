# INC-018 — 太保跨年度 Block ID 导致同一行拆分

## 现象

太保机器宽表中，`fvtpl_assets / 债券` 的 2023–2025 数据分散在三行。三行的 member、row path、canonical item、classification axis 与单位一致，但 `container_id/table_block_id` 不同。

## 根因

- source key 对唯一行无条件加入 Capture-local `table_block_id`。
- canonical key 在 axis 已解析时仍加入 `table_block_id`。
- wide pivot 又把全部物理 Block 字段作为 index。

物理 provenance 因此被错误提升为跨年度经济身份。

## 修复

落实 ADR-009：已解析语义轴跨 Capture 对齐；未解析轴继续按 Block 隔离；wide 只按 canonical key pivot，物理 lineage 聚合展示并保留在 Canonical Long provenance。

## 回归

- 三年度、三个 Block ID 的同一“债券”合成一条宽表行。
- 不同语义轴保持分离。
- 未解析轴保持 Block 隔离。
- 同文档维度不同值仍为阻断冲突。

