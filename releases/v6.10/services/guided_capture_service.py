"""Execute a certified capture plan without returning to manual target input."""
from __future__ import annotations

import json
import uuid
from pathlib import Path
from typing import Any

from capture_models import CaptureMode, CaptureRequest


class GuidedCaptureService:
    def __init__(self, *, registry, capture_service, audit_dir: Path):
        self.registry = registry
        self.capture_service = capture_service
        self.audit_dir = Path(audit_dir)

    def execute(self, plan: dict[str, Any], *, pdf_path: Path, batch_id: str | None = None,
                research_batch_id: str | None = None, max_workers: int = 3, options: dict[str, Any] | None = None) -> dict[str, Any]:
        """Materialise the anchor, enqueue only READY detail rows, then start.

        The anchor is an immutable statement evidence artifact, not a synthetic
        financial table. Detail jobs retain their own note/page constraints.
        """
        options = dict(options or {})
        if plan.get("anchor_occurrence_id") is None:
            raise PermissionError("UNSELECTED_ANCHOR_NEVER_MATERIALIZES")
        # Service-level idempotent persistence: callers must not need to know
        # that ResearchBatch review joins through capture_plans.
        from discovery_registry import DiscoveryRegistry
        with self.registry.connect() as conn:
            persisted = conn.execute(
                "SELECT 1 FROM capture_plans WHERE plan_id=?", (plan["plan_id"],)
            ).fetchone()
        if not persisted:
            DiscoveryRegistry(self.registry).save_capture_plan(plan)
        # A certified plan should normally carry its pinned research-definition
        # identity.  Older plans did not always persist those two fields;
        # inherit only from the owning batch's immutable payload, never from a
        # currently active definition.
        batch_definition = {}
        if research_batch_id and (not plan.get("research_definition_id") or not plan.get("definition_version")):
            with self.registry.connect() as conn:
                batch_row = conn.execute(
                    "SELECT payload_json FROM research_batches WHERE research_batch_id=?",
                    (research_batch_id,),
                ).fetchone()
            if batch_row:
                try:
                    batch_definition = json.loads(batch_row["payload_json"] or "{}")
                except (TypeError, json.JSONDecodeError):
                    batch_definition = {}
        effective_definition_id = str(plan.get("research_definition_id") or batch_definition.get("research_definition_id") or "")
        effective_definition_version = str(plan.get("definition_version") or batch_definition.get("definition_version") or "")
        batch_id = batch_id or "GUIDED_" + uuid.uuid4().hex[:12]
        plan_dir = self.audit_dir / "guided_capture_plans" / plan["plan_id"]
        plan_dir.mkdir(parents=True, exist_ok=True)
        (plan_dir / "statement_anchor.json").write_text(
            json.dumps(plan["anchor"], ensure_ascii=False, indent=2), encoding="utf-8"
        )
        ready = [x for x in plan.get("items", []) if x.get("member_table_role") == "NOTE_DETAIL"
                 and x.get("status") == "READY"
                 and (x.get("certified_note_target") or {}).get("status") == "CERTIFIED_NOTE_TARGET"
                 and x.get("confirmed_note_pdf_page_index")]
        requests = []
        # Each target may have a different note/page; enqueue independently so
        # the old family-wide option cannot overwrite the certified plan.
        for item in ready:
            certified_target = item.get("certified_note_target") or {}
            # ``member_table`` is a stable Registry identity.  It is not
            # necessarily the literal PDF title (for example the registry
            # calls a member "投资组合（按投资品种）" while the PDF heading is
            # "保险资金投资组合").  Capture must use the reviewed PDF heading,
            # while identity remains the Registry member id in the job audit.
            target_query = str(certified_target.get("capture_query_title") or certified_target.get("target_heading") or item["member_table"])
            requests.append(CaptureRequest.new(
                capture_mode=CaptureMode.CERTIFIED_TARGET,
                source_pdf_path=str(Path(pdf_path).resolve()),
                source_pdf_id=str(plan.get("source_pdf_id") or ""),
                research_batch_id=str(research_batch_id or ""),
                research_definition_id=effective_definition_id,
                definition_version=effective_definition_version,
                table_family_id=str(plan["table_family"]),
                member_table_id=str(item["member_table"]),
                certified_target_id=str(certified_target.get("target_id") or ""),
                certified_note_target_id=str(certified_target.get("certified_note_target_id") or ""),
                request_metadata={
                    **options,
                    "batch_id": batch_id,
                    "table_query": target_query,
                    "note_number": item.get("note_reference") or None,
                    "note_reference": item.get("note_reference") or None,
                    "member_table_role": item.get("member_table_role"),
                    "member_table_order": item.get("capture_order"),
                    "source_table_title": (plan.get("anchor") or {}).get("source_table_title") or item.get("member_table"),
                    "statement_scope": (
                        (plan.get("anchor") or {}).get("scope")
                        or item.get("statement_scope")
                        or "UNKNOWN"
                    ),
                    "certified_target": certified_target,
                    "capture_plan_id": plan["plan_id"],
                    "company": plan.get("company"),
                    "report_year": plan.get("report_year"),
                },
            ))
        jobs = self.capture_service.submit_batch(
            requests, batch_id=batch_id, max_workers=max_workers, asynchronous=True
        ) if requests else []
        if research_batch_id:
            with self.registry.connect() as conn:
                conn.execute("INSERT OR IGNORE INTO research_batch_members(research_batch_id,plan_id,source_batch_id,role,status,created_at) VALUES(?,?,?,?,?,datetime('now'))", (research_batch_id, plan["plan_id"], None, "PLAN", "ACTIVE"))
                conn.execute("INSERT OR IGNORE INTO research_batch_members(research_batch_id,plan_id,source_batch_id,role,status,created_at) VALUES(?,?,?,?,?,datetime('now'))", (research_batch_id, None, batch_id, "SOURCE_BATCH", "ACTIVE"))
        self.registry.event("GUIDED_CAPTURE_PLAN_EXECUTED", asset_type="CAPTURE_PLAN", asset_id=plan["plan_id"],
                            payload={"batch_id": batch_id, "jobs": [x["job_id"] for x in jobs], "anchor_artifact": str(plan_dir / "statement_anchor.json")})
        return {"research_batch_id": research_batch_id, "batch_id": batch_id, "jobs": jobs, "anchor_artifact": str(plan_dir / "statement_anchor.json"),
                "blocked_items": [x for x in plan.get("items", []) if x not in ready and x.get("member_table_role") == "NOTE_DETAIL"]}
