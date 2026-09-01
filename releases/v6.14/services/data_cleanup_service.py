"""Old-data cleanup service for the System & Migration page.

Clears runtime/business records from the SQLite registry and archives
regenerated DATA_HOME artifacts into a timestamped backup directory.  The
registry schema, Research Definitions, table families/members, taxonomy/config,
Golden corpus and the ``metadata.db`` file itself are never touched.  A
confirmation token is mandatory and a full backup is created before any
deletion, so the operation is recoverable.
"""
from __future__ import annotations

import hashlib
import json
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


CLEANUP_CONFIRMATION_TOKEN = "DELETE-OLD-DATA"

# Supported cleanup scopes.
SCOPE_ALL = "all"
SCOPE_CAPTURE = "capture"
CLEANUP_SCOPES = (SCOPE_ALL, SCOPE_CAPTURE)

# Runtime/business tables cleared by the feature.  Foreign keys are disabled
# inside the single cleanup transaction, so ordering below is informational.
BUSINESS_TABLES: tuple[str, ...] = (
    "anchor_adjudications",
    "anchor_candidate_scores",
    "anchor_certification_audit",
    "anchor_child_concepts",
    "anchor_review_queue",
    "archive_operations",
    "asset_dependencies",
    "asset_status_transitions",
    "asset_tags",
    "block_adjudications",
    "candidate_evidence",
    "canonical_mapping_training_examples",
    "capture_batches",
    "capture_bundle_children",
    "capture_bundles",
    "capture_plan_items",
    "capture_plans",
    "capture_request_targets",
    "capture_requests",
    "capture_review_records",
    "capture_semantics",
    "capture_versions",
    "captures",
    "certified_child_table_links",
    "certified_child_table_segments",
    "certified_discoveries",
    "certified_note_table_inventories",
    "certified_note_targets",
    "child_discovery_runs",
    "child_inventory_adjudications",
    "child_inventory_resolution_cases",
    "child_logical_table_candidates",
    "child_mapping_review_queue",
    "child_mapping_review_records",
    "child_note_table_inventories",
    "child_table_link_candidates",
    "child_table_segment_candidates",
    "discovery_adjudications",
    "discovery_candidate_clusters",
    "discovery_training_examples",
    "downstream_stale_flags",
    "enriched_child_table_candidates",
    "financial_note_headings",
    "financial_note_indexes",
    "global_child_assignments",
    "golden_certifications",
    "jobs",
    "layout_evidence_cache",
    "logical_assets",
    "machine_discoveries",
    "merge_projects",
    "merge_sources",
    "ml_labels",
    "note_containers",
    "note_locator_training_examples",
    "reconciliation_relationships",
    "registry_events",
    "research_batch_members",
    "research_batches",
    "review_issues",
    "review_queue",
    "review_task_decisions",
    "review_tasks",
    "saved_asset_views",
    "saved_review_views",
    "stage_b_execution_sessions",
    "statement_note_edges",
    "statement_occurrences",
    "statement_scope_selections",
    "strategy_executions",
    "structural_learning_candidates",
    "structure_revisions",
    "structure_training_examples",
    "table_blocks",
    "table_notes",
    "thin_child_table_candidates",
)

# Registry configuration tables that are always preserved.
KEEP_TABLES: tuple[str, ...] = (
    "analysis_domains",
    "discovery_strategies",
    "domain_bridge_contracts",
    "family_members",
    "metric_family_mappings",
    "ml_label_schemas",
    "research_definition_audit",
    "research_definitions",
    "research_metrics",
    "schema_meta",
    "table_families",
)

# Capture-execution scope: everything downstream of certification (capture,
# jobs, plans, sessions, review of captures, merge products).  Certification
# records (occurrences, anchors, child candidates, inventories, certified
# links/segments/targets, discovery runs/indexes) are preserved.
CAPTURE_SCOPE_TABLES: tuple[str, ...] = (
    "archive_operations",
    "asset_dependencies",
    "asset_status_transitions",
    "asset_tags",
    "block_adjudications",
    "canonical_mapping_training_examples",
    "capture_batches",
    "capture_bundle_children",
    "capture_bundles",
    "capture_plan_items",
    "capture_plans",
    "capture_request_targets",
    "capture_requests",
    "capture_review_records",
    "capture_semantics",
    "capture_versions",
    "captures",
    "downstream_stale_flags",
    "jobs",
    "layout_evidence_cache",
    "logical_assets",
    "merge_projects",
    "merge_sources",
    "note_containers",
    "reconciliation_relationships",
    "registry_events",
    "research_batch_members",
    "research_batches",
    "review_issues",
    "review_queue",
    "review_task_decisions",
    "review_tasks",
    "saved_asset_views",
    "saved_review_views",
    "stage_b_execution_sessions",
    "strategy_executions",
    "structure_revisions",
    "structure_training_examples",
    "table_blocks",
    "table_notes",
)

