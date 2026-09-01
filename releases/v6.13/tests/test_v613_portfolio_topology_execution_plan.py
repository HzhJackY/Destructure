from __future__ import annotations

from copy import deepcopy
from pathlib import Path

import pytest

from guided_workflow_ui import (
    _clear_stale_guided_discovery_state,
    _effective_guided_definition,
    _guided_discovery_context_identity,
    _portfolio_stage_action,
)
from portfolio_topology_execution_plan import (
    DIRECT_PHYSICAL_TABLE,
    NOTE_CHILD_TABLE,
    build_portfolio_topology_execution_plan,
    evaluate_portfolio_certification_readiness,
)


def _direct_child(
    member: str,
    *,
    physical: str = "PHYS_1",
    block: str = "BLOCK_1",
    axis: str = "BY_INVESTMENT_OBJECT",
) -> dict:
    return {
        "anchor_child_id": f"ACHILD_{member}",
        "canonical_concept_id": member,
        "member_table": member,
        "direct_portfolio_table": True,
        "portfolio_source_kind": DIRECT_PHYSICAL_TABLE,
        "candidate_note_pdf_page_index": 48,
        "physical_asset_id": physical,
        "logical_block_id": block,
        "classification_axis": axis,
        "physical_bbox": {"x0": 20, "y0": 80, "x1": 580, "y1": 700},
    }


def _note_child(member: str = "portfolio_components", ordinal: str = "8") -> dict:
    return {
        "anchor_child_id": f"ACHILD_NOTE_{ordinal}",
        "canonical_concept_id": member,
        "member_table": member,
        "portfolio_source_kind": NOTE_CHILD_TABLE,
        "note_reference_normalized": f"附注{ordinal}",
        "note_target_candidates": [{"pdf_page_index": 180}],
    }


def _occurrence(topology: str, children: list[dict]) -> dict:
    return {
        "occurrence_id": f"OCC_{topology}",
        "pdf_id": "synthetic.pdf",
        "company": "SYNTHETIC",
        "report_year": "2025",
        "scope": "CONSOLIDATED",
        "table_family": "investment_portfolio",
        "disclosure_topology": topology,
        "structure_evidence": {"disclosure_topology": topology},
        "child_rows": children,
    }


@pytest.mark.parametrize(
    "topology,children,route,direct_count,note_count,aggregation",
    [
        (
            "DIRECT_SEPARATE_TABLES_SAME_PAGE",
            [
                _direct_child("portfolio_by_category", physical="PHYS_A", block="BLOCK_A"),
                _direct_child(
                    "portfolio_by_measurement",
                    physical="PHYS_B",
                    block="BLOCK_B",
                    axis="BY_ACCOUNTING_MEASUREMENT",
                ),
            ],
            "DIRECT_ONLY", 2, 0, "KEEP_PHYSICAL_TABLES_SEPARATE",
        ),
        (
            "DIRECT_COMPOUND_TABLE",
            [
                _direct_child("portfolio_by_category", block="BLOCK_A"),
                _direct_child(
                    "portfolio_by_measurement",
                    block="BLOCK_B",
                    axis="BY_ACCOUNTING_MEASUREMENT",
                ),
            ],
            "DIRECT_ONLY", 1, 0, "ONE_PHYSICAL_TWO_LOGICAL_AXES",
        ),
        (
            "DIRECT_SINGLE_AXIS_TABLE",
            [_direct_child("portfolio_by_category")],
            "DIRECT_ONLY", 1, 0, "SINGLE_DISCLOSED_AXIS_NO_MISSING_AXIS",
        ),
        (
            "MULTI_NOTE_COMPONENT_SET_NO_REPORTED_TOTAL",
            [_note_child(ordinal="8"), _note_child(ordinal="9")],
            "NOTE_ONLY", 0, 2, "KEEP_COMPONENTS_SEPARATE_NO_SYNTHETIC_TOTAL",
        ),
        (
            "HYBRID_DIRECT_AND_NOTE_COMPONENTS",
            [
                _direct_child("portfolio_by_category"),
                _note_child(ordinal="8"),
            ],
            "HYBRID", 1, 1, "DIRECT_TOTAL_NOTE_COMPONENTS_NO_DOUBLE_COUNT",
        ),
    ],
)
def test_all_five_topologies_share_one_execution_plan(
    topology, children, route, direct_count, note_count, aggregation
):
    plan = build_portfolio_topology_execution_plan(
        _occurrence(topology, deepcopy(children))
    )
    assert plan["readiness"] == "READY_FOR_STAGE_A_REVIEW"
    assert plan["ui_route"] == route
    assert plan["counts"]["direct_physical_targets"] == direct_count
    assert plan["counts"]["note_child_targets"] == note_count
    assert plan["aggregation_policy"] == aggregation


def test_hybrid_requires_both_certification_branches_before_capture_plan():
    occurrence = _occurrence(
        "HYBRID_DIRECT_AND_NOTE_COMPONENTS",
        [_direct_child("portfolio_by_category"), _note_child(ordinal="8")],
    )
    plan = build_portfolio_topology_execution_plan(occurrence)
    direct_link = {
        "certification_status": "CERTIFIED",
        "relation_type": "DIRECT_PORTFOLIO_WHOLE_TABLE",
        "logical_table_id": "PHYS_1",
    }
    incomplete = evaluate_portfolio_certification_readiness(plan, [direct_link])
    assert incomplete["status"] == "REVIEW_REQUIRED"
    assert incomplete["missing_target_ids"] == ["ACHILD_NOTE_8"]
    note_link = {
        "certification_status": "CERTIFIED",
        "relation_type": "STATEMENT_ITEM_TO_NOTE_TABLE",
        "anchor_child_id": "ACHILD_NOTE_8",
    }
    complete = evaluate_portfolio_certification_readiness(
        plan, [direct_link, note_link]
    )
    assert complete["status"] == "READY_FOR_CAPTURE_PLAN"


