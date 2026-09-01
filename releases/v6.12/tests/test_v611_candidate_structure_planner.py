from __future__ import annotations

import json
from pathlib import Path

import pytest
import spatial_table_capture as spatial


PAGE_WIDTH = 800.0
CL23_PDF = (
    Path(__file__).resolve().parents[3]
    / "docu"
    / "中国人寿2023年年度报告.pdf"
)


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


def _amount_row(
    y0: float,
    label: str,
    centers: list[float],
    values: list[str],
) -> dict:
    words = [_word(80.0, 180.0, label, y0)]
    for center, value in zip(centers, values):
        words.append(_word(center - 18.0, center + 18.0, value, y0))
    return _line(y0, words)


def test_local_header_labels_bind_group_parent_and_exclude_period_token() -> None:
    centers = [370.5, 455.6, 559.0]
    lines = [
        _line(126.0, [
            _word(405.0, 474.0, "2023年12月31日", 126.0),
        ]),
        _line(141.0, [
            _word(378.0, 442.0, "以公允价值计量", 141.0),
            _word(516.0, 561.0, "以成本计量", 141.0),
        ]),
        _line(156.0, [
            _word(346.0, 391.0, "债权型投资", 156.0),
            _word(431.0, 476.0, "股权型投资", 156.0),
            _word(516.0, 561.0, "股权型投资", 156.0),
        ]),
        _amount_row(
            177.0,
            "成本/摊余成本",
            centers,
            ["1,164,070", "1,123,417", "–"],
        ),
    ]

    labels = spatial._local_header_labels(
        lines,
        start_y=125.0,
        body_y=177.0,
        centers=centers,
        page_width=595.276,
    )

    assert labels == [
        "以公允价值计量 | 债权型投资",
        "以公允价值计量 | 股权型投资",
        "以成本计量 | 股权型投资",
    ]


def test_sparse_group_header_extends_local_header_without_bleeding_to_total() -> None:
    centers = [297.2, 375.3, 450.0, 525.3]
    lines = [
        _line(445.9, [
            _word(
                90.0,
                295.0,
                "于2023年度，债权投资信用损失准备变动情况如下：",
                445.9,
            ),
        ]),
        _line(473.0, [_word(419.9, 456.4, "第三阶段", 473.0)]),
        _line(486.0, [
            _word(267.0, 303.2, "第一阶段", 486.0),
            _word(343.5, 379.8, "第二阶段", 486.0),
            _word(405.0, 453.0, "（整个存续期", 486.0),
        ]),
        _line(499.0, [
            _word(250.0, 306.8, "(12个月预期", 499.0),
            _word(320.0, 385.0, "（整个存续期", 499.0),
            _word(414.0, 462.4, "预期信用", 499.0),
        ]),
        _line(512.0, [
            _word(262.0, 308.0, "信用损失）", 512.0),
            _word(317.0, 387.8, "预期信用损失）", 512.0),
            _word(396.0, 461.8, "损失－已减值）", 512.0),
            _word(510.0, 539.6, "合计", 512.0),
        ]),
        _line(541.0, [_word(80.0, 159.6, "2023年1月1日", 541.0)]),
        _amount_row(
            554.0,
            "信用损失准备",
            centers,
            ["91", "－", "76", "167"],
        ),
    ]

    header_y0 = spatial._preceding_local_lane_header_y0(
        lines,
        period_y0=541.0,
        lower_bound=429.4,
        centers=centers,
        page_width=595.276,
    )
    labels = spatial._local_header_labels(
        lines,
        start_y=header_y0 - 0.01,
        body_y=554.0,
        centers=centers,
        page_width=595.276,
    )

    assert header_y0 == 473.0
    assert labels == [
        "第一阶段 | (12个月预期 | 信用损失）",
        "第二阶段 | （整个存续期 | 预期信用损失）",
        "第三阶段 | （整个存续期 | 预期信用 | 损失－已减值）",
        "合计",
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
        _amount_row(
            270.0,
            "2024年1月1日信用损失准备",
            stage_centers,
            ["87", "2", "386", "475"],
        ),
        _amount_row(292.0, "本年计提", stage_centers, ["26", "857", "1,594", "2,425"]),
        _amount_row(
            314.0,
            "2024年12月31日信用损失准备",
            stage_centers,
            ["6", "914", "1,980", "2,900"],
        ),
    ]
    page_194 = [
        _line(35.0, [
            _word(292.0, 368.0, "第一阶段", 35.0),
            _word(432.0, 508.0, "第二阶段", 35.0),
            _word(572.0, 648.0, "第三阶段", 35.0),
            _word(712.0, 768.0, "合计", 35.0),
        ]),
        _amount_row(
            85.0,
            "2023年1月1日信用损失准备",
            stage_centers,
            ["1", "2", "3", "6"],
        ),
        _amount_row(108.0, "汇兑差额", stage_centers, ["4", "5", "6", "15"]),
        _amount_row(
            131.0,
            "2023年12月31日期末余额",
            stage_centers,
            ["6", "914", "1,980", "2,900"],
        ),
    ]
    return {193: page_193, 194: page_194}, {
        193: PAGE_WIDTH,
        194: PAGE_WIDTH,
    }


