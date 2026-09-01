"""Fresh Stage-B inventory, certification, and optional Capture revalidation.

The default harness uses the production Discovery/Inventory/Certification
services against a private task database and does not create Capture amounts.
With ``--execute-stage-b`` it reuses that same scratch registry and invokes the
formal ``ChildCaptureExecutionService`` path.  It never writes the configured
DATA_HOME.  Reports separate automatic certification, execution integrity,
and reducer quality/merge readiness for the 12 target filings.
"""
from __future__ import annotations

import argparse
import csv
import datetime as dt
import hashlib
import json
import sys
import time
from pathlib import Path
from typing import Any, Callable

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from data_home import resolve_data_home
from discovery_registry import DiscoveryRegistry
from hierarchical_child_discovery import (
    ChildDiscoveryRepository,
    FinancialNoteIndexService,
    HierarchicalChildTableDiscoveryService,
)
from metadata_registry import MetadataRegistry
from research_definition_registry import ResearchDefinitionService
from generic_discovery_engine import GenericDiscoveryService
from services.discovery_service import DiscoveryService
from capture_models import CAPTURE_SCOPE_CONTRACT_VERSION, CaptureScopePolicy
from repositories.job_repository import JobRepository

DEFAULT_OUT = Path(
    r"C:\dev\AXA_research\output\_agent_runs\four_company_child_cache_reset"
)
DOCU = Path(r"C:\dev\AXA_research\docu")
FILINGS = (
    ("中国平安", "2023", "中国平安2023年报.pdf"), ("中国平安", "2024", "中国平安2024年报.pdf"), ("中国平安", "2025", "中国平安2025年报.pdf"),
    ("新华保险", "2023", "新华保险2023年报.pdf"), ("新华保险", "2024", "新华保险2024年报.pdf"), ("新华保险", "2025", "新华保险2025年报.pdf"),
    ("中国太保", "2023", "中国太保2023年报.pdf"), ("中国太保", "2024", "中国太保2024年报.pdf"), ("中国太保", "2025", "中国太保2025年报.pdf"),
    ("中国人寿", "2023", "中国人寿2023年年度报告.pdf"), ("中国人寿", "2024", "中国人寿2024年年度报告.pdf"), ("中国人寿", "2025", "中国人寿2025年年度报告.pdf"),
)
STAGE_B_SCOPE_POLICIES = (
    CaptureScopePolicy.PRIMARY_ONLY.value,
    CaptureScopePolicy.SELECTED_NOTE_TABLES.value,
)
STAGE_B_EXECUTED_JOB_STATUSES = frozenset({"SUCCESS", "REVIEW_REQUIRED"})
STAGE_B_TERMINAL_JOB_STATUSES = frozenset({
    "SUCCESS", "REVIEW_REQUIRED", "FAILED", "CANCELLED", "SKIPPED",
})


def _database_file_snapshot(database_path: Path) -> dict[str, Any]:
    path = Path(database_path).resolve()
    if not path.is_file():
        return {
            "path":str(path),
            "exists":False,
            "size_bytes":None,
            "mtime_ns":None,
            "sha256":None,
        }
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    stat = path.stat()
    return {
        "path":str(path),
        "exists":True,
        "size_bytes":int(stat.st_size),
        "mtime_ns":int(stat.st_mtime_ns),
        "sha256":digest.hexdigest(),
    }


def _database_file_modified(
    before: dict[str, Any],
    after: dict[str, Any],
) -> bool:
    fields = ("path", "exists", "size_bytes", "mtime_ns", "sha256")
    return any(before.get(field) != after.get(field) for field in fields)


def choose_occurrence(rows: list[dict]) -> dict | None:
    scoped = [row for row in rows if str(row.get("scope") or "") == "CONSOLIDATED"]
    candidates = scoped or rows
    if not candidates:
        return None
    # Current main-statement resolver orders formal, structurally-complete
    # occurrences first.  The report retains its identity for review.
    return max(candidates, key=lambda row: (len(row.get("child_rows") or []), bool(row.get("statement_pdf_page_index"))))