def test_compound_ui_route_never_asks_for_note_anchor():
    occurrence = _occurrence(
        "DIRECT_COMPOUND_TABLE",
        [
            _direct_child("portfolio_by_category", block="BLOCK_A"),
            _direct_child(
                "portfolio_by_measurement",
                block="BLOCK_B",
                axis="BY_ACCOUNTING_MEASUREMENT",
            ),
        ],
    )
    action = _portfolio_stage_action([occurrence])
    assert action["is_portfolio"] is True
    assert "直接物理表" in action["stage_a_button"]
    assert "附注目标" not in action["stage_a_button"]
    assert action["routes"] == ["DIRECT_ONLY"]
    target = action["plans"][0]["direct_targets"][0]
    assert target["conditional_logical_members"] == [{
        "member_id": "portfolio_summary",
        "classification_axis": "PORTFOLIO_SUMMARY",
        "activation": "NUMERIC_PREFIX_BEFORE_FIRST_CERTIFIED_AXIS",
        "required": False,
    }]
    assert "portfolio_summary" not in target["member_table_ids"]


def test_hybrid_ui_route_exposes_direct_and_note_in_one_filing():
    occurrence = _occurrence(
        "HYBRID_DIRECT_AND_NOTE_COMPONENTS",
        [_direct_child("portfolio_by_category"), _note_child(ordinal="8")],
    )
    action = _portfolio_stage_action([occurrence])
    assert action["routes"] == ["HYBRID"]
    assert "Direct + Note" in action["stage_a_button"]
    assert action["summaries"][0]["direct_target_count"] == 1
    assert action["summaries"][0]["note_target_count"] == 1


def test_legacy_financial_investment_keeps_existing_note_anchor_action():
    action = _portfolio_stage_action([{
        "table_family": "financial_investment",
        "child_rows": [],
    }])
    assert action["is_portfolio"] is False
    assert action["stage_a_button"] == "② 认证所选 Anchor 并解析附注目标"


def test_multi_note_topology_forbids_source_total_synthesis():
    plan = build_portfolio_topology_execution_plan(_occurrence(
        "MULTI_NOTE_COMPONENTS_NO_TOTAL",
        [_note_child(ordinal="8"), _note_child(ordinal="9")],
    ))
    assert plan["reported_total_policy"] == "NOT_DISCLOSED_NO_SYNTHETIC_TOTAL"
    assert plan["aggregation_policy"] == "KEEP_COMPONENTS_SEPARATE_NO_SYNTHETIC_TOTAL"


def test_hybrid_missing_note_branch_fails_closed():
    occurrence = _occurrence(
        "HYBRID_DIRECT_AND_NOTE_COMPONENTS",
        [_direct_child("portfolio_by_category")],
    )
    plan = build_portfolio_topology_execution_plan(occurrence)
    assert plan["readiness"] == "REVIEW_REQUIRED"
    assert "REQUIRED_NOTE_CHILD_TABLE_SOURCE_MISSING" in plan["blocking_issue_codes"]


def test_switching_definition_clears_stale_v1_topology_ui_state():
    state = {
        "v613_guided_discovery_context_identity": (
            "INVESTMENT_PORTFOLIO_V1", "", ("a.pdf",), "CONSOLIDATED"
        ),
        "v65_clusters": [{"statement_type": "NOTE_SECTION"}],
        "v65_occurrences": [{"table_family": "investment_portfolio"}],
        "v610_certified_child_links": [{"certified_link_id": "OLD"}],
        "unrelated_ui_key": "keep",
    }
    identity = _guided_discovery_context_identity(
        {"definition_id": "INVESTMENT_PORTFOLIO_V2"},
        [Path("a.pdf")],
        "CONSOLIDATED",
        None,
    )
    assert _clear_stale_guided_discovery_state(state, identity) is True
    assert "v65_clusters" not in state
    assert "v65_occurrences" not in state
    assert "v610_certified_child_links" not in state
    assert state["unrelated_ui_key"] == "keep"


def test_portfolio_knowledge_package_routes_new_work_to_v2_definition():
    class _Definitions:
        @staticmethod
        def definition(definition_id):
            assert definition_id == "INVESTMENT_PORTFOLIO_V2"
            return {
                "definition_id": definition_id,
                "status": "ACTIVE",
                "payload": {"selection_status": "CURRENT"},
            }

    selected, route = _effective_guided_definition(
        None, "investment_portfolio", _Definitions()
    )
    assert selected["definition_id"] == "INVESTMENT_PORTFOLIO_V2"
    assert route == "KNOWLEDGE_PACKAGE_ROUTED_TO_INVESTMENT_PORTFOLIO_V2"


def test_financial_knowledge_package_keeps_legacy_generic_entry_unchanged():
    selected, route = _effective_guided_definition(
        None, "financial_investment", object()
    )
    assert selected is None
    assert route == ""
