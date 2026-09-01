# CHANGELOG v6.0

## Data Asset Management Center
- Added top-level `数据资产管理` workspace.
- Historical management removed from the `整表抓取` sub-section.
- Added central tabs:
  - Captures
  - Batches
  - Merges
  - PDF
  - Recycle Bin

## Capture Lifecycle
- Added:
  - ACTIVE
  - INVALIDATED
  - TRASHED
- Added invalidation metadata:
  - invalidated_at
  - invalidation_reason_code
  - invalidation_note
- Added predefined reason codes.
- INVALIDATED Captures remain auditable but cannot enter formal Merge.

## Bulk Capture Management
- Added multi-select table.
- Added select-all-filtered-results behavior.
- Added filters for:
  - lifecycle
  - table
  - company
  - document year
  - producer version
- Added bulk:
  - invalidate
  - reactivate
  - move to trash
  - re-capture

## Batch Lifecycle
- Added `batch_id` to new Capture metadata.
- Added optional batch ID input to `整表抓取`.
- Added generated batch IDs.
- Added Batch aggregation view.
- Added whole-batch:
  - invalidation
  - rerun
  - trash

## Re-Capture / Supersession
- Added batch re-capture from original PDFs.
- New Captures do not overwrite old ones.
- Added:
  - supersedes_capture_id
  - superseded_by_capture_id

## Merge Dependency Protection
- Capture invalidation/trash scans Merge manifests.
- Dependent Merge metadata becomes:
  - STALE_SOURCE_INVALIDATED
- Added stale_capture_run_ids.
- Added dependency refresh command.
- Added stale missing-source detection.

## Formal Merge Lifecycle Gate
- `table_merge.load_capture_long()` blocks non-ACTIVE Capture sources.
- New hard error:
  - CAPTURE_LIFECYCLE_BLOCKED

## Recycle Bin
- Added batch Capture restore/purge.
- Added batch Merge restore/purge.
- Capture restore preserves pre-trash lifecycle when possible.

## PDF Asset View
- Added source PDF inventory with Capture reference counts.
- Source PDF bulk hard-delete intentionally not exposed by default.

## Single-Instance Launcher
- Added `launcher.py`.
- `run_gui.bat` and `run_gui.ps1` now use launcher.py.
- Added active instance registry:
  - DATA_HOME/runtime/active_instance.json
- Added token-authenticated control channel:
  - DATA_HOME/runtime/control.json
- Added safe previous-instance shutdown.
- Added validated port-owner cleanup for older directly launched versions.
- Never uses `taskkill python.exe`.
- Unrelated Streamlit/Python processes are not terminated.
- Falls back to another free port when the default port is owned by unrelated software.

## GUI Runtime Controls
- Added sidebar:
  - Restart
  - Exit
- Launcher owns child-process shutdown/restart.
- Direct Streamlit mode shows a warning rather than force-killing itself.

## Shared DATA_HOME
- Data schema version bumped to 6.0.
- Added:
  - runtime/
  - asset_reports/

## Regression
- v5.9 parser regression corpus remains PASS.
- Added tests/regression_v60.py.
- PASS:
  - BATCH_GROUPING_PASS
  - DEPENDENCY_IMPACT_PASS
  - BULK_INVALIDATE_AND_STALE_MERGE_PASS
  - INVALIDATED_MERGE_GATE_PASS
  - REACTIVATE_DEPENDENCY_REFRESH_PASS
  - TRASH_RESTORE_LIFECYCLE_PASS
  - SINGLE_INSTANCE_PID_VALIDATION_PASS
  - ALL_V60_ASSET_TESTS_PASS
