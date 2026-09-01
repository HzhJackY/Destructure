"""Real-PDF execution smoke test for the v6.5.1 guided capture path.

It uses an isolated temporary DATA_HOME, so the test never changes the user's
production capture registry.  REVIEW_REQUIRED is an acceptable success state:
the table was captured but requires a later human structure review.
"""
from __future__ import annotations

from pathlib import Path
import sys
import tempfile
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend_context import build_backend_services
from data_home import ensure_data_home
from note_target_resolver import NoteReferenceResolver
from pdf_evidence import extract_statement_anchor
from statement_anchored_family import StatementOccurrence, build_capture_plan


def main() -> None:
    release = Path(__file__).resolve().parents[1]
    fixture_root = Path(r"C:\dev\AXA_research\docu")
    with tempfile.TemporaryDirectory(prefix="fmr_v651_capture_") as temp:
        backend = build_backend_services(ensure_data_home(Path(temp), release / "metric_aliases.json"))
        batches: list[str] = []
        for year in ("2023", "2024", "2025"):
            pdf = next(fixture_root.glob(f"中国平安{year}年报.pdf"))
            found = extract_statement_anchor(pdf)
            assert found["status"] == "FOUND", (year, found)
            resolver = NoteReferenceResolver()
            certified_children = []
            for child in found["children"]:
                candidates = resolver.candidates_from_pdf(pdf, note_reference=child["note_reference_normalized"], member_table=child["member_table"])
                assert candidates, (year, child["member_table"])
                certified_children.append(dict(child) | {"certified_note_target": resolver.certify(candidates[0])})
            occurrence = StatementOccurrence(
                f"OCC_{year}", "金融投资", "BALANCE_SHEET", found["source_table_title"], "CONSOLIDATED",
                found["statement_pdf_page_index"], found["statement_printed_page"], "金融投资", tuple(certified_children), {},
            )
            plan = build_capture_plan(occurrence, selected_anchor=True)
            plan.update({"plan_id": f"TEST_PLAN_{year}", "anchor_occurrence_id": occurrence.occurrence_id, "pdf_id": str(pdf)})
            result = backend.guided_capture_service.execute(plan, pdf_path=pdf, batch_id=f"TEST_GUIDED_{year}", max_workers=3)
            assert len(result["jobs"]) == 4
            batches.append(result["batch_id"])
        deadline = time.time() + 110
        summaries = {}
        while time.time() < deadline:
            summaries = {batch: backend.table_capture_runner.monitor(batch) for batch in batches}
            if all(not summary["is_running"] for summary in summaries.values()):
                break
            time.sleep(0.5)
        assert all(not summary["is_running"] for summary in summaries.values()), summaries
        assert sum(summary["total"] for summary in summaries.values()) == 12
        assert all(summary["counts"].get("FAILED", 0) == 0 for summary in summaries.values()), summaries
        assert sum(summary["counts"].get("SUCCESS", 0) + summary["counts"].get("REVIEW_REQUIRED", 0) for summary in summaries.values()) == 12
    print("REAL_THREE_PDF_TWELVE_DETAIL_CAPTURE_PASS")


if __name__ == "__main__":
    main()
