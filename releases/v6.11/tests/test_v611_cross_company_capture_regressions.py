from __future__ import annotations

from pathlib import Path
import sys
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from compound_note_engine import (
    _block_terminal_type,
    _declared_source_column_ordinals,
    _reconciliation,
    materialize_block_result,
    segment_table_blocks,
)
from header_review import _result_dataclass
from services.capture_decision_reducer import CaptureDecisionReducer
from spatial_table_capture import (
    _arbitrate_header_candidates,
    _classic_absolute_year_words,
    _detect_stacked_period_measure_sections,
    _mark_report_footer_noise,
    _active_vertical_section,
    _vertical_period_plan,
    _vertical_sections_for_page,
    capture_named_table_spatial,
)
from table_boundary_resolver import BoundaryReason, resolve_table_boundary
from table_capture import TableCell, TableRow, analyze_column_dimensions


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


def _stacked_measure_lines() -> list[dict]:
    lines = []
    for section, year in enumerate(("2023", "2022")):
        base = 20.0 + section * 120.0
        lines.append(_line(base, [
            _word(407.0, 476.0, f"{year}年12月31日", base),
            _word(493.0, 561.0, f"{year}年12月31日", base),
        ]))
        lines.append(_line(base + 15.0, [
            _word(440.0, 476.0, "摊余成本", base + 15.0),
            _word(525.0, 561.0, "公允价值", base + 15.0),
        ]))
        for offset, label in enumerate(("国债", "政府机构债券", "企业债券")):
            row_y = base + 50.0 + offset * 15.0
            lines.append(_line(row_y, [
                _word(72.0, 126.0, label, row_y),
                _word(443.0, 476.0, f"{314057 + offset:,}", row_y),
                _word(528.0, 561.0, f"{359637 + offset:,}", row_y),
            ]))
        total_y = base + 98.0
        lines.append(_line(total_y, [
            _word(62.0, 81.0, "合计", total_y),
            _word(435.0, 476.0, "1,706,441", total_y),
            _word(520.0, 561.0, "1,901,726", total_y),
        ]))
    return lines


def test_year_qualified_next_note_is_not_rejected_as_amount_row() -> None:
    boundary = resolve_table_boundary(
        note_reference="附注十-11",
        title="债权投资",
        start_page=1,
        start_y=20.0,
        title_x0=40.0,
        page_count=1,
        page_height=lambda _page: 800.0,
        page_lines=lambda _page: [{
            "text": "12. 其他债权投资（仅适用2023年）",
            "x0": 40.0,
            "y0": 300.0,
            "words": [
                {"text": "12."},
                {"text": "其他债权投资（仅适用"},
                {"text": "2023年）"},
            ],
        }],
    )
    assert boundary["boundary_reason"] == BoundaryReason.NEXT_NOTE_ORDINAL.value
    assert boundary["boundary_evidence"]["next_note_ordinal"] == 12


def test_ageing_row_with_multiple_numbers_is_not_a_peer_heading() -> None:
    boundary = resolve_table_boundary(
        note_reference="2",
        title="应收款项",
        start_page=1,
        start_y=20.0,
        title_x0=40.0,
        page_count=1,
        page_height=lambda _page: 800.0,
        page_lines=lambda _page: [{
            "text": "3个月至1年 1,000 2,000",
            "x0": 40.0,
            "y0": 300.0,
            "words": [
                {"text": "3个月至1年"},
                {"text": "1,000"},
                {"text": "2,000"},
            ],
        }],
    )
    assert boundary["boundary_reason"] == BoundaryReason.SAME_PAGE_FOOTER_FALLBACK.value


def test_ageing_row_with_placeholders_is_not_a_peer_heading() -> None:
    boundary = resolve_table_boundary(
        note_reference="2",
        title="应收款项",
        start_page=1,
        start_y=20.0,
        title_x0=40.0,
        page_count=1,
        page_height=lambda _page: 800.0,
        page_lines=lambda _page: [{
            "text": "3个月至1年 — —",
            "x0": 40.0,
            "y0": 300.0,
            "words": [
                {"text": "3个月至1年"},
                {"text": "—"},
                {"text": "—"},
            ],
        }],
    )
    assert boundary["boundary_reason"] == BoundaryReason.SAME_PAGE_FOOTER_FALLBACK.value


