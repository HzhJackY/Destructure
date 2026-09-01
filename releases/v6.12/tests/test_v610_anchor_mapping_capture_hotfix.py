from __future__ import annotations

from pathlib import Path

import pytest

from anchor_candidate_selection import rank_and_preselect
from hierarchical_child_discovery import (
    ChildDiscoveryRepository,
    FinancialNoteIndexService,
    HierarchicalChildTableDiscoveryService,
    _capture_query_heading,
)
from metadata_registry import MetadataRegistry
from table_boundary_resolver import match_peer_note_heading, resolve_table_boundary


def _anchor(occurrence_id: str, *, historical: bool) -> dict:
    children = [
        {
            "item": f"子项{i}", "value": 100 + i,
            "note_reference_normalized": f"附注八-{9 + i}", "data_year": "2023",
        }
        for i in range(4)
    ]
    return {
        "occurrence_id": occurrence_id, "pdf_id": "PDF_A", "scope": "CONSOLIDATED",
        "display_name": "金融投资", "parent_text": "金融投资",
        "statement_type": "BALANCE_SHEET", "source_table_title": "合并资产负债表",
        "statement_pdf_page_index": 100 if historical else 101, "child_rows": children,
        "evidence": {
            "formal_statement_region": True, "period_headers": ["2023", "2022"],
            "unit": "CNY_MILLION", "amount_columns_present": True,
            "amount_columns_aligned": True, "bbox_verified": True,
            "historical_certified_support": historical,
            "research_definition_match": historical,
        },
    }


def _complete_inventory(*, title: str) -> dict:
    return {
        "note_table_inventory_candidate_id":"INV_C1",
        "inventory_status":"COMPLETE",
        "logical_tables":[{
            "logical_table_candidate_id":"LOGICAL_C1",
            "classification":"PRIMARY_TABLE",
            "title":title,
            "confidence":0.99,
            "segments":[],
        }],
    }


def test_unique_perfect_anchor_preselects_despite_small_margin():
    perfect = _anchor("PERFECT", historical=True)
    near_perfect = _anchor("NEAR", historical=False)
    ranked = rank_and_preselect([perfect, near_perfect], {"required_scopes": ["CONSOLIDATED"]})
    assert ranked["candidates"][0]["total_score"] == 1.0
    assert ranked["candidates"][1]["total_score"] >= 0.90
    assert ranked["preselected_ids"] == ["PERFECT"]
    decision = next(iter(ranked["scope_decisions"].values()))
    assert decision["status"] == "SINGLE_PRESELECTED_EXACT_MAXIMUM"


def test_sole_viable_child_mapping_is_preselected_for_review_form():
    class Repo:
        def save_link_candidates(self, rows):
            self.rows = rows

    service = object.__new__(HierarchicalChildTableDiscoveryService)
    service.repo = Repo()
    anchor = {"occurrence_id": "A1"}
    child = {"anchor_child_id": "AC1", "statement_scope": "CONSOLIDATED", "raw_label": "债权投资"}
    enriched = [{
        "candidate_id": "C1", "base_score": 0.62, "raw_heading": "10. 债权投资",
        "score_breakdown": {"evidence_score": 0.30, "penalties": 0.0},
        "hard_gate_results": {"source_pdf_match": True, "heading_found": True},
        "reconciliation_candidates": [{"relation": "EXACT_TOTAL", "status": "PASS_EXACT"}],
        "certification_score": 0.62,
        "note_table_inventory":_complete_inventory(title="10. 债权投资"),
    }]
    rows = service.link_candidates(anchor, child, enriched, {"member_table_id": "debt_investment", "canonical_title": "债权投资"})
    assert len(rows) == 1
    assert rows[0]["is_preselected"] is True
    assert rows[0]["preselection_reason"] == "SOLE_VIABLE_PRIMARY_CANDIDATE"


def test_note_ordinal_is_removed_only_from_capture_query():
    assert _capture_query_heading("12. 其他权益工具投资") == "其他权益工具投资"
    assert _capture_query_heading("(3) 以公允价值计量且其变动计入当期损益的金融资产。") == (
        "以公允价值计量且其变动计入当期损益的金融资产"
    )


def test_mismatched_explicit_note_reference_is_not_preselected():
    class Repo:
        def save_link_candidates(self, rows):
            self.rows = rows

    service = object.__new__(HierarchicalChildTableDiscoveryService)
    service.repo = Repo()
    rows = service.link_candidates(
        {"occurrence_id": "A1"},
        {
            "anchor_child_id": "AC1", "statement_scope": "CONSOLIDATED",
            "raw_label": "金融资产", "inline_note_reference": "附注八-9",
        },
        [{
            "candidate_id": "C1", "base_score": 0.62,
            "raw_heading": "(3) 金融资产", "note_reference": "3",
            "score_breakdown": {"evidence_score": 0.30, "penalties": 0.0},
            "hard_gate_results": {"source_pdf_match": True, "heading_found": True},
            "reconciliation_candidates": [{"relation": "NO_DIRECT_AMOUNT_RELATION", "status": "NOT_TESTABLE"}],
            "certification_score": 0.92,
            "note_table_inventory":_complete_inventory(title="(3) 金融资产"),
        }],
        {"member_table_id": "financial_asset"},
    )
    assert rows[0]["hard_gate_results"]["note_reference_matches_anchor"] is False
    assert rows[0]["is_preselected"] is False
    assert "note_reference_matches_anchor" in rows[0]["blocking_warnings"]


