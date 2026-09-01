"""Offline four-company Stage-B revalidation tool contract tests."""
from __future__ import annotations

import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))

import tools.run_four_company_stage_b_revalidation as revalidation_tool
from metadata_registry import MetadataRegistry
from repositories.job_repository import JobRepository
from research_definition_registry import ResearchDefinitionService
from tools.run_four_company_stage_b_revalidation import (
    _arguments,
    _build_stage_b_backend,
    _database_file_modified,
    _database_file_snapshot,
    _execute_stage_b_filing,
)


class _FakeChildRepository:
    def certified_target(self,certified_link_id):
        return {
            "certified_link_id":certified_link_id,
            "source_pdf_id":"PDF_SOURCE",
        }


class _FakeCaptureRepository:
    def __init__(self,run_path):
        self.run_path=Path(run_path)

    def get(self,capture_id):
        return {
            "capture_id":capture_id,
            "run_path":str(self.run_path),
        }


class _FakeRunner:
    def __init__(self,job):
        self.job=dict(job)

    def monitor(self,batch_id):
        return {
            "batch_id":batch_id,
            "total":1,
            "complete":1,
            "counts":{self.job["status"]:1},
            "jobs":[dict(self.job)],
        }


class _FakeExecutionService:
    def __init__(self):
        self.calls=[]

    def execution_session_key(self,**kwargs):
        return "STAGEB_SYNTHETIC"

    def create_execution_batch(self,**kwargs):
        self.calls.append(dict(kwargs))
        return {
            "session_key":"STAGEB_SYNTHETIC",
            "research_batch_id":"RB_SYNTHETIC",
            "plan_ids":["PLAN_SYNTHETIC"],
            "batch_ids":["BATCH_SYNTHETIC"],
            "blocked_count":0,
        }

    def restore_execution(self,session_key):
        return {
            "session_key":session_key,
            "research_batch_id":"RB_SYNTHETIC",
            "plan_ids":["PLAN_SYNTHETIC"],
            "batch_ids":["BATCH_SYNTHETIC"],
            "all_terminal":True,
            "review_queue":[],
        }


def _link(
    certified_link_id: str,
    logical_table_id: str,
    table_classification: str,
) -> dict:
    return {
        "certified_link_id":certified_link_id,
        "logical_table_id":logical_table_id,
        "table_classification":table_classification,
        "certification_status":"CERTIFIED",
    }


def _backend(
    tmp_path: Path,
    *,
    policy: str,
    selected_logical_table_ids: list[str],
    job_status: str = "SUCCESS",
    merge_ready: bool = True,
    blockers: list[str] | None = None,
    warnings: list[str] | None = None,
    table_classification: str = "PRIMARY_TABLE",
    logical_table_id: str = "LOGICAL_PRIMARY",
    runner_job_status: str | None = None,
):
    run_path=tmp_path/"capture_run"
    run_path.mkdir()
    metadata={
        "certified_segment_manifest_validation":{
            "status":"VALID",
            "issue_codes":[],
            "validated_pairs":[{"drift_fields":[]}],
        },
        "certified_note_table_inventory_validation":{
            "status":"VALID",
            "issue_codes":[],
        },
        "selected_segment_manifest":[{
            "segment_id":"RUNTIME_SEGMENT",
            "classification":table_classification,
        }],
        "scope_issue_codes":[],
        "capture_quality_status":(
            "READY" if merge_ready else "REVIEW_REQUIRED"
        ),
        "merge_ready":merge_ready,
        "merge_blockers":list(blockers or []),
        "non_blocking_warnings":list(warnings or []),
        "capture_decision":{
            "quality_status":"READY" if merge_ready else "REVIEW_REQUIRED",
            "merge_eligible":merge_ready,
            "blocking_issues":list(blockers or []),
            "non_blocking_warnings":list(warnings or []),
        },
    }
    (run_path/"capture_metadata.json").write_text(
        json.dumps(metadata,ensure_ascii=False),encoding="utf-8",
    )
    request={
        "request_id":"REQUEST_SYNTHETIC",
        "capture_scope_contract_version":2,
        "capture_scope_policy":policy,
        "selected_logical_table_ids":selected_logical_table_ids,
        "certified_note_target_id":"LINK_SELECTED",
        "request_metadata":{
            "certified_target":{
                "certified_link_id":"LINK_SELECTED",
                "logical_table_id":logical_table_id,
                "table_classification":table_classification,
                "certified_segments":[{
                    "certified_segment_id":"CERTIFIED_SEGMENT",
                }],
            },
        },
    }
    job={
        "job_id":"JOB_SYNTHETIC",
        "batch_id":"BATCH_SYNTHETIC",
        "job_type":"TABLE_CAPTURE",
        "status":job_status,
        "target_asset_id":"CAPTURE_SYNTHETIC",
        "payload":{"capture_request":request},
        "result":{
            "capture_id":"CAPTURE_SYNTHETIC",
            "logical_asset_id":"LOGICAL_ASSET_SYNTHETIC",
            "request_id":"REQUEST_SYNTHETIC",
            "registration_confirmed":True,
        },
    }
    registry=MetadataRegistry(tmp_path/"metadata.db")
    job_repository=JobRepository(registry)
    job_repository.create(job)
    runner_job=dict(job)
    if runner_job_status is not None:
        runner_job["status"]=runner_job_status
    execution_service=_FakeExecutionService()
    return SimpleNamespace(
        registry=registry,
        job_repository=job_repository,
        child_discovery_repository=_FakeChildRepository(),
        child_capture_execution_service=execution_service,
        table_capture_runner=_FakeRunner(runner_job),
        capture_repository=_FakeCaptureRepository(run_path),
    ),execution_service


