from __future__ import annotations

import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from merge_asset_picker_ui import (  # noqa: E402
    UNKNOWN_MEMBER_TABLE,
    _persist_picker_selection,
    base_member_table_id,
    capture_block_display,
    capture_filter_dimensions,
    capture_research_batch_ids,
    enrich_merge_filter_identity,
    filter_merge_records,
    merge_asset_label,
    merge_filter_options,
    merge_project_label,
    merge_selection_summary,
    normalize_merge_picker_state,
    reconcile_merge_selection,
)


ROWS = [
    {
        "capture_id": "CAP_A",
        "company": "中国平安",
        "document_year": "2024",
        "table_query": "债权投资",
        "display_name": "平安债权投资",
        "research_batch_ids": "RB_1,RB_SHARED",
    },
    {
        "capture_id": "CAP_B",
        "company": "中国平安",
        "document_year": "2023",
        "member_table_id": "other_debt_investment::BLOCK_123",
        "member_table_display": "其他债权投资",
        "research_batch_ids": "RB_2,RB_SHARED",
    },
    {
        "capture_id": "CAP_C",
        "company_id": "中国太保",
        "report_year": "2024",
        "member_table": "债权投资",
        "research_batch_id": "RB_3",
    },
]


def _ids(rows):
    return [row["capture_id"] for row in rows]


def test_filter_dimensions_use_registry_fields_with_deterministic_fallbacks():
    assert capture_filter_dimensions(ROWS[0]) == {
        "company": "中国平安",
        "year": "2024",
        "member_table": "债权投资",
    }
    assert base_member_table_id("other_debt_investment::BLOCK_123") == "other_debt_investment"
    assert capture_filter_dimensions({
        "member_table_id": "other_debt_investment::BLOCK_123",
    })["member_table"] == "other_debt_investment"
    assert capture_filter_dimensions({})["member_table"] == UNKNOWN_MEMBER_TABLE


def test_logical_asset_identity_collapses_blocks_and_uses_display_name():
    enriched = enrich_merge_filter_identity(
        {"capture_id": "CAP_X", "company": "旧公司", "table_query": "按资产类型"},
        {
            "company_id": "中国太保",
            "report_year": "2025",
            "member_table_id": "other_debt_investment::BLOCK_123",
        },
        {"other_debt_investment": "其他债权投资"},
    )
    assert capture_filter_dimensions(enriched) == {
        "company": "中国太保",
        "year": "2025",
        "member_table": "其他债权投资",
    }


def test_filter_options_and_single_dimension_filters_preserve_registry_order():
    assert merge_filter_options(ROWS) == {
        "companies": ["中国太保", "中国平安"],
        "years": ["2024", "2023"],
        "member_tables": ["债权投资", "其他债权投资"],
        "research_batch_ids": ["RB_1", "RB_2", "RB_3", "RB_SHARED"],
    }
    assert _ids(filter_merge_records(ROWS, companies={"中国平安"})) == ["CAP_A", "CAP_B"]
    assert _ids(filter_merge_records(ROWS, years={"2024"})) == ["CAP_A", "CAP_C"]
    assert _ids(filter_merge_records(ROWS, member_tables={"其他债权投资"})) == ["CAP_B"]
    assert _ids(filter_merge_records(ROWS, research_batch_ids={"RB_SHARED"})) == ["CAP_A", "CAP_B"]


def test_research_batch_ids_are_parsed_as_multi_value_memberships():
    assert capture_research_batch_ids(ROWS[0]) == ("RB_1", "RB_SHARED")
    assert capture_research_batch_ids({"research_batch_ids": ["RB_A", "RB_A", "RB_B"]}) == (
        "RB_A", "RB_B"
    )


def test_filters_can_be_combined_without_changing_identity():
    assert _ids(filter_merge_records(
        ROWS,
        companies={"中国平安"},
        years={"2024"},
        member_tables={"债权投资"},
    )) == ["CAP_A"]


def test_selection_reconciliation_retains_hidden_and_removes_invalid_ids():
    selected = reconcile_merge_selection(
        selected_ids={"CAP_A", "CAP_B", "STALE"},
        visible_ids={"CAP_A", "CAP_C"},
        chosen_visible_ids={"CAP_C", "OUT_OF_VIEW"},
        valid_ids={"CAP_A", "CAP_B", "CAP_C"},
    )
    assert selected == {"CAP_B", "CAP_C"}


