"""边界状态推导优先级 + BoundaryReason 契约 + 表尾页码杂音回归测试。

核心规则：人工裁决优先；机器强证据其次；复合完整性证据再次；
机器预置的 REVIEW_REQUIRED 只能作为最后兜底，不能短路更强证据。
"""
from __future__ import annotations

from pathlib import Path
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from capture_library import (
    MERGE_READY_STATUSES,
    derive_boundary_status,
)
from table_boundary_resolver import BoundaryReason, resolve_table_boundary


def _cell(raw: str, parsed: float | None = None) -> dict:
    return {"column_ordinal": 0, "raw": raw, "parsed_number": parsed}


def _row(
    label: str | None = None,
    *,
    cells: list | None = None,
    row_role: str = "DETAIL",
    row_type: str = "DETAIL",
    page: int = 1,
    bbox: dict | None = None,
    excluded: bool = False,
) -> dict:
    return {
        "row_order": 0,
        "page": page,
        "row_type": row_type,
        "row_role": row_role,
        "raw_item": label,
        "row_item_raw": label,
        "normalized_item": label or "",
        "cells": cells or [],
        "bbox": bbox,
        "excluded_from_table_logic": excluded,
    }


def _evidence(
    *,
    reason: str = BoundaryReason.NEXT_NOTE_ORDINAL.value,
    confidence: str = "HIGH",
    method: str = "NEXT_NOTE_ORDINAL",
    next_note_verified: bool = True,
    rows: list | None = None,
    end_page: int = 1,
    explicit: str = "REVIEW_REQUIRED",
    source: str = "MACHINE_DEFAULT",
    warnings: list | None = None,
) -> dict:
    return {
        "boundary_status": explicit,
        "boundary_status_source": source,
        "start_page": 1,
        "end_page": end_page,
        "rows": rows or [],
        "columns": [],
        "warnings": warnings or [],
        "stats": {
            "engine": "SPATIAL_ROI_DUAL_HEADER_V1",
            "boundary_reason": reason,
            "boundary_confidence": confidence,
            "boundary_evidence": {
                "method": method,
                "next_note_verified": next_note_verified,
            },
        },
    }


def _net_value_table() -> list[dict]:
    return [
        _row("债券", cells=[_cell("100", 100.0), _cell("90", 90.0)]),
        _row("减：减值准备", cells=[_cell("(10)", -10.0)]),
        _row("净额", cells=[_cell("90", 90.0)]),
    ]


def _total_with_noise_table() -> list[dict]:
    return [
        _row("债券", cells=[_cell("100", 100.0), _cell("90", 90.0)]),
        _row("合计", row_role="TOTAL", row_type="TOTAL",
             cells=[_cell("100", 100.0), _cell("90", 90.0)]),
        _row(None, row_role="PAGE_NUMBER_NOISE", row_type="DETAIL",
             cells=[_cell("85", None)], excluded=True,
             bbox={"x0": 290.0, "y0": 795.0, "x1": 302.0, "y1": 806.0}),
    ]


# 1. 强证据：NEXT_NOTE_ORDINAL + HIGH，末行为“净额”仍硬确认
def test_next_note_ordinal_high_with_net_value_row_hard_confirms() -> None:
    result = _evidence(rows=_net_value_table())
    assert derive_boundary_status(result) == "HARD_BOUNDARY_CONFIRMED"
    assert result["boundary_status_source"] == "MACHINE_DERIVED"


# 2. 机器默认 REVIEW_REQUIRED 可被强证据推翻
def test_machine_default_review_overridden_by_strong_evidence() -> None:
    result = _evidence(explicit="REVIEW_REQUIRED", source="MACHINE_DEFAULT")
    assert derive_boundary_status(result) == "HARD_BOUNDARY_CONFIRMED"


# 3. 人工 REVIEW_REQUIRED 不可被自动推翻
def test_human_review_required_not_overridden() -> None:
    result = _evidence(explicit="REVIEW_REQUIRED", source="HUMAN_ADJUDICATION")
    assert derive_boundary_status(result) == "REVIEW_REQUIRED"
    assert result["boundary_status_source"] == "HUMAN_ADJUDICATION"


