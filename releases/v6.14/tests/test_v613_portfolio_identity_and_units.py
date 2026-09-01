from __future__ import annotations

import json

import pandas as pd
import pytest

import golden_acceptance
from spatial_table_capture import _resolve_observation_unit
from table_capture import (
    TableCaptureResult,
    TableCell,
    TableColumn,
    TableRow,
    apply_item_label_normalization,
    capture_to_long_df,
    normalize_item_label_with_evidence,
)
from table_merge import (
    apply_mapping,
    assign_conditional_source_keys,
    build_mapping_queue,
    materialize_canonical,
)


def _row(label: str, *, normalized: str | None = None) -> TableRow:
    return TableRow(
        row_order=1,
        page=48,
        block_id="PHYSICAL_1",
        source_method="NATIVE_TEXT",
        raw_item=label,
        normalized_item=normalized or label,
        canonical_item=None,
        mapping_status="RAW",
        row_type="DETAIL",
        row_level=0,
        parent_section=None,
        cells=[
            TableCell(
                column_ordinal=0,
                source_column_index=1,
                raw="100",
                parsed_number=100.0,
                unit_original="百万元",
                value_yuan=100_000_000.0,
                unit_source="CERTIFIED_DIRECT_AMOUNT_UNIT",
                unit_evidence={"certified_amount_unit": "RMB_MILLION"},
            )
        ],
        header_source_page=48,
        row_item_raw=label,
        row_item_normalized=normalized or label,
        bbox={"x0": 80, "y0": 200, "x1": 520, "y1": 210},
        container_id="CONTAINER_1",
        table_block_id="BLOCK_1",
        block_order=0,
        classification_axis="PORTFOLIO_SUMMARY",
        block_role="PRIMARY",
        block_terminal_type="NONE",
    )


def test_numeric_footnote_requires_certified_evidence() -> None:
    unresolved = normalize_item_label_with_evidence("现金及现金等价物(2)")
    assert unresolved.normalized_item == "现金及现金等价物(2)"
    assert unresolved.normalization_status == "ROW_LABEL_FOOTNOTE_UNRESOLVED"

    geometry = normalize_item_label_with_evidence(
        "现金及现金等价物(2)",
        numeric_footnote_evidence=[{
            "marker": "2", "method": "NATIVE_SUPERSCRIPT_GEOMETRY",
            "page": 48,
        }],
    )
    assert geometry.normalized_item == "现金及现金等价物"
    assert geometry.footnote_markers == ("2",)
    assert geometry.normalization_status == "CERTIFIED_NUMERIC_FOOTNOTE_REMOVED"

    numbered_note = normalize_item_label_with_evidence(
        "其他资产（3）",
        numeric_footnote_evidence=[{
            "marker": "3", "method": "SAME_PAGE_FOOTNOTE_NUMBER",
            "page": 48,
        }],
    )
    assert numbered_note.normalized_item == "其他资产"
    assert numbered_note.footnote_markers == ("3",)

    bare_unresolved = normalize_item_label_with_evidence("债权型金融产品1")
    assert bare_unresolved.normalized_item == "债权型金融产品1"
    assert bare_unresolved.normalization_status == "ROW_LABEL_FOOTNOTE_UNRESOLVED"

    bare_geometry = normalize_item_label_with_evidence(
        "债权型金融产品1",
        numeric_footnote_evidence=[{
            "marker": "1", "method": "NATIVE_SUPERSCRIPT_GEOMETRY",
            "page": 20,
        }],
    )
    assert bare_geometry.normalized_item == "债权型金融产品"
    assert bare_geometry.footnote_markers == ("1",)

    note_digit_unresolved = normalize_item_label_with_evidence("债权投资计划注1")
    assert note_digit_unresolved.normalized_item == "债权投资计划注1"
    assert note_digit_unresolved.normalization_status == "ROW_LABEL_FOOTNOTE_UNRESOLVED"

    note_digit_geometry = normalize_item_label_with_evidence(
        "债权投资计划注1",
        numeric_footnote_evidence=[{
            "marker": "1", "method": "NATIVE_SUPERSCRIPT_GEOMETRY",
            "page": 48,
        }],
    )
    assert note_digit_geometry.normalized_item == "债权投资计划"
    assert note_digit_geometry.footnote_markers == ("1",)

    note_digit_numbered = normalize_item_label_with_evidence(
        "其他投资注3",
        numeric_footnote_evidence=[{
            "marker": "3", "method": "SAME_PAGE_FOOTNOTE_NUMBER",
            "page": 48,
        }],
    )
    assert note_digit_numbered.normalized_item == "其他投资"
    assert note_digit_numbered.footnote_markers == ("3",)

    semantic = normalize_item_label_with_evidence("金融资产（按公允价值计量）")
    assert semantic.normalized_item == "金融资产（按公允价值计量）"
    assert semantic.normalization_status == "NORMALIZED_NO_FOOTNOTE"


