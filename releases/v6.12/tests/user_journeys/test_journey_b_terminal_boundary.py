"""Journey B: Terminal Boundary auto-closes without UI dependency.

Invariant: BUG-002 — A page-terminal reconciled table must be AUTO_HIGH_CONFIDENCE
and READY without any user click on "前往处理".
"""
from __future__ import annotations

import json, sys, sqlite3
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))


def test_auto_closed_boundaries_in_production() -> None:
    """Production: captures with AUTO_HIGH_CONFIDENCE are merge_ready=1."""
    db = Path.home() / "FinancialMetricResolverData" / "metadata.db"
    conn = sqlite3.connect(str(db))
    conn.row_factory = sqlite3.Row

    auto_closed = conn.execute(
        "SELECT capture_id, run_path FROM captures WHERE is_trashed=0 AND merge_ready=1"
    ).fetchall()

    boundary_statuses = {}
    for row in auto_closed:
        run_path = str(row["run_path"] or "")
        result_path = Path(run_path) / "table_capture_result.json"
        if not result_path.exists():
            continue
        evidence = json.loads(result_path.read_text(encoding="utf-8"))
        from capture_library import derive_boundary_status
        bs = derive_boundary_status(evidence)
        boundary_statuses[row["capture_id"]] = bs

    conn.close()

    # All merge_ready captures should have boundary in MERGE_READY_STATUSES
    from capture_library import MERGE_READY_STATUSES
    non_ready = {k: v for k, v in boundary_statuses.items() if v not in MERGE_READY_STATUSES}
    assert not non_ready, (
        f"Found {len(non_ready)} merge_ready captures with non-ready boundary: {non_ready}"
    )
    auto_high = sum(1 for v in boundary_statuses.values() if v == "AUTO_HIGH_CONFIDENCE")
    print(f"JOURNEY_B_PASS: {len(auto_closed)} merge_ready, {auto_high} AUTO_HIGH_CONFIDENCE, 0 non-ready")


def test_natural_page_end_auto_closes() -> None:
    """Synthetic: a natural page-end table gets AUTO_HIGH_CONFIDENCE."""
    from capture_library import derive_boundary_status

    evidence = {
        "boundary_status": "",
        "stats": {
            "boundary_reason": "boundary_unresolved",
            "boundary_evidence": {"method": "NO_PEER_HEADING_FOUND"},
            "v69_header_topology": {"consistent": True},
            "v69_reconciliation": {"status": "PASS"},
            "roi": {"end_y": 800},
            "engine": "v6.11",
        },
        "rows": [
            {"row_order": 1, "row_role": "DETAIL", "raw_item": "上市",
             "cells": [{"raw": "100"}], "value": 100},
            {"row_order": 2, "row_role": "TOTAL", "raw_item": "合计",
             "cells": [{"raw": "100"}], "value": 100, "bbox": {"y1": 780}},
        ],
        "warnings": [],
    }
    status = derive_boundary_status(evidence)
    assert status == "AUTO_HIGH_CONFIDENCE", (
        f"Natural page end should be AUTO_HIGH_CONFIDENCE, got {status}"
    )
    print("JOURNEY_B_NATURAL_PAGE_END_AUTO_CLOSES_PASS")


def test_auto_closed_no_review_inbox() -> None:
    """CaptureDecisionReducer: AUTO_HIGH_CONFIDENCE → inbox_eligible=False."""
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
        },
        "rows": [
            {"row_order": 1, "row_role": "DETAIL", "raw_item": "上市",
             "cells": [{"raw": "100"}], "value": 100},
            {"row_order": 2, "row_role": "TOTAL", "raw_item": "合计",
             "cells": [{"raw": "100"}], "value": 100, "bbox": {"y1": 780}},
        ],
        "warnings": [],
        "header_dimension_status": "AUTO_CONFIRMED",
        "unit": "万元",
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
        machine_evidence=evidence,
        capture_version=cv,
        lifecycle_state={"registration_status": "REGISTERED"},
    )
    assert result.review_inbox_eligible is False, (
        f"Auto-closed boundary should NOT be inbox-eligible"
    )
    assert "PDF_BOUNDARY_UNCERTAIN" not in result.blocking_issues
    print("JOURNEY_B_AUTO_CLOSED_NO_INBOX_PASS")


def main() -> None:
    test_auto_closed_boundaries_in_production()
    test_natural_page_end_auto_closes()
    test_auto_closed_no_review_inbox()
    print("\n=== JOURNEY B (TERMINAL BOUNDARY): ALL CHECKS PASSED ===")


if __name__ == "__main__":
    main()