def test_boundary_lookahead_does_not_expand_capture_roi() -> None:
    boundary = resolve_table_boundary(
        note_reference="10",
        title="债权投资",
        start_page=1,
        start_y=20.0,
        title_x0=40.0,
        page_count=2,
        page_height=lambda _page: 800.0,
        page_lines=lambda page: ([{
            "text": "11. 其他债权投资",
            "x0": 40.0,
            "y0": 150.0,
            "words": [{"text": "11."}, {"text": "其他债权投资"}],
        }] if page == 2 else []),
        max_pages=1,
        lookahead_pages=1,
    )
    assert boundary["boundary_reason"] == BoundaryReason.NEXT_NOTE_ORDINAL.value
    assert boundary["end_page"] == 1
    assert boundary["end_y"] == 770.0
    assert boundary["boundary_evidence"]["next_note_pdf_page_index"] == 2
    assert boundary["boundary_evidence"]["next_note_outside_capture_roi"] is True


def test_boundary_lookahead_with_continuation_prefix_does_not_hard_confirm() -> None:
    boundary = resolve_table_boundary(
        note_reference="10",
        title="债权投资",
        start_page=1,
        start_y=20.0,
        title_x0=40.0,
        page_count=2,
        page_height=lambda _page: 800.0,
        page_lines=lambda page: ([
            {
                "text": "续表项目 100 200",
                "x0": 40.0,
                "y0": 80.0,
                "words": [
                    {"text": "续表项目"},
                    {"text": "100"},
                    {"text": "200"},
                ],
            },
            {
                "text": "11. 其他债权投资",
                "x0": 40.0,
                "y0": 150.0,
                "words": [{"text": "11."}, {"text": "其他债权投资"}],
            },
        ] if page == 2 else []),
        max_pages=1,
        lookahead_pages=1,
    )
    assert boundary["boundary_reason"] == BoundaryReason.SAME_PAGE_FOOTER_FALLBACK.value
    rejection = boundary["boundary_evidence"]["lookahead_rejection"]
    assert rejection["reason"] == "LOOKAHEAD_PREFIX_CONTAINS_TABLE_OR_BODY_CONTENT"


def test_duplicate_year_words_remain_two_measure_columns() -> None:
    lines = _stacked_measure_lines()
    assert len(_classic_absolute_year_words(lines[0])) == 2
    header, arbitration = _arbitrate_header_candidates(lines, 600.0)
    selected = arbitration["candidates"][arbitration["selected_parser"]]
    assert selected["leaf_count"] == 2
    assert selected["numeric_cluster_count"] == 2
    assert header["measure_labels"] == ["摊余成本", "公允价值"]


def test_stacked_period_measure_sections_are_distinct() -> None:
    sections = _detect_stacked_period_measure_sections(
        _stacked_measure_lines(),
        600.0,
    )
    assert len(sections) == 2
    assert [section["years"][0] for section in sections] == ["2023", "2022"]
    assert all(section["measure_labels"] == ["摊余成本", "公允价值"] for section in sections)


def test_vertical_period_plan_reuses_second_period_on_continuation_page() -> None:
    first_page = _stacked_measure_lines()
    second_page = _stacked_measure_lines()[6:]
    groups, occurrences = _vertical_period_plan(
        {1: first_page, 2: second_page},
        {1: 600.0, 2: 600.0},
    )
    assert [group["column_offset"] for group in groups] == [0, 2]
    assert len(occurrences[2]) == 1
    assert occurrences[2][0]["column_offset"] == 2
    assert occurrences[2][0]["block_id"] == groups[1]["block_id"]

    page_sections = _vertical_sections_for_page(
        groups,
        occurrences,
        page_no=2,
        page_width=600.0,
        active_section_index=1,
    )
    before_header = _active_vertical_section(page_sections, 10.0)
    after_header = _active_vertical_section(page_sections, 200.0)
    assert before_header is not None
    assert after_header is not None
    assert before_header["column_offset"] == 2
    assert after_header["column_offset"] == 2
    assert before_header["block_id"] == after_header["block_id"]


