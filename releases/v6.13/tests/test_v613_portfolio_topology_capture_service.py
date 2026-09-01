from __future__ import annotations

from copy import deepcopy
from pathlib import Path
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from discovery_registry import DiscoveryRegistry
from metadata_registry import MetadataRegistry
from portfolio_topology_execution_plan import (
    DIRECT_PHYSICAL_TABLE,
    NOTE_CHILD_TABLE,
)
from services.child_capture_execution_service import ChildCaptureExecutionService


def _direct(member: str, physical: str, block: str, axis: str) -> dict:
    return {
        "anchor_child_id": f"ACHILD_{member}",
        "canonical_concept_id": member,
        "member_table": member,
        "portfolio_source_kind": DIRECT_PHYSICAL_TABLE,
        "direct_portfolio_table": True,
        "candidate_note_pdf_page_index": 24,
        "physical_asset_id": physical,
        "logical_block_id": block,
        "classification_axis": axis,
        "physical_bbox": {"x0": 20, "y0": 30, "x1": 500, "y1": 700},
    }


def _note(member: str, ordinal: str) -> dict:
    return {
        "anchor_child_id": f"ACHILD_NOTE_{ordinal}",
        "canonical_concept_id": member,
        "member_table": member,
        "portfolio_source_kind": NOTE_CHILD_TABLE,
        "note_reference_normalized": f"附注{ordinal}",
        "note_target_candidates": [{"pdf_page_index": 180 + int(ordinal)}],
    }


CASES = [
    (
        "DIRECT_SEPARATE_TABLES_SAME_PAGE",
        [
            _direct("portfolio_by_category", "PHYS_A", "BLOCK_A", "BY_INVESTMENT_OBJECT"),
            _direct("portfolio_by_measurement", "PHYS_B", "BLOCK_B", "BY_ACCOUNTING_MEASUREMENT"),
        ],
    ),
    (
        "DIRECT_COMPOUND_TABLE",
        [
            _direct("portfolio_by_category", "PHYS_A", "BLOCK_A", "BY_INVESTMENT_OBJECT"),
            _direct("portfolio_by_measurement", "PHYS_A", "BLOCK_B", "BY_ACCOUNTING_MEASUREMENT"),
        ],
    ),
    (
        "DIRECT_SINGLE_AXIS_TABLE",
        [_direct("portfolio_by_category", "PHYS_A", "BLOCK_A", "BY_INVESTMENT_OBJECT")],
    ),
    (
        "MULTI_NOTE_COMPONENT_SET_NO_REPORTED_TOTAL",
        [_note("portfolio_components", "8"), _note("portfolio_components", "9")],
    ),
    (
        "HYBRID_DIRECT_AND_NOTE_COMPONENTS",
        [
            _direct("portfolio_by_category", "PHYS_A", "BLOCK_A", "BY_INVESTMENT_OBJECT"),
            _note("portfolio_components", "8"),
        ],
    ),
]


class _TargetRepo:
    def __init__(self, targets: dict[str, dict]):
        self.targets = targets

    def certified_target(self, certified_link_id: str) -> dict:
        return deepcopy(self.targets[certified_link_id])


class _Discovery:
    def __init__(self, targets: dict[str, dict]):
        self.repo = _TargetRepo(targets)


def _link_and_target(child: dict, number: int, occurrence_id: str) -> tuple[dict, dict]:
    direct = child["portfolio_source_kind"] == DIRECT_PHYSICAL_TABLE
    link_id = f"CLINK_{number}"
    relation = (
        "DIRECT_PORTFOLIO_WHOLE_TABLE"
        if direct else "STATEMENT_ITEM_TO_NOTE_TABLE"
    )
    link = {
        "certification_status": "CERTIFIED",
        "certified_link_id": link_id,
        "anchor_id": occurrence_id,
        "anchor_child_id": child["anchor_child_id"],
        "table_family_id": "investment_portfolio",
        "member_table_id": child["member_table"],
        "statement_scope": "CONSOLIDATED",
        "research_definition_id": "INVESTMENT_PORTFOLIO_V2",
        "definition_version": "INVESTMENT_PORTFOLIO_V2",
        "pdf_id": "SYNTHETIC_PORTFOLIO_PDF",
        "company": "SYNTHETIC",
        "report_year": "2025",
        "relation_type": relation,
        "logical_table_id": (
            child.get("physical_asset_id")
            if direct else f"LOGICAL_NOTE_{number}"
        ),
    }
    target = {
        "source_pdf_id": "SYNTHETIC_PORTFOLIO_PDF",
        "member_table_id": child["member_table"],
        "statement_scope": "CONSOLIDATED",
        "confirmed_note_pdf_page_index": child.get("candidate_note_pdf_page_index", 188),
        "candidate_note_pdf_page_index": child.get("candidate_note_pdf_page_index", 188),
        "target_heading": child["member_table"],
        "capture_query_title": child["member_table"],
        "logical_table_id": link["logical_table_id"],
        "table_classification": "PRIMARY_TABLE",
        "segment_manifest_status": "CERTIFIED_SEGMENT_MANIFEST",
        "note_table_inventory_status": "COMPLETE",
        "certified_segments": [{"classification": "PRIMARY_TABLE", "start_page": 24}],
        "relation_type": relation,
        "direct_portfolio_table": direct,
    }
    return link, target


