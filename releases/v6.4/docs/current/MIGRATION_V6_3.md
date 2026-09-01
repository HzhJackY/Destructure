# v6.3 迁移说明

v6.3 从本地 v6.2 代码基线升级，不回退 v6.1，不重建既有 v6.2 的 Job、表族和结构解析能力。

## SQLite

首次打开数据目录时，`metadata.db` 执行幂等 `CREATE TABLE IF NOT EXISTS`：

- `capture_semantics`：表族、成员表、原表标题、附注引用和主表锚点；
- `statement_note_edges`：主表与附注导航边；
- `table_notes`：不可变表格备注证据。

这些都是控制面索引。删除或损坏 SQLite 后可以由 PDF、Capture JSON 和导出证据重新建立；不存放大型财务数据。

## 输出合同

旧的复合列标题不得作为研究主键。新数据以 Long 为主：`company, report_year, data_year, table_family, member_table, row_path, scope, restated, period_type, unit, value`。CSV 宽表以 `C0001` 等稳定列名输出，并由 `column_dimensions` 解释各列维度。

## 审计边界

主表—附注对账、脚注分类、结构推断和人工裁决均为派生信息；不能修改原 PDF、原 Capture 数值或机器证据。无法确认附注编号、科目语义或完整维度时，流程必须停在 `REVIEW_REQUIRED` 或 `NOT_TESTABLE`。
