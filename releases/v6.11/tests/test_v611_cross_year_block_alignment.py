"""Cross-Capture row identity must use semantic axes, not physical Block IDs."""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from table_merge import (  # noqa: E402
    apply_mapping,
    assign_conditional_source_keys,
    materialize_canonical,
)


def _row(
    year: str,
    block_id: str,
    value: float,
    *,
    axis: str = "ASSET_TYPE",
    capture_id: str | None = None,
) -> dict:
    capture_id = capture_id or f"CAP_{year}_{block_id}"
    return {
        "capture_run_id": capture_id,
        "source_key": f"BLOCK::{block_id}||UNIQUE||债券",
        "value": value,
        "normalized_item": "债券",
        "raw_item": "债券",
        "parent_section": "",
        "row_path": "债券",
        "row_type": "DETAIL",
        "row_level": 0,
        "row_order": 1,
        "column_ordinal": 0,
        "table_id": "太保金融投资",
        "table_family": "financial_investment",
        "member_table": "fvtpl_assets",
        "member_table_role": "NOTE_DETAIL",
        "source_table_title": "以公允价值计量且其变动计入当期损益的金融资产",
        "note_reference": "附注六-5",
        "source_pdf": f"中国太保{year}年报.pdf",
        "company": "中国太保",
        "report_year": year,
        "data_year": year,
        "statement_scope": "CONSOLIDATED",
        "restated_flag": False,
        "period_type": "ANNUAL",
        "currency_unit": "CNY_THOUSAND",
        "unit": "千元",
        "measure": "",
        "container_id": f"NOTE_{year}",
        "table_block_id": block_id,
        "block_order": 0,
        "classification_axis": axis,
        "block_role": "PRIMARY_TABLE",
        "block_terminal_type": "FINAL_TOTAL",
        "page": 100,
        "bbox": "{}",
    }


def _mapped(rows: list[dict]) -> pd.DataFrame:
    raw = pd.DataFrame(rows)
    mapping = raw[["source_key"]].drop_duplicates().assign(
        canonical_section="",
        canonical_item="债券",
        category="",
        mapping_status="UNMAPPED_PRESERVED",
        mapping_note="",
    )
    return apply_mapping(raw, mapping)


def test_resolved_axis_aligns_same_row_across_year_local_blocks() -> None:
    rows = [
        _row("2023", "BLOCK_2023", 167522146.0),
        _row("2024", "BLOCK_2024", 231355997.0),
        _row("2025", "BLOCK_2025", 240857834.0),
    ]
    source_keys = [
        assign_conditional_source_keys(pd.DataFrame([row]))["source_key"].iloc[0]
        for row in rows
    ]
    assert len(set(source_keys)) == 1

    mapped = _mapped(rows)
    assert mapped["canonical_key"].nunique() == 1
    resolved, wide, conflicts = materialize_canonical(mapped)
    value_columns = [column for column in wide if str(column).startswith("company=")]

    assert conflicts.empty
    assert len(resolved) == 3
    assert len(wide) == 1
    assert len(value_columns) == 3
    assert wide[value_columns].notna().sum().sum() == 3
    assert str(wide.iloc[0]["table_block_id"]).startswith("MULTIPLE[")


def test_different_semantic_axes_remain_separate() -> None:
    mapped = _mapped([
        _row("2025", "BLOCK_ASSET", 10.0, axis="ASSET_TYPE"),
        _row("2025", "BLOCK_MEASURE", 20.0, axis="MEASUREMENT_COMPOSITION"),
    ])
    resolved, wide, conflicts = materialize_canonical(mapped)

    assert conflicts.empty
    assert mapped["canonical_key"].nunique() == 2
    assert len(resolved) == 2
    assert len(wide) == 2


def test_unresolved_axes_remain_isolated_by_physical_block() -> None:
    rows = [
        _row("2024", "BLOCK_UNKNOWN_A", 10.0, axis="UNRESOLVED"),
        _row("2025", "BLOCK_UNKNOWN_B", 20.0, axis="UNRESOLVED"),
    ]
    source_keys = [
        assign_conditional_source_keys(pd.DataFrame([row]))["source_key"].iloc[0]
        for row in rows
    ]
    mapped = _mapped(rows)
    _, wide, conflicts = materialize_canonical(mapped)

    assert len(set(source_keys)) == 2
    assert mapped["canonical_key"].nunique() == 2
    assert len(wide) == 2
    assert conflicts.empty


def test_same_document_semantic_row_different_values_is_blocking_conflict() -> None:
    mapped = _mapped([
        _row("2025", "BLOCK_A", 10.0, capture_id="CAP_A"),
        _row("2025", "BLOCK_B", 20.0, capture_id="CAP_B"),
    ])
    _, wide, conflicts = materialize_canonical(mapped)

    assert wide.empty
    assert "VALUE_CONFLICT" in set(conflicts["conflict_status"])
    assert set(conflicts["conflict_severity"]) == {"BLOCKING"}