def test_capture_long_preserves_raw_label_and_footnote_provenance() -> None:
    row = _row("现金及现金等价物(2)")
    row.footnote_evidence = [{
        "marker": "2",
        "method": "NATIVE_SUPERSCRIPT_GEOMETRY",
        "page": 48,
        "span": {"size": 5.2},
    }]
    apply_item_label_normalization(row)
    result = TableCaptureResult(
        pdf_name="新华保险2023年报.pdf",
        pdf_sha256="sha",
        table_query="投资组合情况",
        note_number=None,
        located_title="投资组合情况",
        start_page=48,
        end_page=48,
        pages=[48],
        unit="百万元",
        columns=[
            TableColumn(0, 1, "2023年 | 金额", "2023", None, False, "2023年", "金额")
        ],
        rows=[row],
        warnings=[],
        stats={},
        document_context={"currency": "CNY", "statement_scope": "CONSOLIDATED"},
    )
    long = capture_to_long_df(result)
    record = long.iloc[0]
    assert record["raw_item"] == "现金及现金等价物(2)"
    assert record["normalized_item"] == "现金及现金等价物"
    assert json.loads(record["footnote_markers"]) == ["2"]
    assert json.loads(record["footnote_evidence"])[0]["page"] == 48
    assert record["unit"] == "百万元"
    assert record["currency_unit"] == "CNY_MILLION"
    assert record["unit_source"] == "CERTIFIED_DIRECT_AMOUNT_UNIT"


def test_observation_unit_contract_is_measure_aware() -> None:
    amount = _resolve_observation_unit(
        raw_cell_unit=None,
        measure="金额",
        number=12.5,
        certified_amount_unit="百万元",
        page_context_unit="千元",
        page_context_source_page=48,
        certified_amount_unit_code="RMB_MILLION",
    )
    assert amount[:3] == (
        "百万元", 12_500_000.0, "CERTIFIED_DIRECT_AMOUNT_UNIT",
    )

    for measure in ("占比", "金额增减变动"):
        percent = _resolve_observation_unit(
            raw_cell_unit=None,
            measure=measure,
            number=12.5,
            certified_amount_unit="百万元",
            page_context_unit="千元",
        )
        assert percent[0] == "%"
        assert percent[1] is None
        assert percent[2] == "CERTIFIED_COLUMN_MEASURE"

    explicit = _resolve_observation_unit(
        raw_cell_unit="万元",
        measure="金额",
        number=2.0,
        certified_amount_unit="百万元",
        page_context_unit="千元",
    )
    assert explicit[:3] == ("万元", 20_000.0, "EXPLICIT_CELL_UNIT")

    unresolved = _resolve_observation_unit(
        raw_cell_unit=None,
        measure="金额",
        number=2.0,
        certified_amount_unit=None,
        page_context_unit=None,
    )
    assert unresolved[:3] == (
        None, None, "UNIT_UNRESOLVED_AMOUNT_OBSERVATION",
    )


