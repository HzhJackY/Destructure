from financial_investment_period_contract import financial_member_contract_snapshot
from anchor_candidate_selection import score_anchor_candidate
from services.discovery_service import DiscoveryService
from statement_anchor_evidence_v2 import PeriodColumnEvidence, _member_rows, _select_note_topology
from research_definition_registry import FINANCIAL_INVESTMENT_MEMBER_CONTRACT_VERSION
from golden_acceptance import compare_statement_anchor


def _word(x0, x1, text, y=20):
    return (float(x0), float(y), float(x1), float(y + 10), text)


def test_mixed_contract_keeps_current_and_legacy_identities_distinct():
    snapshot = financial_member_contract_snapshot({
        "presentation_regime": "MIXED_TRANSITION_PRESENTATION",
        "scope": "CONSOLIDATED",
    })
    assert snapshot["required_current_members"] == [
        "fvtpl_assets", "debt_investment", "other_debt_investment", "other_equity_investment",
    ]
    aliases = {item["member_table"]: item["aliases"] for item in snapshot["members"]}
    assert "交易性金融资产" in aliases["fvtpl_assets"]
    assert "以公允价值计量且其变动计入当期损益的金融资产" in aliases["fvtpl_assets"]
    assert "以公允价值计量且其变动计入当期损益的金融资产" in aliases["legacy_fvtpl_assets"]
    assert snapshot["contract_version"] == "FINANCIAL_INVESTMENT_MEMBER_CONTRACT_V6"
    assert snapshot["physical_row_identity"] == "SOURCE_ROW_ID__PERIOD_IDENTITY"
    assert snapshot["filing_level_member_mutual_exclusion"] is False
    assert FINANCIAL_INVESTMENT_MEMBER_CONTRACT_VERSION == snapshot["contract_version"]


def test_v6_all_transition_members_have_explicit_bridge_memberships():
    snapshot = financial_member_contract_snapshot({
        "presentation_regime": "MIXED_TRANSITION_PRESENTATION",
        "scope": "CONSOLIDATED",
    })
    specs = {item["member_table"]: item for item in snapshot["members"]}
    assert {item["analysis_bridge_group"] for item in specs["fvtpl_assets"]["analysis_bridge_groups"]} == {"FVTPL_ASSETS"}
    assert {item["analysis_bridge_group"] for item in specs["legacy_loans"]["analysis_bridge_groups"]} == {"AMORTIZED_COST_DEBT"}
    assert {item["analysis_bridge_group"] for item in specs["held_to_maturity_investments"]["analysis_bridge_groups"]} == {"AMORTIZED_COST_DEBT"}
    assert {item["analysis_bridge_group"] for item in specs["available_for_sale_assets"]["analysis_bridge_groups"]} == {"FVOCI_DEBT", "FVOCI_EQUITY"}
    assert specs["time_deposits"]["analysis_bridge_groups"] == []


def test_mixed_long_fvtpl_alias_is_resolved_by_period_values():
    contract = financial_member_contract_snapshot({
        "presentation_regime": "MIXED_TRANSITION_PRESENTATION",
        "scope": "CONSOLIDATED",
    })
    periods = [
        PeriodColumnEvidence("2023年12月31日", 2023, "CURRENT", {"x0": 110, "y0": 0, "x1": 150, "y1": 10}, "DATE:2023-12-31", column_index=0, x_range=(100, 200)),
        PeriodColumnEvidence("2022年12月31日", 2022, "COMPARATIVE", {"x0": 210, "y0": 0, "x1": 250, "y1": 10}, "DATE:2022-12-31", column_index=1, x_range=(200, 300)),
    ]
    label = "以公允价值计量且其变动计入当期损益的金融资产"
    current_rows = _member_rows([
        [_word(0, 50, "金融投资", 0)],
        [_word(0, 90, label, 20), _word(120, 160, "1803047", 20), _word(220, 260, "1640519", 20)],
    ], page=145, periods=periods, parent_aliases=("金融投资",), member_contract=contract)
    assert current_rows[0]["member_table"] == "fvtpl_assets"
    assert current_rows[0]["member_period_status"] == "ACTIVE_CURRENT_PERIOD"

    comparative_rows = _member_rows([
        [_word(0, 50, "金融投资", 0)],
        [_word(0, 90, label, 20), _word(120, 160, "不适用", 20), _word(220, 260, "38301", 20)],
    ], page=142, periods=periods, parent_aliases=("金融投资",), member_contract=contract)
    assert comparative_rows[0]["member_table"] == "legacy_fvtpl_assets"
    assert comparative_rows[0]["member_period_status"] == "COMPARATIVE_ONLY_LEGACY_MEMBER"


