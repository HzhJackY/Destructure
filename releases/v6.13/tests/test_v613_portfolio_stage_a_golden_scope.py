from __future__ import annotations

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from unittest.mock import patch

from guided_workflow_ui import (
    _has_formal_anchor_certification,
    _render_golden_anchor_check,
    _restored_anchor_default,
    _union_certified_links,
)


class _FakeStreamlit:
    def __init__(self) -> None:
        self.captions: list[str] = []

    def caption(self, value: str) -> None:
        self.captions.append(value)

    def warning(self, value: str) -> None:
        raise AssertionError(value)

    def dataframe(self, *args, **kwargs) -> None:
        raise AssertionError("Golden dataframe must not render for investment_portfolio")

    def success(self, value: str) -> None:
        raise AssertionError(value)

    def error(self, value: str) -> None:
        raise AssertionError(value)

    def expander(self, *args, **kwargs):
        raise AssertionError("Golden historical evidence must not render for investment_portfolio")


def test_investment_portfolio_never_uses_financial_investment_anchor_golden_gate() -> None:
    st = _FakeStreamlit()
    candidate = {
        "table_family": "investment_portfolio",
        "company": "中国平安",
        "report_year": "2025",
        "child_rows": [
            {"member_table": "portfolio_by_category", "values": [100]},
            {"member_table": "portfolio_by_measurement", "values": [100]},
        ],
    }
    with patch("golden_acceptance.compare_statement_anchor") as comparator, patch(
        "golden_acceptance.compare_portfolio_anchor", return_value={"status": "NO_GOLDEN"},
    ) as portfolio_comparator:
        assert _render_golden_anchor_check(st, candidate) is True
    comparator.assert_not_called()
    portfolio_comparator.assert_called_once()
    assert any("investment_portfolio" in value for value in st.captions)


def test_selected_portfolio_knowledge_package_is_enough_when_candidate_has_no_family_id() -> None:
    st = _FakeStreamlit()
    with patch("golden_acceptance.compare_statement_anchor") as comparator, patch(
        "golden_acceptance.compare_portfolio_anchor", return_value={"status": "NO_GOLDEN"},
    ) as portfolio_comparator:
        assert _render_golden_anchor_check(
            st,
            {"company": "中国平安", "report_year": "2025", "child_rows": []},
            selected_family_id="investment_portfolio",
        ) is True
    comparator.assert_not_called()
    portfolio_comparator.assert_called_once()


def test_financial_investment_keeps_its_existing_anchor_golden_gate() -> None:
    st = _FakeStreamlit()
    candidate = {
        "table_family": "financial_investment",
        "company": "测试保险",
        "report_year": "2025",
        "child_rows": [],
    }
    with patch(
        "golden_acceptance.compare_statement_anchor",
        return_value={"status": "NO_GOLDEN"},
    ) as comparator:
        assert _render_golden_anchor_check(st, candidate) is True
    comparator.assert_called_once_with("测试保险", "2025", [])


class _FakeDiscoveryRegistry:
    def __init__(self, certified_ids: set[str], equivalent_ids: set[str] | None = None) -> None:
        self.certified_ids = certified_ids
        self.equivalent_ids = equivalent_ids or set()

    def get_occurrence(self, occurrence_id: str) -> dict:
        return {
            "occurrence_id": occurrence_id,
            "status": "ANCHOR_CERTIFIED" if occurrence_id in self.certified_ids else "NEEDS_REVIEW",
        }

    def is_anchor_certified(self, occurrence_id: str) -> bool:
        return occurrence_id in self.certified_ids

    def is_equivalent_anchor_certified(self, candidate: dict) -> bool:
        return str(candidate.get("occurrence_id")) in self.equivalent_ids


def test_stage_a_restores_formal_certification_before_score_recommendation() -> None:
    rows = [{"occurrence_id": "LOW_SCORE_CERTIFIED"}, {"occurrence_id": "HIGH_SCORE"}]
    selected = _restored_anchor_default(
        rows, {"HIGH_SCORE"}, _FakeDiscoveryRegistry({"LOW_SCORE_CERTIFIED"}),
    )
    assert selected == "LOW_SCORE_CERTIFIED"


def test_stage_a_keeps_unrecommended_uncertified_candidate_unselected() -> None:
    rows = [{"occurrence_id": "LOW_SCORE"}]
    selected = _restored_anchor_default(
        rows, set(), _FakeDiscoveryRegistry(set()),
    )
    assert selected is None


def test_stage_a_restores_append_only_occurrence_by_certified_physical_identity() -> None:
    rows = [{"occurrence_id": "FRESH_OCCURRENCE", "statement_pdf_page_index": 48}]
    selected = _restored_anchor_default(
        rows, set(), _FakeDiscoveryRegistry(set(), {"FRESH_OCCURRENCE"}),
    )
    assert selected == "FRESH_OCCURRENCE"


def test_equivalent_formal_anchor_is_recognized_for_audit_only_gate_display() -> None:
    registry = _FakeDiscoveryRegistry(set(), {"FRESH_OCCURRENCE"})
    assert _has_formal_anchor_certification(
        {"occurrence_id": "FRESH_OCCURRENCE"}, registry,
    ) is True
    assert _has_formal_anchor_certification(
        {"occurrence_id": "UNRESOLVED_OCCURRENCE"}, registry,
    ) is False


def test_stage_a_unions_current_and_restored_certified_links_by_owner_id() -> None:
    merged = _union_certified_links(
        [
            {"certified_link_id": "CLINK_B", "fresh": True},
            {"certified_link_id": "CLINK_C"},
        ],
        [
            {"certified_link_id": "CLINK_A"},
            {"certified_link_id": "CLINK_B", "fresh": False},
        ],
    )
    assert [row["certified_link_id"] for row in merged] == [
        "CLINK_A", "CLINK_B", "CLINK_C",
    ]
    assert next(row for row in merged if row["certified_link_id"] == "CLINK_B")[
        "fresh"
    ] is True
