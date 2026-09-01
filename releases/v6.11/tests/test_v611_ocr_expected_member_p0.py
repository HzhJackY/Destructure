"""P0 contracts for the v6.11 OCR / expected-member repair.

These tests intentionally exercise only temporary registries, synthetic PDFs,
and injected OCR providers.  Real filing acceptance is run separately.
"""
from __future__ import annotations

import json
import tempfile
from pathlib import Path

import fitz

from conditional_statement_ocr import conditional_ocr_primary_statements
from expected_member_resolver import resolve_expected_members
from generic_discovery import discover
from generic_structure_parser import GenericStructureParser
from metadata_registry import MetadataRegistry
from research_definition_registry import ResearchDefinitionService
from statement_family_resolution import StatementFamilyResolver


NEW = "NEW_FINANCIAL_INSTRUMENT_CLASSIFICATION"
LEGACY = "LEGACY_FINANCIAL_ASSET_CLASSIFICATION"
UNKNOWN = "UNKNOWN"
NEW_REQUIRED = [
    "fvtpl_assets",
    "debt_investment",
    "other_debt_investment",
    "other_equity_investment",
]
OUTSIDE = ["time_deposits", "long_term_equity"]


def _members() -> list[dict]:
    return [
        {
            "member_id": "fvtpl_assets", "display_name": "交易性金融资产",
            "member_role": "NOTE_DETAIL", "required": True, "canonical_order": 1,
            "payload": {"aliases": [], "presentation_regime": NEW},
        },
        {
            "member_id": "debt_investment", "display_name": "债权投资",
            "member_role": "NOTE_DETAIL", "required": True, "canonical_order": 2,
            "payload": {"aliases": [], "presentation_regime": NEW},
        },
        {
            "member_id": "other_debt_investment", "display_name": "其他债权投资",
            "member_role": "NOTE_DETAIL", "required": True, "canonical_order": 3,
            "payload": {"aliases": [], "presentation_regime": NEW},
        },
        {
            "member_id": "other_equity_investment", "display_name": "其他权益工具投资",
            "member_role": "NOTE_DETAIL", "required": True, "canonical_order": 4,
            "payload": {"aliases": [], "presentation_regime": NEW},
        },
        {
            "member_id": "legacy_fvtpl_assets",
            "display_name": "以公允价值计量且其变动计入当期损益的金融资产",
            "member_role": "NOTE_DETAIL", "required": False, "canonical_order": 10,
            "payload": {"aliases": [], "presentation_regime": LEGACY, "direct_member": True},
        },
        {
            "member_id": "legacy_loans", "display_name": "贷款",
            "member_role": "NOTE_DETAIL", "required": False, "canonical_order": 11,
            "payload": {"aliases": ["贷款及应收款项"], "presentation_regime": LEGACY, "direct_member": True},
        },
        {
            "member_id": "available_for_sale_assets", "display_name": "可供出售金融资产",
            "member_role": "NOTE_DETAIL", "required": False, "canonical_order": 12,
            "payload": {"aliases": [], "presentation_regime": LEGACY, "direct_member": True},
        },
        {
            "member_id": "held_to_maturity_investments", "display_name": "持有至到期投资",
            "member_role": "NOTE_DETAIL", "required": False, "canonical_order": 13,
            "payload": {"aliases": [], "presentation_regime": LEGACY, "direct_member": True},
        },
        {
            "member_id": "time_deposits", "display_name": "定期存款",
            "member_role": "NOTE_DETAIL", "required": False, "canonical_order": 14,
            "payload": {"aliases": [], "presentation_regime": LEGACY, "direct_member": False, "outside_family": True},
        },
        {
            "member_id": "long_term_equity", "display_name": "长期股权投资",
            "member_role": "NOTE_DETAIL", "required": False, "canonical_order": 15,
            "payload": {"aliases": [], "presentation_regime": LEGACY, "direct_member": False, "outside_family": True},
        },
    ]


def _definition_contract() -> dict:
    return {
        "contract_version": "FINANCIAL_INVESTMENT_MEMBER_CONTRACT_V2",
        "required_members": list(NEW_REQUIRED),
        "optional_members": [
            "legacy_fvtpl_assets", "legacy_loans",
            "available_for_sale_assets", "held_to_maturity_investments",
        ],
        "outside_family_members": list(OUTSIDE),
        "expected_member_contracts": {
            NEW: {
                "CONSOLIDATED": {
                    "required_members": list(NEW_REQUIRED),
                    "optional_members": [],
                },
            },
            LEGACY: {
                "CONSOLIDATED": {
                    "required_members": [
                        "legacy_fvtpl_assets", "legacy_loans",
                        "available_for_sale_assets", "held_to_maturity_investments",
                    ],
                    "optional_members": [],
                },
            },
            UNKNOWN: {
                "CONSOLIDATED": {
                    "required_members": list(NEW_REQUIRED),
                    "optional_members": [],
                },
            },
        },
    }


