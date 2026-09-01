from __future__ import annotations

import hashlib
import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from data_home import ensure_data_home
from metadata_registry import MetadataRegistry
from registry_sync import RegistrySynchronizer, _pdf_id
from repositories.pdf_repository import PdfRepository
from services.pdf_service import PdfService


def _service(tmp_path: Path) -> tuple[PdfService, MetadataRegistry, dict[str, Path], Path, str]:
    rules = tmp_path / "bundled_rules.json"
    rules.write_text('{"version":1,"metrics":[]}', encoding="utf-8")
    paths = ensure_data_home(tmp_path / "data_home", rules)
    registry = MetadataRegistry(paths["metadata_db"])
    source = paths["uploads"] / "sample.pdf"
    source.write_bytes(b"%PDF-1.4\nsynthetic pdf asset lifecycle\n%%EOF")
    pdf_id = _pdf_id(source)
    registry.upsert_pdf({
        "pdf_id": pdf_id,
        "filename": source.name,
        "display_name": source.name,
        "sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
        "company": "虚构保险",
        "document_year": "2099",
        "size_bytes": source.stat().st_size,
        "path": str(source.resolve()),
    })
    return PdfService(PdfRepository(registry), paths), registry, paths, source, pdf_id


def test_unreferenced_pdf_trash_restore_and_permanent_delete(tmp_path: Path) -> None:
    service, registry, paths, source, pdf_id = _service(tmp_path)

    trashed = service.trash(pdf_id)
    assert trashed["status"] == "TRASHED"
    assert not source.exists()
    assert Path(trashed["trash_path"]).is_file()
    assert service.list() == []
    assert len(service.list(only_trash=True)) == 1

    restored = service.restore(pdf_id)
    assert restored["status"] == "ACTIVE"
    assert source.is_file()
    assert service.list(only_trash=True) == []

    service.trash(pdf_id)
    digest = hashlib.sha256((paths["pdf_trash"] / source.name).read_bytes()).hexdigest()
    cache_dir = paths["cache"] / digest
    cache_dir.mkdir(parents=True)
    (cache_dir / "fast_index_test.json").write_text("{}", encoding="utf-8")
    text_index_dir = paths["text_indexes"] / digest
    text_index_dir.mkdir(parents=True)
    (text_index_dir / "native.json").write_text("{}", encoding="utf-8")
    purged = service.purge(pdf_id, confirmation=f"DELETE {pdf_id}")
    assert purged["status"] == "PURGED"
    assert not (paths["pdf_trash"] / source.name).exists()
    assert not cache_dir.exists()
    assert not text_index_dir.exists()
    assert PdfRepository(registry).get(pdf_id) is None

    with registry.connect() as conn:
        events = [row[0] for row in conn.execute(
            "SELECT event_type FROM registry_events WHERE asset_id=? ORDER BY event_id", (pdf_id,)
        ).fetchall()]
    assert events == [
        "PDF_TRASHED", "PDF_RESTORED", "PDF_TRASHED",
        "PDF_PERMANENT_DELETE_REQUESTED", "PDF_PERMANENTLY_DELETED",
    ]


@pytest.mark.parametrize("reference_table", ["captures", "machine_discoveries", "statement_occurrences"])
def test_registry_reference_blocks_pdf_trash(tmp_path: Path, reference_table: str) -> None:
    service, registry, _paths, source, pdf_id = _service(tmp_path)
    with registry.connect() as conn:
        if reference_table == "captures":
            conn.execute(
                """INSERT INTO captures(capture_id,run_path,pdf_id,lifecycle_status,updated_at)
                   VALUES(?,?,?,?,?)""",
                ("CAP_REF", str(tmp_path / "run"), pdf_id, "ACTIVE", "now"),
            )
        elif reference_table == "machine_discoveries":
            conn.execute(
                """INSERT INTO machine_discoveries(discovery_id,pdf_id,status,evidence_json,created_at)
                   VALUES(?,?,?,?,?)""",
                ("DISC_REF", str(source), "NEEDS_REVIEW", "{}", "now"),
            )
        else:
            conn.execute(
                """INSERT INTO statement_occurrences(
                       occurrence_id,pdf_id,display_name,table_family,parent_text,child_rows_json,
                       status,evidence_json,created_at
                   ) VALUES(?,?,?,?,?,?,?,?,?)""",
                ("OCC_REF", str(source), "投资组合", "investment_portfolio", "投资组合", "[]",
                 "NEEDS_ANCHOR_REVIEW", "{}", "now"),
            )

    impact = service.dependency_impact(pdf_id)
    assert impact["reference_count"] == 1
    assert impact["references"][0]["table"] == reference_table
    with pytest.raises(PermissionError, match="PDF_HAS_REGISTRY_REFERENCES"):
        service.trash(pdf_id)
    assert source.is_file()
    assert service.list()[0]["lifecycle_status"] == "ACTIVE"


def test_wrong_permanent_delete_token_fails_closed(tmp_path: Path) -> None:
    service, registry, paths, source, pdf_id = _service(tmp_path)
    service.trash(pdf_id)

    with pytest.raises(PermissionError, match="PDF_PERMANENT_DELETE_CONFIRMATION_MISMATCH"):
        service.purge(pdf_id, confirmation="DELETE WRONG")

    assert (paths["pdf_trash"] / source.name).is_file()
    assert PdfRepository(registry).get(pdf_id)["lifecycle_status"] == "TRASHED"


def test_registry_sync_preserves_trashed_pdf_index(tmp_path: Path) -> None:
    service, registry, paths, _source, pdf_id = _service(tmp_path)
    service.trash(pdf_id)

    sync = RegistrySynchronizer(registry, paths).sync_pdfs()

    assert sync["count"] == 0
    assert PdfRepository(registry).get(pdf_id)["lifecycle_status"] == "TRASHED"


def test_stale_upsert_cannot_reactivate_trashed_pdf(tmp_path: Path) -> None:
    service, registry, paths, source, pdf_id = _service(tmp_path)
    trashed = service.trash(pdf_id)

    registry.upsert_pdf({
        "pdf_id": pdf_id,
        "filename": source.name,
        "display_name": source.name,
        "path": str(source),
        "size_bytes": 999,
    })

    row = PdfRepository(registry).get(pdf_id)
    assert row["lifecycle_status"] == "TRASHED"
    assert row["path"] == trashed["trash_path"]
    assert (paths["pdf_trash"] / source.name).is_file()


def test_managed_path_boundary_fails_closed(tmp_path: Path) -> None:
    service, registry, _paths, source, pdf_id = _service(tmp_path)
    outside = tmp_path / "outside.pdf"
    outside.write_bytes(source.read_bytes())
    with registry.connect() as conn:
        conn.execute("UPDATE pdf_assets SET path=? WHERE pdf_id=?", (str(outside), pdf_id))

    with pytest.raises(PermissionError, match="PDF_PATH_OUTSIDE_MANAGED_ROOT"):
        service.trash(pdf_id)

    assert outside.is_file()
    assert source.is_file()
