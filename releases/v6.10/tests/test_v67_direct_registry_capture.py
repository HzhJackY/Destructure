"""Targeted real-PDF acceptance for v6.7 Pattern D registry flow.

This is deliberately a narrow release test: registry definition -> direct
discovery -> anchor and target certification -> capture plan -> real capture.
It does not claim a full historic regression.
"""
from __future__ import annotations

import tempfile
import time
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from backend_context import build_backend_services
from data_home import ensure_data_home

PDF = Path(r"C:\dev\AXA_research\docu\中国平安2023年报.pdf")


def main() -> None:
    assert PDF.is_file(), PDF
    with tempfile.TemporaryDirectory(prefix="v67_direct_capture_") as temp:
        backend = build_backend_services(ensure_data_home(Path(temp), ROOT / "metric_aliases.json"))
        found = backend.generic_discovery_service.discover(
            pdf_path=PDF,
            definition_id="INVESTMENT_PORTFOLIO_V1",
            company="中国平安",
            report_year="2023",
        )
        occurrences = [
            backend.discovery_service.build_occurrence(
                context=dict(raw) | {"pdf_id": str(PDF)},
                parent_text=raw["parent_text"],
                child_rows=raw["child_rows"],
                source_table_title=raw["source_table_title"],
                scope=raw.get("scope", "CONSOLIDATED"),
            )
            for raw in found["occurrences"]
        ]
        assert len(occurrences) == 2
        backend.discovery_service.bulk_adjudicate_anchors(
            [x["occurrence_id"] for x in occurrences], label="ACCEPTED", reason="v6.7 direct registry acceptance"
        )
        plans = []
        for occurrence in occurrences:
            resolved = backend.discovery_service.resolve_note_targets(occurrence)
            child = resolved["child_rows"][0]
            candidate = child["note_target_candidates"][0]
            target = backend.discovery_service.note_resolver.certify(candidate)
            plan = backend.discovery_service.certified_capture_plan(
                resolved, certified_ids=[], certified_targets={child["member_table"]: target}
            )
            assert plan["plan_status"] == "CERTIFIED", plan
            plans.append(plan)
        batch = backend.research_batch_service.create("v6.7 直接披露真实抓取", "投资组合")
        executions = [
            backend.guided_capture_service.execute(plan, pdf_path=PDF, research_batch_id=batch["research_batch_id"], max_workers=2)
            for plan in plans
        ]
        summaries = [
            backend.table_capture_runner.join(x["batch_id"], timeout=100)
            for x in executions
        ]
        assert summaries and all(summary["complete"] for summary in summaries), summaries
        assert all(summary["counts"].get("FAILED", 0) == 0 for summary in summaries), summaries
        # A real table can legitimately be REVIEW_REQUIRED pending structure
        # review; it is still a successfully materialised capture asset.  The
        # active merge subset deliberately excludes it until certified.
        captures = backend.research_batch_service.all_capture_ids(batch["research_batch_id"])
        assert len(captures) == 2, captures
        backend.table_capture_runner.shutdown(wait=True)
    print("DIRECT_DISCLOSURE_CERTIFIED_CAPTURE_PLAN_PASS")
    print("DIRECT_DISCLOSURE_REAL_CAPTURE_PASS")


if __name__ == "__main__":
    main()