def test_vertical_period_plan_detects_new_period_first_seen_next_page() -> None:
    first_period = _stacked_measure_lines()[:6]
    second_period = _stacked_measure_lines()[6:]
    groups, occurrences = _vertical_period_plan(
        {1: first_period, 2: second_period},
        {1: 600.0, 2: 600.0},
    )
    assert [group["period_labels"][0] for group in groups] == ["2023", "2022"]
    assert [group["column_offset"] for group in groups] == [0, 2]

    page_sections = _vertical_sections_for_page(
        groups,
        occurrences,
        page_no=2,
        page_width=600.0,
        active_section_index=0,
    )
    before_new_header = _active_vertical_section(page_sections, 10.0)
    after_new_header = _active_vertical_section(page_sections, 200.0)
    assert before_new_header is not None
    assert after_new_header is not None
    assert before_new_header["column_offset"] == 0
    assert after_new_header["column_offset"] == 2


def test_measure_is_part_of_unique_column_dimension() -> None:
    result = analyze_column_dimensions([
        {"ordinal": 0, "year": "2023", "scope": None, "restated": False, "measure": "摊余成本"},
        {"ordinal": 1, "year": "2023", "scope": None, "restated": False, "measure": "公允价值"},
    ])
    assert result["status"] == "AUTO_CONFIRMED"


def test_full_report_footer_is_retained_but_excluded() -> None:
    footer = TableRow(
        row_order=2,
        page=174,
        block_id="spatial_p174",
        source_method="spatial_roi+text_only_detail",
        raw_item="172二零二三年年报|财务报告",
        normalized_item="172二零二三年年报|财务报告",
        canonical_item=None,
        mapping_status="UNMAPPED",
        row_type="DETAIL",
        row_level=0,
        parent_section=None,
        cells=[],
        header_source_page=None,
    )
    body = TableRow(
        row_order=1,
        page=174,
        block_id="spatial_p174",
        source_method="spatial_roi+text_only_detail",
        raw_item="年报相关投资说明",
        normalized_item="年报相关投资说明",
        canonical_item=None,
        mapping_status="UNMAPPED",
        row_type="DETAIL",
        row_level=0,
        parent_section=None,
        cells=[],
        header_source_page=None,
    )
    _mark_report_footer_noise([body, footer])
    assert body.excluded_from_table_logic is False
    assert footer.excluded_from_table_logic is True
    assert footer.row_role == "PAGE_FOOTER_NOISE"


def test_excluded_footer_does_not_downgrade_final_total() -> None:
    total = TableRow(
        row_order=1,
        page=1,
        block_id="B1",
        source_method="fixture",
        raw_item="合计",
        normalized_item="合计",
        canonical_item=None,
        mapping_status="UNMAPPED",
        row_type="TOTAL",
        row_level=0,
        parent_section=None,
        cells=[TableCell(0, 1, "10", 10.0, None, None)],
        header_source_page=None,
        row_role="TOTAL",
    )
    footer = TableRow(
        row_order=2,
        page=1,
        block_id="B1",
        source_method="fixture",
        raw_item="172二零二三年年报|财务报告",
        normalized_item="172二零二三年年报|财务报告",
        canonical_item=None,
        mapping_status="UNMAPPED",
        row_type="PAGE_FOOTER_NOISE",
        row_level=0,
        parent_section=None,
        cells=[],
        header_source_page=None,
        row_role="PAGE_FOOTER_NOISE",
        excluded_from_table_logic=True,
    )
    assert _block_terminal_type([total, footer], is_final_block=True) == "FINAL_TOTAL"


def test_vertical_group_keeps_declared_blank_measure_column() -> None:
    result = SimpleNamespace(stats={
        "vertical_period_column_groups": [{
            "block_id": "B2022",
            "source_column_ordinals": [2, 3],
        }],
    })
    rows = [TableRow(
        row_order=1,
        page=2,
        block_id="B2022",
        source_method="fixture",
        raw_item="企业债",
        normalized_item="企业债",
        canonical_item=None,
        mapping_status="UNMAPPED",
        row_type="DETAIL",
        row_level=0,
        parent_section=None,
        cells=[TableCell(2, 3, "10", 10.0, None, None)],
        header_source_page=1,
    )]
    assert _declared_source_column_ordinals(result, rows) == [2, 3]


