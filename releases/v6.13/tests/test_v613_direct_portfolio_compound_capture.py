from __future__ import annotations

from copy import deepcopy

from compound_note_engine import (
    _axis_assignments,
    _assert_direct_numeric_row_conservation,
    _normalise_certified_direct_logical_axis_rows,
    coalesce_certified_physical_table_blocks,
)
from investment_portfolio_axis_semantics import (
    BY_ACCOUNTING_MEASUREMENT,
    BY_INVESTMENT_OBJECT,
    UNRESOLVED_AXIS_BOUNDARY,
    recognise_portfolio_axis_boundary,
)
from spatial_table_capture import (
    LogicalRowCandidate,
    _apply_certified_context_to_metadata,
    _arbitrate_with_certified_context,
    _certified_header,
    _direct_portfolio_column_context,
    _header_metadata,
    _is_valid_suffix_candidate,
    _parse_period_token,
    _resolve_anchor_prefix_candidates,
    _single_row_period_lane_assignment,
)
from table_capture import (
    TableCell,
    TableColumn,
    TableRow,
    analyze_column_dimensions,
)


def _row(label: str, *, total: bool = False) -> TableRow:
    return TableRow(
        row_order=0,
        page=48,
        block_id="PHYSICAL_SEGMENT",
        source_method="NATIVE_TEXT",
        raw_item=label,
        normalized_item=label,
        canonical_item=None,
        mapping_status="RAW",
        row_type="TOTAL" if total else "DETAIL",
        row_level=0,
        parent_section=None,
        cells=[TableCell(0, 1, "1,000", 1000.0, "RMB_MILLION", None)],
        header_source_page=48,
        row_role="TOTAL" if total else "DETAIL",
        bbox={"x0": 80, "y0": 200, "x1": 520, "y1": 210},
        physical_segment_id="PHYSICAL_SEGMENT",
    )


def _five_lane_certified_context() -> dict:
    return {
        "lane_count": 5,
        "anchors": [280.0, 340.0, 400.0, 460.0, 520.0],
        "period_labels": ["2024年", "2024年", "2023年", "2023年", "2024年较2023年"],
        "period_kinds": ["ABSOLUTE_YEAR"] * 4 + ["PERIOD_CHANGE"],
        "year_labels": ["2024", "2024", "2023", "2023", None],
        "measure_labels": ["金额", "占比", "金额", "占比", "金额增减变动"],
        "measure_kinds": ["AMOUNT", "PERCENTAGE", "AMOUNT", "PERCENTAGE", "CHANGE_RATE"],
        "header_y0": 170.0,
        "header_y1": 208.0,
        "numeric_clusters": {"centers": [280.0, 340.0, 400.0, 460.0, 520.0]},
        "column_topology_contract_version": 2,
    }


def test_certified_context_only_wins_auto_arbitration_on_lane_conflict() -> None:
    context = _five_lane_certified_context()
    ordinary = {"parser": "GENERALIZED_HEADER", "anchors": [340.0, 460.0]}
    arbitration = {
        "selected_parser": "GENERALIZED_HEADER",
        "auto_selected_parser": "GENERALIZED_HEADER",
        "candidates": {"GENERALIZED_HEADER": {"leaf_count": 2}},
    }
    selected, evidence = _arbitrate_with_certified_context(
        ordinary, arbitration, context
    )
    assert selected["parser"] == "CERTIFIED_COLUMN_CONTEXT"
    assert len(selected["anchors"]) == 5
    assert evidence["selection_reason"] == (
        "CERTIFIED_CONTEXT_RESOLVES_LANE_COUNT_CONFLICT"
    )

    matching = {"parser": "GENERALIZED_HEADER", "anchors": list(context["anchors"])}
    selected, evidence = _arbitrate_with_certified_context(
        matching, arbitration, context
    )
    assert selected is matching
    assert evidence["selected_parser"] == "GENERALIZED_HEADER"
    assert evidence["certified_context_status"] == "LANE_COUNT_MATCH"
    assert "CERTIFIED_COLUMN_CONTEXT" in evidence["candidates"]


def test_period_change_is_a_complete_unique_column_dimension() -> None:
    columns = [
        TableColumn(0, 1, "2024年 | 金额", "2024", None, False, "2024年", "金额", "ABSOLUTE_YEAR"),
        TableColumn(1, 2, "2024年 | 占比", "2024", None, False, "2024年", "占比", "ABSOLUTE_YEAR"),
        TableColumn(2, 3, "2023年 | 金额", "2023", None, False, "2023年", "金额", "ABSOLUTE_YEAR"),
        TableColumn(3, 4, "2023年 | 占比", "2023", None, False, "2023年", "占比", "ABSOLUTE_YEAR"),
        TableColumn(4, 5, "2024年较2023年 | 金额增减变动", None, None, False, "2024年较2023年", "金额增减变动", "PERIOD_CHANGE"),
    ]
    assert analyze_column_dimensions(columns)["status"] == "AUTO_CONFIRMED"

    duplicate = list(columns) + [
        TableColumn(5, 6, "重复", None, None, False, "2024年较2023年", "金额增减变动", "PERIOD_CHANGE")
    ]
    check = analyze_column_dimensions(duplicate)
    assert check["status"] == "REVIEW_REQUIRED"
    assert any(issue["issue"] == "HEADER_DIMENSION_COLLISION" for issue in check["issues"])


