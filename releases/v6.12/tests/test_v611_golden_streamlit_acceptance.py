from pathlib import Path
import shutil
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from golden_acceptance import (
    compare_child_capture_csv,
    compare_child_target,
    compare_statement_anchor,
)


def test_pingan_2023_golden_matches_source_facts():
    result = compare_statement_anchor("中国平安", "2023", [
        {"member_table": "以公允价值计量且其变动计入当期损益的金融资产", "note_reference_normalized": "附注八-9", "values": ["1,803,047"]},
        {"member_table": "债权投资", "note_reference_normalized": "附注八-10", "values": ["1,243,353"]},
        {"member_table": "其他债权投资", "note_reference_normalized": "附注八-11", "values": ["2,637,008"]},
        {"member_table": "其他权益工具投资", "note_reference_normalized": "附注八-12", "values": ["264,877"]},
    ])
    assert result["status"] == "MATCH", result


def test_golden_mismatch_is_not_silently_accepted():
    result = compare_statement_anchor("中国平安", "2023", [
        {"member_table": "债权投资", "note_reference_normalized": "附注八-10", "values": ["1"]},
    ])
    assert result["status"] == "MISMATCH", result


def test_xinhua_2023_current_members_match_while_legacy_comparative_is_not_a_gate():
    result = compare_statement_anchor("新华保险", "2023", [
        {"member_table": "交易性金融资产", "note_reference_normalized": "附注4(11)", "values": ["380,239"]},
        {"member_table": "债权投资", "note_reference_normalized": "附注4(12)", "values": ["313,148"]},
        {"member_table": "其他债权投资", "note_reference_normalized": "附注4(13)", "values": ["347,262"]},
        {"member_table": "其他权益工具投资", "note_reference_normalized": "附注4(14)", "values": ["5,370"]},
    ])
    assert result["status"] == "MATCH", result
    assert result["current_required_member_ids"] == [
        "fvtpl_assets", "debt_investment", "other_debt_investment", "other_equity_investment",
    ]
    assert result["missing_current_members"] == []
    assert result["historical_variants"] == [{
        "member_id": "legacy_fvtpl_assets",
        "golden_label": "以公允价值计量且其变动计入当期损益的金融资产",
        "golden_note": "附注4(15)",
        "golden_status": "RESTATED_COMPARATIVE_PERIOD",
        "observed_in_current_anchor": False,
    }]


def test_xinhua_2023_current_member_is_still_a_blocking_mismatch():
    result = compare_statement_anchor("新华保险", "2023", [
        {"member_table": "交易性金融资产", "note_reference_normalized": "附注4(11)", "values": ["380,239"]},
        {"member_table": "债权投资", "note_reference_normalized": "附注4(12)", "values": ["313,148"]},
        {"member_table": "其他债权投资", "note_reference_normalized": "附注4(13)", "values": ["347,262"]},
    ])
    assert result["status"] == "MISMATCH", result
    assert result["missing_current_members"] == ["other_equity_investment"]


def test_china_life_2023_legacy_loans_alias_matches_full_current_contract():
    result = compare_statement_anchor("中国人寿", "2023", [
        {
            "member_table": "legacy_fvtpl_assets",
            "canonical_concept_id": "legacy_fvtpl_assets",
            "note_reference_normalized": "附注十-2",
            "statement_amount_raw": "253,879",
        },
        {
            "member_table": "legacy_loans",
            "canonical_concept_id": "legacy_loans",
            "note_reference_normalized": "附注十-8",
            "statement_amount_raw": "603,639",
        },
        {
            "member_table": "time_deposits",
            "canonical_concept_id": "time_deposits",
            "note_reference_normalized": "附注十-9",
            "statement_amount_raw": "404,131",
        },
        {
            "member_table": "available_for_sale_assets",
            "canonical_concept_id": "available_for_sale_assets",
            "note_reference_normalized": "附注十-10",
            "statement_amount_raw": "2,263,047",
        },
        {
            "member_table": "held_to_maturity_investments",
            "canonical_concept_id": "held_to_maturity_investments",
            "note_reference_normalized": "附注十-11",
            "statement_amount_raw": "1,706,441",
        },
    ])

    assert result["status"] == "MATCH", result
    assert result["missing_current_members"] == []
    loans = next(row for row in result["rows"] if row["member_id"] == "legacy_loans")
    assert loans["observed_label"] == "legacy_loans"
    assert loans["observed_note"] == "附注十-8"
    assert loans["observed_amounts"] == [603639]
    assert loans["status"] == "MATCH"


