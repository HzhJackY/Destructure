from __future__ import annotations

import copy
import runpy
from pathlib import Path

import pandas as pd
import pytest

from compound_note_engine import materialize_block_result, segment_table_blocks
from metadata_registry import MetadataRegistry
from spatial_table_capture import _primary_table_end_y
from table_capture import (
    TableCaptureResult,
    TableCell,
    TableColumn,
    TableRow,
    capture_named_table,
    capture_to_long_df,
)
from table_merge import (
    apply_mapping,
    assign_conditional_source_keys,
    materialize_canonical,
)


BLOCK_FIELDS = {
    "container_id",
    "table_block_id",
    "block_order",
    "classification_axis",
    "block_role",
    "block_terminal_type",
}


def _line(y0: float, text: str, *numeric_tokens: str) -> dict:
    words = [{"text": token} for token in numeric_tokens]
    if not words:
        words = [{"text": text}]
    return {
        "y0": y0,
        "y1": y0 + 10,
        "text": text,
        "words": words,
    }


def _cells(*values: float) -> list[TableCell]:
    return [
        TableCell(
            column_ordinal=index,
            source_column_index=index + 1,
            raw=f"{value:,.0f}",
            parsed_number=value,
            unit_original="百万元",
            value_yuan=value * 1_000_000,
        )
        for index, value in enumerate(values)
    ]


def _row(
    order: int,
    label: str | None,
    *values: float,
    row_type: str = "DETAIL",
    parent_section: str | None = None,
) -> TableRow:
    normalized = str(label or "").replace("：", "").strip()
    return TableRow(
        row_order=order,
        page=263,
        block_id="spatial_p263",
        source_method="TEST",
        raw_item=label,
        normalized_item=normalized,
        canonical_item=None,
        mapping_status="UNMAPPED",
        row_type=row_type,
        row_level=1 if parent_section else 0,
        parent_section=parent_section,
        cells=_cells(*values),
        header_source_page=None,
        row_role=row_type,
        row_item_raw=label,
        row_item_normalized=normalized or None,
        label_derivation="EXPLICIT_TEXT" if label else "NONE",
        derivation_method=("ARITHMETIC_RECONCILIATION" if row_type == "IMPLICIT_TOTAL" else None),
        derivation_evidence=(
            {"status": "RECONCILED_FROM_LISTING_ROWS"}
            if row_type == "IMPLICIT_TOTAL"
            else None
        ),
        bbox={"x0": 50, "y0": order * 20, "x1": 550, "y1": order * 20 + 12},
    )


def _multiblock_result() -> TableCaptureResult:
    rows = [
        _row(1, "债券", row_type="SECTION_HEADER"),
        _row(2, "政府债", 2_620_241, 2_493_010, parent_section="债券"),
        _row(3, "金融债", 362_548, 410_742, parent_section="债券"),
        _row(4, "企业债", 83_453, 95_586, parent_section="债券"),
        _row(5, "债权计划", 89_704, 102_884),
        _row(6, "理财产品投资", 75_489, 84_715),
        _row(7, "合计", 3_231_435, 3_186_937, row_type="TOTAL"),
        _row(8, "其中：", row_type="SECTION_HEADER"),
        _row(9, "－摊余成本", 2_801_516, 2_591_775, parent_section="其中"),
        _row(10, "－累计公允价值变动", 429_919, 595_162, parent_section="其中"),
        _row(11, "上市", 722_809, 398_075),
        _row(12, "非上市", 2_508_626, 2_788_862),
        _row(
            13,
            None,
            3_231_435,
            3_186_937,
            row_type="IMPLICIT_TOTAL",
        ),
    ]
    return TableCaptureResult(
        pdf_name="中国平安2025年报.pdf",
        pdf_sha256="sha256",
        table_query="其他债权投资",
        note_number="11",
        located_title="11. 其他债权投资",
        start_page=263,
        end_page=263,
        pages=[263],
        unit="百万元",
        columns=[
            TableColumn(0, 1, "2025", "2025", "CONSOLIDATED", False, "2025"),
            TableColumn(1, 2, "2024", "2024", "CONSOLIDATED", False, "2024"),
        ],
        rows=rows,
        warnings=[],
        stats={
            "source_pdf_path": "中国平安2025年报.pdf",
            "boundary_reason": "next_note_12",
            "boundary_confidence": "HIGH",
            "boundary_evidence": {"method": "NEXT_NOTE_ORDINAL"},
        },
        document_context={"statement_scope": "CONSOLIDATED", "currency": "CNY"},
    )


