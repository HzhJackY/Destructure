"""Regression: Stage B searches by registered member semantics, not OCR row text."""
from __future__ import annotations

from generic_structure_parser import GenericStructureParser
from guided_workflow_ui import _member_contract_for_stage_b, _stage_b_amount_caption
from statement_family_resolution import PingAnRowParser


def test_ocr_statement_row_keeps_canonical_member_and_display_only_numbers():
    candidate = {
        "pdf_id": "test.pdf", "statement_type": "BALANCE_SHEET",
        "scope": "CONSOLIDATED", "statement_pdf_page_index": 10,
        "source_table_title": "合并资产负债表", "display_name": "金融投资",
        "statement_item": "交易性金融资产", "raw_member_label": "交易性金融资产",
        "member_table": "fvtpl_assets",
        "member_display_name": "以公允价值计量且其变动计入当期损益的金融资产",
        "canonical_concept_id": "fvtpl_assets",
        "concept_aliases": ["交易性金融资产"], "ocr_used": True,
        "ocr_amount_candidates": ["5,564,558,855", "484,418,369"],
        "note_reference_normalized": "附注七-10", "confidence": 0.95,
    }
    occurrence = GenericStructureParser().parse(
        [candidate], strategy="STATEMENT_PARENT_TO_MULTI_NOTE",
        family_id="financial_investment", display_name="金融投资",
    )[0]
    child = occurrence["child_rows"][0]
    assert child["canonical_concept_id"] == "fvtpl_assets"
    assert child["canonical_display_name"] == "以公允价值计量且其变动计入当期损益的金融资产"
    assert child["statement_amount_raw"] == []
    assert child["ocr_amount_candidates"] == ["5,564,558,855", "484,418,369"]


def test_stage_b_contract_prefers_registry_title_and_aliases():
    class Definitions:
        @staticmethod
        def members(_family_id):
            return [{
                "member_id": "fvtpl_assets",
                "display_name": "以公允价值计量且其变动计入当期损益的金融资产",
                "payload": {"aliases": ["交易性金融资产", "FVTPL金融资产"]},
            }]

    contract = _member_contract_for_stage_b(Definitions(), "financial_investment", {
        "canonical_concept_id": "fvtpl_assets",
        "canonical_display_name": "错误 OCR 名称 5 123",
        "raw_label": "交易性金融资产 5 123",
        "concept_aliases": ["交易性金融资产"],
    })
    assert contract["canonical_title"] == "以公允价值计量且其变动计入当期损益的金融资产"
    assert "交易性金融资产" in contract["exact_aliases"]
    assert "错误 OCR 名称 5 123" not in contract["canonical_title"]


def test_stage_b_caption_does_not_claim_ocr_tokens_are_certified_amounts():
    text = _stage_b_amount_caption({
        "statement_amount_raw": [],
        "inline_note_reference_evidence": {"ocr_amount_candidates": ["484,418,369"]},
    })
    assert "OCR 数值候选" in text
    assert "不参与认证/勾稽" in text


def test_source_row_label_is_not_the_full_numeric_ocr_line():
    member = {
        "member_id": "fvtpl_assets", "display_name": "以公允价值计量且其变动计入当期损益的金融资产",
        "canonical_order": 1, "payload": {"aliases": ["交易性金融资产"]},
    }
    rows = PingAnRowParser().parse(
        ["交易性金融资产 10 5,564,558,855 484,418,369"],
        [("交易性金融资产", member)], "中国平安",
    )
    assert rows[0]["raw_member_label"] == "交易性金融资产"
    assert rows[0]["source_line"].endswith("484,418,369")