def test_portfolio_axis_transition_materialises_numeric_prefix_summary() -> None:
    rows = [
        _row("投资资产（合计）", total=True),
        _row("按投资对象分现金、现金等价物"),
        _row("债权类金融资产"),
        _row("按会计核算方法分类以摊余成本计量的金融资产"),
        _row("以公允价值计量且其变动计入当期损益的金融资产"),
    ]
    assert _axis_assignments(rows) == [
        "PORTFOLIO_SUMMARY",
        "BY_INVESTMENT_OBJECT",
        "BY_INVESTMENT_OBJECT",
        "BY_ACCOUNTING_MEASUREMENT",
        "BY_ACCOUNTING_MEASUREMENT",
    ]


def test_direct_portfolio_four_lane_context_requires_certified_roi_and_periods() -> None:
    period_words = []
    for x, value in ((365, "2023年12月31日"), (487, "2022年12月31日")):
        period_words.append({
            "text": value, "x0": x - 45, "x1": x + 45,
            "xc": x, "y0": 170, "y1": 178, "yc": 174,
        })
    period_line = {
        "text": "2023年12月31日 2022年12月31日",
        "words": period_words, "y0": 170, "y1": 178,
    }
    measure_words = [{
        "text": "投资资产类别", "x0": 50, "x1": 150,
        "xc": 100, "y0": 190, "y1": 198, "yc": 194,
    }]
    for x, value in zip((330, 398, 458, 516), ("金额", "占比", "金额", "占比")):
        measure_words.append({
            "text": value, "x0": x - 12, "x1": x + 12,
            "xc": x, "y0": 190, "y1": 198, "yc": 194,
        })
    measure_line = {
        "text": "投资资产类别 金额 占比 金额 占比",
        "words": measure_words, "y0": 190, "y1": 198,
    }
    lines = [period_line, measure_line]
    for y, values in enumerate((
        ("2,250,073", "100.0", "2,021,933", "100.0"),
        ("1,676,100", "74.5", "1,396,316", "69.1"),
        ("325,234", "14.5", "299,942", "14.8"),
    ), start=220):
        words = []
        for x, value in zip((330, 398, 458, 516), values):
            words.append({
                "text": value, "x0": x - 10, "x1": x + 10,
                "xc": x, "y0": y, "y1": y + 8, "yc": y + 4,
            })
        lines.append({"text": " ".join(values), "words": words, "y0": y, "y1": y + 8})
    segment = {
        "certification_status": "CERTIFIED",
        "start_page": 48,
        "classification": "PRIMARY_TABLE",
        "bbox": {"x0": 24, "y0": 150, "x1": 595, "y1": 510},
        "evidence": {
            "strategy": "DIRECT_PORTFOLIO_TABLES",
            "period_labels": ["2023年末", "2023年初"],
        },
    }
    context = _direct_portfolio_column_context(
        [segment], page_number=48, lines=lines, page_width=595.0
    )
    assert context is not None
    assert context["lane_count"] == 4
    assert context["measure_labels"] == ["金额", "占比", "金额", "占比"]
    assert context["period_labels"] == [
        "2023年12月31日", "2023年12月31日",
        "2022年12月31日", "2022年12月31日",
    ]
    assert context["header_y0"] == 170
    assert context["header_y1"] == 198
    assert context["data_y_min"] == 198
    assert context["header_geometry_source"] == (
        "DIRECT_PORTFOLIO_PHYSICAL_COLUMN_TOPOLOGY_V4"
    )
    assert context["column_topology_contract_version"] == 4
    assert context["lane_group_ids"] == [
        "PERIOD_GROUP_1", "PERIOD_GROUP_1",
        "PERIOD_GROUP_2", "PERIOD_GROUP_2",
    ]
    assert context["period_mapping_evidence"]["mapping_mode"] == (
        "MULTIROW_CONTIGUOUS_COLUMN_GROUP"
    )
    header, _arbitration = _certified_header(context)
    _metadata, header_bottom = _header_metadata(lines, header, 595.0)
    assert header_bottom == 198
    assert measure_line["y1"] < header_bottom + 2
    assert lines[2]["y1"] >= header_bottom + 2
    missing_periods = deepcopy(segment)
    missing_periods["evidence"].pop("period_labels")
    assert _direct_portfolio_column_context(
        [missing_periods], page_number=48, lines=lines, page_width=595.0
    ) is None


