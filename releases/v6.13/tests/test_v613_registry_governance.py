"""v6.13 Registry governance and direct-main-statement contracts.

These tests use an isolated DATA_HOME/SQLite database and a non-PDF byte file
only as immutable source identity.  They never invoke OCR, browser E2E, real
annual reports, Discovery jobs, or Capture jobs.
"""
from __future__ import annotations

import json
from pathlib import Path

import fitz
import tempfile

import pytest

from generic_structure_parser import GenericStructureParser
from hierarchical_child_discovery import ChildDiscoveryRepository
from metadata_registry import MetadataRegistry
from research_definition_registry import ResearchDefinitionService


def _bundle() -> dict:
    return {
        "family": {
            "family_id": "custom_cash_table",
            "display_name": "自定义现金流披露",
            "definition_version": "CUSTOM_CASH_TABLE_V1",
            "discovery_strategy": "DIRECT_NOTE_TABLE_FAMILY",
            "preferred_statement_types": ["NOTE_SECTION"],
            "preferred_scope": "CONSOLIDATED",
        },
        "members": [{
            "member_id": "custom_cash_detail",
            "display_name": "自定义现金流披露",
            "member_role": "DIRECT_DISCLOSURE_TABLE",
            "required": True,
            "canonical_order": 1,
            "aliases": ["现金流披露变体"],
            "row_signatures": ["现金流"],
            "column_signatures": ["本期"],
        }],
        "definition": {
            "definition_id": "CUSTOM_CASH_TABLE_V1",
            "display_name": "自定义现金流披露",
            "definition_version": "CUSTOM_CASH_TABLE_V1",
            "table_families": ["custom_cash_table"],
            "research_scope": {
                "core_members": ["custom_cash_detail"],
                "optional_members": [],
                "excluded_members": [],
            },
        },
    }


def test_builtin_main_statement_families_are_seeded_and_read_only(tmp_path: Path) -> None:
    service = ResearchDefinitionService(MetadataRegistry(tmp_path / "metadata.db"))
    families = {row["family_id"]: row for row in service.families()}
    assert {"financial_investment", "investment_portfolio", "consolidated_balance_sheet", "cash_flow_statement"}.issubset(families)
    assert families["consolidated_balance_sheet"]["discovery_strategy"] == "DIRECT_MAIN_STATEMENT_TABLE"
    assert families["cash_flow_statement"]["payload"]["preferred_statement_types"] == ["CASH_FLOW"]
    portfolio_contract = families["investment_portfolio"]["payload"][
        "portfolio_topology_contract"
    ]
    assert portfolio_contract["runtime_activation_status"] == "ACTIVE_FOR_INVESTMENT_PORTFOLIO_V2"
    assert portfolio_contract["resolver_implementation_status"] == "IMPLEMENTED_NODE_4_NATIVE_FIRST"
    portfolio_definition = service.definition("INVESTMENT_PORTFOLIO_V1")
    assert portfolio_definition["payload"]["research_scope"][
        "topology_runtime_activation_status"
    ] == "ACTIVE_FOR_INVESTMENT_PORTFOLIO_V2"
    portfolio_v2 = service.definition("INVESTMENT_PORTFOLIO_V2")
    assert portfolio_v2 is not None
    assert portfolio_v2["payload"]["family_strategy_overrides"] == {
        "investment_portfolio": "DIRECT_PORTFOLIO_TABLES"
    }
    assert "INVESTMENT_PORTFOLIO_V1" not in {
        row["definition_id"] for row in service.definitions()
    }
    assert service.definition("INVESTMENT_PORTFOLIO_V1")["status"] == "ACTIVE"
    with pytest.raises(PermissionError, match="内置 Family"):
        service.archive_family("cash_flow_statement")
    with pytest.raises(PermissionError, match="内置 Definition"):
        service.archive_definition("CONSOLIDATED_BALANCE_SHEET_V1")


def test_user_registry_draft_requires_validation_then_activates(tmp_path: Path) -> None:
    service = ResearchDefinitionService(MetadataRegistry(tmp_path / "metadata.db"))
    invalid = _bundle()
    invalid["definition"]["research_scope"]["core_members"] = ["missing_member"]
    draft = service.create_user_draft(invalid)
    assert draft["status"] == "DRAFT"
    assert draft["validation"]["valid"] is False
    with pytest.raises(ValueError, match="校验未通过"):
        service.activate_user_draft(draft["draft_id"])

    valid = service.create_user_draft(_bundle())
    report = service.validate_user_draft(valid["draft_id"])
    assert report["valid"] is True
    active = service.activate_user_draft(valid["draft_id"])
    assert active["status"] == "ACTIVE"
    assert service.definition("CUSTOM_CASH_TABLE_V1")["status"] == "ACTIVE"
    assert "custom_cash_table" in {row["family_id"] for row in service.families()}