def _mapped_observation(
    *,
    capture_run_id: str,
    report_year: str,
    measure: str,
    unit: str,
    currency_unit: str,
    value: float,
) -> dict[str, object]:
    return {
        "capture_run_id": capture_run_id,
        "table_id": "investment_portfolio",
        "table_family": "investment_portfolio",
        "member_table": "portfolio_summary",
        "member_table_role": "DIRECT_DISCLOSURE_TABLE",
        "container_id": "CONTAINER_1",
        "table_block_id": "BLOCK_1",
        "block_order": 0,
        "classification_axis": "PORTFOLIO_SUMMARY",
        "block_role": "PRIMARY",
        "block_terminal_type": "NONE",
        "source_table_title": "投资组合情况",
        "note_reference": "",
        "source_pdf": f"新华保险{report_year}年报.pdf",
        "row_path": "投资组合 / 投资资产",
        "canonical_key": "CANON::investment_portfolio::portfolio_summary::投资资产",
        "canonical_section": "投资组合",
        "canonical_item": "投资资产",
        "normalized_item": "投资资产",
        "row_item_normalized": "投资资产",
        "raw_item": "投资资产(2)" if report_year == "2023" else "投资资产",
        "row_item_raw": "投资资产(2)" if report_year == "2023" else "投资资产",
        "footnote_markers": '["2"]' if report_year == "2023" else None,
        "footnote_evidence": (
            '[{"marker":"2","method":"NATIVE_SUPERSCRIPT_GEOMETRY"}]'
            if report_year == "2023" else None
        ),
        "normalization_status": (
            "CERTIFIED_NUMERIC_FOOTNOTE_REMOVED"
            if report_year == "2023" else "NORMALIZED_NO_FOOTNOTE"
        ),
        "company": "新华保险",
        "report_year": report_year,
        "data_year": report_year,
        "statement_scope": "CONSOLIDATED",
        "restated_flag": False,
        "period_type": "ANNUAL",
        "currency_unit": currency_unit,
        "unit": unit,
        "measure": measure,
        "mapping_status": "AUTO_EXACT_IDENTITY",
        "value": value,
        "page": 48,
        "bbox": "{}",
    }


def test_merge_unit_conflicts_are_scoped_to_the_same_measure() -> None:
    cross_measure = pd.DataFrame([
        _mapped_observation(
            capture_run_id="CAP_2023", report_year="2023", measure="金额",
            unit="百万元", currency_unit="CNY_MILLION", value=100.0,
        ),
        _mapped_observation(
            capture_run_id="CAP_2023", report_year="2023", measure="占比",
            unit="%", currency_unit="PERCENT", value=100.0,
        ),
    ])
    resolved, _wide, conflicts = materialize_canonical(cross_measure)
    assert set(resolved["conflict_status"]) == {"OK"}
    assert conflicts.empty

    same_measure = pd.DataFrame([
        _mapped_observation(
            capture_run_id="CAP_A", report_year="2023", measure="金额",
            unit="百万元", currency_unit="CNY_MILLION", value=100.0,
        ),
        _mapped_observation(
            capture_run_id="CAP_B", report_year="2023", measure="金额",
            unit="千元", currency_unit="CNY_THOUSAND", value=100.0,
        ),
    ])
    resolved, _wide, conflicts = materialize_canonical(same_measure)
    assert set(resolved["conflict_status"]) == {"REVIEW_REQUIRED_UNIT_CONFLICT"}
    assert set(conflicts["conflict_severity"]) == {"WARNING"}


def test_unresolved_amount_observation_fails_closed_before_merge() -> None:
    frame = pd.DataFrame([
        _mapped_observation(
            capture_run_id="CAP_2023", report_year="2023", measure="金额",
            unit="", currency_unit="", value=100.0,
        )
    ])
    with pytest.raises(ValueError, match="UNIT_UNRESOLVED_AMOUNT_OBSERVATION"):
        materialize_canonical(frame)