def test_split_date_words_are_consumed_before_measure_recognition() -> None:
    period_line = {
        "text": "2023 年12月31日 2022 年12月31日",
        "words": [
            {"text": "2023", "x0": 320, "x1": 340, "xc": 330,
             "y0": 170, "y1": 178, "yc": 174},
            {"text": "年12月31日", "x0": 341, "x1": 410, "xc": 375.5,
             "y0": 170, "y1": 178, "yc": 174},
            {"text": "2022", "x0": 442, "x1": 462, "xc": 452,
             "y0": 170, "y1": 178, "yc": 174},
            {"text": "年12月31日", "x0": 463, "x1": 532, "xc": 497.5,
             "y0": 170, "y1": 178, "yc": 174},
        ],
        "y0": 170,
        "y1": 178,
    }
    measure_line = {
        "text": "金额 占比 金额 占比",
        "words": [
            {"text": value, "x0": x - 12, "x1": x + 12, "xc": x,
             "y0": 190, "y1": 198, "yc": 194}
            for x, value in zip((330, 398, 458, 516), ("金额", "占比", "金额", "占比"))
        ],
        "y0": 190,
        "y1": 198,
    }
    body = []
    for y, values in zip(
        (220, 240, 260),
        (("100", "40%", "80", "35%"),
         ("120", "45%", "90", "40%"),
         ("140", "50%", "100", "45%")),
    ):
        body.append({
            "text": " ".join(values),
            "words": [
                {"text": value, "x0": x - 10, "x1": x + 10, "xc": x,
                 "y0": y, "y1": y + 8, "yc": y + 4}
                for x, value in zip((330, 398, 458, 516), values)
            ],
            "y0": y,
            "y1": y + 8,
        })
    segment = {
        "certification_status": "CERTIFIED",
        "start_page": 48,
        "classification": "PRIMARY_TABLE",
        "bbox": {"x0": 24, "y0": 150, "x1": 595, "y1": 510},
        "evidence": {
            "strategy": "DIRECT_PORTFOLIO_TABLES",
            "period_labels": ["2023年末", "2023年初"],
        },
    }

    context = _direct_portfolio_column_context(
        [segment],
        page_number=48,
        lines=[period_line, measure_line, *body],
        page_width=595.0,
    )

    assert context is not None
    assert context["measure_labels"] == ["金额", "占比", "金额", "占比"]
    assert [
        group["consumed_spans"][0]["word_indices"]
        for group in context["period_groups"]
    ] == [[0, 1], [2, 3]]
    assert all(
        "12月31日" not in label for label in context["measure_labels"]
    )


def test_four_word_native_dates_do_not_leak_month_day_into_measure() -> None:
    period_line = {
        "text": "2024年12月31日 占比(%) 2023年12月31日 占比(%)",
        "words": [],
        "y0": 170,
        "y1": 180,
    }
    for offset, token in enumerate(("2024", "年12", "月31", "日")):
        x0 = 246 + offset * 20
        period_line["words"].append({
            "text": token, "x0": x0, "x1": x0 + 18, "xc": x0 + 9,
            "y0": 170, "y1": 180, "yc": 175,
        })
    period_line["words"].append({
        "text": "占比(%)", "x0": 348, "x1": 378, "xc": 363,
        "y0": 170, "y1": 180, "yc": 175,
    })
    for offset, token in enumerate(("2023", "年12", "月31", "日")):
        x0 = 388 + offset * 20
        period_line["words"].append({
            "text": token, "x0": x0, "x1": x0 + 18, "xc": x0 + 9,
            "y0": 170, "y1": 180, "yc": 175,
        })
    period_line["words"].append({
        "text": "占比(%)", "x0": 490, "x1": 520, "xc": 505,
        "y0": 170, "y1": 180, "yc": 175,
    })
    body = [
        {
            "text": "100 40% 80 35%",
            "words": [
                {"text": value, "x0": x - 10, "x1": x + 10, "xc": x,
                 "y0": y, "y1": y + 8, "yc": y + 4}
                for x, value in zip((300, 363, 442, 505), values)
            ],
            "y0": y,
            "y1": y + 8,
        }
        for y, values in (
            (220, ("100", "40%", "80", "35%")),
            (240, ("120", "45%", "90", "40%")),
            (260, ("140", "50%", "100", "45%")),
        )
    ]
    segment = {
        "certification_status": "CERTIFIED",
        "start_page": 48,
        "classification": "PRIMARY_TABLE",
        "bbox": {"x0": 24, "y0": 150, "x1": 595, "y1": 510},
        "evidence": {
            "strategy": "DIRECT_PORTFOLIO_TABLES",
            "period_labels": ["2024年12月31日", "2023年12月31日"],
        },
    }

    context = _direct_portfolio_column_context(
        [segment], page_number=48, lines=[period_line, *body], page_width=595.0
    )

    assert context is not None
    assert context["period_labels"] == [
        "2024年12月31日", "2024年12月31日",
        "2023年12月31日", "2023年12月31日",
    ]
    assert context["measure_labels"] == ["金额", "占比(%)", "金额", "占比(%)"]
    assert [
        group["consumed_spans"][0]["word_indices"]
        for group in context["period_groups"]
    ] == [[0, 1, 2, 3], [5, 6, 7, 8]]


