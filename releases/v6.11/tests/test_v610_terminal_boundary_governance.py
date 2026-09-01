"""v6.10 Terminal Boundary auto-closure governance contracts.

Validates:
  - Natural page-end tables auto-close with AUTO_HIGH_CONFIDENCE
  - Missing next heading alone does NOT block
  - Reconciled terminal tables skip review task generation
  - Same-note different-block detection
  - AUTO_ACCEPTED_WITH_NON_BLOCKING_WARNING for mid-page same-note blocks
  - Auto-closed boundaries do NOT enter Review Inbox
  - Auto-closed captures are merge-eligible
  - Stale boundary issues resolved by rule upgrade
  - Mid-page end without auto-closure requires review
  - Failed reconciliation requires review
  - Real-world acceptance: Xinhua 2025 other debt investment
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import json
from capture_library import (
    derive_boundary_status,
    derive_boundary_decision,
    capture_readiness,
    TerminalBoundaryDecision,
    MERGE_READY_STATUSES,
    _explicit_terminal_total_is_safe,
    _page_terminal_reconciled_block_is_safe,
    _same_note_different_block_signal,
)


def _base_result(**overrides) -> dict:
    """Build a minimal plausible result dict for boundary testing."""
    base = {
        "boundary_status": "UNASSESSED",
        "stats": {
            "boundary_reason": "boundary_unresolved",
            "boundary_evidence": {"method": "NO_PEER_HEADING_FOUND"},
            "boundary_confidence": "",
            "v69_reconciliation": {"status": "PASS"},
            "v69_header_topology": {"consistent": True},
            "roi": {"end_y": 800},
            "engine": "v6.10",
        },
        "rows": [
            {"row_order": 1, "row_role": "DETAIL", "raw_item": "上市",
             "cells": [{"raw": "100"}], "value": 100},
            {"row_order": 2, "row_role": "TOTAL", "raw_item": "合计",
             "cells": [{"raw": "100"}], "value": 100,
             "bbox": {"y1": 780}},
        ],
        "warnings": [],
    }
    base.update(overrides)
    return base


def test_natural_page_end_auto_high_confidence() -> None:
    """A reconciled table ending near the page bottom with a total row
    auto-closes with AUTO_HIGH_CONFIDENCE."""
    result = _base_result()
    status = derive_boundary_status(result)
    assert status == "AUTO_HIGH_CONFIDENCE", f"Expected AUTO_HIGH_CONFIDENCE, got {status}"
    print("NATURAL_PAGE_END_AUTO_HIGH_CONFIDENCE_PASS")


def test_missing_next_heading_alone_non_blocking() -> None:
    """When a table has a total, reconciliation PASS, and consistent topology,
    NO_PEER_HEADING_FOUND by itself should not force REVIEW_REQUIRED if the
    table is page-terminal."""
    result = _base_result()
    safe, sub = _page_terminal_reconciled_block_is_safe(
        result, reason="boundary_unresolved", warnings=""
    )
    assert safe, f"Expected safe=True, got sub={sub}"
    assert sub == "PAGE_TERMINAL_RECONCILED", f"Expected PAGE_TERMINAL_RECONCILED, got {sub}"
    print("MISSING_NEXT_HEADING_ALONE_NON_BLOCKING_PASS")


def test_reconciled_terminal_table_no_review_required() -> None:
    """A fully reconciled terminal table returns a merge-ready boundary status."""
    result = _base_result()
    status = derive_boundary_status(result)
    assert status in MERGE_READY_STATUSES, f"Expected merge-ready, got {status}"
    print("RECONCILED_TERMINAL_TABLE_NO_REVIEW_REQUIRED_PASS")


def test_explicit_terminal_total_safe() -> None:
    """A table with an explicit 合计 row and no continuation warnings is safe."""
    result = _base_result()
    safe = _explicit_terminal_total_is_safe(
        result, reason="boundary_unresolved", warnings=""
    )
    assert safe, f"Expected safe=True"
    print("EXPLICIT_TERMINAL_TOTAL_SAFE_PASS")


def test_explicit_terminal_total_unsafe_with_continuation() -> None:
    """A table with continuation warnings is NOT safe for explicit-total shortcut."""
    result = _base_result()
    result["warnings"] = ["跨页续表"]
    safe = _explicit_terminal_total_is_safe(
        result, reason="boundary_unresolved", warnings="跨页续表"
    )
    assert not safe
    print("EXPLICIT_TERMINAL_TOTAL_UNSAFE_CONTINUATION_PASS")


def test_same_note_different_block_detection() -> None:
    """A table ending mid-page within a note that has a SECTION row after the total
    is detected as same-note different-block."""
    rows = [
        {"row_order": 1, "row_role": "DETAIL", "raw_item": "上市", "cells": [{"raw": "100"}], "value": 100},
        {"row_order": 2, "row_role": "TOTAL", "raw_item": "合计", "cells": [{"raw": "100"}], "value": 100},
        {"row_order": 3, "row_role": "SECTION", "raw_item": "公允价值变动", "cells": []},
    ]
    result = _base_result()
    result["rows"] = rows
    # Reduce page position so the 80% threshold fails
    result["rows"][1]["bbox"] = {"y1": 400}
    result["stats"]["roi"]["end_y"] = 800
    detected = _same_note_different_block_signal(result, rows, 1)
    assert detected, "Should detect same-note different-block signal"
    print("SAME_NOTE_DIFFERENT_BLOCK_DETECTED_PASS")


def test_auto_accepted_with_non_blocking_warning() -> None:
    """Mid-page table in same-note different-block returns
    AUTO_ACCEPTED_WITH_NON_BLOCKING_WARNING."""
    rows = [
        {"row_order": 1, "row_role": "DETAIL", "raw_item": "上市", "cells": [{"raw": "100"}], "value": 100},
        {"row_order": 2, "row_role": "TOTAL", "raw_item": "合计", "cells": [{"raw": "100"}], "value": 100},
        {"row_order": 3, "row_role": "SECTION", "raw_item": "其他", "cells": []},
    ]
    result = _base_result()
    result["rows"] = rows
    result["rows"][1]["bbox"] = {"y1": 400}
    status = derive_boundary_status(result)
    assert status == "AUTO_ACCEPTED_WITH_NON_BLOCKING_WARNING", (
        f"Expected AUTO_ACCEPTED_WITH_NON_BLOCKING_WARNING, got {status}"
    )
    print("AUTO_ACCEPTED_WITH_NON_BLOCKING_WARNING_PASS")


def test_auto_accepted_in_merge_ready_statuses() -> None:
    """AUTO_ACCEPTED_WITH_NON_BLOCKING_WARNING is in MERGE_READY_STATUSES."""
    assert "AUTO_ACCEPTED_WITH_NON_BLOCKING_WARNING" in MERGE_READY_STATUSES
    print("AUTO_ACCEPTED_IN_MERGE_READY_PASS")


def test_auto_accepted_capture_merge_eligible() -> None:
    """A capture with AUTO_ACCEPTED_WITH_NON_BLOCKING_WARNING is merge-eligible."""
    rows = [
        {"row_order": 1, "row_role": "DETAIL", "raw_item": "上市", "cells": [{"raw": "100"}], "value": 100},
        {"row_order": 2, "row_role": "TOTAL", "raw_item": "合计", "cells": [{"raw": "100"}], "value": 100},
        {"row_order": 3, "row_role": "SECTION", "raw_item": "其他", "cells": []},
    ]
    result = _base_result()
    result["rows"] = rows
    result["rows"][1]["bbox"] = {"y1": 400}
    readiness = capture_readiness(result)
    assert readiness["boundary_status"] == "AUTO_ACCEPTED_WITH_NON_BLOCKING_WARNING"
    assert readiness["merge_ready"], (
        f"Expected merge_ready=True, got blockers={readiness.get('merge_blockers')}"
    )
    print("AUTO_ACCEPTED_CAPTURE_MERGE_ELIGIBLE_PASS")


def test_mid_page_end_without_signal_requires_review() -> None:
    """A table ending mid-page WITHOUT a post-total SECTION row still requires review."""
    rows = [
        {"row_order": 1, "row_role": "DETAIL", "raw_item": "上市", "cells": [{"raw": "100"}], "value": 100},
        {"row_order": 2, "row_role": "DETAIL", "raw_item": "非上市", "cells": [{"raw": "50"}], "value": 50},
    ]
    result = _base_result()
    result["rows"] = rows
    result["rows"][1]["bbox"] = {"y1": 300}  # mid-page
    result["stats"]["boundary_evidence"]["method"] = "NO_PEER_HEADING_FOUND"
    status = derive_boundary_status(result)
    # Without a total row, should require review
    assert status == "REVIEW_REQUIRED", f"Expected REVIEW_REQUIRED, got {status}"
    print("MID_PAGE_END_REQUIRES_REVIEW_PASS")


def test_failed_reconciliation_without_total_requires_review() -> None:
    """A table with failed reconciliation and NO explicit total requires review.
    (An explicit total still auto-closes the boundary — reconciliation is a
    separate quality gate handled by V69_RECONCILIATION_MISMATCH.)"""
    result = _base_result()
    # Remove the TOTAL row so explicit-total shortcut doesn't fire
    result["rows"] = [
        {"row_order": 1, "row_role": "DETAIL", "raw_item": "上市",
         "cells": [{"raw": "100"}], "value": 100, "bbox": {"y1": 780}},
        {"row_order": 2, "row_role": "DETAIL", "raw_item": "非上市",
         "cells": [{"raw": "50"}], "value": 50, "bbox": {"y1": 790}},
    ]
    result["stats"]["v69_reconciliation"]["status"] = "WARNING"
    result["stats"]["boundary_reason"] = "boundary_unresolved"
    result["stats"]["boundary_evidence"]["method"] = "NO_PEER_HEADING_FOUND"
    status = derive_boundary_status(result)
    assert status == "REVIEW_REQUIRED", f"Expected REVIEW_REQUIRED, got {status}"
    print("FAILED_RECONCILIATION_REQUIRES_REVIEW_PASS")


def test_inconsistent_topology_without_total_requires_review() -> None:
    """A table with inconsistent header topology and NO explicit total requires review.
    (An explicit total still auto-closes the boundary.)"""
    result = _base_result()
    result["rows"] = [
        {"row_order": 1, "row_role": "DETAIL", "raw_item": "上市",
         "cells": [{"raw": "100"}], "value": 100, "bbox": {"y1": 780}},
    ]
    result["stats"]["v69_header_topology"]["consistent"] = False
    result["stats"]["boundary_reason"] = "boundary_unresolved"
    result["stats"]["boundary_evidence"]["method"] = "NO_PEER_HEADING_FOUND"
    status = derive_boundary_status(result)
    assert status == "REVIEW_REQUIRED", f"Expected REVIEW_REQUIRED, got {status}"
    print("INCONSISTENT_TOPOLOGY_REQUIRES_REVIEW_PASS")


def test_stale_review_required_re_evaluated() -> None:
    """A persisted REVIEW_REQUIRED is re-evaluated and auto-closed when conditions
    now meet the auto-closure criteria."""
    result = _base_result()
    result["boundary_status"] = "REVIEW_REQUIRED"
    status = derive_boundary_status(result)
    assert status == "AUTO_HIGH_CONFIDENCE", (
        f"Expected AUTO_HIGH_CONFIDENCE (re-evaluated), got {status}"
    )
    print("STALE_REVIEW_REQUIRED_RE_EVALUATED_PASS")


def test_terminal_boundary_decision_struct() -> None:
    """derive_boundary_decision returns a TerminalBoundaryDecision with evidence chain."""
    result = _base_result()
    decision = derive_boundary_decision(result)
    assert isinstance(decision, TerminalBoundaryDecision)
    assert decision.status == "AUTO_HIGH_CONFIDENCE"
    assert len(decision.evidence_chain) >= 2, f"Expected ≥2 evidence items, got {decision.evidence_chain}"
    assert decision.sub_decision in ("PAGE_TERMINAL_RECONCILED", "EXPLICIT_TOTAL")
    print("TERMINAL_BOUNDARY_DECISION_STRUCT_PASS")


def test_auto_boundary_capture_ready() -> None:
    """An auto-closed boundary capture is READY (not REVIEW_REQUIRED)."""
    result = _base_result()
    readiness = capture_readiness(result)
    assert readiness["capture_quality_status"] == "READY", (
        f"Expected READY, got {readiness['capture_quality_status']}"
    )
    assert readiness["merge_ready"] is True
    assert not readiness["merge_blockers"], f"Expected 0 blockers, got {readiness['merge_blockers']}"
    print("AUTO_BOUNDARY_CAPTURE_READY_PASS")


def test_terminal_total_with_labelled_post_rows() -> None:
    """Table with TOTAL row followed only by labelled breakdown rows
    (e.g. '其中：成本') auto-closes with AUTO_HIGH_CONFIDENCE."""
    from capture_library import _terminal_total_with_labelled_post_rows_is_safe
    result = _base_result()
    result["rows"] = [
        {"row_order": 1, "row_role": "DETAIL", "raw_item": "上市",
         "cells": [{"raw": "100"}], "value": 100},
        {"row_order": 2, "row_role": "DETAIL", "raw_item": "非上市",
         "cells": [{"raw": "50"}], "value": 50},
        {"row_order": 3, "row_role": "TOTAL", "raw_item": "合计",
         "cells": [{"raw": "150"}], "value": 150},
        {"row_order": 4, "row_role": "SECTION", "raw_item": "其中：",
         "cells": []},
        {"row_order": 5, "row_role": "DETAIL", "raw_item": "－成本",
         "cells": [{"raw": "120"}], "value": 120},
    ]
    safe, evidence = _terminal_total_with_labelled_post_rows_is_safe(
        result, reason="boundary_unresolved", warnings=""
    )
    assert safe, "TOTAL + labelled post rows should be safe"
    status = derive_boundary_status(result)
    assert status in ("AUTO_HIGH_CONFIDENCE", "AUTO_ACCEPTED_WITH_NON_BLOCKING_WARNING"), f"Got {status}"
    print("TERMINAL_TOTAL_WITH_LABELLED_POST_ROWS_AUTO_HIGH_PASS")


def test_unlabeled_numeric_spill_after_total_blocks() -> None:
    """Anonymous numeric row after TOTAL → still REVIEW_REQUIRED."""
    from capture_library import _terminal_total_with_labelled_post_rows_is_safe
    result = _base_result()
    result["rows"] = [
        {"row_order": 1, "row_role": "DETAIL", "raw_item": "上市",
         "cells": [{"raw": "100"}], "value": 100},
        {"row_order": 2, "row_role": "TOTAL", "raw_item": "合计",
         "cells": [{"raw": "100"}], "value": 100},
        {"row_order": 3, "row_role": "ANONYMOUS_NUMERIC_ROW",
         "cells": [{"raw": "42"}], "value": 42},
    ]
    safe, _ = _terminal_total_with_labelled_post_rows_is_safe(
        result, reason="boundary_unresolved", warnings=""
    )
    assert not safe, "Anonymous numeric spill should NOT be safe"
    print("UNLABELED_NUMERIC_SPILL_AFTER_TOTAL_BLOCKS_PASS")


def test_note_text_after_total_blocks() -> None:
    """Prose/NOTE_TEXT after TOTAL → still REVIEW_REQUIRED."""
    from capture_library import _terminal_total_with_labelled_post_rows_is_safe
    result = _base_result()
    result["rows"] = [
        {"row_order": 1, "row_role": "DETAIL", "raw_item": "上市",
         "cells": [{"raw": "100"}], "value": 100},
        {"row_order": 2, "row_role": "TOTAL", "raw_item": "合计",
         "cells": [{"raw": "100"}], "value": 100},
        {"row_order": 3, "row_role": "NOTE_TEXT", "raw_item": "本表数据来源",
         "cells": []},
    ]
    safe, _ = _terminal_total_with_labelled_post_rows_is_safe(
        result, reason="boundary_unresolved", warnings=""
    )
    assert not safe, "Text contamination should NOT be safe"
    print("TEXT_CONTAMINATION_AFTER_TOTAL_BLOCKS_PASS")


def test_cross_page_continuation_blocks_new_function() -> None:
    """跨页续表 still blocks the new auto-close path."""
    from capture_library import _terminal_total_with_labelled_post_rows_is_safe
    result = _base_result()
    result["rows"] = [
        {"row_order": 1, "row_role": "DETAIL", "raw_item": "上市",
         "cells": [{"raw": "100"}], "value": 100},
        {"row_order": 2, "row_role": "TOTAL", "raw_item": "合计",
         "cells": [{"raw": "100"}], "value": 100},
        {"row_order": 3, "row_role": "DETAIL", "raw_item": "－成本",
         "cells": [{"raw": "120"}], "value": 120},
    ]
    safe, _ = _terminal_total_with_labelled_post_rows_is_safe(
        result, reason="boundary_unresolved", warnings="跨页续表"
    )
    assert not safe, "跨页续表 should block"
    print("CROSS_PAGE_CONTINUATION_BLOCKS_NEW_FUNCTION_PASS")


def test_two_leaf_columns_terminal_safe() -> None:
    """ABSOLUTE_YEAR_CLASSIC with 2 leaf columns + TOTAL + labelled post rows
    → AUTO_HIGH_CONFIDENCE (matching the user's reported case)."""
    result = _base_result()
    result["rows"] = [
        {"row_order": 1, "row_role": "DETAIL", "raw_item": "上市",
         "cells": [{"raw": "100"}], "value": 100},
        {"row_order": 2, "row_role": "TOTAL", "raw_item": "合计",
         "cells": [{"raw": "100"}], "value": 100},
        {"row_order": 3, "row_role": "SECTION", "raw_item": "其中：",
         "cells": []},
    ]
    result["stats"]["boundary_reason"] = "boundary_unresolved"
    result["stats"]["boundary_evidence"]["method"] = "NO_PEER_HEADING_FOUND"
    result["warnings"] = [
        "HEADER_PARSER_AUTO_SELECTED：ABSOLUTE_YEAR_CLASSIC；numeric_clusters=2；leaf_columns=2。",
    ]
    status = derive_boundary_status(result)
    assert status in ("AUTO_HIGH_CONFIDENCE", "AUTO_ACCEPTED_WITH_NON_BLOCKING_WARNING"), f"Got {status}"
    print("HEADER_TWO_COLUMNS_TERMINAL_SAFE_PASS")


def test_missing_next_heading_with_total_auto_closes() -> None:
    """When NO_PEER_HEADING_FOUND but a TOTAL + labelled post rows exist,
    boundary auto-closes without blocking."""
    result = _base_result()
    result["rows"] = [
        {"row_order": 1, "row_role": "DETAIL", "raw_item": "上市",
         "cells": [{"raw": "100"}], "value": 100},
        {"row_order": 2, "row_role": "TOTAL", "raw_item": "合计",
         "cells": [{"raw": "100"}], "value": 100},
        {"row_order": 3, "row_role": "DETAIL", "raw_item": "－明细",
         "cells": [{"raw": "80"}], "value": 80},
    ]
    result["stats"]["boundary_reason"] = "boundary_unresolved"
    result["stats"]["boundary_evidence"]["method"] = "NO_PEER_HEADING_FOUND"
    status = derive_boundary_status(result)
    assert status in ("AUTO_HIGH_CONFIDENCE", "AUTO_ACCEPTED_WITH_NON_BLOCKING_WARNING"), f"Got {status}"
    print("MISSING_NEXT_HEADING_WITH_TOTAL_AUTO_CLOSES_PASS")


def test_stale_boundary_review_required_reassessed() -> None:
    """CaptureDecisionReducer: a persisted REVIEW_REQUIRED with labelled
    post-total rows is re-evaluated to AUTO_HIGH_CONFIDENCE."""
    from services.capture_decision_reducer import CaptureDecisionReducer
    reducer = CaptureDecisionReducer()
    evidence = {
        "boundary_status": "REVIEW_REQUIRED",
        "stats": {
            "boundary_reason": "boundary_unresolved",
            "boundary_evidence": {"method": "NO_PEER_HEADING_FOUND"},
            "v69_header_topology": {"consistent": True},
            "v69_reconciliation": {"status": "PASS"},
            "roi": {"end_y": 800},
            "engine": "v6.11",
            "mixed_cell_count": 0,
            "post_total_disclosure_not_merged": False,
        },
        "rows": [
            {"row_order": 1, "row_role": "DETAIL", "raw_item": "上市",
             "cells": [{"raw": "100"}], "value": 100},
            {"row_order": 2, "row_role": "TOTAL", "raw_item": "合计",
             "cells": [{"raw": "100"}], "value": 100},
            {"row_order": 3, "row_role": "SECTION", "raw_item": "其中：",
             "cells": []},
        ],
        "header_dimension_status": "AUTO_CONFIRMED",
        "unit": "万元",
        "warnings": [],
    }
    cv = {
        "research_definition_id": "FINANCIAL_INVESTMENT_V1",
        "definition_version": "FINANCIAL_INVESTMENT_V1",
        "table_family_id": "financial_investment",
        "statement_scope": "CONSOLIDATED",
        "is_current": True, "pdf_id": "pdf123",
        "registration_status": "REGISTERED",
        "asset_status": "ACTIVE",
    }
    result = reducer.reduce(machine_evidence=evidence, capture_version=cv)
    assert result.quality_status == "READY", f"Got quality={result.quality_status}"
    assert "PDF_BOUNDARY_UNCERTAIN" not in result.blocking_issues, f"Blockers: {result.blocking_issues}"
    assert result.review_inbox_eligible == False
    print("STALE_BOUNDARY_REASSESSED_AFTER_RULE_UPGRADE_PASS")


def test_auto_high_confidence_no_blocking_task() -> None:
    """When boundary is AUTO_HIGH_CONFIDENCE, no blocking review task
    is created."""
    from services.capture_decision_reducer import CaptureDecisionReducer
    reducer = CaptureDecisionReducer()
    evidence = {
        "boundary_status": "",
        "stats": {
            "boundary_reason": "boundary_unresolved",
            "boundary_evidence": {"method": "NO_PEER_HEADING_FOUND"},
            "v69_header_topology": {"consistent": True},
            "v69_reconciliation": {"status": "PASS"},
            "roi": {"end_y": 800},
            "engine": "v6.11",
            "mixed_cell_count": 0,
            "post_total_disclosure_not_merged": False,
        },
        "rows": [
            {"row_order": 1, "row_role": "DETAIL", "raw_item": "上市",
             "cells": [{"raw": "100"}], "value": 100},
            {"row_order": 2, "row_role": "TOTAL", "raw_item": "合计",
             "cells": [{"raw": "100"}], "value": 100},
            {"row_order": 3, "row_role": "DETAIL", "raw_item": "－成本",
             "cells": [{"raw": "80"}], "value": 80},
        ],
        "header_dimension_status": "AUTO_CONFIRMED",
        "unit": "万元",
        "warnings": [
            "HEADER_PARSER_AUTO_SELECTED：ABSOLUTE_YEAR_CLASSIC；numeric_clusters=2；leaf_columns=2。",
        ],
    }
    cv = {
        "research_definition_id": "FINANCIAL_INVESTMENT_V1",
        "definition_version": "FINANCIAL_INVESTMENT_V1",
        "table_family_id": "financial_investment",
        "statement_scope": "CONSOLIDATED",
        "is_current": True, "pdf_id": "pdf123",
        "registration_status": "REGISTERED",
    }
    result = reducer.reduce(
        machine_evidence=evidence, capture_version=cv,
        lifecycle_state={"registration_status": "REGISTERED"},
    )
    assert result.merge_eligible == True
    assert "PDF_BOUNDARY_UNCERTAIN" not in result.blocking_issues
    print("AUTO_HIGH_CONFIDENCE_NO_BLOCKING_TASK_PASS")


def test_split_label_post_total_memo_auto_closes() -> None:
    """TOTAL row followed by split-label memo '其中 / －成本' with values
    → AUTO_HIGH_CONFIDENCE with POST_TOTAL_MEMO_DETAIL semantic role."""
    from capture_library import (
        _terminal_total_with_labelled_post_rows_is_safe,
        derive_boundary_status,
    )
    result = _base_result()
    result["rows"] = [
        {"row_order": 1, "row_role": "DETAIL", "raw_item": "股票",
         "cells": [{"raw": "548109"}, {"raw": "267082"}],
         "value": 548109, "row_id": "ROW_1"},
        {"row_order": 2, "row_role": "DETAIL", "raw_item": "优先股",
         "cells": [{"raw": "54291"}, {"raw": "82575"}],
         "value": 54291, "row_id": "ROW_2"},
        {"row_order": 3, "row_role": "DETAIL", "raw_item": "其他权益投资",
         "cells": [{"raw": "7150"}, {"raw": "6836"}],
         "value": 7150, "row_id": "ROW_3"},
        {"row_order": 4, "row_role": "TOTAL", "raw_item": "合计",
         "cells": [{"raw": "609550"}, {"raw": "356493"}],
         "value": 609550, "row_id": "ROW_4"},
        {"row_order": 6, "row_role": "DETAIL", "raw_item": "其中 / －成本",
         "cells": [{"raw": "483071"}, {"raw": "320035"}],
         "value": 483071, "row_id": "ROW_6"},
    ]
    safe, evidence = _terminal_total_with_labelled_post_rows_is_safe(
        result, reason="boundary_unresolved", warnings=""
    )
    assert safe, f"Split-label memo should be safe, got evidence={evidence}"
    assert evidence["terminal_pattern"] == "RECONCILED_TOTAL_WITH_LABELLED_POST_TOTAL_ROWS"
    assert evidence["terminal_total_row_id"] == "ROW_4"
    assert evidence["post_total_row_ids"] == ["ROW_6"]
    assert len(evidence["post_total_semantic_roles"]) == 1
    assert evidence["post_total_semantic_roles"][0]["post_total_semantic_role"] == "POST_TOTAL_MEMO_DETAIL"
    assert evidence["final_boundary_decision"] == "AUTO_HIGH_CONFIDENCE"

    status = derive_boundary_status(result)
    assert status in ("AUTO_HIGH_CONFIDENCE", "AUTO_ACCEPTED_WITH_NON_BLOCKING_WARNING"), f"Got {status}"
    print("SPLIT_LABEL_POST_TOTAL_MEMO_AUTO_CLOSES_PASS")


def test_whereof_memo_label_detection() -> None:
    """_is_post_total_memo_label detects various whereof patterns."""
    from capture_library import _is_post_total_memo_label
    assert _is_post_total_memo_label("其中：成本")
    assert _is_post_total_memo_label("其中 / －成本")
    assert _is_post_total_memo_label("其中－成本")
    assert _is_post_total_memo_label("其中 / 公允价值变动")
    assert not _is_post_total_memo_label("股票")
    assert not _is_post_total_memo_label("合计")
    assert not _is_post_total_memo_label("")
    print("WHEREOF_MEMO_LABEL_DETECTION_PASS")


def main() -> None:
    test_natural_page_end_auto_high_confidence()
    test_missing_next_heading_alone_non_blocking()
    test_reconciled_terminal_table_no_review_required()
    test_explicit_terminal_total_safe()
    test_explicit_terminal_total_unsafe_with_continuation()
    test_same_note_different_block_detection()
    test_auto_accepted_with_non_blocking_warning()
    test_auto_accepted_in_merge_ready_statuses()
    test_auto_accepted_capture_merge_eligible()
    test_mid_page_end_without_signal_requires_review()
    test_failed_reconciliation_without_total_requires_review()
    test_inconsistent_topology_without_total_requires_review()
    test_stale_review_required_re_evaluated()
    test_terminal_boundary_decision_struct()
    test_auto_boundary_capture_ready()
    # v6.11: terminal-total-with-labelled-post-rows tests
    test_terminal_total_with_labelled_post_rows()
    test_unlabeled_numeric_spill_after_total_blocks()
    test_note_text_after_total_blocks()
    test_cross_page_continuation_blocks_new_function()
    test_two_leaf_columns_terminal_safe()
    test_missing_next_heading_with_total_auto_closes()
    test_stale_boundary_review_required_reassessed()
    test_auto_high_confidence_no_blocking_task()
    # v6.11: split-label memo / whereof pattern tests
    test_split_label_post_total_memo_auto_closes()
    test_whereof_memo_label_detection()
    print("\n=== ALL 25 TERMINAL BOUNDARY GOVERNANCE TESTS PASSED ===")


if __name__ == "__main__":
    main()
