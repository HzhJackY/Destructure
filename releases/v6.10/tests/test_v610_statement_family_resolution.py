from __future__ import annotations

from statement_family_resolution import StatementFamilyResolver
from statement_note_navigation import TextIndexRecord
from generic_discovery_engine import GenericDiscoveryService


def _member(member_id, label, *, aliases=(), direct=False, order=1):
    return {
        "member_id": member_id, "display_name": label, "member_role": "NOTE_DETAIL",
        "canonical_order": order,
        "payload": {"aliases": list(aliases), "direct_member": direct,
                     "canonical_analysis_bucket": member_id},
    }


def _family():
    return {
        "family_id": "financial_investment", "display_name": "金融投资",
        "definition_version": "FINANCIAL_INVESTMENT_V1",
        "payload": {
            "preferred_scope": "CONSOLIDATED",
            "core_members": ["fvtpl_assets", "debt_investment", "other_debt_investment", "other_equity_investment"],
            "family_resolution_contract": {
                "allowed_resolution_modes": ["EXPLICIT_PARENT", "IMPLICIT_MEMBER_SET", "HYBRID"],
                "explicit_parent_aliases": ["金融投资"],
                "direct_member_concepts": ["legacy_fvtpl_assets", "legacy_loans", "time_deposits", "available_for_sale_assets", "held_to_maturity_investments", "long_term_equity"],
            },
        },
    }


def _members():
    return [
        _member("fvtpl_assets", "以公允价值计量且其变动计入当期损益的金融资产", aliases=("交易性金融资产",), order=1),
        _member("debt_investment", "债权投资", order=2),
        _member("other_debt_investment", "其他债权投资", order=3),
        _member("other_equity_investment", "其他权益工具投资", order=4),
        _member("legacy_fvtpl_assets", "以公允价值计量且其变动计入当期损益的金融资产", direct=True, order=10),
        _member("legacy_loans", "贷款", aliases=("贷款及应收款项",), direct=True, order=11),
        _member("time_deposits", "定期存款", direct=True, order=12),
        _member("available_for_sale_assets", "可供出售金融资产", direct=True, order=13),
        _member("held_to_maturity_investments", "持有至到期投资", direct=True, order=14),
        _member("long_term_equity", "长期股权投资", direct=True, order=15),
    ]


def _index(statement_text):
    return [
        TextIndexRecord(1, statement_text, "合并资产负债表", "", ()),
        TextIndexRecord(9, "附注一\n交易性金融资产", "附注一", "一", ("附注-1",)),
        TextIndexRecord(10, "附注二\n债权投资", "附注二", "二", ("附注-2",)),
    ]


def test_explicit_parent_preserves_real_parent_and_never_derives_total():
    text = """合并资产负债表
附注
金融投资：
交易性金融资产
1
100
债权投资
2
200
其他债权投资
3
300
其他权益工具投资
4
400"""
    rows, resolutions = StatementFamilyResolver().resolve(
        index=_index(text), family=_family(), members=_members(), company="测试", report_year="2023", filing_type="ANNUAL_REPORT")
    assert len(resolutions) == 1
    resolution = resolutions[0]
    assert resolution["resolution_mode"] == "EXPLICIT_PARENT"
    assert resolution["raw_parent_label"] == "金融投资："
    assert resolution["raw_parent_row_id"]
    assert resolution["family_total_status"] == "NOT_REPORTED"
    assert {row["member_origin"] for row in rows} == {"EXPLICIT_CHILD_ROW"}
    assert all(row["raw_parent_row_id"] == resolution["raw_parent_row_id"] for row in rows)


def test_implicit_member_set_has_null_source_parent_and_legacy_semantics():
    text = """合并资产负债表
附注
以公允价值计量且其变动计入当期损益的金融资产
1
100
贷款
2
200
定期存款
3
300
可供出售金融资产
4
400
持有至到期投资
5
500
长期股权投资
6
600"""
    rows, resolutions = StatementFamilyResolver().resolve(
        index=_index(text), family=_family(), members=_members(), company="测试", report_year="2023", filing_type="ANNUAL_REPORT")
    assert len(resolutions) == 1
    resolution = resolutions[0]
    assert resolution["resolution_mode"] == "IMPLICIT_MEMBER_SET"
    assert resolution["raw_parent_row_id"] is None
    assert resolution["raw_parent_label"] is None
    assert resolution["derived_family_label_is_source_text"] is False
    assert resolution["family_total_status"] == "NOT_REPORTED"
    assert len(rows) == 6
    assert {row["member_origin"] for row in rows} == {"DIRECT_STATEMENT_ROW"}
    assert all(row["raw_parent_row_id"] is None for row in rows)
    assert {row["presentation_regime"] for row in rows} == {"LEGACY_FINANCIAL_ASSET_CLASSIFICATION"}
    assert {row["comparability_status"] for row in rows} == {"PARTIALLY_COMPARABLE"}
    assert "legacy_fvtpl_assets" in {row["member_table"] for row in rows}