def test_v3_certified_context_replaces_native_date_fragment_measure() -> None:
    context = {
        "lane_count": 4,
        "period_labels": ["2024年12月31日"] * 2 + ["2023年12月31日"] * 2,
        "period_kinds": ["ABSOLUTE_YEAR"] * 4,
        "year_labels": ["2024", "2024", "2023", "2023"],
        "measure_labels": ["金额", "占比(%)", "金额", "占比(%)"],
        "column_topology_contract_version": 3,
    }
    metadata = [
        {"year": "2024", "period_label": "2024", "period_kind": "ABSOLUTE_YEAR",
         "scope": None, "restated": False, "measure": "月31", "tokens": ["2024", "月31"]},
        {"year": "2024", "period_label": "2024", "period_kind": "ABSOLUTE_YEAR",
         "scope": None, "restated": False, "measure": "占比(%)", "tokens": ["2024", "占比(%)"]},
        {"year": "2023", "period_label": "2023", "period_kind": "ABSOLUTE_YEAR",
         "scope": None, "restated": False, "measure": "月31", "tokens": ["2023", "月31"]},
        {"year": "2023", "period_label": "2023", "period_kind": "ABSOLUTE_YEAR",
         "scope": None, "restated": False, "measure": "占比(%)", "tokens": ["2023", "占比(%)"]},
    ]

    _apply_certified_context_to_metadata(metadata, context)

    assert [item["measure"] for item in metadata] == [
        "金额", "占比(%)", "金额", "占比(%)",
    ]
    assert all("月31" not in item["tokens"] for item in metadata)


def test_period_headers_accept_terminal_numeric_footnote_markers() -> None:
    current = _parse_period_token("2023年12月31日1")
    comparative = _parse_period_token("2022年(1)")

    assert current is not None
    assert current["period_label"] == "2023年12月31日"
    assert current["token"] == "2023年12月31日1"
    assert comparative is not None
    assert comparative["period_label"] == "2022"
    assert comparative["token"] == "2022年(1)"
    assert _parse_period_token("2024年12") is None


def test_native_period_headers_override_conflicting_stage_a_labels() -> None:
    period_line = {
        "text": "2024年12月31日 2023年12月31日1",
        "words": [
            {"text": "2024年12月31日", "x0": 300, "x1": 380, "xc": 340,
             "y0": 170, "y1": 178, "yc": 174},
            {"text": "2023年12月31日1", "x0": 430, "x1": 520, "xc": 475,
             "y0": 170, "y1": 178, "yc": 174},
        ],
        "y0": 170,
        "y1": 178,
    }
    measure_line = {
        "text": "金额 占比 金额 占比",
        "words": [
            {"text": value, "x0": x - 12, "x1": x + 12, "xc": x,
             "y0": 190, "y1": 198, "yc": 194}
            for x, value in zip(
                (320, 390, 455, 520),
                ("金额", "占比", "金额", "占比"),
            )
        ],
        "y0": 190,
        "y1": 198,
    }
    body = [
        {
            "text": " ".join(values),
            "words": [
                {"text": value, "x0": x - 10, "x1": x + 10, "xc": x,
                 "y0": y, "y1": y + 8, "yc": y + 4}
                for x, value in zip((320, 390, 455, 520), values)
            ],
            "y0": y,
            "y1": y + 8,
        }
        for y, values in (
            (220, ("100", "40%", "80", "35%")),
            (240, ("120", "45%", "90", "40%")),
            (260, ("140", "50%", "100", "45%")),
        )
    ]
    segment = {
        "certification_status": "CERTIFIED",
        "start_page": 20,
        "classification": "PRIMARY_TABLE",
        "bbox": {"x0": 24, "y0": 150, "x1": 595, "y1": 510},
        "evidence": {
            "strategy": "DIRECT_PORTFOLIO_TABLES",
            "period_labels": ["2024年", "2024年12月31日"],
        },
    }

    context = _direct_portfolio_column_context(
        [segment],
        page_number=20,
        lines=[period_line, measure_line, *body],
        page_width=595.0,
    )

    assert context is not None
    assert context["period_labels"] == [
        "2024年12月31日", "2024年12月31日",
        "2023年12月31日", "2023年12月31日",
    ]
    resolution = context["period_label_resolution_evidence"]
    assert resolution["period_label_source"] == "BOUNDED_NATIVE_PHYSICAL_HEADER"
    assert resolution["physical_override_count"] == 1
    assert resolution["comparisons"][1]["resolution"] == (
        "PHYSICAL_LABEL_OVERRIDES_CERTIFIED_HINT"
    )


