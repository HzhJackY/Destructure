"""Real-PDF v6.6 guided-capture acceptance test (isolated DATA_HOME)."""
from __future__ import annotations

import tempfile
import time
import sys
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from backend_context import build_backend_services
from data_home import ensure_data_home
from note_target_resolver import NoteReferenceResolver
from pdf_evidence import extract_statement_anchor
from statement_anchored_family import StatementOccurrence, build_capture_plan


PDF_DIR = Path(r"C:\dev\AXA_research\docu")


def make_plan(pdf: Path) -> dict:
    raw = extract_statement_anchor(pdf)
    assert raw["status"] == "FOUND", raw
    resolver = NoteReferenceResolver()
    children = []
    for child in raw["children"]:
        candidates = resolver.candidates_from_pdf(pdf, note_reference=child["note_reference_normalized"], member_table=child["member_table"])
        assert candidates, (pdf.name, child["member_table"], "NO_NOTE_CANDIDATE")
        target = resolver.certify(candidates[0])
        assert target["status"] == "CERTIFIED_NOTE_TARGET", target
        children.append(dict(child) | {"certified_note_target": target})
    occurrence = StatementOccurrence(
        occurrence_id=f"REAL_{pdf.stem}", display_name="金融投资", statement_type=raw["statement_type"],
        source_table_title=raw["source_table_title"], scope=raw["scope"],
        statement_pdf_page_index=raw["statement_pdf_page_index"], statement_printed_page=raw["statement_printed_page"],
        parent_text=raw["parent_text"], child_rows=tuple(children), evidence={"real_pdf": str(pdf)},
    )
    plan = build_capture_plan(occurrence, selected_anchor=True)
    plan["plan_id"] = f"REAL_{pdf.stem}"
    plan["pdf_id"] = str(pdf)
    assert plan["plan_status"] == "CERTIFIED", plan
    return plan


