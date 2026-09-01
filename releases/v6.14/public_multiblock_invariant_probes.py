"""Synthetic, redistributable invariant probes for compound note table blocks.

These probes deliberately contain no filing, Golden, production DATA_HOME, or
browser dependency.  They are the executable public source for BUG-010–012.
"""
from __future__ import annotations

import pandas as pd

from compound_note_engine import materialize_block_result, segment_table_blocks
from spatial_table_capture import _primary_table_end_y
from table_capture import TableCaptureResult, TableCell, TableColumn, TableRow, capture_to_long_df
from table_merge import materialize_canonical


BLOCK_FIELDS = {
    "container_id", "table_block_id", "block_order", "classification_axis",
    "block_role", "block_terminal_type",
}


def _cells(*values: float) -> list[TableCell]:
    return [
        TableCell(
            column_ordinal=index, source_column_index=index + 1,
            raw=f"{value:,.0f}", parsed_number=value, unit_original="百万元",
            value_yuan=value * 1_000_000,
        )
        for index, value in enumerate(values)
    ]


def _row(
    order: int, label: str | None, *values: float,
    row_type: str = "DETAIL", parent_section: str | None = None,
) -> TableRow:
    normalized = str(label or "").replace("：", "").strip()
    return TableRow(
        row_order=order, page=1, block_id="synthetic_p1", source_method="SYNTHETIC",
        raw_item=label, normalized_item=normalized, canonical_item=None,
        mapping_status="UNMAPPED", row_type=row_type, row_level=1 if parent_section else 0,
        parent_section=parent_section, cells=_cells(*values), header_source_page=None,
        row_role=row_type, row_item_raw=label, row_item_normalized=normalized or None,
        label_derivation="EXPLICIT_TEXT" if label else "NONE",
        derivation_method="ARITHMETIC_RECONCILIATION" if row_type == "IMPLICIT_TOTAL" else None,
        derivation_evidence={"status": "RECONCILED_FROM_LISTING_ROWS"} if row_type == "IMPLICIT_TOTAL" else None,
        bbox={"x0": 50, "y0": order * 20, "x1": 550, "y1": order * 20 + 12},
    )


def _result() -> TableCaptureResult:
    rows = [
        _row(1, "债券", row_type="SECTION_HEADER"),
        _row(2, "政府债", 100, 90, parent_section="债券"),
        _row(3, "金融债", 20, 10, parent_section="债券"),
        _row(4, "合计", 120, 100, row_type="TOTAL"),
        _row(5, "其中：", row_type="SECTION_HEADER"),
        _row(6, "－摊余成本", 110, 92, parent_section="其中"),
        _row(7, "－累计公允价值变动", 10, 8, parent_section="其中"),
        _row(8, "上市", 40, 30), _row(9, "非上市", 80, 70),
        _row(10, None, 120, 100, row_type="IMPLICIT_TOTAL"),
    ]
    return TableCaptureResult(
        pdf_name="synthetic.pdf", pdf_sha256="synthetic", table_query="其他债权投资",
        note_number="1", located_title="1. 其他债权投资", start_page=1, end_page=1,
        pages=[1], unit="百万元",
        columns=[
            TableColumn(0, 1, "2025", "2025", "CONSOLIDATED", False, "2025"),
            TableColumn(1, 2, "2024", "2024", "CONSOLIDATED", False, "2024"),
        ],
        rows=rows, warnings=[], stats={"boundary_confidence": "HIGH"},
        document_context={"statement_scope": "CONSOLIDATED", "currency": "CNY"},
    )


def assert_first_total_does_not_end_table() -> None:
    def line(y0: float, text: str, *numbers: str) -> dict:
        return {
            "y0": y0, "y1": y0 + 10, "text": text,
            "words": [{"text": item} for item in (numbers or (text,))],
        }

    end_y = _primary_table_end_y([
        line(10, "政府债 100 90", "100", "90"),
        line(30, "合计 120 100", "120", "100"),
        line(50, "其中："), line(70, "－摊余成本 110 92", "110", "92"),
        line(90, "上市 40 30", "40", "30"), line(110, "非上市 80 70", "80", "70"),
        line(130, "120 100", "120", "100"),
    ], header_y1=0)
    assert end_y is None or end_y >= 120
    assert end_y != 40


def assert_ordered_classification_axes() -> None:
    container, blocks = segment_table_blocks(_result())
    assert container.container_id
    assert [block.classification_axis for block in blocks] == [
        "ASSET_TYPE", "MEASUREMENT_COMPOSITION", "LISTING_STATUS",
    ]
    assert [block.block_order for block in blocks] == [0, 1, 2]
    assert [block.block_terminal_type for block in blocks] == ["LOCAL_TOTAL", "NONE", "FINAL_TOTAL"]


def assert_block_fields_survive_capture_long() -> None:
    result = _result()
    container, blocks = segment_table_blocks(result)
    frames = []
    for block in blocks:
        child = materialize_block_result(result, block)
        assert BLOCK_FIELDS.issubset(child.to_dict()["rows"][0])
        frame = capture_to_long_df(child)
        assert BLOCK_FIELDS.issubset(frame.columns)
        frames.append(frame)
    combined = pd.concat(frames, ignore_index=True)
    assert set(combined["container_id"]) == {container.container_id}
    assert set(combined["classification_axis"]) == {
        "ASSET_TYPE", "MEASUREMENT_COMPOSITION", "LISTING_STATUS",
    }


def assert_block_fields_survive_canonical_materialization() -> None:
    rows = []
    for order, axis in enumerate(["ASSET_TYPE", "MEASUREMENT_COMPOSITION", "LISTING_STATUS"]):
        rows.append({
            "value": float(order + 1), "table_id": "OTHER_DEBT", "table_family": "FINANCIAL_INVESTMENT",
            "member_table": "其他债权投资", "member_table_role": "COMPONENT", "source_table_title": "其他债权投资",
            "row_path": f"{axis}/row", "canonical_key": f"OTHER_DEBT::{axis}", "canonical_section": "其他债权投资",
            "canonical_item": axis, "company": "SYNTHETIC", "report_year": "2025", "data_year": "2025",
            "statement_scope": "CONSOLIDATED", "restated_flag": False, "period_type": "ANNUAL",
            "currency_unit": "CNY_MILLION", "unit": "百万元", "measure": "", "mapping_status": "EXACT",
            "capture_run_id": "SYNTHETIC", "source_pdf": "synthetic.pdf", "page": 1, "bbox": "{}",
            "raw_item": axis, "container_id": "NOTE_1", "table_block_id": f"BLOCK_{order}",
            "block_order": order, "classification_axis": axis,
            "block_role": "PRIMARY_TABLE" if order == 0 else "SECONDARY_TABLE",
            "block_terminal_type": "LOCAL_TOTAL" if order == 0 else "FINAL_TOTAL" if order == 2 else "NONE",
        })
    resolved, _, conflicts = materialize_canonical(pd.DataFrame(rows))
    assert conflicts.empty
    assert BLOCK_FIELDS.issubset(resolved.columns)
    assert resolved["table_block_id"].nunique() == 3