def test_same_row_periods_use_left_preference_for_leaf_groups() -> None:
    header_line = {
        "text": "2024年 金额 占比 2023年 金额 占比",
        "words": [
            {"text": "2024年", "x0": 220, "x1": 260, "xc": 240,
             "y0": 170, "y1": 178, "yc": 174},
            {"text": "金额", "x0": 270, "x1": 294, "xc": 282,
             "y0": 170, "y1": 178, "yc": 174},
            {"text": "占比", "x0": 310, "x1": 334, "xc": 322,
             "y0": 170, "y1": 178, "yc": 174},
            {"text": "2023年", "x0": 350, "x1": 390, "xc": 370,
             "y0": 170, "y1": 178, "yc": 174},
            {"text": "金额", "x0": 400, "x1": 424, "xc": 412,
             "y0": 170, "y1": 178, "yc": 174},
            {"text": "占比", "x0": 440, "x1": 464, "xc": 452,
             "y0": 170, "y1": 178, "yc": 174},
        ],
        "y0": 170,
        "y1": 178,
    }
    body = []
    for y, values in zip(
        (210, 230, 250),
        (("100", "40%", "80", "35%"),
         ("120", "45%", "90", "40%"),
         ("140", "50%", "100", "45%")),
    ):
        body.append({
            "text": " ".join(values),
            "words": [
                {"text": value, "x0": x - 10, "x1": x + 10, "xc": x,
                 "y0": y, "y1": y + 8, "yc": y + 4}
                for x, value in zip((282, 322, 412, 452), values)
            ],
            "y0": y,
            "y1": y + 8,
        })
    segment = {
        "certification_status": "CERTIFIED",
        "start_page": 10,
        "classification": "PRIMARY_TABLE",
        "bbox": {"x0": 24, "y0": 150, "x1": 595, "y1": 510},
        "evidence": {
            "strategy": "DIRECT_PORTFOLIO_TABLES",
            "period_labels": ["2024年", "2023年"],
        },
    }

    context = _direct_portfolio_column_context(
        [segment],
        page_number=10,
        lines=[header_line, *body],
        page_width=595.0,
    )

    assert context is not None
    assert context["period_labels"] == [
        "2024", "2024", "2023", "2023",
    ]
    assert context["period_mapping_evidence"]["mapping_mode"] == (
        "SAME_ROW_LEFT_PREFERRED_RIGHT_PENALISED"
    )


def test_same_row_period_parent_on_right_remains_penalised_fallback() -> None:
    assignment, evidence = _single_row_period_lane_assignment(
        [{"x0": 160, "x1": 200, "xc": 180}],
        [120.0],
        [{"x0": 108, "x1": 132, "y0": 10, "y1": 18}],
        [0],
        page_width=595.0,
    )

    assert assignment == {0: 0}
    assert evidence["direction_by_lane"] == {"0": "RIGHT_PENALISED"}


def test_direct_portfolio_context_does_not_invent_missing_measure_geometry() -> None:
    period_line = {
        "text": "2023年12月31日 2022年12月31日",
        "words": [
            {"text": "2023年12月31日", "x0": 320, "x1": 410,
             "xc": 365, "y0": 170, "y1": 178, "yc": 174},
            {"text": "2022年12月31日", "x0": 442, "x1": 532,
             "xc": 487, "y0": 170, "y1": 178, "yc": 174},
        ],
        "y0": 170,
        "y1": 178,
    }
    body_lines = []
    for y, values in enumerate((
        ("2,250,073", "100.0", "2,021,933", "100.0"),
        ("1,676,100", "74.5", "1,396,316", "69.1"),
        ("325,234", "14.5", "299,942", "14.8"),
    ), start=220):
        words = [
            {"text": value, "x0": x - 10, "x1": x + 10,
             "xc": x, "y0": y, "y1": y + 8, "yc": y + 4}
            for x, value in zip((330, 398, 458, 516), values)
        ]
        body_lines.append({
            "text": " ".join(values), "words": words,
            "y0": y, "y1": y + 8,
        })
    segment = {
        "certification_status": "CERTIFIED",
        "start_page": 48,
        "classification": "PRIMARY_TABLE",
        "bbox": {"x0": 24, "y0": 150, "x1": 595, "y1": 510},
        "evidence": {
            "strategy": "DIRECT_PORTFOLIO_TABLES",
            "period_labels": ["2023年末", "2023年初"],
        },
    }

    assert _direct_portfolio_column_context(
        [segment],
        page_number=48,
        lines=[period_line, *body_lines],
        page_width=595.0,
    ) is None


