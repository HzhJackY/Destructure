from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace
import json

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from metadata_registry import MetadataRegistry
from research_definition_registry import ResearchDefinitionService

from investment_portfolio_topology_contract import (
    INVESTMENT_PORTFOLIO_TOPOLOGY_CONTRACT,
)
from research_definition_registry import BUILTIN_MEMBERS
from services.capture_service import (
    _certified_member_for_axis,
    _direct_bundle_order,
)


def test_portfolio_summary_registry_member_is_optional_and_first() -> None:
    members = BUILTIN_MEMBERS["investment_portfolio"]
    summary = next(row for row in members if row["member_id"] == "portfolio_summary")
    assert summary["required"] is False
    assert summary["canonical_order"] == 1
    assert summary["classification_axis"] == "PORTFOLIO_SUMMARY"
    assert {row["member_id"]: row["canonical_order"] for row in members} == {
        "portfolio_summary": 1,
        "portfolio_by_category": 2,
        "portfolio_by_measurement": 3,
        "portfolio_components": 4,
    }


def test_direct_contract_declares_conditional_member_not_required() -> None:
    compound = INVESTMENT_PORTFOLIO_TOPOLOGY_CONTRACT["topologies"][
        "DIRECT_COMPOUND_TABLE"
    ]
    assert "portfolio_summary" not in compound["required_members"]
    assert compound["conditional_logical_members"] == [{
        "member_id": "portfolio_summary",
        "classification_axis": "PORTFOLIO_SUMMARY",
        "activation": "NUMERIC_PREFIX_BEFORE_FIRST_CERTIFIED_AXIS",
        "required": False,
    }]


def test_capture_member_mapping_reads_conditional_axis() -> None:
    target = {
        "classification_axes": [
            "BY_INVESTMENT_OBJECT", "BY_ACCOUNTING_MEASUREMENT"
        ],
        "member_table_ids": [
            "portfolio_by_category", "portfolio_by_measurement"
        ],
        "conditional_logical_members": [{
            "member_id": "portfolio_summary",
            "classification_axis": "PORTFOLIO_SUMMARY",
            "activation": "NUMERIC_PREFIX_BEFORE_FIRST_CERTIFIED_AXIS",
            "required": False,
        }],
    }
    assert _certified_member_for_axis(
        target, "PORTFOLIO_SUMMARY", "portfolio_by_category"
    ) == "portfolio_summary"


def test_bundle_root_order_is_independent_of_physical_block_order() -> None:
    summary = SimpleNamespace(classification_axis="PORTFOLIO_SUMMARY", block_order=0)
    category = SimpleNamespace(classification_axis="BY_INVESTMENT_OBJECT", block_order=1)
    measurement = SimpleNamespace(
        classification_axis="BY_ACCOUNTING_MEASUREMENT", block_order=2
    )
    assert [row.classification_axis for row in sorted(
        [summary, category, measurement], key=_direct_bundle_order
    )] == [
        "BY_INVESTMENT_OBJECT", "PORTFOLIO_SUMMARY",
        "BY_ACCOUNTING_MEASUREMENT",
    ]


def test_registry_upgrade_is_idempotent_for_existing_data_home(tmp_path) -> None:
    registry = MetadataRegistry(tmp_path / "metadata.db")
    service = ResearchDefinitionService(registry)
    with registry.connect() as conn:
        conn.execute(
            """UPDATE family_members SET canonical_order=1,payload_json=?
               WHERE family_id='investment_portfolio'
                 AND member_id='portfolio_by_category'""",
            (json.dumps({"classification_axis": "BY_INVESTMENT_OBJECT"}),),
        )
        conn.execute(
            """DELETE FROM family_members WHERE family_id='investment_portfolio'
               AND member_id='portfolio_summary'"""
        )
    service = ResearchDefinitionService(registry)
    service = ResearchDefinitionService(registry)
    members = service.members("investment_portfolio")
    assert [(row["member_id"], row["canonical_order"]) for row in members] == [
        ("portfolio_summary", 1),
        ("portfolio_by_category", 2),
        ("portfolio_by_measurement", 3),
        ("portfolio_components", 4),
    ]


def test_numeric_parent_reconciles_with_dash_column() -> None:
    from spatial_table_capture import _numeric_parent_reconciles

    parent = SimpleNamespace(
        cells=[
            SimpleNamespace(column_ordinal=0, parsed_number=3258062.0),
            SimpleNamespace(column_ordinal=1, parsed_number=56.8),
            SimpleNamespace(column_ordinal=2, parsed_number=2645104.0),
            SimpleNamespace(column_ordinal=3, parsed_number=56.0),
        ]
    )
    children = [
        SimpleNamespace(
            cells=[
                SimpleNamespace(column_ordinal=0, parsed_number=2993899.0),
                SimpleNamespace(column_ordinal=1, parsed_number=52.2),
                SimpleNamespace(column_ordinal=2, parsed_number=2469121.0),
                SimpleNamespace(column_ordinal=3, parsed_number=52.3),
            ]
        ),
        SimpleNamespace(
            cells=[
                SimpleNamespace(column_ordinal=0, parsed_number=263158.0),
                SimpleNamespace(column_ordinal=1, parsed_number=4.6),
                SimpleNamespace(column_ordinal=2, parsed_number=175097.0),
                SimpleNamespace(column_ordinal=3, parsed_number=3.7),
            ]
        ),
        SimpleNamespace(
            cells=[
                SimpleNamespace(column_ordinal=0, parsed_number=1005.0),
                SimpleNamespace(column_ordinal=1, parsed_number=None),  # Dash / negligible percentage
                SimpleNamespace(column_ordinal=2, parsed_number=886.0),
                SimpleNamespace(column_ordinal=3, parsed_number=None),  # Dash / negligible percentage
            ]
        ),
    ]

    reconciles, checks = _numeric_parent_reconciles(parent, children)
    assert reconciles is True
    assert checks[0]["reported"] == 3258062.0
    assert checks[0]["sum_children"] == 3258062.0
    assert checks[2]["reported"] == 2645104.0
    assert checks[2]["sum_children"] == 2645104.0

