# Financial Metric Resolver v5.3 — Boundary Review + Capture Library Management

v5.3 closes the table-boundary review loop and turns historical table captures into a managed data library.

## 1. Boundary review is now performed directly on extracted output

Problem in prior versions:

```text
warning:
未发现下一附注编号作为硬结束边界，
当前使用 max_pages 边界，请人工核对末尾。
```

but there was no actual review workflow.

v5.3 adds a real adjudication step.

When boundary status is:

```text
REVIEW_REQUIRED
```

the reviewer sees the full machine-extracted table and chooses:

```text
最后一条属于目标表的记录
```

Example:

```text
15 · 合计
16 · 可归属于保险合同组合的费用
17 · 不可归属于保险合同组合的费用
18 · 银行存款减值损失
19 · 净利润
```

If row 17 is selected:

```text
row 1–17
→ official output

row 18+
→ EXCLUDED BY BOUNDARY REVIEW
```

No PDF y-coordinate editing is required.

## 2. Machine evidence is immutable

v5.3 separates:

```text
machine_capture_full_long.csv
machine_capture_full_wide.csv
```

from official/adjudicated output:

```text
table_raw_long.csv
table_raw_wide.csv
table_item_dictionary.csv
```

Human boundary review never deletes the original machine capture.

Excluded rows are preserved in:

```text
boundary_excluded_rows.csv
```

Boundary decision is recorded in:

```text
boundary_review.json
```

and in:

```text
table_capture_result.json
```

## 3. Boundary statuses

### HARD_BOUNDARY_CONFIRMED

Automatic hard boundary found, for example:

```text
30. target note
...
31. next note
```

### HUMAN_CONFIRMED

Reviewer explicitly selected the last valid output row.

### REVIEW_REQUIRED

No reliable hard end boundary exists yet.

Only merge-ready statuses can enter the formal Merge workspace:

```text
HARD_BOUNDARY_CONFIRMED
AUTO_HIGH_CONFIDENCE
HUMAN_CONFIRMED
```

`REVIEW_REQUIRED` captures are blocked from formal merge until reviewed.

## 4. Boundary review rematerializes all official artifacts

After confirmation:

```text
table_raw_long.csv
table_raw_wide.csv
table_item_dictionary.csv
table_capture.xlsx
```

are regenerated from the accepted row range.

Excel includes:

```text
raw_long
raw_wide
item_dictionary
machine_full_long
machine_full_wide
boundary_excluded
```

The complete machine extraction remains available for audit.

## 5. Reset / re-adjudicate

A reviewed capture can be reset:

```text
恢复完整机器抓取并重新待审
```

This restores the full machine output and returns the boundary to its automatic status.

The reviewer can then choose a different cutoff.

## 6. Source-aware automatic capture names

New capture run directories now include:

```text
original PDF filename
+
note/table name
+
timestamp
```

Example:

```text
中国平安2025年度报告
__30_业务及管理费和其他业务成本
__20260721T153022
```

This makes filesystem-level runs much easier to distinguish.

A separate stable `run_id` remains the internal identifier.

## 7. Capture Library

The historical capture section is upgraded to a managed Capture Library.

The library table shows:

```text
display name
source PDF
table name
note number
page range
official row count
boundary status
merge readiness
note
```

## 8. Historical preview

Each capture has a Preview workspace containing:

```text
正式宽表
机器完整宽表
正式长表
PDF页预览
```

PDF preview shows:

```text
start page
end page
```

so extracted output can be visually compared with source evidence.

If the original PDF is no longer available under `workspace/uploads`, the UI reports that explicitly.

## 9. Historical boundary review

Any historical capture can reopen the same boundary-review workflow:

```text
Capture Library
→ select capture
→ 边界复核
→ choose last valid row
→ rematerialize official outputs
```

This also works for older captures when their existing raw output can be migrated into a machine-full audit snapshot.

## 10. Rename and notes

Capture Library metadata supports:

```text
display_name
note
```

Renaming the display name does not change the stable run directory identity.

Examples:

```text
平安2025_业务管理费_最终确认
国寿2024_业务管理费_待核单位
```

## 11. Soft delete / recycle bin

Deleting a historical capture does not immediately destroy it.

```text
移到回收站
```

moves the run under:

```text
workspace/table_captures/_trash/
```

The original PDF is not deleted.

Recycle-bin actions:

```text
恢复
永久删除
```

Permanent deletion requires explicit confirmation.

## 12. Merge boundary gate

The Merge workspace now separates:

```text
merge-ready captures
```

from:

```text
boundary-unconfirmed captures
```

Unconfirmed captures are listed with a message directing the user to:

```text
整表抓取
→ Capture Library
→ 边界复核
```

They cannot silently enter the canonical research dataset.

## 13. Current-capture workflow

Immediately after a new table capture, tabs are:

```text
正式宽表
正式长表
边界复核
细项字典
列结构
机器JSON
下载
```

If the boundary is uncertain, review can be completed immediately without leaving the result page.

## 14. Download/export behavior

Both official and machine-full outputs can be downloaded:

```text
table_raw_long.csv
table_raw_wide.csv

machine_capture_full_long.csv
machine_capture_full_wide.csv

table_item_dictionary.csv
table_capture.xlsx
```

v5.2 custom filesystem CSV export remains available.

## 15. Validation performed

Automated regression:

```text
machine capture rows = 1..5

human cutoff = row 3

official output
→ rows 1..3

machine full
→ rows 1..5 unchanged

excluded audit
→ rows 4..5

boundary_status
→ HUMAN_CONFIRMED

merge_ready
→ True

PASS
```

Reset regression:

```text
HUMAN_CONFIRMED
→ reset
→ full machine output restored
→ REVIEW_REQUIRED
→ merge blocked

PASS
```

Hard-boundary regression:

```text
boundary_reason = next_note_31
→ HARD_BOUNDARY_CONFIRMED
→ merge ready

PASS
```

Capture Library regression:

```text
source-aware display name
soft delete
restore

PASS
```

## 16. Retained functionality

v5.3 retains all v5.2 functionality:

```text
semantic score + evidence quality + arbitration score
complete-source preference
custom CSV directory / filename export
```

and all v5.1 functionality:

```text
Spatial ROI Table Capture
numeric fragment reconstruction
exact note boundaries
TOC resistance
complete Merge / Taxonomy workflow
persistent taxonomy
conflict gates
coverage reports
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