# 4. footer fallback + 合计 + 页码杂音 → SOFT_BOUNDARY_CONFIRMED（非阻塞）
def test_footer_fallback_total_with_noise_soft_confirms() -> None:
    result = _evidence(
        reason=BoundaryReason.SAME_PAGE_FOOTER_FALLBACK.value,
        confidence="MEDIUM",
        method="SAME_PAGE_FOOTER_FALLBACK",
        next_note_verified=False,
        rows=_total_with_noise_table(),
    )
    assert derive_boundary_status(result) == "SOFT_BOUNDARY_CONFIRMED"
    assert result["boundary_status_source"] == "MACHINE_DERIVED"
    evidence = result["stats"]["boundary_evidence"]
    assert evidence["method"] == "SAME_PAGE_FOOTER_FALLBACK"  # 原始方法保留
    assert evidence["terminal_row_status"] == "CONFIRMED"
    assert evidence["continuation_status"] == "NOT_DETECTED"
    assert evidence["post_terminal_noise_only"] is True
    assert evidence["capture_completeness"] == "HIGH"
    assert evidence["confidence_basis"] == "COMPOSITE_EVIDENCE"
    assert evidence["review_required"] is False
    assert result["stats"]["boundary_confidence"] == "MEDIUM"  # 不把原始置信度改成 HIGH
    assert "SOFT_BOUNDARY_CONFIRMED" in MERGE_READY_STATUSES


# 5. footer fallback + 合计，但存在续表/续行 → 仍需审核
def test_footer_fallback_with_continuation_next_page_reviews() -> None:
    rows = _total_with_noise_table()
    rows.append(_row("续表行", cells=[_cell("1", 1.0)], page=2))
    result = _evidence(
        reason=BoundaryReason.SAME_PAGE_FOOTER_FALLBACK.value,
        confidence="MEDIUM",
        method="SAME_PAGE_FOOTER_FALLBACK",
        next_note_verified=False,
        rows=rows,
    )
    assert derive_boundary_status(result) == "REVIEW_REQUIRED"


def test_footer_fallback_with_continuation_warning_reviews() -> None:
    result = _evidence(
        reason=BoundaryReason.SAME_PAGE_FOOTER_FALLBACK.value,
        confidence="MEDIUM",
        method="SAME_PAGE_FOOTER_FALLBACK",
        next_note_verified=False,
        rows=_total_with_noise_table(),
        warnings=["跨页续表未合并"],
    )
    assert derive_boundary_status(result) == "REVIEW_REQUIRED"


# 6. 合计后出现真实第二张子表，不能当作杂音删除
def test_real_second_subtable_after_total_is_not_noise() -> None:
    rows = _total_with_noise_table()
    rows.append(
        _row("上市", cells=[_cell("60", 60.0), _cell("50", 50.0)])
    )
    result = _evidence(
        reason=BoundaryReason.SAME_PAGE_FOOTER_FALLBACK.value,
        confidence="MEDIUM",
        method="SAME_PAGE_FOOTER_FALLBACK",
        next_note_verified=False,
        rows=rows,
    )
    assert derive_boundary_status(result) == "REVIEW_REQUIRED"
    # 原始行仍保留，未被标记为排除
    assert rows[-1]["excluded_from_table_logic"] is False


# 7. 位于金额列内/表格区域的单独数字不能被识别为页码
def test_single_digit_inside_table_region_is_not_page_number() -> None:
    from table_capture import TableCell, TableRow
    from spatial_table_capture import _mark_tail_page_number_noise

    rows = [
        TableRow(
            row_order=1, page=1, block_id="B", source_method="SPATIAL",
            raw_item="合计", normalized_item="合计", canonical_item=None,
            mapping_status="MAPPED", row_type="TOTAL", row_level=0,
            parent_section=None,
            cells=[TableCell(0, 1, "100", 100.0, None, None)],
            header_source_page=1, row_role="TOTAL",
        ),
        TableRow(
            row_order=2, page=1, block_id="B", source_method="SPATIAL",
            raw_item=None, normalized_item="", canonical_item=None,
            mapping_status="", row_type="DETAIL", row_level=0,
            parent_section=None,
            cells=[TableCell(0, 1, "85", None, None, None)],
            header_source_page=1, row_role="IMPLICIT_ROW_CANDIDATE",
            bbox={"x0": 100.0, "y0": 300.0, "x1": 130.0, "y1": 320.0},
        ),
    ]
    roi = {
        "page_heights": {1: 842.0},
        "printed_page_numbers": {1: [85]},
        "amount_column_x_centers": [110.0],
    }
    _mark_tail_page_number_noise(rows, roi)
    assert rows[1].excluded_from_table_logic is False
    assert rows[1].row_role == "IMPLICIT_ROW_CANDIDATE"


