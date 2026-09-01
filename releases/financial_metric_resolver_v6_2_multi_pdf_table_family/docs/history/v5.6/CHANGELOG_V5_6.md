# CHANGELOG v5.6

## Shared DATA_HOME
- Separated code versions from persistent historical data.
- Added `data_home.py`.
- Default shared repository: `~/FinancialMetricResolverData`.
- Added stable global pointer:
  - `~/.financial_metric_resolver/data_home.json`
- Added `FIN_METRIC_DATA_HOME` environment override.
- Runtime L0 rules moved to shared `DATA_HOME/config/metric_aliases.json`.
- Runtime Table Taxonomy moved to shared `DATA_HOME/config/table_taxonomy.json`.
- Added `data_manifest.json` with data schema provenance.
- `batch_cli.py` now defaults to shared rules/cache/output paths.

## Historical Migration Center
- Added `migration_center.py`.
- Added GUI `数据管理 / 历史版本迁移`.
- Supports old app-root or direct workspace path.
- Migrates:
  - PDFs
  - Captures
  - boundary/header adjudications
  - batch runs
  - single runs
  - reviews
  - rule backups
- Conservatively merges:
  - Table Taxonomy
  - metric_aliases
- Preserves capture/merge recycle-bin history.
- Old Merge Projects are archived as `ARCHIVED_REBUILD_RECOMMENDED`.
- Cache is intentionally skipped.
- Added machine-readable `migration_report.json`.

## Schema Provenance
- New Capture JSON:
  - producer_version=v5.6
  - capture_schema_version=5.6
  - reconciliation_schema_version=1
- New Merge manifest:
  - version=v5.6
  - merge_schema_version=5.6

## Auto Note Number Inference
- Added `AUTO_NOTE_NUMBER_INFERENCE_FROM_LOCATED_TITLE`.
- Blank note number can be inferred from located headings such as:
  - `34. 标题`
  - `34．标题`
  - `34、标题`
  - `34 标题`
- Records:
  - resolved_note_number
  - note_number_source
- Uses inferred `n+1` note as hard end boundary.
- Added spatial heading-alignment guard against numeric-row false boundaries.
- Legacy fallback locator also gains note-number inference.

## Conditional parent_section Identity
- `parent_section` is no longer always part of source identity.
- If an item is unique inside a source:
  - key = `UNIQUE||item`
- If the same item appears multiple times in one source:
  - key = `CONTEXT||item||parent_section||row_type||occurrence`
- Prevents harmless parent-section parser differences from blocking same-name merges.
- Preserves safety for true same-source repeated labels.
- Added backward-compatible lookup for unambiguous legacy taxonomy keys.

## Total/Subtotal Reconciliation Audit
- Added `reconciliation.py`.
- Added:
  - `table_reconciliation_audit.csv`
  - `merge_reconciliation_audit.csv`
- Added Excel `reconciliation` sheets.
- Supports structural patterns:
  - TRAILING_TOTAL
  - LEADING_PARENT_TOTAL
- Membership is inferred from structure first.
- Arithmetic is validation-only.
- Statuses:
  - PASS_EXACT
  - PASS_ROUNDING
  - WARNING_SUM_MISMATCH
  - WARNING_COMPONENT_SCOPE_AMBIGUOUS
  - NOT_TESTABLE_*
- Warning-only: never modifies data or automatically blocks canonical output.
- GUI review added to current Capture, Capture Library, and Merge Project.

## Retained
- v5.5 hierarchical header dimensions and header review.
- v5.4 canonical structural ordering and Merge Library.
- v5.3 boundary review and Capture Library.
- v5.2 evidence-quality arbitration and custom CSV export.
- v5.1 Spatial ROI and complete Taxonomy Merge workflow.