def test_header_review_round_trip_preserves_measure_noise_and_audit_fields() -> None:
    rebuilt = _result_dataclass(
        {
            "pdf_name": "fixture.pdf",
            "pdf_sha256": "sha",
            "table_query": "测试表",
            "start_page": 1,
            "end_page": 1,
            "pages": [1],
            "columns": [{
                "ordinal": 0,
                "source_column_index": 1,
                "header_raw": "2023 | 公允价值",
                "year": "2023",
                "period_label": "2023",
                "measure": "公允价值",
                "restated": False,
            }],
            "rows": [{
                "row_order": 1,
                "page": 1,
                "block_id": "B1",
                "raw_item": "172二零二三年年报|财务报告",
                "row_type": "PAGE_FOOTER_NOISE",
                "row_role": "PAGE_FOOTER_NOISE",
                "excluded_from_table_logic": True,
                "cells": [],
            }],
            "document_context": {"currency": "CNY"},
            "boundary_status_source": "MACHINE_DERIVED",
        },
        [{
            "ordinal": 0,
            "source_column_index": 1,
            "header_raw": "2023 | 公允价值",
            "year": "2023",
            "period_label": "2023",
            "measure": "公允价值",
            "restated": False,
        }],
    )
    assert rebuilt.columns[0].measure == "公允价值"
    assert rebuilt.rows[0].excluded_from_table_logic is True
    assert rebuilt.document_context == {"currency": "CNY"}
    assert rebuilt.boundary_status_source == "MACHINE_DERIVED"


def test_reconciliation_aligns_cells_by_column_ordinal() -> None:
    rows = [
        TableRow(
            row_order=1,
            page=1,
            block_id="B1",
            source_method="fixture",
            raw_item="明细",
            normalized_item="明细",
            canonical_item=None,
            mapping_status="UNMAPPED",
            row_type="DETAIL",
            row_level=0,
            parent_section=None,
            cells=[
                TableCell(1, 2, "30", 30.0, None, None),
                TableCell(0, 1, "4", 4.0, None, None),
            ],
            header_source_page=None,
        ),
        TableRow(
            row_order=2,
            page=1,
            block_id="B1",
            source_method="fixture",
            raw_item="合计",
            normalized_item="合计",
            canonical_item=None,
            mapping_status="UNMAPPED",
            row_type="TOTAL",
            row_level=0,
            parent_section=None,
            cells=[
                TableCell(0, 1, "4", 4.0, None, None),
                TableCell(1, 2, "30", 30.0, None, None),
            ],
            header_source_page=None,
            row_role="TOTAL",
        ),
    ]
    reconciliation = _reconciliation(rows)
    assert reconciliation["status"] == "PASS"
    assert [check["column"] for check in reconciliation["checks"]] == [0, 1]


def test_reducer_blocks_selected_header_undersegmentation() -> None:
    blocking, _warnings = CaptureDecisionReducer()._derive_issue_codes(
        evidence={
            "stats": {
                "header_arbitration": {
                    "selected_parser": "ABSOLUTE_YEAR_CLASSIC",
                    "candidates": {
                        "ABSOLUTE_YEAR_CLASSIC": {
                            "leaf_count": 1,
                            "numeric_cluster_count": 2,
                        }
                    },
                }
            }
        },
        boundary_status="HARD_BOUNDARY_CONFIRMED",
        header_status="AUTO_CONFIRMED",
        rows=[],
        cv={
            "research_definition_id": "DEF",
            "definition_version": "1",
            "table_family_id": "financial_investment",
            "statement_scope": "CONSOLIDATED",
            "is_current": True,
            "pdf_id": "PDF",
        },
        lifecycle={"registration_status": "REGISTERED", "asset_status": "ACTIVE"},
        implicit_unresolved=0,
        mixed_cells=0,
        topology_ready=True,
        reconciliation_ready=True,
    )
    assert "HEADER_TOPOLOGY_AMBIGUOUS" in blocking


CHINA_LIFE_2023 = Path(r"C:\dev\AXA_research\docu\中国人寿2023年年度报告.pdf")
PINGAN_2023 = Path(r"C:\dev\AXA_research\docu\中国平安2023年报.pdf")
CPIC_2023 = Path(r"C:\dev\AXA_research\docu\中国太保2023年报.pdf")
XINHUA_2023 = Path(r"C:\dev\AXA_research\docu\新华保险2023年报.pdf")
XINHUA_2024 = Path(r"C:\dev\AXA_research\docu\新华保险2024年报.pdf")
XINHUA_2025 = Path(r"C:\dev\AXA_research\docu\新华保险2025年报.pdf")


