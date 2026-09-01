# Changelog

## v6.1 — Backend Decoupling + SQLite Metadata Registry

### Backend architecture
- Added SQLite metadata control plane at `DATA_HOME/metadata.db`.
- Added `MetadataRegistry` with WAL mode, foreign keys, indexed Capture/Batch/Merge/Job tables.
- Added Repository Layer for Captures, Batches, Merges, PDFs, and Jobs.
- Added Service Layer for Capture, Review, Asset, Batch, Merge, PDF, Registry, and Jobs.
- Added `backend_context.py` dependency container with no Streamlit dependency.
- Added headless `service_cli.py`.

### Metadata registry
- First v6.1 launch bootstraps existing DATA_HOME into SQLite once.
- Registry is rebuildable from filesystem evidence.
- New Capture/review/merge write paths include best-effort registry synchronization hooks.
- Added manual full-sync from UI and CLI.

### Data Asset Management
- Capture asset list now uses SQL-backed filtering and pagination.
- Dependency impact uses indexed `merge_sources` rather than rescanning every Merge for each selection.
- Batch main list excludes fully trashed batches.
- Added Batch aggregate status and dedicated Batch Trash view.
- Lifecycle operations use Service Layer and dual-write to legacy metadata/evidence + SQLite index.

### Job foundation
- Added persistent jobs table and `JobService`.
- Status contract: `QUEUED / RUNNING / SUCCESS / REVIEW_REQUIRED / FAILED / CANCELLED`.
- Heavy multi-PDF worker orchestration remains scheduled for the next workflow release.

### Project cleanup
- Historical per-version README/CHANGELOG files moved from project root to `docs/history/<version>/`.
- Root now uses consolidated `README.md` + `CHANGELOG.md`.
- Current guides live in `docs/current/`.

### Preserved
- v5.7 relative-period/wrapped-row fixes.
- v5.8 absolute-year resolution.
- v5.9 Classic + Generalized dual-header arbitration and topology review.
- v6.0 asset lifecycle, batch invalidation, stale Merge protection, and single-instance launcher.
- v6.0.1 Batch ID callback hotfix.

## v6.0.1
- Fixed Streamlit Session State exception when generating a new Capture Batch ID.

## v6.0
- Added Data Asset Management Center.
- Added Capture lifecycle: ACTIVE / INVALIDATED / TRASHED.
- Added bulk invalidation, trash/restore, batch rerun, Merge dependency stale marking.
- Added single-instance launcher and graceful restart/exit control.

## v5.9
- Added Classic + v5.7 Generalized dual-header parsers.
- Added independent numeric-column referee and parser arbitration.
- Fixed 4-real-column → 8-machine-column header regression.
- Added manual parser selection and safe KEEP/DROP topology review.

Older detailed notes are archived under `docs/history/`.
