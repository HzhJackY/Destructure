# Financial Metric Resolver v5.5 — Hierarchical Header Dimensions + Header Review

v5.5 fixes a P0 false-conflict problem in multi-level financial-statement headers.

Example source table:

```text
                  本集团                    本公司
             2022年度  2021年度       2022年度  2021年度
总计          909041083 987834923      922826882 992644880
```

Older extraction could lose the parent `本集团 / 本公司` dimension and materialize:

```text
2022 | scope=None | 909041083
2022 | scope=None | 922826882
```

The Merge layer then correctly—but falsely from an accounting perspective—raised:

```text
VALUE_CONFLICT
```

because two different data windows had collapsed into the same natural key.

v5.5 fixes the problem before Merge.

## 1. Hierarchical Header Span Binding

The spatial table engine now recognizes parent-level headers that span multiple leaf period columns.

```text
         本集团                 本公司
      2022   2021          2022   2021
```

is bound as:

```text
col0 = 2022 | 本集团
col1 = 2021 | 本集团
col2 = 2022 | 本公司
col3 = 2021 | 本公司
```

The old behavior assigned a parent label only to its nearest single year anchor.

The new behavior propagates a parent label across all spatially plausible child anchors in its span.

## 2. Parent headers above the year row are now parsed

The old header parser mainly inspected rows below the year header.

v5.5 scans a bounded header band both:

```text
above the year row
and
below the year row
```

This supports common layouts where:

```text
本集团 / 本公司
```

sit above:

```text
2022年度 / 2021年度
```

## 3. Header Dimension Uniqueness Gate

Every logical numeric column must have a unique identity:

```text
year
scope
restated
```

The system validates:

```text
column_dimension_key =
year | scope | ORIGINAL/RESTATED
```

Unsafe example:

```text
2022 | scope missing
2021 | scope missing
2022 | scope missing
2021 | scope missing
```

produces:

```text
DUPLICATE_PERIOD_WITHOUT_COMPLETE_SCOPE
HEADER_DIMENSION_COLLISION
```

and:

```text
header_dimension_status = REVIEW_REQUIRED
```

## 4. Unsafe header dimensions block formal Merge

A capture is now merge-ready only when both independent structural gates pass:

```text
Boundary gate:
HARD_BOUNDARY_CONFIRMED
or HUMAN_CONFIRMED
or AUTO_HIGH_CONFIDENCE

AND

Header gate:
AUTO_CONFIRMED
or HUMAN_CONFIRMED
```

A capture with:

```text
boundary = HARD_BOUNDARY_CONFIRMED
header_dimension = REVIEW_REQUIRED
```

is still blocked from formal Merge.

This prevents false `VALUE_CONFLICT` from entering downstream canonicalization.

## 5. Header Dimension Review

Capture results now include:

```text
表头维度复核
```

The reviewer directly sees the machine-detected logical columns:

```text
ordinal
source_column_index
header_raw
year
scope
restated
```

Editable fields:

```text
year
scope
restated
```

Example correction:

```text
col0  2022  本集团  false
col1  2021  本集团  false
col2  2022  本公司  false
col3  2021  本公司  false
```

After confirmation:

```text
header_dimension_status = HUMAN_CONFIRMED
```

and official outputs are rematerialized without re-running the PDF parser.

## 6. Machine headers remain immutable

The machine-detected header evidence stays in:

```text
table_capture_result.json["columns"]
machine_capture_full_long.csv
machine_capture_full_wide.csv
```

Human corrections are stored separately:

```text
header_review.json
table_capture_result.json["header_review"]
```

The corrected dimensions affect only official/adjudicated outputs.

## 7. Official outputs are rematerialized after header review

The same immutable row/cell values are rebound to corrected column dimensions.

Regenerated:

```text
table_raw_long.csv
table_raw_wide.csv
table_item_dictionary.csv
table_capture.xlsx
```

No PDF re-extraction is required.

## 8. Boundary review and header review are composable

Boundary adjudication and header adjudication are independent.

Example:

```text
machine rows = 1..60
human boundary cutoff = 25

machine header scopes = incomplete
human header correction = 本集团 / 本公司
```

Official output becomes:

```text
rows 1..25
+
corrected year/scope/restated dimensions
```

Neither review overwrites the other.

## 9. Collision-safe machine wide output

Before header review, duplicated period labels are no longer silently collapsed by pivot.

Unsafe machine dimensions:

```text
2022
2021
2022
2021
```

are preserved as:

```text
2022 [col0]
2021 [col1]
2022 [col2]
2021 [col3]
```

This keeps every physical logical column visible for audit and review.

After correction:

```text
2022 本集团
2021 本集团
2022 本公司
2021 本公司
```

## 10. Long output gains explicit column identity

`table_raw_long.csv` now includes:

```text
column_ordinal
source_column_index
column_dimension_key
```

alongside:

```text
year
scope
restated
header_raw
```

This makes the source-column-to-value relationship auditable.

## 11. False VALUE_CONFLICT regression fixed

Test case:

```text
总计

2022 本集团 = 909041083
2021 本集团 = 987834923
2022 本公司 = 922826882
2021 本公司 = 992644880
```

Before header correction:

```text
header_dimension_status = REVIEW_REQUIRED
formal merge = BLOCKED
```

After header review:

```text
4 unique dimension windows
formal merge = READY
merge_conflicts.csv = empty
```

PASS.

## 12. Automatic hierarchical binding regression

Synthetic header:

```text
本集团                 本公司
2022  2021            2022  2021
```

automatically resolves:

```text
2022 本集团
2021 本集团
2022 本公司
2021 本公司
```

PASS.

## 13. Capture Library visibility

Capture Library now shows both:

```text
边界状态
表头维度状态
```

and whether the capture is merge-ready.

Blocked captures show explicit blockers such as:

```text
BOUNDARY:REVIEW_REQUIRED
HEADER:REVIEW_REQUIRED
```

## 14. Retained functionality

v5.5 retains all v5.4 functionality:

```text
canonical structural order
reference ordering table
小计/明细/合计 order preservation
ORDER_CONFLICT audit
Merge Library management
```

v5.3:

```text
output-based boundary review
machine vs official capture layers
Capture Library
```

v5.2:

```text
source evidence quality arbitration
custom CSV location/name
```

v5.1:

```text
Spatial ROI
numeric fragment reconstruction
complete Merge / Taxonomy workflow
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