def _same_page_two_period_supplementary() -> tuple[
    dict[int, list[dict]], dict[int, float]
]:
    balance_centers = [560.0, 700.0]
    stage_centers = [330.0, 470.0, 610.0, 740.0]
    page_196 = [
        _line(40.0, [
            _word(520.0, 600.0, "2025年12月31日", 40.0),
            _word(660.0, 740.0, "2024年12月31日", 40.0),
        ]),
        _amount_row(80.0, "政府债", balance_centers, ["300", "280"]),
        _amount_row(105.0, "金融债", balance_centers, ["200", "190"]),
        _amount_row(130.0, "合计", balance_centers, ["500", "470"]),
    ]
    page_197 = [
        _line(35.0, [
            _word(292.0, 368.0, "第一阶段", 35.0),
            _word(432.0, 508.0, "第二阶段", 35.0),
            _word(572.0, 648.0, "第三阶段", 35.0),
            _word(712.0, 768.0, "合计", 35.0),
        ]),
        _amount_row(75.0, "2025年1月1日信用损失准备", stage_centers, ["21", "331", "2,159", "2,511"]),
        _amount_row(100.0, "本年计提", stage_centers, ["5", "308", "1,870", "1,557"]),
        _amount_row(125.0, "2025年12月31日信用损失准备", stage_centers, ["16", "0", "4,052", "4,068"]),
        _line(230.0, [
            _word(292.0, 368.0, "第一阶段", 230.0),
            _word(432.0, 508.0, "第二阶段", 230.0),
            _word(572.0, 648.0, "第三阶段", 230.0),
            _word(712.0, 768.0, "合计", 230.0),
        ]),
        _amount_row(270.0, "2024年1月1日信用损失准备", stage_centers, ["42", "4", "1,524", "1,570"]),
        _amount_row(295.0, "本年计提", stage_centers, ["19", "325", "635", "941"]),
        _amount_row(320.0, "2024年12月31日信用损失准备", stage_centers, ["21", "331", "2,159", "2,511"]),
    ]
    return {196: page_196, 197: page_197}, {
        196: PAGE_WIDTH,
        197: PAGE_WIDTH,
    }


def _continuation_pages() -> tuple[dict[int, list[dict]], dict[int, float]]:
    centers = [560.0, 700.0]
    first = [
        _line(40.0, [
            _word(520.0, 600.0, "2024年12月31日", 40.0),
            _word(660.0, 740.0, "2023年12月31日", 40.0),
        ]),
        _amount_row(80.0, "政府债", centers, ["246,842", "260,108"]),
        _amount_row(105.0, "金融债", centers, ["3,851", "3,724"]),
    ]
    second = [
        _line(15.0, [
            _word(80.0, 150.0, "续表", 15.0),
        ]),
        _line(35.0, [
            _word(520.0, 600.0, "2024年12月31日", 35.0),
            _word(660.0, 740.0, "2023年12月31日", 35.0),
        ]),
        _amount_row(80.0, "企业债", centers, ["277,791", "313,623"]),
        _amount_row(105.0, "其他", centers, ["274,891", "313,148"]),
    ]
    return {1: first, 2: second}, {1: PAGE_WIDTH, 2: PAGE_WIDTH}


def _cl23_primary_page() -> list[dict]:
    centers = [560.0, 700.0]
    return [
        _line(40.0, [
            _word(520.0, 600.0, "2023年12月31日", 40.0),
            _word(660.0, 740.0, "2022年12月31日", 40.0),
        ]),
        _amount_row(80.0, "债券", centers, ["300", "280"]),
        _amount_row(105.0, "合计", centers, ["300", "280"]),
    ]


