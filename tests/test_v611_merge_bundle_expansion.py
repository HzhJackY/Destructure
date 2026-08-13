from __future__ import annotations

import json
import sqlite3
import sys
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace

import pandas as pd
import pytest


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import capture_library
import merge_library
import table_merge
from services import merge_service as merge_service_module
from services.merge_service import MergeService
from table_merge import _apply_merge_row_exclusions


class _Registry:
    def __init__(self, path: Path):
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as conn:
            conn.executescript(
                """
                CREATE TABLE capture_bundles (
                    bundle_id TEXT PRIMARY KEY,
                    container_id TEXT,
                    table_family_id TEXT,
                    member_table_id TEXT,
                    status TEXT NOT NULL
                );
                CREATE TABLE capture_bundle_children (
                    bundle_id TEXT NOT NULL,
                    block_id TEXT NOT NULL,
                    capture_id TEXT,
                    logical_asset_id TEXT,
                    child_order INTEGER NOT NULL,
                    status TEXT NOT NULL
                );
                CREATE TABLE pdf_assets (
                    pdf_id TEXT PRIMARY KEY,
                    sha256 TEXT
                );
                CREATE TABLE note_containers (
                    container_id TEXT PRIMARY KEY,
                    source_pdf_id TEXT,
                    source_pdf_sha256 TEXT
                );
                CREATE TABLE jobs (
                    target_asset_id TEXT,
                    payload_json TEXT,
                    updated_at TEXT,
                    created_at TEXT
                );
                CREATE TABLE capture_plans (
                    plan_id TEXT PRIMARY KEY,
                    payload_json TEXT
                );
                """
            )

    @contextmanager
    def connect(self):
        conn = sqlite3.connect(self.path)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()


class _CaptureRepository:
    def __init__(self, records: list[dict[str, object]]):
        self.records = {str(record["capture_id"]): record for record in records}

    def get_many(self, capture_ids: list[str]) -> list[dict[str, object]]:
        return list(reversed([
            self.records[capture_id]
            for capture_id in capture_ids
            if capture_id in self.records
        ]))


class _Eligibility:
    def __init__(self):
        self.calls: list[list[str]] = []

    def assert_capture_ids(self, capture_ids):
        self.calls.append(list(capture_ids))


def _derived_row(status: str, row_order: int, block_id: str) -> dict[str, object]:
    return {
        "table_block_id": block_id,
        "row_order": row_order,
        "row_type": "IMPLICIT_TOTAL",
        "observation_type": "DERIVED_OBSERVATION",
        "normalized_item": f"合计{row_order}",
        "derived_status": status,
        "derivation_method": "SUM_CHILDREN",
        "cells": [
            {
                "cell_role": "NUMERIC",
                "column_ordinal": ordinal,
                "raw": str(100 + ordinal),
                "parsed_number": float(100 + ordinal),
                "value_yuan": float(100 + ordinal),
            }
            for ordinal in (0, 1)
        ],
    }


def _source_row(row_order: int, block_id: str) -> dict[str, object]:
    return {
        "table_block_id": block_id,
        "row_order": row_order,
        "row_type": "DETAIL",
        "observation_type": "SOURCE_OBSERVATION",
        "normalized_item": f"明细{row_order}",
        "derived_status": "",
        "cells": [],
    }


def _write_capture(
    root: Path,
    capture_id: str,
    *,
    bundle_id: str,
    block_id: str,
    block_order: int,
    member_table: str = "debt_investment",
    logical_table_id: str = "LTCAND_TEST",
    excluded_status: str = "",
) -> dict[str, object]:
    run_dir = root / capture_id
    run_dir.mkdir(parents=True)
    metadata = {
        "capture_bundle_id": bundle_id,
        "table_block_id": block_id,
        "block_order": block_order,
        "table_family": "financial_investment",
        "table_family_id": "financial_investment",
        "member_table": member_table,
        "member_table_id": f"{member_table}::{block_id}",
        "member_table_role": "NOTE_DETAIL",
        "source_table_title": "合并资产负债表",
        "note_reference": "附注十-7",
        "lifecycle_status": "ACTIVE",
        "merge_ready": True,
        "certified_target": {
            "logical_table_id": logical_table_id,
            "member_table_id": member_table,
        },
    }
    result = {
        "pdf_name": "测试公司2025年报.pdf",
        "pdf_sha256": "canonical-pdf-sha",
        "table_query": f"子表{block_order}",
        "note_number": "7",
        "located_title": f"子表{block_order}",
        "columns": [{"year": "2025"}],
        "rows": [
            _derived_row(excluded_status, 10 + block_order, block_id)
            if excluded_status
            else _source_row(10 + block_order, block_id)
        ],
    }
    (run_dir / "capture_metadata.json").write_text(
        json.dumps(metadata, ensure_ascii=False), encoding="utf-8"
    )
    (run_dir / "table_capture_result.json").write_text(
        json.dumps(result, ensure_ascii=False), encoding="utf-8"
    )
    return {
        "capture_id": capture_id,
        "run_path": str(run_dir),
        "company": "测试公司",
        "document_year": "2025",
        "pdf_id": "PDF_TEST",
        "merge_ready": True,
        "lifecycle_status": "ACTIVE",
        "is_trashed": False,
    }


