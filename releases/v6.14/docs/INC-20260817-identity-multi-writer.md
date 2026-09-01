# INC-20260817 — Capture 身份多写入者导致父子关系漂移

## 现象

数值父项已通过缩进和金额闭合认证，但 Direct 原生恢复后部分子行的
`parent_section`/`row_level` 被清空；`extractor_row_role`、公开 `row_role` 和父项字段互相矛盾。

## 根因

Spatial Capture 的 `_infer_numeric_parent_hierarchy()` 与 Direct 恢复函数都拥有层级写权限；
后者使用原生字符串首字符空格进行第二次启发式判断，覆盖了前者的机器证据。Long、
financial structure resolver 和 Merge 又各自按标签或行序重新推断。

## 修复

- Spatial Capture 创建稳定 `source_row_id` 并写入 `parent_row_id` 和 hierarchy evidence。
- Direct 恢复第二扫描改为审计-only。
- 下游优先消费已认证 `parent_row_id`，不再重新裁决。
- UI 与 Merge 已统一调用认证父子图投影；Merge 使用独立的 `semantic_row_key`，不把
  Capture-local `source_row_id` 当作跨年度身份。
- 旧字段在迁移后不再作为正式身份；历史缺少新字段的 Capture 只能进入明确标记的兼容适配器。

## 回归不变量

任何 Capture 后处理不得降低已认证父子边的置信状态或清空 `parent_row_id`。
