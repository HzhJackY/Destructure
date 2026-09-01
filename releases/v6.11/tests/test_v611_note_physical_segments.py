from __future__ import annotations

import sys
from types import SimpleNamespace

try:
    import fitz  # noqa: F401
except ModuleNotFoundError:
    sys.modules["fitz"] = SimpleNamespace()

from compound_note_engine import materialize_block_result, segment_table_blocks
from spatial_table_capture import (
    _line_to_spatial_cells,
    _plan_physical_table_segments,
    _report_page_chrome_role,
    _validated_numeric_assignment_anchors,
)
from table_capture import TableCaptureResult, TableCell, TableColumn, TableRow
from table_segment_classifier import (
    SegmentClassification,
    classify_table_segment,
)


PAGE_WIDTH = 800.0


def _word(x0: float, x1: float, text: str, y0: float) -> dict:
    return {
        "x0": x0,
        "x1": x1,
        "y0": y0,
        "y1": y0 + 12.0,
        "xc": (x0 + x1) / 2.0,
        "yc": y0 + 6.0,
        "text": text,
    }


def _line(y0: float, words: list[dict]) -> dict:
    return {
        "x0": min(word["x0"] for word in words),
        "x1": max(word["x1"] for word in words),
        "y0": y0,
        "y1": y0 + 12.0,
        "text": " ".join(str(word["text"]) for word in words),
        "words": words,
    }


def _amount_row(y0: float, label: str, centers: list[float], values: list[str]) -> dict:
    words = [_word(80.0, 180.0, label, y0)]
    for center, value in zip(centers, values):
        words.append(_word(center - 18.0, center + 18.0, value, y0))
    return _line(y0, words)


def test_right_aligned_amount_lanes_can_differ_from_header_text_centres() -> None:
    header_anchors = [468.4, 510.9]
    numeric_clusters = {
        "count": 2,
        "centers": [450.2, 535.3],
        "supports": [4, 4],
        "lines": 4,
        "body_end_y": 368.7,
        "body_bounded": True,
    }
    assignment_anchors = _validated_numeric_assignment_anchors(
        header_anchors,
        numeric_clusters,
        page_width=595.3,
    )
    assert assignment_anchors == [450.2, 535.3]
    assert _validated_numeric_assignment_anchors(
        header_anchors,
        {**numeric_clusters, "body_bounded": False},
        page_width=595.3,
        require_body_bounded=True,
    ) is None

    line = _line(150.0, [
        _word(62.0, 111.0, "未上市股权", 150.0),
        _word(451.3, 462.1, "24", 157.8),
        _word(536.4, 547.1, "22", 158.3),
    ])
    parsed = _line_to_spatial_cells(
        line,
        header_anchors,
        595.3,
        numeric_anchors=assignment_anchors,
    )
    assert [(raw, number) for raw, number, _unit in parsed["values"]] == [
        ("24", 24.0),
        ("22", 22.0),
    ]