def test_direct_main_statement_structure_keeps_stable_member_identity() -> None:
    candidate = {
        "member_table": "consolidated_balance_sheet_table",
        "member_display_name": "合并资产负债表",
        "statement_item": "合并资产负债表",
        "matched_title": "资产负债表",
        "certified_heading": "资产负债表",
        "candidate_note_pdf_page_index": 42,
        "confidence": 0.95,
        "direct_main_statement": True,
        "locator_method": "DIRECT_PRIMARY_STATEMENT_TITLE_AND_SIGNATURE",
        "evidence": {"row_signature_hits": 3},
    }
    occurrence = GenericStructureParser().parse(
        [candidate], strategy="DIRECT_MAIN_STATEMENT_TABLE",
        family_id="consolidated_balance_sheet", display_name="合并资产负债表",
    )[0]
    child = occurrence["child_rows"][0]
    assert child["member_table"] == "consolidated_balance_sheet_table"
    assert child["direct_main_statement"] is True
    assert child["note_target_candidates"][0]["pdf_page_index"] == 42


def test_direct_main_statement_certifies_through_existing_link_owner(tmp_path: Path) -> None:
    registry = MetadataRegistry(tmp_path / "metadata.db")
    repository = ChildDiscoveryRepository(registry)
    source = tmp_path / "source.pdf"
    source.write_bytes(b"immutable-test-source")
    anchor = {
        "occurrence_id": "OCC_DIRECT_MAIN", "pdf_id": str(source),
        "table_family": "consolidated_balance_sheet", "scope": "CONSOLIDATED",
        "statement_pdf_page_index": 7, "source_table_title": "合并资产负债表",
    }
    child = {
        "anchor_child_id": "ACHILD_DIRECT_MAIN", "canonical_concept_id": "consolidated_balance_sheet_table",
        "canonical_display_name": "合并资产负债表", "candidate_note_pdf_page_index": 7,
        "statement_scope": "CONSOLIDATED", "report_year": "2025", "data_year": "2025",
        "research_definition_id": "CONSOLIDATED_BALANCE_SHEET_V1",
        "definition_version": "CONSOLIDATED_BALANCE_SHEET_V1", "direct_main_statement": True,
        "direct_capture_title": "合并资产负债表",
        "inline_note_reference_evidence": {"direct_main_statement": True},
    }
    link = repository.certify_direct_main_statement(
        anchor, child,
        {"member_table_id": "consolidated_balance_sheet_table", "canonical_title": "合并资产负债表", "direct_main_statement": True},
    )
    target = repository.certified_target(link["certified_link_id"])
    assert target["status"] == "CERTIFIED_NOTE_TARGET"
    assert target["confirmed_note_pdf_page_index"] == 7
    assert target["capture_query_title"] == "合并资产负债表"
    assert target["segment_manifest_status"] == "DIRECT_MAIN_STATEMENT_SINGLE_SEGMENT"