def test_explicit_parent_does_not_absorb_out_of_block_direct_rows():
    text = """合并资产负债表
附注
金融投资
交易性金融资产
1
100
债权投资
2
200
定期存款
3
300"""
    rows, resolutions = StatementFamilyResolver().resolve(
        index=_index(text), family=_family(), members=_members(), company="测试", report_year="2023", filing_type="ANNUAL_REPORT")
    resolution = resolutions[0]
    assert resolution["resolution_mode"] == "EXPLICIT_PARENT"
    assert resolution["presentation_regime"] == "NEW_FINANCIAL_INSTRUMENT_CLASSIFICATION"
    assert {row["member_origin"] for row in rows} == {"EXPLICIT_CHILD_ROW"}
    assert {row["member_table"] for row in rows} == {"fvtpl_assets", "debt_investment"}
    assert all(row["raw_parent_row_id"] == resolution["raw_parent_row_id"] for row in rows)
    assert all(item["source_pdf_page_index"] == 1 for item in resolution["evidence"]["source_rows"])


def test_ocr_explicit_parent_never_becomes_hybrid_from_direct_rows():
    family = _family()
    rows = [
        {"statement_item": "金融投资", "member_table": "金融投资", "statement_pdf_page_index": 7, "evidence": {}},
        {"statement_item": "交易性金融资产", "member_table": "fvtpl_assets", "statement_pdf_page_index": 7, "evidence": {}},
        {"statement_item": "债权投资", "member_table": "debt_investment", "statement_pdf_page_index": 7, "evidence": {}},
        {"statement_item": "定期存款", "member_table": "time_deposits", "statement_pdf_page_index": 7, "evidence": {}},
        {"statement_item": "长期股权投资", "member_table": "long_term_equity", "statement_pdf_page_index": 7, "evidence": {}},
    ]
    resolutions = GenericDiscoveryService._resolution_from_discovered_rows(rows, family)
    assert len(resolutions) == 1
    resolution = resolutions[0]
    assert resolution["resolution_mode"] == "EXPLICIT_PARENT"
    assert resolution["presentation_regime"] == "NEW_FINANCIAL_INSTRUMENT_CLASSIFICATION"
    assert resolution["member_ids"] == ["fvtpl_assets", "debt_investment"]
    assert set(resolution["member_origins"].values()) == {"EXPLICIT_CHILD_ROW"}


def test_ocr_unreadable_parent_never_certifies_implicit_member_set():
    family = _family()
    rows = [
        {"statement_item": "交易性金融资产", "member_table": "fvtpl_assets", "statement_pdf_page_index": 7,
         "evidence": {"family_parent_recovery_status": "REVIEW_REQUIRED_OCR_PARENT_UNREADABLE"}},
        {"statement_item": "债权投资", "member_table": "debt_investment", "statement_pdf_page_index": 7,
         "evidence": {"family_parent_recovery_status": "REVIEW_REQUIRED_OCR_PARENT_UNREADABLE"}},
    ]
    resolutions = GenericDiscoveryService._resolution_from_discovered_rows(rows, family)
    assert len(resolutions) == 1
    resolution = resolutions[0]
    assert resolution["resolution_mode"] == "UNRESOLVED_OCR_PARENT"
    assert resolution["review_status"] == "REVIEW_REQUIRED"
    assert resolution["member_ids"] == []


def test_ocr_raw_labels_are_normalized_before_implicit_resolution():
    """Raw OCR labels must not be compared directly to registry member IDs."""
    family = _family()
    members = _members()
    raw_rows = [
        {"statement_item": "以公允价值计量且其变动计入当期损益的金融资产", "member_table": "以公允价值计量且其变动计入当期损益的金融资产", "evidence": {}},
        {"statement_item": "贷款", "member_table": "贷款", "evidence": {}},
        {"statement_item": "定期存款", "member_table": "定期存款", "evidence": {}},
        {"statement_item": "可供出售金融资产", "member_table": "可供出售金融资产", "evidence": {}},
        {"statement_item": "持有至到期投资", "member_table": "持有至到期投资", "evidence": {}},
    ]
    GenericDiscoveryService._normalize_ocr_rows_to_registry(raw_rows, members)
    assert {row["member_table"] for row in raw_rows} >= {
        "legacy_fvtpl_assets", "legacy_loans", "time_deposits",
        "available_for_sale_assets", "held_to_maturity_investments",
    }
    resolutions = GenericDiscoveryService._resolution_from_discovered_rows(raw_rows, family)
    assert len(resolutions) == 1
    assert resolutions[0]["resolution_mode"] == "IMPLICIT_MEMBER_SET"
    assert resolutions[0]["raw_parent_row_id"] is None
    assert all(row["statement_item"] == row["source_member_table_raw"] for row in raw_rows)
