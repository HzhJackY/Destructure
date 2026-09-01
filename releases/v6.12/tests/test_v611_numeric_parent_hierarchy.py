from __future__ import annotations

import json

from compound_note_engine import _semantic_graph
from spatial_table_capture import _infer_numeric_parent_hierarchy
from table_capture import (
    TableCaptureResult,
    TableCell,
    TableColumn,
    TableRow,
    capture_to_long_df,
)


def _row(
    order: int,
    label: str,
    values: tuple[float, ...],
    *,
    x0: float,
    page: int = 10,
    block_id: str = "segment-1",
) -> TableRow:
    return TableRow(
        row_order=order,
        page=page,
        block_id=block_id,
        source_method="spatial_roi+column_anchors",
        raw_item=label,
        normalized_item=label,
        canonical_item=None,
        mapping_status="UNMAPPED",
        row_type="DETAIL",
        row_level=0,
        parent_section=None,
        cells=[
            TableCell(
                column_ordinal=ordinal,
                source_column_index=ordinal + 1,
                raw=str(value),
                parsed_number=value,
                unit_original="千元",
                value_yuan=value * 1_000,
            )
            for ordinal, value in enumerate(values)
        ],
        header_source_page=None,
        row_role="DETAIL",
        row_item_raw=label,
        row_item_normalized=label,
        bbox={"x0": x0, "y0": float(order * 12), "x1": 500.0, "y1": float(order * 12 + 10)},
    )


def test_numeric_parent_hierarchy_survives_semantic_graph_and_long_lineage() -> None:
    rows = [
        _row(1, "债券", (300.0, 280.0), x0=126.98),
        _row(2, "金融债", (100.0, 90.0), x0=136.94),
        _row(3, "企业债", (200.0, 190.0), x0=136.94),
        _row(4, "股票", (50.0, 40.0), x0=126.98),
    ]
    original_parent_bbox = dict(rows[0].bbox or {})

    evidence = _infer_numeric_parent_hierarchy(rows)

    assert len(evidence) == 1
    assert evidence[0]["parent_label"] == "债券"
    assert evidence[0]["child_row_orders"] == [2, 3]
    assert rows[0].raw_item == "债券"
    assert rows[0].normalized_item == "债券"
    assert rows[0].bbox == original_parent_bbox
    assert [(row.parent_section, row.row_level) for row in rows[1:3]] == [
        ("债券", 1),
        ("债券", 1),
    ]
    assert rows[3].parent_section is None

    graph = _semantic_graph(rows)
    parent_relations = [
        relation for relation in graph["relations"]
        if relation["type"] == "PARENT_OF"
    ]
    assert [(item["parent"], item["child"]) for item in parent_relations] == [
        ("债券", "金融债"),
        ("债券", "企业债"),
    ]

    result = TableCaptureResult(
        pdf_name="fixture-2024.pdf",
        pdf_sha256="abc123",
        table_query="交易性金融资产",
        note_number="5",
        located_title="5. 交易性金融资产",
        start_page=10,
        end_page=10,
        pages=[10],
        unit="千元",
        columns=[
            TableColumn(0, 1, "2024年", "2024", None, False, "2024年"),
            TableColumn(1, 2, "2023年", "2023", None, False, "2023年"),
        ],
        rows=rows,
        warnings=[],
        stats={},
    )
    long_df = capture_to_long_df(result)
    child = long_df[long_df["raw_item"] == "金融债"]
    assert set(child["parent_section"]) == {"债券"}
    assert set(child["parent_row_id"]) == {"abc123:交易性金融资产:1"}
    assert all(json.loads(value)["x0"] == 136.94 for value in child["bbox"])


def test_numeric_parent_requires_multiple_children_and_full_reconciliation() -> None:
    mismatched = [
        _row(1, "债券", (304.0, 280.0), x0=100.0),
        _row(2, "金融债", (100.0, 90.0), x0=110.0),
        _row(3, "企业债", (200.0, 190.0), x0=110.0),
    ]
    single_child = [
        _row(1, "债券", (100.0,), x0=100.0),
        _row(2, "金融债", (100.0,), x0=110.0),
    ]

    assert _infer_numeric_parent_hierarchy(mismatched) == []
    assert all(row.parent_section is None for row in mismatched)
    assert _infer_numeric_parent_hierarchy(single_child) == []
    assert all(row.parent_section is None for row in single_child)


def test_numeric_parent_does_not_cross_page_or_physical_block() -> None:
    rows = [
        _row(1, "债券", (300.0,), x0=100.0),
        _row(2, "金融债", (100.0,), x0=110.0),
        _row(3, "企业债", (200.0,), x0=110.0, block_id="segment-2"),
    ]

    assert _infer_numeric_parent_hierarchy(rows) == []
    assert all(row.parent_section is None for row in rows)