def test_direct_portfolio_certifies_without_financial_note_retrieval(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    registry = MetadataRegistry(tmp_path / "metadata.db")
    repository = ChildDiscoveryRepository(registry)
    source = tmp_path / "portfolio.pdf"
    doc = fitz.open()
    page = doc.new_page(width=595, height=842)
    page.insert_text((280, 80), "2025年", fontname="china-s")
    page.insert_text((420, 80), "2024年", fontname="china-s")
    for x, text in zip((250, 320, 390, 460), ("金额", "占比", "金额", "占比")):
        page.insert_text((x, 100), text, fontname="china-s")
    for y, values in zip(
        (130, 150, 170),
        (("100", "40%", "80", "35%"),
         ("120", "45%", "90", "40%"),
         ("140", "50%", "100", "45%")),
    ):
        for x, value in zip((250, 320, 390, 460), values):
            page.insert_text((x, y), value)
    doc.save(source)
    doc.close()
    monkeypatch.setattr(
        "spatial_table_capture.build_certified_column_topology_from_pdf",
        lambda *args, **kwargs: {
            "period_signature": {
                "contract_version": 2,
                "period_labels": ["2025年", "2025年", "2024年", "2024年"],
                "period_kinds": ["ABSOLUTE_YEAR"] * 4,
                "year_labels": ["2025", "2025", "2024", "2024"],
            },
            "header_signature": {
                "contract_version": 2,
                "fingerprint": "test-fingerprint",
                "leaf_count": 4,
                "labels": ["金额", "占比", "金额", "占比"],
                "measure_kinds": ["AMOUNT", "PERCENTAGE", "AMOUNT", "PERCENTAGE"],
                "leaf_bboxes": [
                    {"x0": x, "y0": 80, "x1": x + 20, "y1": 100}
                    for x in (240, 310, 380, 450)
                ],
                "header_bbox": {"x0": 240, "y0": 60, "x1": 470, "y1": 100},
            },
            "amount_lane_signature": {
                "contract_version": 2,
                "lane_count": 4,
                "anchor_ratios": [0.42, 0.54, 0.66, 0.78],
                "source_column_ordinals": [0, 1, 2, 3],
            },
            "evidence": {
                "column_topology_contract_version": 2,
                "column_topology_source": "TEST_CERTIFIED_PHYSICAL_HEADER_AND_BODY_LANES",
                "header_y0": 60.0,
                "header_y1": 100.0,
                "data_y_min": 100.0,
            },
        },
    )
    anchor = {
        "occurrence_id": "OCC_DIRECT_PORTFOLIO",
        "pdf_id": str(source),
        "table_family": "investment_portfolio",
        "scope": "CONSOLIDATED",
        "statement_pdf_page_index": 1,
        "source_table_title": "投资组合情况",
    }
    child = {
        "anchor_child_id": "ACHILD_DIRECT_PORTFOLIO",
        "canonical_concept_id": "portfolio_by_category",
        "canonical_display_name": "投资组合（按投资品种）",
        "candidate_note_pdf_page_index": 1,
        "statement_scope": "CONSOLIDATED",
        "report_year": "2025",
        "data_year": "2025",
        "research_definition_id": "INVESTMENT_PORTFOLIO_V2",
        "definition_version": "INVESTMENT_PORTFOLIO_V2",
        "direct_portfolio_table": True,
        "direct_capture_title": "投资组合情况",
        "physical_asset_id": "PORTFOLIO_PHYSICAL_TEST",
        "logical_block_id": "PORTFOLIO_BLOCK_CATEGORY",
        "classification_axis": "BY_INVESTMENT_OBJECT",
        "physical_bbox": {"x0": 20, "y0": 40, "x1": 540, "y1": 220},
        "disclosure_topology": "DIRECT_COMPOUND_TABLE",
        "inline_note_reference_evidence": {
            "direct_portfolio_table": True,
            "physical_asset_id": "PORTFOLIO_PHYSICAL_TEST",
            "logical_block_id": "PORTFOLIO_BLOCK_CATEGORY",
            "classification_axis": "BY_INVESTMENT_OBJECT",
            "disclosure_topology": "DIRECT_COMPOUND_TABLE",
            "physical_bbox": {"x0": 20, "y0": 40, "x1": 540, "y1": 220},
            "period_headers": ["2025年", "2024年"],
        },
    }
    link = repository.certify_direct_portfolio_table(
        anchor,
        child,
        {
            "member_table_id": "portfolio_by_category",
            "member_table_ids": [
                "portfolio_by_category", "portfolio_by_measurement"
            ],
            "logical_block_ids": [
                "PORTFOLIO_BLOCK_CATEGORY", "PORTFOLIO_BLOCK_MEASUREMENT"
            ],
            "classification_axes": [
                "BY_INVESTMENT_OBJECT", "BY_ACCOUNTING_MEASUREMENT"
            ],
            "canonical_title": "投资组合（按投资品种）",
            "direct_portfolio_table": True,
            "physical_asset_id": "PORTFOLIO_PHYSICAL_TEST",
        },
    )
    target = repository.certified_target(link["certified_link_id"])
    assert link["relation_type"] == "DIRECT_PORTFOLIO_WHOLE_TABLE"
    assert target["logical_table_id"] == "PORTFOLIO_PHYSICAL_TEST"
    assert target["confirmed_note_pdf_page_index"] == 1
    assert target["segment_manifest_status"] == "CERTIFIED_SEGMENT_MANIFEST"
    assert target["member_table_ids"] == [
        "portfolio_by_category", "portfolio_by_measurement"
    ]
    assert target["logical_block_ids"] == [
        "PORTFOLIO_BLOCK_CATEGORY", "PORTFOLIO_BLOCK_MEASUREMENT"
    ]
    assert target["classification_axes"] == [
        "BY_INVESTMENT_OBJECT", "BY_ACCOUNTING_MEASUREMENT"
    ]
    assert target["certified_segments"][0]["header_signature"]["leaf_count"] == 4
    assert target["certified_segments"][0]["period_signature"]["contract_version"] == 2
    assert target["certified_segments"][0]["amount_lane_signature"]["lane_count"] == 4

    monkeypatch.setattr(
        "spatial_table_capture.build_certified_column_topology_from_pdf",
        lambda *args, **kwargs: {
            "period_signature": {
                "contract_version": 3,
                "period_labels": ["2025年", "2025年", "2024年", "2024年"],
                "period_kinds": ["ABSOLUTE_YEAR"] * 4,
                "year_labels": ["2025", "2025", "2024", "2024"],
                "lane_group_ids": [
                    "PERIOD_GROUP_1", "PERIOD_GROUP_1",
                    "PERIOD_GROUP_2", "PERIOD_GROUP_2",
                ],
                "column_groups": [
                    {
                        "period": period,
                        "period_anchor_bbox": {"x0": x, "y0": 60, "x1": x + 40, "y1": 80},
                        "period_group_bbox": {"x0": x - 40, "y0": 60, "x1": x + 100, "y1": 100},
                        "period_header_row_band": {"y0": 60, "y1": 80},
                        "child_header_row_band": {"y0": 80, "y1": 100},
                        "consumed_spans": [{"text": period}],
                        "column_group_id": f"PERIOD_GROUP_{index}",
                        "confidence": 1.0,
                        "evidence": {"mapping_mode": "MULTIROW_CONTIGUOUS_COLUMN_GROUP"},
                    }
                    for index, (period, x) in enumerate(
                        (("2025年", 250), ("2024年", 390)),
                        start=1,
                    )
                ],
            },
            "header_signature": {
                "contract_version": 3,
                "fingerprint": "test-fingerprint-v3",
                "leaf_count": 4,
                "labels": ["金额", "占比", "金额", "占比"],
                "measure_kinds": ["AMOUNT", "PERCENTAGE", "AMOUNT", "PERCENTAGE"],
                "leaf_bboxes": [
                    {"x0": x, "y0": 80, "x1": x + 20, "y1": 100}
                    for x in (240, 310, 380, 450)
                ],
                "header_bbox": {"x0": 240, "y0": 60, "x1": 470, "y1": 100},
            },
            "amount_lane_signature": {
                "contract_version": 3,
                "lane_count": 4,
                "anchor_ratios": [0.42, 0.54, 0.66, 0.78],
                "source_column_ordinals": [0, 1, 2, 3],
            },
            "evidence": {
                "column_topology_contract_version": 3,
                "column_topology_source": "TEST_CERTIFIED_PERIOD_GROUP_AND_BODY_LANES",
                "header_y0": 60.0,
                "header_y1": 100.0,
                "data_y_min": 100.0,
            },
        },
    )
    upgraded_link = repository.certify_direct_portfolio_table(
        anchor,
        child,
        {
            "member_table_id": "portfolio_by_category",
            "member_table_ids": [
                "portfolio_by_category", "portfolio_by_measurement"
            ],
            "logical_block_ids": [
                "PORTFOLIO_BLOCK_CATEGORY", "PORTFOLIO_BLOCK_MEASUREMENT"
            ],
            "classification_axes": [
                "BY_INVESTMENT_OBJECT", "BY_ACCOUNTING_MEASUREMENT"
            ],
            "canonical_title": "投资组合（按投资品种）",
            "direct_portfolio_table": True,
            "physical_asset_id": "PORTFOLIO_PHYSICAL_TEST",
        },
    )
    upgraded_target = repository.certified_target(upgraded_link["certified_link_id"])
    assert upgraded_link["certified_link_id"] != link["certified_link_id"]
    assert upgraded_target["certified_segments"][0]["period_signature"]["contract_version"] == 3
    with registry.connect() as conn:
        versions = [
            json.loads(row["period_signature_json"])["contract_version"]
            for row in conn.execute(
                """SELECT segment.period_signature_json
                   FROM certified_child_table_segments AS segment
                   JOIN certified_child_table_links AS link
                     ON link.certified_link_id=segment.certified_link_id
                   WHERE link.anchor_id=? AND link.logical_table_id=?
                   ORDER BY segment.certified_at""",
                ("OCC_DIRECT_PORTFOLIO", "PORTFOLIO_PHYSICAL_TEST"),
            ).fetchall()
        ]
        assert versions == [2, 3]
        run = conn.execute(
            "SELECT tiers_executed_json,tiers_skipped_json FROM child_discovery_runs WHERE anchor_child_id=?",
            ("ACHILD_DIRECT_PORTFOLIO",),
        ).fetchone()
    assert json.loads(run["tiers_executed_json"]) == ["DIRECT_PORTFOLIO_TABLE"]
    assert json.loads(run["tiers_skipped_json"]) == ["NOTE_RETRIEVAL_NOT_APPLICABLE"]


def test_template_stats_query_execution(tmp_path: Path) -> None:
    registry = MetadataRegistry(tmp_path / "metadata.db")
    service = ResearchDefinitionService(registry)
    stats = service.template_stats()
    assert isinstance(stats, list)
    assert len(stats) == 0