def _service_fixture(tmp_path: Path, monkeypatch, *, mismatch: bool = False):
    registry = _Registry(tmp_path / "metadata.db")
    bundle_id = "BUNDLE_TEST"
    records = [
        _write_capture(
            tmp_path / "captures", "ROOT", bundle_id=bundle_id,
            block_id="BLOCK_1", block_order=0,
        ),
        _write_capture(
            tmp_path / "captures", "ROOT__b2__", bundle_id=bundle_id,
            block_id="BLOCK_2", block_order=1,
            excluded_status="DERIVED_REJECTED_NON_BLOCKING",
        ),
        _write_capture(
            tmp_path / "captures", "ROOT__b3__", bundle_id=bundle_id,
            block_id="BLOCK_3", block_order=2,
            logical_table_id="LTCAND_OTHER" if mismatch else "LTCAND_TEST",
            excluded_status="SUPPRESSED_BY_EXPLICIT_TOTAL",
        ),
    ]
    with registry.connect() as conn:
        conn.execute(
            """INSERT INTO capture_bundles(
                   bundle_id,container_id,table_family_id,member_table_id,status
               ) VALUES(?,?,?,?,?)""",
            (
                bundle_id, "NOTE_TEST", "financial_investment",
                "debt_investment", "READY",
            ),
        )
        conn.execute(
            "INSERT INTO pdf_assets(pdf_id,sha256) VALUES(?,?)",
            ("PDF_TEST", "canonical-pdf-sha"),
        )
        conn.execute(
            """INSERT INTO note_containers(
                   container_id,source_pdf_id,source_pdf_sha256
               ) VALUES(?,?,?)""",
            ("NOTE_TEST", "PDF_TEST", "canonical-pdf-sha"),
        )
        conn.executemany(
            """INSERT INTO capture_bundle_children(
                   bundle_id,block_id,capture_id,logical_asset_id,child_order,status
               ) VALUES(?,?,?,?,?,?)""",
            [
                (
                    bundle_id, f"BLOCK_{index + 1}", record["capture_id"],
                    f"ASSET_{index + 1}", index, "CAPTURED",
                )
                for index, record in enumerate(records)
            ],
        )

    eligibility = _Eligibility()
    seen: dict[str, object] = {}

    def fake_create_merge_project(
        capture_dirs,
        metadata_rows,
        output_dir,
        table_id,
        taxonomy_path,
        reference_capture_run_id=None,
        merge_lineage=None,
        member_display_map=None,
        order_policy=None,
        reference_report_year=None,
    ):
        seen.update({
            "capture_dirs": list(capture_dirs),
            "metadata_rows": list(metadata_rows),
            "merge_lineage": dict(merge_lineage or {}),
        })
        Path(output_dir).mkdir(parents=True, exist_ok=True)
        return {"manifest": str(Path(output_dir) / "merge_manifest.json")}

    monkeypatch.setattr(
        capture_library,
        "capture_readiness",
        lambda result: {"merge_ready": True, "merge_blockers": []},
    )
    monkeypatch.setattr(table_merge, "create_merge_project", fake_create_merge_project)
    monkeypatch.setattr(merge_library, "ensure_merge_metadata", lambda output_dir: None)
    monkeypatch.setattr(
        merge_service_module, "sync_merge_run", lambda output_dir: {"status": "OK"}
    )

    service = MergeService(
        SimpleNamespace(),
        _CaptureRepository(records),
        registry,
        SimpleNamespace(),
        {
            "table_merges": tmp_path / "merges",
            "taxonomy": tmp_path / "taxonomy.json",
        },
        eligibility_service=eligibility,
    )
    return service, records, eligibility, seen


