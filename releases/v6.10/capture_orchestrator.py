"""The single v6.8 production orchestration path for every table capture."""
from __future__ import annotations

import traceback
from typing import Any, Callable

from capture_models import CaptureRequest, ResolvedCaptureTarget


class CaptureOrchestrator:
    def __init__(
        self, *, repository, strategies, executor: Callable,
        capture_repository, logical_asset_service, lifecycle_service,
        review_inbox_service,
    ):
        self.repo = repository
        self.strategies = strategies
        self.executor = executor
        self.capture_repo = capture_repository
        self.logical_assets = logical_asset_service
        self.lifecycle = lifecycle_service
        self.review = review_inbox_service

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
            from capture_library import capture_readiness
            evidence = result.get("result") or {}
            readiness = capture_readiness(evidence)
            merge_ready = bool(readiness.get("merge_ready"))
            blockers = list(readiness.get("merge_blockers") or [])
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
                "member_table_id": request.member_table_id,
                "logical_source_role": request.request_metadata.get("member_table_role") or "COMPONENT",
                "statement_scope": (
                    target.statement_scope
                    if str(target.statement_scope or "UNKNOWN").upper() not in {"", "UNKNOWN"}
                    else request.request_metadata.get("statement_scope") or "UNKNOWN"
                ),
                "derivation_evidence": {"request_id": request.request_id, "target_id": target.target_id},
            }
            registered_asset = self.logical_assets.register_capture(
                capture_id=capture_id, metadata=metadata,
                processing_status="COMPLETED", registration_status="REGISTERED",
                quality_status="READY" if merge_ready else "REVIEW_REQUIRED",
                review_status="CONFIRMED_AUTO" if merge_ready else "PENDING",
                certified=merge_ready,
            )
            logical_asset_id = registered_asset["logical_asset"]["logical_asset_id"]
            if result.get("capture_bundle_id"):
                with self.repo.registry.connect() as conn:
                    conn.execute(
                        "UPDATE capture_bundle_children SET logical_asset_id=? WHERE bundle_id=? AND capture_id=?",
                        (logical_asset_id,result["capture_bundle_id"],capture_id),
                    )
            # A v6.9 compound note exposes each resolved table block as an
            # independently governed child capture.  The child subtable id is
            # part of its logical identity, preventing same-name tables from
            # silently collapsing during later family merge.
            child_assets = []
            for child in list(result.get("child_captures") or [])[1:]:
                child_id = str(child.get("capture_id") or "")
                if not child_id or not self.capture_repo.get(child_id):
                    continue
                block = dict(child.get("block") or {})
                child_metadata = {
                    **metadata,
                    "member_table_id": f"{request.member_table_id or 'MEMBER'}::{block.get('block_id') or child_id}",
                    "member_table": str(block.get("title") or request.member_table_id or ""),
                    "logical_source_role": "NOTE_DETAIL",
                    "derivation_evidence": {"request_id": request.request_id, "target_id": target.target_id,
                                              "capture_bundle_id": result.get("capture_bundle_id"), "block": block},
                }
                child_ready = str(block.get("quality_status") or "REVIEW_REQUIRED") == "READY"
                child_asset = self.logical_assets.register_capture(
                    capture_id=child_id, metadata=child_metadata,
                    processing_status="COMPLETED", registration_status="REGISTERED",
                    quality_status="READY" if child_ready else "REVIEW_REQUIRED",
                    review_status="CONFIRMED_AUTO" if child_ready else "PENDING", certified=child_ready,
                )
                child_assets.append({"capture_id": child_id,
                                     "logical_asset_id": child_asset["logical_asset"]["logical_asset_id"],
                                     "block_id": block.get("block_id")})
                if not child_ready:
                    self.review.route(logical_asset_id=child_asset["logical_asset"]["logical_asset_id"], capture_id=child_id,
                                      reasons=["V69_BLOCK_REVIEW_REQUIRED"], evidence={"block": block, "request_id": request.request_id})
            if child_assets and result.get("capture_bundle_id"):
                with self.repo.registry.connect() as conn:
                    for child in child_assets:
                        conn.execute("UPDATE capture_bundle_children SET logical_asset_id=? WHERE bundle_id=? AND capture_id=?",
                                     (child["logical_asset_id"], result["capture_bundle_id"], child["capture_id"]))
            if result.get("capture_bundle_id"):
                self.repo.recalculate_bundle_status(capture_id)
            if not merge_ready:
                self.review.route(
                    logical_asset_id=logical_asset_id, capture_id=capture_id,
                    reasons=blockers or ["STRUCTURE_REVIEW_REQUIRED"],
                    evidence={"readiness": readiness, "request_id": request.request_id},
                )
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
            }
        except Exception as exc:
            self.repo.update_request(
                request.request_id, "FAILED", error=f"{type(exc).__name__}:{exc}",
                traceback=traceback.format_exc(),
            )
            raise
