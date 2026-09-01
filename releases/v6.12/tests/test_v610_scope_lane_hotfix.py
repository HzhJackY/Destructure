from __future__ import annotations

import tempfile
from pathlib import Path

from backend_context import build_backend_services
from data_home import ensure_data_home


ROOT = Path(__file__).resolve().parents[1]


def _backend(tmp: str):
    return build_backend_services(
        ensure_data_home(Path(tmp), ROOT / "metric_aliases.json")
    )


def test_consolidated_request_does_not_materialize_unknown_review_lane():
    with tempfile.TemporaryDirectory() as tmp:
        backend = _backend(tmp)
        occurrences = []
        for year in ("2023", "2024", "2025"):
            for scope, page in (("CONSOLIDATED", 100), ("UNKNOWN", 200)):
                occurrences.append(backend.discovery_registry.save_occurrence({
                    "pdf_id": f"C:/fixtures/pingan-{year}.pdf",
                    "company": "中国平安", "report_year": year,
                    "display_name": "金融投资", "statement_type": "BALANCE_SHEET",
                    "scope": scope, "source_table_title": "合并资产负债表",
                    "statement_pdf_page_index": page, "parent_text": "金融投资",
                    "child_rows": [{"item": "债权投资", "values": [1]}],
                    "evidence": {"formal_statement_region": True},
                }))
        ranked = backend.discovery_service.rank_anchor_candidates(
            occurrences, scope_preference="CONSOLIDATED",
            required_scopes=["CONSOLIDATED"],
        )
        assert len(ranked["candidates"]) == 3
        assert {row["scope"] for row in ranked["candidates"]} == {"CONSOLIDATED"}
        assert {
            (row["pdf_id"], row["scope"]) for row in ranked["candidates"]
        } == {
            (f"C:/fixtures/pingan-{year}.pdf", "CONSOLIDATED")
            for year in ("2023", "2024", "2025")
        }


def test_certified_chosen_scope_materializes_without_overwriting_machine_scope():
    with tempfile.TemporaryDirectory() as tmp:
        backend = _backend(tmp)
        row = backend.discovery_registry.save_occurrence({
            "pdf_id": "C:/fixtures/pingan-2024.pdf",
            "company": "中国平安", "report_year": "2024",
            "display_name": "金融投资", "statement_type": "BALANCE_SHEET",
            "scope": "UNKNOWN", "source_table_title": "合并资产负债表",
            "statement_pdf_page_index": 100, "parent_text": "金融投资",
            "child_rows": [{"item": "债权投资", "values": [1]}],
            "evidence": {},
        })
        backend.discovery_service.adjudicate_anchor(
            row["occurrence_id"], label="ACCEPTED",
            chosen_scope="CONSOLIDATED", reason="真实页人工确认",
            override={"selected_candidate_id": row["occurrence_id"]},
        )
        certified = backend.discovery_registry.get_occurrence(row["occurrence_id"])
        assert certified["scope"] == "CONSOLIDATED"
        assert certified["machine_scope"] == "UNKNOWN"
        assert certified["evidence"]["certified_scope_source"] == (
            "HUMAN_ANCHOR_ADJUDICATION"
        )
