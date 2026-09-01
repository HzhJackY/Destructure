"""v6.10 IMPLICIT_TOTAL non-blocking governance contracts.

Validates:
  - EMPTY-label numeric rows default to ANONYMOUS_NUMERIC_ROW
  - Only verified IMPLICIT_TOTAL rows become DERIVED_OBSERVATION
  - Non-required derived totals do NOT block merge
  - Explicit total suppression works
  - Required derived totals still block
  - Source rows remain merge-eligible with derived rows excluded
  - Real-world acceptance: Ping An 2025 debt investment
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from accounting_semantic_parser_v2 import (
    ROW_ROLES,
    OBSERVATION_TYPES,
    DERIVED_STATUSES,
    infer_row_role,
    build_semantic_rows,
)
from implicit_total_rows import (
    recover_implicit_total_rows,
    DERIVED_VALIDATED,
    DERIVED_REJECTED_NON_BLOCKING,
    DERIVED_EXCLUDED,
    SUPPRESSED_BY_EXPLICIT_TOTAL,
    REQUIRED_DERIVED_TOTAL_UNRESOLVED,
)
from capture_library import capture_readiness


class _Cell:
    def __init__(self, value: float):
        self.parsed_number = value


class _Row:
    def __init__(self, *, label, role, values, order):
        self.raw_item = label
        self.row_role = role
        self.row_type = role
        self.cells = [_Cell(value) for value in values]
        self.row_order = order
        self.parent_section = ""


def test_anonymous_numeric_row_default() -> None:
    """Empty-label numeric rows default to ANONYMOUS_NUMERIC_ROW, not IMPLICIT_TOTAL."""
    role = infer_row_role(None, has_value=True)
    assert role == "ANONYMOUS_NUMERIC_ROW", f"Expected ANONYMOUS_NUMERIC_ROW, got {role}"
    print("EMPTY_LABEL_NUMERIC_DEFAULTS_ANONYMOUS_ROW_PASS")


def test_anonymous_numeric_row_in_roles() -> None:
    """ANONYMOUS_NUMERIC_ROW is a recognised row role."""
    assert "ANONYMOUS_NUMERIC_ROW" in ROW_ROLES
    print("ANONYMOUS_NUMERIC_ROW_IN_ROLES_PASS")


def test_observation_types_defined() -> None:
    """SOURCE_OBSERVATION and DERIVED_OBSERVATION are defined."""
    assert "SOURCE_OBSERVATION" in OBSERVATION_TYPES
    assert "DERIVED_OBSERVATION" in OBSERVATION_TYPES
    print("OBSERVATION_TYPES_DEFINED_PASS")


def test_derived_statuses_defined() -> None:
    """All five derived statuses are defined."""
    assert "DERIVED_VALIDATED" in DERIVED_STATUSES
    assert "DERIVED_REJECTED_NON_BLOCKING" in DERIVED_STATUSES
    assert "DERIVED_EXCLUDED" in DERIVED_STATUSES
    assert "SUPPRESSED_BY_EXPLICIT_TOTAL" in DERIVED_STATUSES
    assert "REQUIRED_DERIVED_TOTAL_UNRESOLVED" in DERIVED_STATUSES
    print("DERIVED_STATUSES_DEFINED_PASS")


def test_source_observation_default() -> None:
    """Normal rows get SOURCE_OBSERVATION by default."""
    rows = [
        {"raw_item": "上市", "value": 100, "row_level": 0, "row_type": "DETAIL"},
        {"raw_item": "非上市", "value": 50, "row_level": 0, "row_type": "DETAIL"},
    ]
    result = build_semantic_rows(rows)
    for row in result:
        assert row.get("observation_type") == "SOURCE_OBSERVATION", (
            f"Expected SOURCE_OBSERVATION, got {row.get('observation_type')}"
        )
    print("SOURCE_OBSERVATION_DEFAULT_PASS")


def test_implicit_total_gets_derived_observation() -> None:
    """Rows classified as IMPLICIT_TOTAL get DERIVED_OBSERVATION."""
    rows = [
        {"raw_item": "上市", "value": 259579, "row_level": 0, "row_type": "DETAIL",
         "row_role": "DETAIL"},
        {"raw_item": "非上市", "value": 5298, "row_level": 0, "row_type": "DETAIL",
         "row_role": "DETAIL"},
        {"raw_item": None, "value": 264877, "row_level": 0, "row_type": "DETAIL",
         "row_role": "IMPLICIT_TOTAL", "derived_item": "推导总额",
         "label_derivation": "DERIVED_FROM_STRUCTURE"},
    ]
    result = build_semantic_rows(rows)
    derived = [r for r in result if r.get("row_role") == "IMPLICIT_TOTAL"]
    assert len(derived) == 1
    assert derived[0].get("observation_type") == "DERIVED_OBSERVATION"
    print("DERIVED_OBSERVATION_ON_IMPLICIT_TOTAL_PASS")


def test_footer_noise_does_not_hide_anonymous_arithmetic_total() -> None:
    rows = [
        _Row(label="上市", role="DETAIL", values=[62_757, 61_208], order=1),
        _Row(label="非上市", role="DETAIL", values=[1_180_596, 1_062_827], order=2),
        _Row(label="页脚", role="PAGE_FOOTER_NOISE", values=[], order=3),
        _Row(label=None, role="IMPLICIT_ROW_CANDIDATE", values=[1_243_353, 1_124_035], order=4),
    ]

    recovered = recover_implicit_total_rows(rows, parent_table="债权投资")

    assert recovered[-1].row_role == "IMPLICIT_TOTAL"
    assert recovered[-1].derived_from_rows == ["上市", "非上市"]
    assert recovered[-1].derived_status == DERIVED_REJECTED_NON_BLOCKING


def test_anonymous_numeric_row_not_blocking() -> None:
    """ANONYMOUS_NUMERIC_ROW rows do NOT count as unresolved implicit rows."""
    result = {
        "boundary_status": "HARD_BOUNDARY_CONFIRMED",
        "rows": [
            {"row_order": 1, "row_role": "SECTION", "raw_item": "投资资产", "cells": []},
            {"row_order": 2, "row_role": "DETAIL", "raw_item": "上市", "cells": [{"raw": "100"}], "value": 100},
            {"row_order": 3, "row_role": "ANONYMOUS_NUMERIC_ROW", "cells": [{"raw": "50"}], "value": 50},
        ],
        "stats": {
            "v69_header_topology": {"consistent": True},
            "v69_reconciliation": {"status": "PASS"},
        },
    }
    readiness = capture_readiness(result)
    assert readiness["unresolved_implicit_rows"] == 0, (
        f"Expected 0 unresolved, got {readiness['unresolved_implicit_rows']}"
    )
    assert "IMPLICIT_ROW_UNRESOLVED" not in str(readiness.get("merge_blockers", []))
    print("ANONYMOUS_NUMERIC_ROW_NOT_BLOCKING_PASS")


def test_non_required_implicit_total_not_blocking() -> None:
    """IMPLICIT_TOTAL with non-blocking derived_status does not block merge."""
    result = {
        "boundary_status": "HARD_BOUNDARY_CONFIRMED",
        "rows": [
            {"row_order": 1, "row_role": "DETAIL", "raw_item": "上市", "cells": [{"raw": "100"}], "value": 100},
            {"row_order": 2, "row_role": "IMPLICIT_TOTAL", "value": 100,
             "derived_status": "DERIVED_REJECTED_NON_BLOCKING",
             "human_confirmed": False, "cells": [{"raw": "100"}]},
        ],
        "stats": {
            "v69_header_topology": {"consistent": True},
            "v69_reconciliation": {"status": "PASS"},
        },
    }
    readiness = capture_readiness(result)
    assert readiness["unresolved_implicit_rows"] == 0
    assert "IMPLICIT_ROW_UNRESOLVED" not in str(readiness.get("merge_blockers", []))
    print("NON_REQUIRED_IMPLICIT_TOTAL_NOT_BLOCKING_PASS")


def test_suppressed_implicit_total_not_blocking() -> None:
    """SUPPRESSED_BY_EXPLICIT_TOTAL rows do not block merge."""
    result = {
        "boundary_status": "HARD_BOUNDARY_CONFIRMED",
        "rows": [
            {"row_order": 1, "row_role": "DETAIL", "raw_item": "上市", "cells": [{"raw": "100"}], "value": 100},
            {"row_order": 2, "row_role": "TOTAL", "raw_item": "合计", "cells": [{"raw": "100"}], "value": 100},
            {"row_order": 3, "row_role": "IMPLICIT_TOTAL", "value": 100,
             "derived_status": "SUPPRESSED_BY_EXPLICIT_TOTAL",
             "human_confirmed": False, "cells": [{"raw": "100"}]},
        ],
        "stats": {
            "v69_header_topology": {"consistent": True},
            "v69_reconciliation": {"status": "PASS"},
        },
    }
    readiness = capture_readiness(result)
    assert readiness["unresolved_implicit_rows"] == 0
    print("SUPPRESSED_IMPLICIT_TOTAL_NOT_BLOCKING_PASS")


def test_required_derived_total_still_blocks() -> None:
    """REQUIRED_DERIVED_TOTAL_UNRESOLVED still blocks merge."""
    result = {
        "boundary_status": "HARD_BOUNDARY_CONFIRMED",
        "rows": [
            {"row_order": 1, "row_role": "DETAIL", "raw_item": "上市", "cells": [{"raw": "100"}], "value": 100},
            {"row_order": 2, "row_role": "IMPLICIT_TOTAL", "value": 100,
             "derived_status": "REQUIRED_DERIVED_TOTAL_UNRESOLVED",
             "human_confirmed": False, "cells": [{"raw": "100"}]},
        ],
        "stats": {
            "v69_header_topology": {"consistent": True},
            "v69_reconciliation": {"status": "PASS"},
        },
    }
    readiness = capture_readiness(result)
    assert readiness["unresolved_implicit_rows"] > 0
    print("REQUIRED_DERIVED_TOTAL_STILL_BLOCKS_PASS")


def test_derived_excluded_not_blocking() -> None:
    """DERIVED_EXCLUDED rows do not block merge."""
    result = {
        "boundary_status": "HARD_BOUNDARY_CONFIRMED",
        "rows": [
            {"row_order": 1, "row_role": "DETAIL", "raw_item": "上市", "cells": [{"raw": "100"}], "value": 100},
            {"row_order": 2, "row_role": "IMPLICIT_TOTAL", "value": 100,
             "derived_status": "DERIVED_EXCLUDED",
             "human_confirmed": False, "cells": [{"raw": "100"}]},
        ],
        "stats": {
            "v69_header_topology": {"consistent": True},
            "v69_reconciliation": {"status": "PASS"},
        },
    }
    readiness = capture_readiness(result)
    assert readiness["unresolved_implicit_rows"] == 0
    print("DERIVED_EXCLUDED_NOT_BLOCKING_PASS")


def test_source_rows_merge_eligible_with_derived_excluded() -> None:
    """Source rows remain merge-eligible even when derived rows are excluded."""
    result = {
        "boundary_status": "HARD_BOUNDARY_CONFIRMED",
        "rows": [
            {"row_order": 1, "row_role": "SECTION", "raw_item": "投资资产", "cells": []},
            {"row_order": 2, "row_role": "BREAKDOWN_DETAIL", "raw_item": "上市", "cells": [{"raw": "259579"}], "value": 259579},
            {"row_order": 3, "row_role": "BREAKDOWN_DETAIL", "raw_item": "非上市", "cells": [{"raw": "5298"}], "value": 5298},
            {"row_order": 4, "row_role": "ANONYMOUS_NUMERIC_ROW", "cells": [{"raw": "264877"}], "value": 264877},
        ],
        "stats": {
            "v69_header_topology": {"consistent": True},
            "v69_reconciliation": {"status": "PASS"},
        },
    }
    readiness = capture_readiness(result)
    assert readiness["merge_ready"], (
        f"Expected merge_ready=True, blockers={readiness.get('merge_blockers')}"
    )
    print("SOURCE_ROWS_MERGE_ELIGIBLE_WITH_DERIVED_EXCLUDED_PASS")


def main() -> None:
    test_anonymous_numeric_row_default()
    test_anonymous_numeric_row_in_roles()
    test_observation_types_defined()
    test_derived_statuses_defined()
    test_source_observation_default()
    test_implicit_total_gets_derived_observation()
    test_anonymous_numeric_row_not_blocking()
    test_non_required_implicit_total_not_blocking()
    test_suppressed_implicit_total_not_blocking()
    test_required_derived_total_still_blocks()
    test_derived_excluded_not_blocking()
    test_source_rows_merge_eligible_with_derived_excluded()
    print("\n=== ALL 12 IMPLICIT_TOTAL GOVERNANCE TESTS PASSED ===")


if __name__ == "__main__":
    main()