def test_unique_tier1_note_identity_can_defer_main_statement_amount_relation():
    class Repo:
        def save_link_candidates(self, rows):
            self.rows = rows

    service = object.__new__(HierarchicalChildTableDiscoveryService)
    service.repo = Repo()
    rows = service.link_candidates(
        {"occurrence_id":"A1","table_family":"financial_investment"},
        {
            "anchor_child_id":"AC1","statement_scope":"CONSOLIDATED",
            "raw_label":"债权投资","inline_note_reference":"附注七-11",
        },
        [{
            "candidate_id":"C1","base_score":1.0,
            "raw_heading":"债权投资","note_reference":"附注七-11",
            "retrieval_tier":"TIER1",
            "score_breakdown":{"evidence_score":0.98,"penalties":0.45},
            "hard_gate_results":{
                "source_pdf_match":True,"heading_found":True,
                "main_statement_amount_present":False,
            },
            "negative_evidence":["MAIN_STATEMENT_MEMBER_AMOUNT_MISSING"],
            "reconciliation_candidates":[{
                "relation":"MAIN_STATEMENT_MEMBER_AMOUNT_MISSING",
                "status":"MISSING_MAIN_STATEMENT_AMOUNT",
            }],
            "certification_score":0.57,
            "note_table_inventory":_complete_inventory(title="债权投资"),
        }],
        {"member_table_id":"debt_investment"},
    )

    assert rows[0]["is_preselected"] is True
    assert rows[0]["preselection_reason"]==(
        "SOLE_VIABLE_NOTE_IDENTITY_WITHOUT_AMOUNT_RECONCILIATION"
    )


def test_numeric_amount_is_not_a_peer_note_boundary_heading():
    assert match_peer_note_heading("93.15亿元的其他权益工具") is None
    assert match_peer_note_heading("3. 衍生金融工具") == (3, "衍生金融工具")


def test_missing_note_ordinal_does_not_invent_a_peer_hard_boundary():
    boundary = resolve_table_boundary(
        note_reference="", title="债权投资", start_page=1, start_y=20, title_x0=20,
        page_count=2, page_height=lambda _page: 800,
        page_lines=lambda page: ([
            {"text": "93.15亿元的其他权益工具", "x0": 20, "y0": 200, "words": []},
            {"text": "3. 衍生金融工具", "x0": 20, "y0": 300, "words": []},
        ] if page == 1 else []),
    )
    # 无当前附注序号时不发明硬边界：footer 兜底保持 MEDIUM，next_note_verified=False
    assert boundary["boundary_reason"] == "same_page_footer_fallback"
    assert boundary["boundary_confidence"] == "MEDIUM"
    assert boundary["boundary_evidence"]["next_note_verified"] is False


@pytest.mark.skipif(
    not Path(r"C:\dev\AXA_research\docu\中国太保2023年报.pdf").exists(),
    reason="本地真实夹具不可用",
)
def test_real_taibao_2023_certified_raw_headings_keep_spatial_boundary_capture():
    """Certified capture must use source headings, not Registry member ids."""
    from table_capture import capture_named_table

    pdf = Path(r"C:\dev\AXA_research\docu\中国太保2023年报.pdf")
    cases = [
        ("以公允价值计量且其变动计入当期损益的金融资产（仅适用2022年）", "2", 165),
        ("可供出售金融资产（仅适用2022年）", "7", 168),
        ("投资收益", "40", 211),
    ]
    for heading, note_reference, page in cases:
        captured = capture_named_table(
            pdf, heading, note_number=note_reference, start_page_override=page,
            strict_target_identity=True, allow_legacy_fallback=False,
            certified_target_heading=heading,
        )
        assert captured.columns
        assert captured.rows
        assert captured.stats.get("boundary_reason")
        assert captured.stats.get("boundary_reason") != "next_peer_heading_93"


@pytest.mark.skipif(
    not Path(r"C:\Users\HzhJa\FinancialMetricResolverData\uploads\860c455bbad9_中国平安2025年报.pdf").exists(),
    reason="本地真实夹具不可用",
)
def test_real_pingan_split_note_ordinal_is_composed_and_capturable(tmp_path):
    pdf = Path(r"C:\Users\HzhJa\FinancialMetricResolverData\uploads\860c455bbad9_中国平安2025年报.pdf")
    registry = MetadataRegistry(tmp_path / "metadata.db")
    index = FinancialNoteIndexService(ChildDiscoveryRepository(registry))
    built = index.build(pdf)
    headings = index.headings(built["index_id"])
    note9 = [
        row for row in headings
        if str(row.get("note_ordinal") or "") == "9"
        and row.get("normalized_heading") == "以公允价值计量且其变动计入当期损益的金融资产"
        and int(row["start_page"]) == 262
    ]
    assert len(note9) == 1

    from table_capture import capture_named_table
    for title, note, page in [
        ("以公允价值计量且其变动计入当期损益的金融资产", "附注八-9", 262),
        ("债权投资", "附注八-10", 262),
        ("其他债权投资", "附注八-11", 263),
        ("其他权益工具投资", "附注八-12", 263),
    ]:
        captured = capture_named_table(
            pdf, title, note_number=note, start_page_override=page,
            strict_target_identity=True, allow_legacy_fallback=False,
            certified_target_heading=title,
        )
        assert captured.columns
        assert captured.rows