def test_registry_persists_current_and_historical_member_contracts_in_isolated_db():
    from metadata_registry import MetadataRegistry
    from research_definition_registry import ResearchDefinitionService

    home = Path(tempfile.mkdtemp())
    try:
        service = ResearchDefinitionService(MetadataRegistry(home / "metadata.db"))
        family = next(row for row in service.families() if row["family_id"] == "financial_investment")
        contract = family["payload"]["family_resolution_contract"]
        assert contract["contract_version"] == "FINANCIAL_INVESTMENT_MEMBER_CONTRACT_V4"
        assert contract["current_required_members"] == [
            "fvtpl_assets", "debt_investment", "other_debt_investment", "other_equity_investment",
        ]
        assert "legacy_fvtpl_assets" in contract["historical_variant_members"]
        definition = next(row for row in service.definitions() if row["definition_id"] == "FINANCIAL_INVESTMENT_V1")
        scope = definition["payload"]["research_scope"]
        assert scope["expected_member_contract_version"] == "FINANCIAL_INVESTMENT_MEMBER_CONTRACT_V4"
        assert "legacy_fvtpl_assets" in scope["historical_variant_members"]
    finally:
        shutil.rmtree(home, ignore_errors=True)


def test_pingan_and_xinhua_child_target_pages_match_golden():
    pingan = compare_child_target(
        "中国平安", "2023", member_label="债权投资", note_reference="附注八-10",
        candidate_page=221, candidate_heading="债权投资",
    )
    xinhua = compare_child_target(
        "新华保险", "2023", member_label="债权投资", note_reference="附注4(12)",
        candidate_page=188, candidate_heading="债权投资",
    )
    assert pingan["status"] == "MATCH", pingan
    assert xinhua["status"] == "MATCH", xinhua


def test_wrong_child_target_page_requires_investigation():
    result = compare_child_target(
        "新华保险", "2023", member_label="债权投资", note_reference="附注4(12)",
        candidate_page=187, candidate_heading="债权投资",
    )
    assert result["status"] == "MISMATCH", result


def test_child_capture_detail_values_match_and_detect_difference(tmp_path):
    path = tmp_path / "table_raw_long.csv"
    path.write_text(
        "normalized_item,data_year,restated_flag,value_raw\n"
        "政府债,2023,False,892641\n"
        "政府债,2022,True,767761\n"
        "金融债,2023,False,32113\n"
        "金融债,2022,True,32047\n"
        "企业债,2023,False,47433\n"
        "企业债,2022,True,53131\n"
        "债权计划,2023,False,14196\n"
        "债权计划,2022,True,16102\n"
        "理财产品投资,2023,False,117172\n"
        "理财产品投资,2022,True,147424\n"
        "其他投资,2023,False,186775\n"
        "其他投资,2022,True,148373\n"
        "总额,2023,False,1290330\n"
        "总额,2022,True,1164838\n"
        "减：减值准备,2023,False,-46977\n"
        "减：减值准备,2022,True,-40803\n"
        "净额,2023,False,1243353\n"
        "净额,2022,True,1124035\n"
        "上市,2023,False,62757\n"
        "上市,2022,True,61208\n"
        "非上市,2023,False,1180596\n"
        "非上市,2022,True,1062827\n",
        encoding="utf-8",
    )
    good = compare_child_capture_csv("中国平安", "2023", member_label="债权投资", raw_long_path=path)
    assert good["status"] == "MATCH", good
    path.write_text(path.read_text(encoding="utf-8").replace("892641", "1", 1), encoding="utf-8")
    bad = compare_child_capture_csv("中国平安", "2023", member_label="债权投资", raw_long_path=path)
    assert bad["status"] == "MISMATCH", bad
