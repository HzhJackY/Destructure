from golden_acceptance import compare_statement_anchor
from generic_discovery import assemble_statement_occurrences
from generic_structure_parser import GenericStructureParser
from statement_family_resolution import CpicRowParser, StatementFamilyResolver


def _word(x0, y0, x1, y1, text):
    return (x0, y0, x1, y1, text)


def test_cpic_spatial_amount_is_period_bound_anchor_evidence_not_certified_value():
    member = {
        "member_id": "debt_investment",
        "display_name": "债权投资",
        "canonical_order": 1,
        "payload": {"aliases": []},
    }
    words = [
        _word(120, 10, 155, 22, "附注"),
        _word(200, 10, 240, 22, "2023"),
        _word(320, 10, 360, 22, "2022"),
        _word(20, 50, 72, 62, "债权"),
        _word(75, 50, 112, 62, "投资"),
        _word(128, 50, 140, 62, "11"),
        _word(195, 50, 285, 62, "5,567,857"),
        _word(315, 50, 395, 62, "6,000,913"),
    ]
    row = CpicRowParser().parse_spatial(words, [("债权投资", member)], "中国太保")[0]

    assert row["statement_amount_raw"] == "5,567,857"
    assert row["ocr_spatial_geometry_verified"] is True
    assert row["value_evidence_status"] == "OCR_SPATIAL_COLUMN_GEOMETRY_OBSERVATION"
    assert [(item["period_label"], item["raw_value"]) for item in row["anchor_amount_observations"]] == [
        ("2023", "5,567,857"),
        ("2022", "6,000,913"),
    ]


def test_cpic_spatial_amount_accepts_dotted_thousands_separator():
    """OCR dot separators (4.986,274) must not drop the current-period value."""
    member = {
        "member_id": "debt_investment",
        "display_name": "债权投资",
        "canonical_order": 1,
        "payload": {"aliases": []},
    }
    words = [
        _word(120, 10, 155, 22, "附注"),
        _word(200, 10, 240, 22, "2024"),
        _word(320, 10, 360, 22, "2023"),
        _word(20, 50, 72, 62, "债权"),
        _word(75, 50, 112, 62, "投资"),
        _word(128, 50, 140, 62, "6"),
        _word(195, 50, 285, 62, "4.986,274"),
        _word(315, 50, 395, 62, "5,567,857"),
    ]
    row = CpicRowParser().parse_spatial(words, [("债权投资", member)], "中国太保")[0]
    assert [
        (item["period_label"], item["raw_value"])
        for item in row["anchor_amount_observations"]
    ] == [
        ("2024", "4.986,274"),
        ("2023", "5,567,857"),
    ]


def test_golden_anchor_matches_dotted_current_period_amount():
    """太保2024 债权投资 current value OCR'd as 4.986,274 still matches."""
    result = compare_statement_anchor(
        "中国太保",
        "2024",
        [
            {
                "canonical_concept_id": "fvtpl_assets",
                "member_table": "fvtpl_assets",
                "note_reference": "附注六-5",
                "anchor_amount_observations": [
                    {"period_label": "2024", "raw_value": "564,558,855"},
                ],
            },
            {
                "canonical_concept_id": "debt_investment",
                "member_table": "debt_investment",
                "note_reference": "附注六-6",
                "anchor_amount_observations": [
                    {"period_label": "2024", "raw_value": "4.986,274"},
                    {"period_label": "2023", "raw_value": "5,567,857"},
                ],
            },
            {
                "canonical_concept_id": "other_debt_investment",
                "member_table": "other_debt_investment",
                "note_reference": "附注六-7",
                "anchor_amount_observations": [
                    {"period_label": "2024", "raw_value": "1,532,157,546"},
                ],
            },
            {
                "canonical_concept_id": "other_equity_investment",
                "member_table": "other_equity_investment",
                "note_reference": "附注六-8",
                "anchor_amount_observations": [
                    {"period_label": "2024", "raw_value": "139,706,315"},
                ],
            },
        ],
    )
    assert result["status"] == "MATCH"
    assert result["missing_current_members"] == []