def test_tail_page_number_noise_marked_and_raw_preserved() -> None:
    from table_capture import TableCell, TableRow
    from spatial_table_capture import _mark_tail_page_number_noise

    rows = [
        TableRow(
            row_order=1, page=1, block_id="B", source_method="SPATIAL",
            raw_item="合计", normalized_item="合计", canonical_item=None,
            mapping_status="MAPPED", row_type="TOTAL", row_level=0,
            parent_section=None,
            cells=[TableCell(0, 1, "100", 100.0, None, None)],
            header_source_page=1, row_role="TOTAL",
        ),
        TableRow(
            row_order=2, page=1, block_id="B", source_method="SPATIAL",
            raw_item=None, normalized_item="", canonical_item=None,
            mapping_status="", row_type="DETAIL", row_level=0,
            parent_section=None,
            cells=[TableCell(0, 1, "85", None, None, None)],
            header_source_page=1, row_role="IMPLICIT_ROW_CANDIDATE",
            bbox={"x0": 290.0, "y0": 795.0, "x1": 302.0, "y1": 806.0},
        ),
    ]
    roi = {
        "page_heights": {1: 842.0},
        "printed_page_numbers": {1: [85]},
        "amount_column_x_centers": [90.0, 350.0],
    }
    _mark_tail_page_number_noise(rows, roi)
    assert rows[1].excluded_from_table_logic is True
    assert rows[1].row_role == "PAGE_NUMBER_NOISE"
    assert rows[1].cells[0].raw == "85"  # 原始证据保留


def test_tail_digit_not_matching_printed_page_is_not_noise() -> None:
    from table_capture import TableCell, TableRow
    from spatial_table_capture import _mark_tail_page_number_noise

    rows = [
        TableRow(
            row_order=1, page=1, block_id="B", source_method="SPATIAL",
            raw_item="合计", normalized_item="合计", canonical_item=None,
            mapping_status="MAPPED", row_type="TOTAL", row_level=0,
            parent_section=None,
            cells=[TableCell(0, 1, "100", 100.0, None, None)],
            header_source_page=1, row_role="TOTAL",
        ),
        TableRow(
            row_order=2, page=1, block_id="B", source_method="SPATIAL",
            raw_item=None, normalized_item="", canonical_item=None,
            mapping_status="", row_type="DETAIL", row_level=0,
            parent_section=None,
            cells=[TableCell(0, 1, "85", None, None, None)],
            header_source_page=1, row_role="IMPLICIT_ROW_CANDIDATE",
            bbox={"x0": 290.0, "y0": 795.0, "x1": 302.0, "y1": 806.0},
        ),
    ]
    roi = {
        "page_heights": {1: 842.0},
        "printed_page_numbers": {1: [86]},  # 与印刷页码不一致
        "amount_column_x_centers": [90.0, 350.0],
    }
    _mark_tail_page_number_noise(rows, roi)
    assert rows[1].excluded_from_table_logic is False


def _xinhua_side_07_rows():
    from table_capture import TableCell, TableRow

    def make_row(order, label, cells, role="DETAIL", bbox=None):
        return TableRow(
            row_order=order, page=1, block_id="B", source_method="SPATIAL",
            raw_item=label, normalized_item=label or "", canonical_item=None,
            mapping_status="MAPPED" if label else "", row_type="DETAIL",
            row_level=0, parent_section=None, cells=cells,
            header_source_page=1, row_role=role, bbox=bbox,
        )

    return [
        make_row(1, "债券国债及政府债", [TableCell(0, 1, "740", 740.0, None, None)],
                 bbox={"x0": 99.2, "y0": 514.6, "x1": 532.9, "y1": 525.3}),
        make_row(2, None, [TableCell(0, 1, "07", None, None, None)],
                 role="IMPLICIT_ROW_CANDIDATE",
                 bbox={"x0": 573.7, "y0": 557.0, "x1": 585.1, "y1": 568.9}),
        make_row(3, "合计", [TableCell(0, 1, "380,239", 380239.0, None, None)],
                 role="TOTAL",
                 bbox={"x0": 90.7, "y0": 699.6, "x1": 532.9, "y1": 710.3}),
    ]