def _two_table_pages() -> tuple[dict[int, list[dict]], dict[int, float]]:
    balance_centers = [560.0, 700.0]
    stage_centers = [330.0, 470.0, 610.0, 740.0]
    page_193 = [
        _line(40.0, [
            _word(520.0, 600.0, "2024年12月31日", 40.0),
            _word(660.0, 740.0, "2023年12月31日", 40.0),
        ]),
        _amount_row(80.0, "政府债", balance_centers, ["246,842", "260,108"]),
        _amount_row(100.0, "金融债", balance_centers, ["3,851", "3,724"]),
        _amount_row(120.0, "小计", balance_centers, ["277,791", "313,623"]),
        _amount_row(140.0, "合计", balance_centers, ["274,891", "313,148"]),
        _line(175.0, [
            _word(
                90.0,
                650.0,
                "于本年度及上年度，信用损失准备的具体变动情况列示如下表所示",
                175.0,
            ),
        ]),
        _line(215.0, [
            _word(292.0, 368.0, "第一阶段", 215.0),
            _word(432.0, 508.0, "第二阶段", 215.0),
            _word(572.0, 648.0, "第三阶段", 215.0),
            _word(712.0, 768.0, "合计", 215.0),
        ]),
        _line(232.0, [
            _word(286.0, 374.0, "12个月预期信用损失", 232.0),
            _word(420.0, 520.0, "整个存续期预期信用损失", 232.0),
            _word(555.0, 665.0, "整个存续期预期信用损失-已减值", 232.0),
        ]),
        _amount_row(270.0, "2024年1月1日信用损失准备", stage_centers, ["87", "2", "386", "475"]),
        _amount_row(292.0, "本年计提", stage_centers, ["26", "857", "1,594", "2,425"]),
        _amount_row(314.0, "2024年12月31日信用损失准备", stage_centers, ["6", "914", "1,980", "2,900"]),
    ]
    page_194 = [
        _line(35.0, [
            _word(292.0, 368.0, "第一阶段", 35.0),
            _word(432.0, 508.0, "第二阶段", 35.0),
            _word(572.0, 648.0, "第三阶段", 35.0),
            _word(712.0, 768.0, "合计", 35.0),
        ]),
        _amount_row(85.0, "2023年1月1日信用损失准备", stage_centers, ["1", "2", "3", "6"]),
        _amount_row(108.0, "汇兑差额", stage_centers, ["4", "5", "6", "15"]),
        _amount_row(131.0, "2023年12月31日期末余额", stage_centers, ["6", "914", "1,980", "2,900"]),
    ]
    return {193: page_193, 194: page_194}, {193: PAGE_WIDTH, 194: PAGE_WIDTH}


def _root_metadata() -> list[dict]:
    return [
        {
            "tokens": ["2024年12月31日"],
            "year": "2024",
            "scope": None,
            "restated": False,
            "period_label": "2024年12月31日",
            "period_kind": "ABSOLUTE_DATE",
            "measure": None,
        },
        {
            "tokens": ["2023年12月31日"],
            "year": "2023",
            "scope": None,
            "restated": False,
            "period_label": "2023年12月31日",
            "period_kind": "ABSOLUTE_DATE",
            "measure": None,
        },
    ]


def test_same_note_period_reset_builds_independent_supplementary_tables() -> None:
    lines_by_page, page_widths = _two_table_pages()
    plans, by_page, additional_columns = _plan_physical_table_segments(
        lines_by_page,
        page_widths,
        start_page=193,
        end_page=194,
        root_header={
            "header_y0": 40.0,
            "header_y1": 52.0,
            "anchors": [560.0, 700.0],
        },
        root_metadata=_root_metadata(),
        root_header_bottom=52.0,
        note_identity="12",
        table_identity="12. 债权投资",
        unit="百万元",
    )

    assert [plan["segment"].classification.value for plan in plans] == [
        "PRIMARY_TABLE",
        "SUPPLEMENTARY_TABLE",
        "SUPPLEMENTARY_TABLE",
    ]
    assert [len(plan["anchors"]) for plan in plans] == [2, 4, 4]
    assert len(additional_columns) == 8
    assert plans[1]["source_column_ordinals"] == [2, 3, 4, 5]
    assert plans[2]["source_column_ordinals"] == [6, 7, 8, 9]
    assert plans[2]["segment"].continuation_of_segment_id is None
    assert "PERIOD_AXIS_RESET" in plans[2]["segment"].reason_codes
    assert by_page[194][0]["header_source_page"] is None
    assert all("新华" not in str(plan["segment"].reason_codes) for plan in plans)


def test_orphan_continuation_marker_is_unresolved_candidate() -> None:
    segment = classify_table_segment(
        "SEG_orphan",
        2,
        (0.0, 0.0, 800.0, 700.0),
        "12",
        "债权投资",
        ["债权投资（续）"],
        ["2024", "2023"],
        anchor_ratios=[0.7, 0.85],
    )

    assert segment.classification is SegmentClassification.UNRESOLVED
    assert segment.candidate_relation == "CONTINUATION_SEGMENT"
    assert "CONTINUATION_RELATION_UNRESOLVED" in segment.reason_codes


