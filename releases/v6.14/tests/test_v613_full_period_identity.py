from __future__ import annotations

import pandas as pd
import pytest

from period_identity import normalize_period_token
from table_capture import analyze_column_dimensions
from table_merge import (
    _ensure_period_identity_columns,
    _resolve_relative_period_years,
    period_precision_audit,
)


@pytest.mark.parametrize(
    ("source", "identity", "label", "year", "month", "day", "precision"),
    [
        ("2023年12月31日", "DATE:2023-12-31", "2023年12月31日", 2023, 12, 31, "DAY"),
        ("2023年1月1日", "DATE:2023-01-01", "2023年1月1日", 2023, 1, 1, "DAY"),
        ("2023年12月", "MONTH:2023-12", "2023年12月", 2023, 12, None, "MONTH"),
        ("2023年", "YEAR:2023", "2023", 2023, None, None, "YEAR"),
        ("2023年末", "DATE:2023-12-31", "2023年12月31日", 2023, 12, 31, "DAY"),
        ("2023年初", "DATE:2023-01-01", "2023年1月1日", 2023, 1, 1, "DAY"),
    ],
)
def test_point_period_contract_preserves_available_precision(
    source, identity, label, year, month, day, precision,
):
    period = normalize_period_token(source)
    assert period is not None
    assert period["period_identity"] == identity
    assert period["period_label"] == label
    assert period["period_year"] == year
    assert period["period_month"] == month
    assert period["period_day"] == day
    assert period["period_precision"] == precision


def test_invalid_calendar_date_is_blocked():
    with pytest.raises(ValueError, match="PERIOD_COMPONENTS_INVALID"):
        normalize_period_token("2023年2月29日")


def test_v3_capture_labels_are_adapted_without_rewriting_source_label():
    legacy = pd.DataFrame([
        {
            "source_period_label": "2023年12月31日",
            "period_label": "2023年12月31日",
            "data_year": "2023",
        },
        {
            "source_period_label": "2023年1月1日",
            "period_label": "2023年1月1日",
            "data_year": "2023",
        },
    ])

    adapted = _ensure_period_identity_columns(legacy)

    assert adapted["source_period_label"].tolist() == [
        "2023年12月31日", "2023年1月1日",
    ]
    assert adapted["period_identity"].tolist() == [
        "DATE:2023-12-31", "DATE:2023-01-01",
    ]
    assert adapted["data_year"].tolist() == ["2023", "2023"]


def test_structure_only_row_does_not_require_period_identity():
    source = pd.DataFrame([{
        "raw_item": "金融投资",
        "normalized_item": "金融投资",
        "value": None,
        "period_label": None,
    }])

    adapted = _ensure_period_identity_columns(source)

    assert pd.isna(adapted.at[0, "period_identity"])


def test_numeric_observation_still_requires_period_identity():
    source = pd.DataFrame([{
        "raw_item": "金融投资",
        "normalized_item": "金融投资",
        "value": 100,
        "period_label": None,
    }])

    with pytest.raises(ValueError, match="PERIOD_DATE_UNRESOLVED"):
        _ensure_period_identity_columns(source)


def test_same_year_distinct_dates_do_not_collide_in_header_identity():
    result = analyze_column_dimensions([
        {
            "ordinal": 0,
            "header_raw": "2023年12月31日",
            "year": "2023",
            "period_label": "2023年12月31日",
            "measure": "金额",
            "scope": "CONSOLIDATED",
            "restated": False,
        },
        {
            "ordinal": 1,
            "header_raw": "2023年1月1日",
            "year": "2023",
            "period_label": "2023年1月1日",
            "measure": "金额",
            "scope": "CONSOLIDATED",
            "restated": False,
        },
    ])

    assert result["status"] == "AUTO_CONFIRMED"
    assert [column["period_identity"] for column in result["columns"]] == [
        "DATE:2023-12-31", "DATE:2023-01-01",
    ]


def test_year_and_date_precision_difference_is_nonblocking_audit():
    source = pd.DataFrame([
        {
            "company": "中国太保", "report_year": "2023",
            "member_table": "portfolio_by_category", "canonical_item": "债券",
            "measure": "金额", "period_label": "2023年", "value": 1,
        },
        {
            "company": "中国太保", "report_year": "2023",
            "member_table": "portfolio_by_category", "canonical_item": "债券",
            "measure": "金额", "period_label": "2023年12月31日", "value": 1,
        },
    ])

    audit = period_precision_audit(source)

    assert audit["audit_code"].tolist() == ["PERIOD_PRECISION_MISMATCH"]
    assert audit["blocking"].tolist() == [False]


@pytest.mark.parametrize("period_type", ["QUARTERLY", "SEMIANNUAL"])
def test_relative_nonannual_period_requires_certified_period_end(period_type):
    raw = pd.DataFrame([
        {
            "year": "本期",
            "period_label": "本期",
            "source_period_label": "本期",
            "period_type": period_type,
        }
    ])

    with pytest.raises(ValueError, match="PERIOD_DATE_UNRESOLVED"):
        _resolve_relative_period_years(raw, "2024")
