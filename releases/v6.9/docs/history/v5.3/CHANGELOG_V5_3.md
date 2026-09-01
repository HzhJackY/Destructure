# CHANGELOG v5.3

## Boundary Review Workflow
- Added real table-boundary human adjudication.
- Review is performed directly from extracted output.
- Reviewer chooses the last valid `row_order`.
- Added context preview around cutoff.
- Added reviewer note.
- Added `HUMAN_CONFIRMED` boundary status.
- Added `boundary_review.json`.
- Added `boundary_excluded_rows.csv`.
- Official table outputs are rematerialized after review.
- Machine-full extraction is immutable.
- Added reset/re-adjudicate workflow.
- Added merge-readiness boundary gate.

## Machine vs Official Capture Layers
- Added:
  - `machine_capture_full_long.csv`
  - `machine_capture_full_wide.csv`
- Official:
  - `table_raw_long.csv`
  - `table_raw_wide.csv`
  - `table_item_dictionary.csv`
- Excel now includes machine-full and excluded-boundary sheets.

## Capture Library
- Added source-aware automatic run names:
  - original PDF
  - note/table
  - timestamp
- Added `capture_metadata.json`.
- Added library overview table.
- Added display-name editing.
- Added notes.
- Added official/machine preview.
- Added PDF start/end page preview.
- Added historical boundary review.
- Added soft delete.
- Added recycle bin.
- Added restore.
- Added permanent delete with confirmation.

## Merge Gate
- Formal merge only lists boundary-confirmed captures.
- REVIEW_REQUIRED captures are displayed separately and blocked from merge.
- Supported merge-ready statuses:
  - HARD_BOUNDARY_CONFIRMED
  - AUTO_HIGH_CONFIDENCE
  - HUMAN_CONFIRMED

## Retained
- v5.2 source-quality arbitration and custom CSV export.
- v5.1 spatial capture and complete Merge/Taxonomy workflow.