def test_root_input_expands_same_bundle_and_records_cell_lineage(tmp_path, monkeypatch):
    service, _, eligibility, seen = _service_fixture(tmp_path, monkeypatch)

    service.create(
        capture_ids=["ROOT"],
        table_id="financial_investment",
        output_dir=tmp_path / "merge",
    )

    selected_ids = [path.name for path in seen["capture_dirs"]]
    assert selected_ids == ["ROOT", "ROOT__b2__", "ROOT__b3__"]
    assert eligibility.calls == [selected_ids]
    lineage = seen["merge_lineage"]
    assert lineage["requested_capture_count"] == 1
    assert lineage["bundle_graph_discovered_capture_count"] == 3
    assert lineage["selected_capture_count"] == 3
    assert lineage["capture_level_exclusion_count"] == 0
    assert lineage["row_cell_exclusion_count"] == 4
    assert lineage["row_cell_exclusion_status_counts"] == {
        "DERIVED_REJECTED_NON_BLOCKING": 2,
        "SUPPRESSED_BY_EXPLICIT_TOTAL": 2,
    }
    metadata_rows = seen["metadata_rows"]
    assert [row["merge_bundle_lineage"]["bundle_role"] for row in metadata_rows] == [
        "ROOT", "DERIVED", "DERIVED"
    ]
    assert all(
        row["merge_bundle_lineage"]["target_identity"]["certified_logical_table_id"]
        == "LTCAND_TEST"
        for row in metadata_rows
    )


def test_bundle_target_mismatch_fails_closed(tmp_path, monkeypatch):
    service, _, _, _ = _service_fixture(tmp_path, monkeypatch, mismatch=True)
    with pytest.raises(ValueError, match="CAPTURE_BUNDLE_TARGET_MISMATCH"):
        service.create(
            capture_ids=["ROOT"],
            table_id="financial_investment",
            output_dir=tmp_path / "merge",
        )


def test_bundle_root_and_child_order_cardinality_fail_closed(tmp_path, monkeypatch):
    service, _, _, _ = _service_fixture(tmp_path / "two_roots", monkeypatch)
    with service.registry.connect() as conn:
        conn.execute(
            "UPDATE capture_bundle_children SET child_order=0 "
            "WHERE capture_id='ROOT__b2__'"
        )
    with pytest.raises(ValueError, match="CAPTURE_BUNDLE_ROOT_CARDINALITY_INVALID"):
        service.create(
            capture_ids=["ROOT"],
            table_id="financial_investment",
            output_dir=tmp_path / "two_roots_merge",
        )

    service, _, _, _ = _service_fixture(tmp_path / "duplicate_order", monkeypatch)
    with service.registry.connect() as conn:
        conn.execute(
            "UPDATE capture_bundle_children SET child_order=1 "
            "WHERE capture_id='ROOT__b3__'"
        )
    with pytest.raises(ValueError, match="CAPTURE_BUNDLE_CHILD_ORDER_INVALID"):
        service.create(
            capture_ids=["ROOT"],
            table_id="financial_investment",
            output_dir=tmp_path / "duplicate_order_merge",
        )


def test_duplicate_and_non_ready_bundle_inputs_are_rejected(tmp_path, monkeypatch):
    service, records, _, _ = _service_fixture(tmp_path, monkeypatch)
    with pytest.raises(ValueError, match="DUPLICATE_CAPTURE_IDS"):
        service.create(
            capture_ids=["ROOT", "ROOT"],
            table_id="financial_investment",
            output_dir=tmp_path / "duplicate",
        )

    records[1]["merge_ready"] = False
    with pytest.raises(ValueError, match="REGISTRY_MERGE_READY_FALSE"):
        service.create(
            capture_ids=["ROOT"],
            table_id="financial_investment",
            output_dir=tmp_path / "not_ready",
        )


