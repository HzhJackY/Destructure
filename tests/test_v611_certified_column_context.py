from __future__ import annotations

import pytest

import spatial_table_capture as spatial


PAGE_WIDTH = 800.0
CENTERS = [320.0, 440.0, 560.0, 680.0]
MEASURES = ["第一阶段", "第二阶段", "第三阶段", "合计"]


def _word(center: float, text: str, y0: float, width: float = 40.0) -> dict:
    return {
        "x0": center - width / 2.0,
        "x1": center + width / 2.0,
        "y0": y0,
        "y1": y0 + 12.0,
        "xc": center,
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


def _amount_line(y0: float, label: str, values: list[str]) -> dict:
    words = [_word(120.0, label, y0, width=180.0)]
    words.extend(
        _word(center, value, y0)
        for center, value in zip(CENTERS, values)
    )
    return _line(y0, words)


def _segment(periods: list[str]) -> dict:
    return {
        "certification_status": "CERTIFIED",
        "classification": "SUPPLEMENTARY_TABLE",
        "start_page": 1,
        "bbox": {
            "page": 1,
            "x0": 0.0,
            "y0": 20.0,
            "x1": PAGE_WIDTH,
            "y1": 220.0,
        },
        "evidence": {
            "header_y0": 20.0,
            "header_y1": 60.0,
            "data_y_min": 60.0,
        },
        "period_signature": {"period_labels": periods},
        "header_signature": {
            "leaf_count": 4,
            "labels": MEASURES,
        },
        "amount_lane_signature": {
            "lane_count": 4,
            "anchor_ratios": [center / PAGE_WIDTH for center in CENTERS],
            "source_column_ordinals": [2, 3, 4, 5],
        },
    }


def _body_lines() -> list[dict]:
    return [
        _amount_line(80.0, "期初余额", ["1", "2", "3", "6"]),
        _amount_line(105.0, "本期计提", ["4", "5", "6", "15"]),
        _amount_line(130.0, "期末余额", ["5", "7", "9", "21"]),
    ]


def test_certified_single_period_broadcasts_to_measure_lanes() -> None:
    context = spatial._certified_column_context(
        [_segment(["2025"])],
        page_number=1,
        lines=_body_lines(),
        page_width=PAGE_WIDTH,
    )

    header, arbitration = spatial._certified_header(context)

    assert header["period_labels"] == ["2025"] * 4
    assert header["measure_labels"] == MEASURES
    assert arbitration["auto_abstain"] is False
    assert arbitration["candidates"]["CERTIFIED_COLUMN_CONTEXT"]["status"] == "VALID"


def test_certified_context_rejects_body_lane_count_mismatch() -> None:
    lines = [
        _amount_line(80.0, "期初余额", ["1", "2", "3"]),
        _amount_line(105.0, "本期计提", ["4", "5", "6"]),
        _amount_line(130.0, "期末余额", ["5", "7", "9"]),
    ]

    with pytest.raises(
        ValueError,
        match="CERTIFIED_COLUMN_CONTEXT_BODY_LANES_MISMATCH",
    ):
        spatial._certified_column_context(
            [_segment(["2025"])],
            page_number=1,
            lines=lines,
            page_width=PAGE_WIDTH,
        )


def test_certified_context_counts_fullwidth_placeholder_lane_support() -> None:
    lines = [
        _amount_line(80.0, "期初余额", ["－", "2", "3", "5"]),
        _amount_line(105.0, "本期计提", ["－", "5", "6", "11"]),
        _amount_line(130.0, "期末余额", ["－", "7", "9", "16"]),
    ]

    context = spatial._certified_column_context(
        [_segment(["2025"])],
        page_number=1,
        lines=lines,
        page_width=PAGE_WIDTH,
    )

    assert len(context["numeric_assignment_anchors"]) == 4


def test_multisegment_target_does_not_use_single_segment_column_context() -> None:
    second = _segment(["2025"])
    second["start_page"] = 2
    second["bbox"] = {**second["bbox"], "page": 2}

    context = spatial._certified_column_context(
        [_segment(["2025"]), second],
        page_number=1,
        lines=_body_lines(),
        page_width=PAGE_WIDTH,
    )

    assert context is None


def test_certified_periods_create_distinct_logical_blocks_over_shared_lanes() -> None:
    lines = [
        _amount_line(80.0, "2025年1月1日信用损失准备", ["1", "2", "3", "6"]),
        _amount_line(105.0, "本年计提", ["4", "5", "6", "15"]),
        _amount_line(130.0, "2025年12月31日信用损失准备", ["5", "7", "9", "21"]),
        _amount_line(160.0, "2024年1月1日信用损失准备", ["2", "3", "4", "9"]),
        _amount_line(185.0, "本年计提", ["1", "1", "1", "3"]),
        _amount_line(205.0, "2024年12月31日信用损失准备", ["3", "4", "5", "12"]),
    ]
    context = spatial._certified_column_context(
        [_segment(["2025", "2024"])],
        page_number=1,
        lines=lines,
        page_width=PAGE_WIDTH,
    )

    groups, occurrences = spatial._certified_vertical_period_plan(
        context,
        {1: lines},
        {1: PAGE_WIDTH},
    )

    assert len(groups) == 2
    assert [group["column_offset"] for group in groups] == [0, 4]
    assert [group["column_count"] for group in groups] == [4, 4]
    assert [group["period_labels"][0] for group in groups] == ["2025", "2024"]
    assert len(occurrences[1]) == 2


def test_navigation_chrome_is_not_part_of_local_header_labels() -> None:
    navigation = _line(10.0, [
        _word(300.0, "关于公司", 10.0),
        _word(400.0, "致股东函", 10.0),
        _word(500.0, "企业管治", 10.0),
        _word(600.0, "财务报告", 10.0),
    ])
    stage_header = _line(35.0, [
        _word(center, label, 35.0)
        for center, label in zip(CENTERS, MEASURES)
    ])
    body = _amount_line(80.0, "期初余额", ["1", "2", "3", "6"])

    labels = spatial._local_header_labels(
        [navigation, stage_header, body],
        start_y=0.0,
        body_y=70.0,
        centers=CENTERS,
        page_width=PAGE_WIDTH,
    )

    assert labels == MEASURES


def test_fullwidth_dash_remains_an_aligned_placeholder_slot() -> None:
    line = _amount_line(80.0, "期初余额", ["－", "2", "3", "5"])

    parsed = spatial._line_to_spatial_cells(
        line,
        CENTERS,
        PAGE_WIDTH,
    )

    assert parsed["values"][0] == ("－", None, None)
    assert len(parsed["values"]) == 4


def test_not_applicable_is_materialized_only_in_an_amount_lane() -> None:
    line = _amount_line(80.0, "期初余额", ["1", "2", "不适用", "3"])

    parsed = spatial._line_to_spatial_cells(
        line,
        CENTERS,
        PAGE_WIDTH,
    )

    assert parsed["label"] == "期初余额"
    assert parsed["values"] == [
        ("1", 1.0, None),
        ("2", 2.0, None),
        ("不适用", None, None),
        ("3", 3.0, None),
    ]


def test_not_applicable_in_the_label_region_stays_label_text() -> None:
    line = _amount_line(80.0, "不适用的资产", ["1", "2", "3", "6"])

    parsed = spatial._line_to_spatial_cells(
        line,
        CENTERS,
        PAGE_WIDTH,
    )

    assert parsed["label"] == "不适用的资产"
    assert [raw for raw, _number, _unit in parsed["values"]] == ["1", "2", "3", "6"]