def test_split_label_numeric_rows_do_not_turn_local_total_into_hard_end() -> None:
    lines = [
        _line(10, "政府债 2,620,241 2,493,010", "2,620,241", "2,493,010"),
        _line(30, "合计 3,231,435 3,186,937", "3,231,435", "3,186,937"),
        _line(50, "其中："),
        _line(70, "－摊余成本 2,801,516 2,591,775", "2,801,516", "2,591,775"),
        _line(90, "－累计公允价值变动 429,919 595,162", "429,919", "595,162"),
        _line(110, "上市 722,809 398,075", "722,809", "398,075"),
        _line(130, "非上市 2,508,626 2,788,862", "2,508,626", "2,788,862"),
        _line(150, "3,231,435 3,186,937", "3,231,435", "3,186,937"),
        _line(170, "这是表后附注叙述，不属于任何具有两个对齐年度金额列的经济项目。"),
    ]

    candidate_end = _primary_table_end_y(lines, header_y1=0)

    assert candidate_end is None or candidate_end >= 160
    assert candidate_end != 40


def test_axis_state_machine_builds_three_ordered_blocks() -> None:
    result = _multiblock_result()

    container, blocks = segment_table_blocks(result)

    assert [block.classification_axis for block in blocks] == [
        "ASSET_TYPE",
        "MEASUREMENT_COMPOSITION",
        "LISTING_STATUS",
    ]
    assert [block.block_order for block in blocks] == [0, 1, 2]
    assert [block.block_terminal_type for block in blocks] == [
        "LOCAL_TOTAL",
        "NONE",
        "FINAL_TOTAL",
    ]
    assert [row.raw_item for row in blocks[0].rows][-1] == "合计"
    assert [row.raw_item for row in blocks[1].rows] == [
        "其中：",
        "－摊余成本",
        "－累计公允价值变动",
    ]
    assert [row.raw_item for row in blocks[2].rows] == ["上市", "非上市", None]
    for block in blocks:
        for row in block.rows:
            assert row.container_id == container.container_id
            assert row.table_block_id == block.block_id
            assert row.block_order == block.block_order
            assert row.classification_axis == block.classification_axis
            assert row.block_role == block.role
            assert row.block_terminal_type == block.block_terminal_type


def test_block_fields_survive_json_and_canonical_long() -> None:
    result = _multiblock_result()
    container, blocks = segment_table_blocks(result)

    frames = []
    for block in blocks:
        child = materialize_block_result(result, block)
        row_json = child.to_dict()["rows"][0]
        assert BLOCK_FIELDS.issubset(row_json)
        frame = capture_to_long_df(child)
        assert BLOCK_FIELDS.issubset(frame.columns)
        frames.append(frame)

    combined = pd.concat(frames, ignore_index=True)
    assert set(combined["container_id"]) == {container.container_id}
    assert set(combined["classification_axis"]) == {
        "ASSET_TYPE",
        "MEASUREMENT_COMPOSITION",
        "LISTING_STATUS",
    }
    assert combined["table_block_id"].nunique() == 3