def test_registry_graph_source_status_and_block_drift_fail_closed(tmp_path, monkeypatch):
    service, records, _, _ = _service_fixture(tmp_path, monkeypatch)
    registry = service.registry
    with registry.connect() as conn:
        conn.execute(
            "DELETE FROM capture_bundle_children WHERE capture_id='ROOT'"
        )
    with pytest.raises(ValueError, match="CAPTURE_BUNDLE_REGISTRY_GRAPH_MISSING"):
        service.create(
            capture_ids=["ROOT"],
            table_id="financial_investment",
            output_dir=tmp_path / "missing_graph",
        )

    service, records, _, _ = _service_fixture(tmp_path / "source", monkeypatch)
    result_path = Path(records[1]["run_path"]) / "table_capture_result.json"
    result = json.loads(result_path.read_text(encoding="utf-8"))
    result["rows"][0]["observation_type"] = "SOURCE_OBSERVATION"
    result_path.write_text(json.dumps(result, ensure_ascii=False), encoding="utf-8")
    with pytest.raises(ValueError, match="MERGE_ROW_EXCLUSION_SOURCE_STATUS_CONFLICT"):
        service.create(
            capture_ids=["ROOT"],
            table_id="financial_investment",
            output_dir=tmp_path / "source_conflict",
        )

    service, records, _, _ = _service_fixture(tmp_path / "block", monkeypatch)
    metadata_path = Path(records[1]["run_path"]) / "capture_metadata.json"
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    metadata["table_block_id"] = "BLOCK_WRONG"
    metadata_path.write_text(json.dumps(metadata, ensure_ascii=False), encoding="utf-8")
    with pytest.raises(ValueError, match="CAPTURE_BUNDLE_BLOCK_LINEAGE_MISMATCH"):
        service.create(
            capture_ids=["ROOT"],
            table_id="financial_investment",
            output_dir=tmp_path / "block_drift",
        )

    service, _, _, _ = _service_fixture(tmp_path / "bundle_status", monkeypatch)
    with service.registry.connect() as conn:
        conn.execute(
            "UPDATE capture_bundles SET status='REVIEW_REQUIRED'"
        )
    with pytest.raises(ValueError, match="CAPTURE_BUNDLE_NOT_READY"):
        service.create(
            capture_ids=["ROOT"],
            table_id="financial_investment",
            output_dir=tmp_path / "bundle_not_ready",
        )

    service, _, _, _ = _service_fixture(tmp_path / "child_status", monkeypatch)
    with service.registry.connect() as conn:
        conn.execute(
            "UPDATE capture_bundle_children SET status='PENDING' "
            "WHERE capture_id='ROOT__b2__'"
        )
    with pytest.raises(ValueError, match="CAPTURE_BUNDLE_CHILD_NOT_CAPTURED"):
        service.create(
            capture_ids=["ROOT"],
            table_id="financial_investment",
            output_dir=tmp_path / "child_not_captured",
        )

    service, records, _, _ = _service_fixture(tmp_path / "missing_rows", monkeypatch)
    result_path = Path(records[0]["run_path"]) / "table_capture_result.json"
    result = json.loads(result_path.read_text(encoding="utf-8"))
    result["rows"] = []
    result_path.write_text(json.dumps(result, ensure_ascii=False), encoding="utf-8")
    with pytest.raises(ValueError, match="CAPTURE_RESULT_BLOCK_LINEAGE_MISSING"):
        service.create(
            capture_ids=["ROOT"],
            table_id="financial_investment",
            output_dir=tmp_path / "missing_result_rows",
        )

    service, records, _, _ = _service_fixture(tmp_path / "partial_block", monkeypatch)
    result_path = Path(records[1]["run_path"]) / "table_capture_result.json"
    result = json.loads(result_path.read_text(encoding="utf-8"))
    result["rows"].append(_source_row(99, ""))
    result_path.write_text(json.dumps(result, ensure_ascii=False), encoding="utf-8")
    with pytest.raises(ValueError, match="CAPTURE_RESULT_BLOCK_LINEAGE_MISSING"):
        service.create(
            capture_ids=["ROOT"],
            table_id="financial_investment",
            output_dir=tmp_path / "partial_missing_block",
        )

    service, records, _, _ = _service_fixture(tmp_path / "pdf_id", monkeypatch)
    records[1]["pdf_id"] = "PDF_WRONG"
    with pytest.raises(ValueError, match="CAPTURE_BUNDLE_PDF_ID_MISMATCH"):
        service.create(
            capture_ids=["ROOT"],
            table_id="financial_investment",
            output_dir=tmp_path / "pdf_id_mismatch",
        )


def test_unbundled_legacy_capture_without_block_lineage_remains_compatible(
    tmp_path, monkeypatch
):
    service, _, _, seen = _service_fixture(tmp_path / "base", monkeypatch)
    standalone = _write_capture(
        tmp_path / "standalone", "STANDALONE", bundle_id="",
        block_id="BLOCK_LEGACY", block_order=0,
    )
    metadata_path = Path(standalone["run_path"]) / "capture_metadata.json"
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    metadata.pop("capture_bundle_id", None)
    metadata.pop("table_block_id", None)
    metadata.pop("block_id", None)
    metadata_path.write_text(json.dumps(metadata, ensure_ascii=False), encoding="utf-8")
    result_path = Path(standalone["run_path"]) / "table_capture_result.json"
    result = json.loads(result_path.read_text(encoding="utf-8"))
    result["rows"][0].pop("table_block_id", None)
    result_path.write_text(json.dumps(result, ensure_ascii=False), encoding="utf-8")
    service.capture_repo = _CaptureRepository([standalone])

    service.create(
        capture_ids=["STANDALONE"],
        table_id="financial_investment",
        output_dir=tmp_path / "legacy_merge",
    )

    assert [path.name for path in seen["capture_dirs"]] == ["STANDALONE"]
    assert seen["merge_lineage"]["row_cell_exclusion_count"] == 0

