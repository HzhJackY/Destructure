"""Real-PDF acceptance for a bare “附注” statement column (新华保险 2023)."""
from __future__ import annotations

import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from backend_context import build_backend_services
from data_home import ensure_data_home
from statement_anchored_family import StatementOccurrence, build_capture_plan

PDF = Path(r"C:\dev\AXA_research\docu\新华保险2023年报.pdf")
EXPECTED = {"附注11": 187, "附注12": 188, "附注13": 189, "附注14": 190}


def main() -> None:
    assert PDF.exists(), PDF
    with tempfile.TemporaryDirectory(prefix="v67_xinhua_direct_ordinal_") as tmp:
        backend = build_backend_services(ensure_data_home(Path(tmp), ROOT / "metric_aliases.json"))
        found = backend.generic_discovery_service.discover(
            pdf_path=PDF, definition_id="FINANCIAL_INVESTMENT_V1",
            company="新华保险", report_year="2023",
        )
        anchors = [
            item for item in found["occurrences"]
            if item.get("statement_pdf_page_index") == 109
            and {child.get("note_reference_normalized") for child in item.get("child_rows", [])} == set(EXPECTED)
        ]
        assert len(anchors) == 1, anchors
        raw = anchors[0]
        children = []
        for child in raw["child_rows"]:
            candidates = child.get("note_target_candidates") or []
            assert len(candidates) == 1, child
            assert candidates[0]["pdf_page_index"] == EXPECTED[child["note_reference_normalized"]], child
            children.append(dict(child) | {"certified_note_target": backend.discovery_service.note_resolver.certify(candidates[0])})
        occurrence = StatementOccurrence(
            occurrence_id="XINHUA_2023_BARE_NOTE_COLUMN",
            display_name="金融投资", statement_type=raw["statement_type"],
            source_table_title=raw["source_table_title"], scope=raw["scope"],
            statement_pdf_page_index=raw["statement_pdf_page_index"],
            statement_printed_page=raw.get("statement_printed_page"),
            parent_text=raw["parent_text"], child_rows=tuple(children), evidence=raw.get("evidence", {}),
        )
        plan = build_capture_plan(occurrence, table_family="financial_investment", selected_anchor=True)
        assert plan["plan_status"] == "CERTIFIED", plan
        assert len(plan["items"]) == 5, plan
        print("XINHUA_2023_BARE_NOTE_ANCHOR_PASS")
        print("XINHUA_2023_CERTIFIABLE_NOTE_TARGETS_PASS")


if __name__ == "__main__":
    main()
