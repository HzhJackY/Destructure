"""Shared point-period normalization for Capture, Canonical, and Merge."""
from __future__ import annotations

import datetime as dt
import re
from typing import Any, Optional


_RELATIVE_PERIOD_KINDS = {
    "本年累计数": "CURRENT",
    "本年度累计数": "CURRENT",
    "本期累计数": "CURRENT",
    "本期数": "CURRENT",
    "本年数": "CURRENT",
    "本期": "CURRENT",
    "本年": "CURRENT",
    "本年度": "CURRENT",
    "当期累计数": "CURRENT",
    "当期": "CURRENT",
    "上年累计数": "PRIOR",
    "上年度累计数": "PRIOR",
    "上期累计数": "PRIOR",
    "上期数": "PRIOR",
    "上年数": "PRIOR",
    "上期": "PRIOR",
    "上年": "PRIOR",
    "上年度": "PRIOR",
    "去年": "PRIOR",
    "去年累计数": "PRIOR",
    "去年数": "PRIOR",
    "去年同期": "PRIOR",
    "上年同期": "PRIOR",
    "上年度同期": "PRIOR",
    "期末": "CURRENT_END",
    "本期期末": "CURRENT_END",
    "本年末": "CURRENT_END",
    "本年度末": "CURRENT_END",
    "期初": "CURRENT_BEGIN",
    "本期期初": "CURRENT_BEGIN",
    "本年初": "CURRENT_BEGIN",
    "本年度初": "CURRENT_BEGIN",
}


def _compact(value: Any) -> str:
    if value is None:
        return ""
    text = str(value).strip()
    if text in {"", "<NA>", "nan", "NaN", "NaT"}:
        return ""
    return re.sub(r"\s+", "", text).replace("（", "(").replace("）", ")")


def _strip_period_suffixes(value: str) -> str:
    token = re.sub(r"\(?(?:已重述|经重述|重述后|重述)\)?", "", value)
    token = re.sub(r"(?:人民币)?(?:亿元|百万元|万元|千元|元)$", "", token)
    parenthesised = re.sub(r"\(\d+\)$", "", token)
    if parenthesised != token:
        return parenthesised
    return re.sub(r"(?<=[日末初度])\d+$", "", token)


def _absolute_payload(
    *,
    raw: str,
    year: int,
    month: Optional[int],
    day: Optional[int],
    derivation: str = "LITERAL",
) -> dict[str, Any]:
    if day is not None:
        if month is None:
            raise ValueError("PERIOD_COMPONENTS_INVALID:DAY_WITHOUT_MONTH")
        try:
            value = dt.date(year, month, day)
        except ValueError as exc:
            raise ValueError(
                f"PERIOD_COMPONENTS_INVALID:{year:04d}-{month:02d}-{day:02d}"
            ) from exc
        label = f"{year}年{month}月{day}日"
        precision = "DAY"
        period_date = value.isoformat()
        identity = f"DATE:{period_date}"
        kind = "ABSOLUTE_DATE"
    elif month is not None:
        if not 1 <= month <= 12:
            raise ValueError(f"PERIOD_COMPONENTS_INVALID:{year:04d}-{month:02d}")
        label = f"{year}年{month}月"
        precision = "MONTH"
        period_date = None
        identity = f"MONTH:{year:04d}-{month:02d}"
        kind = "ABSOLUTE_MONTH"
    else:
        label = str(year)
        precision = "YEAR"
        period_date = None
        identity = f"YEAR:{year:04d}"
        kind = "ABSOLUTE_YEAR"
    return {
        "token": raw,
        "source_period_label": raw,
        "year": str(year),
        "period_label": label,
        "period_year": year,
        "period_month": month,
        "period_day": day,
        "period_precision": precision,
        "period_date": period_date,
        "period_identity": identity,
        "period_kind": kind,
        "period_normalization_evidence": {
            "method": derivation,
            "source_period_label": raw,
        },
    }


