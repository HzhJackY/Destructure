# CHANGELOG v5.2

## Source Quality Arbitration
- Split candidate evaluation into semantic score and evidence quality.
- Added `evidence_quality` to Candidate.
- Added `arbitration_score` to Candidate.
- Added detailed evidence-quality components.
- Unit completeness and unit/value-type compatibility now materially affect source selection.
- Period/header completeness now affects source selection.
- Structured source-method quality now affects tie-breaking.
- Exact-label candidates are ranked by evidence quality instead of saturated rule score alone.
- Added auditable exact-selection reason with quality comparison.
- L2 payload now includes semantic/evidence/arbitration scores.
- DeepSeek/Gemini prompts now prefer complete evidence among semantically equivalent candidates.
- Human review candidate table now shows:
  - semantic score
  - evidence quality
  - arbitration score
  - unit completeness
  - period/header completeness
- Markdown/HTML reports now expose the three-score model.

## Custom CSV Export
- Added `export_utils.py`.
- Added direct filesystem CSV export with:
  - custom directory
  - custom filename
  - automatic `.csv` extension
  - directory creation
  - overwrite protection
- Added custom export UI for:
  - batch final wide/long
  - batch machine wide/long
  - table-capture raw long/wide/item dictionary
  - merge raw/mapping/canonical/resolved/conflict/coverage CSVs
- Browser download buttons are retained.

## Retained
- All v5.1 Spatial Table Capture and Merge functionality.
- All earlier extraction/review/audit protections.
