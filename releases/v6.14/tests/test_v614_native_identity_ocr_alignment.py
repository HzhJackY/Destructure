from statement_anchor_evidence_v2 import (
    MemberRowEvidence, PeriodColumnEvidence, _hybrid_native_identity_ocr_values,
    _normalize_ocr_words_to_pdf_points,
)


def _word(x0, x1, text, y):
    return (float(x0), float(y), float(x1), float(y + 10), text)


def _periods():
    return [
        PeriodColumnEvidence(
            "2023年12月31日", 2023, "CURRENT", {"x0": 110, "y0": 0, "x1": 180, "y1": 10},
            "DATE:2023-12-31", column_index=0, x_range=(110, 210),
        )
    ]


def _native_member(member, label, y, note=None):
    box = {"x0": 10, "y0": float(y), "x1": 90, "y1": float(y + 10)}
    return MemberRowEvidence(
        member, label, box, f"NATIVE_{member}", "EXPLICIT_CHILD_OF_PARENT", note,
        "EXPLICIT_CERTIFIED_NOTE_COLUMN" if note else "NOTE_REFERENCE_UNRESOLVED", (),
        binding_row_bbox=box, source_line_index=y, identity_source="NATIVE_PDF_WORDS",
    )


def _native(members):
    return {
        "scope": "CONSOLIDATED", "scope_source": "FORMAL_TITLE", "scope_confidence": 1.0,
        "scope_conflict": None, "title": "合并资产负债表", "title_bbox": {"x0": 0, "y0": 0, "x1": 100, "y1": 10},
        "unit": "人民币百万元", "periods": [], "members": members, "parent_identity": "EXPLICIT_PARENT",
        "note_verified": False, "topology_hypotheses": [], "selected_topology_id": None,
        "source": "NATIVE_PDF_WORDS",
    }


def _ocr(lines):
    return {"periods": _periods(), "lines": lines, "page_count": 300, "median_height": 10.0}


def test_pixel_ocr_words_normalize_to_pdf_points_and_require_metadata():
    words = [(200, 400, 300, 440, "贷款")]
    converted, provenance, meta = _normalize_ocr_words_to_pdf_points(
        words,
        {"ocr_geometry_metadata": {
            "geometry_schema_version": "FAST_INDEX_OCR_GEOMETRY_V2",
            "coordinate_space": "RASTER_PIXELS", "render_width": 1200, "render_height": 2400,
        }}, page_width=600, page_height=1200,
    )
    assert converted == [(100.0, 200.0, 150.0, 220.0, "贷款")]
    assert provenance[(100.0, 200.0, 150.0, 220.0, "贷款")]["raw_bbox"]["x0"] == 200.0
    assert meta["normalized_coordinate_space"] == "PDF_POINTS"
    assert _normalize_ocr_words_to_pdf_points(words, {}, page_width=600, page_height=1200)[2] is None


def test_hybrid_preserves_native_member_identity_when_ocr_label_is_wrong():
    native = _native([
        _native_member("fvtpl_assets", "交易性金融资产", 20),
        _native_member("legacy_loans", "分类为贷款及应收款的投资", 40),
    ])
    ocr = _ocr([
        [_word(10, 80, "交易性金融资产", 20), _word(130, 180, "383020", 20)],
        [_word(10, 100, "分类为侧款及应收款的投资", 40), _word(130, 180, "176082", 40)],
    ])
    hybrid, conflicts = _hybrid_native_identity_ocr_values(
        native, ocr,
        contract={"required_current_members": ["fvtpl_assets", "legacy_loans"]},
        ocr_provenance={},
    )
    assert not conflicts
    rows = {row.member_table: row for row in hybrid["members"]}
    assert rows["legacy_loans"].raw_label == "分类为贷款及应收款的投资"
    assert rows["legacy_loans"].source_row_id == "NATIVE_legacy_loans"
    assert rows["legacy_loans"].amount_cells[0]["value"] == 176082
    assert rows["legacy_loans"].alignment_evidence["ocr_label_diagnostic"] == "分类为侧款及应收款的投资"


def test_hybrid_note_mismatch_fails_closed():
    native = _native([
        _native_member("fvtpl_assets", "交易性金融资产", 20, note="3"),
        _native_member("debt_investment", "债权投资", 40, note="5"),
    ])
    ocr = _ocr([
        [_word(70, 100, "附注", 0)],
        [_word(10, 80, "错误标签", 20), _word(80, 90, "4", 20), _word(130, 180, "383020", 20)],
        [_word(10, 80, "债权投资", 40), _word(80, 90, "5", 40), _word(130, 180, "318605", 40)],
    ])
    hybrid, conflicts = _hybrid_native_identity_ocr_values(
        native, ocr, contract={"required_current_members": ["fvtpl_assets", "debt_investment"]}, ocr_provenance={},
    )
    assert hybrid is None
    assert conflicts[0]["status"] == "NATIVE_OCR_CONFLICT"
    assert conflicts[0]["field"] == "note_reference"


def test_anonymous_note_lane_never_becomes_an_amount_cell():
    native = _native([
        _native_member("fvtpl_assets", "交易性金融资产", 20),
        _native_member("debt_investment", "债权投资", 40),
    ])
    ocr = _ocr([
        [_word(70, 100, "附注", 0)],
        [_word(10, 80, "标签", 20), _word(80, 90, "3", 20), _word(130, 180, "383020", 20)],
        [_word(10, 80, "债权投资", 40), _word(80, 90, "4", 40), _word(130, 180, "318605", 40)],
    ])
    hybrid, conflicts = _hybrid_native_identity_ocr_values(
        native, ocr, contract={"required_current_members": ["fvtpl_assets", "debt_investment"]}, ocr_provenance={},
    )
    assert not conflicts
    cells = hybrid["members"][0].amount_cells
    assert [cell["value"] for cell in cells] == [383020]
    assert hybrid["members"][0].alignment_evidence["ocr_note_reference"] == "3"


def test_legacy_financial_family_key_enters_v2_evidence_route():
    from services.discovery_service import DiscoveryService

    assert DiscoveryService._is_financial_investment({"table_family": "financial_investment"})
    assert DiscoveryService._is_financial_investment({"table_family": "FINANCIAL_INVESTMENT_V1"})
    assert not DiscoveryService._is_financial_investment({"table_family": "investment_portfolio"})


def test_combined_scope_is_a_compatible_lane_not_a_ranking_penalty():
    from anchor_candidate_selection import score_anchor_candidate

    candidate = score_anchor_candidate({
        "pdf_id": "fixture.pdf", "scope": "CONSOLIDATED",
        "source_statement_scope": "COMBINED_CONSOLIDATED_AND_PARENT",
        "statement_type": "BALANCE_SHEET", "parent_text": "金融投资",
        "display_name": "金融投资", "child_rows": [{"values": [1]}] * 4,
        "evidence": {"formal_statement_region": True},
    }, {"scope_preference": "CONSOLIDATED"})
    assert candidate["hard_gate_results"]["scope_compatible"] is True
    assert candidate["score_components"]["scope_match"] == 0.05
    assert candidate["score_components"]["scope_conflict_penalty"] == 0.0