# DATA_HOME artifact directories archived into the backup (regenerable).
ARCHIVE_DIR_KEYS: tuple[str, ...] = (
    "table_captures",
    "table_merges",
    "batch_runs",
    "runs",
    "reviews",
    "research_exports",
    "archive",
    "cache",
    "text_indexes",
    "asset_reports",
    "runtime",
    "migration_reports",
)

# DATA_HOME directories archived by the capture-only scope.
CAPTURE_SCOPE_DIR_KEYS: tuple[str, ...] = (
    "table_captures",
    "table_merges",
    "batch_runs",
    "runs",
    "reviews",
    "research_exports",
    "cache",
    "text_indexes",
    "asset_reports",
)


class DataCleanupService:
    """Read-only preview + backup-first cleanup of old research data."""

    def __init__(
        self,
        registry: Any,
        paths: dict[str, Path] | None = None,
        *,
        app_version: str = "",
    ) -> None:
        self.registry = registry
        self.paths = {str(key): Path(value) for key, value in (paths or {}).items()}
        self.app_version = str(app_version or "")

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _table_exists(conn: Any, table: str) -> bool:
        row = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
            (table,),
        ).fetchone()
        return bool(row)

    @staticmethod
    def _row_count(conn: Any, table: str) -> int:
        row = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()
        return int(row[0])

    @staticmethod
    def _sha256(path: Path) -> str:
        digest = hashlib.sha256()
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()

    @staticmethod
    def _file_count(directory: Path) -> int:
        if not directory.is_dir():
            return 0
        return sum(1 for _ in directory.rglob("*") if _.is_file())

    def _backup_dir(self, stamp: str) -> Path:
        return Path(self.paths.get("root", Path("."))) / "backup" / f"old_data_clear_{stamp}"

    def _registry_tables(
        self, *, scope: str = SCOPE_ALL, include_pdfs: bool,
    ) -> list[str]:
        if scope == SCOPE_CAPTURE:
            tables = list(CAPTURE_SCOPE_TABLES)
        else:
            tables = list(BUSINESS_TABLES)
        if include_pdfs:
            tables.append("pdf_assets")
        return tables

    def _dir_keys(
        self, *, scope: str = SCOPE_ALL, include_pdfs: bool,
    ) -> list[str]:
        keys = (
            list(CAPTURE_SCOPE_DIR_KEYS)
            if scope == SCOPE_CAPTURE
            else list(ARCHIVE_DIR_KEYS)
        )
        if include_pdfs:
            keys.append("uploads")
        return keys

    # ------------------------------------------------------------------
    # Read-only preview
    # ------------------------------------------------------------------

    def preview(
        self,
        *,
        scope: str = SCOPE_ALL,
        include_pdfs: bool = False,
    ) -> dict[str, Any]:
        """Return registry row counts and DATA_HOME file counts without writes."""
        if scope not in CLEANUP_SCOPES:
            raise ValueError(f"UNKNOWN_CLEANUP_SCOPE:{scope}")
        registry_rows: dict[str, int] = {}
        with self.registry.connect() as conn:
            for table in self._registry_tables(
                scope=scope, include_pdfs=include_pdfs,
            ):
                if self._table_exists(conn, table):
                    count = self._row_count(conn, table)
                    if count:
                        registry_rows[table] = count
        dir_files: dict[str, int] = {}
        for key in self._dir_keys(scope=scope, include_pdfs=include_pdfs):
            directory = self.paths.get(key)
            if directory is None:
                continue
            count = self._file_count(directory)
            if count:
                dir_files[key] = count
        return {
            "registry_rows": registry_rows,
            "dir_files": dir_files,
            "scope": scope,
            "include_pdfs": bool(include_pdfs),
            "read_only": True,
        }

    # ------------------------------------------------------------------
    # Backup
    # ------------------------------------------------------------------

    def create_backup(
        self,
        *,
        scope: str = SCOPE_ALL,
        include_pdfs: bool = False,
    ) -> dict[str, Any]:
        """Copy the SQLite DB and manifest into a timestamped backup directory."""
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        backup_dir = self._backup_dir(stamp)
        candidate = backup_dir
        index = 0
        while candidate.exists():
            index += 1
            candidate = backup_dir.with_name(f"{backup_dir.name}_{index}")
        backup_dir = candidate
        backup_dir.mkdir(parents=True)
        db_path = Path(self.registry.db_path)
        db_backup = backup_dir / db_path.name
        shutil.copy2(db_path, db_backup)
        manifest_src = self.paths.get("manifest")
        manifest_copy = ""
        if manifest_src and manifest_src.is_file():
            manifest_copy = str(backup_dir / "data_manifest.json")
            shutil.copy2(manifest_src, manifest_copy)
        payload = {
            "stamp": stamp,
            "app_version": self.app_version,
            "scope": scope,
            "include_pdfs": bool(include_pdfs),
            "backup_dir": str(backup_dir),
            "database": str(db_backup),
            "database_sha256": self._sha256(db_backup),
            "data_manifest": manifest_copy,
        }
        (backup_dir / "backup_manifest.json").write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        return payload

    # ------------------------------------------------------------------
    # Registry clear
    # ------------------------------------------------------------------

    def clear_registry(
        self,
        *,
        scope: str = SCOPE_ALL,
        include_pdfs: bool = False,
    ) -> dict[str, int]:
        """Delete all rows from business tables in one recoverable transaction."""
        tables = self._registry_tables(scope=scope, include_pdfs=include_pdfs)
        deleted: dict[str, int] = {}
        with self.registry.connect() as conn:
            conn.execute("PRAGMA foreign_keys=OFF")
            conn.execute("BEGIN")
            try:
                for table in tables:
                    if not self._table_exists(conn, table):
                        continue
                    count = self._row_count(conn, table)
                    if count:
                        conn.execute(f"DELETE FROM {table}")
                    deleted[table] = count
                conn.execute("COMMIT")
            except Exception:
                conn.execute("ROLLBACK")
                raise
            finally:
                conn.execute("PRAGMA foreign_keys=ON")
        return deleted

    # ------------------------------------------------------------------
    # DATA_HOME archive
    # ------------------------------------------------------------------

    def archive_dirs(
        self,
        *,
        scope: str = SCOPE_ALL,
        include_pdfs: bool = False,
        backup_dir: Path | None = None,
    ) -> dict[str, Any]:
        """Move regenerable DATA_HOME dirs into the backup, recreating empties."""
        if backup_dir is None:
            backup_dir = self._backup_dir(
                datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
            )
            backup_dir.mkdir(parents=True, exist_ok=True)
        archived: dict[str, Any] = {}
        for key in self._dir_keys(scope=scope, include_pdfs=include_pdfs):
            source = self.paths.get(key)
            if source is None or not source.exists():
                continue
            files = self._file_count(source)
            target = backup_dir / "archived" / source.name
            if target.exists():
                target = backup_dir / "archived" / f"{source.name}_{key}"
            try:
                shutil.move(str(source), str(target))
                source.mkdir(parents=True, exist_ok=True)
                archived[key] = {
                    "source": str(source),
                    "target": str(target),
                    "files": files,
                }
            except Exception as exc:  # keep the cleanup resilient per directory
                archived[key] = {
                    "source": str(source),
                    "target": str(target),
                    "files": files,
                    "error": f"{type(exc).__name__}:{exc}",
                }
        return {"backup_dir": str(backup_dir), "archived": archived}

    # ------------------------------------------------------------------
    # Orchestrated cleanup
    # ------------------------------------------------------------------

    def run_cleanup(
        self,
        *,
        confirmation: str = "",
        scope: str = SCOPE_ALL,
        include_pdfs: bool = False,
    ) -> dict[str, Any]:
        """Require the confirmation token, back up, clear and archive."""
        if confirmation != CLEANUP_CONFIRMATION_TOKEN:
            raise PermissionError("DATA_CLEANUP_CONFIRMATION_REQUIRED")
        if scope not in CLEANUP_SCOPES:
            raise ValueError(f"UNKNOWN_CLEANUP_SCOPE:{scope}")
        preview = self.preview(scope=scope, include_pdfs=include_pdfs)
        backup = self.create_backup(scope=scope, include_pdfs=include_pdfs)
        deleted = self.clear_registry(scope=scope, include_pdfs=include_pdfs)
        archived = self.archive_dirs(
            scope=scope,
            include_pdfs=include_pdfs,
            backup_dir=Path(backup["backup_dir"]),
        )
        report = {
            "confirmation_token_matched": True,
            "scope": scope,
            "include_pdfs": bool(include_pdfs),
            "preview": preview,
            "backup": backup,
            "registry_tables_deleted": deleted,
            "archived_dirs": archived,
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        report_path = Path(backup["database"]).parent / "cleanup_report.json"
        report_path.write_text(
            json.dumps(report, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        report["report_path"] = str(report_path)
        return report
