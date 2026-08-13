"""v6.11 authoritative capture-completion state-chain contracts.

All tests use a temporary MetadataRegistry.  They must never access the
configured/production DATA_HOME.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from capture_models import CaptureMode, CaptureRequest, ResolvedCaptureTarget
from capture_orchestrator import CaptureOrchestrator
from metadata_registry import MetadataRegistry
from repositories.asset_governance_repository import AssetGovernanceRepository
from repositories.capture_repository import CaptureRepository
from services.asset_governance_services import (
    AssetLifecycleService,
    LogicalAssetService,
    ReviewInboxService,
)
from services.capture_completion_service import CaptureCompletionService
from services.capture_decision_reducer import CaptureDecisionReducer
from services.review_task_service import ReviewTaskService


def _ready_evidence(**overrides) -> dict:
    result = {
        "boundary_status": "HARD_BOUNDARY_CONFIRMED",
        "header_dimension_status": "AUTO_CONFIRMED",
        "unit": "万元",
        "columns": [
            {
                "role": "VALUE",
                "raw_header_path": "2023年12月31日",
                "data_year": "2023",
                "period_type": "CURRENT",
                "statement_scope": "CONSOLIDATED",
                "unit": "万元",
            }
        ],
        "stats": {
            "boundary_reason": "next_note_74",
            "boundary_evidence": {"method": "NEXT_NOTE_ORDINAL"},
            "boundary_confidence": "HIGH",
            "v69_header_topology": {"consistent": True},
            "v69_reconciliation": {"status": "PASS"},
            "mixed_cell_count": 0,
        },
        "rows": [
            {
                "row_order": 1,
                "row_role": "DETAIL",
                "raw_item": "债权投资",
                "cells": [{
                    "raw": "100",
                    "cell_role": "VALUE",
                    "column_ordinal": 0,
                }],
            }
        ],
    }
    result.update(overrides)
    return result


def _review_evidence() -> dict:
    result = _ready_evidence(boundary_status="")
    result["stats"] = {
        **result["stats"],
        "boundary_reason": "boundary_unresolved",
        "boundary_evidence": {"method": "NO_PEER_HEADING_FOUND"},
        "boundary_confidence": "",
    }
    return result


def _certified_bbox_evidence() -> dict:
    validation = {
        "status": "VALID",
        "manifest_status": "CERTIFIED_SEGMENT_MANIFEST",
        "issue_codes": [],
        "certified_segments": [{
            "certified_segment_id": "CSEG_SHARED",
            "classification": "PRIMARY_TABLE",
            "certification_status": "CERTIFIED",
        }],
        "discovered_segments": [{
            "segment_id": "SEG_SHARED",
            "classification": "PRIMARY_TABLE",
        }],
        "validated_pairs": [{
            "certified_segment_id": "CSEG_SHARED",
            "discovered_segment_id": "SEG_SHARED",
            "page": {"match": True},
            "classification": {"match": True},
            "header": {"match": True},
            "period": {"match": True},
            "lane": {"match": True},
            "continuation": {"match": True},
            "bbox": {"match": True},
            "drift_fields": [],
        }],
    }
    inventory_validation = {"status": "VALID", "issue_codes": []}
    evidence = _ready_evidence(boundary_status="")
    evidence["rows"][0]["physical_segment_id"] = "SEG_SHARED"
    evidence["stats"] = {
        **evidence["stats"],
        "boundary_reason": "certified_segment_bbox",
        "v69_reconciliation": {"status": "NOT_TESTABLE"},
        "capture_scope_contract_version": 2,
        "capture_scope_policy": "PRIMARY_ONLY",
        "selected_segment_manifest": [{
            "segment_id": "SEG_SHARED",
            "classification": "PRIMARY_TABLE",
        }],
        "physical_table_segments": [{
            "segment_id": "SEG_SHARED",
            "classification": "PRIMARY_TABLE",
        }],
        "physical_segment_ids": ["SEG_SHARED"],
        "certified_segment_manifest_validation": validation,
        "certified_note_table_inventory_validation": inventory_validation,
    }
    return evidence


def _identity(**overrides) -> dict:
    result = {
        "company_id": "中国平安",
        "filing_type": "ANNUAL_REPORT",
        "report_year": "2023",
        "statement_scope": "CONSOLIDATED",
        "research_project_id": "PROJECT_1",
        "research_task_id": "TASK_1",
        "research_batch_id": "RBATCH_1",
        "research_definition_id": "FINANCIAL_INVESTMENT_V1",
        "definition_version": "1.0",
        "table_family_id": "FINANCIAL_INVESTMENT",
        "member_table_id": "debt_investment",
        "logical_source_role": "NOTE_DETAIL",
        "pdf_name": "fixture.pdf",
    }
    result.update(overrides)
    return result


def test_reducer_blocks_identity_before_merge_decision() -> None:
    decision = CaptureDecisionReducer().reduce(
        machine_evidence=_ready_evidence(),
        capture_version=_identity(
            research_definition_id="",
            definition_version="",
            table_family_id="",
            statement_scope="UNKNOWN",
            is_current=True,
            registration_status="REGISTERED",
        ),
        lifecycle_state={
            "registration_status": "REGISTERED",
            "asset_status": "ACTIVE",
        },
    )

    assert decision.blocking is True
    assert decision.blocking_issues
    assert decision.quality_status == "REVIEW_REQUIRED"
    assert decision.review_status == "PENDING"
    assert decision.asset_status == "ACTIVE"
    assert decision.certified is False
    assert decision.review_inbox_eligible is True
    assert decision.merge_eligible is False
    assert decision.bundle_status == "REVIEW_REQUIRED"


def test_reducer_ready_state_is_internally_consistent() -> None:
    decision = CaptureDecisionReducer().reduce(
        machine_evidence=_certified_bbox_evidence(),
        capture_version=_identity(
            is_current=True,
            registration_status="REGISTERED",
        ),
        lifecycle_state={
            "registration_status": "REGISTERED",
            "asset_status": "ACTIVE",
        },
    )

    assert decision.blocking is False
    assert decision.blocking_issues == []
    assert decision.quality_status == "READY"
    assert decision.review_status == "CONFIRMED_AUTO"
    assert decision.asset_status == "CERTIFIED_ACTIVE"
    assert decision.certified is True
    assert decision.review_inbox_eligible is False
    assert decision.merge_eligible is True
    assert decision.bundle_status == "READY"


def _orchestrator(tmp_path: Path, evidence: dict):
    registry = MetadataRegistry(tmp_path / "metadata.db")
    governance = AssetGovernanceRepository(registry)
    captures = CaptureRepository(registry)
    logical = LogicalAssetService(governance, "v6.11")
    lifecycle = AssetLifecycleService(governance, "v6.11")
    inbox = ReviewInboxService(governance)
    review_tasks = ReviewTaskService(governance, "v6.11")
    completion = CaptureCompletionService(
        governance_repository=governance,
        review_task_service=review_tasks,
        producer_version="v6.11",
    )

    run_dir = tmp_path / "capture_run"
    run_dir.mkdir()
    (run_dir / "table_capture_result.json").write_text(
        json.dumps(evidence, ensure_ascii=False), encoding="utf-8"
    )
    (run_dir / "capture_metadata.json").write_text(
        json.dumps({
            "capture_quality_status": "UNASSESSED",
            "review_status": "PENDING",
            "merge_ready": False,
            "merge_blockers": ["PENDING_CAPTURE_COMPLETION"],
        }, ensure_ascii=False),
        encoding="utf-8",
    )

    def executor(request, target):
        registry.upsert_capture(
            {
                "capture_id": "CAP_STATE_CHAIN",
                "run_path": str(run_dir),
                "pdf_name": "fixture.pdf",
                "source_pdf_display": "fixture.pdf",
                "company": "中国平安",
                "document_year": "2023",
                "table_query": "债权投资",
                "table_family_id": request.table_family_id,
                "producer_version": "v6.11",
                # A compatibility projection only.  Completion must replace it.
                "merge_ready": False,
            }
        )
        return {
            "capture_id": "CAP_STATE_CHAIN",
            "run_path": str(run_dir),
            "result": evidence,
            "metadata": {
                "pdf_name": "fixture.pdf",
                "company": "中国平安",
                "document_year": "2023",
            },
        }

    orchestrator = CaptureOrchestrator(
        repository=governance,
        strategies=None,
        executor=executor,
        capture_repository=captures,
        logical_asset_service=logical,
        lifecycle_service=lifecycle,
        review_inbox_service=inbox,
        completion_service=completion,
    )
    return registry, governance, review_tasks, orchestrator


def _request() -> CaptureRequest:
    return CaptureRequest.new(
        capture_mode=CaptureMode.CERTIFIED_TARGET,
        source_pdf_path="C:/isolated-fixture.pdf",
        source_pdf_id="PDF_FIXTURE",
        research_project_id="PROJECT_1",
        research_task_id="TASK_1",
        research_batch_id="RBATCH_1",
        research_definition_id="FINANCIAL_INVESTMENT_V1",
        definition_version="1.0",
        table_family_id="FINANCIAL_INVESTMENT",
        member_table_id="debt_investment",
        request_metadata={
            "company": "中国平安",
            "report_year": "2023",
            "statement_scope": "CONSOLIDATED",
            "member_table_role": "NOTE_DETAIL",
        },
    )


def _target() -> ResolvedCaptureTarget:
    return ResolvedCaptureTarget.new(
        source_pdf_id="PDF_FIXTURE",
        strategy_id="TEST_CERTIFIED",
        target_type="NOTE_TABLE",
        start_page=1,
        end_page=1,
        title="债权投资",
        statement_scope="CONSOLIDATED",
        confidence=1.0,
        certification_status="CERTIFIED",
    )


def test_capture_completion_materializes_review_before_any_ui(tmp_path: Path) -> None:
    registry, _, review_tasks, orchestrator = _orchestrator(
        tmp_path, _review_evidence()
    )

    outcome = orchestrator.execute(_request(), _target())
    assert outcome["status"] == "REVIEW_REQUIRED"
    assert outcome["decision"]["merge_eligible"] is False

    with registry.connect() as conn:
        version = conn.execute(
            """SELECT quality_status,review_status,asset_status
               FROM capture_versions WHERE capture_id='CAP_STATE_CHAIN'"""
        ).fetchone()
        issue_count = conn.execute(
            """SELECT COUNT(*) n FROM review_issues
               WHERE capture_version_id='CAP_STATE_CHAIN' AND status='OPEN'"""
        ).fetchone()["n"]
        task_count = conn.execute(
            """SELECT COUNT(*) n FROM review_tasks
               WHERE capture_version_id='CAP_STATE_CHAIN'"""
        ).fetchone()["n"]
        queue_count = conn.execute(
            """SELECT COUNT(*) n FROM review_queue
               WHERE capture_id='CAP_STATE_CHAIN' AND status='PENDING'"""
        ).fetchone()["n"]

    assert dict(version) == {
        "quality_status": "REVIEW_REQUIRED",
        "review_status": "PENDING",
        "asset_status": "ACTIVE",
    }
    assert issue_count >= 1
    assert task_count >= 1
    assert queue_count == 1
    projected = json.loads(
        (tmp_path / "capture_run" / "capture_metadata.json").read_text(
            encoding="utf-8"
        )
    )
    assert projected["capture_quality_status"] == "REVIEW_REQUIRED"
    assert projected["review_status"] == "PENDING"
    assert projected["merge_ready"] is False
    assert "PENDING_CAPTURE_COMPLETION" not in projected["merge_blockers"]

    # The read model must not mutate rows.
    with registry.connect() as conn:
        before = tuple(
            conn.execute(
                f"SELECT COUNT(*) FROM {table}"
            ).fetchone()[0]
            for table in ("review_issues", "review_tasks", "review_queue")
        )
    review_tasks.summary("CAP_STATE_CHAIN")
    with registry.connect() as conn:
        after = tuple(
            conn.execute(
                f"SELECT COUNT(*) FROM {table}"
            ).fetchone()[0]
            for table in ("review_issues", "review_tasks", "review_queue")
        )
    assert after == before


def test_capture_completion_ready_is_merge_eligible_without_inbox(tmp_path: Path) -> None:
    registry, governance, _, orchestrator = _orchestrator(
        tmp_path, _certified_bbox_evidence()
    )

    outcome = orchestrator.execute(_request(), _target())
    assert outcome["status"] == "SUCCESS"
    assert outcome["decision"]["blocking"] is False
    assert outcome["decision"]["merge_eligible"] is True

    detail = governance.capture_detail("CAP_STATE_CHAIN")
    assert detail["quality_status"] == "READY"
    assert detail["review_status"] == "CONFIRMED_AUTO"
    assert detail["asset_status"] == "CERTIFIED_ACTIVE"
    assert governance.current_merge_eligible()[0]["capture_id"] == "CAP_STATE_CHAIN"

    with registry.connect() as conn:
        queue_count = conn.execute(
            "SELECT COUNT(*) n FROM review_queue WHERE capture_id='CAP_STATE_CHAIN' AND status='PENDING'"
        ).fetchone()["n"]
        legacy_merge = conn.execute(
            "SELECT merge_ready FROM captures WHERE capture_id='CAP_STATE_CHAIN'"
        ).fetchone()["merge_ready"]
    assert queue_count == 0
    assert legacy_merge == 1
    projected = json.loads(
        (tmp_path / "capture_run" / "capture_metadata.json").read_text(
            encoding="utf-8"
        )
    )
    assert projected["capture_quality_status"] == "READY"
    assert projected["quality_status"] == "READY"
    assert projected["review_status"] == "CONFIRMED_AUTO"
    assert projected["merge_ready"] is True
    assert projected["merge_blockers"] == []
    assert projected["boundary_status"] == "HARD_BOUNDARY_CONFIRMED"
    assert projected["header_dimension_status"] == "AUTO_CONFIRMED"


def test_capture_completion_rolls_back_every_projection_on_failure(
    tmp_path: Path,monkeypatch,
) -> None:
    registry, governance, _, orchestrator = _orchestrator(
        tmp_path,_review_evidence(),
    )

    def fail_bundle_recalculation(conn,capture_id):
        raise RuntimeError("forced completion rollback")

    monkeypatch.setattr(
        governance,
        "_recalculate_bundle_status_in_tx",
        fail_bundle_recalculation,
    )
    with pytest.raises(RuntimeError,match="forced completion rollback"):
        orchestrator.execute(_request(),_target())

    with registry.connect() as conn:
        counts = {
            table: conn.execute(
                f"SELECT COUNT(*) n FROM {table}"
            ).fetchone()["n"]
            for table in (
                "logical_assets",
                "capture_versions",
                "review_issues",
                "review_tasks",
                "review_queue",
            )
        }
        legacy_merge = conn.execute(
            """SELECT merge_ready FROM captures
               WHERE capture_id='CAP_STATE_CHAIN'"""
        ).fetchone()["merge_ready"]
    assert counts == {
        "logical_assets": 0,
        "capture_versions": 0,
        "review_issues": 0,
        "review_tasks": 0,
        "review_queue": 0,
    }
    assert legacy_merge == 0
    stale_projection = json.loads(
        (tmp_path / "capture_run" / "capture_metadata.json").read_text(
            encoding="utf-8"
        )
    )
    assert stale_projection["merge_blockers"] == ["PENDING_CAPTURE_COMPLETION"]


def test_capture_completion_projects_secondary_child_registry_state(
    tmp_path: Path,
) -> None:
    registry = MetadataRegistry(tmp_path / "metadata.db")
    governance = AssetGovernanceRepository(registry)
    captures = CaptureRepository(registry)
    review_tasks = ReviewTaskService(governance, "v6.11")
    completion = CaptureCompletionService(
        governance_repository=governance,
        review_task_service=review_tasks,
        producer_version="v6.11",
    )
    child_dir = tmp_path / "held_to_maturity_b2"
    child_dir.mkdir()
    (child_dir / "capture_metadata.json").write_text(
        json.dumps({
            "capture_quality_status": "UNASSESSED",
            "merge_ready": False,
            "merge_blockers": ["PENDING_CAPTURE_COMPLETION"],
        }, ensure_ascii=False),
        encoding="utf-8",
    )
    registry.upsert_capture({
        "capture_id": "CAP_HELD_B2",
        "run_path": str(child_dir),
        "pdf_name": "fixture.pdf",
        "source_pdf_display": "fixture.pdf",
        "company": "中国人寿",
        "document_year": "2023",
        "table_query": "持有至到期投资 2022",
        "producer_version": "v6.11",
        "merge_ready": False,
    })
    record = captures.get("CAP_HELD_B2")
    assert record is not None
    outcome = completion.complete(
        capture_id="CAP_HELD_B2",
        machine_evidence=_certified_bbox_evidence(),
        metadata=_identity(
            company_id="中国人寿",
            member_table_id="held_to_maturity::B2",
            run_path=str(child_dir),
            table_block_id="B2",
            block_order=1,
        ),
        capture_record=record,
        research_definition={
            "definition_id": "FINANCIAL_INVESTMENT_V1",
            "definition_version": "1.0",
        },
    )
    assert outcome["metadata_projection"]["status"] == "OK"
    projected = json.loads(
        (child_dir / "capture_metadata.json").read_text(encoding="utf-8")
    )
    assert projected["capture_quality_status"] == "READY"
    assert projected["review_status"] == "CONFIRMED_AUTO"
    assert projected["merge_ready"] is True
    assert projected["merge_blockers"] == []
    detail = governance.capture_detail("CAP_HELD_B2")
    assert detail["quality_status"] == projected["capture_quality_status"]
    assert detail["review_status"] == projected["review_status"]


def test_certified_bbox_completion_closes_root_and_derived_child(
    tmp_path: Path,
) -> None:
    registry = MetadataRegistry(tmp_path / "metadata.db")
    governance = AssetGovernanceRepository(registry)
    captures = CaptureRepository(registry)
    completion = CaptureCompletionService(
        governance_repository=governance,
        review_task_service=ReviewTaskService(governance, "v6.11"),
        producer_version="v6.11",
    )
    evidence = _certified_bbox_evidence()
    stats = evidence["stats"]

    for suffix, block_order in (("ROOT", 0), ("B2", 1)):
        capture_id = f"CAP_CERTIFIED_{suffix}"
        child_dir = tmp_path / suffix.lower()
        child_dir.mkdir()
        (child_dir / "capture_metadata.json").write_text(
            json.dumps({
                "capture_quality_status": "UNASSESSED",
                "merge_ready": False,
                "merge_blockers": ["PENDING_CAPTURE_COMPLETION"],
            }, ensure_ascii=False),
            encoding="utf-8",
        )
        registry.upsert_capture({
            "capture_id": capture_id,
            "run_path": str(child_dir),
            "pdf_name": "fixture.pdf",
            "source_pdf_display": "fixture.pdf",
            "company": "中国平安",
            "document_year": "2023",
            "table_query": f"债权投资 {suffix}",
            "producer_version": "v6.11",
            "merge_ready": False,
        })
        record = captures.get(capture_id)
        assert record is not None
        outcome = completion.complete(
            capture_id=capture_id,
            machine_evidence=json.loads(json.dumps(evidence)),
            metadata=_identity(
                run_path=str(child_dir),
                table_block_id=suffix,
                block_order=block_order,
                capture_scope_contract_version=2,
                capture_scope_policy="PRIMARY_ONLY",
                selected_segment_manifest=stats["selected_segment_manifest"],
                certified_segment_manifest_validation=stats[
                    "certified_segment_manifest_validation"
                ],
                certified_note_table_inventory_validation=stats[
                    "certified_note_table_inventory_validation"
                ],
            ),
            capture_record=record,
            research_definition={
                "definition_id": "FINANCIAL_INVESTMENT_V1",
                "definition_version": "1.0",
            },
        )

        decision = outcome["decision"]
        assert decision.quality_status == "READY"
        assert decision.merge_eligible is True
        assert decision.decision_evidence[
            "boundary_decision"
        ]["sub_decision"] == "CERTIFIED_SEGMENT_MANIFEST"
        projected = json.loads(
            (child_dir / "capture_metadata.json").read_text(encoding="utf-8")
        )
        assert projected["capture_quality_status"] == "READY"
        assert projected["review_status"] == "CONFIRMED_AUTO"
        assert projected["merge_ready"] is True
        assert projected["merge_blockers"] == []
        detail = governance.capture_detail(capture_id)
        assert detail["quality_status"] == "READY"
        assert detail["review_status"] == "CONFIRMED_AUTO"


def test_stale_boundary_reassessment_closes_all_state_projections(
    tmp_path: Path,
) -> None:
    registry, governance, review_tasks, orchestrator = _orchestrator(
        tmp_path, _review_evidence()
    )
    first = orchestrator.execute(_request(), _target())
    assert first["status"] == "REVIEW_REQUIRED"

    now = "2026-07-29T00:00:00+08:00"
    with registry.connect() as conn:
        conn.execute(
            """INSERT INTO note_containers(
               container_id,source_pdf_id,source_pdf_sha256,source_pdf_path,
               note_reference,note_title,start_pdf_page,end_pdf_page,
               context_json,layout_graph_json,created_at
               ) VALUES('CONT_STATE',NULL,'','C:/isolated-fixture.pdf','','',1,1,'{}','{}',?)""",
            (now,),
        )
        conn.execute(
            """INSERT INTO table_blocks(
               block_id,container_id,block_order,block_title,block_role,
               start_pdf_page,end_pdf_page,bbox_json,header_topology_json,
               semantic_graph_json,reconciliation_json,quality_status,status,
               evidence_json,created_at
               ) VALUES(
               'BLOCK_STATE','CONT_STATE',0,'债权投资','NOTE_DETAIL',1,1,
               '{}','{}','{}','{}','REVIEW_REQUIRED','CAPTURED','{}',?)""",
            (now,),
        )
        conn.execute(
            """INSERT INTO capture_bundles(
               bundle_id,request_id,container_id,table_family_id,member_table_id,
               status,payload_json,created_at,updated_at
               ) VALUES(
               'BUNDLE_STATE',NULL,'CONT_STATE','FINANCIAL_INVESTMENT',
               'debt_investment','REVIEW_REQUIRED','{}',?,?)""",
            (now,now),
        )
        conn.execute(
            """INSERT INTO capture_bundle_children(
               bundle_id,block_id,capture_id,logical_asset_id,child_order,
               status,payload_json,created_at
               ) VALUES(
               'BUNDLE_STATE','BLOCK_STATE','CAP_STATE_CHAIN',?,0,
               'CAPTURED','{}',?)""",
            (first["logical_asset_id"],now),
        )

    detail = governance.capture_detail("CAP_STATE_CHAIN")
    result_path = Path(detail["run_path"]) / "table_capture_result.json"
    result_path.write_text(
        json.dumps(_certified_bbox_evidence(), ensure_ascii=False), encoding="utf-8"
    )

    stats = review_tasks.reassess_stale_boundary_issues(dry_run=False)
    assert stats["resolved_by_rule_upgrade"] >= 1
    assert stats["captures_quality_upgraded"] == 1

    detail = governance.capture_detail("CAP_STATE_CHAIN")
    assert detail["quality_status"] == "READY"
    assert detail["review_status"] == "CONFIRMED_AUTO"
    assert detail["asset_status"] == "CERTIFIED_ACTIVE"
    assert governance.current_merge_eligible()[0]["capture_id"] == "CAP_STATE_CHAIN"

    with registry.connect() as conn:
        issue = conn.execute(
            """SELECT status,decision FROM review_issues
               WHERE capture_version_id='CAP_STATE_CHAIN'
                 AND reason_code='PDF_BOUNDARY_UNCERTAIN'"""
        ).fetchone()
        queue = conn.execute(
            """SELECT status FROM review_queue
               WHERE capture_id='CAP_STATE_CHAIN'"""
        ).fetchone()
        bundle = conn.execute(
            """SELECT status FROM capture_bundles
               WHERE bundle_id='BUNDLE_STATE'"""
        ).fetchone()
        legacy_merge = conn.execute(
            """SELECT merge_ready FROM captures
               WHERE capture_id='CAP_STATE_CHAIN'"""
        ).fetchone()["merge_ready"]
    assert dict(issue) == {
        "status": "RESOLVED",
        "decision": "RESOLVED_BY_RULE_UPGRADE",
    }
    assert queue["status"] == "RESOLVED"
    assert bundle["status"] == "READY"
    assert legacy_merge == 1


def test_render_paths_are_read_only_and_backend_does_not_bootstrap() -> None:
    inspection = (ROOT / "components" / "capture_inspection_panel.py").read_text(
        encoding="utf-8"
    )
    review_panel = (ROOT / "components" / "review_action_panel.py").read_text(
        encoding="utf-8"
    )
    backend = (ROOT / "backend_context.py").read_text(encoding="utf-8")
    bridge = (ROOT / "registry_bridge.py").read_text(encoding="utf-8")

    assert "review_task_service.materialize(" not in inspection
    assert "review_task_service.materialize(" not in review_panel
    assert "logical_assets.bootstrap_existing()" not in backend
    assert "capture_readiness(" not in bridge