def test_default_mode_does_not_build_stage_b_backend(tmp_path) -> None:
    args=_arguments([])
    assert args.execute_stage_b is False
    assert args.capture_scope_policy=="PRIMARY_ONLY"

    def forbidden(*_args,**_kwargs):
        raise AssertionError("DEFAULT_MODE_MUST_NOT_BUILD_BACKEND")

    assert _build_stage_b_backend(
        tmp_path,False,ensure_paths=forbidden,backend_builder=forbidden,
    ) is None
    with pytest.raises(SystemExit):
        _arguments(["--capture-scope-policy","SELECTED_NOTE_TABLES"])
    selected=_arguments([
        "--execute-stage-b",
        "--capture-scope-policy","SELECTED_NOTE_TABLES",
        "--include-all-certified-supplementary",
    ])
    assert selected.execute_stage_b is True
    assert selected.include_all_certified_supplementary is True


@pytest.mark.parametrize("execute_stage_b",[False,True])
def test_main_never_opens_configured_registry_and_reports_file_facts(
    tmp_path,monkeypatch,execute_stage_b,
) -> None:
    configured_data_home=tmp_path/"configured_data_home"
    configured_data_home.mkdir()
    configured_database=configured_data_home/"metadata.db"
    configured_database.write_bytes(b"CONFIGURED_DATABASE_MUST_STAY_CLOSED")
    configured_path=configured_database.resolve()
    instantiated_paths=[]
    real_registry=MetadataRegistry

    def recording_registry(path):
        resolved=Path(path).resolve()
        instantiated_paths.append(resolved)
        if resolved==configured_path:
            raise AssertionError("CONFIGURED_REGISTRY_MUST_NOT_BE_INSTANTIATED")
        return real_registry(resolved)

    monkeypatch.setattr(
        revalidation_tool,"resolve_data_home",
        lambda _root:configured_data_home,
    )
    monkeypatch.setattr(revalidation_tool,"MetadataRegistry",recording_registry)
    monkeypatch.setattr(revalidation_tool,"FILINGS",())
    if execute_stage_b:
        def scratch_backend(scratch,enabled):
            assert enabled is True
            registry=real_registry(Path(scratch)/"metadata.db")
            return SimpleNamespace(
                registry=registry,
                research_definition_service=ResearchDefinitionService(registry),
                child_discovery_repository=object(),
                hierarchical_child_discovery_service=object(),
                table_capture_runner=SimpleNamespace(
                    shutdown=lambda wait=True:None,
                ),
            )

        monkeypatch.setattr(
            revalidation_tool,"_build_stage_b_backend",scratch_backend,
        )

    output_dir=tmp_path/("stage_b" if execute_stage_b else "default")
    argv=["--output-dir",str(output_dir),"--run-id","SAFE_REGISTRY"]
    if execute_stage_b:
        argv.append("--execute-stage-b")
    revalidation_tool.main(argv)

    report=json.loads((
        output_dir/"runs"/"SAFE_REGISTRY"/"stage_b_revalidation.json"
    ).read_text(encoding="utf-8"))
    assert configured_path not in instantiated_paths
    assert report["configured_data_home_modified"] is False
    assert report["configured_database_before"]==report[
        "configured_database_after"
    ]
    assert report["configured_database_before"]["sha256"]