def main() -> None:
    pdfs = sorted(PDF_DIR.glob("中国平安20*.pdf"))
    assert len(pdfs) == 3, pdfs
    with tempfile.TemporaryDirectory(prefix="v66_pingan_e2e_") as temp:
        paths = ensure_data_home(Path(temp), ROOT / "metric_aliases.json")
        backend = build_backend_services(paths)
        batch = backend.research_batch_service.create("中国平安真实PDF验收", "金融投资")
        executions = []
        for pdf in pdfs:
            plan = make_plan(pdf)
            # The production guided path persists the certified plan before it
            # can create its parent-batch membership or worker jobs.
            backend.discovery_registry.save_capture_plan(plan)
            executions.append(backend.guided_capture_service.execute(plan, pdf_path=pdf, research_batch_id=batch["research_batch_id"], max_workers=2))
        batch_ids = [row["batch_id"] for row in executions]
        summaries = [
            backend.table_capture_runner.join(batch_id, timeout=180)
            for batch_id in batch_ids
        ]
        assert summaries and all(not item["is_running"] for item in summaries), summaries
        status = [job["status"] for summary in summaries for job in summary["jobs"]]
        assert len(status) == 12, status
        assert not any(value == "FAILED" for value in status), status
        assert all(value in {"SUCCESS", "REVIEW_REQUIRED"} for value in status), status
        result_rows = backend.research_batch_service.result_review(batch["research_batch_id"])
        assert len(result_rows) == 12, result_rows
        assert all(row["capture_quality"] == "READY" for row in result_rows), result_rows
        assert all(row["boundary_status"] == "HARD_BOUNDARY_CONFIRMED" for row in result_rows), result_rows
        assert all(not row["quality_blockers"] for row in result_rows), result_rows
        for row in result_rows:
            capture_id = row["capture_ids"][0]
            record = backend.merge_service.capture_repo.get_many([capture_id])[0]
            persisted = json.loads(
                (Path(record["run_path"]) / "capture_metadata.json").read_text(encoding="utf-8")
            )
            assert persisted["capture_quality_status"] == "READY", persisted
            assert persisted["merge_ready"] is True, persisted
            assert persisted["unresolved_implicit_rows"] == 0, persisted
        print("CURRENT_CAPTURE_QUALITY_PROJECTION_PASS")
        print("CAPTURE_METADATA_LIVE_READINESS_PERSISTENCE_PASS")

        # Defense in depth: even if a caller bypasses the UI/registry filter,
        # MergeService must fail closed on current machine evidence.
        gated_capture_id = result_rows[0]["capture_ids"][0]
        gated_record = backend.merge_service.capture_repo.get_many([gated_capture_id])[0]
        gated_result_path = Path(gated_record["run_path"]) / "table_capture_result.json"
        original_result_text = gated_result_path.read_text(encoding="utf-8")
        gated_result = json.loads(original_result_text)
        gated_result["boundary_status"] = "REVIEW_REQUIRED"
        gated_result_path.write_text(
            json.dumps(gated_result, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        try:
            try:
                backend.merge_service.create(
                    capture_ids=[gated_capture_id],
                    table_id="SHOULD_BE_BLOCKED",
                )
            except ValueError as exc:
                assert "CAPTURE_NOT_MERGE_READY" in str(exc), exc
            else:
                raise AssertionError("REVIEW_REQUIRED_CAPTURE_ENTERED_MERGE")
        finally:
            gated_result_path.write_text(original_result_text, encoding="utf-8")
        print("MERGE_SERVICE_CURRENT_QUALITY_GATE_PASS")

        all_candidates = backend.research_batch_service.rerun_candidates(batch["research_batch_id"], "ALL")
        assert len(all_candidates) == 12, all_candidates
        assert backend.research_batch_service.rerun_candidates(
            batch["research_batch_id"], "REVIEW_REQUIRED"
        ) == []
        rerun_plans = backend.research_batch_service.build_rerun_plans(batch["research_batch_id"], "ALL")
        assert len(rerun_plans) == 3, rerun_plans
        assert all(
            len([item for item in plan["items"] if item.get("member_table_role") == "NOTE_DETAIL"]) == 4
            for plan in rerun_plans
        ), rerun_plans
        assert all(plan.get("rerun_mode") == "ALL" for plan in rerun_plans), rerun_plans
        rerun_executions = [
            backend.guided_capture_service.execute(
                plan,
                pdf_path=Path(plan["pdf_id"]),
                research_batch_id=batch["research_batch_id"],
                max_workers=2,
            )
            for plan in rerun_plans
        ]
        rerun_batch_ids = [row["batch_id"] for row in rerun_executions]
        deadline = time.time() + 180
        rerun_summaries = []
        while time.time() < deadline:
            rerun_summaries = [backend.table_capture_runner.monitor(batch_id) for batch_id in rerun_batch_ids]
            if all(not item["is_running"] for item in rerun_summaries):
                break
            time.sleep(0.5)
        rerun_status = [job["status"] for summary in rerun_summaries for job in summary["jobs"]]
        assert len(rerun_status) == 12 and not any(value == "FAILED" for value in rerun_status), rerun_status
        print("CERTIFIED_ALL_RERUN_PLAN_PASS", len(rerun_plans))
        print("CERTIFIED_ALL_RERUN_EXECUTION_PASS", rerun_status)
        trashed = backend.research_batch_service.trash(batch["research_batch_id"])
        assert trashed["status"] == "TRASHED", trashed
        restored = backend.research_batch_service.restore(batch["research_batch_id"])
        assert restored["status"] == "ACTIVE", restored
        assert all(plan["status"] == "CERTIFIED" for plan in backend.research_batch_service.plan_view(batch["research_batch_id"])), restored
        print("REAL_PINGAN_2023_2025_GUIDED_E2E_PASS", status)
        print("PARENT_BATCH_CAPTURE_TRASH_RESTORE_PASS")


if __name__ == "__main__":
    main()
