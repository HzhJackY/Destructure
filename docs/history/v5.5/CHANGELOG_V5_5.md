# CHANGELOG v5.5

## P0: Hierarchical Header Dimensions
- Fixed parent-level header binding for `本集团 / 本公司`.
- Parent headers can now span multiple child year columns.
- Header parser now inspects bounded rows above and below the year header.
- Added spatial parent-header propagation across logical column anchors.

## Header Dimension Safety Gate
- Added `analyze_column_dimensions`.
- Added `column_dimension_key = year|scope|restated`.
- Added:
  - `DUPLICATE_PERIOD_WITHOUT_COMPLETE_SCOPE`
  - `HEADER_DIMENSION_COLLISION`
  - `MISSING_PERIOD_DIMENSION`
- Added `header_dimension_status`:
  - AUTO_CONFIRMED
  - HUMAN_CONFIRMED
  - REVIEW_REQUIRED
- Formal Merge now requires both boundary readiness and header-dimension readiness.

## Header Dimension Review
- Added `header_review.py`.
- Added `表头维度复核` UI for current and historical captures.
- Editable:
  - year
  - scope
  - restated
- Added `header_review.json`.
- Machine header evidence remains immutable.
- Official CSV/Excel rematerializes without PDF re-extraction.
- Boundary and header reviews compose safely.

## Output Safety
- Added to long output:
  - column_ordinal
  - source_column_index
  - column_dimension_key
- Duplicate unresolved period columns in wide output receive physical suffixes:
  - `[col0]`
  - `[col1]`
  etc.
- Prevents pivot from silently collapsing unresolved data windows.
- Excel after adjudication includes:
  - machine_headers
  - effective_headers

## Capture Library / Merge Gate
- Capture Library displays header-dimension status.
- Merge blockers now distinguish:
  - BOUNDARY:<status>
  - HEADER:<status>
- Header-collision captures cannot enter formal Merge.

## Regression
- Reproduced 2022/2021 本集团 + 2022/2021 本公司 false VALUE_CONFLICT.
- Confirmed header review produces four unique scope/year windows.
- Confirmed `merge_conflicts.csv` is empty after correct scope binding.
- Confirmed hierarchical parent span auto-binding.
