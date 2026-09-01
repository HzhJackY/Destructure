from __future__ import annotations

import pandas as pd

from components.capture_inspection_panel import _certified_row_structure_frame
from table_merge import assign_semantic_row_keys


def _row(
    *,
    capture: str,
    source_id: str,
    label: str,
    order: int,
    parent_id: str | None = None,
    year: str = "2025",
    parent_section: str | None = None,
    row_level: int = 0,
    row_type: str = "DETAIL",
) -> dict[str, object]:
    return {
        "capture_run_id": capture,
        "source_row_id": source_id,
        "parent_row_id": parent_id,
        "row_order": order,
        "raw_item": label,
        "normalized_item": label,
        "row_role": "BREAKDOWN_DETAIL" if parent_id else "DETAIL",
        "parent_section": parent_section,
        "row_level": row_level,
        "row_type": row_type,
        "table_family": "investment_portfolio",
        "member_table": "portfolio_by_category",
        "member_table_role": "DIRECT_DISCLOSURE_TABLE",
        "classification_axis": "BY_INVESTMENT_OBJECT",
        "table_block_id": "BLOCK",
        "report_year": year,
        "value": 1.0,
    }


def test_same_economic_row_across_years_ignores_physical_source_id() -> None:
    rows = pd.DataFrame([
        _row(capture="CAP_2024", source_id="ROW_PDF_2024", label="债券", order=1, year="2024"),
        _row(capture="CAP_2025", source_id="ROW_PDF_2025", label="债券", order=1, year="2025"),
    ])
    keyed = assign_semantic_row_keys(rows)
    assert keyed["source_row_id"].nunique() == 2
    assert keyed["semantic_row_key"].nunique() == 1


def test_same_name_under_different_certified_parents_stays_distinct() -> None:
    rows = pd.DataFrame([
        _row(capture="CAP", source_id="PARENT_A", label="固定到期日金融资产", order=1),
        _row(capture="CAP", source_id="CHILD_A", parent_id="PARENT_A", label="其他", order=2),
        _row(capture="CAP", source_id="PARENT_B", label="权益类金融资产", order=3),
        _row(capture="CAP", source_id="CHILD_B", parent_id="PARENT_B", label="其他", order=4),
    ])
    keyed = assign_semantic_row_keys(rows)
    children = keyed[keyed["source_row_id"].isin(["CHILD_A", "CHILD_B"])]
    assert children["semantic_row_key"].nunique() == 2
    assert set(children["semantic_parent_path"]) == {
        "固定到期日金融资产", "权益类金融资产",
    }


def test_same_name_same_parent_uses_local_occurrence_only_when_needed() -> None:
    rows = pd.DataFrame([
        _row(capture="CAP", source_id="PARENT", label="投资资产", order=1),
        _row(capture="CAP", source_id="CHILD_1", parent_id="PARENT", label="其他", order=2),
        _row(capture="CAP", source_id="CHILD_2", parent_id="PARENT", label="其他", order=3),
    ])
    keyed = assign_semantic_row_keys(rows)
    children = keyed[keyed["source_row_id"].str.startswith("CHILD")]
    assert children["semantic_row_key"].nunique() == 2
    assert set(children["semantic_occurrence"]) == {1, 2}
    assert all("||OCC::" in key for key in children["semantic_row_key"])


def test_ui_and_merge_consume_the_same_certified_parent_graph() -> None:
    rows = [
        _row(capture="CAP", source_id="PARENT", label="固定到期日金融资产", order=1),
        _row(
            capture="CAP", source_id="CHILD", parent_id="PARENT",
            label="定期存款", order=2,
            parent_section="错误旧父项", row_level=9, row_type="TOTAL",
        ),
    ]
    ui = _certified_row_structure_frame(rows)
    merged = assign_semantic_row_keys(pd.DataFrame(rows))
    ui_child = ui[ui["source_row_id"] == "CHILD"].iloc[0]
    merge_child = merged[merged["source_row_id"] == "CHILD"].iloc[0]
    assert ui_child["hierarchy_path"] == "固定到期日金融资产 / 定期存款"
    assert merge_child["hierarchy_path"] == ui_child["hierarchy_path"]
    assert merge_child["semantic_parent_path"] == "固定到期日金融资产"
    assert "错误旧父项" not in merge_child["semantic_row_key"]
    assert "TOTAL" not in merge_child["semantic_row_key"]


def test_unresolved_certified_parent_isolated_by_capture() -> None:
    rows = pd.DataFrame([
        _row(
            capture="CAP_A", source_id="ROW_A", parent_id="MISSING",
            label="定期存款", order=1,
        ),
        _row(
            capture="CAP_B", source_id="ROW_B", parent_id="MISSING",
            label="定期存款", order=1,
        ),
    ])
    keyed = assign_semantic_row_keys(rows)
    assert set(keyed["semantic_identity_status"]) == {"PARENT_ROW_ID_UNRESOLVED"}
    assert keyed["semantic_row_key"].nunique() == 2
    assert all("UNRESOLVED_SOURCE" in key for key in keyed["semantic_row_key"])