@pytest.mark.parametrize(
    ("pdf_path", "table_query", "note_number", "start_page", "chrome_page", "printed_page"),
    [
        (XINHUA_2023, "12 债权投资", "12", 188, 189, "187"),
        (XINHUA_2024, "11 交易性金融资产", "11", 192, 193, "191"),
        (XINHUA_2024, "14 其他权益工具投资", "14", 196, 197, "195"),
    ],
)
def test_real_xinhua_running_header_is_excluded_before_amount_parsing(
    pdf_path: Path,
    table_query: str,
    note_number: str,
    start_page: int,
    chrome_page: int,
    printed_page: str,
) -> None:
    if not pdf_path.exists():
        pytest.skip("真实新华 PDF 不可用")
    result = capture_named_table_spatial(
        pdf_path,
        table_query,
        note_number=note_number,
        start_page_override=start_page,
        max_pages=8,
        strict_target_identity=True,
        certified_target_heading=table_query,
    )
    chrome_rows = [
        row for row in result.rows
        if row.page == chrome_page
        and printed_page in str(row.raw_item or "")
        and ("年度报告" in str(row.raw_item or "") or "年度報告" in str(row.raw_item or ""))
    ]
    assert chrome_rows
    assert all(row.excluded_from_table_logic for row in chrome_rows)
    assert all(row.row_role == "PAGE_HEADER_NOISE" for row in chrome_rows)


@pytest.mark.parametrize(
    ("table_query", "note_number", "page_number", "expected_header_y0"),
    [
        ("12 债权投资", "12", 188, 473.012),
        ("13 其他债权投资", "13", 189, 524.838),
    ],
)
@pytest.mark.skipif(not XINHUA_2023.exists(), reason="真实新华2023 PDF 不可用")
def test_real_xinhua_2023_ecl_group_header_is_preserved(
    table_query: str,
    note_number: str,
    page_number: int,
    expected_header_y0: float,
) -> None:
    result = capture_named_table_spatial(
        XINHUA_2023,
        table_query,
        note_number=note_number,
        start_page_override=page_number,
        max_pages=1,
        strict_target_identity=True,
        certified_target_heading=table_query,
    )
    supplementary_segment = next(
        segment
        for segment in result.stats["physical_table_segments"]
        if segment["classification"] == "SUPPLEMENTARY_TABLE"
    )
    _container, blocks = segment_table_blocks(result)
    supplementary_block = next(
        block
        for block in blocks
        if len(block.header_topology.get("header_labels") or []) == 4
    )
    child = materialize_block_result(result, supplementary_block)

    assert supplementary_segment["bbox"][1] == pytest.approx(
        expected_header_y0,
        abs=0.01,
    )
    assert [column.measure for column in child.columns] == [
        "第一阶段 | (12个月预期 | 信用损失）",
        "第二阶段 | （整个存续期 | 预期信用损失）",
        "第三阶段 | （整个存续期 | 预期信用 | 损失－已减值）",
        "合计",
    ]


@pytest.mark.skipif(not XINHUA_2025.exists(), reason="真实新华2025 PDF 不可用")
def test_real_xinhua_2025_right_aligned_amount_lane_is_retained() -> None:
    result = capture_named_table_spatial(
        XINHUA_2025,
        "其他权益工具投资",
        note_number="十五",
        start_page_override=198,
        max_pages=1,
        strict_target_identity=True,
        certified_target_heading="其他权益工具投资",
    )
    rows = [
        row for row in result.rows
        if row.normalized_item == "未上市股权"
    ]
    assert len(rows) == 1
    assert [(cell.raw, cell.parsed_number) for cell in rows[0].cells] == [
        ("24", 24.0),
        ("22", 22.0),
    ]
    assert result.stats["header_arbitration"]["numeric_assignment_source"] == (
        "VALIDATED_BODY_NUMERIC_CLUSTERS"
    )


