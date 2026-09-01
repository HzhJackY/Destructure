from pathlib import Path
from types import SimpleNamespace

import conditional_statement_ocr as ocr
from anchor_candidate_selection import score_anchor_candidate
from period_identity import normalize_period_token
from services.discovery_service import DiscoveryService
from statement_anchor_evidence_v2 import _note_reference, _sequence_shape


def test_period_identity_supports_year_month_quarter_and_half_year():
    expected = {
        "2024年": "YEAR:2024",
        "2024年3月": "MONTH:2024-03",
        "2024年第1季度": "QUARTER:2024-Q1",
        "2024Q2": "QUARTER:2024-Q2",
        "2024年上半年": "HALF:2024-H1",
        "2024H2": "HALF:2024-H2",
    }
    assert {token: normalize_period_token(token)["period_identity"] for token in expected} == expected


def test_full_document_batches_are_untried_and_fixed_size(monkeypatch, tmp_path):
    calls = []

    def fake_group(pdf_path, *, page_numbers, recovery_stage, **kwargs):
        calls.append((tuple(page_numbers), recovery_stage))
        return ({page: {"ocr_words": [], "metadata": {}} for page in page_numbers}, {"ocr_pages": list(page_numbers)})

    monkeypatch.setattr(ocr, "ocr_statement_page_group", fake_group)
    batches = list(ocr.iter_full_document_ocr_batches(
        Path("fixture.pdf"), cache_root=tmp_path, page_count=27, attempted_pages={2, 14},
        config={"full_document_ocr_batch_size": 12},
    ))
    assert [call[0] for call in calls] == [
        (1, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13),
        (15, 16, 17, 18, 19, 20, 21, 22, 23, 24, 25, 26),
        (27,),
    ]
    assert all(call[1] == "FULL_DOCUMENT_RECOVERY" for call in calls)
    assert [audit["full_document_ocr_batch_index"] for _, audit in batches] == [1, 2, 3]


def test_explicit_page_group_limits_fast_index_to_requested_pages(monkeypatch, tmp_path):
    captured = {}

    def fake_fast_index(*args, **kwargs):
        captured.update(kwargs)
        return [
            SimpleNamespace(page=3, text="", ocr_words=[], ocr_rows=[]),
            SimpleNamespace(page=9, text="", ocr_words=[], ocr_rows=[]),
        ], {"cache_hit": False, "ocr_page_cache_path": "", "ocr_page_cache_hit_pages": []}

    monkeypatch.setattr(ocr, "build_fast_index", fake_fast_index)
    ocr.ocr_statement_page_group(
        Path("fixture.pdf"), cache_root=tmp_path, page_numbers=[3, 9],
        native_page_count=12, recovery_stage="FULL_DOCUMENT_RECOVERY",
    )
    assert captured["page_subset"] == {3, 9}
    assert captured["force_ocr_pages"] == {3, 9}
    assert captured["ocr_psm"] == 4
    assert captured["require_ocr_geometry_metadata"] is True


def test_scope_conflict_never_becomes_a_recoverable_ocr_gap():
    candidate = score_anchor_candidate({
        "pdf_id": "fixture.pdf", "scope": "PARENT_COMPANY", "source_statement_scope": "PARENT_COMPANY",
        "report_year": "2024", "statement_type": "BALANCE_SHEET", "parent_text": "金融投资",
        "display_name": "金融投资", "child_rows": [{"value": 1}] * 4,
        "evidence": {
            "schema_version": "STATEMENT_ANCHOR_EVIDENCE_V2", "source_statement_scope": "PARENT_COMPANY",
            "period_columns": [{"period_year": 2024, "period_role": "CURRENT"}],
            "members": [{"member_table": key} for key in ("fvtpl_assets", "debt_investment", "other_debt_investment", "other_equity_investment")],
            "unit": "人民币百万元", "value_geometry_verified": True,
        },
    }, {"scope_preference": "CONSOLIDATED", "required_member_tables": ["fvtpl_assets", "debt_investment", "other_debt_investment", "other_equity_investment"]})
    assert candidate["hard_gate_results"]["scope_compatible"] is False
    assert DiscoveryService._recoverable_evidence_gap(candidate) is False


def test_note_ordinal_contract_rejects_amount_like_and_over_cap_tokens():
    assert _note_reference("5", 150) == ("5", [5], None)
    assert _note_reference("1,000", 150)[2] == "NOTE_ORDINAL_OVER_CAP"
    assert _note_reference("5.0", 150)[2] == "NOTE_ORDINAL_OVER_CAP"
    assert _note_reference("（附注五、2）", 150)[2] == "NOTE_GRAMMAR_INVALID"
    assert _sequence_shape([3, 5, 5, 8]) == "NON_DECREASING_WITH_GAPS"
    assert _sequence_shape([5, 5, 5]) == "STABLE_REPEAT"