def test_new_filing_transition_row_keeps_legacy_long_fvtpl_identity():
    """A new-regime filing can contain both current and comparative vocabularies."""
    contract = financial_member_contract_snapshot({
        "presentation_regime": "NEW_FINANCIAL_INSTRUMENT_CLASSIFICATION",
        "scope": "CONSOLIDATED",
    })
    aliases = {item["member_table"]: item["aliases"] for item in contract["members"]}
    assert "以公允价值计量且其变动计入当期损益的金融资产" in aliases["fvtpl_assets"]
    assert "以公允价值计量且其变动计入当期损益的金融资产" in aliases["legacy_fvtpl_assets"]
    periods = [
        PeriodColumnEvidence("2024年12月31日", 2024, "CURRENT", {"x0": 110, "y0": 0, "x1": 150, "y1": 10}, "DATE:2024-12-31", column_index=0, x_range=(100, 200)),
        PeriodColumnEvidence("2023年12月31日", 2023, "COMPARATIVE", {"x0": 210, "y0": 0, "x1": 250, "y1": 10}, "DATE:2023-12-31", column_index=1, x_range=(200, 300)),
    ]
    rows = _member_rows([
        [_word(0, 50, "金融投资", 0)],
        [_word(0, 90, "交易性金融资产", 20), _word(120, 160, "1908098", 20), _word(220, 260, "不适用", 20)],
        [_word(0, 90, "以公允价值计量且其变动计入当期损益的金融资产", 40), _word(120, 160, "不适用", 40), _word(220, 260, "257054", 40)],
    ], page=96, periods=periods, parent_aliases=("金融投资",), member_contract=contract)
    by_id = {row["member_table"]: row for row in rows}
    assert by_id["fvtpl_assets"]["member_period_status"] == "ACTIVE_CURRENT_PERIOD"
    assert by_id["legacy_fvtpl_assets"]["member_period_status"] == "COMPARATIVE_ONLY_LEGACY_MEMBER"


def test_transition_page_retains_not_applicable_as_period_semantics():
    contract = financial_member_contract_snapshot({
        "presentation_regime": "MIXED_TRANSITION_PRESENTATION",
        "scope": "CONSOLIDATED",
    })
    periods = [
        PeriodColumnEvidence("2023年12月31日", 2023, "CURRENT", {"x0": 110, "y0": 0, "x1": 150, "y1": 10}, "DATE:2023-12-31", column_index=0, x_range=(100, 200)),
        PeriodColumnEvidence("2022年12月31日", 2022, "COMPARATIVE", {"x0": 210, "y0": 0, "x1": 250, "y1": 10}, "DATE:2022-12-31", column_index=1, x_range=(200, 300)),
    ]
    rows = [[_word(0, 50, "金融投资", 0)]]
    current = [
        ("交易性金融资产", "383020"),
        ("债权投资", "318605"),
        ("其他债权投资", "338717"),
        ("其他权益工具投资", "96541"),
    ]
    for index, (label, value) in enumerate(current, 1):
        rows.append([_word(0, 90, label, index * 20), _word(120, 160, value, index * 20), _word(220, 260, "不适用", index * 20)])
    rows.extend([
        [_word(0, 90, "以公允价值计量且其变动计入当期损益的金融资产", 120), _word(120, 160, "不适用", 120), _word(220, 260, "38301", 120)],
        [_word(0, 90, "贷款及应收款项", 140), _word(120, 160, "不适用", 140), _word(220, 260, "557582", 140)],
    ])
    members = _member_rows(
        rows, page=142, periods=periods, parent_aliases=("金融投资",),
        member_contract=contract,
    )
    by_id = {row["member_table"]: row for row in members}
    assert all(by_id[member]["member_period_status"] == "ACTIVE_CURRENT_PERIOD" for member in contract["required_current_members"])
    assert by_id["legacy_fvtpl_assets"]["member_period_status"] == "COMPARATIVE_ONLY_LEGACY_MEMBER"
    assert by_id["legacy_loans"]["member_period_status"] == "COMPARATIVE_ONLY_LEGACY_MEMBER"
    assert by_id["legacy_loans"]["amount_cells"][0]["period_value_status"] == "NOT_APPLICABLE"
    assert by_id["legacy_loans"]["amount_cells"][1]["value"] == 557582