def test_formal_loader_filter_preserves_source_and_fails_closed_on_drift(tmp_path):
    raw = pd.DataFrame([
        {"table_block_id": "BLOCK", "row_order": 1, "column_ordinal": 0,
         "normalized_item": "source", "row_id": "source-0", "value_raw": "10", "value": 10},
        {"table_block_id": "BLOCK", "row_order": 1, "column_ordinal": 1,
         "normalized_item": "source", "row_id": "source-1", "value_raw": "11", "value": 11},
        {"table_block_id": "BLOCK", "row_order": 2, "column_ordinal": 0,
         "normalized_item": "rejected", "row_id": "rejected-0", "value_raw": "20", "value": 20},
        {"table_block_id": "BLOCK", "row_order": 2, "column_ordinal": 1,
         "normalized_item": "rejected", "row_id": "rejected-1", "value_raw": "21", "value": 21},
        {"table_block_id": "BLOCK", "row_order": 3, "column_ordinal": 0,
         "normalized_item": "suppressed", "row_id": "suppressed-0", "value_raw": "30", "value": 30},
        {"table_block_id": "BLOCK", "row_order": 3, "column_ordinal": 1,
         "normalized_item": "suppressed", "row_id": "suppressed-1", "value_raw": "31", "value": 31},
    ])
    exclusions = [
        {
            "capture_run_id": "CAPTURE",
            "table_block_id": "BLOCK",
            "row_order": row_order,
            "column_ordinal": ordinal,
            "derived_status": status,
            "observation_type": "DERIVED_OBSERVATION",
            "normalized_item": "rejected" if row_order == 2 else "suppressed",
            "value_raw": str(row_order * 10 + ordinal),
            "parsed_number": float(row_order * 10 + ordinal),
        }
        for row_order, status in (
            (2, "DERIVED_REJECTED_NON_BLOCKING"),
            (3, "SUPPRESSED_BY_EXPLICIT_TOTAL"),
        )
        for ordinal in (0, 1)
    ]
    metadata = {"merge_row_exclusions": exclusions}

    filtered = _apply_merge_row_exclusions(raw, metadata, tmp_path / "CAPTURE")

    assert filtered["row_id"].tolist() == ["source-0", "source-1"]
    assert len(raw) == 6
    assert metadata["merge_row_excluded_cell_count"] == 4
    assert [row["source_row_id"] for row in metadata["merge_row_exclusions_applied"]] == [
        "rejected-0", "rejected-1", "suppressed-0", "suppressed-1"
    ]

    drifted = {"merge_row_exclusions": [{**exclusions[0], "row_order": 99}]}
    with pytest.raises(ValueError, match="MERGE_ROW_EXCLUSION_DRIFT"):
        _apply_merge_row_exclusions(raw, drifted, tmp_path / "CAPTURE")

    stale = {
        "merge_row_exclusions": [
            {**exclusions[0], "normalized_item": "stale-item"}
        ]
    }
    with pytest.raises(ValueError, match="MERGE_ROW_EXCLUSION_EVIDENCE_MISMATCH"):
        _apply_merge_row_exclusions(raw, stale, tmp_path / "CAPTURE")

    zero_raw = pd.DataFrame([{
        "table_block_id": "BLOCK",
        "row_order": 4,
        "column_ordinal": 0,
        "normalized_item": "zero",
        "row_id": "zero-0",
        "value_raw": 0,
        "value": 0,
    }])
    zero_metadata = {"merge_row_exclusions": [{
        "capture_run_id": "CAPTURE",
        "table_block_id": "BLOCK",
        "row_order": 4,
        "column_ordinal": 0,
        "derived_status": "DERIVED_REJECTED_NON_BLOCKING",
        "observation_type": "DERIVED_OBSERVATION",
        "normalized_item": "zero",
        "value_raw": 0,
        "parsed_number": 0.0,
    }]}
    assert _apply_merge_row_exclusions(
        zero_raw, zero_metadata, tmp_path / "CAPTURE"
    ).empty
    assert zero_metadata["merge_row_excluded_cell_count"] == 1