def test_xinhua_side_page_number_07_marked_and_raw_preserved() -> None:
    from spatial_table_capture import _mark_side_page_number_noise

    rows = _xinhua_side_07_rows()
    roi = {
        "page_widths": {1: 595.28},
        "page_heights": {1: 807.87},
        "printed_page_numbers": {1: [7]},
    }
    _mark_side_page_number_noise(rows, roi)
    assert rows[1].excluded_from_table_logic is True
    assert rows[1].row_role == "PAGE_NUMBER_NOISE"
    assert rows[1].cells[0].raw == "07"  # 原始证据保留


def test_xinhua_side_digit_not_matching_printed_page_not_noise() -> None:
    from spatial_table_capture import _mark_side_page_number_noise

    rows = _xinhua_side_07_rows()
    roi = {
        "page_widths": {1: 595.28},
        "page_heights": {1: 807.87},
        "printed_page_numbers": {1: [8]},
    }
    _mark_side_page_number_noise(rows, roi)
    assert rows[1].excluded_from_table_logic is False


def test_side_position_digit_inside_table_band_not_noise() -> None:
    from table_capture import TableCell, TableRow
    from spatial_table_capture import _mark_side_page_number_noise

    rows = _xinhua_side_07_rows()
    # 把“07”移到表格 x 带内（x0=400）
    rows[1].bbox = {"x0": 400.0, "y0": 557.0, "x1": 412.0, "y1": 568.9}
    roi = {
        "page_widths": {1: 595.28},
        "page_heights": {1: 807.87},
        "printed_page_numbers": {1: [7]},
    }
    _mark_side_page_number_noise(rows, roi)
    assert rows[1].excluded_from_table_logic is False


def test_side_marker_with_label_not_noise() -> None:
    from spatial_table_capture import _mark_side_page_number_noise

    rows = _xinhua_side_07_rows()
    rows[1].raw_item = "页码"
    rows[1].row_item_raw = "页码"
    roi = {
        "page_widths": {1: 595.28},
        "page_heights": {1: 807.87},
        "printed_page_numbers": {1: [7]},
    }
    _mark_side_page_number_noise(rows, roi)
    assert rows[1].excluded_from_table_logic is False


def test_side_marker_excluded_from_two_column_topology() -> None:
    from compound_note_engine import _topology
    from table_capture import TableColumn, TableCell, TableRow

    def row(label, cells, excluded=False, role="DETAIL", bbox=None):
        return TableRow(
            row_order=0, page=1, block_id="B", source_method="SPATIAL",
            raw_item=label, normalized_item=label or "", canonical_item=None,
            mapping_status="", row_type="DETAIL", row_level=0,
            parent_section=None, cells=cells, header_source_page=1,
            row_role=role, excluded_from_table_logic=excluded, bbox=bbox,
        )

    rows = [
        row("债券", [TableCell(0, 1, "100", 100.0, None, None),
                     TableCell(1, 2, "90", 90.0, None, None)],
            bbox={"x0": 90.0, "y0": 100.0, "x1": 500.0, "y1": 120.0}),
        row(None, [TableCell(0, 1, "07", None, None, None)],
            excluded=True, role="PAGE_NUMBER_NOISE",
            bbox={"x0": 573.0, "y0": 200.0, "x1": 585.0, "y1": 212.0}),
    ]
    cols = [TableColumn(0, 1, "2025", "2025", "CONSOLIDATED", False, "2025"),
            TableColumn(1, 2, "2024", "2024", "CONSOLIDATED", False, "2024")]
    topo = _topology(rows, cols)
    assert topo["consistent"] is True
    assert topo["occupied_slot_widths"] == [2]


# 8. 旧的 boundary_unresolved 样本仍保持阻塞
def test_legacy_boundary_unresolved_still_blocks() -> None:
    result = _evidence(
        reason="boundary_unresolved",
        confidence="LOW",
        method="NO_PEER_HEADING_FOUND",
        rows=_net_value_table(),
    )
    assert derive_boundary_status(result) == "REVIEW_REQUIRED"


