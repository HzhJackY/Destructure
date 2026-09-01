from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from anchor_candidate_selection import score_anchor_candidate
from generic_structure_parser import GenericStructureParser
from golden_acceptance import compare_portfolio_anchor
from investment_portfolio_resolver import (
    InvestmentPortfolioTopologyResolver,
    _period_headers,
    ocr_period_headers_from_words,
)
from research_definition_registry import BUILTIN_MEMBERS
from services.capture_service import _validate_direct_portfolio_physical_manifest
from statement_note_navigation import TextIndexRecord


def _members():
    return [
        {
            "member_id": row["member_id"],
            "display_name": row["display_name"],
            "payload": row,
        }
        for row in BUILTIN_MEMBERS["investment_portfolio"]
    ]


def _resolve(text: str):
    return InvestmentPortfolioTopologyResolver().resolve(
        pdf_path=Path("synthetic.pdf"),
        index=[TextIndexRecord(7, text, "", "", ())],
        members=_members(),
        company="SYNTHETIC",
        report_year="2025",
        filing_type="ANNUAL_REPORT",
    )


def test_compound_table_shares_physical_identity_and_preserves_two_blocks():
    candidates, audit = _resolve(
        "投资资产情况\n单位：人民币百万元\n投资资产（合计）\n10,000\n9,000\n"
        "按投资对象分类\n债券\n6,000\n按会计计量分类\n以公允价值计量\n7,000\n"
    )
    assert audit["selected_topology"] == "DIRECT_COMPOUND_TABLE"
    assert len(candidates) == 2
    assert len({row["physical_asset_id"] for row in candidates}) == 1
    assert len({row["logical_block_id"] for row in candidates}) == 2
    occurrences = GenericStructureParser().parse(
        candidates,
        strategy="DIRECT_PORTFOLIO_TABLES",
        family_id="investment_portfolio",
        display_name="投资组合",
    )
    assert len(occurrences) == 1
    assert len(occurrences[0]["child_rows"]) == 2


def test_separate_same_page_tables_keep_two_physical_identities():
    candidates, audit = _resolve(
        "保险资金投资组合\n单位：人民币百万元\n投资组合（按投资品种）\n"
        "投资资产合计\n10,000\n9,000\n债券\n6,000\n"
        "投资组合（按会计计量）\n以公允价值计量\n7,000\n"
    )
    assert audit["selected_topology"] == "DIRECT_SEPARATE_TABLES_SAME_PAGE"
    assert len({row["physical_asset_id"] for row in candidates}) == 2
    assert {row["unit"] for row in candidates} == {"RMB_MILLION"}
    occurrences = GenericStructureParser().parse(
        candidates,
        strategy="DIRECT_PORTFOLIO_TABLES",
        family_id="investment_portfolio",
        display_name="投资组合",
    )
    assert len(occurrences) == 1
    assert len(occurrences[0]["child_rows"]) == 2
    assert {row["unit"] for row in occurrences[0]["child_rows"]} == {
        "RMB_MILLION"
    }
    assert occurrences[0]["structure_evidence"]["physical_asset_count"] == 2


def test_single_axis_marks_measurement_not_applicable_not_missing():
    candidates, audit = _resolve(
        "投资组合情况\n单位：人民币百万元\n投资资产合计\n10,000\n9,000\n"
        "按投资对象分类\n债券\n6,000\n股票\n2,000\n"
    )
    assert audit["selected_topology"] == "DIRECT_SINGLE_AXIS_TABLE"
    assert [row["member_table"] for row in candidates] == ["portfolio_by_category"]
    assert candidates[0]["not_applicable_members"] == ["portfolio_by_measurement"]


def test_narrative_without_table_evidence_abstains():
    candidates, audit = _resolve("公司持续优化投资组合并加强资产负债管理。")
    assert candidates == []
    assert audit["final_status"] == "NO_DIRECT_PORTFOLIO_TABLE"


def test_plain_portfolio_title_requires_and_accepts_physical_table_evidence():
    candidates, audit = _resolve(
        "投资组合\n单位：人民币百万元\n"
        "2025年12月31日 2024年12月31日\n"
        "投资资产合计 1,901,634 1,641,756\n"
        "按投资对象分类\n债券 1,200,000 1,000,000\n"
        "按核算方法分类\n以公允价值计量 900,000 800,000\n"
    )
    assert audit["selected_topology"] == "DIRECT_COMPOUND_TABLE"
    assert audit["selected_page"] == 7
    assert len(candidates) == 2
    assert {row["classification_axis"] for row in candidates} == {
        "BY_INVESTMENT_OBJECT",
        "BY_ACCOUNTING_MEASUREMENT",
    }


