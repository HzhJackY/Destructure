from __future__ import annotations

import json
import sys
from pathlib import Path
from types import SimpleNamespace


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from metadata_registry import MetadataRegistry
from repositories.batch_repository import BatchRepository
from repositories.capture_repository import CaptureRepository
from services.batch_service import BatchService


NOW = "2026-08-05T12:00:00+08:00"


class _Eligibility:
    def __init__(self, capture_ids: set[str] | None = None) -> None:
        self.capture_ids = set(capture_ids or set())

    def eligible_assets(self):
        return [{"capture_id": capture_id} for capture_id in self.capture_ids]


def _service(tmp_path: Path, eligible: set[str] | None = None):
    registry = MetadataRegistry(tmp_path / "metadata.db")
    capture_repository = CaptureRepository(registry)
    assets = SimpleNamespace(capture_repo=capture_repository)
    service = BatchService(
        BatchRepository(registry),
        assets,
        merge_eligibility_service=_Eligibility(eligible),
    )
    return registry, service


def _insert_capture_batch(connection, batch_id: str) -> None:
    connection.execute(
        """INSERT OR IGNORE INTO capture_batches(
           batch_id,batch_status,table_query,updated_at
           ) VALUES(?, 'ACTIVE', '', ?)""",
        (batch_id, NOW),
    )


def _insert_job(
    connection, *, batch_id: str, job_id: str, status: str,
    capture_id: str | None,
) -> None:
    result = {"capture_id": capture_id} if capture_id else {}
    connection.execute(
        """INSERT INTO jobs(
           job_id,batch_id,job_type,status,progress,target_asset_id,
           payload_json,result_json,created_at,updated_at
           ) VALUES(?,?, 'TABLE_CAPTURE', ?, 1, ?, '{}', ?, ?, ?)""",
        (
            job_id, batch_id, status, capture_id,
            json.dumps(result), NOW, NOW,
        ),
    )


