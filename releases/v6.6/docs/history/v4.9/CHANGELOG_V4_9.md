# CHANGELOG v4.9

## Wide-table output
- Replaced v4.8 synthetic unit rows with a dedicated `unit` column.
- Wide contract is now `metric | unit | company-year...`.
- Removed generation of `machine_wide_values_only.csv`.
- Removed generation of `adjudicated_wide_values_only.csv`.
- Removed values-only Excel sheets.
- Excel now contains five sheets:
  - machine_long
  - machine_wide
  - adjudicated_long
  - adjudicated_wide
  - review_log
- Added mixed-unit guard: `REVIEW_REQUIRED[unit1|unit2]`.

## Cross-page table context
- Added cross-page period-header propagation.
- Added cross-page unit propagation.
- Added cross-page table-type propagation.
- Added conservative continuation scoring.
- Rejects inheritance when the current page has a new explicit table/header.
- Added `inherited_period_headers` to PDFBlock.
- Added `header_source_page` provenance.
- Added `context_inheritance_confidence`.
- Candidate / LLM payloads now retain cross-page header provenance.
- Human review shows header source page.
- Fast Index always includes immediate predecessor pages as context pages.
- Cross-page propagation is re-run after cached/new block merging.

## Retained
- v4.8 percent conversion fix.
- verified L0 alias writeback.
- v4.7 Candidate Value Recovery.
- v4.6 batch identity/review/report fixes.
