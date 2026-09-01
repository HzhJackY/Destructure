"""勾稽语义拆分：MISMATCH（已证不一致，阻塞）与 WARNING（警告，非阻塞）分离。"""
from __future__ import annotations

from pathlib import Path
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from compound_note_engine import _reconciliation
from capture_library import capture_readiness
from services.capture_decision_reducer import CaptureDecisionReducer
from services.review_task_service import ISSUE_CATALOG
from table_capture import TableCell, TableRow
from review_reasons import normalize_review_reason


def _row(order: int, label: str, cells: list[float | None], row_type: str = "DETAIL") -> TableRow:
    return TableRow(
        row_order=order, page=1, block_id="B", source_method="SPATIAL",
        raw_item=label, normalized_item=label, canonical_item=None,
        mapping_status="MAPPED", row_type=row_type, row_level=0,
        parent_section=None,
        cells=[
            TableCell(i, i + 1, str(v) if v is not None else "", v, None, None)
            for i, v in enumerate(cells)
        ],
        header_source_page=1,
        row_role="TOTAL" if row_type == "TOTAL" else "DETAIL",
    )


def test_reconciliation_pass_when_sum_matches() -> None:
    rows = [
        _row(1, "债券", [40.0]),
        _row(2, "股票", [60.0]),
        _row(3, "合计", [100.0], row_type="TOTAL"),
    ]
    rec = _reconciliation(rows)
    assert rec["status"] == "PASS"


def test_reconciliation_mismatch_not_warning() -> None:
    rows = [
        _row(1, "债券", [40.0]),
        _row(2, "股票", [70.0]),
        _row(3, "合计", [100.0], row_type="TOTAL"),
    ]
    rec = _reconciliation(rows)
    assert rec["status"] == "MISMATCH"
    assert rec["checks"][0]["pass"] is False


def test_reconciliation_not_testable_without_totals() -> None:
    rows = [_row(1, "债券", [40.0]), _row(2, "股票", [60.0])]
    assert _reconciliation(rows)["status"] == "NOT_TESTABLE"


def _reduce_with_recon(status: str):
    return CaptureDecisionReducer().reduce(
        machine_evidence={
            "rows": [],
            "columns": [],
            "stats": {"v69_reconciliation": {"status": status, "checks": []}},
        },
        capture_version={},
        lifecycle_state={},
        rule_version="v6.11-test",
    )
def test_mismatch_warns_without_blocking_merge() -> None:
    decision = _reduce_with_recon("MISMATCH")
    assert "RECONCILIATION_MISMATCH" not in decision.blocking_issues
    assert "RECONCILIATION_WARNING" in decision.non_blocking_warnings


def test_legacy_warning_status_remains_non_blocking() -> None:
    decision = _reduce_with_recon("WARNING")
    assert "RECONCILIATION_MISMATCH" not in decision.blocking_issues
    assert "RECONCILIATION_WARNING" in decision.non_blocking_warnings


def test_not_testable_does_not_block() -> None:
    decision = _reduce_with_recon("NOT_TESTABLE")
    assert "RECONCILIATION_MISMATCH" not in decision.blocking_issues
    assert "RECONCILIATION_WARNING" not in decision.non_blocking_warnings


def test_pass_does_not_block() -> None:
    decision = _reduce_with_recon("PASS")
    assert "RECONCILIATION_MISMATCH" not in decision.blocking_issues


def test_fail_remains_blocking() -> None:
    decision = _reduce_with_recon("FAIL")
    assert "RECONCILIATION_MISMATCH" in decision.blocking_issues
    assert decision.merge_eligible is False


def test_capture_readiness_allows_reconciliation_mismatch() -> None:
    readiness = capture_readiness({
        "boundary_status": "HARD_BOUNDARY_CONFIRMED",
        "header_dimension_status": "AUTO_CONFIRMED",
        "rows": [],
        "stats": {
            "v69_header_topology": {"consistent": True},
            "v69_reconciliation": {"status": "MISMATCH"},
        },
    })
    assert readiness["merge_ready"] is True
    assert "V69_RECONCILIATION_MISMATCH" not in readiness["merge_blockers"]


def test_warning_code_is_non_blocking_in_catalog_semantics() -> None:
    assert "RECONCILIATION_MISMATCH" in ISSUE_CATALOG
    assert "RECONCILIATION_WARNING" in ISSUE_CATALOG
    # MISMATCH 仍是机器事实；对外评审以非阻断 WARNING 呈现。
    assert "勾稽不一致" in ISSUE_CATALOG["RECONCILIATION_MISMATCH"][0]
    # 阻塞与否由 reducer 权威决定，MISMATCH/WARNING 均为非阻断警告。


def test_normalize_review_reason_distinguishes_mismatch() -> None:
    assert normalize_review_reason("RECONCILIATION_MISMATCH") == "RECONCILIATION_MISMATCH"
    assert normalize_review_reason("V69_RECONCILIATION_MISMATCH") == "RECONCILIATION_MISMATCH"
    assert normalize_review_reason("RECONCILIATION_WARNING") == "RECONCILIATION_WARNING"
