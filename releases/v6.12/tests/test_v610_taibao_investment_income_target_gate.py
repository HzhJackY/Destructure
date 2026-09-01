from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from generic_discovery import discover
from generic_structure_parser import GenericStructureParser


PDF_ROOT = Path(r"C:\dev\AXA_research\docu")
PDF_NAMES = [
    "中国太保2023年报.pdf",
    "中国太保2024年报.pdf",
    "中国太保2025年报.pdf",
]
EXPECTED = {
    "中国太保2023年报.pdf": (76, 211, "附注七-40"),
    "中国太保2024年报.pdf": (75, 193, "附注六-35"),
    "中国太保2025年报.pdf": (76, 194, "附注六-35"),
}


@pytest.mark.skipif(
    not all((PDF_ROOT / name).exists() for name in PDF_NAMES),
    reason="中国太保真实 PDF 测试集不可用",
)
def test_real_taibao_investment_income_uses_one_consolidated_anchor_per_pdf():
    context = {
        "preferred_statement_type": "INCOME_STATEMENT",
        "preferred_scope": "CONSOLIDATED",
        "require_note_reference": True,
        "discovery_strategy": "STATEMENT_ITEM_TO_SINGLE_NOTE_COMPLEX_TABLE",
        "core_candidates": ["投资收益"],
    }
    with tempfile.TemporaryDirectory() as tmp:
        for name in PDF_NAMES:
            audit = {}
            rows = discover(
                PDF_ROOT / name, Path(tmp) / "cache",
                display_name="投资收益", company="中国太保",
                report_year=name[-10:-6], discovery_context=context,
                audit_sink=audit,
            )
            assert len(rows) == 1
            row = rows[0]
            expected_statement, expected_note, expected_reference = EXPECTED[name]
            assert row["statement_pdf_page_index"] == expected_statement
            assert row["scope"] == "CONSOLIDATED"
            assert row["candidate_note_pdf_page_index"] == expected_note
            assert row["note_reference_normalized"] == expected_reference
            assert row["note_reference_status"] in {
                "COMPOSED_FROM_HEADER_AND_ROW", "INFERRED"
            }
            assert audit["final_status"] == "FOUND_QUALIFIED_TARGET_AFTER_OCR"
            assert audit["ocr_triggered"] is True


def test_single_statement_item_strategy_materializes_parent_as_note_entry():
    parser = GenericStructureParser()
    occurrences = parser.parse(
        [{
            "display_name": "投资收益",
            "statement_item": "投资收益",
            "member_table": "investment_income",
            "candidate_note_pdf_page_index": 193,
            "confidence": .88,
            "scope": "CONSOLIDATED",
            "statement_type": "INCOME_STATEMENT",
            "statement_pdf_page_index": 9,
        }],
        strategy="STATEMENT_ITEM_TO_SINGLE_NOTE_COMPLEX_TABLE",
        family_id="investment_income",
        display_name="投资收益",
    )
    assert len(occurrences) == 1
    assert len(occurrences[0]["child_rows"]) == 1
    assert occurrences[0]["child_rows"][0]["item"] == "投资收益"
    assert occurrences[0]["child_rows"][0]["candidate_note_pdf_page_index"] == 193
