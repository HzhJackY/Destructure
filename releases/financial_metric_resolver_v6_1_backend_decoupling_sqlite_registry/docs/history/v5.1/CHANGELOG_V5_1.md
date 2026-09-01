# CHANGELOG v5.1

## P0 table-capture reconstruction
- Added `spatial_table_capture.py`.
- New default engine: `SPATIAL_ROI_V1`.
- Added exact named-note ROI using title y-coordinate.
- Added same-page next-note hard stop.
- Added TOC false-positive resistance using nearby table evidence.
- Added period-header x-anchor model.
- Logical column count now comes from table headers, not numeric fragments.
- Added numeric-fragment reconstruction within each column anchor.
- Added hard table-context reset at target note root.
- Added normalized x-anchor inheritance for continuation pages.
- Added explicit unknown-unit behavior: no magnitude-based guessing.
- Legacy table capture is fallback-only and is explicitly warned.

## Complete Merge workspace
- Added `table_merge.py`.
- Added Streamlit `合表` workspace.
- Added multi-capture source metadata editor.
- Added Canonical Table ID.
- Added immutable merge raw evidence layer.
- Added context-aware mapping key: parent_section + normalized_item.
- Added exact-identity auto alignment.
- Added fuzzy suggestion-only matching.
- Added human mapping editor.
- Added persistent `table_taxonomy.json`.
- Added taxonomy replay as `AUTO_TAXONOMY`.
- Added canonical section / item / category fields.
- Added RAW-preserved keys for unmapped items.
- Added canonical long / resolved long / canonical wide outputs.
- Added VALUE_CONFLICT and UNIT_CONFLICT gates.
- Conflicted keys are excluded from research wide.
- Added coverage report.
- Added merge Excel workbook and manifest.
- Added taxonomy snapshot.

## Retained
- v5.0 L0 additions:
  - 业务及管理费
  - 支付给职工以及为职工支付的现金
- v4.9 metric wide unit-column contract.
- v4.8 percentage and verified L0 alias fixes.
- v4.7 candidate value recovery and semantic safeguards.