def member_contract(
    definitions: ResearchDefinitionService,
    family_id: str,
    concept: dict,
) -> dict:
    member_id = str(concept.get("canonical_concept_id") or "")
    registry_member = next(
        (
            member for member in definitions.members(family_id)
            if str(member.get("member_id") or "") == member_id
        ),
        None,
    )
    payload = dict((registry_member or {}).get("payload") or {})
    canonical_title = str(
        (registry_member or {}).get("display_name")
        or concept.get("canonical_display_name")
        or concept.get("raw_label")
        or member_id
    )
    aliases = list(dict.fromkeys([
        canonical_title,
        *(payload.get("aliases") or []),
        *(concept.get("concept_aliases") or []),
        str(concept.get("raw_label") or ""),
    ]))
    return {
        "member_table_id":member_id or str(concept.get("raw_label") or ""),
        "canonical_title":canonical_title,
        "exact_aliases":[value for value in aliases if value],
        "certified_company_aliases":[],
    }


def _arguments(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--run-id", default="")
    parser.add_argument("--company", default="")
    parser.add_argument("--year", default="")
    parser.add_argument("--execute-stage-b", action="store_true")
    parser.add_argument(
        "--capture-scope-policy",
        choices=STAGE_B_SCOPE_POLICIES,
        default=CaptureScopePolicy.PRIMARY_ONLY.value,
    )
    parser.add_argument(
        "--include-all-certified-supplementary",
        action="store_true",
    )
    parser.add_argument(
        "--stage-b-timeout-seconds",
        type=float,
        default=1800.0,
    )
    parser.add_argument(
        "--stage-b-poll-interval-seconds",
        type=float,
        default=1.0,
    )
    args = parser.parse_args(argv)
    if not args.execute_stage_b and (
        args.capture_scope_policy != CaptureScopePolicy.PRIMARY_ONLY.value
        or args.include_all_certified_supplementary
    ):
        parser.error("--execute-stage-b is required for Capture scope options")
    if (
        args.capture_scope_policy
        == CaptureScopePolicy.SELECTED_NOTE_TABLES.value
        and not args.include_all_certified_supplementary
    ):
        parser.error(
            "SELECTED_NOTE_TABLES requires "
            "--include-all-certified-supplementary"
        )
    if (
        args.capture_scope_policy == CaptureScopePolicy.PRIMARY_ONLY.value
        and args.include_all_certified_supplementary
    ):
        parser.error(
            "--include-all-certified-supplementary requires "
            "SELECTED_NOTE_TABLES"
        )
    if args.stage_b_timeout_seconds <= 0:
        parser.error("--stage-b-timeout-seconds must be positive")
    if args.stage_b_poll_interval_seconds <= 0:
        parser.error("--stage-b-poll-interval-seconds must be positive")
    return args


def _build_stage_b_backend(
    scratch: Path,
    enabled: bool,
    *,
    ensure_paths: Callable[[Path, Path], dict[str, Path]] | None = None,
    backend_builder: Callable[[dict[str, Path]], Any] | None = None,
) -> Any | None:
    """Build the production service graph only for explicit Stage-B runs."""
    if not enabled:
        return None
    if ensure_paths is None:
        from data_home import ensure_data_home

        ensure_paths = ensure_data_home
    if backend_builder is None:
        from backend_context import build_backend_services

        backend_builder = build_backend_services
    paths = ensure_paths(scratch, ROOT / "metric_aliases.json")
    return backend_builder(paths)


def _certified_supplementary_ids(
    certified_links: list[dict[str, Any]],
) -> list[str]:
    return sorted({
        str(link.get("logical_table_id") or "").strip()
        for link in certified_links
        if str(link.get("certification_status") or "").upper() == "CERTIFIED"
        and str(link.get("table_classification") or "").upper()
        == "SUPPLEMENTARY_TABLE"
        and str(link.get("logical_table_id") or "").strip()
    })


def _dict_payload(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return dict(value)
    if isinstance(value, str) and value.strip():
        try:
            payload = json.loads(value)
        except json.JSONDecodeError:
            return {}
        return dict(payload) if isinstance(payload, dict) else {}
    return {}


def _load_capture_metadata(
    backend: Any,
    capture_id: str,
) -> tuple[dict[str, Any], str, str]:
    if not capture_id:
        return {}, "", "CAPTURE_ID_MISSING"
    record = backend.capture_repository.get(capture_id) or {}
    run_path = str(record.get("run_path") or "")
    if not run_path:
        return {}, "", "CAPTURE_RUN_PATH_MISSING"
    metadata_path = Path(run_path) / "capture_metadata.json"
    if not metadata_path.is_file():
        return {}, str(metadata_path), "CAPTURE_METADATA_MISSING"
    try:
        payload = json.loads(metadata_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return {}, str(metadata_path), f"CAPTURE_METADATA_INVALID:{type(exc).__name__}"
    if not isinstance(payload, dict):
        return {}, str(metadata_path), "CAPTURE_METADATA_NOT_OBJECT"
    return payload, str(metadata_path), ""


def _fresh_batch_jobs(backend: Any, batch_id: str) -> list[dict[str, Any]]:
    registry = getattr(backend, "registry", None)
    if registry is None:
        raise RuntimeError("SCRATCH_REGISTRY_REQUIRED_FOR_JOB_AUDIT")
    return JobRepository(registry).list(
        batch_id=str(batch_id),
        limit=100000,
    )


def _all_batches_terminal(backend: Any, batch_ids: list[str]) -> bool:
    if not batch_ids:
        return False
    for batch_id in batch_ids:
        jobs = _fresh_batch_jobs(backend, batch_id)
        if not jobs or any(
            str(job.get("status") or "") not in STAGE_B_TERMINAL_JOB_STATUSES
            for job in jobs
        ):
            return False
    return True


def _job_audit_rows(
    backend: Any,
    *,
    company: str,
    report_year: str,
    batch_ids: list[str],
    expected_scope_policy: str,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for batch_id in batch_ids:
        for job in _fresh_batch_jobs(backend, batch_id):
            payload = _dict_payload(job.get("payload"))
            request = _dict_payload(payload.get("capture_request"))
            request_metadata = _dict_payload(request.get("request_metadata"))
            certified_target = _dict_payload(
                request_metadata.get("certified_target")
            )
            job_result = _dict_payload(job.get("result"))
            capture_id = str(
                job_result.get("capture_id")
                or job.get("target_asset_id")
                or ""
            )
            logical_asset_id = str(
                job_result.get("logical_asset_id") or ""
            )
            metadata, metadata_path, metadata_error = _load_capture_metadata(
                backend, capture_id,
            )
            manifest_validation = _dict_payload(
                metadata.get("certified_segment_manifest_validation")
            )
            inventory_validation = _dict_payload(
                metadata.get("certified_note_table_inventory_validation")
            )
            validated_pairs = [
                dict(pair)
                for pair in (manifest_validation.get("validated_pairs") or [])
                if isinstance(pair, dict)
            ]
            drift_fields = sorted({
                str(field)
                for pair in validated_pairs
                for field in (pair.get("drift_fields") or [])
                if str(field)
            })
            manifest_issue_codes = [
                str(code)
                for code in (manifest_validation.get("issue_codes") or [])
                if str(code)
            ]
            scope_issue_codes = [
                str(code)
                for code in (metadata.get("scope_issue_codes") or [])
                if str(code)
            ]
            inventory_issue_codes = [
                str(code)
                for code in (inventory_validation.get("issue_codes") or [])
                if str(code)
            ]
            issue_codes = list(dict.fromkeys([
                *manifest_issue_codes,
                *scope_issue_codes,
                *inventory_issue_codes,
            ]))
            selected_manifest = [
                dict(segment)
                for segment in (metadata.get("selected_segment_manifest") or [])
                if isinstance(segment, dict)
            ]
            selected_classifications = sorted({
                str(
                    segment.get("classification")
                    or segment.get("segment_classification")
                    or ""
                ).strip().upper()
                for segment in selected_manifest
                if str(
                    segment.get("classification")
                    or segment.get("segment_classification")
                    or ""
                ).strip()
            })
            forbidden_segments = sorted(
                set(selected_classifications).intersection(
                    {"PEER_TABLE", "UNRESOLVED"}
                )
            )
            decision = _dict_payload(metadata.get("capture_decision"))
            blockers = [
                str(value)
                for value in (
                    metadata.get("merge_blockers")
                    or decision.get("blocking_issues")
                    or []
                )
                if str(value)
            ]
            warnings = [
                str(value)
                for value in (
                    metadata.get("non_blocking_warnings")
                    or decision.get("non_blocking_warnings")
                    or []
                )
                if str(value)
            ]
            requested_policy = str(
                request.get("capture_scope_policy") or ""
            )
            selected_ids = sorted(
                str(value)
                for value in (request.get("selected_logical_table_ids") or [])
                if str(value)
            )
            contract_version = int(
                request.get("capture_scope_contract_version") or 0
            )
            logical_table_id = str(
                certified_target.get("logical_table_id") or ""
            )
            registration_confirmed = bool(
                job_result.get("registration_confirmed")
            )
            status = str(job.get("status") or "")
            manifest_valid = (
                str(manifest_validation.get("status") or "").upper()
                == "VALID"
            )
            inventory_valid = (
                str(inventory_validation.get("status") or "").upper()
                == "VALID"
            )
            scope_selection_matches = bool(
                contract_version == CAPTURE_SCOPE_CONTRACT_VERSION
                and requested_policy == expected_scope_policy
                and bool(logical_table_id)
                and selected_ids == (
                    [logical_table_id]
                    if expected_scope_policy
                    == CaptureScopePolicy.SELECTED_NOTE_TABLES.value
                    else []
                )
            )
            execution_pass = bool(
                status in STAGE_B_EXECUTED_JOB_STATUSES
                and capture_id
                and logical_asset_id
                and registration_confirmed
                and not metadata_error
                and decision
                and manifest_valid
                and inventory_valid
                and not drift_fields
                and not issue_codes
                and not forbidden_segments
                and scope_selection_matches
            )
            merge_ready = bool(
                metadata.get("merge_ready", decision.get("merge_eligible", False))
            )
            quality_pass = bool(
                execution_pass and merge_ready and not blockers
            )
            rows.append({
                "company":company,
                "report_year":report_year,
                "batch_id":str(batch_id),
                "job_id":str(job.get("job_id") or ""),
                "job_status":status,
                "job_error_type":str(job.get("error_type") or ""),
                "job_error_message":str(job.get("error_message") or ""),
                "request_id":str(
                    job_result.get("request_id")
                    or request.get("request_id")
                    or ""
                ),
                "capture_id":capture_id,
                "logical_asset_id":logical_asset_id,
                "registration_confirmed":registration_confirmed,
                "capture_metadata_path":metadata_path,
                "capture_metadata_error":metadata_error,
                "capture_scope_contract_version":contract_version,
                "requested_capture_scope_policy":requested_policy,
                "selected_logical_table_ids":selected_ids,
                "scope_selection_matches":scope_selection_matches,
                "certified_link_id":str(
                    certified_target.get("certified_link_id")
                    or request.get("certified_note_target_id")
                    or ""
                ),
                "logical_table_id":str(
                    logical_table_id
                ),
                "table_classification":str(
                    certified_target.get("table_classification") or ""
                ),
                "certified_segment_ids":[
                    str(segment.get("certified_segment_id") or "")
                    for segment in (
                        certified_target.get("certified_segments") or []
                    )
                    if isinstance(segment, dict)
                ],
                "manifest_validation_status":str(
                    manifest_validation.get("status") or ""
                ),
                "manifest_validation":manifest_validation,
                "manifest_drift_fields":drift_fields,
                "manifest_issue_codes":manifest_issue_codes,
                "inventory_validation_status":str(
                    inventory_validation.get("status") or ""
                ),
                "inventory_validation":inventory_validation,
                "inventory_issue_codes":inventory_issue_codes,
                "scope_issue_codes":scope_issue_codes,
                "all_execution_issue_codes":issue_codes,
                "selected_segment_manifest":selected_manifest,
                "selected_segment_classifications":selected_classifications,
                "forbidden_selected_segments":forbidden_segments,
                "capture_quality_status":str(
                    metadata.get("capture_quality_status")
                    or decision.get("quality_status")
                    or ""
                ),
                "merge_ready":merge_ready,
                "merge_blockers":blockers,
                "non_blocking_warnings":warnings,
                "reducer_decision_present":bool(decision),
                "execution_pass":execution_pass,
                "quality_pass":quality_pass,
            })
    return rows


def _execute_stage_b_filing(
    backend: Any,
    *,
    company: str,
    report_year: str,
    pdf_path: Path,
    certified_links: list[dict[str, Any]],
    research_definition: dict[str, Any],
    certification_complete: bool,
    capture_scope_policy: str,
    include_all_certified_supplementary: bool,
    timeout_seconds: float,
    poll_interval_seconds: float,
) -> dict[str, Any]:
    supplementary_ids = _certified_supplementary_ids(certified_links)
    selected_logical_table_ids = (
        supplementary_ids
        if (
            capture_scope_policy
            == CaptureScopePolicy.SELECTED_NOTE_TABLES.value
            and include_all_certified_supplementary
        )
        else []
    )
    base = {
        "company":company,
        "report_year":report_year,
        "capture_scope_contract_version":CAPTURE_SCOPE_CONTRACT_VERSION,
        "capture_scope_policy":capture_scope_policy,
        "selected_logical_table_ids":selected_logical_table_ids,
        "available_certified_supplementary_ids":supplementary_ids,
        "execution_pass":False,
        "quality_pass":False,
        "review_required_count":0,
        "jobs":[],
    }
    if not certification_complete:
        return {
            **base,
            "status":"BLOCKED_INCOMPLETE_CERTIFICATION",
            "blocking_reason":"ALL_REQUIRED_MEMBERS_MUST_BE_AUTO_CERTIFIED",
        }
    if not certified_links:
        return {
            **base,
            "status":"BLOCKED_NO_CERTIFIED_LINKS",
            "blocking_reason":"CERTIFIED_CHILD_TABLE_LINK_REQUIRED",
        }
    if (
        capture_scope_policy
        == CaptureScopePolicy.SELECTED_NOTE_TABLES.value
        and not selected_logical_table_ids
    ):
        return {
            **base,
            "status":"BLOCKED_NO_CERTIFIED_SUPPLEMENTARY",
            "blocking_reason":"CERTIFIED_SUPPLEMENTARY_LOGICAL_TABLE_REQUIRED",
        }

    source_pdf_map: dict[str, Path] = {}
    for link in certified_links:
        target = backend.child_discovery_repository.certified_target(
            str(link.get("certified_link_id") or "")
        )
        source_pdf_id = str(target.get("source_pdf_id") or "")
        if not source_pdf_id:
            return {
                **base,
                "status":"BLOCKED_SOURCE_PDF_ID_MISSING",
                "blocking_reason":"CERTIFIED_TARGET_SOURCE_PDF_REQUIRED",
            }
        source_pdf_map[source_pdf_id] = Path(pdf_path)

    service = backend.child_capture_execution_service
    display_name = f"{company}{report_year}金融投资离线StageB验收"
    session_key = service.execution_session_key(
        display_name=display_name,
        research_definition=research_definition,
        scope="CONSOLIDATED",
    )
    try:
        submitted = service.create_execution_batch(
            display_name=display_name,
            certified_links=certified_links,
            source_pdf_map=source_pdf_map,
            research_definition=research_definition,
            scope="CONSOLIDATED",
            session_key=session_key,
            entry_origin="STRICT",
            capture_scope_contract_version=CAPTURE_SCOPE_CONTRACT_VERSION,
            capture_scope_policy=capture_scope_policy,
            selected_logical_table_ids=selected_logical_table_ids,
            selected_block_roles=[],
            selected_block_ids=[],
        )
    except Exception as exc:
        return {
            **base,
            "status":"SUBMISSION_ERROR",
            "session_key":session_key,
            "blocking_reason":f"{type(exc).__name__}:{exc}",
        }

    batch_ids = [str(value) for value in submitted.get("batch_ids") or []]
    blocked_count = int(submitted.get("blocked_count") or 0)
    state = dict(submitted)
    timed_out = False
    if batch_ids:
        deadline = time.monotonic() + float(timeout_seconds)
        last_progress: tuple[tuple[Any, ...], ...] | None = None
        while True:
            state = service.restore_execution(session_key)
            progress = tuple(
                (
                    row.get("批次"),row.get("已完成"),
                    row.get("失败"),row.get("总作业"),
                )
                for row in (state.get("progress") or [])
            )
            if progress and progress != last_progress:
                print(json.dumps({
                    "event":"STAGE_B_FILING_PROGRESS",
                    "company":company,
                    "report_year":report_year,
                    "progress":progress,
                }, ensure_ascii=False))
                last_progress = progress
            if _all_batches_terminal(backend, batch_ids):
                break
            if time.monotonic() >= deadline:
                timed_out = True
                break
            time.sleep(float(poll_interval_seconds))

    job_rows = _job_audit_rows(
        backend,
        company=company,
        report_year=report_year,
        batch_ids=batch_ids,
        expected_scope_policy=capture_scope_policy,
    )
    actual_selected_logical_table_ids = sorted({
        str(row.get("logical_table_id") or "")
        for row in job_rows
        if str(row.get("table_classification") or "").upper()
        == "SUPPLEMENTARY_TABLE"
        and str(row.get("logical_table_id") or "")
    })
    batch_scope_union_matches = (
        actual_selected_logical_table_ids
        == sorted(selected_logical_table_ids)
    )
    status_counts: dict[str, int] = {}
    for row in job_rows:
        job_status = str(row.get("job_status") or "")
        status_counts[job_status] = status_counts.get(job_status, 0) + 1
    review_required_count = status_counts.get("REVIEW_REQUIRED", 0)
    execution_pass = bool(
        batch_ids
        and job_rows
        and not timed_out
        and blocked_count == 0
        and batch_scope_union_matches
        and all(bool(row.get("execution_pass")) for row in job_rows)
    )
    quality_pass = bool(
        execution_pass
        and all(bool(row.get("quality_pass")) for row in job_rows)
    )
    if timed_out:
        status = "TIMEOUT"
    elif not batch_ids:
        status = "BLOCKED_NO_BATCHES"
    elif execution_pass:
        status = "EXECUTION_PASS"
    else:
        status = "EXECUTION_FAILED"
    return {
        **base,
        "status":status,
        "session_key":session_key,
        "research_batch_id":str(state.get("research_batch_id") or ""),
        "plan_ids":[str(value) for value in state.get("plan_ids") or []],
        "batch_ids":batch_ids,
        "job_count":len(job_rows),
        "blocked_count":blocked_count,
        "timed_out":timed_out,
        "terminal_status_counts":status_counts,
        "review_required_count":review_required_count,
        "batch_expected_selected_logical_table_ids":sorted(
            selected_logical_table_ids
        ),
        "batch_actual_selected_logical_table_ids":(
            actual_selected_logical_table_ids
        ),
        "batch_scope_union_matches":batch_scope_union_matches,
        "execution_pass":execution_pass,
        "quality_pass":quality_pass,
        "review_queue_count":len(state.get("review_queue") or []),
        "jobs":job_rows,
    }


def _csv_row(row: dict[str, Any]) -> dict[str, Any]:
    return {
        key:(
            json.dumps(value, ensure_ascii=False, sort_keys=True)
            if isinstance(value, (dict, list, tuple))
            else value
        )
        for key, value in row.items()
    }


def main(argv: list[str] | None = None) -> None:
    args = _arguments(argv)
    configured_database = (
        resolve_data_home(ROOT) / "metadata.db"
    ).resolve()
    configured_database_before = _database_file_snapshot(
        configured_database
    )
    output_root = Path(args.output_dir).resolve()
    run_id = str(args.run_id or dt.datetime.now().strftime("%Y%m%dT%H%M%S"))
    run_dir = output_root / "runs" / run_id
    run_dir.mkdir(parents=True, exist_ok=False)
    scratch = run_dir / "stage_b_revalidation_scratch"
    scratch.mkdir(parents=True, exist_ok=False)
    scratch_db = scratch / "metadata.db"
    stage_b_backend = _build_stage_b_backend(
        scratch, args.execute_stage_b,
    )
    scratch_registry = (
        stage_b_backend.registry
        if stage_b_backend is not None
        else MetadataRegistry(scratch_db)
    )
    definitions = (
        stage_b_backend.research_definition_service
        if stage_b_backend is not None
        else ResearchDefinitionService(scratch_registry)
    )
    definition_id = "FINANCIAL_INVESTMENT_V1"
    cache_dir = output_root / "cold_index_cache"
    generic = GenericDiscoveryService(definitions, cache_dir)
    discovery = DiscoveryService(DiscoveryRegistry(scratch_registry), cache_dir)
    child_repo = (
        stage_b_backend.child_discovery_repository
        if stage_b_backend is not None
        else ChildDiscoveryRepository(scratch_registry)
    )
    child_discovery_service = (
        stage_b_backend.hierarchical_child_discovery_service
        if stage_b_backend is not None
        else HierarchicalChildTableDiscoveryService(
            child_repo, FinancialNoteIndexService(child_repo),
        )
    )
    definition = definitions.definition(definition_id) or {}
    definition_version = str(definition.get("definition_version") or definition_id)
    output: list[dict] = []
    stage_b_filing_runs: list[dict[str, Any]] = []
    selected_filings = [
        filing for filing in FILINGS
        if (not args.company or filing[0] == args.company)
        and (not args.year or filing[1] == args.year)
    ]
    for company, year, name in selected_filings:
        pdf = DOCU / name
        result = generic.discover(pdf_path=pdf, definition_id=definition_id, company=company, report_year=year)
        occurrence = choose_occurrence(result.get("occurrences") or [])
        if occurrence is None:
            output.append({"company": company, "report_year": year, "status": "NO_MAIN_OCCURRENCE"})
            if stage_b_backend is not None:
                stage_b_filing_runs.append(_execute_stage_b_filing(
                    stage_b_backend,
                    company=company,
                    report_year=year,
                    pdf_path=pdf,
                    certified_links=[],
                    research_definition=definition,
                    certification_complete=False,
                    capture_scope_policy=args.capture_scope_policy,
                    include_all_certified_supplementary=(
                        args.include_all_certified_supplementary
                    ),
                    timeout_seconds=args.stage_b_timeout_seconds,
                    poll_interval_seconds=args.stage_b_poll_interval_seconds,
                ))
            continue
        occurrence = discovery.build_occurrence(
            context={**occurrence, "pdf_id": str(pdf)},
            parent_text=occurrence.get("parent_text") or "",
            child_rows=occurrence.get("child_rows") or [],
            source_table_title=occurrence.get("source_table_title") or "",
            scope="CONSOLIDATED",
        )
        concepts = child_repo.create_anchor_children(
            occurrence,
            research_definition_id=definition_id,
            definition_version=definition_version,
        )
        links_by_child: dict[str, list[dict]] = {}
        filing_rows: list[dict] = []
        if not concepts:
            output.append({
                "company": company,
                "report_year": year,
                "occurrence_id": occurrence.get("occurrence_id"),
                "member": "",
                "note_reference": "",
                "candidate_count": 0,
                "candidate_pages": "",
                "candidate_methods": "",
                "status": "NO_ACTIVE_CHILD_CONCEPTS",
                "cache_hit": False,
                "source_child_row_count": len(occurrence.get("child_rows") or []),
            })
        family_id = str(
            occurrence.get("table_family") or "financial_investment"
        )
        for concept in concepts:
            contract = member_contract(definitions, family_id, concept)
            found = child_discovery_service.discover(
                pdf, occurrence, concept, contract, "CONSOLIDATED",
            )
            candidates = found.get("candidates") or []
            enriched = child_discovery_service.enrich_top_k(
                pdf,concept,candidates,contract,
            )
            links = child_discovery_service.link_candidates(
                occurrence,concept,enriched,contract,
            )
            links_by_child[str(concept["anchor_child_id"])] = links
            inventories = [
                dict(item.get("note_table_inventory") or {})
                for item in enriched
                if item.get("note_table_inventory")
            ]
            row = {
                "company": company,
                "report_year": year,
                "occurrence_id": occurrence.get("occurrence_id"),
                "anchor_child_id":concept.get("anchor_child_id"),
                "member": concept.get("raw_label"),
                "member_table_id":contract["member_table_id"],
                "note_reference": concept.get("inline_note_reference"),
                "candidate_count": len(candidates),
                "enriched_candidate_count":len(enriched),
                "candidate_pages": ";".join(str(row.get("start_page")) for row in candidates),
                "candidate_methods": ";".join(str(row.get("retrieval_method")) for row in candidates),
                "inventory_statuses":";".join(
                    str(item.get("inventory_status") or "")
                    for item in inventories
                ),
                "logical_table_candidate_count":sum(
                    len(item.get("logical_tables") or []) for item in inventories
                ),
                "resolved_logical_link_candidate_count":len(links),
                "discovery_status": (found.get("run") or {}).get("status") or found.get("early_stop_reason") or "UNKNOWN",
                "cache_hit": ((found.get("run") or {}).get("metrics") or {}).get("discovery_cache_hit", False),
                "source_child_row_count": len(occurrence.get("child_rows") or []),
            }
            filing_rows.append(row)
            output.append(row)
        assignment = child_discovery_service.assign_global(
            str(occurrence["occurrence_id"]),
            "CONSOLIDATED",links_by_child,
        ) if links_by_child else {"decisions":[],"certified_links":[]}
        decisions = {
            str(item.get("anchor_child_id") or ""):item
            for item in assignment.get("decisions") or []
        }
        certified_by_child: dict[str, list[dict]] = {}
        for link in assignment.get("certified_links") or []:
            certified_by_child.setdefault(
                str(link.get("anchor_child_id") or ""),[]
            ).append(link)
        for row in filing_rows:
            child_id = str(row.get("anchor_child_id") or "")
            decision = decisions.get(child_id) or {}
            certified = certified_by_child.get(child_id,[])
            row.update({
                "assignment_status":decision.get("status") or "UNRESOLVED",
                "unresolved_reason":decision.get("unresolved_reason") or "",
                "certified_logical_link_count":len(certified),
                "certified_segment_count":sum(
                    len(item.get("certified_segments") or [])
                    for item in certified
                ),
                "manual_correction_required":decision.get("status")
                != "AUTO_CERTIFIED",
            })
        if stage_b_backend is not None:
            certification_complete = bool(filing_rows) and all(
                row.get("assignment_status") == "AUTO_CERTIFIED"
                for row in filing_rows
            )
            print(json.dumps({
                "event":"STAGE_B_FILING_START",
                "company":company,
                "report_year":year,
                "capture_scope_policy":args.capture_scope_policy,
                "certification_complete":certification_complete,
            }, ensure_ascii=False))
            stage_b_result = _execute_stage_b_filing(
                stage_b_backend,
                company=company,
                report_year=year,
                pdf_path=pdf,
                certified_links=[
                    dict(link)
                    for link in (assignment.get("certified_links") or [])
                ],
                research_definition=definition,
                certification_complete=certification_complete,
                capture_scope_policy=args.capture_scope_policy,
                include_all_certified_supplementary=(
                    args.include_all_certified_supplementary
                ),
                timeout_seconds=args.stage_b_timeout_seconds,
                poll_interval_seconds=args.stage_b_poll_interval_seconds,
            )
            stage_b_filing_runs.append(stage_b_result)
            print(json.dumps({
                "event":"STAGE_B_FILING_COMPLETE",
                "company":company,
                "report_year":year,
                "status":stage_b_result.get("status"),
                "job_count":stage_b_result.get("job_count",0),
                "review_required_count":stage_b_result.get(
                    "review_required_count",0
                ),
                "execution_pass":stage_b_result.get("execution_pass"),
                "quality_pass":stage_b_result.get("quality_pass"),
            }, ensure_ascii=False))
    stage_b_job_rows = [
        dict(job)
        for filing in stage_b_filing_runs
        for job in (filing.get("jobs") or [])
    ]
    stage_b_status_counts: dict[str, int] = {}
    for job in stage_b_job_rows:
        status = str(job.get("job_status") or "")
        stage_b_status_counts[status] = stage_b_status_counts.get(status,0)+1
    stage_b_execution_pass = (
        bool(stage_b_filing_runs)
        and len(stage_b_filing_runs) == len(selected_filings)
        and all(
            bool(filing.get("execution_pass"))
            for filing in stage_b_filing_runs
        )
    ) if args.execute_stage_b else None
    stage_b_quality_pass = (
        bool(stage_b_execution_pass)
        and all(
            bool(filing.get("quality_pass"))
            for filing in stage_b_filing_runs
        )
    ) if args.execute_stage_b else None
    configured_database_after = _database_file_snapshot(
        configured_database
    )
    report = {
        "run_id":run_id,
        "scratch_database":str(scratch_db),
        "configured_database_before":configured_database_before,
        "configured_database_after":configured_database_after,
        "configured_data_home_modified":_database_file_modified(
            configured_database_before,
            configured_database_after,
        ),
        "filing_count":len(selected_filings),
        "member_count":len(output),
        "auto_certified_member_count":sum(
            row.get("assignment_status")=="AUTO_CERTIFIED" for row in output
        ),
        "manual_correction_required_count":sum(
            bool(row.get("manual_correction_required")) for row in output
        ),
        "stage_b_requested":bool(args.execute_stage_b),
        "stage_b_capture_scope_contract_version":(
            CAPTURE_SCOPE_CONTRACT_VERSION
            if args.execute_stage_b else None
        ),
        "stage_b_capture_scope_policy":(
            args.capture_scope_policy if args.execute_stage_b else None
        ),
        "stage_b_include_all_certified_supplementary":bool(
            args.execute_stage_b
            and args.include_all_certified_supplementary
        ),
        "stage_b_filing_count":len(stage_b_filing_runs),
        "stage_b_job_count":len(stage_b_job_rows),
        "stage_b_terminal_status_counts":stage_b_status_counts,
        "stage_b_review_required_count":sum(
            int(filing.get("review_required_count") or 0)
            for filing in stage_b_filing_runs
        ),
        "stage_b_execution_pass":stage_b_execution_pass,
        "stage_b_quality_pass":stage_b_quality_pass,
        "stage_b_filing_runs":stage_b_filing_runs,
        "rows":output,
    }
    (run_dir / "stage_b_revalidation.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8",
    )
    with (run_dir / "stage_b_revalidation.csv").open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=sorted({key for row in output for key in row}))
        writer.writeheader(); writer.writerows(output)
    if args.execute_stage_b:
        job_csv = run_dir / "stage_b_job_audit.csv"
        fieldnames = sorted({
            key for row in stage_b_job_rows for key in row
        }) or [
            "company","report_year","job_status",
            "execution_pass","quality_pass",
        ]
        with job_csv.open("w", newline="", encoding="utf-8-sig") as handle:
            writer = csv.DictWriter(handle, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(_csv_row(row) for row in stage_b_job_rows)
        stage_b_backend.table_capture_runner.shutdown(wait=True)
    print(json.dumps({
        key:value for key,value in report.items()
        if key not in {"rows","stage_b_filing_runs"}
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()