def test_canonical_materializer_preserves_block_dimensions() -> None:
    rows = []
    for order, axis in enumerate(
        ["ASSET_TYPE", "MEASUREMENT_COMPOSITION", "LISTING_STATUS"]
    ):
        rows.append(
            {
                "value": float(order + 1),
                "table_id": "OTHER_DEBT",
                "table_family": "FINANCIAL_INVESTMENT",
                "member_table": "其他债权投资",
                "member_table_role": "COMPONENT",
                "source_table_title": "其他债权投资",
                "row_path": f"{axis}/row",
                "canonical_key": f"OTHER_DEBT::{axis}",
                "canonical_section": "其他债权投资",
                "canonical_item": axis,
                "company": "TEST",
                "report_year": "2025",
                "data_year": "2025",
                "statement_scope": "CONSOLIDATED",
                "restated_flag": False,
                "period_type": "ANNUAL",
                "currency_unit": "CNY_MILLION",
                "unit": "百万元",
                "measure": "",
                "mapping_status": "EXACT",
                "capture_run_id": "CAPTURE",
                "source_pdf": "fixture.pdf",
                "page": 1,
                "bbox": "{}",
                "raw_item": axis,
                "container_id": "NOTE_1",
                "table_block_id": f"BLOCK_{order}",
                "block_order": order,
                "classification_axis": axis,
                "block_role": "PRIMARY_TABLE" if order == 0 else "SECONDARY_TABLE",
                "block_terminal_type": (
                    "LOCAL_TOTAL" if order == 0 else "FINAL_TOTAL" if order == 2 else "NONE"
                ),
            }
        )

    resolved, _, conflicts = materialize_canonical(pd.DataFrame(rows))

    assert conflicts.empty
    assert BLOCK_FIELDS.issubset(resolved.columns)
    assert resolved["table_block_id"].nunique() == 3
    assert resolved.sort_values("block_order")["classification_axis"].tolist() == [
        "ASSET_TYPE",
        "MEASUREMENT_COMPOSITION",
        "LISTING_STATUS",
    ]


def test_apply_mapping_accepts_capture_long_with_existing_mapping_columns() -> None:
    result = _multiblock_result()
    _, blocks = segment_table_blocks(result)
    raw = capture_to_long_df(materialize_block_result(result, blocks[0]))
    raw["capture_run_id"] = "CAPTURE"
    raw["company"] = "TEST"
    raw = assign_conditional_source_keys(raw)
    mapping = raw[["source_key"]].drop_duplicates().assign(
        canonical_section="其他债权投资",
        canonical_item="已映射项目",
        category="",
        mapping_status="CONFIRMED",
        mapping_note="",
    )

    mapped = apply_mapping(raw, mapping)

    assert "canonical_item" in mapped.columns
    assert "mapping_status" in mapped.columns
    assert not any(column.endswith(("_x", "_y")) for column in mapped.columns)
    assert set(mapped["canonical_item"]) == {"已映射项目"}


def test_registry_and_ui_expose_block_dimensions(tmp_path: Path) -> None:
    registry = MetadataRegistry(tmp_path / "metadata.db")
    with registry.connect() as conn:
        table_block_columns = {
            row[1] for row in conn.execute("PRAGMA table_info(table_blocks)").fetchall()
        }
    assert {"classification_axis", "block_terminal_type"}.issubset(table_block_columns)

    panel = (
        Path(__file__).resolve().parents[1]
        / "components"
        / "capture_inspection_panel.py"
    ).read_text(encoding="utf-8")
    for field in BLOCK_FIELDS:
        assert field in panel


def test_unrelated_numeric_disclosure_after_local_total_is_not_silently_merged() -> None:
    result = _multiblock_result()
    result.rows = [
        _row(1, "债券", row_type="SECTION_HEADER"),
        _row(2, "政府债", 100, 90, parent_section="债券"),
        _row(3, "合计", 100, 90, row_type="TOTAL"),
        _row(4, "风险敞口：", row_type="SECTION_HEADER"),
        _row(5, "最大信用风险敞口", 999, 888),
    ]

    _, blocks = segment_table_blocks(result)
    containing = [
        block
        for block in blocks
        if any(row.raw_item == "最大信用风险敞口" for row in block.rows)
    ]

    assert len(containing) == 1
    disclosure = containing[0]
    assert disclosure.classification_axis == "UNRESOLVED"
    assert disclosure.block_terminal_type == "UNRESOLVED"
    assert disclosure.quality_status == "REVIEW_REQUIRED"
    assert not any(row.raw_item == "政府债" for row in disclosure.rows)


def test_numeric_unresolved_axis_and_terminal_block_requires_review() -> None:
    result = _multiblock_result()
    result.rows = [_row(1, "最大信用风险敞口", 999, 888)]

    _, blocks = segment_table_blocks(result)

    assert len(blocks) == 1
    assert blocks[0].classification_axis == "UNRESOLVED"
    assert blocks[0].block_terminal_type == "UNRESOLVED"
    assert blocks[0].quality_status == "REVIEW_REQUIRED"


