"""v6.11 CaptureDecisionReducer contracts."""
from __future__ import annotations

import copy
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from capture_library import capture_readiness
from services.capture_decision_reducer import (
    CaptureDecisionReducer, DecisionResult,
)


def _base_evidence(**overrides) -> dict:
    base = {
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
    base.update(overrides)
    return base


def _base_cv(**overrides) -> dict:
    base = {
        "capture_id": "TEST001",
        "research_definition_id": "FINANCIAL_INVESTMENT_V1",
        "definition_version": "FINANCIAL_INVESTMENT_V1",
        "table_family_id": "financial_investment",
        "statement_scope": "CONSOLIDATED",
        "is_current": True,
        "pdf_id": "pdf123",
        "registration_status": "REGISTERED",
        "asset_status": "ACTIVE",
        "quality_status": "READY",
        "review_status": "CONFIRMED_AUTO",
    }
    base.update(overrides)
    return base


def _confirmed_primary_only_evidence(*, active_excluded_row: bool = False) -> dict:
    evidence = _base_evidence(
        boundary_status="",
        capture_scope_limited=True,
    )
    stats = dict(evidence["stats"])
    stats.update({
        "boundary_reason": "boundary_unresolved",
        "boundary_evidence": {"method": "NO_PEER_HEADING_FOUND"},
        "boundary_confidence": "",
        "scope_boundary_decision": "POLICY_TRUNCATION",
        "excluded_segment_manifest": [{
            "segment_id": "SEG_CONTINUATION",
            "classification": "CONTINUATION_SEGMENT",
            "continuation_of_segment_id": "SEG_PRIMARY",
            "page_number": 2,
            "row_order_start": 20,
            "row_order_end": 21,
        }],
        "physical_table_segments": [
            {
                "segment_id": "SEG_PRIMARY",
                "classification": "PRIMARY_TABLE",
                "page_number": 1,
            },
            {
                "segment_id": "SEG_CONTINUATION",
                "classification": "CONTINUATION_SEGMENT",
                "continuation_of_segment_id": "SEG_PRIMARY",
                "page_number": 2,
            },
        ],
    })
    evidence["stats"] = stats
    if active_excluded_row:
        evidence["rows"] = list(evidence["rows"]) + [{
            "row_order": 20,
            "page": 2,
            "physical_segment_id": "SEG_CONTINUATION",
            "row_role": "DETAIL",
            "raw_item": "不应进入表逻辑的续表行",
            "cells": [{"raw": "200"}],
            "excluded_from_table_logic": False,
        }]
    return evidence


def _unresolved_continuation_evidence() -> dict:
    evidence = _base_evidence()
    stats = dict(evidence["stats"])
    stats["physical_table_segments"] = [{
        "segment_id": "SEG_UNKNOWN",
        "classification": "UNRESOLVED",
        "candidate_relation": "CONTINUATION_SEGMENT",
        "reason_codes": ["CONTINUATION_RELATION_UNRESOLVED"],
        "relation_status": "UNRESOLVED",
        "page_number": 2,
    }]
    evidence["stats"] = stats
    return evidence


def _certified_boundary_validation(**overrides) -> dict:
    match = {"match": True}
    validation = {
        "status": "VALID",
        "manifest_status": "CERTIFIED_SEGMENT_MANIFEST",
        "issue_codes": [],
        "certified_segments": [{
            "certified_segment_id": "CSEG_PRIMARY",
            "classification": "PRIMARY_TABLE",
            "certification_status": "CERTIFIED",
        }],
        "discovered_segments": [{
            "segment_id": "SEG_PRIMARY",
            "classification": "PRIMARY_TABLE",
        }],
        "validated_pairs": [{
            "certified_segment_id": "CSEG_PRIMARY",
            "discovered_segment_id": "SEG_PRIMARY",
            "page": dict(match),
            "classification": dict(match),
            "header": dict(match),
            "period": dict(match),
            "lane": dict(match),
            "continuation": dict(match),
            "bbox": dict(match),
            "drift_fields": [],
        }],
    }
    validation.update(overrides)
    return validation


def _certified_bbox_evidence(validation: dict | None = None) -> dict:
    validation = copy.deepcopy(validation or _certified_boundary_validation())
    evidence = _base_evidence(boundary_status="")
    evidence["rows"][0]["physical_segment_id"] = "SEG_PRIMARY"
    evidence["stats"] = {
        **evidence["stats"],
        "boundary_reason": "certified_segment_bbox",
        "boundary_evidence": {"method": "NEXT_NOTE_ORDINAL"},
        "boundary_confidence": "HIGH",
        "v69_reconciliation": {"status": "NOT_TESTABLE"},
        "capture_scope_contract_version": 2,
        "capture_scope_policy": "PRIMARY_ONLY",
        "selected_segment_manifest": [{
            "segment_id": "SEG_PRIMARY",
            "classification": "PRIMARY_TABLE",
        }],
        "physical_table_segments": [{
            "segment_id": "SEG_PRIMARY",
            "classification": "PRIMARY_TABLE",
        }],
        "physical_segment_ids": ["SEG_PRIMARY"],
        "certified_segment_manifest_validation": validation,
        "certified_note_table_inventory_validation": {
            "status": "VALID",
            "issue_codes": [],
        },
    }
    return evidence


def _certified_boundary_cv(validation: dict | None = None) -> dict:
    validation = copy.deepcopy(validation or _certified_boundary_validation())
    return _base_cv(
        capture_scope_contract_version=2,
        capture_scope_policy="PRIMARY_ONLY",
        selected_segment_manifest=[{
            "segment_id": "SEG_PRIMARY",
            "classification": "PRIMARY_TABLE",
        }],
        certified_segment_manifest_validation=validation,
        certified_note_table_inventory_validation={
            "status": "VALID",
            "issue_codes": [],
        },
    )


def test_reducer_merge_eligible() -> None:
    reducer = CaptureDecisionReducer()
    result = reducer.reduce(
        machine_evidence=_base_evidence(),
        capture_version=_base_cv(),
    )
    assert result.quality_status == "READY"
    assert result.merge_eligible is True
    assert result.review_inbox_eligible is False
    assert not result.blocking_issues
    print("REDUCER_MERGE_ELIGIBLE_PASS")


def test_reducer_review_required_boundary() -> None:
    reducer = CaptureDecisionReducer()
    evidence = _base_evidence(
        boundary_status="",
        stats={
            "boundary_reason": "boundary_unresolved",
            "boundary_evidence": {"method": "NO_PEER_HEADING_FOUND"},
            "boundary_confidence": "",
            "v69_header_topology": {"consistent": True},
            "v69_reconciliation": {"status": "PASS"},
            "mixed_cell_count": 0,
        },
    )
    result = reducer.reduce(
        machine_evidence=evidence,
        capture_version=_base_cv(),
    )
    assert result.quality_status == "REVIEW_REQUIRED"
    assert "PDF_BOUNDARY_UNCERTAIN" in result.blocking_issues
    print("REDUCER_REVIEW_REQUIRED_BOUNDARY_PASS")


def test_certified_bbox_runtime_match_is_hard_boundary_without_reconciliation() -> None:
    validation = _certified_boundary_validation()
    result = CaptureDecisionReducer().reduce(
        machine_evidence=_certified_bbox_evidence(validation),
        capture_version=_certified_boundary_cv(validation),
    )

    assert result.merge_eligible is True
    assert result.quality_status == "READY"
    assert "PDF_BOUNDARY_UNCERTAIN" not in result.blocking_issues
    assert result.decision_evidence["boundary_decision"] == {
        "status": "HARD_BOUNDARY_CONFIRMED",
        "sub_decision": "CERTIFIED_SEGMENT_MANIFEST",
        "evidence_chain": [
            "method=NEXT_NOTE_ORDINAL",
            "confidence=HIGH",
            "reason=certified_segment_bbox",
            "capture_scope_policy=PRIMARY_ONLY",
            "capture_scope_limited=true",
            "certified_segment_manifest=VALID_RUNTIME_MATCH",
            "reconciliation=NOT_TESTABLE",
            "topology_consistent=True",
        ],
    }


def test_direct_physical_roi_runtime_match_is_hard_boundary() -> None:
    validation = _certified_boundary_validation(
        validation_mode="DIRECT_PORTFOLIO_PHYSICAL_ROI",
    )
    validation["validated_pairs"] = [{
        "certified_segment_id": "CSEG_PRIMARY",
        "discovered_segment_id": "SEG_PRIMARY",
        "drift_fields": [],
    }]
    result = CaptureDecisionReducer().reduce(
        machine_evidence=_certified_bbox_evidence(validation),
        capture_version=_certified_boundary_cv(validation),
    )

    assert result.merge_eligible is True
    assert result.quality_status == "READY"
    assert "PDF_BOUNDARY_UNCERTAIN" not in result.blocking_issues


@pytest.mark.parametrize(
    "validation_overrides",
    [
        {"status": "REVIEW_REQUIRED"},
        {"validated_pairs": []},
        {"validated_pairs": [{
            "certified_segment_id": "CSEG_PRIMARY",
            "discovered_segment_id": "SEG_PRIMARY",
            "page": {"match": True},
            "classification": {"match": True},
            "header": {"match": True},
            "period": {"match": True},
            "lane": {"match": True},
            "continuation": {"match": True},
            "bbox": {"match": False},
            "drift_fields": ["bbox"],
        }]},
    ],
)
def test_certified_bbox_without_full_runtime_match_remains_blocking(
    validation_overrides: dict,
) -> None:
    validation = _certified_boundary_validation(**validation_overrides)
    result = CaptureDecisionReducer().reduce(
        machine_evidence=_certified_bbox_evidence(validation),
        capture_version=_certified_boundary_cv(validation),
    )

    assert result.merge_eligible is False
    assert "PDF_BOUNDARY_UNCERTAIN" in result.blocking_issues


@pytest.mark.parametrize(
    "case",
    [
        "MACHINE_METADATA_CONFLICT",
        "PAIR_ID_NOT_IN_ARRAYS",
        "DISCOVERED_PEER_CLASSIFICATION",
        "CAPTURE_SCOPE_POLICY_MISSING",
        "SELECTED_MANIFEST_EMPTY",
    ],
)
def test_certified_bbox_rejects_inconsistent_governance_evidence(case: str) -> None:
    validation = _certified_boundary_validation()
    evidence = _certified_bbox_evidence(validation)
    capture_version = _certified_boundary_cv(validation)
    if case == "MACHINE_METADATA_CONFLICT":
        evidence["stats"]["certified_segment_manifest_validation"][
            "status"
        ] = "REVIEW_REQUIRED"
    elif case == "PAIR_ID_NOT_IN_ARRAYS":
        for target in (evidence["stats"], capture_version):
            target["certified_segment_manifest_validation"][
                "validated_pairs"
            ][0]["discovered_segment_id"] = "SEG_OTHER"
    elif case == "DISCOVERED_PEER_CLASSIFICATION":
        for target in (evidence["stats"], capture_version):
            target["certified_segment_manifest_validation"][
                "discovered_segments"
            ][0]["classification"] = "PEER_TABLE"
    elif case == "CAPTURE_SCOPE_POLICY_MISSING":
        evidence["stats"].pop("capture_scope_policy")
        capture_version.pop("capture_scope_policy")
    elif case == "SELECTED_MANIFEST_EMPTY":
        evidence["stats"]["selected_segment_manifest"] = []
        capture_version["selected_segment_manifest"] = []

    result = CaptureDecisionReducer().reduce(
        machine_evidence=evidence,
        capture_version=capture_version,
    )

    assert result.merge_eligible is False
    assert "PDF_BOUNDARY_UNCERTAIN" in result.blocking_issues


def test_reducer_implicit_total_non_blocking() -> None:
    reducer = CaptureDecisionReducer()
    evidence = _base_evidence(
        rows=[
            {"row_order": 1, "row_role": "DETAIL", "raw_item": "上市",
             "cells": [{"raw": "100"}], "value": 100},
            {"row_order": 2, "row_role": "IMPLICIT_TOTAL",
             "derived_status": "DERIVED_REJECTED_NON_BLOCKING",
             "human_confirmed": False, "cells": [{"raw": "100"}], "value": 100},
        ],
    )
    result = reducer.reduce(
        machine_evidence=evidence,
        capture_version=_base_cv(),
    )
    assert result.quality_status == "READY"
    assert result.merge_eligible is True
    assert "IMPLICIT_TOTAL_UNCERTIFIED_NON_BLOCKING" in result.non_blocking_warnings
    assert "IMPLICIT_TOTAL_UNCERTIFIED" not in result.blocking_issues
    print("REDUCER_IMPLICIT_TOTAL_NON_BLOCKING_PASS")


def test_reducer_idempotency() -> None:
    """Same inputs from any entry point → same DecisionResult."""
    reducer = CaptureDecisionReducer()
    evidence = _base_evidence()
    cv = _base_cv()

    r1 = reducer.reduce(machine_evidence=evidence, capture_version=cv)
    r2 = reducer.reduce(machine_evidence=evidence, capture_version=cv)
    r3 = reducer.reduce(machine_evidence=evidence, capture_version=cv, rule_version="v6.11")

    assert r1 == r2, "Two identical calls produced different results"
    assert r1.quality_status == r3.quality_status
    assert r1.merge_eligible == r3.merge_eligible
    assert r1.blocking_issues == r3.blocking_issues
    print("REDUCER_IDEMPOTENCY_PASS")


def test_reducer_missing_identity_blocks() -> None:
    reducer = CaptureDecisionReducer()
    cv = _base_cv(
        research_definition_id="",
        definition_version="",
        table_family_id="",
        statement_scope="UNKNOWN",
    )
    result = reducer.reduce(
        machine_evidence=_base_evidence(),
        capture_version=cv,
    )
    assert "RESEARCH_DEFINITION_MISSING" in result.blocking_issues
    assert "DEFINITION_VERSION_MISSING" in result.blocking_issues
    assert "TABLE_FAMILY_MISSING" in result.blocking_issues
    assert "STATEMENT_SCOPE_UNKNOWN" in result.blocking_issues
    print("REDUCER_MISSING_IDENTITY_BLOCKS_PASS")


def test_reducer_non_current_capture() -> None:
    reducer = CaptureDecisionReducer()
    result = reducer.reduce(
        machine_evidence=_base_evidence(),
        capture_version=_base_cv(is_current=False),
    )
    assert "NON_CURRENT_CAPTURE" in result.blocking_issues
    print("REDUCER_NON_CURRENT_CAPTURE_PASS")


def test_reducer_decision_result_immutable() -> None:
    result = DecisionResult(
        quality_status="READY",
        merge_eligible=True,
        review_inbox_eligible=False,
        blocking_issues=["TEST"],
    )
    assert result.quality_status == "READY"
    d = result.to_dict()
    assert d["quality_status"] == "READY"
    assert d["blocking_issues"] == ["TEST"]
    print("REDUCER_DECISION_RESULT_IMMUTABLE_PASS")


def test_primary_only_confirmed_policy_truncation_is_merge_ready_warning() -> None:
    evidence = _confirmed_primary_only_evidence()
    result = CaptureDecisionReducer().reduce(
        machine_evidence=evidence,
        capture_version=_base_cv(capture_scope_policy="PRIMARY_ONLY"),
    )

    assert result.merge_eligible is True
    assert result.quality_status == "READY"
    assert "CONTINUATION_EXCLUDED_BY_POLICY" in result.non_blocking_warnings
    assert "CONTINUATION_EXCLUDED_BY_POLICY" not in result.blocking_issues
    assert result.decision_evidence["boundary_decision"]["status"] == (
        "SCOPE_BOUNDARY_CONFIRMED"
    )
    assert result.decision_evidence["capture_scope_limited"] is True


def test_primary_only_scope_readiness_matches_reducer() -> None:
    evidence = _confirmed_primary_only_evidence()
    evidence["capture_scope_policy"] = "PRIMARY_ONLY"

    readiness = capture_readiness(evidence)

    assert readiness["boundary_status"] == "SCOPE_BOUNDARY_CONFIRMED"
    assert readiness["capture_scope_limited"] is True
    assert readiness["merge_ready"] is True
    assert readiness["merge_blockers"] == []
    assert readiness["non_blocking_warnings"] == [
        "CONTINUATION_EXCLUDED_BY_POLICY"
    ]


def test_primary_only_without_policy_truncation_proof_keeps_boundary_blocking() -> None:
    evidence = _base_evidence(
        boundary_status="",
        capture_scope_limited=True,
        stats={
            "boundary_reason": "boundary_unresolved",
            "boundary_evidence": {"method": "NO_PEER_HEADING_FOUND"},
            "boundary_confidence": "",
            "v69_header_topology": {"consistent": True},
            "v69_reconciliation": {"status": "PASS"},
            "mixed_cell_count": 0,
        },
    )

    result = CaptureDecisionReducer().reduce(
        machine_evidence=evidence,
        capture_version=_base_cv(capture_scope_policy="PRIMARY_ONLY"),
    )

    assert result.merge_eligible is False
    assert "PDF_BOUNDARY_UNCERTAIN" in result.blocking_issues
    assert "CONTINUATION_EXCLUDED_BY_POLICY" not in result.non_blocking_warnings


def test_primary_only_policy_truncation_with_active_excluded_rows_fails_closed() -> None:
    evidence = _confirmed_primary_only_evidence(active_excluded_row=True)

    result = CaptureDecisionReducer().reduce(
        machine_evidence=evidence,
        capture_version=_base_cv(capture_scope_policy="PRIMARY_ONLY"),
    )

    assert result.merge_eligible is False
    assert "CAPTURE_SCOPE_POLICY_EVIDENCE_INCOMPLETE" in result.blocking_issues
    assert "PDF_BOUNDARY_UNCERTAIN" in result.blocking_issues


@pytest.mark.parametrize(
    "policy",
    ["PRIMARY_WITH_CONTINUATIONS", "ALL_NOTE_TABLES"],
)
def test_including_continuations_blocks_unresolved_relation(policy: str) -> None:
    evidence = _unresolved_continuation_evidence()

    result = CaptureDecisionReducer().reduce(
        machine_evidence=evidence,
        capture_version=_base_cv(capture_scope_policy=policy),
    )

    assert result.merge_eligible is False
    assert "CONTINUATION_UNRESOLVED" in result.blocking_issues
    assert result.decision_evidence["boundary_decision"]["status"] == (
        "CONTINUATION_REQUIRED"
    )


def test_including_continuations_accepts_confirmed_chain_with_natural_end() -> None:
    evidence = _base_evidence()
    evidence["stats"] = {
        **evidence["stats"],
        "physical_table_segments": [
            {
                "segment_id": "SEG_PRIMARY",
                "classification": "PRIMARY_TABLE",
                "page_number": 1,
            },
            {
                "segment_id": "SEG_CONTINUATION",
                "classification": "CONTINUATION_SEGMENT",
                "continuation_of_segment_id": "SEG_PRIMARY",
                "page_number": 2,
            },
        ],
        "scope_boundary_decision": "CONTINUATION_CHAIN_COMPLETE",
    }

    result = CaptureDecisionReducer().reduce(
        machine_evidence=evidence,
        capture_version=_base_cv(
            capture_scope_policy="PRIMARY_WITH_CONTINUATIONS",
        ),
    )

    assert result.merge_eligible is True
    assert "CONTINUATION_UNRESOLVED" not in result.blocking_issues


@pytest.mark.parametrize(
    "issue_code",
    [
        "CERTIFIED_SEGMENT_MANIFEST_REQUIRED",
        "CERTIFIED_SEGMENT_MANIFEST_DRIFT",
        "CERTIFIED_NOTE_TABLE_INVENTORY_REQUIRED",
    ],
)
def test_certified_scope_governance_issues_fail_closed(issue_code: str) -> None:
    evidence = _base_evidence()
    evidence["stats"] = {
        **evidence["stats"],
        "scope_issue_codes": [issue_code],
    }

    decision = CaptureDecisionReducer().reduce(
        machine_evidence=evidence,
        capture_version=_base_cv(capture_scope_policy="ALL_NOTE_TABLES"),
    )
    readiness = capture_readiness(
        evidence,
        scope_metadata={"capture_scope_policy": "ALL_NOTE_TABLES"},
    )

    assert decision.merge_eligible is False
    assert issue_code in decision.blocking_issues
    assert readiness["merge_ready"] is False
    assert issue_code in readiness["merge_blockers"]


def main() -> None:
    test_reducer_merge_eligible()
    test_reducer_review_required_boundary()
    test_reducer_implicit_total_non_blocking()
    test_reducer_idempotency()
    test_reducer_missing_identity_blocks()
    test_reducer_non_current_capture()
    test_reducer_decision_result_immutable()
    test_primary_only_confirmed_policy_truncation_is_merge_ready_warning()
    test_primary_only_scope_readiness_matches_reducer()
    test_primary_only_without_policy_truncation_proof_keeps_boundary_blocking()
    test_primary_only_policy_truncation_with_active_excluded_rows_fails_closed()
    test_including_continuations_blocks_unresolved_relation(
        "PRIMARY_WITH_CONTINUATIONS"
    )
    test_including_continuations_blocks_unresolved_relation("ALL_NOTE_TABLES")
    test_including_continuations_accepts_confirmed_chain_with_natural_end()
    print("\n=== ALL 14 CAPTURE DECISION REDUCER TESTS PASSED ===")


if __name__ == "__main__":
    main()
