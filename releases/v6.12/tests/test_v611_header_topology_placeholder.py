"""表头拓扑占位符对齐回归测试（中国太保“-”破折号披露写法）。

原则：破折号是“已占用的金额列占位符”，不是数值 0，也不是表头歧义证据；
只有上游确认缺失位置存在合法占位符才解除歧义，reducer 门禁不放宽。
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from compound_note_engine import _cell_state, _topology
from table_capture import TableCell, TableColumn, TableRow


def _col(ordinal: int, header_raw: str) -> TableColumn:
    return TableColumn(
        ordinal=ordinal,
        source_column_index=ordinal,
        header_raw=header_raw,
        year=header_raw,
        scope="CONSOLIDATED",
        restated=False,
        period_label=header_raw,
    )


def _cell(raw: str, ordinal: int, parsed: float | None = None) -> TableCell:
    return TableCell(
        column_ordinal=ordinal,
        source_column_index=ordinal,
        raw=raw,
        parsed_number=parsed,
        unit_original=None,
        value_yuan=None,
    )


def _row(order: int, label: str, cells: list[TableCell]) -> TableRow:
    return TableRow(
        row_order=order,
        page=156,
        block_id="BLOCK_T",
        source_method="SPATIAL",
        raw_item=label,
        normalized_item=label,
        canonical_item=None,
        mapping_status="MAPPED",
        row_type="DETAIL",
        row_level=0,
        parent_section=None,
        cells=cells,
        header_source_page=156,
    )


def _two_year_columns() -> list[TableColumn]:
    return [_col(0, "2025"), _col(1, "2024")]


# ---------------------------------------------------------------------------
# Layer 1: 单元格状态分类
# ---------------------------------------------------------------------------


def test_negative_number_is_numeric_not_placeholder() -> None:
    cell = _cell("-98,265", 0, parsed=-98265.0)
    assert _cell_state(cell) == "NUMERIC"


def test_table_rule_stroke_without_column_alignment_is_unparseable() -> None:
    # 贯穿页面的横线“———”没有列对齐，不能成为金额槽位
    cell = TableCell(
        column_ordinal=None, source_column_index=None,
        raw="———", parsed_number=None,
        unit_original=None, value_yuan=None,
    )
    assert _cell_state(cell) == "UNPARSEABLE"


def test_blank_cell_is_empty() -> None:
    cell = _cell("", 0)
    assert _cell_state(cell) == "EMPTY"


# ---------------------------------------------------------------------------
# Layer 2: 拓扑推导
# ---------------------------------------------------------------------------


def test_normal_two_year_table_consistent() -> None:
    rows = [
        _row(1, "债权投资", [_cell("100", 0, 100.0), _cell("90", 1, 90.0)]),
        _row(2, "政府债", [_cell("80", 0, 80.0), _cell("70", 1, 70.0)]),
    ]
    topo = _topology(rows, _two_year_columns())
    assert topo["expected_numeric_columns"] == 2
    assert topo["occupied_slot_widths"] == [2]
    assert topo["parsed_numeric_widths"] == [2]
    assert topo["consistent"] is True
    assert topo["candidate_types"] == ["TWO_PERIOD_COLUMNS"]
    assert topo["score"] == 1.0
    assert topo["topology_reason"] == "ALL_SLOTS_PARSED"


def test_single_side_dash_placeholder_is_consistent() -> None:
    # 企业债 | - | 98,265 —— 2025 列是合法占位符
    rows = [
        _row(1, "政府债", [_cell("250,924", 0, 250924.0), _cell("189,435", 1, 189435.0)]),
        _row(2, "企业债", [_cell("-", 0), _cell("98,265", 1, 98265.0)]),
    ]
    topo = _topology(rows, _two_year_columns())
    assert topo["expected_numeric_columns"] == 2
    assert topo["occupied_slot_widths"] == [2]
    assert topo["parsed_numeric_widths"] == [1, 2]
    assert topo["placeholder_cell_count"] == 1
    assert topo["placeholder_tokens"] == ["-"]
    assert topo["unresolved_cell_count"] == 0
    assert topo["column_alignment_consistent"] is True
    assert topo["consistent"] is True
    assert topo["candidate_types"] == ["TWO_PERIOD_COLUMNS"]
    assert topo["score"] == 0.95
    assert topo["topology_reason"] == "HEADER_ALIGNED_WITH_DISCLOSED_PLACEHOLDERS"
    # 单元格状态保留：破折号是 PLACEHOLDER，数值仍是 NUMERIC
    assert rows[1].cells[0].cell_state == "PLACEHOLDER"
    assert rows[1].cells[1].cell_state == "NUMERIC"


def test_other_side_dash_is_consistent() -> None:
    rows = [
        _row(1, "企业债", [_cell("98,265", 0, 98265.0), _cell("—", 1)]),
        _row(2, "政府债", [_cell("80", 0, 80.0), _cell("70", 1, 70.0)]),
    ]
    topo = _topology(rows, _two_year_columns())
    assert topo["occupied_slot_widths"] == [2]
    assert topo["consistent"] is True
    assert topo["placeholder_tokens"] == ["—"]


def test_two_amounts_and_not_applicable_fill_three_disclosed_slots() -> None:
    columns = [_col(0, "2025"), _col(1, "2024"), _col(2, "2023")]
    rows = [
        _row(1, "政府债", [
            _cell("100", 0, 100.0),
            _cell("90", 1, 90.0),
            _cell("不适用", 2),
        ]),
        _row(2, "企业债", [
            _cell("80", 0, 80.0),
            _cell("70", 1, 70.0),
            _cell("60", 2, 60.0),
        ]),
    ]

    topo = _topology(rows, columns)

    assert topo["occupied_slot_widths"] == [3]
    assert topo["parsed_numeric_widths"] == [2, 3]
    assert topo["placeholder_tokens"] == ["不适用"]
    assert topo["unresolved_cell_count"] == 0
    assert topo["consistent"] is True
    assert topo["topology_reason"] == "HEADER_ALIGNED_WITH_DISCLOSED_PLACEHOLDERS"
    assert rows[0].cells[2].cell_state == "PLACEHOLDER"


def test_double_dash_structure_is_consistent_semantics_deferred() -> None:
    rows = [
        _row(1, "企业债", [_cell("-", 0), _cell("-", 1)]),
        _row(2, "政府债", [_cell("80", 0, 80.0), _cell("70", 1, 70.0)]),
    ]
    topo = _topology(rows, _two_year_columns())
    assert topo["occupied_slot_widths"] == [2]
    assert topo["placeholder_cell_count"] == 2
    assert topo["consistent"] is True  # 结构明确；数值语义由披露规则另行决定


def test_genuine_missing_column_stays_ambiguous() -> None:
    # 另一列没有 token、没有 bbox、没有占位证据 —— 不能自动视为两列完整
    rows = [
        _row(1, "企业债", [_cell("98,265", 0, 98265.0)]),
        _row(2, "政府债", [_cell("80", 0, 80.0), _cell("70", 1, 70.0)]),
    ]
    topo = _topology(rows, _two_year_columns())
    assert topo["occupied_slot_widths"] == [1, 2]
    assert topo["consistent"] is False
    assert topo["candidate_types"] == ["AMBIGUOUS"]
    assert topo["topology_reason"] == "MISSING_SLOTS"


def test_sparse_x_anchor_preserves_empty_leading_period() -> None:
    rows = [
        _row(1, "信托计划", [_cell("9,688", 1, 9688.0)]),
        _row(2, "政府债", [_cell("80", 0, 80.0), _cell("70", 1, 70.0)]),
    ]
    topo = _topology(rows, _two_year_columns())
    assert topo["occupied_slot_widths"] == [2]
    assert topo["parsed_numeric_widths"] == [1, 2]
    assert topo["consistent"] is True
    assert topo["topology_reason"] == "ALL_SLOTS_PARSED"


def test_table_rule_stroke_row_keeps_table_ambiguous() -> None:
    rows = [
        _row(1, "政府债", [_cell("80", 0, 80.0), _cell("70", 1, 70.0)]),
        _row(2, "横线", [
            TableCell(
                column_ordinal=None, source_column_index=None,
                raw="———", parsed_number=None,
                unit_original=None, value_yuan=None,
            ),
        ]),
    ]
    topo = _topology(rows, _two_year_columns())
    assert topo["unresolved_cell_count"] == 1
    assert topo["consistent"] is False
    assert topo["topology_reason"] == "UNRESOLVED_CELLS"


def test_real_counter_example_multi_width_without_placeholder_is_ambiguous() -> None:
    # 真实反例：宽度不一致且无占位符证据 → 必须仍触发歧义
    rows = [
        _row(1, "A", [_cell("100", 0, 100.0), _cell("90", 1, 90.0)]),
        _row(2, "B", [_cell("80", 0, 80.0)]),
    ]
    topo = _topology(rows, _two_year_columns())
    assert topo["consistent"] is False
    assert topo["candidate_types"] == ["AMBIGUOUS"]


# ---------------------------------------------------------------------------
# Layer 3: reducer 门禁不放宽
# ---------------------------------------------------------------------------


def _reduce(evidence: dict) -> object:
    from services.capture_decision_reducer import CaptureDecisionReducer

    return CaptureDecisionReducer().reduce(
        machine_evidence=evidence,
        capture_version={},
        lifecycle_state={},
        rule_version="v6.11-test",
    )


def test_placeholder_aligned_topology_unblocks_header_review() -> None:
    rows = [
        _row(1, "政府债", [_cell("250,924", 0, 250924.0), _cell("189,435", 1, 189435.0)]),
        _row(2, "企业债", [_cell("-", 0), _cell("98,265", 1, 98265.0)]),
    ]
    topo = _topology(rows, _two_year_columns())
    evidence = {"rows": [], "columns": [], "stats": {"v69_header_topology": topo}}
    decision = _reduce(evidence)
    assert "HEADER_TOPOLOGY_AMBIGUOUS" not in decision.blocking_issues


def test_ambiguous_topology_still_blocks() -> None:
    topo = _topology(
        [_row(1, "A", [_cell("100", 0, 100.0), _cell("90", 1, 90.0)]),
         _row(2, "B", [_cell("80", 0, 80.0)])],
        _two_year_columns(),
    )
    assert topo["consistent"] is False
    evidence = {"rows": [], "columns": [], "stats": {"v69_header_topology": topo}}
    decision = _reduce(evidence)
    assert "HEADER_TOPOLOGY_AMBIGUOUS" in decision.blocking_issues


# ---------------------------------------------------------------------------
# 真实资产 Canary：太保 2025 债权投资（修复目标）与交易性金融资产（反例）
# ---------------------------------------------------------------------------


def _table_captures_root() -> Path | None:
    env_home = os.environ.get("FIN_METRIC_DATA_HOME")
    if env_home:
        root = Path(env_home) / "table_captures"
        if root.is_dir():
            return root
    root = Path(r"C:\Users\HzhJa\FinancialMetricResolverData\table_captures")
    return root if root.is_dir() else None


def _rows_from_json(rows_json: list[dict]) -> list[TableRow]:
    rows = []
    for order, r in enumerate(rows_json, start=1):
        cells = [
            TableCell(
                column_ordinal=c.get("column_ordinal"),
                source_column_index=c.get("source_column_index"),
                raw=str(c.get("raw") or ""),
                parsed_number=c.get("parsed_number"),
                unit_original=None,
                value_yuan=None,
            )
            for c in (r.get("cells") or [])
        ]
        label = str(r.get("raw_item") or r.get("row_item_raw") or "")
        rows.append(TableRow(
            row_order=order,
            page=int(r.get("page") or 0),
            block_id=str(r.get("block_id") or ""),
            source_method=str(r.get("source_method") or ""),
            raw_item=label or None,
            normalized_item=str(r.get("normalized_item") or label),
            canonical_item=r.get("canonical_item"),
            mapping_status=str(r.get("mapping_status") or ""),
            row_type=str(r.get("row_type") or "DETAIL"),
            row_level=int(r.get("row_level") or 0),
            parent_section=r.get("parent_section"),
            cells=cells,
            header_source_page=r.get("header_source_page"),
        ))
    return rows


def _columns_from_json(cols_json: list[dict]) -> list[TableColumn]:
    return [
        TableColumn(
            ordinal=int(c["ordinal"]),
            source_column_index=int(c.get("source_column_index") or c["ordinal"]),
            header_raw=str(c.get("header_raw") or ""),
            year=c.get("year"),
            scope=c.get("scope"),
            restated=bool(c.get("restated")),
            period_label=c.get("period_label"),
            measure=c.get("measure"),
        )
        for c in (cols_json or [])
    ]


def test_real_asset_cpic_2025_debt_investment_placeholder_aligned() -> None:
    root = _table_captures_root()
    if root is None:
        pytest.skip("FinancialMetricResolverData 未找到，跳过真实资产 Canary")
    path = root / "中国太保2025年报__债权投资__20260803T150547_938828" / "table_capture_result.json"
    if not path.is_file():
        pytest.skip("太保2025债权投资运行产物缺失，跳过")
    d = json.loads(path.read_text(encoding="utf-8"))
    topo = _topology(_rows_from_json(d["rows"]), _columns_from_json(d.get("columns") or []))
    assert topo["expected_numeric_columns"] == 2
    assert topo["occupied_slot_widths"] == [2]
    assert topo["parsed_numeric_widths"] == [1, 2]
    assert topo["placeholder_tokens"] == ["-"]
    assert topo["placeholder_cell_count"] == 1
    assert topo["consistent"] is True
    assert topo["topology_reason"] == "HEADER_ALIGNED_WITH_DISCLOSED_PLACEHOLDERS"


def test_real_counter_example_cpic_2025_fvtpl_stays_ambiguous() -> None:
    root = _table_captures_root()
    if root is None:
        pytest.skip("FinancialMetricResolverData 未找到，跳过真实资产 Canary")
    path = root / "中国太保2025年报__交易性金融资产__20260804T092456_946593" / "table_capture_result.json"
    if not path.is_file():
        pytest.skip("太保2025交易性金融资产运行产物缺失，跳过")
    d = json.loads(path.read_text(encoding="utf-8"))
    topo = _topology(_rows_from_json(d["rows"]), _columns_from_json(d.get("columns") or []))
    # 该表歧义来自单槽杂音行（如页码 token），无合法占位符证据 → 必须仍阻塞
    assert topo["expected_numeric_columns"] == 2
    assert topo["consistent"] is False
    assert topo["topology_reason"] == "MISSING_SLOTS"