def test_plain_portfolio_narrative_with_years_but_without_axis_abstains():
    candidates, audit = _resolve(
        "投资组合及投资收益\n2025年和2024年市场波动较大，"
        "公司配置规模分别为1,901,634、1,641,756、1,400,000、1,300,000。"
    )
    assert candidates == []
    assert audit["final_status"] == "NO_DIRECT_PORTFOLIO_TABLE"


def test_native_identity_can_request_bounded_numeric_evidence_recovery():
    resolver = InvestmentPortfolioTopologyResolver()
    index = [TextIndexRecord(
        42,
        "投资组合\n单位：百万元\n投资资产\n按投资对象分类\n按核算方法分类",
        "投资组合",
        "",
        (),
    )]
    assert resolver.evidence_recovery_pages(index) == [42]
    assert resolver.evidence_recovery_pages([
        TextIndexRecord(7, "公司持续优化投资组合。", "", "", ())
    ]) == []


def test_native_chinese_period_headers_allow_horizontal_pdf_whitespace():
    candidates, audit = _resolve(
        "集团合并投资组合\n单位：人民币百万元\n"
        "2025 年12 月31 日 占比(%) 2024 年12 月31 日 占比(%)\n"
        "投资资产（合计） 3,039,987 100.0 2,734,457 100.0\n"
        "按投资对象分\n债券投资 1,855,656\n"
        "按会计核算方法分类\n以公允价值计量 1,948,239\n"
    )
    assert audit["selected_topology"] == "DIRECT_COMPOUND_TABLE"
    assert candidates[0]["evidence"]["period_headers"] == [
        "2025年12月31日",
        "2024年12月31日",
    ]
    assert candidates[0]["evidence"]["period_header_complete"] is True

    occurrence = GenericStructureParser().parse(
        candidates,
        strategy="DIRECT_PORTFOLIO_TABLES",
        family_id="investment_portfolio",
        display_name="投资组合",
    )[0]
    scored = score_anchor_candidate(
        occurrence,
        {"scope_preference": "CONSOLIDATED"},
    )
    assert scored["hard_gate_results"]["period_recognized"] is True
    assert scored["hard_gates_passed"] is True


def test_contiguous_chinese_period_headers_remain_compatible():
    assert _period_headers("2025年12月31日 2024年12月31日") == [
        "2025年12月31日",
        "2024年12月31日",
    ]


def test_full_date_supersedes_bare_year_for_same_period_identity():
    assert _period_headers("2025年业务回顾\n2025年12月31日 2024年12月31日") == [
        "2025年12月31日",
        "2024年12月31日",
    ]


def test_period_parser_does_not_join_date_glyphs_across_rows():
    assert _period_headers("2025\n年12月31日") == []


def test_ocr_period_geometry_reconstructs_adjacent_baselines_without_text_join():
    words = [
        [1520, 852, 1813, 902, "2023"],
        [1671, 843, 1734, 914, "年"],
        [1733, 843, 1796, 914, "12"],
        [1795, 843, 1836, 914, "月"],
        [1829, 858, 1881, 898, "31"],
        [1904, 857, 1935, 900, "日"],
        [2286, 852, 2579, 902, "2022"],
        [2439, 843, 2498, 915, "年"],
        [2498, 843, 2561, 915, "12"],
        [2561, 843, 2606, 915, "月"],
        [2595, 858, 2647, 898, "31"],
        [2670, 855, 2754, 900, "日"],
        [2723, 843, 2755, 915, "0"],
    ]
    assert ocr_period_headers_from_words(words) == [
        "2023年12月31日",
        "2022年12月31日",
    ]


def test_ocr_period_geometry_does_not_infer_missing_components():
    words = [
        [100, 100, 180, 130, "2025"],
        [190, 100, 220, 130, "年"],
        [230, 100, 260, 130, "12"],
        [270, 100, 300, 130, "月"],
    ]
    assert ocr_period_headers_from_words(words) == []


def test_duplicate_native_period_does_not_complete_two_period_gate():
    candidates, _ = _resolve(
        "集团合并投资组合\n单位：人民币百万元\n"
        "2025 年12 月31 日 占比(%) 2025年12月31日 占比(%)\n"
        "投资资产（合计） 3,039,987 100.0 3,039,987 100.0\n"
        "按投资对象分\n债券投资 1,855,656\n"
        "按会计核算方法分类\n以公允价值计量 1,948,239\n"
    )
    assert candidates[0]["evidence"]["period_headers"] == ["2025年12月31日"]
    assert candidates[0]["evidence"]["period_header_complete"] is False


