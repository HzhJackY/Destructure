"""The single v6.8 production orchestration path for every table capture."""
from __future__ import annotations

import json
import traceback
from pathlib import Path
from typing import Any, Callable

from capture_models import (
    CAPTURE_SCOPE_CONTRACT_VERSION,
    CaptureRequest,
    CaptureScopePolicy,
    ResolvedCaptureTarget,
)


class CaptureOrchestrator:
    def __init__(
        self, *, repository, strategies, executor: Callable,
        capture_repository, logical_asset_service, lifecycle_service,
        review_inbox_service, completion_service=None,
    ):
        self.repo = repository
        self.strategies = strategies
        self.executor = executor
        self.capture_repo = capture_repository
        self.logical_assets = logical_asset_service
        self.lifecycle = lifecycle_service
        self.review = review_inbox_service
        if completion_service is None:
            from services.capture_completion_service import CaptureCompletionService
            from services.review_task_service import ReviewTaskService
            completion_service = CaptureCompletionService(
                governance_repository=repository,
                review_task_service=ReviewTaskService(repository),
            )
        self.completion = completion_service

    def resolve(self, request: CaptureRequest) -> dict[str, Any]:
        request.validate()
        self.repo.save_request(request, "DISCOVERING")
        context = {"request": request}
        strategy = self.strategies.resolve(request, context)
        candidates: list[dict[str, Any]] = []
        try:
            candidates = strategy.discover_candidates(request, context)
            ranked = strategy.rank_candidates(candidates, context)
            if not ranked:
                self.repo.save_strategy_execution(
                    request_id=request.request_id, strategy_id=strategy.strategy_id,
                    status="ABSTAINED", candidates=[], abstain_reason=strategy.abstain_reason(),
                )
                self.repo.update_request(request.request_id, "REVIEW_REQUIRED",
                                         abstain_reason=strategy.abstain_reason())
                return {"request_id": request.request_id, "status": "REVIEW_REQUIRED",
                        "reason": strategy.abstain_reason(), "candidates": []}
            target = strategy.resolve_target(ranked[0], context)
            self.repo.save_target(request.request_id, target)
            valid = strategy.validate_target(target, context)
            self.repo.save_strategy_execution(
                request_id=request.request_id, strategy_id=strategy.strategy_id,
                status="RESOLVED" if valid else "REVIEW_REQUIRED", candidates=ranked,
                selected_target_id=target.target_id if valid else "",
                abstain_reason="" if valid else "TARGET_NOT_CERTIFIED",
            )
            if not valid:
                self.repo.update_request(request.request_id, "REVIEW_REQUIRED",
                                         target=target.to_dict())
                return {"request_id": request.request_id, "status": "REVIEW_REQUIRED",
                        "reason": "TARGET_NOT_CERTIFIED", "target": target.to_dict()}
            self.repo.update_request(request.request_id, "READY", target=target.to_dict())
            return {"request_id": request.request_id, "status": "READY", "target": target.to_dict()}
        except Exception as exc:
            self.repo.save_strategy_execution(
                request_id=request.request_id, strategy_id=strategy.strategy_id,
                status="FAILED", candidates=candidates,
                abstain_reason=f"{type(exc).__name__}:{exc}",
            )
            self.repo.update_request(request.request_id, "FAILED",
                                     error=f"{type(exc).__name__}:{exc}")
            raise

    def execute(self, request: CaptureRequest, target: ResolvedCaptureTarget | None = None) -> dict[str, Any]:
        if target is None:
            resolved = self.resolve(request)
            if resolved["status"] != "READY":
                return resolved
            target = ResolvedCaptureTarget.from_dict(resolved["target"])
        target.validate_for_execution()
        self.repo.save_request(request, "RUNNING")
        try:
            result = self.executor(request, target)
            capture_id = str(result.get("capture_id") or "")
            registered = self.capture_repo.get(capture_id) if capture_id else None
            if not registered:
                raise RuntimeError("JOB_SUCCESS_REQUIRES_REGISTRATION_CONFIRMATION")
            evidence = result.get("result") or {}
            metadata = {
                **request.request_metadata,
                **dict(result.get("metadata") or {}),
                "company_id": request.request_metadata.get("company"),
                "report_year": request.request_metadata.get("report_year"),
                "research_project_id": request.research_project_id,
                "research_task_id": request.research_task_id,
                "research_definition_id": request.research_definition_id,
                "definition_version": request.definition_version,
                "table_family_id": request.table_family_id,
                "member_table_id": str(
                    (result.get("metadata") or {}).get("member_table_id")
                    or (result.get("metadata") or {}).get("member_table")
                    or request.member_table_id
                ),
                "capture_scope_contract_version":(
                    request.capture_scope_contract_version
                ),
                "capture_scope_policy":(
                    CaptureScopePolicy.ALL_NOTE_TABLES.value
                    if request.capture_scope_contract_version
                    == CAPTURE_SCOPE_CONTRACT_VERSION
                    and request.capture_scope_policy
                    == CaptureScopePolicy.SELECTED_NOTE_TABLES.value
                    else request.capture_scope_policy
                ),
                "requested_capture_scope_policy":request.capture_scope_policy,
                "capture_request_snapshot":request.to_dict(),
                "selected_logical_table_ids":list(
                    request.selected_logical_table_ids
                ),
                "selected_block_roles":list(request.selected_block_roles),
                "selected_block_ids":list(request.selected_block_ids),
                "certified_logical_table_id":str(
                    (target.evidence or {}).get("logical_table_id")
                    or (result.get("metadata") or {}).get(
                        "certified_logical_table_id"
                    )
                    or ""
                ).strip(),
                "capture_request_id":request.request_id,
                "logical_source_role": request.request_metadata.get("member_table_role") or "COMPONENT",
                "pdf_id": registered.get("pdf_id") or request.source_pdf_id,
                "pdf_name": registered.get("pdf_name"),
                "source_pdf_path": request.source_pdf_path,
                "run_path": registered.get("run_path") or result.get("run_path"),
                "statement_scope": (
                    target.statement_scope
                    if str(target.statement_scope or "UNKNOWN").upper() not in {"", "UNKNOWN"}
                    else request.request_metadata.get("statement_scope") or "UNKNOWN"
                ),
                "derivation_evidence": {"request_id": request.request_id, "target_id": target.target_id},
            }
            completion = self.completion.complete(
                capture_id=capture_id,
                machine_evidence=evidence,
                metadata=metadata,
                capture_record=registered,
                research_definition={
                    "definition_id": request.research_definition_id,
                    "definition_version": request.definition_version,
                },
                capture_bundle_id=result.get("capture_bundle_id"),
            )
            decision = completion["decision"]
            merge_ready = bool(decision.merge_eligible)
            blockers = list(decision.blocking_issues)
            logical_asset_id = completion["logical_asset_id"]
            readiness = {
                "boundary_status": (
                    decision.decision_evidence.get("boundary_decision") or {}
                ).get("status"),
                "header_dimension_status": decision.decision_evidence.get("header_status"),
                "capture_quality_status": decision.quality_status,
                "merge_ready": decision.merge_eligible,
                "merge_blockers": blockers,
            }
            # A v6.9 compound note exposes each resolved table block as an
            # independently governed child capture.  The child subtable id is
            # part of its logical identity, preventing same-name tables from
            # silently collapsing during later family merge.
            child_assets = []
            for child in list(result.get("child_captures") or [])[1:]:
                child_id = str(child.get("capture_id") or "")
                child_record = self.capture_repo.get(child_id) if child_id else None
                if not child_id or not child_record:
                    continue
                block = dict(child.get("block") or {})
                certified_child_member = str(
                    child.get("certified_member_table_id") or ""
                ).strip()
                child_metadata = {
                    **metadata,
                    "member_table_id": (
                        certified_child_member
                        or f"{request.member_table_id or 'MEMBER'}::{block.get('block_id') or child_id}"
                    ),
                    "member_table": str(
                        child.get("member_table")
                        or certified_child_member
                        or block.get("title")
                        or request.member_table_id
                        or ""
                    ),
                    "logical_source_role": "NOTE_DETAIL",
                    "container_id": result.get("note_container_id") or metadata.get("container_id"),
                    "table_block_id": block.get("block_id"),
                    "block_order": block.get("block_order"),
                    "classification_axis": block.get("classification_axis") or "UNRESOLVED",
                    "block_role": block.get("role") or "SECONDARY_TABLE",
                    "block_terminal_type": block.get("block_terminal_type") or "UNRESOLVED",
                    "derivation_evidence": {"request_id": request.request_id, "target_id": target.target_id,
                                              "capture_bundle_id": result.get("capture_bundle_id"), "block": block},
                }
                child_evidence: dict[str, Any] = {}
                child_result_path = (
                    Path(str(child_record.get("run_path") or child.get("run_path") or ""))
                    / "table_capture_result.json"
                )
                if child_result_path.is_file():
                    try:
                        child_evidence = json.loads(
                            child_result_path.read_text(encoding="utf-8")
                        )
                    except (OSError, json.JSONDecodeError):
                        child_evidence = {}
                child_completion = self.completion.complete(
                    capture_id=child_id,
                    machine_evidence=child_evidence,
                    metadata=child_metadata,
                    capture_record=child_record,
                    research_definition={
                        "definition_id": request.research_definition_id,
                        "definition_version": request.definition_version,
                    },
                    capture_bundle_id=result.get("capture_bundle_id"),
                )
                child_decision = child_completion["decision"]
                child_ready = bool(child_decision.merge_eligible)
                child_assets.append({"capture_id": child_id,
                                     "logical_asset_id": child_completion["logical_asset_id"],
                                     "block_id": block.get("block_id")})
            if result.get("capture_bundle_id"):
                self.repo.recalculate_bundle_status(capture_id)
            final_status = "SUCCESS" if merge_ready else "REVIEW_REQUIRED"
            self.lifecycle.transition(
                logical_asset_id=logical_asset_id, capture_id=capture_id,
                previous_status="RUNNING", new_status=final_status, reason="CAPTURE_COMPLETED",
                evidence={"registration_confirmed": True, "readiness": readiness},
            )
            self.repo.update_request(
                request.request_id, final_status, capture_id=capture_id,
                logical_asset_id=logical_asset_id, registration_confirmed=True,
            )
            return {
                **result, "request_id": request.request_id, "status": final_status,
                "logical_asset_id": logical_asset_id, "registration_confirmed": True,
                "readiness": readiness, "child_logical_assets": child_assets,
                "decision": decision.to_dict(),
                "bundle_status": completion["bundle_status"],
            }
        except Exception as exc:
            self.repo.update_request(
                request.request_id, "FAILED", error=f"{type(exc).__name__}:{exc}",
                traceback=traceback.format_exc(),
            )
            raise