def test_note_topology_is_bound_by_physical_source_row_not_member_identity():
    contract = financial_member_contract_snapshot({
        "presentation_regime": "MIXED_TRANSITION_PRESENTATION",
        "scope": "CONSOLIDATED",
    })
    periods = [
        PeriodColumnEvidence("2023年12月31日", 2023, "CURRENT", {"x0": 110, "y0": 0, "x1": 150, "y1": 10}, "DATE:2023-12-31", column_index=0, x_range=(100, 200)),
        PeriodColumnEvidence("2022年12月31日", 2022, "COMPARATIVE", {"x0": 210, "y0": 0, "x1": 250, "y1": 10}, "DATE:2022-12-31", column_index=1, x_range=(200, 300)),
    ]
    rows = _member_rows([
        [_word(0, 50, "金融投资", 0)],
        [_word(0, 52, "以公允价值计量且其变动计入当期损益的金融资产", 20), _word(60, 68, "2", 20), _word(120, 160, "不适用", 20), _word(220, 260, "26560", 20)],
        [_word(0, 52, "交易性金融资产", 40), _word(60, 68, "10", 40), _word(120, 160, "581602", 40), _word(220, 260, "-", 40)],
    ], page=144, periods=periods, parent_aliases=("金融投资",), member_contract=contract)
    by_member = {row["member_table"]: row for row in rows}
    assert by_member["legacy_fvtpl_assets"]["source_row_id"] != by_member["fvtpl_assets"]["source_row_id"]
    selected, _ = _select_note_topology(
        rows,
        [("附注", {"x0": 58.0, "y0": 0.0, "x1": 70.0, "y1": 10.0})],
        periods,
        page_count=300,
        median_height=10.0,
    )
    observations = selected["observations"]
    assert observations[by_member["legacy_fvtpl_assets"]["source_row_id"]]["reference"] == "2"
    assert observations[by_member["fvtpl_assets"]["source_row_id"]]["reference"] == "10"
    assert by_member["fvtpl_assets"]["amount_cells"][0]["value"] == 581602


def test_stage_a_uses_candidate_contract_instead_of_hardcoded_new_members():
    required = [
        "legacy_fvtpl_assets", "legacy_loans", "time_deposits",
        "available_for_sale_assets", "held_to_maturity_investments",
    ]
    matrix = [{"member_table": member, "member_period_status": "ACTIVE_CURRENT_PERIOD"} for member in required]
    candidate = score_anchor_candidate({
        "pdf_id": "fixture.pdf", "scope": "CONSOLIDATED", "source_statement_scope": "CONSOLIDATED",
        "report_year": "2022", "statement_type": "BALANCE_SHEET", "parent_text": "金融投资",
        "display_name": "金融投资", "child_rows": [{"value": 1}] * len(required),
        "evidence": {
            "schema_version": "STATEMENT_ANCHOR_EVIDENCE_V2", "formal_statement_region": True,
            "source_statement_scope": "CONSOLIDATED", "period_columns": [{"period_year": 2022, "period_role": "CURRENT"}],
            "members": [{"member_table": member} for member in required], "member_period_matrix": matrix,
            "member_contract_snapshot": {"required_current_members": required},
            "required_current_member_status_valid": True, "unit": "人民币百万元",
            "value_geometry_verified": True, "period_geometry_verified": True,
            "row_binding_verified": True, "amount_columns_present": True,
        },
    }, {"scope_preference": "CONSOLIDATED"})
    assert candidate["hard_gate_results"]["required_member_coverage"] is True
    assert candidate["hard_gate_results"]["required_current_member_status_valid"] is True


def test_historical_member_never_generates_stage_b_note_candidates(tmp_path):
    pdf = tmp_path / "fixture.pdf"
    pdf.write_bytes(b"not-used")
    service = object.__new__(DiscoveryService)

    class Resolver:
        def candidates_from_pdf(self, *args, **kwargs):
            raise AssertionError("historical member must not enter Stage B discovery")

    service.note_resolver = Resolver()
    result = service.resolve_note_targets({
        "pdf_id": str(pdf),
        "child_rows": [{
            "member_table": "legacy_loans", "member_period_status": "COMPARATIVE_ONLY_LEGACY_MEMBER",
            "note_reference_normalized": "附注五-2",
        }],
    })
    assert result["child_rows"][0]["note_target_candidates"] == []
    assert result["child_rows"][0]["stage_b_requirement"] == "HISTORICAL_COVERAGE_GAP_NON_BLOCKING"


def test_golden_anchor_comparison_prefers_active_current_over_legacy_alias(tmp_path):
    company = "中国人寿"
    golden = tmp_path / "companies" / "china_life" / "2024"
    golden.mkdir(parents=True)
    (golden / "golden_values.yaml").write_text(
        "values:\n"
        "  - member_id: fvtpl_assets\n"
        "    raw_label: 交易性金融资产\n"
        "    note_reference: 十一、6\n"
        "    current_amount_raw: '1,908,098'\n"
        "    status: ACTIVE_CURRENT_PERIOD\n",
        encoding="utf-8",
    )
    comparison = compare_statement_anchor(company, 2024, [
        {"member_table": "legacy_fvtpl_assets", "member_period_status": "COMPARATIVE_ONLY_LEGACY_MEMBER", "note_reference": "2", "values": []},
        {"member_table": "fvtpl_assets", "member_period_status": "ACTIVE_CURRENT_PERIOD", "note_reference": "6", "values": [1908098]},
    ], root=tmp_path)
    assert comparison["status"] == "MATCH"
    assert comparison["rows"][0]["observed_label"] == "fvtpl_assets"
