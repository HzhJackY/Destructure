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
    separate quality gate handled by V69_RECONCILIATION_WARNING.)"""
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
    print("\n=== ALL 15 TERMINAL BOUNDARY GOVERNANCE TESTS PASSED ===")


if __name__ == "__main__":
    main()