def normalize_period_token(text: Any) -> Optional[dict[str, Any]]:
    raw = _compact(text)
    token = _strip_period_suffixes(_compact(raw))
    if not token:
        return None

    change_match = re.fullmatch(r"(.+?)较(.+)", token)
    if change_match:
        left = normalize_period_token(change_match.group(1))
        right = normalize_period_token(change_match.group(2))
        if left and right:
            return {
                "token": raw,
                "source_period_label": raw,
                "year": None,
                "period_label": f"{left['period_label']}较{right['period_label']}",
                "period_year": None,
                "period_month": None,
                "period_day": None,
                "period_precision": "COMPOSITE",
                "period_date": None,
                "period_identity": (
                    f"CHANGE:{left['period_identity']}->{right['period_identity']}"
                ),
                "period_kind": "PERIOD_CHANGE",
                "period_normalization_evidence": {
                    "method": "COMPOSITE_PERIOD_CHANGE",
                    "source_period_label": raw,
                    "left": left["period_identity"],
                    "right": right["period_identity"],
                },
            }

    full_date = re.fullmatch(r"(?:截至)?(20\d{2})年(\d{1,2})月(\d{1,2})日?", token)
    if full_date:
        return _absolute_payload(
            raw=raw,
            year=int(full_date.group(1)),
            month=int(full_date.group(2)),
            day=int(full_date.group(3)),
        )

    month_period = re.fullmatch(r"(?:截至)?(20\d{2})年(\d{1,2})月", token)
    if month_period:
        return _absolute_payload(
            raw=raw,
            year=int(month_period.group(1)),
            month=int(month_period.group(2)),
            day=None,
        )

    year_boundary = re.fullmatch(r"(?:截至)?(20\d{2})年(末|初)", token)
    if year_boundary:
        is_end = year_boundary.group(2) == "末"
        return _absolute_payload(
            raw=raw,
            year=int(year_boundary.group(1)),
            month=12 if is_end else 1,
            day=31 if is_end else 1,
            derivation="DERIVED_CALENDAR_YEAR_BOUNDARY",
        )

    year_period = re.fullmatch(r"(?:截至)?(20\d{2})(?:年(?:度)?)?", token)
    if year_period:
        return _absolute_payload(
            raw=raw,
            year=int(year_period.group(1)),
            month=None,
            day=None,
        )

    legacy_float_match = re.fullmatch(r"((?:19|20)\d{2})\.0", token)
    if legacy_float_match:
        return _absolute_payload(
            raw=raw,
            year=int(legacy_float_match.group(1)),
            month=None,
            day=None,
            derivation="LEGACY_FLOAT_COERCED_YEAR_REPAIR",
        )

    relative_kind = _RELATIVE_PERIOD_KINDS.get(token)
    if relative_kind:
        return {
            "token": raw,
            "source_period_label": raw,
            "year": token,
            "period_label": token,
            "period_year": None,
            "period_month": None,
            "period_day": None,
            "period_precision": "UNRESOLVED",
            "period_date": None,
            "period_identity": f"RELATIVE:{relative_kind}:{token}",
            "period_kind": relative_kind,
            "period_normalization_evidence": {
                "method": "RELATIVE_PERIOD_PRESERVED",
                "source_period_label": raw,
            },
        }
    return None


def normalize_period_fields(
    *,
    source_period_label: Any = None,
    period_label: Any = None,
    year: Any = None,
) -> dict[str, Any]:
    for candidate in (source_period_label, period_label, year):
        parsed = normalize_period_token(candidate)
        if parsed:
            return parsed
    fallback = next(
        (_compact(candidate) for candidate in (source_period_label, period_label, year)
         if _compact(candidate)),
        "",
    )
    return {
        "token": fallback,
        "source_period_label": fallback,
        "year": _compact(year) or None,
        "period_label": _compact(period_label) or _compact(year) or None,
        "period_year": None,
        "period_month": None,
        "period_day": None,
        "period_precision": "UNRESOLVED",
        "period_date": None,
        "period_identity": None,
        "period_kind": "UNRESOLVED",
        "period_normalization_evidence": {
            "method": "UNRESOLVED",
            "source_period_label": fallback,
        },
    }
