"""Authoritative v6.11 Capture completion application service.

Extraction remains owned by the existing Capture primitive.  This service
starts only after immutable machine evidence and the physical Capture registry
record exist.  It reduces and persists all governance/review projections in
one SQLite transaction.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from services.capture_decision_reducer import CaptureDecisionReducer


class CaptureCompletionService:
    def __init__(
        self, *, governance_repository, review_task_service,
        producer_version: str = "v6.11",
        reducer: CaptureDecisionReducer | None = None,
    ) -> None:
        self.repo = governance_repository
        self.registry = governance_repository.registry
        self.review_tasks = review_task_service
        self.producer_version = producer_version
        self.reducer = reducer or CaptureDecisionReducer()

    @staticmethod
    def _project_capture_metadata(
        *,
        run_path: str | Path | None,
        metadata: dict[str, Any],
        decision,
    ) -> dict[str, Any]:
        if not run_path:
            return {"status": "SKIPPED", "reason": "RUN_PATH_MISSING"}
        run_dir = Path(run_path)
        if not run_dir.is_dir():
            return {
                "status": "SKIPPED",
                "reason": "RUN_PATH_UNAVAILABLE",
                "run_path": str(run_dir),
            }
        metadata_path = run_dir / "capture_metadata.json"
        payload: dict[str, Any] = {}
        if metadata_path.is_file():
            try:
                payload = json.loads(metadata_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                payload = {}
        payload = {**dict(metadata or {}), **payload}
        boundary_decision = (
            decision.decision_evidence.get("boundary_decision") or {}
        )
        payload.update({
            "boundary_status": boundary_decision.get("status"),
            "header_dimension_status": decision.decision_evidence.get(
                "header_status"
            ),
            "capture_quality_status": decision.quality_status,
            "quality_status": decision.quality_status,
            "review_status": decision.review_status,
            "merge_ready": bool(decision.merge_eligible),
            "merge_blockers": list(decision.blocking_issues),
            "non_blocking_warnings": list(decision.non_blocking_warnings),
            "asset_status": decision.asset_status,
            "certified": bool(decision.certified),
            "capture_decision": decision.to_dict(),
        })
        staged = metadata_path.with_suffix(metadata_path.suffix + ".completion.tmp")
        staged.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2, default=str),
            encoding="utf-8",
        )
        staged.replace(metadata_path)
        return {"status": "OK", "path": str(metadata_path)}

    def complete(
        self, *, capture_id: str, machine_evidence: dict[str, Any],
        metadata: dict[str, Any], capture_record: dict[str, Any] | None = None,
        research_definition: dict[str, Any] | None = None,
        human_adjudications: dict[str, Any] | None = None,
        capture_bundle_id: str | None = None,
        stale_resolution_decision: str | None = None,
    ) -> dict[str, Any]:
        """Reduce and atomically persist the authoritative completion state."""
        record = dict(capture_record or {})
        identity = {
            **dict(metadata or {}),
            "pdf_id": record.get("pdf_id") or metadata.get("pdf_id"),
            "pdf_name": (
                record.get("pdf_name")
                or metadata.get("pdf_name")
                or metadata.get("source_pdf_display")
            ),
            "source_pdf_path": (
                record.get("source_pdf_path")
                or metadata.get("source_pdf_path")
            ),
        }
        candidate_version = {
            **identity,
            "capture_id": capture_id,
            "is_current": bool(record.get("is_current", True)),
            "processing_status": "COMPLETED",
            "registration_status": str(
                record.get("registration_status") or "REGISTERED"
            ),
            "quality_status": str(record.get("quality_status") or "UNASSESSED"),
            "review_status": str(record.get("review_status") or "PENDING"),
            "asset_status": str(record.get("asset_status") or "ACTIVE"),
            "run_path": record.get("run_path") or metadata.get("run_path"),
        }
        lifecycle = {
            "registration_status": candidate_version["registration_status"],
            "asset_status": candidate_version["asset_status"],
        }
        decision = self.reducer.reduce(
            machine_evidence=machine_evidence,
            research_definition=research_definition,
            capture_version=candidate_version,
            human_adjudications=human_adjudications,
            lifecycle_state=lifecycle,
            rule_version=self.producer_version,
        )

        with self.registry.connect() as conn:
            asset_row = self.repo._get_or_create_logical_asset_in_tx(
                conn,identity,
            )
            asset = dict(asset_row)
            logical_asset_id = str(asset["logical_asset_id"])
            version_row = self.repo._register_capture_version_in_tx(
                conn,
                logical_asset_id=logical_asset_id,
                capture_id=capture_id,
                producer_version=self.producer_version,
                processing_status="COMPLETED",
                registration_status="REGISTERED",
                quality_status=decision.quality_status,
                review_status=decision.review_status,
                certified=decision.certified,
                asset_status=decision.asset_status,
            )
            if capture_bundle_id:
                conn.execute(
                    """UPDATE capture_bundle_children SET logical_asset_id=?
                       WHERE bundle_id=? AND capture_id=?""",
                    (logical_asset_id,capture_bundle_id,capture_id),
                )
            detail = {
                **candidate_version,
                **dict(version_row),
                "logical_asset_id": logical_asset_id,
                "run_path": record.get("run_path") or metadata.get("run_path"),
            }
            review_summary = self.review_tasks.materialize_decision_in_tx(
                conn,
                capture_id=capture_id,
                detail=detail,
                result=machine_evidence,
                decision=decision,
                stale_resolution_decision=stale_resolution_decision,
            )
            aggregate_bundle_status = self.repo._recalculate_bundle_status_in_tx(
                conn,capture_id,
            )

        run_path = record.get("run_path") or metadata.get("run_path")
        try:
            metadata_projection = self._project_capture_metadata(
                run_path=run_path,
                metadata=metadata,
                decision=decision,
            )
        except Exception as exc:
            metadata_projection = {
                "status": "ERROR",
                "path": (
                    str(Path(run_path) / "capture_metadata.json")
                    if run_path else None
                ),
                "error_type": type(exc).__name__,
                "error": str(exc),
            }

        return {
            "logical_asset": asset,
            "logical_asset_id": logical_asset_id,
            "capture_version": dict(version_row),
            "decision": decision,
            "review_summary": review_summary,
            "bundle_status": aggregate_bundle_status or decision.bundle_status,
            "metadata_projection": metadata_projection,
        }
