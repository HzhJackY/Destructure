"""v6.10 investment portfolio discovery and classification contracts."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from statement_note_navigation import (
    DISCLOSURE_SECTION_PATTERNS,
    ABSENCE_CLASSIFICATIONS,
    classify_absence,
)
from generic_discovery_engine import GenericDiscoveryService
_has_table_evidence = GenericDiscoveryService._has_table_evidence
from research_definition_registry import BUILTIN_FAMILIES, BUILTIN_MEMBERS


def test_disclosure_section_patterns_defined() -> None:
    assert "MANAGEMENT_DISCUSSION" in DISCLOSURE_SECTION_PATTERNS
    assert "INVESTMENT_BUSINESS_ANALYSIS" in DISCLOSURE_SECTION_PATTERNS
    assert "BUSINESS_REVIEW" in DISCLOSURE_SECTION_PATTERNS
    print("DISCLOSURE_SECTION_PATTERNS_DEFINED_PASS")


def test_absence_classifications_defined() -> None:
    assert "FOUND_CANONICAL_TABLE" in ABSENCE_CLASSIFICATIONS
    assert "FOUND_DISCLOSURE_VARIANT" in ABSENCE_CLASSIFICATIONS
    assert "LEGITIMATELY_ABSENT" in ABSENCE_CLASSIFICATIONS
    assert "NARRATIVE_ONLY" in ABSENCE_CLASSIFICATIONS
    assert "DISCOVERY_FAILED" in ABSENCE_CLASSIFICATIONS
    print("ABSENCE_CLASSIFICATIONS_DEFINED_PASS")


def test_classify_absence_canonical() -> None:
    result = classify_absence(
        candidates_found=1, exact_title_match=True,
        certified_alias_match=False, section_searched=True,
        table_evidence=True, narrative_only=False,
    )
    assert result == "FOUND_CANONICAL_TABLE", f"Got {result}"
    print("CLASSIFY_ABSENCE_CANONICAL_PASS")


def test_classify_absence_variant() -> None:
    result = classify_absence(
        candidates_found=1, exact_title_match=False,
        certified_alias_match=True, section_searched=True,
        table_evidence=True, narrative_only=False,
    )
    assert result == "FOUND_DISCLOSURE_VARIANT", f"Got {result}"
    print("CLASSIFY_ABSENCE_VARIANT_PASS")


def test_classify_absence_narrative_only() -> None:
    result = classify_absence(
        candidates_found=1, exact_title_match=False,
        certified_alias_match=True, section_searched=True,
        table_evidence=False, narrative_only=True,
    )
    assert result == "NARRATIVE_ONLY", f"Got {result}"
    print("CLASSIFY_ABSENCE_NARRATIVE_ONLY_PASS")


def test_classify_absence_legitimately_absent() -> None:
    result = classify_absence(
        candidates_found=0, exact_title_match=False,
        certified_alias_match=False, section_searched=True,
        table_evidence=False, narrative_only=False,
        human_reviewed=True,
    )
    assert result == "LEGITIMATELY_ABSENT", f"Got {result}"
    print("CLASSIFY_ABSENCE_LEGITIMATELY_ABSENT_PASS")


def test_classify_absence_discovery_failed() -> None:
    result = classify_absence(
        candidates_found=0, exact_title_match=False,
        certified_alias_match=False, section_searched=False,
        table_evidence=False, narrative_only=False,
    )
    assert result == "DISCOVERY_FAILED", f"Got {result}"
    print("CLASSIFY_ABSENCE_DISCOVERY_FAILED_PASS")


def test_classify_absence_unresolved() -> None:
    result = classify_absence(
        candidates_found=0, exact_title_match=False,
        certified_alias_match=False, section_searched=True,
        table_evidence=False, narrative_only=False,
    )
    assert result == "UNRESOLVED", f"Got {result}"
    print("CLASSIFY_ABSENCE_UNRESOLVED_PASS")


def test_has_table_evidence_true() -> None:
    assert _has_table_evidence("现金 100 债券 200 股票 300 基金 400")
    print("HAS_TABLE_EVIDENCE_TRUE_PASS")


def test_has_table_evidence_false() -> None:
    assert not _has_table_evidence("公司投资业务持续发展，取得了良好的业绩")
    print("HAS_TABLE_EVIDENCE_FALSE_PASS")


def test_portfolio_family_exists() -> None:
    assert "investment_portfolio" in BUILTIN_FAMILIES
    fp = BUILTIN_FAMILIES["investment_portfolio"]
    assert fp["discovery_strategy"] == "DIRECT_NOTE_TABLE_FAMILY"
    print("PORTFOLIO_FAMILY_EXISTS_PASS")


def test_portfolio_members_have_classification_axis() -> None:
    members = BUILTIN_MEMBERS.get("investment_portfolio", [])
    assert len(members) >= 2
    axes = {m.get("classification_axis") for m in members}
    assert "BY_INVESTMENT_OBJECT" in axes
    assert "BY_ACCOUNTING_MEASUREMENT" in axes
    print("PORTFOLIO_MEMBERS_CLASSIFICATION_AXIS_PASS")


def test_portfolio_members_have_ratio_reconciliation() -> None:
    members = BUILTIN_MEMBERS.get("investment_portfolio", [])
    for m in members:
        assert m.get("ratio_total_reconciliation") is True, f"{m['member_id']} missing ratio reconciliation"
    print("PORTFOLIO_RATIO_RECONCILIATION_PASS")


def test_investment_asset_situation_alias() -> None:
    """投资资产情况 maps to the same portfolio family."""
    members = BUILTIN_MEMBERS.get("investment_portfolio", [])
    category = next((m for m in members if m["member_id"] == "portfolio_by_category"), None)
    assert category is not None
    aliases = category.get("aliases", [])
    assert "投资资产情况" in aliases
    assert "投资组合情况" in aliases
    print("INVESTMENT_ASSET_SITUATION_ALIAS_PASS")


def test_axes_not_collapsed() -> None:
    """BY_INVESTMENT_OBJECT != BY_ACCOUNTING_MEASUREMENT."""
    members = BUILTIN_MEMBERS.get("investment_portfolio", [])
    axes = {m["member_id"]: m.get("classification_axis") for m in members}
    assert axes.get("portfolio_by_category") != axes.get("portfolio_by_measurement"), (
        "Two classification axes must not be collapsed"
    )
    print("AXES_NOT_COLLAPSED_PASS")


def main() -> None:
    test_disclosure_section_patterns_defined()
    test_absence_classifications_defined()
    test_classify_absence_canonical()
    test_classify_absence_variant()
    test_classify_absence_narrative_only()
    test_classify_absence_legitimately_absent()
    test_classify_absence_discovery_failed()
    test_classify_absence_unresolved()
    test_has_table_evidence_true()
    test_has_table_evidence_false()
    test_portfolio_family_exists()
    test_portfolio_members_have_classification_axis()
    test_portfolio_members_have_ratio_reconciliation()
    test_investment_asset_situation_alias()
    test_axes_not_collapsed()
    print("\n=== ALL 15 INVESTMENT PORTFOLIO TESTS PASSED ===")


if __name__ == "__main__":
    main()
