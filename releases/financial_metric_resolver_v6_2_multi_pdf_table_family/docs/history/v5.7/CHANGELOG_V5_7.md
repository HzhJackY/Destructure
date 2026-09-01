# CHANGELOG v5.7

## P0: Relative-Period Header Support
- Added recognition for:
  - 本年累计数 / 上年累计数
  - 本期累计数 / 上期累计数
  - 本期 / 上期
  - 本年 / 上年
  - 当期
  - 期末 / 期初
- Added adjacent-word reconstruction for split period labels.
- Added support for relative-period labels with restated/unit suffixes.
- `_detect_header` now uses general period anchors rather than four-digit years only.
- Repeated unit rows such as `人民币元` extend the header band and are not materialized as data.

## Header Dimension / Merge Period Resolution
- Relative periods remain faithful in Capture evidence.
- Added `period_label` to long output.
- Added `source_period_label` in Merge.
- When `document_year` is known:
  - 本年/本期/current -> document_year
  - 上年/上期/prior -> document_year - 1
- Scope dimensions remain independent:
  - 本集团
  - 本公司

## No-Note-Number Locator Fix
- Relative-period headers now count as strong body-table evidence.
- Fixed TOC-vs-body selection for tables without four-digit year headers.
- Fixed ROI title candidate accidentally swallowing the next parent-header line.
- Added conservative title containment compatibility for cross-company naming differences.

## Wrapped Row Structure Fix
- Same-indent text-only accounting rows with blank values remain `DETAIL`.
- Explicit structural markers (`减:`, `加:`, `按费用项目:`) remain `SECTION_HEADER`.
- Indented continuation lines are merged into wrapped accounting labels.
- Examples:
  - 当期发生的保费获取 + 现金流
  - 当期发生的其他保险 + 履约现金流
- Final TOTAL after +/- section returns to top-level hierarchy.

## Reconciliation v2
- Reconciliation schema version bumped to 2.
- Fixed trailing subtotal membership after blank-value detail rows.
- Added:
  - BASE_MINUS_COMPONENTS
  - BASE_PLUS_COMPONENTS
- Added audit fields:
  - component_operators
  - formula_expression
- Example:
  - 合计 = 小计 - 获取现金流 - 履约现金流
- Missing component values produce warning-only ambiguity; never implicit zero.

## Diagnostics
- If spatial and legacy table capture both fail, error now reports both causes.
- Prevents legacy fallback error from hiding the original spatial failure.

## Regression
- Reproduced reported relative-period insurance expense table.
- Verified no-note-number body location over TOC.
- Verified 4 logical columns:
  - 本年累计数 本集团
  - 上年累计数 本集团
  - 本年累计数 本公司
  - 上年累计数 本公司
- Verified blank `租赁费` remains detail.
- Verified wrapped deduction labels.
- Verified subtotal child membership.
- Verified `小计 - 两个减项 = 合计`.
- Verified Merge resolves relative periods to absolute years.
