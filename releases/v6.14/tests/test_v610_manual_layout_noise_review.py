"""Regression: an audited layout-noise row cannot block merge readiness."""
from capture_library import capture_readiness, human_layout_noise_orders


def _result():
    return {
        "boundary_status": "HUMAN_CONFIRMED",
        "header_dimension_status": "AUTO_CONFIRMED",
        "boundary_review": {"status": "HUMAN_CONFIRMED", "last_included_row_order": 3},
        "unit": "CNY_MILLION",
        "stats": {
            "v69_header_topology": {"consistent": True},
            "v69_reconciliation": {"status": "PASS"},
        },
        "rows": [
            {"row_order": 1, "raw_item": "政府债", "row_role": "DETAIL", "cells": [{"raw": "10"}]},
            {"row_order": 2, "raw_item": None, "row_role": "IMPLICIT_ROW_CANDIDATE", "cells": [{"raw": "07"}]},
            {"row_order": 3, "raw_item": "金融债", "row_role": "DETAIL", "cells": [{"raw": "20"}]},
        ],
    }


def test_manual_layout_noise_is_auditable_and_not_an_implicit_blocker():
    result = _result()
    # Make the shape deliberately fail the automatic two-neighbour heuristic:
    # human adjudication remains available for conservative parser cases.
    result["rows"][0]["raw_item"] = None
    result["human_row_noise_review"] = [{
        "row_order": 2,
        "decision": "LAYOUT_NOISE_EXCLUDED",
        "reason": "侧页码污染",
        "machine_token": "07",
    }]
    assert human_layout_noise_orders(result) == {2}
    readiness = capture_readiness(result)
    assert readiness["unresolved_implicit_rows"] == 0
    assert readiness["merge_ready"] is True
