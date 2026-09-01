# CHANGELOG v5.8

## P0: Absolute Year Resolution
- Relative period labels can no longer remain as canonical `year`.
- Added conversion:
  - 本年 / 本期 / 本年累计数 / 本期累计数 → document_year
  - 去年 / 上年 / 上期 / 去年累计数 / 上年累计数 → document_year - 1
- Preserves original source wording in `source_period_label`.

## Root Cause Fix
- Fixed `infer_capture_metadata` using lexical `max()` over relative period labels.
- `document_year` now accepts only absolute four-digit year evidence.
- Relative labels are never eligible as document identity.

## `去年` Support
- Added:
  - 去年
  - 去年累计数
  - 去年数
  - 去年同期
- Spatial header parser now recognizes `去年/去年累计数` as PRIOR period labels.

## Merge Safety Gate
- Added `PERIOD_RESOLUTION_REQUIRED`.
- Added `PERIOD_RESOLUTION_INVARIANT_VIOLATION`.
- Formal canonicalization is blocked if relative `year` labels remain unresolved.

## Existing v5.7 Merge Repair
- Every Merge rematerialization now repairs period dimensions from manifest/source metadata.
- Repairs:
  - document_year
  - year
  - column_dimension_key
- Existing v5.7 `merge_raw_long.csv` can be corrected by rematerialization.
- Added manifest policy:
  - RELATIVE_PERIOD_TO_ABSOLUTE_YEAR_BEFORE_CANONICAL_MERGE

## GUI
- Added explicit four-digit document_year guidance.
- Added explanation of relative→absolute year mapping.

## Regression
- 2022 本年累计数/上年累计数 → 2022/2021 PASS.
- 2023 本年累计数/去年累计数 → 2023/2022 PASS.
- Old v5.7 relative-year Merge auto-repair PASS.
- Missing document_year hard gate PASS.
- Spatial 去年累计数 token recognition PASS.