def _report_header() -> dict:
    return _line(10.0, [
        _word(350.0, 560.0, "2023年度财务报表附注（续）", 10.0),
    ])


def _cl23_horizontal_period_page() -> list[dict]:
    centers = [620.0, 740.0]
    return [
        _report_header(),
        _line(70.0, [_word(60.0, 240.0, "8. 贷款（续）", 70.0)]),
        _line(140.0, [
            _word(80.0, 180.0, "到期期限", 140.0),
            _word(570.0, 670.0, "2023年12月31日", 140.0),
            _word(690.0, 790.0, "2022年12月31日", 140.0),
        ]),
        _amount_row(180.0, "5年以内", centers, ["210,660", "233,675"]),
        _amount_row(205.0, "10年以上", centers, ["19,579", "13,670"]),
        _amount_row(230.0, "合计", centers, ["333,989", "344,426"]),
    ]


def _cl23_vertical_period_page(*, combined_header: bool) -> list[dict]:
    centers = [470.0, 610.0, 740.0]
    lines = [
        _report_header(),
        _line(70.0, [_word(60.0, 260.0, "持有至到期投资（续）", 70.0)]),
    ]
    if combined_header:
        lines.extend([
            _line(120.0, [
                _word(60.0, 170.0, "2023年12月31日", 120.0),
                _word(430.0, 510.0, "第一层级", 120.0),
                _word(570.0, 650.0, "第二层级", 120.0),
                _word(710.0, 770.0, "合计", 120.0),
            ]),
            _amount_row(160.0, "国债", centers, ["205", "154", "359"]),
            _amount_row(185.0, "合计", centers, ["276", "1,625", "1,901"]),
            _line(260.0, [
                _word(60.0, 170.0, "2022年12月31日", 260.0),
                _word(430.0, 510.0, "第一层级", 260.0),
                _word(570.0, 650.0, "第二层级", 260.0),
                _word(710.0, 770.0, "合计", 260.0),
            ]),
            _amount_row(300.0, "国债", centers, ["240", "177", "417"]),
            _amount_row(325.0, "合计", centers, ["346", "1,354", "1,700"]),
        ])
    else:
        for period_y, body_y, period, values in [
            (120.0, 180.0, "2023", ["1,164", "1,123", "–"]),
            (270.0, 330.0, "2022", ["856", "886", "17"]),
        ]:
            lines.extend([
                _line(period_y, [
                    _word(350.0, 520.0, f"{period}年12月31日", period_y),
                ]),
                _line(period_y + 20.0, [
                    _word(420.0, 520.0, "债权型投资", period_y + 20.0),
                    _word(560.0, 660.0, "股权型投资", period_y + 20.0),
                    _word(700.0, 780.0, "股权型投资", period_y + 20.0),
                ]),
                _amount_row(body_y, "成本", centers, values),
                _amount_row(body_y + 25.0, "公允价值", centers, values),
            ])
    return lines


def _plan_cl23_supplementary(page_two: list[dict]) -> dict:
    return spatial.plan_table_structure_candidates(
        {1: _cl23_primary_page(), 2: page_two},
        {1: PAGE_WIDTH, 2: PAGE_WIDTH},
        start_page=1,
        end_page=2,
        title_bbox=[40.0, 10.0, 280.0, 25.0],
        note_identity="10",
        table_identity="10. 金融投资",
        unit="百万元",
        boundary=_verified_boundary(
            3,
            next_note_ordinal="11",
            next_note_title="下一附注",
        ),
        candidate_namespace="TCAND_CL23_SIGNATURE",
    )


def _verified_boundary(
    next_note_page: int,
    *,
    next_note_ordinal: str,
    next_note_title: str,
) -> dict:
    heading = f"{next_note_ordinal}. {next_note_title}"
    return {
        "boundary_reason": "next_note_ordinal",
        "boundary_confidence": "HIGH",
        "boundary_evidence": {
            "method": "NEXT_NOTE_ORDINAL",
            "next_note_verified": True,
            "next_note_reference": f"附注{next_note_ordinal}",
            "next_note_ordinal": next_note_ordinal,
            "next_note_title": next_note_title,
            "next_note_heading_raw": heading,
            "next_note_pdf_page_index": next_note_page,
            "next_note_y0": 40.0,
            "next_note_bbox": {
                "x0": 40.0,
                "y0": 40.0,
                "x1": 280.0,
                "y1": 52.0,
            },
        },
    }