def test_direct_portfolio_five_lane_context_preserves_period_change_column() -> None:
    centers = (280, 340, 400, 460, 520)
    period_line = {
        "text": "2024年 2023年",
        "words": [
            {"text": "2024年", "x0": 290, "x1": 330,
             "xc": 310, "y0": 170, "y1": 178, "yc": 174},
            {"text": "2023年", "x0": 410, "x1": 450,
             "xc": 430, "y0": 170, "y1": 178, "yc": 174},
        ],
        "y0": 170,
        "y1": 178,
    }
    first_header = {
        "text": "金额 占比 金额 占比 金额",
        "words": [
            {"text": text, "x0": x - 12, "x1": x + 12,
             "xc": x, "y0": 190, "y1": 198, "yc": 194}
            for x, text in zip(centers, ("金额", "占比", "金额", "占比", "金额"))
        ],
        "y0": 190,
        "y1": 198,
    }
    change_header = {
        "text": "增减变动",
        "words": [{
            "text": "增减变动", "x0": 495, "x1": 545,
            "xc": 520, "y0": 200, "y1": 208, "yc": 204,
        }],
        "y0": 200,
        "y1": 208,
    }
    lines = [period_line, first_header, change_header]
    for y, values in enumerate((
        ("100", "40%", "80", "35%", "25%"),
        ("120", "45%", "90", "40%", "33%"),
        ("140", "50%", "100", "45%", "40%"),
    ), start=230):
        words = [
            {"text": value, "x0": x - 10, "x1": x + 10,
             "xc": x, "y0": y, "y1": y + 8, "yc": y + 4}
            for x, value in zip(centers, values)
        ]
        lines.append({
            "text": " ".join(values), "words": words,
            "y0": y, "y1": y + 8,
        })
    segment = {
        "certification_status": "CERTIFIED",
        "start_page": 34,
        "classification": "PRIMARY_TABLE",
        "bbox": {"x0": 24, "y0": 150, "x1": 595, "y1": 510},
        "evidence": {
            "strategy": "DIRECT_PORTFOLIO_TABLES",
            "period_labels": ["2024年", "2023年"],
        },
    }

    context = _direct_portfolio_column_context(
        [segment], page_number=34, lines=lines, page_width=595.0
    )

    assert context is not None
    assert context["lane_count"] == 5
    assert context["measure_labels"] == [
        "金额", "占比", "金额", "占比", "金额增减变动"
    ]
    assert context["period_labels"] == [
        "2024", "2024", "2023", "2023", "2024较2023"
    ]
    assert context["period_kinds"][-1] == "PERIOD_CHANGE"
    header, _arbitration = _certified_header(context)
    assert header["years"][-1] is None
    assert header["period_kinds"][-1] == "PERIOD_CHANGE"
    assert header["header_y1"] == 208


def test_compound_direct_preserves_two_logical_blocks() -> None:
    class _Block:
        def __init__(self, axis: str):
            self.classification_axis = axis
            self.evidence = {}
            self.physical_segment_ids = ["PHYSICAL_SEGMENT"]

    blocks = [_Block("BY_INVESTMENT_OBJECT"), _Block("BY_ACCOUNTING_MEASUREMENT")]
    preserved = coalesce_certified_physical_table_blocks(
        result=object(),
        container=object(),
        blocks=blocks,
        physical_asset_id="PHYS_1",
        title="投资组合",
        classification_axis="BY_INVESTMENT_OBJECT",
        preserve_logical_axes=True,
    )
    assert preserved is blocks
    assert [row.classification_axis for row in preserved] == [
        "BY_INVESTMENT_OBJECT", "BY_ACCOUNTING_MEASUREMENT"
    ]
    assert all(row.evidence["physical_asset_id"] == "PHYS_1" for row in preserved)


