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
                max_workers: int = 3, options: dict[str, Any] | None = None) -> dict[str, Any]:
        """Materialise the anchor, enqueue only READY detail rows, then start.

        The anchor is an immutable statement evidence artifact, not a synthetic
        financial table. Detail jobs retain their own note/page constraints.
        """
        options = dict(options or {})
        batch_id = batch_id or "GUIDED_" + uuid.uuid4().hex[:12]
        plan_dir = self.audit_dir / "guided_capture_plans" / plan["plan_id"]
        plan_dir.mkdir(parents=True, exist_ok=True)
        (plan_dir / "statement_anchor.json").write_text(
            json.dumps(plan["anchor"], ensure_ascii=False, indent=2), encoding="utf-8"
        )
        ready = [x for x in plan.get("items", []) if x.get("member_table_role") == "NOTE_DETAIL" and x.get("status") == "READY"]
        family = build_family("GUIDED_" + plan["plan_id"], plan["table_family"], [
            {"name": x["member_table"], "role": "NOTE_DETAIL", "required": False} for x in ready
        ])
        jobs = []
        # Each target may have a different note/page; enqueue independently so
        # the old family-wide option cannot overwrite the certified plan.
        for item in ready:
            member_family = build_family("GUIDED_" + plan["plan_id"], plan["table_family"], [
                {"name": item["member_table"], "role": "NOTE_DETAIL", "required": False}
            ])
            jobs.extend(self.runner.enqueue(
                pdf_paths=[Path(pdf_path)], family=member_family, batch_id=batch_id,
                options=options | {"note_number": item.get("note_reference") or None,
                                   "start_page_override": item.get("confirmed_note_pdf_page_index") or item.get("candidate_note_pdf_page_index")},
            ))
        if jobs:
            self.runner.start(batch_id=batch_id, max_workers=max_workers)
        self.registry.event("GUIDED_CAPTURE_PLAN_EXECUTED", asset_type="CAPTURE_PLAN", asset_id=plan["plan_id"],
                            payload={"batch_id": batch_id, "jobs": [x["job_id"] for x in jobs], "anchor_artifact": str(plan_dir / "statement_anchor.json")})
        return {"batch_id": batch_id, "jobs": jobs, "anchor_artifact": str(plan_dir / "statement_anchor.json"),
                "blocked_items": [x for x in plan.get("items", []) if x.get("status") != "READY" and x.get("member_table_role") == "NOTE_DETAIL"]}