def test_database_modified_flag_is_derived_from_hash_and_mtime(tmp_path) -> None:
    database=tmp_path/"metadata.db"
    database.write_bytes(b"before")
    before=_database_file_snapshot(database)
    database.write_bytes(b"after")
    after=_database_file_snapshot(database)

    assert _database_file_modified(before,before) is False
    assert _database_file_modified(before,after) is True


def test_primary_only_uses_formal_v2_execution_and_reports_pass(tmp_path) -> None:
    backend,execution_service=_backend(
        tmp_path,
        policy="PRIMARY_ONLY",
        selected_logical_table_ids=[],
    )
    result=_execute_stage_b_filing(
        backend,
        company="测试公司",report_year="2025",
        pdf_path=tmp_path/"report.pdf",
        certified_links=[
            _link("LINK_PRIMARY","LOGICAL_PRIMARY","PRIMARY_TABLE"),
            _link("LINK_SUP","LOGICAL_SUP","SUPPLEMENTARY_TABLE"),
        ],
        research_definition={
            "definition_id":"FINANCIAL_INVESTMENT_V1",
            "definition_version":"1",
        },
        certification_complete=True,
        capture_scope_policy="PRIMARY_ONLY",
        include_all_certified_supplementary=False,
        timeout_seconds=1,poll_interval_seconds=.01,
    )

    call=execution_service.calls[0]
    assert call["capture_scope_contract_version"]==2
    assert call["capture_scope_policy"]=="PRIMARY_ONLY"
    assert call["selected_logical_table_ids"]==[]
    assert call["source_pdf_map"]=={"PDF_SOURCE":tmp_path/"report.pdf"}
    assert result["status"]=="EXECUTION_PASS"
    assert result["execution_pass"] is True
    assert result["quality_pass"] is True
    assert result["jobs"][0]["manifest_validation_status"]=="VALID"
    assert result["jobs"][0]["reducer_decision_present"] is True


def test_job_audit_refreshes_terminal_status_from_registry(tmp_path) -> None:
    backend,_execution_service=_backend(
        tmp_path,
        policy="PRIMARY_ONLY",
        selected_logical_table_ids=[],
        job_status="SUCCESS",
        runner_job_status="RUNNING",
    )
    result=_execute_stage_b_filing(
        backend,
        company="测试公司",report_year="2025",
        pdf_path=tmp_path/"report.pdf",
        certified_links=[
            _link("LINK_PRIMARY","LOGICAL_PRIMARY","PRIMARY_TABLE"),
        ],
        research_definition={"definition_id":"FINANCIAL_INVESTMENT_V1"},
        certification_complete=True,
        capture_scope_policy="PRIMARY_ONLY",
        include_all_certified_supplementary=False,
        timeout_seconds=1,poll_interval_seconds=.01,
    )

    assert result["execution_pass"] is True
    assert result["jobs"][0]["job_status"]=="SUCCESS"


def test_selected_supplementary_keeps_review_required_separate(tmp_path) -> None:
    selected_ids=["LOGICAL_SUP_A"]
    backend,execution_service=_backend(
        tmp_path,
        policy="SELECTED_NOTE_TABLES",
        selected_logical_table_ids=selected_ids,
        job_status="REVIEW_REQUIRED",
        merge_ready=False,
        blockers=["HEADER_TOPOLOGY_UNRESOLVED"],
        warnings=["TOTAL_CHILD_SUM_MISMATCH"],
        table_classification="SUPPLEMENTARY_TABLE",
        logical_table_id="LOGICAL_SUP_A",
    )
    result=_execute_stage_b_filing(
        backend,
        company="测试公司",report_year="2025",
        pdf_path=tmp_path/"report.pdf",
        certified_links=[
            _link("LINK_PRIMARY","LOGICAL_PRIMARY","PRIMARY_TABLE"),
            _link("LINK_SUP_A","LOGICAL_SUP_A","SUPPLEMENTARY_TABLE"),
        ],
        research_definition={"definition_id":"FINANCIAL_INVESTMENT_V1"},
        certification_complete=True,
        capture_scope_policy="SELECTED_NOTE_TABLES",
        include_all_certified_supplementary=True,
        timeout_seconds=1,poll_interval_seconds=.01,
    )

    call=execution_service.calls[0]
    assert call["selected_logical_table_ids"]==selected_ids
    assert result["execution_pass"] is True
    assert result["quality_pass"] is False
    assert result["review_required_count"]==1
    assert result["batch_scope_union_matches"] is True
    assert result["jobs"][0]["merge_blockers"]==[
        "HEADER_TOPOLOGY_UNRESOLVED"
    ]
    assert result["jobs"][0]["non_blocking_warnings"]==[
        "TOTAL_CHILD_SUM_MISMATCH"
    ]


