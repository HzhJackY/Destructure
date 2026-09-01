"""v6.11 Clean DATA_HOME — full pipeline from empty DB through merge."""
from __future__ import annotations

import json, sys, tempfile, shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def test_seed_builtin_families() -> None:
    """Empty DB → seed → families and members exist."""
    from metadata_registry import MetadataRegistry
    from research_definition_registry import ResearchDefinitionService

    tmp = Path(tempfile.mkdtemp()) / "metadata.db"
    try:
        reg = MetadataRegistry(tmp)
        svc = ResearchDefinitionService(reg)
        families = svc.families()
        assert any(f["family_id"] == "financial_investment" for f in families)
        assert any(f["family_id"] == "investment_portfolio" for f in families)
        members = svc.members("financial_investment")
        assert len(members) >= 10
    finally:
        shutil.rmtree(tmp.parent, ignore_errors=True)
    print("CLEAN_SEED_BUILTIN_FAMILIES_PASS")


def test_expected_member_resolver_clean() -> None:
    """ExpectedMemberResolver works without real DB."""
    from expected_member_resolver import resolve_expected_members

    result = resolve_expected_members(
        resolution_mode="EXPLICIT_PARENT",
        presentation_regime="NEW_FINANCIAL_INSTRUMENT_CLASSIFICATION",
        report_year="2024", statement_scope="CONSOLIDATED",
        source_parent_boundary={"label": "金融投资"},
        definition_version="V1",
        registry_members=[
            {"member_id": "fvtpl_assets", "payload": {}},
            {"member_id": "debt_investment", "payload": {}},
            {"member_id": "other_debt_investment", "payload": {}},
            {"member_id": "other_equity_investment", "payload": {}},
            {"member_id": "time_deposits", "payload": {}},
        ],
        actual_statement_rows=[
            {"member_table": "fvtpl_assets", "member_period_status": "ACTIVE_CURRENT_PERIOD"},
            {"member_table": "debt_investment", "member_period_status": "ACTIVE_CURRENT_PERIOD"},
            {"member_table": "other_debt_investment", "member_period_status": "ACTIVE_CURRENT_PERIOD"},
            {"member_table": "other_equity_investment", "member_period_status": "ACTIVE_CURRENT_PERIOD"},
            {"member_table": "time_deposits", "member_period_status": "OUTSIDE_FAMILY"},
        ],
    )
    assert len(result["required_current_members"]) == 4
    assert "time_deposits" in result["outside_family_members"]
    print("CLEAN_EXPECTED_MEMBER_RESOLVER_PASS")


def test_capture_decision_reducer_clean() -> None:
    """CaptureDecisionReducer works without DB."""
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
            {"row_order": 1, "row_role": "DETAIL", "raw_item": "test",
             "cells": [{"raw": "100"}], "value": 100},
        ],
        "header_dimension_status": "AUTO_CONFIRMED",
        "unit": "万元",
    }
    cv = {
        "capture_id": "TEST001",
        "research_definition_id": "FINANCIAL_INVESTMENT_V1",
        "definition_version": "FINANCIAL_INVESTMENT_V1",
        "table_family_id": "financial_investment",
        "statement_scope": "CONSOLIDATED",
        "is_current": True,
        "pdf_id": "pdf123",
        "registration_status": "REGISTERED",
        "quality_status": "READY",
        "review_status": "CONFIRMED_AUTO",
        "asset_status": "ACTIVE",
    }
    result = reducer.reduce(machine_evidence=evidence, capture_version=cv)
    assert result.quality_status == "READY"
    assert result.merge_eligible is True
    assert result.review_inbox_eligible is False
    print("CLEAN_CAPTURE_DECISION_REDUCER_PASS")


def test_defect_invariants_defined() -> None:
    """All 12 permanent defect invariants are registered."""
    from defect_invariant_registry import DEFECT_INVARIANTS
    ids = {d["defect_id"] for d in DEFECT_INVARIANTS}
    expected = {f"BUG-{i:03d}" for i in range(1, 13)}
    assert ids == expected, f"Missing: {expected - ids}"
    assert all(d["permanent_regression"] for d in DEFECT_INVARIANTS)
    print("CLEAN_DEFECT_INVARIANTS_DEFINED_PASS")


def test_synthetic_fixtures_pass() -> None:
    """Every declared fixture executes; SKIPPED is never treated as PASS."""
    from synthetic_domain_fixtures import SYNTHETIC_FIXTURES, run_fixture
    failed = []
    for fid in SYNTHETIC_FIXTURES:
        result = run_fixture(fid)
        if result.get("status") != "PASS":
            failed.append((fid, result))
    assert not failed, f"Failed fixtures: {failed}"
    print("CLEAN_SYNTHETIC_FIXTURES_ALL_PASS")


def test_portfolio_family_clean() -> None:
    """Portfolio family has classification_axis."""
    from research_definition_registry import BUILTIN_MEMBERS
    members = BUILTIN_MEMBERS.get("investment_portfolio", [])
    axes = {m.get("classification_axis") for m in members if m.get("classification_axis")}
    assert "BY_INVESTMENT_OBJECT" in axes
    assert "BY_ACCOUNTING_MEASUREMENT" in axes
    print("CLEAN_PORTFOLIO_CLASSIFICATION_AXIS_PASS")


def test_period_statuses_clean() -> None:
    """Period status constants are available."""
    from statement_family_resolution import MEMBER_PERIOD_STATUSES
    required = {"ACTIVE_CURRENT_PERIOD", "COMPARATIVE_ONLY_LEGACY_MEMBER",
                "OUTSIDE_FAMILY", "UNRESOLVED"}
    assert required.issubset(MEMBER_PERIOD_STATUSES)
    print("CLEAN_PERIOD_STATUSES_PASS")


def main() -> None:
    test_seed_builtin_families()
    test_expected_member_resolver_clean()
    test_capture_decision_reducer_clean()
    test_defect_invariants_defined()
    test_synthetic_fixtures_pass()
    test_portfolio_family_clean()
    test_period_statuses_clean()
    print("\n=== ALL 7 CLEAN DATA_HOME TESTS PASSED ===")


if __name__ == "__main__":
    main()
