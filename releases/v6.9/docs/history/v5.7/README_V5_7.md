# Financial Metric Resolver v5.7
## Relative-Period Headers + Wrapped Row Structure + Formula Reconciliation

v5.7 fixes a class of insurance annual-report tables that v5.6 could locate only partially or could not parse at all.

Representative structure:

```text
34. 业务及管理费

             本集团                    本公司
        本年累计数  上年累计数     本年累计数  上年累计数
          人民币元    人民币元       人民币元    人民币元

工资和福利费            ...
...
租赁费                  <blank>
其他                    ...
小计                    ...

减：
    当期发生的保费获取
        现金流          ...
    当期发生的其他保险
        履约现金流      ...

合计                    ...
```

Three failures in v5.6 are fixed together:

1. `本年累计数 / 上年累计数` were not recognized as logical period columns because the spatial engine expected four-digit years.
2. Wrapped accounting labels and blank-value detail rows were misclassified as sections, corrupting `child_items`.
3. When no note number was supplied, body-vs-TOC location scoring was too dependent on four-digit year headers.

---

# 1. Relative-period header support

The spatial header engine now recognizes:

```text
2025年度 / 2024年度

本年累计数 / 上年累计数
本期累计数 / 上期累计数
本期 / 上期
本年 / 上年
当期 / 上期
期末 / 期初
```

Relative-period labels can also be split into adjacent PDF word objects:

```text
本年 + 累计数
```

and are reconstructed before column-anchor detection.

---

# 2. Four-column hierarchical header example

This header:

```text
             本集团                    本公司
        本年累计数  上年累计数     本年累计数  上年累计数
```

is now parsed as four unique logical columns:

```text
col0 = 本年累计数 | 本集团
col1 = 上年累计数 | 本集团
col2 = 本年累计数 | 本公司
col3 = 上年累计数 | 本公司
```

The repeated unit row:

```text
人民币元
```

is treated as header context and no longer becomes a fake data row.

---

# 3. Relative periods resolve to absolute years at Merge time

Capture evidence remains faithful to the PDF:

```text
period_label = 本年累计数
period_label = 上年累计数
```

When a Merge source has:

```text
document_year = 2022
```

the Merge layer resolves:

```text
本年累计数 -> 2022
上年累计数 -> 2021
```

while preserving:

```text
source_period_label
```

for audit.

Final dimensions become:

```text
2022 | 本集团
2021 | 本集团
2022 | 本公司
2021 | 本公司
```

No relative-period wording is destroyed in the source evidence.

---

# 4. No-note-number body location fixed for relative-period tables

When the user leaves:

```text
附注编号 = blank
```

v5.7 can locate:

```text
34. 业务及管理费
```

inside the real note body even if the table has no four-digit year headers.

Body-vs-TOC scoring now recognizes relative-period table evidence:

```text
本年累计数
上年累计数
```

as strong table-header evidence.

The system then infers:

```text
resolved_note_number = 34
note_number_source = INFERRED_FROM_LOCATED_TITLE
```

and searches for:

```text
35. 下一附注
```

as the hard end boundary.

---

# 5. Locator no longer swallows the parent header line

A subtle v5.6 failure could occur when:

```text
34. 业务及管理费
本集团       本公司
```

The locator sometimes merged the title line with the next line:

```text
34. 业务及管理费本集团本公司
```

and moved `start_y` below `本集团 / 本公司`.

Result:

```text
scope = missing
```

v5.7 only merges the next physical line when the current line does not already contain a compatible complete title.

Therefore the scope parent header remains inside the ROI.

---

# 6. Cross-company title variation support

A query such as:

```text
业务及管理费和其他业务成本
```

can now conservatively match a numbered body heading such as:

```text
34. 业务及管理费
```

when there is a substantial containment relationship and nearby table evidence confirms the body context.

This helps when equivalent notes use slightly different titles across issuers/years.

---

# 7. Blank-value detail rows no longer become SECTION_HEADER

Example:

```text
短期租赁费和低价值资产    3,467,127 ...
租赁费                    <blank>
其他                      37,906,512 ...
小计                      ...
```

In v5.6:

```text
租赁费
```

could be interpreted as a section header, causing reconciliation to think:

```text
小计 children = 其他 only
```

v5.7 preserves same-indent, text-only rows as:

```text
row_type = DETAIL
cells = []
```

unless they are explicit structural markers.

Thus `租赁费` remains part of the structural child set, while its missing value causes only a review warning.

---

# 8. Wrapped accounting labels are reconstructed

Example:

```text
当期发生的保费获取
    现金流             594,788,447 ...

当期发生的其他保险
    履约现金流         1,355,333,737 ...
```

v5.6 could create:

```text
SECTION_HEADER = 当期发生的保费获取
DETAIL = 现金流
```

and:

```text
SECTION_HEADER = 当期发生的其他保险
DETAIL = 履约现金流
```

v5.7 recognizes the indented second line as a wrapped continuation and reconstructs:

```text
当期发生的保费获取现金流

当期发生的其他保险履约现金流
```

This directly fixes the incorrect reconciliation `child_items`.

---

# 9. Explicit structural markers remain sections

Rows such as:

```text
减：
加：
按费用项目：
```

remain:

```text
SECTION_HEADER
```

They are not merged into the next accounting item.

---

# 10. Small subtotal child membership fixed

For:

```text
工资和福利费
委托管理费及托管费
...
租赁费
其他
小计
```

the `小计` reconciliation child set now includes the full structural block:

```text
工资和福利费
委托管理费及托管费
...
租赁费
其他
```

rather than only:

```text
其他
```

If one member such as `租赁费` has no value, the audit returns:

```text
WARNING_COMPONENT_SCOPE_AMBIGUOUS
```

but preserves the correct `child_items` membership for human review.

No missing value is silently treated as zero.

---

# 11. New net-total formula reconciliation

v5.7 recognizes:

```text
小计
减：
    当期发生的保费获取现金流
    当期发生的其他保险履约现金流
合计
```

as:

```text
BASE_MINUS_COMPONENTS
```

Formula:

```text
合计
=
小计
- 当期发生的保费获取现金流
- 当期发生的其他保险履约现金流
```

Audit fields include:

```text
child_row_orders
child_items
component_operators
formula_expression
reported_total
calculated_sum
difference
status
```

Example operators:

```text
+ | - | -
```

---

# 12. Plus-adjustment pattern

The same engine supports:

```text
小计
加：
    调整项A
    调整项B
合计
```

as:

```text
BASE_PLUS_COMPONENTS
```

Again, structure determines membership; arithmetic only validates.

---

# 13. Final TOTAL hierarchy after 加/减 block

A final:

```text
合计
```

after:

```text
减：
```

is restored to top-level structural hierarchy:

```text
row_level = 0
parent_section = None
```

It is not incorrectly stored as a child of `减`.

---

# 14. Dual-engine failure diagnostics improved

Previously the user could see only the legacy error:

```text
ValueError:
识别到表格块，但无法建立数值列/多层表头结构。
```

even when the actual first failure occurred in the spatial engine.

If both engines fail, v5.7 reports both causes:

```text
SPATIAL=<error>
LEGACY=<error>
```

This makes future unsupported layouts diagnosable.

---

# 15. Header-period provenance in long output

Capture long output now preserves:

```text
year
period_label
source_column_index
column_ordinal
scope
restated
column_dimension_key
```

At Merge time, relative periods are converted to absolute years only when a valid `document_year` exists.

---

# 16. Reconciliation remains warning-only

The v5.7 formula improvements do NOT change the safety contract.

The system never:

```text
changes extracted amounts
fills missing values with zero
searches arbitrary combinations to "make the total work"
deletes a row because a sum mismatches
```

Membership remains:

```text
STRUCTURE -> MEMBERSHIP
ARITHMETIC -> VALIDATION
```

---

# 17. Validation performed

A synthetic PDF reproducing the reported layout was created with:

```text
Page 1:
TOC hit for 34. 业务及管理费

Page 2:
34. 业务及管理费
本集团 / 本公司
本年累计数 / 上年累计数
人民币元
blank 租赁费 row
wrapped 获取现金流 / 履约现金流 rows
小计
减:
合计
35. 下一附注
```

Regression results:

```text
NO_NOTE_NUMBER_BODY_LOCATION_PASS

RELATIVE_PERIOD_4_COLUMN_HEADER_PASS

BLANK_DETAIL_ROW_PASS

WRAPPED_ACCOUNTING_LABEL_PASS

SUBTOTAL_CHILD_MEMBERSHIP_PASS

BASE_MINUS_COMPONENTS_RECONCILIATION_PASS

RELATIVE_TO_ABSOLUTE_YEAR_MERGE_PASS

ALL_V57_REGRESSION_TESTS_PASS
```

Also verified:

```text
query:
业务及管理费和其他业务成本

actual title:
34. 业务及管理费

-> correct body page selected
-> note 34 inferred
-> 4-column relative header parsed
```

---

# 18. Retained functionality

v5.7 retains v5.6:

```text
Shared DATA_HOME
Historical Migration Center
Conditional parent_section identity
Warning-only reconciliation framework
Auto note-number inference
```

v5.5:

```text
Hierarchical 本集团 / 本公司 header binding
Header Dimension Review
Header collision gate
```

v5.4:

```text
canonical_order structural preservation
小计/明细/合计 order protection
Merge Library
```

v5.3 and earlier:

```text
Boundary Review
Capture Library
Source Quality Arbitration
Custom CSV export
Spatial ROI
Taxonomy
conflict gates
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