def _all_keys(value) -> set[str]:
    if isinstance(value, dict):
        return set(value) | {
            nested
            for item in value.values()
            for nested in _all_keys(item)
        }
    if isinstance(value, list):
        return {
            nested
            for item in value
            for nested in _all_keys(item)
        }
    return set()


def test_planner_builds_complete_multi_table_inventory_without_amounts() -> None:
    lines_by_page, page_widths = _two_table_pages()

    first = spatial.plan_table_structure_candidates(
        lines_by_page,
        page_widths,
        start_page=193,
        end_page=194,
        title_bbox=[40.0, 10.0, 280.0, 25.0],
        note_identity="12",
        table_identity="12. 债权投资",
        unit="百万元",
        boundary=_verified_boundary(
            195,
            next_note_ordinal="13",
            next_note_title="其他债权投资",
        ),
        candidate_namespace="TCAND_XINHUA_2024",
    )
    second = spatial.plan_table_structure_candidates(
        lines_by_page,
        page_widths,
        start_page=193,
        end_page=194,
        title_bbox=[40.0, 10.0, 280.0, 25.0],
        note_identity="12",
        table_identity="12. 债权投资",
        unit="百万元",
        boundary=_verified_boundary(
            195,
            next_note_ordinal="13",
            next_note_title="其他债权投资",
        ),
        candidate_namespace="TCAND_XINHUA_2024",
    )

    assert first["inventory_status"] == "COMPLETE"
    assert [
        item["classification"] for item in first["logical_table_candidates"]
    ] == ["PRIMARY_TABLE", "SUPPLEMENTARY_TABLE", "SUPPLEMENTARY_TABLE"]
    assert [item["classification"] for item in first["segment_candidates"]] == [
        "PRIMARY_TABLE",
        "SUPPLEMENTARY_TABLE",
        "SUPPLEMENTARY_TABLE",
    ]
    boundary_evidence = first["boundary_evidence"]
    assert boundary_evidence["peer_classification"] == "PEER_TABLE"
    assert boundary_evidence["next_note_reference"] == "附注13"
    assert boundary_evidence["next_note_ordinal"] == "13"
    assert boundary_evidence["next_note_title"] == "其他债权投资"
    assert boundary_evidence["next_note_heading_raw"] == "13. 其他债权投资"
    assert boundary_evidence["next_note_pdf_page_index"] == 195
    assert boundary_evidence["next_note_bbox"] == {
        "page": 195,
        "x0": 40.0,
        "y0": 40.0,
        "x1": 280.0,
        "y1": 52.0,
    }
    assert boundary_evidence["next_note_bbox_source"] == "BOUNDARY_EVIDENCE_BBOX"
    assert all(
        item["classification"] != "PEER_TABLE"
        for item in first["logical_table_candidates"]
    )
    assert all(
        item["classification"] != "PEER_TABLE"
        for item in first["segment_candidates"]
    )
    assert first["inventory_id"] == second["inventory_id"]
    assert [
        item["logical_table_candidate_id"]
        for item in first["logical_table_candidates"]
    ] == [
        item["logical_table_candidate_id"]
        for item in second["logical_table_candidates"]
    ]
    assert [
        item["segment_candidate_id"] for item in first["segment_candidates"]
    ] == [
        item["segment_candidate_id"] for item in second["segment_candidates"]
    ]
    assert {
        "sample",
        "value",
        "parsed_number",
        "value_yuan",
        "raw_numeric_tokens",
        "amount_summary",
    }.isdisjoint(_all_keys(first))
    serialized = json.dumps(first, ensure_ascii=False)
    assert "246,842" not in serialized
    assert "313,148" not in serialized
    assert "1,980" not in serialized


def test_same_page_period_blocks_remain_one_supplementary_table() -> None:
    lines_by_page, page_widths = _same_page_two_period_supplementary()

    result = spatial.plan_table_structure_candidates(
        lines_by_page,
        page_widths,
        start_page=196,
        end_page=197,
        title_bbox=[40.0, 10.0, 280.0, 25.0],
        note_identity="14",
        table_identity="14. 其他债权投资",
        unit="百万元",
        boundary=_verified_boundary(
            198,
            next_note_ordinal="15",
            next_note_title="其他权益工具投资",
        ),
        candidate_namespace="TCAND_XINHUA_2025_P197",
    )

    assert result["inventory_status"] == "COMPLETE"
    assert [
        item["classification"] for item in result["logical_table_candidates"]
    ] == ["PRIMARY_TABLE", "SUPPLEMENTARY_TABLE"]
    assert [
        item["classification"] for item in result["segment_candidates"]
    ] == ["PRIMARY_TABLE", "SUPPLEMENTARY_TABLE"]
    supplementary = result["segment_candidates"][1]
    assert supplementary["start_page"] == 197
    assert supplementary["end_page"] == 197
    assert supplementary["period_signature"]["period_labels"] == ["2025", "2024"]
    assert supplementary["continuation_of_segment_candidate_id"] is None


