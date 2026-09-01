"""Contract tests for the isolated real 12-filing matrix v3 runner."""
from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[3]
RUNNER_PATH = (
    REPO_ROOT
    / "output"
    / "_agent_runs"
    / "v611_codex_takeover"
    / "matrix_v3_impl"
    / "run_real_12_filing_matrix_v3.py"
)
SPEC = importlib.util.spec_from_file_location("matrix_v3_runner", RUNNER_PATH)
assert SPEC and SPEC.loader
runner = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(runner)


EXPECTED_COLUMNS = [
    "company",
    "year",
    "pdf_sha256",
    "document_modality",
    "discovery_status",
    "ocr_routing_status",
    "ocr_resolution_status",
    "resolution_mode",
    "presentation_regime",
    "expected_member_count",
    "discovered_member_count",
    "missing_members",
    "unexpected_members",
    "comparative_only_members",
    "child_link_status",
    "capture_status",
    "canonical_status",
    "merge_eligibility",
    "review_status",
    "review_actionability",
    "final_status",
    "failure_stage",
]


def _base_row() -> dict:
    return {
        "company": "测试公司",
        "year": "2025",
        "pdf_sha256": "a" * 64,
        "document_modality": "TEXT_DOMINANT",
        "discovery_status": "RESOLVED",
        "ocr_routing_status": "OCR_NOT_NEEDED",
        "ocr_resolution_status": "NOT_APPLICABLE",
        "resolution_mode": "EXPLICIT_PARENT",
        "presentation_regime": "NEW_FINANCIAL_INSTRUMENT_CLASSIFICATION",
        "expected_member_count": 4,
        "discovered_member_count": 4,
        "missing_members": "[]",
        "unexpected_members": "[]",
        "comparative_only_members": "[]",
        "child_link_status": "CERTIFIED",
        "capture_status": "COMPLETED",
        "canonical_status": "COMPLETED",
        "merge_eligibility": "ELIGIBLE",
        "review_status": "APPROVED",
        "review_actionability": "",
        "final_status": "PASS",
        "failure_stage": "",
    }


def test_exact_22_column_contract_and_allowed_terminal_statuses() -> None:
    assert runner.MATRIX_COLUMNS == EXPECTED_COLUMNS
    assert runner.ALLOWED_FINAL_STATUSES == {
        "PASS",
        "REVIEW_REQUIRED_ACTIONABLE",
        "BLOCKED",
        "NOT_RUN",
    }
    assert runner.RUNTIME_ROOT == (
        REPO_ROOT
        / "output"
        / "_agent_runs"
        / "v611_codex_takeover"
        / "matrix_v3_runtime"
    )


def test_document_contract_is_exactly_four_companies_by_three_years() -> None:
    pairs = {
        (item["company"], item["year"])
        for item in runner.DOCUMENTS
    }
    assert len(runner.DOCUMENTS) == 12
    assert pairs == {
        (company, year)
        for company in ("中国平安", "中国太保", "新华保险", "中国人寿")
        for year in ("2023", "2024", "2025")
    }
    assert all(
        str(item["pdf_name"]).endswith(".pdf")
        for item in runner.DOCUMENTS
    )


def test_runner_declares_only_official_v611_chain_and_no_old_matrix_import() -> None:
    source = RUNNER_PATH.read_text(encoding="utf-8")
    for required in (
        "build_backend_services",
        "generic_discovery_service.discover",
        "resolve_expected_members",
        "resolve_note_targets",
        "guided_capture_service.execute",
        "merge_eligibility_service.eligible_assets",
    ):
        assert required in source
    assert "run_12_filing_matrix" not in source
    assert "_resolution_from_discovered_rows" not in source


def test_pass_requires_full_chain_evidence() -> None:
    row = _base_row()
    runner.validate_matrix_row(row)
    for field, unsafe in (
        ("discovery_status", "NO_CANDIDATE"),
        ("child_link_status", "REVIEW_REQUIRED_ACTIONABLE"),
        ("capture_status", "NOT_RUN"),
        ("canonical_status", "NOT_RUN"),
        ("merge_eligibility", "NOT_ELIGIBLE"),
    ):
        broken = {**row, field: unsafe}
        with pytest.raises(ValueError, match="PASS_REQUIRES_FULL_CHAIN"):
            runner.validate_matrix_row(broken)


def test_actionable_requires_specific_action_and_unified_ui_route() -> None:
    row = {
        **_base_row(),
        "final_status": "REVIEW_REQUIRED_ACTIONABLE",
        "review_status": "REVIEW_REQUIRED_ACTIONABLE",
        "failure_stage": "DISCOVERY",
        "review_actionability": (
            "ACTION=人工确认主表父项与四个成员；"
            "UI_ROUTE=DISCOVERY_REVIEW/financial_investment"
        ),
        "capture_status": "NOT_RUN",
        "canonical_status": "NOT_RUN",
        "merge_eligibility": "NOT_ELIGIBLE",
    }
    runner.validate_matrix_row(row)
    for actionability in (
        "",
        "ACTION=人工确认主表父项",
        "UI_ROUTE=DISCOVERY_REVIEW/financial_investment",
    ):
        with pytest.raises(ValueError, match="ACTIONABLE_REQUIRES_ACTION_AND_UI_ROUTE"):
            runner.validate_matrix_row(
                {**row, "review_actionability": actionability}
            )


def test_ocr_needed_can_never_be_pass() -> None:
    row = {
        **_base_row(),
        "ocr_routing_status": "OCR_NEEDED",
    }
    with pytest.raises(ValueError, match="OCR_NEEDED_IS_NOT_PASS"):
        runner.validate_matrix_row(row)


def test_sha_and_cardinality_contracts() -> None:
    row = _base_row()
    with pytest.raises(ValueError, match="PDF_SHA256"):
        runner.validate_matrix_row({**row, "pdf_sha256": "abc"})
    with pytest.raises(ValueError, match="DISCOVERED_MEMBER_COUNT"):
        runner.validate_matrix_row(
            {
                **row,
                "discovered_member_count": 5,
                "expected_member_count": 4,
            }
        )