@pytest.mark.skipif(not CHINA_LIFE_2023.exists(), reason="真实中国人寿2023 PDF 不可用")
def test_real_china_life_stacked_period_measure_capture() -> None:
    result = capture_named_table_spatial(
        CHINA_LIFE_2023,
        "持有至到期投资",
        note_number="11",
        start_page_override=177,
        max_pages=1,
        strict_target_identity=True,
        certified_target_heading="持有至到期投资",
    )
    assert [(column.year, column.measure) for column in result.columns] == [
        ("2023", "摊余成本"),
        ("2023", "公允价值"),
        ("2022", "摊余成本"),
        ("2022", "公允价值"),
    ]
    assert all(len(cell.raw) < 20 for row in result.rows for cell in row.cells)
    _container, blocks = segment_table_blocks(result)
    assert len(blocks) == 2
    children = [materialize_block_result(result, block) for block in blocks]
    assert [[column.year for column in child.columns] for child in children] == [
        ["2023", "2023"],
        ["2022", "2022"],
    ]
    assert all(block.header_topology["consistent"] for block in blocks)
    physical_segments = result.stats["physical_table_segments"]
    assert len(physical_segments) == 1
    physical_segment_id = physical_segments[0]["segment_id"]
    assert [block.physical_segment_ids for block in blocks] == [
        [physical_segment_id],
        [physical_segment_id],
    ]
    assert result.stats["physical_segment_block_ids"][physical_segment_id] == [
        "spatial_p177_period_1",
        "spatial_p177_period_2",
    ]
    assert all(
        row.physical_segment_id == physical_segment_id
        for row in result.rows
        if row.cells
    )


@pytest.mark.skipif(not CHINA_LIFE_2023.exists(), reason="真实中国人寿2023 PDF 不可用")
def test_real_china_life_not_applicable_fills_supplementary_amount_lane() -> None:
    result = capture_named_table_spatial(
        CHINA_LIFE_2023,
        "可供出售金融资产",
        note_number="10",
        start_page_override=176,
        max_pages=2,
        strict_target_identity=True,
        certified_target_heading="可供出售金融资产",
    )
    _container, blocks = segment_table_blocks(result)
    supplementary = next(
        block for block in blocks
        if {row.page for row in block.rows if row.cells} == {177}
    )

    assert supplementary.header_topology["expected_numeric_columns"] == 3
    assert supplementary.header_topology["occupied_slot_widths"] == [3]
    assert supplementary.header_topology["consistent"] is True
    assert "不适用" in supplementary.header_topology["placeholder_tokens"]
    assert supplementary.header_topology["unresolved_cell_count"] == 0
    child = materialize_block_result(result, supplementary)
    assert [column.measure for column in child.columns] == [
        "以公允价值计量 | 债权型投资",
        "以公允价值计量 | 股权型投资",
        "以成本计量 | 股权型投资",
    ]


@pytest.mark.skipif(not CHINA_LIFE_2023.exists(), reason="真实中国人寿2023 PDF 不可用")
def test_real_china_life_footer_does_not_create_child_block() -> None:
    result = capture_named_table_spatial(
        CHINA_LIFE_2023,
        "贷款",
        note_number="8",
        start_page_override=174,
        max_pages=1,
        strict_target_identity=True,
        certified_target_heading="贷款",
    )
    footer_rows = [row for row in result.rows if "年年报" in str(row.raw_item or "")]
    assert footer_rows
    assert all(row.excluded_from_table_logic for row in footer_rows)
    _container, blocks = segment_table_blocks(result)
    assert blocks
    assert all(any(row.cells for row in block.rows) for block in blocks)


@pytest.mark.skipif(not PINGAN_2023.exists(), reason="真实中国平安2023 PDF 不可用")
def test_real_pingan_certified_boundary_rejects_lookahead_after_continuation() -> None:
    result = capture_named_table_spatial(
        PINGAN_2023,
        "债权投资",
        note_number="10",
        start_page_override=221,
        max_pages=1,
        strict_target_identity=True,
        certified_target_heading="债权投资",
    )
    evidence = result.stats["boundary_evidence"]
    assert result.end_page == 221
    assert result.stats["boundary_reason"] == BoundaryReason.SAME_PAGE_FOOTER_FALLBACK.value
    assert evidence["lookahead_rejection"]["reason"] == "LOOKAHEAD_PREFIX_CONTAINS_TABLE_OR_BODY_CONTENT"


@pytest.mark.skipif(not CPIC_2023.exists(), reason="真实中国太保2023 PDF 不可用")
def test_real_cpic_year_qualified_next_note_stops_cross_table_capture() -> None:
    result = capture_named_table_spatial(
        CPIC_2023,
        "债权投资（仅适用2023年）",
        note_number="11",
        start_page_override=170,
        max_pages=1,
        strict_target_identity=True,
        certified_target_heading="债权投资（仅适用2023年）",
    )
    assert result.stats["boundary_reason"] == BoundaryReason.NEXT_NOTE_ORDINAL.value
    assert result.stats["boundary_evidence"]["next_note_ordinal"] == 12
    assert all(
        cell.raw != "1,186,531,148"
        for row in result.rows
        for cell in row.cells
    )