def test_horizontal_period_header_keeps_both_periods_and_local_bbox() -> None:
    result = _plan_cl23_supplementary(_cl23_horizontal_period_page())

    assert result["inventory_status"] == "COMPLETE"
    supplementary = result["segment_candidates"][1]
    assert supplementary["classification"] == "SUPPLEMENTARY_TABLE"
    assert supplementary["period_signature"]["period_labels"] == [
        "2023",
        "2022",
    ]
    assert supplementary["bbox"]["y0"] == 140.0
    assert supplementary["header_signature"]["labels"] == [
        "2023年12月31日",
        "2022年12月31日",
    ]
    assert all(
        supplementary["evidence"]["signature_coverage"][key] is True
        for key in ("page_bbox", "period", "header", "amount_lanes")
    )


@pytest.mark.parametrize("combined_header", [False, True])
def test_vertical_period_blocks_keep_physical_order_without_page_header(
    combined_header: bool,
) -> None:
    result = _plan_cl23_supplementary(
        _cl23_vertical_period_page(combined_header=combined_header)
    )

    assert result["inventory_status"] == "COMPLETE"
    supplementary = result["segment_candidates"][1]
    assert supplementary["classification"] == "SUPPLEMENTARY_TABLE"
    assert supplementary["period_signature"]["period_labels"] == [
        "2023",
        "2022",
    ]
    assert supplementary["bbox"]["y0"] == 120.0
    assert "2023年度财务报表附注" not in " | ".join(
        supplementary["header_signature"]["labels"]
    )
    assert supplementary["evidence"]["signature_coverage"] == {
        "page_bbox": True,
        "period": True,
        "header": True,
        "amount_lanes": True,
        "source": "BOUNDED_NATIVE_TEXT",
    }


def test_incomplete_vertical_period_block_fails_inventory_closed() -> None:
    page_two = _cl23_vertical_period_page(combined_header=False)
    page_two[-2] = _amount_row(
        330.0,
        "成本",
        [470.0, 610.0],
        ["856", "886"],
    )
    page_two[-1] = _amount_row(
        355.0,
        "公允价值",
        [470.0, 610.0],
        ["879", "841"],
    )

    result = _plan_cl23_supplementary(page_two)

    assert result["inventory_status"] == "INCOMPLETE"
    supplementary = result["segment_candidates"][1]
    assert supplementary["status"] == "REVIEW_REQUIRED"
    assert supplementary["evidence"]["signature_coverage"]["period"] is False
    assert "PERIOD_AXIS_BLOCK_INCOMPLETE" in result["issue_codes"]


@pytest.mark.skipif(not CL23_PDF.exists(), reason="CL23 canonical PDF unavailable")
@pytest.mark.parametrize(
    (
        "start_page",
        "end_page",
        "title",
        "note_identity",
        "end_y",
        "expected_y0",
    ),
    [
        (174, 175, "8. 贷款", "8", 407.719, 227.698),
        (176, 177, "10. 可供出售金融资产", "10", 390.406, 126.056),
        (177, 178, "11. 持有至到期投资", "11", 791.939, 157.936),
    ],
)
def test_cl23_real_supplementary_signature_canary(
    start_page: int,
    end_page: int,
    title: str,
    note_identity: str,
    end_y: float,
    expected_y0: float,
) -> None:
    doc = spatial.fitz.open(CL23_PDF)
    try:
        lines_by_page = {
            page: spatial._page_lines(doc, page)
            for page in range(start_page, end_page + 1)
        }
        page_widths = {
            page: float(doc[page - 1].rect.width)
            for page in range(start_page, end_page + 1)
        }
        title_line = next(
            line
            for line in lines_by_page[start_page]
            if title.replace(" ", "") in spatial._line_compact(line["text"])
        )
        boundary = _verified_boundary(
            end_page,
            next_note_ordinal=str(int(note_identity) + 1),
            next_note_title="下一附注",
        )
        boundary["end_y"] = end_y
        result = spatial.plan_table_structure_candidates(
            lines_by_page,
            page_widths,
            start_page=start_page,
            end_page=end_page,
            title_bbox={
                key: float(title_line[key])
                for key in ("x0", "y0", "x1", "y1")
            },
            note_identity=note_identity,
            table_identity=title,
            unit="百万元",
            boundary=boundary,
            candidate_namespace=f"CL23_REAL_{note_identity}",
        )
    finally:
        doc.close()

    assert result["inventory_status"] == "COMPLETE"
    supplementary = next(
        item
        for item in result["segment_candidates"]
        if item["classification"] == "SUPPLEMENTARY_TABLE"
        and item["start_page"] == end_page
    )
    assert supplementary["period_signature"]["period_labels"] == [
        "2023",
        "2022",
    ]
    assert supplementary["bbox"]["y0"] == pytest.approx(expected_y0, abs=0.01)
    assert "2023年度财务报表附注" not in " | ".join(
        supplementary["header_signature"]["labels"]
    )
    assert supplementary["evidence"]["signature_coverage"] == {
        "page_bbox": True,
        "period": True,
        "header": True,
        "amount_lanes": True,
        "source": "BOUNDED_NATIVE_TEXT",
    }
    if note_identity == "10":
        assert supplementary["header_signature"]["labels"] == [
            "以公允价值计量 | 债权型投资",
            "以公允价值计量 | 股权型投资",
            "以成本计量 | 股权型投资",
        ]