def test_period_reset_overrides_weak_continuation_marker() -> None:
    primary = classify_table_segment(
        "SEG_primary",
        1,
        (0.0, 0.0, 800.0, 700.0),
        "12",
        "债权投资",
        ["债权投资"],
        ["2024", "2023"],
        anchor_ratios=[0.7, 0.85],
        period_labels=["2024", "2023"],
    )
    supplementary = classify_table_segment(
        "SEG_ecl_2024",
        1,
        (0.0, 350.0, 800.0, 700.0),
        "12",
        "债权投资信用损失准备",
        ["信用损失准备变动情况如下"],
        ["第一阶段", "第二阶段", "第三阶段", "合计"],
        primary,
        anchor_ratios=[0.4, 0.58, 0.76, 0.92],
        period_labels=["2024"],
        measure_labels=["第一阶段", "第二阶段", "第三阶段", "合计"],
        independent_header=True,
        narrative_separator=True,
        local_total_before=True,
    )
    same_period = classify_table_segment(
        "SEG_ecl_2024_cont",
        2,
        (0.0, 0.0, 800.0, 300.0),
        "12",
        supplementary.table_identity,
        ["（续）"],
        ["第一阶段", "第二阶段", "第三阶段", "合计"],
        supplementary,
        anchor_ratios=[0.4, 0.58, 0.76, 0.92],
        period_labels=["2024"],
        measure_labels=["第一阶段", "第二阶段", "第三阶段", "合计"],
        page_adjacent=True,
    )
    reset_period = classify_table_segment(
        "SEG_ecl_2023",
        2,
        (0.0, 300.0, 800.0, 700.0),
        "12",
        supplementary.table_identity,
        ["（续）"],
        ["第一阶段", "第二阶段", "第三阶段", "合计"],
        supplementary,
        anchor_ratios=[0.4, 0.58, 0.76, 0.92],
        period_labels=["2023"],
        measure_labels=["第一阶段", "第二阶段", "第三阶段", "合计"],
        page_adjacent=True,
    )

    assert same_period.classification is SegmentClassification.CONTINUATION_SEGMENT
    assert same_period.continuation_of_segment_id == supplementary.segment_id
    assert reset_period.classification is SegmentClassification.SUPPLEMENTARY_TABLE
    assert reset_period.continuation_of_segment_id is None
    assert "PERIOD_AXIS_RESET" in reset_period.reason_codes


def test_multiple_amount_clusters_assigned_to_one_anchor_fail_closed() -> None:
    line = _line(100.0, [
        _word(70.0, 150.0, "期末余额", 100.0),
        _word(555.0, 580.0, "87", 100.0),
        _word(620.0, 645.0, "386", 100.0),
        _word(688.0, 712.0, "475", 100.0),
    ])

    try:
        _line_to_spatial_cells(line, [600.0, 700.0], PAGE_WIDTH)
    except ValueError as exc:
        assert "MULTIPLE_NUMERIC_CLUSTERS_IN_ONE_CELL" in str(exc)
    else:
        raise AssertionError("多个独立金额簇不得被拼成单一单元格")


def test_report_page_chrome_requires_report_marker_and_page_edge() -> None:
    running_header = _line(24.0, [
        _word(381.0, 475.0, "新华人寿保险股份有限公司", 24.0),
        _word(480.0, 497.0, "2024", 24.0),
        _word(499.0, 539.0, "年年度报告", 24.0),
        _word(550.0, 566.0, "191", 24.0),
    ])
    table_period_row = _line(324.0, [
        _word(119.0, 144.0, "2024年度", 324.0),
        _word(500.0, 530.0, "1,234", 324.0),
    ])

    assert _report_page_chrome_role(running_header, 807.0) == "PAGE_HEADER_NOISE"
    assert _report_page_chrome_role(table_period_row, 807.0) is None


def _cell(ordinal: int, value: float) -> TableCell:
    return TableCell(
        column_ordinal=ordinal,
        source_column_index=ordinal + 1,
        raw=f"{value:,.0f}",
        parsed_number=value,
        unit_original="百万元",
        value_yuan=value * 1_000_000,
    )