def _service_for_case(tmp_path: Path, topology: str, children: list[dict]):
    occurrence_id = f"OCC_{topology}"
    registry = MetadataRegistry(tmp_path / f"{topology}.db")
    DiscoveryRegistry(registry).save_occurrence({
        "occurrence_id": occurrence_id,
        "pdf_id": "SYNTHETIC_PORTFOLIO_PDF",
        "company": "SYNTHETIC",
        "report_year": "2025",
        "statement_type": "NOTE_SECTION",
        "scope": "CONSOLIDATED",
        "display_name": "投资组合",
        "table_family": "investment_portfolio",
        "source_table_title": "投资组合",
        "statement_pdf_page_index": 24,
        "child_rows": children,
        "evidence": {"disclosure_topology": topology},
    })
    links, targets = [], {}
    seen_direct = set()
    for child in children:
        if child["portfolio_source_kind"] == DIRECT_PHYSICAL_TABLE:
            physical = child["physical_asset_id"]
            if physical in seen_direct:
                continue
            seen_direct.add(physical)
        link, target = _link_and_target(child, len(links) + 1, occurrence_id)
        links.append(link)
        targets[link["certified_link_id"]] = target
        if child["portfolio_source_kind"] == DIRECT_PHYSICAL_TABLE:
            target["member_table_ids"] = [
                row["member_table"] for row in children
                if row.get("portfolio_source_kind") == DIRECT_PHYSICAL_TABLE
                and row.get("physical_asset_id") == child.get("physical_asset_id")
            ]
    service = ChildCaptureExecutionService(
        registry=registry,
        capture_service=None,
        table_capture_runner=None,
        research_batch_service=None,
        guided_capture_service=None,
        hierarchical_child_discovery_service=_Discovery(targets),
    )
    return service, links


@pytest.mark.parametrize("topology,children", CASES)
def test_service_layer_accepts_all_five_complete_topology_routes(
    tmp_path: Path, topology: str, children: list[dict]
) -> None:
    service, links = _service_for_case(tmp_path, topology, deepcopy(children))
    plans = service._strict_links_to_plans(
        links,
        source_pdf_map={"SYNTHETIC_PORTFOLIO_PDF": Path("synthetic.pdf")},
        research_definition={
            "definition_id": "INVESTMENT_PORTFOLIO_V2",
            "definition_version": "INVESTMENT_PORTFOLIO_V2",
        },
        scope="CONSOLIDATED",
    )
    assert len(plans) == 1
    plan = plans[0]
    assert plan["portfolio_topology_execution_plan"]["topology"] == topology
    assert plan["portfolio_topology_execution_plan"]["readiness"] == "READY_FOR_STAGE_A_REVIEW"
    details = [item for item in plan["items"] if item["member_table_role"] == "NOTE_DETAIL"]
    expected_execution_members = {link["member_table_id"] for link in links}
    assert {item["member_table"] for item in details} == expected_execution_members
    assert sum(
        item["capture_mode"] == "DIRECT_PORTFOLIO_TABLE" for item in details
    ) == sum(
        link["relation_type"] == "DIRECT_PORTFOLIO_WHOLE_TABLE"
        for link in links
    )
    direct_items = [
        item for item in details
        if item["capture_mode"] == "DIRECT_PORTFOLIO_TABLE"
    ]
    for item in direct_items:
        target = item["certified_note_target"]
        assert target.get("member_table_ids")


def test_service_layer_rejects_hybrid_when_note_branch_is_missing(tmp_path: Path) -> None:
    topology, children = CASES[-1]
    service, links = _service_for_case(tmp_path, topology, deepcopy(children))
    direct_only = [
        link for link in links
        if link["relation_type"] == "DIRECT_PORTFOLIO_WHOLE_TABLE"
    ]
    with pytest.raises(
        PermissionError,
        match="PORTFOLIO_TOPOLOGY_CERTIFICATION_INCOMPLETE",
    ):
        service._strict_links_to_plans(
            direct_only,
            source_pdf_map={"SYNTHETIC_PORTFOLIO_PDF": Path("synthetic.pdf")},
            research_definition={"definition_id": "INVESTMENT_PORTFOLIO_V2"},
            scope="CONSOLIDATED",
        )


def test_service_layer_rejects_compound_when_no_persisted_occurrence(tmp_path: Path) -> None:
    topology, children = CASES[1]
    service, links = _service_for_case(tmp_path, topology, deepcopy(children))
    links[0]["anchor_id"] = "OCC_MISSING"
    with pytest.raises(PermissionError, match="PORTFOLIO_TOPOLOGY_OCCURRENCE_REQUIRED"):
        service._strict_links_to_plans(
            links,
            source_pdf_map={"SYNTHETIC_PORTFOLIO_PDF": Path("synthetic.pdf")},
            research_definition={"definition_id": "INVESTMENT_PORTFOLIO_V2"},
            scope="CONSOLIDATED",
        )
