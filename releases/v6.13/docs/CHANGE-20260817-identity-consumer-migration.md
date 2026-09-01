# Change Report — v6.13 身份消费端迁移

日期：2026-08-17

状态：`TARGETED_VALIDATION_COMPLETE`

## 目标

消除 UI 与 Merge 继续使用旧 `parent_section/row_level/row_type/row_path` 重建层级而
造成的父子口径漂移，并纠正把 Capture-local `source_row_id` 直接用于跨年度合表的风险。

## 实现

- `financial_structure_resolver.project_certified_row_hierarchy()` 成为 UI/Merge 共用的
  认证父子图只读投影。
- Capture Inspection 行结构面板展示 `source_row_id`、`parent_row_id`、认证路径和状态；
  旧字段不再决定 UI 层级。
- `table_merge.assign_semantic_row_keys()` 生成跨年度 `semantic_row_key`，并保留旧
  `assign_conditional_source_keys()` 作为同一实现的兼容入口。
- Canonical key 使用语义父链和 occurrence；物理 ID 与 bbox 仅进入 provenance。
- 缺失父项或循环父项以 `REVIEW_REQUIRED_SEMANTIC_ROW_IDENTITY` 隔离，不静默合并。
- 历史 Capture 缺少新身份时仅进入显式 `LEGACY_IDENTITY_COMPATIBILITY` 适配器；没有
  执行生产 DATA_HOME 破坏性迁移。

## 验证

- 新增身份消费端定向测试：5/5 通过。
- 编译检查：通过。
- 浏览器 E2E：按任务约束未运行。
- 真实 PDF/生产 DATA_HOME：本轮未修改；需在认证 Capture Plan 上另行执行。

## 不变量

- 不同年度的不同 `source_row_id`，只要 member、分类轴、规范项目名和认证父链一致，
  生成相同 `semantic_row_key`。
- 同名行处于不同认证父项时，语义键不同。
- UI 与 Merge 对同一 `parent_row_id` 生成相同层级路径。
- 旧展示字段不能覆盖认证父子边。

## 剩余风险

- 旧资产仍保留旧字段，尚未执行快照后删除；兼容适配器需要在生产迁移窗口单独处理。
- 真实 PDF 回归和用户重启 Streamlit 后人工验收尚未完成。