def _row(
    order: int,
    page: int,
    segment_id: str,
    label: str,
    ordinals: list[int],
) -> TableRow:
    return TableRow(
        row_order=order,
        page=page,
        block_id=segment_id,
        source_method="TEST_PHYSICAL_SEGMENT",
        raw_item=label,
        normalized_item=label,
        canonical_item=None,
        mapping_status="UNMAPPED",
        row_type="DETAIL",
        row_level=0,
        parent_section=None,
        cells=[_cell(ordinal, float(index + 1)) for index, ordinal in enumerate(ordinals)],
        header_source_page=None,
        bbox={"x0": 50.0, "y0": order * 20.0, "x1": 760.0, "y1": order * 20.0 + 12.0},
    )


def test_compound_blocks_preserve_physical_relation_and_local_columns() -> None:
    lines_by_page, page_widths = _two_table_pages()
    plans, _by_page, additional_columns = _plan_physical_table_segments(
        lines_by_page,
        page_widths,
        start_page=193,
        end_page=194,
        root_header={
            "header_y0": 40.0,
            "header_y1": 52.0,
            "anchors": [560.0, 700.0],
        },
        root_metadata=_root_metadata(),
        root_header_bottom=52.0,
        note_identity="12",
        table_identity="12. 债权投资",
        unit="百万元",
    )
    columns = [
        TableColumn(0, 1, "2024年12月31日", "2024", None, False, "2024年12月31日"),
        TableColumn(1, 2, "2023年12月31日", "2023", None, False, "2023年12月31日"),
    ]
    for meta in additional_columns:
        columns.append(TableColumn(
            int(meta["ordinal"]),
            int(meta["source_column_index"]),
            " | ".join(meta.get("tokens") or []),
            meta.get("year"),
            meta.get("scope"),
            bool(meta.get("restated")),
            meta.get("period_label"),
            meta.get("measure"),
        ))
    footer_noise = _row(
        4,
        194,
        "SEG_LAYOUT_NOISE",
        "194二零二四年年报财务报告",
        [],
    )
    footer_noise.excluded_from_table_logic = True
    footer_noise.row_role = "PAGE_FOOTER_NOISE"
    result = TableCaptureResult(
        pdf_name="synthetic.pdf",
        pdf_sha256="sha256",
        table_query="债权投资",
        note_number="12",
        located_title="12. 债权投资",
        start_page=193,
        end_page=194,
        pages=[193, 194],
        unit="百万元",
        columns=columns,
        rows=[
            _row(1, 193, plans[0]["segment_id"], "债券", [0, 1]),
            _row(2, 193, plans[1]["segment_id"], "期初余额", [2, 3, 4, 5]),
            _row(3, 194, plans[2]["segment_id"], "期末余额", [6, 7, 8, 9]),
            footer_noise,
        ],
        warnings=[],
        stats={
            "physical_table_segments": [plan["segment"].to_dict() for plan in plans],
            "physical_segment_column_groups": [
                {
                    "segment_id": plan["segment_id"],
                    "source_column_ordinals": plan["source_column_ordinals"],
                }
                for plan in plans
            ],
        },
    )

    _container, blocks = segment_table_blocks(result)

    assert [block.segment_classification for block in blocks] == [
        "PRIMARY_TABLE",
        "SUPPLEMENTARY_TABLE",
        "SUPPLEMENTARY_TABLE",
    ]
    assert blocks[2].continuation_of_segment_id is None
    assert all(len(block.physical_segment_ids) == 1 for block in blocks)
    supplementary = materialize_block_result(result, blocks[1])
    prior_period_schedule = materialize_block_result(result, blocks[2])
    assert len(supplementary.columns) == 4
    assert [cell.column_ordinal for cell in supplementary.rows[0].cells] == [0, 1, 2, 3]
    assert len(prior_period_schedule.columns) == 4
    assert prior_period_schedule.stats["continuation_of_segment_id"] is None