def _family() -> dict:
    return {
        "family_id": "financial_investment",
        "display_name": "金融投资",
        "definition_version": "FINANCIAL_INVESTMENT_V1",
        "payload": {
            "preferred_scope": "CONSOLIDATED",
            "core_members": list(NEW_REQUIRED),
            "family_resolution_contract": {
                "allowed_resolution_modes": ["EXPLICIT_PARENT", "IMPLICIT_MEMBER_SET"],
                "explicit_parent_aliases": ["金融投资"],
                "direct_member_concepts": [
                    "legacy_fvtpl_assets", "legacy_loans",
                    "available_for_sale_assets", "held_to_maturity_investments",
                ],
                **_definition_contract(),
            },
        },
    }


def _image_pdf(path: Path, pages: int = 3) -> Path:
    doc = fitz.open()
    pix = fitz.Pixmap(fitz.csRGB, fitz.IRect(0, 0, 600, 800), 0)
    pix.clear_with(255)
    payload = pix.tobytes("png")
    for _ in range(pages):
        page = doc.new_page(width=600, height=800)
        page.insert_image(page.rect, stream=payload)
    doc.save(path)
    doc.close()
    return path


def test_expected_denominator_is_definition_owned_not_actual_owned() -> None:
    result = resolve_expected_members(
        resolution_mode="EXPLICIT_PARENT",
        presentation_regime=NEW,
        report_year="2025",
        statement_scope="CONSOLIDATED",
        source_parent_boundary={"label": "金融投资"},
        definition_version="FINANCIAL_INVESTMENT_V1",
        definition_contract=_definition_contract(),
        registry_members=_members(),
        actual_statement_rows=[
            {"member_table": "fvtpl_assets", "member_period_status": "ACTIVE_CURRENT_PERIOD"},
            {"member_table": "debt_investment", "member_period_status": "ACTIVE_CURRENT_PERIOD"},
        ],
    )
    assert result["coverage_denominator"] == 4
    assert result["coverage_numerator"] == 2
    assert result["missing_required_members"] == [
        "other_debt_investment", "other_equity_investment",
    ]
    assert result["quality_status"] == "REVIEW_REQUIRED_ACTIONABLE"


def test_china_life_implicit_contract_has_null_parent_and_excludes_external_assets() -> None:
    from expected_member_resolver import ChinaLifeImplicitMemberContract

    result = ChinaLifeImplicitMemberContract.resolve(
        presentation_regime=LEGACY,
        statement_scope="CONSOLIDATED",
        definition_version="FINANCIAL_INVESTMENT_V1",
        definition_contract=_definition_contract(),
        registry_members=_members(),
        actual_statement_rows=[
            {"member_table": "legacy_fvtpl_assets", "member_period_status": "ACTIVE_CURRENT_PERIOD"},
            {"member_table": "legacy_loans", "member_period_status": "ACTIVE_CURRENT_PERIOD"},
            {"member_table": "time_deposits", "member_period_status": "ACTIVE_CURRENT_PERIOD"},
            {"member_table": "long_term_equity", "member_period_status": "ACTIVE_CURRENT_PERIOD"},
        ],
    )
    assert result["raw_parent_row_id"] is None
    assert result["raw_parent_label"] is None
    assert set(result["outside_family_members"]) == set(OUTSIDE)
    assert not set(OUTSIDE) & set(result["required_current_members"])
    assert result["coverage_denominator"] == 4
    assert result["coverage_numerator"] == 2


