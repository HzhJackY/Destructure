# Financial Metric Resolver v5.4 — Structural Order Preservation + Merge Library Management

v5.4 fixes a critical semantic problem in merged financial-note tables: row order is part of the accounting meaning and must never be treated as a cosmetic sort order.

## 1. Critical fix: merged rows no longer reorder arbitrarily

Prior merge materialization used pandas grouping/pivot operations to create canonical outputs. Even when `sort=False` was used in some places, the final wide-table construction did not have one explicit, authoritative structural order.

That could produce a result such as:

```text
原表：

小计
  明细A
  明细B
合计
```

becoming:

```text
明细A
合计
明细B
小计
```

The values may still be numerically correct, but the accounting/table semantics are destroyed.

v5.4 makes row order a first-class data contract.

## 2. Explicit ordering reference table

When creating a Merge Project, the user now selects:

```text
排序基准表
```

Default:

```text
the first selected capture
```

The selected reference capture provides the immutable structural backbone:

```text
row_order
row_type
row_level
parent_section
```

Example:

```text
1  小计        SUBTOTAL
2  明细A       DETAIL
3  明细B       DETAIL
4  合计        TOTAL
```

These existing reference rows are NEVER reordered by:

```text
groupby
pivot
alphabetical item names
taxonomy mapping
another company's row order
```

## 3. Canonical order

Every merged canonical row now receives:

```text
canonical_order
```

This is the authoritative research-output row sequence.

Example:

```text
canonical_order | row_type | canonical_item
1               | SUBTOTAL | 小计
2               | DETAIL   | 明细A
3               | DETAIL   | 明细C
4               | DETAIL   | 明细B
5               | TOTAL    | 合计
```

The final `merge_canonical_wide.csv` is explicitly sorted by `canonical_order`.

## 4. Other-company unique items use contextual insertion

Suppose the reference table is:

```text
小计
明细A
明细B
合计
```

Another company has:

```text
小计
明细A
明细C
明细B
合计
```

v5.4 does NOT append `明细C` to the bottom.

It inserts it using the nearest known structural anchors:

```text
小计
明细A
明细C
明细B
合计
```

Existing reference keys never move.

This is especially important for:

```text
小计 → child items
subtotal → detail breakdown
classification total → sub-items
合计 → final row
```

## 5. Structural hierarchy metadata preserved

Canonical outputs now retain:

```text
canonical_order
row_type
row_level
parent_section
canonical_section
canonical_item
```

So order and hierarchy can be audited together.

Typical row types:

```text
SECTION_HEADER
DETAIL
SUBTOTAL
TOTAL
CLASSIFICATION_TOTAL
```

## 6. Order conflicts are explicit

If another company's shared rows contradict the reference order:

Reference:

```text
明细A
明细B
```

Other source:

```text
明细B
明细A
```

the system creates:

```text
ORDER_CONFLICT
```

in:

```text
merge_order_conflicts.csv
```

The system does NOT try to average or reconcile the order automatically.

Final policy:

```text
reference order remains authoritative
conflict is surfaced for review
```

## 7. Duplicate canonical-key structural conflict

If multiple original rows inside one source are mapped to the same canonical key at different positions:

```text
DUPLICATE_CANONICAL_KEY_IN_SOURCE
```

is emitted.

This protects against a taxonomy mapping accidentally collapsing two structurally different rows into one identity.

Value/unit conflicts remain separately handled by:

```text
VALUE_CONFLICT
UNIT_CONFLICT
```

## 8. Structural order audit outputs

New files:

```text
merge_structural_order.csv
merge_order_conflicts.csv
```

`merge_structural_order.csv` contains:

```text
canonical_order
canonical_key
row_type
row_level
parent_section
canonical_section
canonical_item
order_source
reference_capture_run_id
reference_row_order
metadata_source_capture_run_id
```

`order_source` examples:

```text
REFERENCE:<run_id>
INSERTED_FROM:<run_id>
APPENDED_UNREFERENCED
```

## 9. Merge manifest records the ordering policy

`merge_manifest.json` now records:

```text
version = v5.4

order_policy =
REFERENCE_CAPTURE_PRESERVE_WITH_CONTEXTUAL_INSERTION

reference_capture_run_id =
<selected capture>
```

This makes the final row ordering reproducible and auditable.

## 10. Mapping refresh cannot reorder the table

After taxonomy/human mapping:

```text
保存映射并重新物化合表
```

the structural order is recomputed from the same reference policy.

The output cannot silently revert to alphabetical/groupby/pivot ordering.

Regression test:

```text
before taxonomy refresh:
小计
明细A
明细C
明细B
合计

after taxonomy refresh:
小计
明细A
明细C
明细B
合计

PASS
```

## 11. Excel adds structural audit sheets

`merge_project.xlsx` now includes:

```text
raw_long
mapping_queue
canonical_long
resolved_long
canonical_wide
conflicts
coverage
structural_order
order_conflicts
```

## 12. New Merge Library management

The Merge workspace is upgraded from a simple folder selector to a managed project library.

Overview columns include:

```text
名称
Table ID
来源数
排序基准
顺序冲突
数值/单位冲突
备注
```

## 13. Merge project rename / notes

Each project has stable:

```text
run_id
```

plus editable:

```text
display_name
note
```

Example:

```text
display_name =
五家上市险企_业务管理费_2020_2025_正式版

note =
排序基准：中国平安2025
```

Changing display name does not change the stable run directory identity.

## 14. Soft delete and recycle bin

Merge project deletion is now managed.

```text
管理
→ 移到回收站
```

moves the whole Merge Project to:

```text
workspace/table_merges/_trash/
```

It does NOT delete:

```text
source table captures
original PDFs
persistent taxonomy
```

Recycle-bin actions:

```text
恢复合表项目
永久删除
```

Permanent deletion requires explicit confirmation.

## 15. New GUI Structural Order tab

Merge Project tabs now include:

```text
Canonical宽表
结构顺序
Resolved Long
映射审核
冲突
覆盖率
Raw Long
管理
下载
```

The `结构顺序` tab shows:

```text
merge_structural_order.csv
merge_order_conflicts.csv
```

so the exact reason for each row's position is visible.

## 16. Validation performed

Critical regression:

Reference table:

```text
1 小计
2 明细A
3 明细B
4 合计
```

Other company:

```text
1 小计
2 明细A
3 明细C
4 明细B
5 合计
```

Final merged output:

```text
1 小计
2 明细A
3 明细C
4 明细B
5 合计
```

Verified:

```text
小计 remains first
合计 remains last
unique child C inserted between A/B
row_type preserved
row_level preserved
parent_section preserved

PASS
```

Conflicting company:

```text
明细B
明细A
```

against reference:

```text
明细A
明细B
```

Result:

```text
ORDER_CONFLICT emitted
reference order unchanged

PASS
```

Merge management regression:

```text
rename/note
soft delete
restore
permanent delete

PASS
```

## 17. Retained functionality

v5.4 retains all v5.3 functionality:

```text
output-based boundary human review
machine-full vs official capture layers
Capture Library
soft delete / recycle bin
merge boundary gate
```

v5.2:

```text
semantic score
evidence quality
arbitration score
custom CSV path/name
```

v5.1:

```text
Spatial ROI Table Capture
numeric fragment reconstruction
exact table boundaries
TOC resistance
complete Merge / Taxonomy workflow
persistent taxonomy
value/unit conflict gates
```

## Launch

```powershell
python -m pip install -r requirements.txt
python -m streamlit run app.py
```

or:

```text
run_gui.bat
```
