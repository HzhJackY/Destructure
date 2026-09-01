from __future__ import annotations

import json
import tempfile
from pathlib import Path

import pytest

from final_data_review import review_final_data_columns
from capture_models import literal_capture_query_title
from hierarchical_child_discovery import (
    ChildDiscoveryRepository,
    FinancialNoteIndexService,
    HierarchicalChildTableDiscoveryService,
    StatementScopeSelection,
)
from metadata_registry import MetadataRegistry


def _services(tmp: str):
    registry = MetadataRegistry(Path(tmp) / "metadata.db")
    repo = ChildDiscoveryRepository(registry)
    index = FinancialNoteIndexService(repo)
    return registry, repo, index, HierarchicalChildTableDiscoveryService(repo, index)


@pytest.mark.parametrize(
    ("source_heading", "expected"),
    [
        ("11.  债权投资（仅适用2023年）", "债权投资（仅适用2023年）"),
        ("7.\uffa0债权投资", "\uffa0债权投资"),
        ("5.\uffa0 债权投资", "\uffa0 债权投资"),
        (
            "14 其他债权投资::SUPPLEMENTARY::8b62bb0dc69a",
            "其他债权投资",
        ),
    ],
)
def test_literal_capture_query_title_preserves_pdf_native_glyphs(
    source_heading,
    expected,
):
    result = literal_capture_query_title(source_heading)
    assert result == expected
    assert "\u1160" not in result


def test_scope_selection_supports_default_parent_and_two_independent_lanes():
    assert StatementScopeSelection.new("a.pdf").lanes() == ("CONSOLIDATED",)
    assert StatementScopeSelection.new("a.pdf", "PARENT_COMPANY").lanes() == ("PARENT_COMPANY",)
    assert StatementScopeSelection.new("a.pdf", "BOTH").lanes() == (
        "CONSOLIDATED", "PARENT_COMPANY"
    )


def test_schema_migration_is_idempotent_and_review_queue_requires_case():
    with tempfile.TemporaryDirectory() as tmp:
        registry, repo, _, _ = _services(tmp)
        MetadataRegistry(Path(tmp) / "metadata.db")
        anchor = {
            "occurrence_id": "A1", "scope": "CONSOLIDATED",
            "display_name": "金融投资", "report_year": "2023",
            "child_rows": [{"item": "债权投资", "values": [100], "note_reference": "12"}],
        }
        child = repo.create_anchor_children(anchor)[0]
        with pytest.raises(
            PermissionError,match="OPEN_UNRESOLVED_INVENTORY_CASE_REQUIRED",
        ):
            repo.enqueue_child_review(
                anchor_id="A1", anchor_child_id=child["anchor_child_id"],
                logical_asset_id="", source_pdf_id="a.pdf",
                statement_scope="CONSOLIDATED", candidate_ids=["C1", "C2"],
                resolution_case_id="MISSING_CASE",
                reason="NO_UNIQUE_HIGH_CONFIDENCE_CHILD_TABLE",
                evidence={"scores": [0.8, 0.79]},
            )
        assert repo.child_review_queue()==[]
        with registry.connect() as conn:
            assert conn.execute(
                "select count(*) n from child_mapping_review_queue"
            ).fetchone()["n"] == 0


def test_global_assignment_never_auto_certifies_ambiguous_candidate():
    with tempfile.TemporaryDirectory() as tmp:
        _, repo, _, service = _services(tmp)
        anchor = {
            "occurrence_id": "A1", "scope": "CONSOLIDATED",
            "display_name": "金融投资", "report_year": "2023",
            "child_rows": [{"item": "债权投资", "values": [100]}],
        }
        child = repo.create_anchor_children(anchor)[0]
        candidate = {
            "source_pdf_id": "a.pdf", "logical_asset_id": "",
        }
        links = [{
            "link_candidate_id": "L1", "candidate_id": "C1",
            "anchor_child_id": child["anchor_child_id"],
            "statement_scope": "CONSOLIDATED",
            "certification_score": 0.82, "is_preselected": False,
            "proposed_subtable_role": "PRIMARY_AMOUNT_DETAIL",
            "candidate": candidate,
        }]
        assignment = service.assign_global(
            "A1", "CONSOLIDATED", {child["anchor_child_id"]: links}
        )
        assert assignment["decisions"][0]["status"] == "AUTOMATION_REPAIR_REQUIRED"
        assert repo.child_review_queue()==[]