def _insert_capture(
    connection, *, capture_id: str, storage_batch_id: str,
    active: bool, ready: bool,
) -> str:
    logical_asset_id = "LASSET_" + capture_id
    _insert_capture_batch(connection, storage_batch_id)
    connection.execute(
        """INSERT INTO captures(
           capture_id,run_path,company,document_year,table_query,batch_id,
           lifecycle_status,merge_ready,is_trashed,created_at,updated_at
           ) VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
        (
            capture_id, str(Path("capture_runs") / capture_id), "测试保险",
            "2025", "债权投资", storage_batch_id,
            "ACTIVE" if active else "TRASHED", int(ready and active),
            int(not active), NOW, NOW,
        ),
    )
    connection.execute(
        """INSERT INTO logical_assets(
           logical_asset_id,identity_key,company_id,filing_type,report_year,
           statement_scope,research_definition_id,definition_version,
           table_family_id,member_table_id,logical_source_role,
           direct_asset_status,archived_by_parent,derivation_evidence_json,
           current_capture_id,created_at,updated_at
           ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (
            logical_asset_id, "IDENTITY::" + capture_id, "测试保险",
            "ANNUAL_REPORT", "2025", "CONSOLIDATED", "DEF", "DEF_V1",
            "FINANCIAL_INVESTMENT", "债权投资", "NOTE_DETAIL",
            "ACTIVE" if active else "TRASHED", 0, "{}",
            capture_id if active else None, NOW, NOW,
        ),
    )
    connection.execute(
        """INSERT INTO capture_versions(
           logical_asset_id,capture_id,capture_version,is_current,
           processing_status,registration_status,quality_status,review_status,
           asset_status,producer_version,created_at,updated_at
           ) VALUES(?,?,1,?,'COMPLETED','REGISTERED',?,?,?,?,?,?)""",
        (
            logical_asset_id, capture_id, int(active),
            "READY" if ready else "REVIEW_REQUIRED",
            "CONFIRMED_AUTO" if ready else "PENDING",
            "CERTIFIED_ACTIVE" if ready and active else "TRASHED",
            "v6.11", NOW, NOW,
        ),
    )
    return logical_asset_id


def _insert_ready_bundle(
    connection, *, capture_id: str, logical_asset_id: str,
) -> str:
    bundle_id = "BUNDLE_" + capture_id
    container_id = "CONTAINER_" + capture_id
    block_id = "BLOCK_" + capture_id
    connection.execute(
        """INSERT INTO note_containers(
           container_id,context_json,layout_graph_json,created_at
           ) VALUES(?, '{}', '{}', ?)""",
        (container_id, NOW),
    )
    connection.execute(
        """INSERT INTO table_blocks(
           block_id,container_id,block_order,block_role,bbox_json,
           header_topology_json,semantic_graph_json,reconciliation_json,
           quality_status,status,evidence_json,created_at
           ) VALUES(?,?,0,'PRIMARY','{}','{}','{}','{}','READY','CAPTURED','{}',?)""",
        (block_id, container_id, NOW),
    )
    connection.execute(
        """INSERT INTO capture_bundles(
           bundle_id,container_id,status,payload_json,created_at,updated_at
           ) VALUES(?,?,'READY','{}',?,?)""",
        (bundle_id, container_id, NOW, NOW),
    )
    connection.execute(
        """INSERT INTO capture_bundle_children(
           bundle_id,block_id,capture_id,logical_asset_id,child_order,status,
           payload_json,created_at
           ) VALUES(?,?,?,?,0,'CAPTURED','{}',?)""",
        (bundle_id, block_id, capture_id, logical_asset_id, NOW),
    )
    return bundle_id


def test_trashed_terminal_batch_is_not_monitorable_or_mergeable(tmp_path):
    batch_id = "CAPTURE_TRASHED_LEGACY"
    registry, service = _service(tmp_path)
    with registry.connect() as connection:
        for index in range(12):
            capture_id = f"CAPTURE_TRASHED_{index}"
            _insert_job(
                connection, batch_id=batch_id, job_id=f"JOB_{index}",
                status="REVIEW_REQUIRED", capture_id=capture_id,
            )
            _insert_capture(
                connection, capture_id=capture_id,
                storage_batch_id=f"LEGACY_SINGLE::{capture_id}",
                active=False, ready=False,
            )

    state = service.execution_readiness(batch_id)

    assert state["total_jobs"] == 12
    assert state["terminal_jobs"] == 12
    assert state["status_counts"]["REVIEW_REQUIRED"] == 12
    assert state["active_current_capture_count"] == 0
    assert state["can_enter_merge"] is False
    assert "INACTIVE_OR_HISTORICAL_CAPTURE_OUTPUT" in state["gate_reasons"]
    assert "NO_ACTIVE_CURRENT_CAPTURE" in state["gate_reasons"]
    assert batch_id not in {
        row["batch_id"] for row in service.list_monitorable_batches()
    }


def test_job_target_resolves_current_capture_when_storage_batch_id_drifts(tmp_path):
    batch_id = "CAPTURE_EXECUTION_BATCH"
    capture_id = "CAPTURE_CURRENT_DRIFT"
    registry, service = _service(tmp_path, {capture_id})
    with registry.connect() as connection:
        _insert_job(
            connection, batch_id=batch_id, job_id="JOB_DRIFT",
            status="SUCCESS", capture_id=capture_id,
        )
        _insert_capture(
            connection, capture_id=capture_id,
            storage_batch_id="LEGACY_SINGLE::CAPTURE_CURRENT_DRIFT",
            active=True, ready=True,
        )

    state = service.execution_readiness(batch_id)

    assert state["active_current_capture_ids"] == [capture_id]
    assert state["root_capture_ids"] == [capture_id]
    assert state["can_enter_merge"] is True
    assert batch_id in {
        row["batch_id"] for row in service.list_monitorable_batches()
    }


def test_zero_active_capture_never_passes_merge_gate(tmp_path):
    batch_id = "CAPTURE_MISSING_OUTPUT"
    registry, service = _service(tmp_path)
    with registry.connect() as connection:
        _insert_job(
            connection, batch_id=batch_id, job_id="JOB_MISSING",
            status="SUCCESS", capture_id="CAPTURE_NOT_REGISTERED",
        )

    state = service.execution_readiness(batch_id)

    assert state["terminal_jobs"] == 1
    assert state["active_current_capture_count"] == 0
    assert state["can_enter_merge"] is False
    assert "MISSING_CAPTURE_OUTPUT" in state["gate_reasons"]
    assert "NO_ACTIVE_CURRENT_CAPTURE" in state["gate_reasons"]


def test_ready_current_bundle_root_can_enter_merge(tmp_path):
    batch_id = "CAPTURE_READY_ROOT"
    capture_id = "CAPTURE_READY_ROOT_1"
    registry, service = _service(tmp_path, {capture_id})
    with registry.connect() as connection:
        _insert_job(
            connection, batch_id=batch_id, job_id="JOB_READY_ROOT",
            status="SUCCESS", capture_id=capture_id,
        )
        logical_asset_id = _insert_capture(
            connection, capture_id=capture_id,
            storage_batch_id=batch_id, active=True, ready=True,
        )
        bundle_id = _insert_ready_bundle(
            connection, capture_id=capture_id,
            logical_asset_id=logical_asset_id,
        )

    state = service.execution_readiness(batch_id)

    assert state["bundle_by_capture"] == {capture_id: bundle_id}
    assert state["eligible_root_capture_ids"] == [capture_id]
    assert state["gate_reasons"] == []
    assert state["can_enter_merge"] is True


def test_non_blocking_warning_does_not_block_ready_root(tmp_path):
    batch_id = "CAPTURE_READY_WITH_WARNING"
    capture_id = "CAPTURE_WARNING_ROOT"
    registry, service = _service(tmp_path, {capture_id})
    with registry.connect() as connection:
        _insert_job(
            connection, batch_id=batch_id, job_id="JOB_WARNING_ROOT",
            status="SUCCESS", capture_id=capture_id,
        )
        logical_asset_id = _insert_capture(
            connection, capture_id=capture_id,
            storage_batch_id=batch_id, active=True, ready=True,
        )
        _insert_ready_bundle(
            connection, capture_id=capture_id,
            logical_asset_id=logical_asset_id,
        )
        connection.execute(
            """INSERT INTO review_tasks(
               task_id,capture_version_id,task_type,required,status,
               reason_codes_json,severity,blocking,affected_rows_json,
               affected_columns_json,evidence_json,recommended_action,
               created_at,updated_at
               ) VALUES(
               'TASK_WARNING',?,'RECONCILIATION_REVIEW',0,'PENDING',
               '["RECONCILIATION_WARNING"]','MEDIUM',0,'[]','[]','[]','',?,?
               )""",
            (capture_id, NOW, NOW),
        )

    state = service.execution_readiness(batch_id)

    assert state["non_blocking_warning_count"] == 1
    assert state["active_blocking_task_count"] == 0
    assert state["review_required_capture_count"] == 0
    assert state["can_enter_merge"] is True


def test_streamlit_batch_monitor_consumes_service_gate():
    app = (ROOT / "app.py").read_text(encoding="utf-8")

    assert "list_monitorable_batches(" in app
    assert "execution_readiness(monitor_batch)" in app
    assert 'b.metric("执行终止"' in app
    assert 'elif readiness["can_enter_merge"]' in app
    assert "batch_id=monitor_batch,include_trash=False" not in app
    assert "当前没有待审核 Capture" not in app