def test_planner_links_a_structurally_matching_continuation() -> None:
    lines_by_page, page_widths = _continuation_pages()

    inventory = spatial.plan_table_structure_candidates(
        lines_by_page,
        page_widths,
        start_page=1,
        end_page=2,
        title_bbox=[40.0, 10.0, 280.0, 25.0],
        note_identity="10",
        table_identity="10. 债权投资",
        unit="百万元",
        boundary=_verified_boundary(
            3,
            next_note_ordinal="11",
            next_note_title="其他债权投资",
        ),
        candidate_namespace="TCAND_CONTINUATION",
    )

    assert inventory["inventory_status"] == "COMPLETE"
    assert len(inventory["logical_table_candidates"]) == 1
    assert [item["classification"] for item in inventory["segment_candidates"]] == [
        "PRIMARY_TABLE",
        "CONTINUATION_SEGMENT",
    ]
    assert inventory["segment_candidates"][1][
        "continuation_of_segment_candidate_id"
    ] == inventory["segment_candidates"][0]["segment_candidate_id"]


def test_planner_fails_closed_when_header_or_boundary_is_unresolved() -> None:
    centers = [560.0, 700.0]
    lines = {
        1: [
            _amount_row(80.0, "政府债", centers, ["246,842", "260,108"]),
            _amount_row(105.0, "金融债", centers, ["3,851", "3,724"]),
        ],
    }

    inventory = spatial.plan_table_structure_candidates(
        lines,
        {1: PAGE_WIDTH},
        start_page=1,
        end_page=1,
        title_bbox=[40.0, 10.0, 280.0, 25.0],
        note_identity="10",
        table_identity="10. 债权投资",
        candidate_namespace="TCAND_UNRESOLVED",
    )

    assert inventory["inventory_status"] == "INCOMPLETE"
    assert inventory["boundary_status"] == "UNRESOLVED"
    assert inventory["logical_table_candidates"][0]["classification"] == "UNRESOLVED"
    assert inventory["segment_candidates"][0]["status"] == "REVIEW_REQUIRED"
    assert "HEADER_TOPOLOGY_UNRESOLVED" in inventory["issue_codes"]


def test_native_line_planner_does_not_open_pdf_or_call_capture(monkeypatch) -> None:
    lines_by_page, page_widths = _continuation_pages()

    def forbidden(*_args, **_kwargs):
        raise AssertionError("FORBIDDEN_CAPTURE_OR_PDF_OPEN")

    monkeypatch.setattr(spatial.fitz, "open", forbidden)
    monkeypatch.setattr(spatial, "capture_named_table_spatial", forbidden)

    inventory = spatial.plan_table_structure_candidates(
        lines_by_page,
        page_widths,
        start_page=1,
        end_page=2,
        title_bbox=[40.0, 10.0, 280.0, 25.0],
        note_identity="10",
        table_identity="10. 债权投资",
        boundary=_verified_boundary(
            3,
            next_note_ordinal="11",
            next_note_title="其他债权投资",
        ),
    )

    assert inventory["inventory_status"] == "COMPLETE"
