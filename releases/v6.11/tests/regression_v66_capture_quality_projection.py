"""Regression for boundary/job/current-Capture status separation."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from capture_library import capture_readiness


def base_result() -> dict:
    return {
        "boundary_status": "HARD_BOUNDARY_CONFIRMED",
        "header_dimension_status": "AUTO_CONFIRMED",
        "stats": {
            "boundary_reason": "next_note_13",
            "mixed_cell_count": 0,
        },
        "columns": [
            {
                "ordinal": 0,
                "source_column_index": 1,
                "header_raw": "2025",
                "year": "2025",
                "scope": None,
                "restated": False,
                "period_label": "2025",
            }
        ],
        "rows": [
            {
                "row_order": 1,
                "raw_item": None,
                "normalized_item": "其他权益工具投资总额",
                "row_role": "IMPLICIT_TOTAL",
                "row_type": "IMPLICIT_TOTAL",
                "cells": [{"parsed_number": 609550}],
            }
        ],
    }


def main() -> None:
    implicit_total = capture_readiness(base_result())
    assert implicit_total["capture_quality_status"] == "READY", implicit_total
    assert implicit_total["merge_ready"] is True, implicit_total
    assert implicit_total["unresolved_implicit_rows"] == 0, implicit_total

    unresolved = base_result()
    unresolved["rows"][0]["row_role"] = "IMPLICIT_ROW_CANDIDATE"
    unresolved_quality = capture_readiness(unresolved)
    assert unresolved_quality["capture_quality_status"] == "REVIEW_REQUIRED"
    assert unresolved_quality["merge_blockers"] == ["IMPLICIT_ROW_UNRESOLVED:1"]

    mixed = base_result()
    mixed["stats"]["mixed_cell_count"] = 1
    mixed_quality = capture_readiness(mixed)
    assert mixed_quality["capture_quality_status"] == "REVIEW_REQUIRED"
    assert mixed_quality["merge_blockers"] == ["MIXED_CELL:1"]

    human_cutoff = base_result()
    human_cutoff["stats"]["mixed_cell_count"] = 1
    human_cutoff["rows"].append({
        "row_order": 2,
        "raw_item": "附注：后续污染文本与金额 100",
        "normalized_item": "附注后续污染文本与金额",
        "row_role": "IMPLICIT_ROW_CANDIDATE",
        "row_type": "IMPLICIT_ROW_CANDIDATE",
        "cells": [{"raw_value": "金额 100", "parsed_number": None, "cell_role": "MIXED"}],
    })
    human_cutoff["boundary_review"] = {
        "status": "HUMAN_CONFIRMED",
        "last_included_row_order": 1,
    }
    cutoff_quality = capture_readiness(human_cutoff)
    assert cutoff_quality["capture_quality_status"] == "READY", cutoff_quality
    assert cutoff_quality["mixed_cell_count"] == 0, cutoff_quality
    assert cutoff_quality["unresolved_implicit_rows"] == 0, cutoff_quality

    medium_boundary = base_result()
    medium_boundary["boundary_status"] = "HARD_BOUNDARY_CONFIRMED"
    medium_boundary["stats"]["boundary_reason"] = "next_peer_heading_13"
    medium_boundary["stats"]["boundary_confidence"] = "MEDIUM"
    medium_boundary["stats"]["boundary_evidence"] = {"method": "NEXT_PEER_HEADING"}
    medium_quality = capture_readiness(medium_boundary)
    assert medium_quality["capture_quality_status"] == "REVIEW_REQUIRED", medium_quality
    assert medium_quality["merge_blockers"] == ["BOUNDARY:REVIEW_REQUIRED"], medium_quality

    print("HARD_BOUNDARY_IMPLICIT_TOTAL_READY_PASS")
    print("UNRESOLVED_IMPLICIT_ROW_REVIEW_PASS")
    print("MIXED_CELL_QUALITY_GATE_PASS")
    print("HUMAN_CUTOFF_RECOMPUTES_SEMANTIC_QUALITY_PASS")
    print("MEDIUM_BOUNDARY_REMAINS_REVIEW_REQUIRED_PASS")


if __name__ == "__main__":
    main()
