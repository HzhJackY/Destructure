# CHANGELOG v5.0

## New: Table Capture MVP
- Added `table_capture.py`.
- Added Streamlit workspace `整表抓取`.
- Added named note/table location by title and optional note number.
- Added manual start-page override and bounded max-page range.
- Added table-block selection with numeric-shape continuity.
- Added multi-level header parser.
- Added shifted/missing blank-header-cell correction.
- Added `year`, `scope`, and `restated` column dimensions.
- Added row hierarchy:
  - SECTION_HEADER
  - DETAIL
  - SUBTOTAL
  - TOTAL
  - CLASSIFICATION_TOTAL
- Added `parent_section`, `row_level`, `row_order`.
- Added raw detail-label preservation.
- Added deterministic `normalized_item`.
- Added mapping-ready `canonical_item/category` dictionary without forced semantic merges.
- Added cross-page header provenance support for table capture.
- Added outputs:
  - table_capture_result.json
  - table_raw_long.csv
  - table_raw_wide.csv
  - table_item_dictionary.csv
  - table_report.md
  - table_report.html
  - table_capture.xlsx
- Added historical table-capture downloads in GUI.

## L0 additions
- Added standard metric `业务及管理费`.
- Added strong aliases `业务及管理费用`, `业务管理费`.
- Added exclusions to prevent full-note/detail-title confusion.
- Added standard metric `支付给职工以及为职工支付的现金`.
- Added strong aliases:
  - 支付给职工及为职工支付的现金
  - 支付给职工以及为职工支付现金
- Explicitly avoids treating `职工工资及福利费`, `职工薪酬`, `应付职工薪酬` as strong aliases.

## Retained
- All v4.9 wide-unit-column and cross-page context behavior.
- All v4.8 percentage and verified L0 alias fixes.
- All v4.7 semantic/value-recovery protections.