def test_portfolio_stage_a_uses_portfolio_golden_not_financial_member_gate():
    candidate = {
        "company": "中国人寿",
        "report_year": "2023",
        "statement_pdf_page_index": 21,
        "disclosure_topology": "DIRECT_SINGLE_AXIS_TABLE",
        "physical_asset_id": "PORTFOLIO_PHYSICAL_TEST",
        "child_rows": [{
            "member_table": "portfolio_by_category",
            "physical_asset_id": "PORTFOLIO_PHYSICAL_TEST",
        }],
        "structure_evidence": {"physical_asset_count": 1},
        "evidence": {
            "strategy": "DIRECT_PORTFOLIO_TABLES",
            "reported_totals_locator_evidence": [5673371, 5064980],
        },
    }
    comparison = compare_portfolio_anchor("中国人寿", "2023", candidate)
    assert comparison["status"] == "MATCH"
    assert all("fvtpl_assets" not in str(row) for row in comparison["rows"])


def _direct_manifest_result(*, bbox: dict[str, float]):
    return SimpleNamespace(
        located_title="保险资金投资组合投资组合（按投资品种）",
        rows=[
            SimpleNamespace(
                page=28,
                bbox=bbox,
                excluded_from_table_logic=False,
            )
        ],
    )


def _direct_manifest_inputs():
    certified = [{
        "certified_segment_id": "CSEG_TEST",
        "certification_status": "CERTIFIED",
        "start_page": 28,
        "bbox": {"x0": 24, "y0": 139, "x1": 571, "y1": 447},
    }]
    discovered = [{
        "segment_id": "SEG_TEST",
        "classification": "PRIMARY_TABLE",
        "pdf_page_number": 28,
        "table_identity": "投资组合（按投资品种）",
    }]
    target = {
        "physical_asset_id": "PORTFOLIO_PHYSICAL_TEST",
        "classification_axis": "BY_INVESTMENT_OBJECT",
        "target_heading": "投资组合（按投资品种）",
    }
    return certified, discovered, target


def test_direct_portfolio_manifest_uses_certified_physical_roi_not_note_signatures():
    certified, discovered, target = _direct_manifest_inputs()
    validation = _validate_direct_portfolio_physical_manifest(
        _direct_manifest_result(
            bbox={"x0": 42, "y0": 186, "x1": 547, "y1": 444}
        ),
        discovered_segments=discovered,
        certified_segments=certified,
        manifest_status="CERTIFIED_SEGMENT_MANIFEST",
        target=target,
    )
    assert validation["status"] == "VALID"
    assert validation["validation_mode"] == "DIRECT_PORTFOLIO_PHYSICAL_ROI"
    assert validation["row_membership_semantics"] == (
        "BBOX_VERTICAL_CENTER_HORIZONTAL_OVERLAP_V1"
    )
    assert validation["validated_pairs"][0]["drift_fields"] == []


def test_direct_portfolio_manifest_fails_closed_outside_certified_roi():
    certified, discovered, target = _direct_manifest_inputs()
    validation = _validate_direct_portfolio_physical_manifest(
        _direct_manifest_result(
            bbox={"x0": 580, "y0": 186, "x1": 590, "y1": 444}
        ),
        discovered_segments=discovered,
        certified_segments=certified,
        manifest_status="CERTIFIED_SEGMENT_MANIFEST",
        target=target,
    )
    assert validation["status"] == "REVIEW_REQUIRED"
    assert "DIRECT_PORTFOLIO_RUNTIME_ROW_OUTSIDE_CERTIFIED_ROI" in validation[
        "issue_codes"
    ]


def test_direct_portfolio_manifest_accepts_tail_glyph_bbox_when_row_anchor_is_inside():
    certified, discovered, target = _direct_manifest_inputs()
    validation = _validate_direct_portfolio_physical_manifest(
        _direct_manifest_result(
            bbox={"x0": 42, "y0": 430, "x1": 547, "y1": 450}
        ),
        discovered_segments=discovered,
        certified_segments=certified,
        manifest_status="CERTIFIED_SEGMENT_MANIFEST",
        target=target,
    )
    assert validation["status"] == "VALID"


def test_direct_portfolio_manifest_rejects_tail_row_when_anchor_is_outside():
    certified, discovered, target = _direct_manifest_inputs()
    validation = _validate_direct_portfolio_physical_manifest(
        _direct_manifest_result(
            bbox={"x0": 42, "y0": 444, "x1": 547, "y1": 460}
        ),
        discovered_segments=discovered,
        certified_segments=certified,
        manifest_status="CERTIFIED_SEGMENT_MANIFEST",
        target=target,
    )
    assert validation["status"] == "REVIEW_REQUIRED"
    assert "DIRECT_PORTFOLIO_RUNTIME_ROW_OUTSIDE_CERTIFIED_ROI" in validation[
        "issue_codes"
    ]