def test_authoritative_axis_hint_resolves_headerless_short_table() -> None:
    result = _multiblock_result()
    result.table_query = "14 其他权益工具投资"
    result.located_title = "14 其他权益工具投资"
    result.rows = [
        _row(1, "股票", 5_351, 5_000),
        _row(2, "未上市股权", 19, 18),
        _row(3, "合计", 5_370, 5_018, row_type="TOTAL"),
    ]

    _, blocks = segment_table_blocks(result, classification_axis_hint="ASSET_TYPE")

    assert len(blocks) == 1
    assert blocks[0].classification_axis == "ASSET_TYPE"
    assert blocks[0].block_terminal_type == "FINAL_TOTAL"
    assert blocks[0].quality_status == "READY"
    assert {row.classification_axis for row in blocks[0].rows} == {"ASSET_TYPE"}


def test_headerless_short_table_without_authoritative_axis_remains_unresolved() -> None:
    result = _multiblock_result()
    result.table_query = "14 其他权益工具投资"
    result.located_title = "14 其他权益工具投资"
    result.rows = [_row(1, "股票", 999, 888), _row(2, "未上市股权", 1, 2), _row(3, "合计", 1000, 890, row_type="TOTAL")]
    result.table_query = "14 其他权益工具投资"
    result.located_title = "14 其他权益工具投资"

    _, blocks = segment_table_blocks(result)

    assert len(blocks) == 1
    assert blocks[0].classification_axis == "UNRESOLVED"


def test_block_ids_survive_insertion_of_an_unrelated_preceding_block() -> None:
    baseline = _multiblock_result()
    _, baseline_blocks = segment_table_blocks(baseline)
    prefixed = _multiblock_result()
    prefixed.rows = [
        _row(-2, "新增短表", 5, 4),
        _row(
            -1,
            "这是一段足够长的叙述分隔文本，用来证明后续原始三个表块本身没有改变。",
            row_type="MEMO_TEXT",
        ),
        *copy.deepcopy(prefixed.rows),
    ]

    _, prefixed_blocks = segment_table_blocks(prefixed)
    stable_axes = {
        "ASSET_TYPE",
        "MEASUREMENT_COMPOSITION",
        "LISTING_STATUS",
    }
    baseline_by_axis = {
        block.classification_axis: block.block_id
        for block in baseline_blocks
        if block.classification_axis in stable_axes
    }
    prefixed_by_axis = {
        block.classification_axis: block.block_id
        for block in prefixed_blocks
        if block.classification_axis in stable_axes
    }

    assert baseline_by_axis == prefixed_by_axis
    assert len(set(prefixed_by_axis.values())) == 3


def test_noncompound_null_block_dimensions_keep_canonical_wide_value() -> None:
    raw = pd.DataFrame(
        [
            {
                "value": 42.0,
                "source_key": "UNIQUE||普通项目",
                "canonical_section": None,
                "canonical_item": None,
                "category": "",
                "mapping_status": "UNMAPPED",
                "mapping_note": "",
                "normalized_item": "普通项目",
                "parent_section": "",
                "row_type": "DETAIL",
                "row_level": 0,
                "row_path": "普通项目",
                "raw_item": "普通项目",
                "row_order": 1,
                "table_id": "SINGLE_TABLE",
                "table_family": "SINGLE_FAMILY",
                "member_table": "SINGLE_MEMBER",
                "member_table_role": "COMPONENT",
                "source_table_title": "SINGLE_MEMBER",
                "container_id": None,
                "table_block_id": None,
                "block_order": None,
                "classification_axis": "UNRESOLVED",
                "block_role": "UNRESOLVED",
                "block_terminal_type": "UNRESOLVED",
                "company": "TEST",
                "report_year": "2026",
                "data_year": "2026",
                "statement_scope": "CONSOLIDATED",
                "restated_flag": False,
                "period_type": "ANNUAL",
                "currency_unit": "CNY",
                "unit": "元",
                "measure": "",
                "capture_run_id": "CAPTURE_SINGLE",
                "source_pdf": "fixture.pdf",
                "page": 1,
                "bbox": "{}",
            }
        ]
    )
    mapping = pd.DataFrame(
        [
            {
                "source_key": "UNIQUE||普通项目",
                "canonical_section": "普通",
                "canonical_item": "普通项目",
                "category": "",
                "mapping_status": "CONFIRMED",
                "mapping_note": "",
            }
        ]
    )

    mapped = apply_mapping(raw, mapping)
    resolved, wide, conflicts = materialize_canonical(mapped)
    document_columns = [
        column for column in wide.columns if str(column).startswith("company=")
    ]

    assert conflicts.empty
    assert len(resolved) == 1
    assert len(wide) == 1
    assert len(document_columns) == 1
    assert float(wide.iloc[0][document_columns[0]]) == 42.0