def test_direct_logical_axis_rows_remove_heading_and_join_single_continuation() -> None:
    heading = _row("按投资对象分类")
    heading.cells = []
    heading.row_type = heading.row_role = "SECTION_HEADER"
    heading.bbox = {"x0": 100, "y0": 100, "x1": 200, "y1": 110}
    cash = _row("现金")
    cash.bbox = {"x0": 100, "y0": 112, "x1": 500, "y1": 122}
    assert [row.raw_item for row in _normalise_certified_direct_logical_axis_rows(
        "按投资对象分类", [_row("投资资产"), heading, cash]
    )] == ["投资资产", "现金"]

    first = _row("按会计核算方法分类以公允价值计量")
    wrapped = _row("以摊余成本计量的金")
    wrapped.cells = []
    wrapped.row_type = wrapped.row_role = "SECTION_HEADER"
    wrapped.bbox = {"x0": 100, "y0": 130, "x1": 220, "y1": 140}
    continuation = _row("融资产")
    continuation.bbox = {"x0": 110, "y0": 141, "x1": 500, "y1": 151}
    next_row = _row("长期股权投资")
    next_row.bbox = {"x0": 100, "y0": 152, "x1": 500, "y1": 162}
    normalized = _normalise_certified_direct_logical_axis_rows(
        "按会计核算方法分类", [first, wrapped, continuation, next_row]
    )
    assert [row.row_item_raw or row.raw_item for row in normalized] == [
        "以公允价值计量", "以摊余成本计量的金融资产", "长期股权投资"
    ]
    assert normalized[1].raw_item == "融资产"

    numeric_first = _row("以公允价值计量且其变动计入其他综合收益的")
    numeric_first.bbox = {"x0": 100, "y0": 160, "x1": 500, "y1": 172}
    trailing = _row("金融资产注5")
    trailing.cells = []
    trailing.bbox = {"x0": 100, "y0": 173, "x1": 180, "y1": 183}
    trailing.row_type = trailing.row_role = "DETAIL"
    normalized = _normalise_certified_direct_logical_axis_rows(
        "按会计核算方法分类",
        [numeric_first, trailing, _row("长期股权投资")],
        "BY_ACCOUNTING_MEASUREMENT",
    )
    assert [row.row_item_raw or row.raw_item for row in normalized] == [
        "以公允价值计量且其变动计入其他综合收益的金融资产注5",
        "长期股权投资",
    ]
    assert normalized[0].raw_item == "以公允价值计量且其变动计入其他综合收益的"
    assert normalized[0].label_derivation == "PHYSICAL_TRAILING_LABEL_CONTINUATION_JOIN"

    group = _row("金融投资")
    group.cells = []
    group.row_type = group.row_role = "SECTION_HEADER"
    group.bbox = {"x0": 100, "y0": 170, "x1": 180, "y1": 180}
    child_a = _row("债券")
    child_a.bbox = {"x0": 110, "y0": 181, "x1": 500, "y1": 191}
    child_b = _row("股票")
    child_b.bbox = {"x0": 110, "y0": 192, "x1": 500, "y1": 202}
    preserved_group = _normalise_certified_direct_logical_axis_rows(
        "按投资对象分类", [group, child_a, child_b]
    )
    assert [row.raw_item for row in preserved_group] == ["金融投资", "债券", "股票"]


def test_numeric_only_anchor_uses_label_region_for_wrapped_prefix_and_suffix() -> None:
    prefix = {
        "text": "以公允价值计量且其变动计入其他综合收益的",
        "x0": 94.95,
        "x1": 237.74,
        "y0": 454.10,
        "y1": 462.38,
        "page": 50,
        "block_id": "SEGMENT",
    }
    numeric_line = {"x0": 285.42, "x1": 518.74, "y0": 458.08, "y1": 466.49}
    parsed_numeric = {
        "label": "",
        "raw_label": "",
        "label_x0": 285.42,
        "has_numeric": True,
    }
    selected, remaining = _resolve_anchor_prefix_candidates(
        [prefix],
        numeric_line,
        parsed_numeric,
        [prefix, numeric_line],
        1,
        page_no=50,
        active_block_id="SEGMENT",
        anchors=[303.60, 372.11, 445.08, 513.76],
        page_width=595.28,
        numeric_anchors=[303.60, 372.11, 445.08, 513.76],
    )

    assert selected == [prefix]
    assert remaining == []

    candidate = LogicalRowCandidate(
        prefix_fragments=selected,
        anchor_fragment={"label": "", "x0": 285.42},
        parsed_line=parsed_numeric,
        line=numeric_line,
        active_block_id="SEGMENT",
        page_no=50,
    )
    suffix_line = {"x0": 102.10, "x1": 137.98, "y0": 462.50, "y1": 470.78}
    assert _is_valid_suffix_candidate(
        candidate,
        suffix_line,
        {"label": "金融资产注5", "label_x0": 102.10, "has_numeric": False},
        page_no=50,
        active_block_id="SEGMENT",
        page_width=595.28,
    )


