"""Journey A: Optional IMPLICIT_TOTAL does not block merge.

Precondition: A capture with ANONYMOUS_NUMERIC_ROW or non-required
IMPLICIT_TOTAL has been completed.

Steps:
  1. Navigate to merge page (整表合表)
  2. Verify the capture appears in merge_ready_records
  3. Verify no IMPLICIT_ROW_UNRESOLVED blocker
  4. Verify capture is eligible for merge selection

Invariant: BUG-001 — optional IMPLICIT_TOTAL must not block source rows.
"""
from __future__ import annotations

import re
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

# This test runs against the production database.
# It does NOT require a browser — it validates the invariant programmatically.


def test_implicit_total_not_in_merge_blockers() -> None:
    """Production captures with merge_ready=True have no IMPLICIT_ROW_UNRESOLVED."""
    import sqlite3
    from pathlib import Path

    db = Path.home() / "FinancialMetricResolverData" / "metadata.db"
    conn = sqlite3.connect(str(db))
    conn.row_factory = sqlite3.Row

    # Find merge_ready captures
    ready = conn.execute(
        "SELECT capture_id, run_path FROM captures WHERE is_trashed=0 AND merge_ready=1"
    ).fetchall()

    false_blocks = 0
    for row in ready:
        run_path = str(row["run_path"] or "")
        result_path = Path(run_path) / "table_capture_result.json"
        if not result_path.exists():
            continue
        import json
        evidence = json.loads(result_path.read_text(encoding="utf-8"))
        rows = evidence.get("rows", [])

        # Check for IMPLICIT_TOTAL rows that should NOT block
        for r in rows:
            role = str(r.get("row_role") or "")
            if role == "IMPLICIT_TOTAL":
                ds = str(r.get("derived_status") or "")
                if ds == "REQUIRED_DERIVED_TOTAL_UNRESOLVED":
                    false_blocks += 1
                    print(f"  WARNING: {row['capture_id'][:60]} has REQUIRED_DERIVED_TOTAL")

    conn.close()
    assert false_blocks == 0, (
        f"Found {false_blocks} merge_ready captures with REQUIRED_DERIVED_TOTAL — "
        "these should be REVIEW_REQUIRED, not merge_ready"
    )
    print(f"JOURNEY_A_PASS: {len(ready)} merge_ready captures, 0 with REQUIRED_DERIVED_TOTAL")


def test_anonymous_numeric_rows_not_blocking() -> None:
    """ANONYMOUS_NUMERIC_ROW rows do not appear in merge_blockers."""
    from capture_library import capture_readiness
    import json
    from pathlib import Path

    # Synthetic test: ANONYMOUS_NUMERIC_ROW should not block
    evidence = {
        "boundary_status": "HARD_BOUNDARY_CONFIRMED",
        "stats": {
            "v69_header_topology": {"consistent": True},
            "v69_reconciliation": {"status": "PASS"},
            "mixed_cell_count": 0,
        },
        "rows": [
            {"row_order": 1, "row_role": "DETAIL", "raw_item": "上市",
             "cells": [{"raw": "100"}], "value": 100},
            {"row_order": 2, "row_role": "ANONYMOUS_NUMERIC_ROW",
             "cells": [{"raw": "50"}], "value": 50},
        ],
        "header_dimension_status": "AUTO_CONFIRMED",
        "unit": "万元",
    }
    readiness = capture_readiness(evidence)
    assert readiness["merge_ready"] is True, (
        f"ANONYMOUS_NUMERIC_ROW caused block: {readiness.get('merge_blockers')}"
    )
    print("JOURNEY_A_ANONYMOUS_NOT_BLOCKING_PASS")


def test_implicit_total_non_blocking_issue_code() -> None:
    """IMPLICIT_TOTAL_UNCERTIFIED_NON_BLOCKING is a warning, not blocking."""
    from services.capture_decision_reducer import CaptureDecisionReducer

    reducer = CaptureDecisionReducer()
    evidence = {
        "boundary_status": "HARD_BOUNDARY_CONFIRMED",
        "stats": {
            "boundary_reason": "next_note_74",
            "boundary_evidence": {"method": "NEXT_NOTE_ORDINAL"},
            "boundary_confidence": "HIGH",
            "v69_header_topology": {"consistent": True},
            "v69_reconciliation": {"status": "PASS"},
            "mixed_cell_count": 0,
        },
        "rows": [
            {"row_order": 1, "row_role": "DETAIL", "raw_item": "上市",
             "cells": [{"raw": "100"}], "value": 100},
            {"row_order": 2, "row_role": "IMPLICIT_TOTAL",
             "derived_status": "DERIVED_REJECTED_NON_BLOCKING",
             "human_confirmed": False, "cells": [{"raw": "100"}], "value": 100},
        ],
        "header_dimension_status": "AUTO_CONFIRMED",
        "unit": "万元",
    }
    cv = {
        "research_definition_id": "FINANCIAL_INVESTMENT_V1",
        "definition_version": "FINANCIAL_INVESTMENT_V1",
        "table_family_id": "financial_investment",
        "statement_scope": "CONSOLIDATED",
        "is_current": True, "pdf_id": "pdf123",
    }
    result = reducer.reduce(machine_evidence=evidence, capture_version=cv)
    assert "IMPLICIT_TOTAL_UNCERTIFIED" not in result.blocking_issues, (
        f"IMPLICIT_TOTAL should not block: {result.blocking_issues}"
    )
    print("JOURNEY_A_NON_BLOCKING_ISSUE_CODE_PASS")


def main() -> None:
    test_implicit_total_not_in_merge_blockers()
    test_anonymous_numeric_rows_not_blocking()
    test_implicit_total_non_blocking_issue_code()
    print("\n=== JOURNEY A (IMPLICIT_TOTAL): ALL CHECKS PASSED ===")


if __name__ == "__main__":
    main()