# 9. BoundaryReason 契约：生产端 reason ∈ 枚举；消费端归一化旧字符串
def test_boundary_reason_enum_contract_consistent() -> None:
    produced = {
        BoundaryReason.NEXT_NOTE_ORDINAL.value,
        BoundaryReason.NEXT_PEER_HEADING.value,
        BoundaryReason.SAME_PAGE_FOOTER_FALLBACK.value,
    }
    all_values = {r.value for r in BoundaryReason}
    assert produced <= all_values

    def fake_page_lines(page: int) -> list[dict]:
        if page == 2:
            return [{
                "text": "11. 其他权益工具投资",
                "y0": 100.0, "x0": 50.0,
                "words": [{"text": "11."}, {"text": "其他权益工具投资"}],
            }]
        return []

    boundary = resolve_table_boundary(
        note_reference="附注七-10",
        title="债权投资",
        start_page=1,
        start_y=10.0,
        title_x0=40.0,
        page_count=5,
        page_height=lambda p: 800.0,
        page_lines=fake_page_lines,
        max_pages=3,
    )
    assert boundary["boundary_reason"] == BoundaryReason.NEXT_NOTE_ORDINAL.value
    assert boundary["boundary_evidence"]["next_note_verified"] is True

    fallback = resolve_table_boundary(
        note_reference="附注七-10",
        title="债权投资",
        start_page=1,
        start_y=10.0,
        title_x0=40.0,
        page_count=5,
        page_height=lambda p: 800.0,
        page_lines=lambda p: [],
        max_pages=3,
    )
    assert fallback["boundary_reason"] == BoundaryReason.SAME_PAGE_FOOTER_FALLBACK.value
    assert fallback["boundary_evidence"]["next_note_verified"] is False
    assert fallback["boundary_confidence"] == "MEDIUM"

    # 消费端归一化旧 reason（历史 artifact 兼容）
    legacy = _evidence(
        reason="next_note_7",
        confidence="HIGH",
        method="NEXT_NOTE_ORDINAL",
        rows=_net_value_table(),
    )
    assert derive_boundary_status(legacy) == "HARD_BOUNDARY_CONFIRMED"


# 10. 修复前后 artifact 保留完整审计差异
def test_artifact_keeps_audit_diff() -> None:
    rows = _total_with_noise_table()
    result = _evidence(
        reason=BoundaryReason.SAME_PAGE_FOOTER_FALLBACK.value,
        confidence="MEDIUM",
        method="SAME_PAGE_FOOTER_FALLBACK",
        next_note_verified=False,
        rows=rows,
    )
    assert derive_boundary_status(result) == "SOFT_BOUNDARY_CONFIRMED"
    noise = rows[-1]
    assert noise["row_role"] == "PAGE_NUMBER_NOISE"
    assert noise["excluded_from_table_logic"] is True
    assert noise["cells"][0]["raw"] == "85"
    assert result["stats"]["boundary_evidence"]["method"] == "SAME_PAGE_FOOTER_FALLBACK"


# 额外：SOFT_BOUNDARY_CONFIRMED 不触发 PDF_BOUNDARY_UNCERTAIN
def test_soft_boundary_confirmed_does_not_trigger_pdf_boundary_uncertain() -> None:
    from services.capture_decision_reducer import CaptureDecisionReducer

    rows = _total_with_noise_table()
    evidence = _evidence(
        reason=BoundaryReason.SAME_PAGE_FOOTER_FALLBACK.value,
        confidence="MEDIUM",
        method="SAME_PAGE_FOOTER_FALLBACK",
        next_note_verified=False,
        rows=rows,
    )
    evidence["stats"]["v69_header_topology"] = {"consistent": True}
    evidence["stats"]["v69_reconciliation"] = {"status": "PASS"}
    decision = CaptureDecisionReducer().reduce(
        machine_evidence=evidence,
        capture_version={},
        lifecycle_state={},
        rule_version="v6.11-test",
    )
    assert "PDF_BOUNDARY_UNCERTAIN" not in decision.blocking_issues
    assert "HEADER_TOPOLOGY_AMBIGUOUS" not in decision.blocking_issues