def test_normalized_item_drives_cross_year_identity_without_collapsing_duplicates() -> None:
    def source_frame(capture_id: str, year: str, raw_item: str) -> pd.DataFrame:
        row = _mapped_observation(
            capture_run_id=capture_id,
            report_year=year,
            measure="金额",
            unit="百万元",
            currency_unit="CNY_MILLION",
            value=100.0,
        )
        row.update({
            "row_order": 1,
            "normalized_item": "现金及现金等价物",
            "row_item_normalized": "现金及现金等价物",
            "raw_item": raw_item,
            "row_item_raw": raw_item,
            "parent_section": "投资资产",
            "row_type": "DETAIL",
        })
        return assign_conditional_source_keys(pd.DataFrame([row]))

    raw = pd.concat([
        source_frame("CAP_2023", "2023", "现金及现金等价物(2)"),
        source_frame("CAP_2024", "2024", "现金及现金等价物"),
    ], ignore_index=True)
    assert raw["source_key"].nunique() == 1
    queue = build_mapping_queue(raw, "investment_portfolio")
    assert queue.iloc[0]["mapping_status"] == "AUTO_EXACT_IDENTITY"
    mapped = apply_mapping(raw, queue)
    assert mapped["canonical_item"].tolist() == [
        "现金及现金等价物", "现金及现金等价物",
    ]

    duplicate = pd.concat([source_frame("CAP_DUP", "2025", "现金")]*2, ignore_index=True)
    duplicate.loc[0, "row_order"] = 1
    duplicate.loc[1, "row_order"] = 2
    duplicate["normalized_item"] = "现金"
    disambiguated = assign_conditional_source_keys(duplicate)
    assert disambiguated["source_key"].nunique() == 2
    assert all("OCC" in value for value in disambiguated["source_key"])