def test_selected_supplementary_batch_union_requires_every_selected_table(
    tmp_path,
) -> None:
    backend,_execution_service=_backend(
        tmp_path,
        policy="SELECTED_NOTE_TABLES",
        selected_logical_table_ids=["LOGICAL_SUP_A"],
        table_classification="SUPPLEMENTARY_TABLE",
        logical_table_id="LOGICAL_SUP_A",
    )
    result=_execute_stage_b_filing(
        backend,
        company="测试公司",report_year="2025",
        pdf_path=tmp_path/"report.pdf",
        certified_links=[
            _link("LINK_PRIMARY","LOGICAL_PRIMARY","PRIMARY_TABLE"),
            _link("LINK_SUP_A","LOGICAL_SUP_A","SUPPLEMENTARY_TABLE"),
            _link("LINK_SUP_B","LOGICAL_SUP_B","SUPPLEMENTARY_TABLE"),
        ],
        research_definition={"definition_id":"FINANCIAL_INVESTMENT_V1"},
        certification_complete=True,
        capture_scope_policy="SELECTED_NOTE_TABLES",
        include_all_certified_supplementary=True,
        timeout_seconds=1,poll_interval_seconds=.01,
    )

    assert result["status"]=="EXECUTION_FAILED"
    assert result["batch_scope_union_matches"] is False
    assert result["batch_expected_selected_logical_table_ids"]==[
        "LOGICAL_SUP_A","LOGICAL_SUP_B",
    ]
    assert result["batch_actual_selected_logical_table_ids"]==[
        "LOGICAL_SUP_A",
    ]


def test_incomplete_certification_never_submits_stage_b(tmp_path) -> None:
    result=_execute_stage_b_filing(
        SimpleNamespace(),
        company="测试公司",report_year="2025",
        pdf_path=tmp_path/"report.pdf",
        certified_links=[],
        research_definition={},
        certification_complete=False,
        capture_scope_policy="PRIMARY_ONLY",
        include_all_certified_supplementary=False,
        timeout_seconds=1,poll_interval_seconds=.01,
    )
    assert result["status"]=="BLOCKED_INCOMPLETE_CERTIFICATION"
    assert result["execution_pass"] is False
    assert result["jobs"]==[]


def test_manifest_drift_is_reported_as_execution_failure(tmp_path) -> None:
    backend,_execution_service=_backend(
        tmp_path,
        policy="PRIMARY_ONLY",
        selected_logical_table_ids=[],
    )
    metadata_path=(
        backend.capture_repository.run_path/"capture_metadata.json"
    )
    metadata=json.loads(metadata_path.read_text(encoding="utf-8"))
    metadata["certified_segment_manifest_validation"]={
        "status":"REVIEW_REQUIRED",
        "issue_codes":["CERTIFIED_SEGMENT_MANIFEST_DRIFT"],
        "validated_pairs":[{"drift_fields":["bbox","header_signature"]}],
    }
    metadata_path.write_text(
        json.dumps(metadata,ensure_ascii=False),encoding="utf-8",
    )

    result=_execute_stage_b_filing(
        backend,
        company="测试公司",report_year="2025",
        pdf_path=tmp_path/"report.pdf",
        certified_links=[
            _link("LINK_PRIMARY","LOGICAL_PRIMARY","PRIMARY_TABLE"),
        ],
        research_definition={"definition_id":"FINANCIAL_INVESTMENT_V1"},
        certification_complete=True,
        capture_scope_policy="PRIMARY_ONLY",
        include_all_certified_supplementary=False,
        timeout_seconds=1,poll_interval_seconds=.01,
    )
    assert result["execution_pass"] is False
    assert result["status"]=="EXECUTION_FAILED"
    assert result["jobs"][0]["manifest_drift_fields"]==[
        "bbox","header_signature"
    ]
    assert result["jobs"][0]["manifest_issue_codes"]==[
        "CERTIFIED_SEGMENT_MANIFEST_DRIFT"
    ]
