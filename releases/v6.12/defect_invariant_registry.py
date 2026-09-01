"""v6.11 permanent defect invariant registry.

Each fixed defect becomes a permanent regression contract.  Any invariant
failure is a release blocker — the same problem must never recur.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path
from typing import Any

DEFECT_INVARIANTS: list[dict[str, Any]] = [
    {
        "defect_id": "BUG-001",
        "title": "optional IMPLICIT_TOTAL must not block source rows",
        "invariant": "ANONYMOUS_NUMERIC_ROW and non-required IMPLICIT_TOTAL rows do not block merge eligibility",
        "fixture_id": "ANONYMOUS_NUMERIC_ROW",
        "severity": "P0",
        "introduced_version": "v6.7",
        "fixed_version": "v6.10",
        "permanent_regression": True,
        "test_location": "tests/test_v610_implicit_total_governance.py",
        "validation_kind": "fixture",
        "last_result": None,
    },
    {
        "defect_id": "BUG-002",
        "title": "terminal boundary auto-closure must not depend on UI open",
        "invariant": "A page-terminal reconciled table with AUTO_HIGH_CONFIDENCE is READY and not in Review Inbox without any user click",
        "fixture_id": "NATURAL_PAGE_END",
        "severity": "P0",
        "introduced_version": "v6.0",
        "fixed_version": "v6.10",
        "permanent_regression": True,
        "test_location": "tests/test_v610_terminal_boundary_governance.py",
        "validation_kind": "fixture",
        "last_result": None,
    },
    {
        "defect_id": "BUG-003",
        "title": "EXPLICIT_PARENT must not inject non-descendant members",
        "invariant": "time_deposits and long_term_equity are OUTSIDE_FAMILY when an explicit parent with NEW-classification children exists",
        "fixture_id": "EXPLICIT_PARENT_WITH_EXTERNAL_INVESTMENT_ROWS",
        "severity": "P0",
        "introduced_version": "v6.7",
        "fixed_version": "v6.10",
        "permanent_regression": True,
        "test_location": "tests/test_v610_financial_investment_boundary.py",
        "validation_kind": "fixture",
        "last_result": None,
    },
    {
        "defect_id": "BUG-004",
        "title": "UI must display certification_score not base_score",
        "invariant": "The child link UI shows certification_score (composite) as the primary score, not base_score (retrieval prior)",
        "fixture_id": None,
        "severity": "P0",
        "introduced_version": "v6.8",
        "fixed_version": "v6.10",
        "permanent_regression": True,
        "test_location": "UI manual inspection",
        "validation_kind": "ui_certification_score",
        "last_result": None,
    },
    {
        "defect_id": "BUG-005",
        "title": "Stage B dual entry must share execution flow",
        "invariant": "Both strict-child-mapping and explicit-note-target flows use the same CertifiedChildCaptureExecutionPanel component and ChildCaptureExecutionService",
        "fixture_id": None,
        "severity": "P0",
        "introduced_version": "v6.8",
        "fixed_version": "v6.10",
        "permanent_regression": True,
        "test_location": "tests/test_v610_stage_b_unified_flow.py",
        "validation_kind": "stage_b_shared_flow",
        "last_result": None,
    },
    {
        "defect_id": "BUG-006",
        "title": "expected coverage must not use actual/actual",
        "invariant": "Member coverage denominator is len(expected_required_members) from ExpectedMemberResolver, not len(discovered_members)",
        "fixture_id": "EXPLICIT_PARENT_STANDARD",
        "severity": "P0",
        "introduced_version": "v6.7",
        "fixed_version": "v6.10",
        "permanent_regression": True,
        "test_location": "tests/test_v610_financial_investment_boundary.py::test_cpic_2024_four_members",
        "validation_kind": "fixture",
        "last_result": None,
    },
    {
        "defect_id": "BUG-007",
        "title": "Review Inbox must only route, not recompute state",
        "invariant": "The Review Inbox displays captures that are already REVIEW_REQUIRED; it does not call capture_readiness() or change quality_status",
        "fixture_id": None,
        "severity": "P0",
        "introduced_version": "v6.8",
        "fixed_version": "v6.11",
        "permanent_regression": True,
        "test_location": "CaptureDecisionReducer integration",
        "validation_kind": "review_inbox_read_only",
        "last_result": None,
    },
    {
        "defect_id": "BUG-008",
        "title": "China Life implicit member set must not fabricate parent",
        "invariant": "When IMPLICIT_MEMBER_SET is resolved, raw_parent_row_id and raw_parent_label are NULL",
        "fixture_id": "IMPLICIT_MEMBER_SET_SCATTERED",
        "severity": "P0",
        "introduced_version": "v6.7",
        "fixed_version": "v6.10",
        "permanent_regression": True,
        "test_location": "tests/test_v610_financial_investment_boundary.py::test_china_life_implicit_member_set",
        "validation_kind": "fixture",
        "last_result": None,
    },
    {
        "defect_id": "BUG-009",
        "title": "OCR discovery must not generate or modify financial amounts",
        "invariant": "OCR-based statement discovery only locates structure; parsed_decimal_value comes from PDF visual/text evidence only",
        "fixture_id": "IMAGE_DOMINANT_STATEMENT_DISCOVERY",
        "severity": "P0",
        "introduced_version": "v6.4",
        "fixed_version": "v6.10",
        "permanent_regression": True,
        "test_location": "conditional_statement_ocr.py contract",
        "validation_kind": "fixture",
        "last_result": None,
    },
    {
        "defect_id": "BUG-010",
        "title": "first total must not terminate a multi-block table",
        "invariant": "A local total followed by aligned classified rows does not become the hard table end",
        "fixture_id": None,
        "severity": "P0",
        "introduced_version": "v6.9-or-earlier",
        "fixed_version": "v6.11",
        "permanent_regression": True,
        "test_location": "tests/test_v611_multiblock_capture.py::test_split_label_numeric_rows_do_not_turn_local_total_into_hard_end",
        "validation_kind": "multiblock_first_total",
        "last_result": None,
    },
    {
        "defect_id": "BUG-011",
        "title": "classification axes after a local total must survive",
        "invariant": "Measurement-composition and listing-status blocks after the first total remain ordered members of one note container",
        "fixture_id": None,
        "severity": "P0",
        "introduced_version": "v6.9-or-earlier",
        "fixed_version": "v6.11",
        "permanent_regression": True,
        "test_location": "tests/test_v611_multiblock_capture.py::test_axis_state_machine_builds_three_ordered_blocks",
        "validation_kind": "multiblock_axis_state",
        "last_result": None,
    },
    {
        "defect_id": "BUG-012",
        "title": "multi-block capture capability must not regress",
        "invariant": "All note-container and block dimensions survive capture JSON, canonical materialization, merge, registry, and UI",
        "fixture_id": None,
        "severity": "P0",
        "introduced_version": "v6.11",
        "fixed_version": "v6.11",
        "permanent_regression": True,
        "test_location": "tests/test_v611_multiblock_capture.py",
        "validation_kind": "multiblock_field_propagation",
        "last_result": None,
    },
]


def validate_all() -> dict[str, Any]:
    """Execute every registered invariant and return auditable results.

    A registry entry is never counted as passed merely because it exists.  The
    fixture contracts run through production resolvers, while the UI and
    multi-block contracts execute targeted structural/behavioral probes.
    """
    results: dict[str, Any] = {"passed": [], "failed": [], "not_run": []}
    for defect in DEFECT_INVARIANTS:
        defect_id = str(defect["defect_id"])
        try:
            evidence = _execute_invariant(defect)
            status = "PASS" if evidence.get("passed") is True else "FAIL"
            row = {
                "defect_id": defect_id,
                "status": status,
                "test_location": defect["test_location"],
                "evidence": evidence,
            }
            defect["last_result"] = status
            results["passed" if status == "PASS" else "failed"].append(row)
        except NotImplementedError as exc:
            defect["last_result"] = "NOT_RUN"
            results["not_run"].append(
                {
                    "defect_id": defect_id,
                    "status": "NOT_RUN",
                    "test_location": defect["test_location"],
                    "reason": str(exc),
                }
            )
        except Exception as exc:  # a broken probe is a failed release contract
            defect["last_result"] = "FAIL"
            results["failed"].append(
                {
                    "defect_id": defect_id,
                    "status": "FAIL",
                    "test_location": defect["test_location"],
                    "evidence": {
                        "passed": False,
                        "exception_type": type(exc).__name__,
                        "exception": str(exc),
                    },
                }
            )
    return results


def _execute_invariant(defect: dict[str, Any]) -> dict[str, Any]:
    kind = str(defect.get("validation_kind") or "")
    if kind == "fixture":
        from synthetic_domain_fixtures import run_fixture

        fixture_id = str(defect["fixture_id"])
        result = run_fixture(fixture_id)
        return {
            "passed": result.get("status") == "PASS",
            "fixture_id": fixture_id,
            "fixture_status": result.get("status"),
            "actual": result.get("actual"),
        }
    if kind == "ui_certification_score":
        return _validate_ui_certification_score()
    if kind == "stage_b_shared_flow":
        return _validate_stage_b_shared_flow()
    if kind == "review_inbox_read_only":
        return _validate_review_inbox_read_only()
    if kind.startswith("multiblock_"):
        return _validate_multiblock_contract(kind)
    raise NotImplementedError(f"no executable validator for {defect['defect_id']}")


def _source(relative_path: str) -> str:
    return (Path(__file__).resolve().parent / relative_path).read_text(
        encoding="utf-8"
    )


def _validate_ui_certification_score() -> dict[str, Any]:
    sources = {
        "guided_workflow_ui.py": _source("guided_workflow_ui.py"),
        "components/child_mapping_review.py": _source(
            "components/child_mapping_review.py"
        ),
    }
    certification_occurrences = sum(
        text.count("certification_score") for text in sources.values()
    )
    primary_base_score_occurrences = sum(
        text.count("['base_score']") + text.count('["base_score"]')
        for text in sources.values()
    )
    return {
        "passed": (
            certification_occurrences >= 4
            and primary_base_score_occurrences == 0
        ),
        "certification_score_occurrences": certification_occurrences,
        "primary_base_score_occurrences": primary_base_score_occurrences,
    }


def _validate_stage_b_shared_flow() -> dict[str, Any]:
    workflow = _source("guided_workflow_ui.py")
    panel = _source("components/child_capture_execution_panel.py")
    service = _source("services/child_capture_execution_service.py")
    shared_panel_calls = workflow.count("render_child_capture_execution_panel(")
    service_calls = panel.count("child_capture_execution_service")
    has_db_restore = (
        "restore_execution(" in panel
        and "preview_capture_plans(" in panel
        and "prepare_capture_plans(" not in panel
        and "stage_b_execution_sessions" in service
    )
    has_one_callback = (
        'CALLBACK_KEY = "GuidedCaptureService.execute"' in service
        and "self.guided_capture.execute(" in service
    )
    has_both_adapters = (
        '"entry_origin":"STRICT"' in service
        and "certified_links" in service
        and "plans" in service
    )
    return {
        "passed": (
            shared_panel_calls == 1
            and service_calls >= 1
            and has_db_restore
            and has_one_callback
            and has_both_adapters
        ),
        "shared_panel_calls": shared_panel_calls,
        "shared_service_calls": service_calls,
        "db_restore": has_db_restore,
        "single_callback": has_one_callback,
        "strict_and_compat_adapters": has_both_adapters,
    }


def _validate_review_inbox_read_only() -> dict[str, Any]:
    paths = (
        "review_inbox_ui.py",
        "guided_workflow_ui.py",
        "components/review_action_panel.py",
    )
    forbidden = (
        "capture_readiness(",
        ".materialize(",
        ".materialize_all(",
        "materialize_decision_in_tx(",
    )
    findings: dict[str, list[str]] = {}
    for path in paths:
        text = _source(path)
        hits = [token for token in forbidden if token in text]
        if hits:
            findings[path] = hits
    return {"passed": not findings, "forbidden_ui_calls": findings}


def _validate_multiblock_contract(kind: str) -> dict[str, Any]:
    test_path = (
        Path(__file__).resolve().parent
        / "tests"
        / "test_v611_multiblock_capture.py"
    )
    spec = importlib.util.spec_from_file_location(
        "_v611_multiblock_invariant_probes", test_path
    )
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load invariant probes: {test_path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    probes = {
        "multiblock_first_total": [
            "test_split_label_numeric_rows_do_not_turn_local_total_into_hard_end",
        ],
        "multiblock_axis_state": [
            "test_axis_state_machine_builds_three_ordered_blocks",
        ],
        "multiblock_field_propagation": [
            "test_block_fields_survive_json_and_canonical_long",
            "test_canonical_materializer_preserves_block_dimensions",
        ],
    }
    executed: list[str] = []
    for name in probes[kind]:
        getattr(module, name)()
        executed.append(name)
    return {"passed": True, "executed_probes": executed}
