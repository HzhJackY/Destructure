from __future__ import annotations

import tempfile
from pathlib import Path

import pytest
from generic_discovery import discover
from hierarchical_child_discovery import (
    ChildDiscoveryRepository,
    FinancialNoteIndexService,
    HierarchicalChildTableDiscoveryService,
    _subtable_role,
)
from metadata_registry import MetadataRegistry


def _service(tmp: str):
    registry = MetadataRegistry(Path(tmp) / "metadata.db")
    repo = ChildDiscoveryRepository(registry)
    return repo, HierarchicalChildTableDiscoveryService(repo, FinancialNoteIndexService(repo))


def test_anchor_child_preserves_statement_amount_sequence_and_note_context():
    with tempfile.TemporaryDirectory() as tmp:
        repo, _ = _service(tmp)
        anchor = {
            "occurrence_id": "A-1", "scope": "CONSOLIDATED", "report_year": "2025",
            "child_rows": [{
                "item": "其他债权投资", "statement_amounts": [347262, 313148],
                "note_reference_normalized": "附注八-13", "statement_pdf_page_index": 101,
                "bbox": {"x0": 12, "y0": 20},
            }],
        }
        child = repo.create_anchor_children(anchor)[0]
        assert child["statement_amount_raw"] == [347262, 313148]
        assert child["statement_amount_normalized"] == [347262, 313148]
        assert child["inline_note_reference"] == "附注八-13"
        assert child["inline_note_reference_evidence"]["amount_source_present"] is True
        assert child["inline_note_reference_evidence"]["amount_source_page"] == 101


def test_missing_statement_amount_is_blocking_not_no_direct_relation():
    assert HierarchicalChildTableDiscoveryService._reconcile({}, [100, 200]) == (
        "MAIN_STATEMENT_MEMBER_AMOUNT_MISSING", "MISSING_MAIN_STATEMENT_AMOUNT"
    )


def test_primary_and_supplementary_roles_do_not_compete():
    contract = {"canonical_title": "债权投资"}
    assert _subtable_role("债权投资", contract) == "PRIMARY_AMOUNT_DETAIL"
    assert _subtable_role("公允价值变动情况", contract) == "FAIR_VALUE_MOVEMENT"
    assert _subtable_role("信用风险敞口", contract) == "CREDIT_RISK_BREAKDOWN"


def test_source_resolved_explicit_note_target_is_a_tier_one_candidate():
    with tempfile.TemporaryDirectory() as tmp:
        repo, service = _service(tmp)
        anchor = {"occurrence_id": "A-2", "scope": "CONSOLIDATED", "report_year": "2025"}
        child = repo.create_anchor_children({
            **anchor,
            "child_rows": [{
                "item": "债权投资", "statement_amounts": [100],
                "note_reference_normalized": "附注六-6",
                "candidate_note_pdf_page_index": 156,
                "locator_method": "SECTION_ORDINAL_EXACT_HEADING",
            }],
        })[0]
        # Exercise the source-target branch with a lightweight temporary PDF.
        import fitz
        pdf = Path(tmp) / "fixture.pdf"
        document = fitz.open(); document.new_page(); document.save(pdf); document.close()
        result = service.discover(pdf, anchor, child, {"canonical_title": "债权投资"}, "CONSOLIDATED")
        assert result["run"]["tiers_executed"] == ["TIER1"]
        assert result["candidates"][0]["retrieval_method"] == "TIER1_SOURCE_RESOLVED_NOTE_TARGET"


@pytest.mark.skipif(
    not Path(r"C:\dev\AXA_research\docu\中国平安2023年报.pdf").exists(),
    reason="本地真实夹具不可用",
)
def test_real_statement_member_amounts_propagate_from_source_line():
    with tempfile.TemporaryDirectory() as tmp:
        rows = discover(
            Path(r"C:\dev\AXA_research\docu\中国平安2023年报.pdf"), Path(tmp),
            display_name="金融投资", company="中国平安", report_year="2023",
            discovery_context={
                "preferred_statement_type": "BALANCE_SHEET",
                "preferred_scope": "CONSOLIDATED", "require_note_reference": True,
                "core_candidates": ["交易性金融资产", "债权投资", "其他债权投资", "其他权益工具投资"],
            },
        )
        investment_rows = [x for x in rows if x.get("statement_item") == "债权投资"]
        assert investment_rows
        assert any(x.get("amount_source_present") for x in investment_rows)
        assert any(x.get("statement_amounts") for x in investment_rows)