def test_portfolio_golden_compares_logical_raw_label_not_physical_provenance(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    from golden_identity import build_identity_sidecar, dump_yaml, sidecar_filename

    golden_path = tmp_path / "investment_portfolio_golden.yaml"
    synthetic_golden = {
        "_path": str(golden_path),
        "golden_id": "SYNTHETIC_PORTFOLIO",
        "company_id": "SYNTHETIC",
        "legal_entity_name": "测试保险",
        "report_year": 2023,
        "source_scope": "LISTED_PARENT_CONSOLIDATED",
        "source": {
            "canonical_pdf_filename": "synthetic.pdf",
            "pdf_sha256": "a" * 64,
            "page_count": 1,
            "source_type": "ANNUAL_REPORT",
        },
        "physical_assets": [{
            "asset_id": "SYNTHETIC_TABLE",
            "physical_page_number": 1,
            "printed_page_number": 1,
            "title": "投资组合",
            "unit": "RMB_MILLION",
            "blocks": [{
                "member_id": "portfolio_by_category",
                "classification_axis": "BY_INVESTMENT_OBJECT",
                "current_period": {"label": "2023年", "amount": 100, "ratio_percent": 10},
                "comparative_period": {"label": "2022年", "amount": 90, "ratio_percent": 9},
                "rows": [{
                    "row_order": 1,
                    "raw_label": "现金及现金等价物(2)",
                    "normalized_label": "现金及现金等价物",
                    "row_kind": "DATA",
                    "current_amount": 100,
                    "current_ratio_percent": 10,
                    "comparative_amount": 90,
                    "comparative_ratio_percent": 9,
                }],
            }],
        }],
    }
    dump_yaml(
        tmp_path / sidecar_filename("investment_portfolio"),
        build_identity_sidecar(family="investment_portfolio", golden=synthetic_golden),
    )
    monkeypatch.setattr(
        golden_acceptance,
        "load_portfolio_golden",
        lambda *_args, **_kwargs: synthetic_golden,
    )
    capture = {
        "portfolio_by_category": {
            "rows": [{
                "raw_item": "按投资对象分类现金及现金等价物(2)",
                "row_item_raw": "现金及现金等价物注2",
                "normalized_item": "现金及现金等价物",
                "row_item_normalized": "现金及现金等价物",
                "row_type": "DETAIL",
                "cells": [
                    {"column_ordinal": 0, "parsed_number": 100},
                    {"column_ordinal": 1, "parsed_number": 10},
                    {"column_ordinal": 2, "parsed_number": 90},
                    {"column_ordinal": 3, "parsed_number": 9},
                ],
            }],
        },
    }

    comparison = golden_acceptance.compare_portfolio_capture_rows(
        "新华保险", "2023", capture,
    )

    assert comparison["status"] == "MATCH"
    raw_label = next(row for row in comparison["rows"] if row["field"] == "raw_label")
    assert raw_label["machine"] == "现金及现金等价物注2"
    assert raw_label["result"] == "MATCH"
    assert raw_label["audit_result"] == "DIFFERENT_NON_BLOCKING"


def test_portfolio_golden_reports_one_semantic_identity_delta_without_numeric_amplification(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    from golden_identity import build_identity_sidecar, dump_yaml, sidecar_filename

    golden_path = tmp_path / "investment_portfolio_golden.yaml"
    synthetic_golden = {
        "_path": str(golden_path),
        "golden_id": "SYNTHETIC_HIERARCHY_COMPARATOR",
        "company_id": "SYNTHETIC",
        "legal_entity_name": "测试保险",
        "report_year": 2025,
        "source_scope": "LISTED_PARENT_CONSOLIDATED",
        "source": {
            "canonical_pdf_filename": "synthetic.pdf",
            "pdf_sha256": "b" * 64,
            "page_count": 1,
            "source_type": "ANNUAL_REPORT",
        },
        "physical_assets": [{
            "asset_id": "SYNTHETIC_TABLE",
            "physical_page_number": 1,
            "printed_page_number": 1,
            "title": "投资组合",
            "unit": "RMB_MILLION",
            "blocks": [{
                "member_id": "portfolio_by_category",
                "classification_axis": "BY_INVESTMENT_OBJECT",
                "current_period": {"label": "2025年12月31日"},
                "comparative_period": {"label": "2024年12月31日"},
                "rows": [
                    {
                        "row_order": 1, "raw_label": "债权类金融资产",
                        "normalized_label": "债权类金融资产", "row_kind": "GROUP",
                        "current_amount": None, "current_ratio_percent": None,
                        "comparative_amount": None, "comparative_ratio_percent": None,
                    },
                    {
                        "row_order": 2, "raw_label": "债券",
                        "normalized_label": "债券", "row_kind": "DATA",
                        "current_amount": 100, "current_ratio_percent": 10,
                        "comparative_amount": 90, "comparative_ratio_percent": 9,
                    },
                ],
            }],
        }],
    }
    dump_yaml(
        tmp_path / sidecar_filename("investment_portfolio"),
        build_identity_sidecar(family="investment_portfolio", golden=synthetic_golden),
    )
    monkeypatch.setattr(
        golden_acceptance,
        "load_portfolio_golden",
        lambda *_args, **_kwargs: synthetic_golden,
    )
    capture = {
        "portfolio_by_category": {
            "rows": [
                {
                    "source_row_id": "GROUP_SOURCE",
                    "parent_row_id": None,
                    "row_item_raw": "债权类金融资产",
                    "row_item_normalized": "债权类金融资产",
                    "row_type": "DETAIL",
                    "cells": [],
                },
                {
                    "source_row_id": "CHILD_SOURCE",
                    "parent_row_id": None,
                    "row_item_raw": "债券",
                    "row_item_normalized": "债券",
                    "row_type": "DETAIL",
                    "cells": [
                        {"column_ordinal": 0, "parsed_number": 100},
                        {"column_ordinal": 1, "parsed_number": 10},
                        {"column_ordinal": 2, "parsed_number": 90},
                        {"column_ordinal": 3, "parsed_number": 9},
                    ],
                },
            ],
        },
    }

    comparison = golden_acceptance.compare_portfolio_capture_rows(
        "测试保险", "2025", capture, root=tmp_path,
    )

    mismatches = [row for row in comparison["rows"] if row["result"] == "MISMATCH"]
    assert comparison["status"] == "MISMATCH"
    assert [row["field"] for row in mismatches] == ["row_kind", "semantic_identity"]
    assert not any(row["field"] in {
        "current_amount", "current_ratio_percent",
        "comparative_amount", "comparative_ratio_percent",
    } for row in mismatches)