def test_direct_logical_axis_rows_use_certified_axis_when_display_title_differs() -> None:
    physical_title = _row("投资资产")
    axis_heading = _row("按投资对象分类")
    axis_heading.cells = []
    axis_heading.row_type = axis_heading.row_role = "SECTION_HEADER"
    cash = _row("现金及现金等价物")
    category_rows = _normalise_certified_direct_logical_axis_rows(
        "投资组合（按投资对象）",
        [physical_title, axis_heading, cash],
        "BY_INVESTMENT_OBJECT",
    )
    # A numeric source row is never deleted by title cleanup.  In the complete
    # segmentation path it belongs to PORTFOLIO_SUMMARY before this function.
    assert [row.raw_item for row in category_rows] == [
        "投资资产", "现金及现金等价物"
    ]


def test_portfolio_axis_semantics_known_and_unresolved_boundaries() -> None:
    assert recognise_portfolio_axis_boundary("按投资资产类别列示").classification_axis == BY_INVESTMENT_OBJECT
    assert recognise_portfolio_axis_boundary("按计量属性构成").classification_axis == BY_ACCOUNTING_MEASUREMENT
    unresolved = recognise_portfolio_axis_boundary("按地区分类")
    assert unresolved.classification_axis == UNRESOLVED_AXIS_BOUNDARY
    assert unresolved.unresolved is True


def test_unresolved_axis_boundary_with_numeric_rows_is_preserved_for_review() -> None:
    heading = _row("按地区分类")
    heading.cells = []
    heading.row_type = heading.row_role = "SECTION_HEADER"
    assert _axis_assignments([heading, _row("境内投资")]) == [
        "UNRESOLVED", "UNRESOLVED"
    ]


def test_portfolio_summary_is_conditional_and_drops_only_structural_rows() -> None:
    title = _row("投资组合情况")
    title.cells = []
    title.row_type = title.row_role = "SECTION_HEADER"
    summary = _row("投资资产")
    heading = _row("按投资对象分类")
    heading.cells = []
    heading.row_type = heading.row_role = "SECTION_HEADER"
    cash = _row("现金")
    assignments = _axis_assignments([title, summary, heading, cash])
    assert assignments == [
        "PORTFOLIO_SUMMARY", "PORTFOLIO_SUMMARY",
        "BY_INVESTMENT_OBJECT", "BY_INVESTMENT_OBJECT",
    ]
    normalised = _normalise_certified_direct_logical_axis_rows(
        "投资组合（总览）", [title, summary], "PORTFOLIO_SUMMARY"
    )
    assert [row.raw_item for row in normalised] == ["投资资产"]


def test_no_numeric_prefix_does_not_materialise_summary() -> None:
    heading = _row("按投资对象划分")
    heading.cells = []
    heading.row_type = heading.row_role = "SECTION_HEADER"
    assert _axis_assignments([heading, _row("现金")]) == [
        "BY_INVESTMENT_OBJECT", "BY_INVESTMENT_OBJECT"
    ]


def test_axis_heading_with_numeric_row_keeps_values_and_strips_prefix() -> None:
    glued = _row("按投资类别分类现金及现金等价物")
    rows = _normalise_certified_direct_logical_axis_rows(
        "投资组合（按投资对象）", [glued], "BY_INVESTMENT_OBJECT"
    )
    assert rows[0].raw_item == "按投资类别分类现金及现金等价物"
    assert rows[0].row_item_raw == "现金及现金等价物"
    assert rows[0].normalized_item == "现金及现金等价物"


def test_direct_numeric_row_conservation_fails_on_loss_or_duplicate() -> None:
    class _Block:
        def __init__(self, rows):
            self.rows = rows

    source = _row("投资资产")
    try:
        _assert_direct_numeric_row_conservation([_Block([source])], [_Block([])])
    except ValueError as exc:
        assert "DIRECT_LOGICAL_AXIS_NUMERIC_ROW_CONSERVATION_FAILED" in str(exc)
    else:
        raise AssertionError("numeric loss must fail closed")
    try:
        _assert_direct_numeric_row_conservation(
            [_Block([source])], [_Block([deepcopy(source), deepcopy(source)])]
        )
    except ValueError as exc:
        assert "DIRECT_LOGICAL_AXIS_NUMERIC_ROW_CONSERVATION_FAILED" in str(exc)
    else:
        raise AssertionError("numeric duplicate must fail closed")

    prefixed = _row(
        "按会计核算方法分类"
        "以公允价值计量且其变动计入当期损益的金融资产"
    )
    measurement_rows = _normalise_certified_direct_logical_axis_rows(
        "投资组合（按会计计量）",
        [prefixed],
        "BY_ACCOUNTING_MEASUREMENT",
    )
    assert [row.row_item_raw for row in measurement_rows] == [
        "以公允价值计量且其变动计入当期损益的金融资产"
    ]
    assert measurement_rows[0].raw_item.startswith("按会计核算方法分类")
