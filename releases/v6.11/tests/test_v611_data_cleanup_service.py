"""v6.11 old-data cleanup service contracts (System & Migration page)."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from metadata_registry import MetadataRegistry, now_iso  # noqa: E402
from services.data_cleanup_service import (  # noqa: E402
    CLEANUP_CONFIRMATION_TOKEN,
    SCOPE_CAPTURE,
    DataCleanupService,
)


def _paths(tmp_path: Path) -> dict[str, Path]:
    names = (
        "root", "uploads", "runs", "rule_backups", "reviews", "cache",
        "batch_runs", "table_captures", "table_capture_trash", "table_merges",
        "merge_trash", "config", "archive", "migration_reports", "runtime",
        "asset_reports", "text_indexes", "research_exports", "metadata_db",
        "manifest",
    )
    paths = {name: tmp_path / name for name in names}
    for path in paths.values():
        path.mkdir(parents=True, exist_ok=True)
    return paths


def _seed(registry: MetadataRegistry) -> None:
    now = now_iso()
    with registry.connect() as conn:
        conn.execute(
            """INSERT INTO research_definitions(
               definition_id, display_name, definition_version, payload_json,
               status, created_at, updated_at)
               VALUES('RD_FIXTURE','测试定义','V1','{}','ACTIVE',?,?)""",
            (now, now),
        )
        conn.execute(
            """INSERT INTO table_families(
               family_id, display_name, definition_version, discovery_strategy,
               payload_json, archived, created_at, updated_at)
               VALUES('TF_FIXTURE','测试族','V1',
                      'DIRECT_NOTE_TABLE_FAMILY','{}',0,?,?)""",
            (now, now),
        )
        conn.execute(
            "INSERT INTO schema_meta(key, value, updated_at) VALUES('k','v',?)",
            (now,),
        )
        conn.execute(
            """INSERT INTO statement_occurrences(
               occurrence_id, pdf_id, company, report_year, display_name,
               table_family, parent_text, child_rows_json, status,
               evidence_json, created_at)
               VALUES('OCC_FIXTURE','PDF::fixture','测试公司','2023',
                      '金融投资','financial_investment','','[]',
                      'ANCHOR_CERTIFIED','{}',?)""",
            (now,),
        )
        conn.execute(
            """INSERT INTO capture_plans(
               plan_id, pdf_id, table_family, status, payload_json,
               created_at, updated_at, archived)
               VALUES('PLAN_FIXTURE','PDF::fixture','金融投资','CERTIFIED',
                      '{}',?,?,0)""",
            (now, now),
        )
        conn.execute(
            """INSERT INTO jobs(
               job_id, batch_id, job_type, status, progress, created_at,
               updated_at)
               VALUES('JOB_FIXTURE','BATCH_FIXTURE','CAPTURE','SUCCESS',1.0,?,?)""",
            (now, now),
        )
        conn.execute(
            """INSERT INTO captures(
               capture_id, run_path, lifecycle_status, merge_ready,
               is_trashed, updated_at)
               VALUES('CAP_FIXTURE','C:/tmp/capture','ACTIVE',0,0,?)""",
            (now,),
        )
        conn.execute(
            """INSERT INTO certified_child_table_links(
               certified_link_id, anchor_id, anchor_child_id, candidate_id,
               link_candidate_id, table_family_id, member_table_id,
               subtable_role, relation_type, statement_scope,
               certification_method, certification_status,
               score_snapshot_json, evidence_snapshot_json,
               reconciliation_result_json, selected_candidate_id,
               alternative_candidates_json, reviewer, certified_at,
               producer_version, logical_table_id, table_classification,
               segment_manifest_status, note_table_inventory_id,
               note_table_inventory_status)
               VALUES('CLINK_FIXTURE','OCC_FIXTURE','ACHILD_FIXTURE',
                      'TCAND_FIXTURE','LKC_FIXTURE','financial_investment',
                      'debt_investment','NOTE_DETAIL','STATEMENT_TO_NOTE',
                      'CONSOLIDATED','AUTO','CERTIFIED','{}','{}','{}',
                      'TCAND_FIXTURE','[]','SYSTEM_RULE_ENGINE',?,
                      'v6.11-test','LTCAND_FIXTURE','PRIMARY_TABLE',
                      'CERTIFIED_SEGMENT_MANIFEST','CINV_FIXTURE','COMPLETE')""",
            (now,),
        )
        conn.execute(
            """INSERT INTO pdf_assets(
               pdf_id, filename, created_at, updated_at)
               VALUES('PDF::fixture','fixture.pdf',?,?)""",
            (now, now),
        )


def _seed_files(tmp_path: Path) -> None:
    (tmp_path / "table_captures" / "a.csv").write_text("a", encoding="utf-8")
    (tmp_path / "table_merges" / "b.csv").write_text("b", encoding="utf-8")
    (tmp_path / "cache" / "c.bin").write_bytes(b"c")
    (tmp_path / "reviews" / "r.json").write_text("{}", encoding="utf-8")
    (tmp_path / "uploads" / "d.pdf").write_bytes(b"d")


def _service(tmp_path: Path):
    registry = MetadataRegistry(tmp_path / "metadata.db")
    paths = _paths(tmp_path)
    _seed(registry)
    _seed_files(tmp_path)
    service = DataCleanupService(registry, paths, app_version="v6.11-test")
    return registry, paths, service


def test_preview_is_read_only_and_reports_rows_and_files(tmp_path: Path):
    registry, _, service = _service(tmp_path)
    preview = service.preview()

    assert preview["read_only"] is True
    assert preview["registry_rows"]["statement_occurrences"] == 1
    assert preview["registry_rows"]["capture_plans"] == 1
    assert preview["registry_rows"]["jobs"] == 1
    assert preview["dir_files"]["table_captures"] == 1
    assert "uploads" not in preview["dir_files"]
    pdf_preview = service.preview(include_pdfs=True)
    assert pdf_preview["dir_files"]["uploads"] == 1
    assert pdf_preview["registry_rows"]["pdf_assets"] == 1
    with registry.connect() as conn:
        assert conn.execute(
            "SELECT COUNT(*) FROM statement_occurrences"
        ).fetchone()[0] == 1


def test_run_cleanup_requires_confirmation_token(tmp_path: Path):
    _, _, service = _service(tmp_path)
    with pytest.raises(PermissionError, match="DATA_CLEANUP_CONFIRMATION_REQUIRED"):
        service.run_cleanup(confirmation="", include_pdfs=False)
    with pytest.raises(PermissionError, match="DATA_CLEANUP_CONFIRMATION_REQUIRED"):
        service.run_cleanup(confirmation="WRONG", include_pdfs=False)


def test_run_cleanup_clears_business_rows_keeps_config_and_backs_up(
    tmp_path: Path,
):
    registry, paths, service = _service(tmp_path)
    with registry.connect() as conn:
        keep_before = {
            table: conn.execute(
                f"SELECT COUNT(*) FROM {table}"
            ).fetchone()[0]
            for table in (
                "research_definitions", "table_families", "schema_meta",
            )
        }
    report = service.run_cleanup(
        confirmation=CLEANUP_CONFIRMATION_TOKEN,
        include_pdfs=False,
    )

    with registry.connect() as conn:
        business = {
            table: conn.execute(
                f"SELECT COUNT(*) FROM {table}"
            ).fetchone()[0]
            for table in (
                "statement_occurrences", "capture_plans", "jobs",
            )
        }
        keep = {
            table: conn.execute(
                f"SELECT COUNT(*) FROM {table}"
            ).fetchone()[0]
            for table in (
                "research_definitions", "table_families", "schema_meta",
            )
        }
        pdf_rows = conn.execute(
            "SELECT COUNT(*) FROM pdf_assets"
        ).fetchone()[0]
    assert business == {
        "statement_occurrences": 0,
        "capture_plans": 0,
        "jobs": 0,
    }
    assert keep == keep_before
    assert pdf_rows == 1

    backup_dir = Path(report["backup"]["database"]).parent
    assert backup_dir.is_dir()
    assert (backup_dir / "metadata.db").is_file()
    assert (backup_dir / "backup_manifest.json").is_file()
    assert (backup_dir / "cleanup_report.json").is_file()
    assert report["backup"]["database_sha256"]
    assert (backup_dir / "archived" / "table_captures" / "a.csv").is_file()
    assert (backup_dir / "archived" / "table_merges" / "b.csv").is_file()
    assert (backup_dir / "archived" / "cache" / "c.bin").is_file()
    # Source dirs are recreated empty so the app remains fully functional.
    assert (paths["table_captures"]).is_dir()
    assert not list((paths["table_captures"]).iterdir())
    assert not list((paths["table_merges"]).iterdir())


def test_run_cleanup_include_pdfs_clears_uploads_and_pdf_assets(
    tmp_path: Path,
):
    registry, paths, service = _service(tmp_path)
    report = service.run_cleanup(
        confirmation=CLEANUP_CONFIRMATION_TOKEN,
        include_pdfs=True,
    )
    with registry.connect() as conn:
        assert conn.execute(
            "SELECT COUNT(*) FROM pdf_assets"
        ).fetchone()[0] == 0
    backup_dir = Path(report["backup"]["database"]).parent
    assert (backup_dir / "archived" / "uploads" / "d.pdf").is_file()
    assert (paths["uploads"]).is_dir()
    assert not list((paths["uploads"]).iterdir())


def test_run_cleanup_is_idempotent(tmp_path: Path):
    _, _, service = _service(tmp_path)
    first = service.run_cleanup(
        confirmation=CLEANUP_CONFIRMATION_TOKEN,
        include_pdfs=False,
    )
    second = service.run_cleanup(
        confirmation=CLEANUP_CONFIRMATION_TOKEN,
        include_pdfs=False,
    )
    assert first["backup"]["database"]
    assert second["backup"]["database"]
    assert second["registry_tables_deleted"]["statement_occurrences"] == 0
    assert second["registry_tables_deleted"]["jobs"] == 0


def test_cleanup_report_is_valid_json(tmp_path: Path):
    _, _, service = _service(tmp_path)
    report = service.run_cleanup(
        confirmation=CLEANUP_CONFIRMATION_TOKEN,
        include_pdfs=False,
    )
    payload = json.loads(
        Path(report["report_path"]).read_text(encoding="utf-8")
    )
    assert payload["confirmation_token_matched"] is True
    assert payload["registry_tables_deleted"]["capture_plans"] == 1


def test_capture_scope_clears_captures_but_keeps_certification(
    tmp_path: Path,
):
    registry, paths, service = _service(tmp_path)
    with registry.connect() as conn:
        certification_before = {
            table: conn.execute(
                f"SELECT COUNT(*) FROM {table}"
            ).fetchone()[0]
            for table in (
                "statement_occurrences", "certified_child_table_links",
            )
        }
    preview = service.preview(scope=SCOPE_CAPTURE)
    assert preview["scope"] == SCOPE_CAPTURE
    assert preview["registry_rows"]["captures"] == 1
    assert "certified_child_table_links" not in preview["registry_rows"]
    assert preview["dir_files"]["reviews"] == 1

    report = service.run_cleanup(
        confirmation=CLEANUP_CONFIRMATION_TOKEN,
        scope=SCOPE_CAPTURE,
        include_pdfs=False,
    )
    with registry.connect() as conn:
        cleared = {
            table: conn.execute(
                f"SELECT COUNT(*) FROM {table}"
            ).fetchone()[0]
            for table in ("captures", "capture_plans", "jobs")
        }
        kept = {
            table: conn.execute(
                f"SELECT COUNT(*) FROM {table}"
            ).fetchone()[0]
            for table in (
                "statement_occurrences", "certified_child_table_links",
            )
        }
        pdf_rows = conn.execute(
            "SELECT COUNT(*) FROM pdf_assets"
        ).fetchone()[0]
    assert cleared == {"captures": 0, "capture_plans": 0, "jobs": 0}
    assert kept == certification_before
    assert pdf_rows == 1

    backup_dir = Path(report["backup"]["database"]).parent
    assert (backup_dir / "archived" / "reviews" / "r.json").is_file()
    assert (paths["reviews"]).is_dir()
    assert not list((paths["reviews"]).iterdir())
    assert report["scope"] == SCOPE_CAPTURE


def test_unknown_cleanup_scope_is_rejected(tmp_path: Path):
    _, _, service = _service(tmp_path)
    with pytest.raises(ValueError, match="UNKNOWN_CLEANUP_SCOPE"):
        service.preview(scope="unknown", include_pdfs=False)
    with pytest.raises(ValueError, match="UNKNOWN_CLEANUP_SCOPE"):
        service.run_cleanup(
            confirmation=CLEANUP_CONFIRMATION_TOKEN,
            scope="unknown",
            include_pdfs=False,
        )


def test_cleanup_ui_widget_keys_do_not_collide_with_session_state():
    """The scan button key must not own the preview session_state key."""
    app_source = (ROOT / "app.py").read_text(encoding="utf-8")
    assert 'key="data_cleanup_scan_btn"' in app_source
    assert 'st.session_state["data_cleanup_preview"] = cleanup_svc.preview(' in (
        app_source
    )
    # No widget may instantiate a key that the page later writes directly.
    assert 'key="data_cleanup_preview"' not in app_source