def test_unknown_shared_resolution_is_actionable_and_never_resolved() -> None:
    family = _family()
    family["payload"]["core_members"] = ["mystery_member"]
    family["payload"]["family_resolution_contract"]["direct_member_concepts"] = ["mystery_member"]
    family["payload"]["family_resolution_contract"]["required_members"] = ["mystery_member"]
    family["payload"]["family_resolution_contract"]["expected_member_contracts"][UNKNOWN] = {
        "CONSOLIDATED": {"required_members": ["mystery_member"], "optional_members": []},
    }
    members = [{
        "member_id": "mystery_member", "display_name": "未知类别资产",
        "member_role": "NOTE_DETAIL", "required": True, "canonical_order": 1,
        "payload": {"aliases": [], "direct_member": True},
    }]
    _, resolutions = StatementFamilyResolver().resolve_discovered_rows(
        rows=[{
            "statement_item": "未知类别资产",
            "member_table": "mystery_member",
            "statement_pdf_page_index": 3,
            "scope": "CONSOLIDATED",
            "ocr_used": True,
            "evidence": {"raw_line": "未知类别资产 100", "ocr_used": True},
        }],
        family=family,
        members=members,
        company="任意公司",
        report_year="2025",
        filing_type="ANNUAL_REPORT",
    )
    assert resolutions
    assert resolutions[0]["presentation_regime"] == UNKNOWN
    assert resolutions[0]["quality_status"] == "REVIEW_REQUIRED_ACTIONABLE"
    assert resolutions[0]["review_status"] == "REVIEW_REQUIRED_ACTIONABLE"


def test_ocr_rows_never_emit_statement_amounts_but_keep_token_provenance() -> None:
    ocr_text = """合并资产负债表
2025年12月31日 人民币百万元
资产 附注七
金融投资：
交易性金融资产 10 484,418
债权投资 11 5,567,857
其他债权投资 12 1,186,531,148
其他权益工具投资 13 108,725,948
资产总计"""
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        pdf = _image_pdf(root / "ocr.pdf")
        rows = discover(
            pdf,
            root / "cache",
            display_name="金融投资",
            company="任意公司",
            report_year="2025",
            discovery_context={
                "preferred_statement_type": "BALANCE_SHEET",
                "preferred_scope": "CONSOLIDATED",
                "require_note_reference": True,
                "core_candidates": [
                    "交易性金融资产", "债权投资", "其他债权投资", "其他权益工具投资",
                ],
            },
            text_provider=lambda _: ["", "", ""],
            ocr_provider=lambda _, page, __: ocr_text if page == 2 else "封面图片",
        )
        member_rows = [row for row in rows if row["statement_item"] != "金融投资"]
        assert member_rows
        assert all(row["statement_amount_raw"] == [] for row in member_rows)
        assert all(row["statement_amount_normalized"] == [] for row in member_rows)
        assert all(row["amount_source_present"] is False for row in member_rows)
        assert all((row["evidence"].get("ocr_token_provenance") or {}).get("usable_as_amount") is False for row in member_rows)
        assert any((row["evidence"].get("ocr_token_provenance") or {}).get("raw_numeric_tokens") for row in member_rows)


def test_structure_parser_preserves_period_status_and_rejects_ocr_amounts() -> None:
    candidate = {
        "statement_type": "BALANCE_SHEET",
        "scope": "CONSOLIDATED",
        "statement_pdf_page_index": 3,
        "source_table_title": "合并资产负债表",
        "statement_item": "债权投资",
        "member_table": "debt_investment",
        "member_period_status": "UNRESOLVED",
        "statement_amount_raw": ["5,567,857"],
        "statement_amount_normalized": ["5567857"],
        "statement_amounts": ["5,567,857"],
        "ocr_used": True,
        "candidate_note_pdf_page_index": 9,
        "confidence": 0.91,
        "evidence": {"ocr_token_provenance": {"usable_as_amount": False}},
    }
    occurrences = GenericStructureParser().parse(
        [candidate],
        strategy="STATEMENT_PARENT_TO_MULTI_NOTE",
        family_id="financial_investment",
        display_name="金融投资",
    )
    child = occurrences[0]["child_rows"][0]
    assert child["member_period_status"] == "UNRESOLVED"
    assert child["statement_amount_raw"] == []
    assert child["statement_amount_normalized"] == []
    assert child["statement_amounts"] == []
    assert child["amount_source_present"] is False
    assert child["value_evidence_status"] == "REJECTED_OCR_WITHOUT_NATIVE_GEOMETRY"


def test_missing_period_status_fails_closed_at_structure_boundary() -> None:
    occurrences = GenericStructureParser().parse(
        [{
            "statement_type": "BALANCE_SHEET",
            "scope": "CONSOLIDATED",
            "statement_pdf_page_index": 3,
            "source_table_title": "合并资产负债表",
            "statement_item": "债权投资",
            "member_table": "debt_investment",
            "candidate_note_pdf_page_index": 9,
            "confidence": 0.91,
            "evidence": {},
        }],
        strategy="STATEMENT_PARENT_TO_MULTI_NOTE",
        family_id="financial_investment",
        display_name="金融投资",
    )
    child = occurrences[0]["child_rows"][0]
    assert child["member_period_status"] == "UNRESOLVED"
    assert child["stage_b_eligibility"] == "REVIEW_REQUIRED_ACTIONABLE"