def test_golden_anchor_2025_matches_dotted_current_period_amounts():
    """太保2025 交易性金融资产/其他债权投资 current OCR dots still match."""
    result = compare_statement_anchor(
        "中国太保",
        "2025",
        [
            {
                "canonical_concept_id": "fvtpl_assets",
                "member_table": "fvtpl_assets",
                "note_reference": "附注六-5",
                "anchor_amount_observations": [
                    {"period_label": "2025", "raw_value": "611.682.378"},
                    {"period_label": "2024", "raw_value": "564,558,855"},
                ],
            },
            {
                "canonical_concept_id": "debt_investment",
                "member_table": "debt_investment",
                "note_reference": "附注六-6",
                "anchor_amount_observations": [
                    {"period_label": "2025", "raw_value": "5,653,378"},
                    {"period_label": "2024", "raw_value": "4,986,274"},
                ],
            },
            {
                "canonical_concept_id": "other_debt_investment",
                "member_table": "other_debt_investment",
                "note_reference": "附注六-7",
                "anchor_amount_observations": [
                    {"period_label": "2025", "raw_value": "1.674.277.381"},
                    {"period_label": "2024", "raw_value": "1,532,157,546"},
                ],
            },
            {
                "canonical_concept_id": "other_equity_investment",
                "member_table": "other_equity_investment",
                "note_reference": "附注六-8",
                "anchor_amount_observations": [
                    {"period_label": "2025", "raw_value": "171,143,582"},
                    {"period_label": "2024", "raw_value": "139,706,315"},
                ],
            },
        ],
    )
    assert result["status"] == "MATCH"
    assert result["missing_current_members"] == []


def test_golden_anchor_reads_only_bbox_bound_ocr_anchor_observation():
    result = compare_statement_anchor(
        "中国太保",
        "2023",
        [
            {
                "member_table": "交易性金融资产",
                "note_reference": "10",
                "statement_amount_raw": [],
                "anchor_amount_observations": [{"period_label": "2023", "raw_value": "484,418,369"}],
            },
            {
                "member_table": "债权投资",
                "note_reference": "11",
                "statement_amount_raw": [],
                "anchor_amount_observations": [{"period_label": "2023", "raw_value": "5,567,857"}],
            },
            {
                "member_table": "其他债权投资",
                "note_reference": "12",
                "statement_amount_raw": [],
                "anchor_amount_observations": [{"period_label": "2023", "raw_value": "1,186,531,148"}],
            },
            {
                "member_table": "其他权益工具投资",
                "note_reference": "13",
                "statement_amount_raw": [],
                "anchor_amount_observations": [{"period_label": "2023", "raw_value": "108,725,948"}],
            },
            # Golden also records legacy comparative members for the 2023
            # filing; their main-statement values are bound to the displayed
            # 2022 column and remain non-certified Anchor evidence.
            {
                "member_table": "可供出售金融资产",
                "note_reference": "7",
                "statement_amount_raw": [],
                "anchor_amount_observations": [{"period_label": "2022", "raw_value": "605,373,941"}],
            },
            {
                "member_table": "持有至到期投资",
                "note_reference": "8",
                "statement_amount_raw": [],
                "anchor_amount_observations": [{"period_label": "2022", "raw_value": "487,672,416"}],
            },
        ],
    )
    # legacy_loans is intentionally omitted: this test proves that a
    # BBox-bound OCR observation reaches the amount comparison; it does not
    # certify the entire filing contract.
    assert result["rows"][0]["amount_match"] is True
    assert result["rows"][1]["amount_match"] is True


