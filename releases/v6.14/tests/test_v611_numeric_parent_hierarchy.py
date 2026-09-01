from __future__ import annotations

import json

from compound_note_engine import _semantic_graph
from spatial_table_capture import _infer_numeric_parent_hierarchy, resolve_pending_label
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
    assert set(child["parent_row_id"]) == {rows[0].source_row_id}
    assert set(child["source_row_id"]) == {rows[1].source_row_id}
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


def test_pending_label_resolver_has_one_structural_decision() -> None:
    assert resolve_pending_label(
        promoted_parent="债权类金融资产",
        explicit_section=False,
        indented_group=False,
        continuation=True,
    ) == "PROMOTED_PARENT"
    assert resolve_pending_label(
        promoted_parent=None,
        explicit_section=True,
        indented_group=False,
        continuation=True,
    ) == "SECTION"
    assert resolve_pending_label(
        promoted_parent=None,
        explicit_section=False,
        indented_group=False,
        continuation=True,
    ) == "CONTINUATION"
    assert resolve_pending_label(
        promoted_parent=None,
        explicit_section=False,
        indented_group=False,
        continuation=False,
    ) == "DETAIL"


def test_numeric_parent_writes_stable_source_edge() -> None:
    rows = [
        _row(1, "债权类金融资产", (300.0,), x0=100.0),
        _row(2, "－债券", (100.0,), x0=110.0),
        _row(3, "－其他债权", (200.0,), x0=110.0),
    ]
    from table_capture import TableCaptureResult, assign_source_row_identities

    result = TableCaptureResult(
        pdf_name="fixture.pdf", pdf_sha256="sha", table_query="投资组合",
        note_number=None, located_title="投资组合", start_page=10,
        end_page=10, pages=[10], unit="百万元", columns=[], rows=rows,
        warnings=[], stats={}, physical_table_id="PHYSICAL_1",
    )
    assign_source_row_identities(result)
    evidence = _infer_numeric_parent_hierarchy(rows)
    assert len(evidence) == 1
    assert rows[1].parent_row_id == rows[0].source_row_id
    assert rows[2].parent_row_id == rows[0].source_row_id
    assert rows[1].hierarchy_evidence["parent_source_row_id"] == rows[0].source_row_id


def test_numeric_parent_ideographic_space_indentation() -> None:
    """China Life style: same bbox.x0 across all rows, but child items start with U+3000."""
    from table_capture import TableCaptureResult, assign_source_row_identities

    rows = [
        _row(1, "固定到期日金融资产", (4138694.0, 72.95), x0=62.36),
        _row(2, "\u3000定期存款", (404131.0, 7.12), x0=62.36),
        _row(3, "\u3000债券", (2926986.0, 51.59), x0=62.36),
        _row(4, "\u3000债权型金融产品", (479962.0, 8.46), x0=62.36),
        _row(5, "\u3000其他固定到期日投资", (327615.0, 5.78), x0=62.36),
        _row(6, "权益类金融资产", (1098776.0, 19.37), x0=62.36),
        _row(7, "\u3000股票", (430200.0, 7.58), x0=62.36),
        _row(8, "\u3000基金", (206793.0, 3.65), x0=62.36),
        _row(9, "\u3000其他权益类投资", (461783.0, 8.14), x0=62.36),
        _row(10, "投资性房地产", (12753.0, 0.22), x0=62.36),
        _row(11, "现金及其他", (165542.0, 2.92), x0=62.36),
        _row(12, "联营企业和合营企业投资", (257606.0, 4.54), x0=62.36),
        _row(13, "合计", (5673371.0, 100.0), x0=62.36),
    ]
    result = TableCaptureResult(
        pdf_name="chinalife_2023.pdf", pdf_sha256="sha", table_query="投资组合情况",
        note_number=None, located_title="投资组合情况", start_page=21,
        end_page=21, pages=[21], unit="百万元", columns=[], rows=rows,
        warnings=[], stats={}, physical_table_id="PHYSICAL_1",
    )
    assign_source_row_identities(result)
    evidence = _infer_numeric_parent_hierarchy(rows)
    assert len(evidence) == 2  # 固定到期日金融资产 and 权益类金融资产

    # 固定到期日金融资产 children
    assert rows[0].row_level == 0
    for child_idx in (1, 2, 3, 4):
        assert rows[child_idx].row_level == 1
        assert rows[child_idx].parent_row_id == rows[0].source_row_id
        assert rows[child_idx].row_role == "BREAKDOWN_DETAIL"
        assert rows[child_idx].hierarchy_evidence["indent_source"] == "IDEOGRAPHIC_SPACE"

    # 权益类金融资产 children
    assert rows[5].row_level == 0
    for child_idx in (6, 7, 8):
        assert rows[child_idx].row_level == 1
        assert rows[child_idx].parent_row_id == rows[5].source_row_id
        assert rows[child_idx].row_role == "BREAKDOWN_DETAIL"
        assert rows[child_idx].hierarchy_evidence["indent_source"] == "IDEOGRAPHIC_SPACE"

    # Non-breakdown rows remain level 0
    for standalone_idx in (9, 10, 11, 12):
        assert rows[standalone_idx].row_level == 0
        assert rows[standalone_idx].parent_row_id is None