def test_real_qa_amount_oracle_rejects_tampered_amount() -> None:
    qa_module = runpy.run_path(
        str(Path(__file__).with_name("run_v611_multiblock_real_qa.py"))
    )
    expected_amounts = qa_module["EXPECTED_AMOUNTS"]
    amounts_match = qa_module["_amounts_match_expected"]

    assert amounts_match("政府债", expected_amounts["政府债"])
    tampered = dict(expected_amounts["政府债"])
    tampered["2025"] += 1
    assert not amounts_match("政府债", tampered)


def test_real_qa_inserts_and_reads_table_block_rows(tmp_path: Path) -> None:
    qa_module = runpy.run_path(
        str(Path(__file__).with_name("run_v611_multiblock_real_qa.py"))
    )
    persist_and_read = qa_module["_persist_and_read_registry_blocks"]
    result = _multiblock_result()
    container, blocks = segment_table_blocks(result)
    registry = MetadataRegistry(tmp_path / "metadata.db")

    persisted = persist_and_read(registry, container, blocks)

    assert len(persisted) == 3
    expected = {
        block.block_id: (
            container.container_id,
            block.block_order,
            block.classification_axis,
            block.role,
            block.block_terminal_type,
        )
        for block in blocks
    }
    actual = {
        row["block_id"]: (
            row["container_id"],
            row["block_order"],
            row["classification_axis"],
            row["block_role"],
            row["block_terminal_type"],
        )
        for row in persisted
    }
    assert actual == expected


def test_real_pingan_other_debt_keeps_all_logical_rows_and_two_years() -> None:
    repo_root = Path(__file__).resolve().parents[3]
    pdf = repo_root / "docu" / "中国平安2025年报.pdf"
    if not pdf.exists():
        pytest.skip(f"real PDF unavailable: {pdf}")

    from note_target_resolver import NoteReferenceResolver

    resolver = NoteReferenceResolver()
    target = resolver.certify(
        resolver.candidates_from_pdf(
            pdf,
            note_reference="附注八-11",
            member_table="其他债权投资",
        )[0]
    )
    result = capture_named_table(
        pdf,
        "其他债权投资",
        note_number="附注八-11",
        start_page_override=target["confirmed_note_pdf_page_index"],
        max_pages=8,
        allow_legacy_fallback=False,
    )

    logical_rows = []
    for row in result.rows:
        if row.row_type in {"MEMO_TEXT", "NOTE_TEXT"}:
            continue
        raw = str(row.raw_item or "").strip()
        if raw.rstrip("：:") == "其中" and not row.cells:
            continue
        if row.row_role == "IMPLICIT_TOTAL" and not raw:
            logical_rows.append("IMPLICIT_FINAL_TOTAL")
        elif str(row.parent_section or "").rstrip("：:") == "其中":
            logical_rows.append("其中" + raw)
        else:
            logical_rows.append(raw)

    assert logical_rows == [
        "债券",
        "政府债",
        "金融债",
        "企业债",
        "债权计划",
        "理财产品投资",
        "合计",
        "其中－摊余成本",
        "其中－累计公允价值变动",
        "上市",
        "非上市",
        "IMPLICIT_FINAL_TOTAL",
    ]
    assert [column.year for column in result.columns] == ["2025", "2024"]
    assert result.stats["post_total_disclosure_not_merged"] is False

    _, blocks = segment_table_blocks(result)
    assert [block.classification_axis for block in blocks] == [
        "ASSET_TYPE",
        "MEASUREMENT_COMPOSITION",
        "LISTING_STATUS",
    ]