def test_spatial_anchor_observation_survives_resolver_and_occurrence_assembly():
    member = {
        "member_id": "debt_investment",
        "display_name": "债权投资",
        "member_role": "NOTE_DETAIL",
        "canonical_order": 1,
        "payload": {"aliases": [], "direct_member": False},
    }
    words = [
        _word(120, 10, 155, 22, "附注"), _word(200, 10, 240, 22, "2023"), _word(320, 10, 360, 22, "2022"),
        _word(20, 50, 72, 62, "债权"), _word(75, 50, 112, 62, "投资"), _word(128, 50, 140, 62, "11"),
        _word(195, 50, 285, 62, "5,567,857"), _word(315, 50, 395, 62, "6,000,913"),
    ]
    parsed = CpicRowParser().parse_spatial(words, [("债权投资", member)], "中国太保")[0]
    source = {
        "statement_pdf_page_index": 74,
        "scope": "CONSOLIDATED",
        "statement_item": "债权投资",
        "member_table": "debt_investment",
        "statement_amount_raw": [],
        "ocr_used": True,
        "note_reference_normalized": "附注七-11",
        "note_reference_section": "附注七",
        "note_reference_item": "11",
        "note_reference_status": "COMPOSED_FROM_HEADER_AND_ROW",
        "candidate_note_pdf_page_index": 170,
        "candidate_note_pages": [170],
        "locator_method": "EXPLICIT_NOTE_REFERENCE",
        "confidence": 1.0,
        "anchor_amount_observations": parsed["anchor_amount_observations"],
        "anchor_period_observations": parsed["anchor_period_observations"],
        "ocr_spatial_geometry_verified": True,
        "evidence": {"raw_line": parsed["source_line"], "ocr_used": True},
    }
    family = {
        "family_id": "financial_investment", "display_name": "金融投资", "definition_version": "TEST",
        "payload": {"preferred_scope": "CONSOLIDATED", "core_members": ["debt_investment"],
                    "family_resolution_contract": {"allowed_resolution_modes": ["IMPLICIT_MEMBER_SET"], "direct_member_concepts": []}},
    }
    candidates, _ = StatementFamilyResolver().resolve_discovered_rows(
        rows=[source], family=family, members=[member], company="中国太保", report_year="2023", filing_type="ANNUAL_REPORT",
    )
    assert candidates[0]["statement_amount_raw"] == []
    assert candidates[0]["value_evidence_status"] == "OCR_SPATIAL_COLUMN_GEOMETRY_OBSERVATION"
    assert candidates[0]["anchor_amount_observations"][0]["raw_value"] == "5,567,857"
    occurrence = assemble_statement_occurrences(candidates)[0]
    assert occurrence["child_rows"][0]["anchor_amount_observations"][0]["period_label"] == "2023"


def test_ui_structure_parser_preserves_spatial_ocr_anchor_evidence_without_promoting_value():
    source = {
        "pdf_id": "CPIC_2023", "statement_type": "BALANCE_SHEET",
        "scope": "CONSOLIDATED", "statement_pdf_page_index": 74,
        "source_table_title": "合并资产负债表", "display_name": "金融投资",
        "statement_item": "债权投资", "member_table": "debt_investment",
        "member_period_status": "ACTIVE_CURRENT_PERIOD", "ocr_used": True,
        "native_value_geometry_present": False,
        "statement_amount_raw": [], "statement_amount_normalized": [],
        "statement_amounts": [], "note_reference_normalized": "附注七-11",
        "candidate_note_pdf_page_index": 170, "confidence": 1.0,
        "anchor_amount_observations": [{"period_label": "2023", "raw_value": "5,567,857"}],
        "anchor_period_observations": [{"period_label": "2023", "column_index": 0}],
        "ocr_spatial_geometry_verified": True,
        "evidence": {"ocr_used": True},
    }
    occurrence = GenericStructureParser().parse(
        [source], strategy="STATEMENT_PARENT_TO_MULTI_NOTE",
        family_id="financial_investment", display_name="金融投资",
    )[0]
    child = occurrence["child_rows"][0]
    assert child["statement_amount_raw"] == []
    assert child["anchor_amount_observations"][0]["raw_value"] == "5,567,857"
    assert child["value_evidence_status"] == "OCR_SPATIAL_COLUMN_GEOMETRY_OBSERVATION"
    assert child["stage_b_eligibility"] == "ELIGIBLE"