def test_conditional_ocr_reuses_fast_index_owned_cache_key_and_directory() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        pdf = _image_pdf(root / "cached.pdf")
        calls = {"count": 0}

        def provider(_, page, __):
            calls["count"] += 1
            return "合并资产负债表\n2025年12月31日\n资产\n金融投资\n资产总计" if page == 2 else "图片"

        first_output, first_audit = conditional_ocr_primary_statements(
            pdf,
            native_pages=["", "", ""],
            preferred_statement_type="BALANCE_SHEET",
            cache_root=root / "cache",
            ocr_provider=provider,
        )
        first_calls = calls["count"]
        second_output, second_audit = conditional_ocr_primary_statements(
            pdf,
            native_pages=["", "", ""],
            preferred_statement_type="BALANCE_SHEET",
            cache_root=root / "cache",
            ocr_provider=provider,
        )
        assert first_output == second_output
        assert first_calls > 0
        assert calls["count"] == first_calls
        assert first_audit["ocr_cache_namespace"] == "FAST_INDEX_SHARED_OCR_PAGE_CACHE"
        assert second_audit["ocr_cache_hits"] == second_audit["ocr_page_count"]
        cache_files = list((root / "cache").glob("*/ocr_page_cache_*.json"))
        assert len(cache_files) == 1


def test_versioned_registry_migration_removes_external_assets_without_production_db() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        registry = MetadataRegistry(Path(tmp) / "metadata.db")
        service = ResearchDefinitionService(registry)
        with registry.connect() as conn:
            row = conn.execute(
                "SELECT payload_json FROM table_families WHERE family_id='financial_investment'"
            ).fetchone()
            payload = json.loads(row[0])
            contract = payload["family_resolution_contract"]
            contract["direct_member_concepts"] = list(dict.fromkeys(
                list(contract["direct_member_concepts"]) + OUTSIDE
            ))
            contract["optional_members"] = list(dict.fromkeys(
                list(contract["optional_members"]) + OUTSIDE
            ))
            contract["contract_version"] = "FINANCIAL_INVESTMENT_MEMBER_CONTRACT_V1"
            payload["optional_members"] = list(dict.fromkeys(
                list(payload.get("optional_members") or []) + OUTSIDE
            ))
            conn.execute(
                "UPDATE table_families SET payload_json=? WHERE family_id='financial_investment'",
                (json.dumps(payload, ensure_ascii=False),),
            )
            for member_id in OUTSIDE:
                member_row = conn.execute(
                    "SELECT payload_json FROM family_members WHERE family_id='financial_investment' AND member_id=?",
                    (member_id,),
                ).fetchone()
                member_payload = json.loads(member_row[0])
                member_payload["direct_member"] = True
                member_payload.pop("outside_family", None)
                conn.execute(
                    "UPDATE family_members SET payload_json=? WHERE family_id='financial_investment' AND member_id=?",
                    (json.dumps(member_payload, ensure_ascii=False), member_id),
                )

        migrated = ResearchDefinitionService(registry)
        family = next(x for x in migrated.families() if x["family_id"] == "financial_investment")
        contract = family["payload"]["family_resolution_contract"]
        assert contract["contract_version"] == "FINANCIAL_INVESTMENT_MEMBER_CONTRACT_V2"
        assert not set(OUTSIDE) & set(contract["direct_member_concepts"])
        assert not set(OUTSIDE) & set(contract["optional_members"])
        assert not set(OUTSIDE) & set(family["payload"].get("optional_members") or [])
        members = {x["member_id"]: x for x in migrated.members("financial_investment")}
        assert all(members[x]["payload"]["direct_member"] is False for x in OUTSIDE)
        assert all(members[x]["payload"]["outside_family"] is True for x in OUTSIDE)
        definition = migrated.definition("FINANCIAL_INVESTMENT_V1")
        scope = definition["payload"]["research_scope"]
        assert scope["expected_member_contract_version"] == (
            "FINANCIAL_INVESTMENT_MEMBER_CONTRACT_V2"
        )
        assert set(scope["outside_family_members"]) == set(OUTSIDE)
        assert not set(OUTSIDE) & set(scope["core_members"])
        assert not set(OUTSIDE) & set(scope["optional_members"])