def test_implicit_total_only_table_is_not_applicable_to_last_token_check():
    review = review_final_data_columns({
        "columns": [{"raw_header_path": "2023", "data_year": "2023"}],
        "rows": [
            {"raw_item": None, "row_role": "IMPLICIT_TOTAL", "values": [100]},
            {"raw_item": None, "row_type": "DERIVED_TOTAL", "values": [100]},
        ],
    })
    check = review["last_column_check"]
    assert check["status"] == "NOT_APPLICABLE"
    assert check["row_count"] == 0
    assert check["excluded_derived_rows"] == 2
    assert "LAST_COLUMN_MAPPING_UNCERTAIN" not in {
        item["reason_code"] for item in review["issues"]
    }


@pytest.mark.skipif(
    not Path(r"C:\dev\AXA_research\docu\中国平安2023年报.pdf").exists(),
    reason="本地真实夹具不可用",
)
def test_real_pingan_2023_financial_note_index_is_formal_and_cached():
    with tempfile.TemporaryDirectory() as tmp:
        _, _, index, _ = _services(tmp)
        pdf = Path(r"C:\dev\AXA_research\docu\中国平安2023年报.pdf")
        first = index.build(pdf)
        second = index.build(pdf)
        assert first["notes_start_page"] == 158
        assert first["heading_count"] > 100
        assert second["cache_hit"] is True


@pytest.mark.skipif(
    not Path(r"C:\dev\AXA_research\docu\中国平安2023年报.pdf").exists(),
    reason="本地真实夹具不可用",
)
def test_real_pingan_explicit_note_reference_stops_at_tier_one():
    with tempfile.TemporaryDirectory() as tmp:
        _, repo, index, service = _services(tmp)
        pdf = Path(r"C:\dev\AXA_research\docu\中国平安2023年报.pdf")
        anchor = {
            "occurrence_id": "A1", "scope": "CONSOLIDATED",
            "display_name": "金融投资", "report_year": "2023",
            "child_rows": [{
                "item": "债权投资", "values": [313148],
                "note_reference_normalized": "附注八-10",
            }],
        }
        child = repo.create_anchor_children(anchor)[0]
        result = service.discover(
            pdf, anchor, child,
            {"canonical_title": "债权投资", "member_table_id": "债权投资"},
            "CONSOLIDATED",
        )
        assert result["run"]["tiers_executed"] == ["TIER1"]
        assert result["run"]["tiers_skipped"] == ["TIER2", "TIER3"]
        assert len(result["candidates"]) == 1
        assert result["candidates"][0]["start_page"] == 221
        enriched = service.enrich_top_k(pdf, child, result["candidates"])
        second = service.discover(
            pdf, anchor, child,
            {"canonical_title": "债权投资", "member_table_id": "债权投资"},
            "CONSOLIDATED",
        )
        enriched_second = service.enrich_top_k(pdf, child, second["candidates"])
        assert second["run"]["metrics"]["discovery_cache_hit"] is True
        assert enriched and enriched_second[0]["enrichment_cache_hit"] is True


@pytest.mark.skipif(
    not Path(r"C:\dev\AXA_research\docu\新华保险2023年报.pdf").exists(),
    reason="本地真实夹具不可用",
)
def test_real_xinhua_2023_index_contains_page_109_target_region():
    with tempfile.TemporaryDirectory() as tmp:
        _, _, index, _ = _services(tmp)
        pdf = Path(r"C:\dev\AXA_research\docu\新华保险2023年报.pdf")
        built = index.build(pdf)
        pages = {row["start_page"] for row in index.headings(built["index_id"])}
        assert built["notes_start_page"] <= 109
        assert 109 in pages


@pytest.mark.skipif(
    not Path(r"C:\dev\AXA_research\docu\新华保险2024年报.pdf").exists(),
    reason="本地真实夹具不可用",
)
def test_real_xinhua_2024_index_pairs_aligned_ordinal_and_title_lines():
    with tempfile.TemporaryDirectory() as tmp:
        _, _, index, _ = _services(tmp)
        pdf = Path(r"C:\dev\AXA_research\docu\新华保险2024年报.pdf")
        built = index.build(pdf)
        matches = [
            row for row in index.headings(built["index_id"])
            if row["start_page"] == 193
            and row.get("note_reference") == "12"
            and "债权投资" in row["raw_heading"]
        ]
        assert len(matches) == 1
        bbox = json.loads(matches[0]["heading_bbox_json"])
        assert bbox[3] - bbox[1] < 30
