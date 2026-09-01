"""Execute a certified capture plan without returning to manual target input."""
from __future__ import annotations

import json
import uuid
from pathlib import Path
from typing import Any

from .table_family_service import build_family


class GuidedCaptureService:
    def __init__(self, *, registry, runner, audit_dir: Path):
        self.registry = registry
        self.runner = runner
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
        family = build_family("GUIDED_" + plan["plan_id"], plan["table_family"], [
            {"name": x["member_table"], "role": "NOTE_DETAIL", "required": False} for x in ready
        ])
        jobs = []
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
            member_family = build_family("GUIDED_" + plan["plan_id"], plan["table_family"], [
                {"name": target_query, "role": "NOTE_DETAIL", "required": False}
            ])
            jobs.extend(self.runner.enqueue(
                pdf_paths=[Path(pdf_path)], family=member_family, batch_id=batch_id,
                options=options | {"note_number": item.get("note_reference") or None,
                                   "note_reference": item.get("note_reference") or None,
                                   "member_table": item.get("member_table"),
                                   "member_table_role": item.get("member_table_role"),
                                   "member_table_order": item.get("capture_order"),
                                   "source_table_title": (plan.get("anchor") or {}).get("source_table_title") or item.get("member_table"),
                                   "start_page_override": item.get("confirmed_note_pdf_page_index"),
                                   "certified_note_target": certified_target,
                                   "guided_target_required": True},
            ))
            # Preserve the plan-item identity in immutable job payload audit;
            # result review must not infer membership from a table-name string.
            for job in jobs[-1:]:
                with self.registry.connect() as current:
                    row = current.execute("SELECT payload_json FROM jobs WHERE job_id=?", (job["job_id"],)).fetchone()
                    payload = json.loads(row["payload_json"] or "{}") if row else {}
                    payload["capture_plan_id"] = plan["plan_id"]
                    payload["plan_member_table"] = item["member_table"]
                    payload["certified_note_target"] = certified_target
                    payload["capture_query_title"] = target_query
                    current.execute("UPDATE jobs SET payload_json=? WHERE job_id=?", (json.dumps(payload, ensure_ascii=False), job["job_id"]))
        if jobs:
            self.runner.start(batch_id=batch_id, max_workers=max_workers)
        if research_batch_id:
            with self.registry.connect() as conn:
                conn.execute("INSERT OR IGNORE INTO research_batch_members(research_batch_id,plan_id,source_batch_id,role,status,created_at) VALUES(?,?,?,?,?,datetime('now'))", (research_batch_id, plan["plan_id"], None, "PLAN", "ACTIVE"))
                conn.execute("INSERT OR IGNORE INTO research_batch_members(research_batch_id,plan_id,source_batch_id,role,status,created_at) VALUES(?,?,?,?,?,datetime('now'))", (research_batch_id, None, batch_id, "SOURCE_BATCH", "ACTIVE"))
        self.registry.event("GUIDED_CAPTURE_PLAN_EXECUTED", asset_type="CAPTURE_PLAN", asset_id=plan["plan_id"],
                            payload={"batch_id": batch_id, "jobs": [x["job_id"] for x in jobs], "anchor_artifact": str(plan_dir / "statement_anchor.json")})
        return {"research_batch_id": research_batch_id, "batch_id": batch_id, "jobs": jobs, "anchor_artifact": str(plan_dir / "statement_anchor.json"),
                "blocked_items": [x for x in plan.get("items", []) if x not in ready and x.get("member_table_role") == "NOTE_DETAIL"]}
