from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from defect_invariant_registry import DEFECT_INVARIANTS, validate_all
from synthetic_domain_fixtures import SYNTHETIC_FIXTURES, run_fixture


def test_all_twelve_defect_invariants_are_executable() -> None:
    result = validate_all()

    assert len(DEFECT_INVARIANTS) == 12
    assert {item["defect_id"] for item in result["passed"]} == {
        f"BUG-{number:03d}" for number in range(1, 13)
    }
    assert result["failed"] == []
    assert result["not_run"] == []


def test_tenth_fixture_is_executed_not_skipped() -> None:
    assert len(SYNTHETIC_FIXTURES) == 10

    result = run_fixture("IMAGE_DOMINANT_STATEMENT_DISCOVERY")

    assert result["status"] == "PASS"
    assert result["actual"] == {
        "ocr_only_locates_structure": True,
        "ocr_does_not_generate_amounts": True,
        "amounts_from_pdf_visual_evidence": True,
    }