def test_durable_picker_state_survives_unrelated_widget_rerun():
    options = merge_filter_options(ROWS)
    state = normalize_merge_picker_state(
        {
            "mode": "按公司",
            "companies": ["中国平安"],
            "selected_ids": ["CAP_A", "CAP_B"],
        },
        valid_ids={"CAP_A", "CAP_B", "CAP_C"},
        options=options,
    )

    # Conditional widget keys may be removed by Streamlit; durable state is not.
    rerun_state = normalize_merge_picker_state(
        state,
        valid_ids={"CAP_A", "CAP_B", "CAP_C"},
        options=options,
    )
    assert rerun_state["mode"] == "按公司"
    assert rerun_state["companies"] == ["中国平安"]
    assert rerun_state["selected_ids"] == ["CAP_A", "CAP_B"]


def test_selection_callback_persists_before_downstream_widget_rerun():
    session_state = {
        "picker_state": {"selected_ids": ["CAP_B"]},
        "picker_visible": ["CAP_A"],
    }
    _persist_picker_selection(
        session_state,
        "picker_state",
        "picker_selected_ids",
        "picker_visible",
        ["CAP_A", "CAP_C"],
        ["CAP_A", "CAP_B", "CAP_C"],
    )
    assert session_state["picker_state"]["selected_ids"] == ["CAP_A", "CAP_B"]
    assert session_state["picker_selected_ids"] == {"CAP_A", "CAP_B"}


def test_summary_and_labels_expose_the_three_filter_dimensions():
    summary = merge_selection_summary(ROWS)
    assert summary.capture_count == 3
    assert summary.company_count == 2
    assert summary.year_range == "2023-2024"
    assert summary.member_table_count == 2
    assert summary.research_batch_count == 4
    assert merge_asset_label(ROWS[0]) == "中国平安 | 2024 | 债权投资 | 平安债权投资 | CAP_A"


def test_multiblock_labels_preserve_chinese_titles_and_distinct_capture_ids():
    base = {
        "company": "中国人寿",
        "document_year": "2025",
        "member_table_display": "其他权益工具投资",
        "display_name": None,
        "table_query": "________________",
    }
    measurement = {
        **base,
        "capture_id": "ROOT__b2________________",
        "classification_axis": "MEASUREMENT_COMPOSITION",
    }
    listing = {
        **base,
        "capture_id": "ROOT__b3________________",
        "classification_axis": "LISTING_STATUS",
    }

    assert capture_block_display(measurement) == "按计量构成"
    assert capture_block_display(listing) == "按上市状态"
    measurement_label = merge_asset_label(measurement)
    listing_label = merge_asset_label(listing)
    assert "按计量构成" in measurement_label
    assert "按上市状态" in listing_label
    assert "None" not in measurement_label + listing_label
    assert measurement["capture_id"] in measurement_label
    assert listing["capture_id"] in listing_label
    assert measurement_label != listing_label


def test_multiblock_label_uses_readable_table_query_when_axis_is_not_projected():
    record = {
        "capture_id": "ROOT__b2________________",
        "company": "中国人寿",
        "document_year": "2025",
        "member_table_display": "其他权益工具投资",
        "display_name": None,
        "table_query": "按计量构成",
    }

    assert capture_block_display(record) == "按计量构成"
    label = merge_asset_label(record)
    assert "按计量构成" in label
    assert "ROOT__b2________________" in label
    assert "None" not in label


def test_merge_project_label_has_stable_missing_name_fallback():
    assert merge_project_label({"run_id": "MERGE_001", "display_name": None}) == "MERGE_001"
    assert merge_project_label({
        "run_id": "MERGE_001",
        "display_name": "国寿金融投资",
    }) == "国寿金融投资 · MERGE_001"
    assert "None" not in merge_project_label({"merge_id": "MERGE_002"})


def test_merge_page_uses_the_reusable_picker():
    source = (ROOT / "app.py").read_text(encoding="utf-8")
    merge_page = source[
        source.index('elif page == "合表"'):
        source.index('elif page == "报告与审计"')
    ]
    assert "render_merge_asset_picker(" in merge_page
    assert "selected_capture_ids" in merge_page
