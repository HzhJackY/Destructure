"""Independent Golden Corpus comparison for Streamlit guided acceptance.

Golden data is read-only evidence outside DATA_HOME.  It is never populated
from the current extraction, so a match is useful and a mismatch remains a
review requirement rather than an automatic rewrite.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[2]
GOLDEN_ROOT = PROJECT_ROOT / "golden_corpus" / "v1.1.0"
COMPANY_DIRS = {
    "中国平安": "ping_an",
    "新华保险": "new_china_life",
    "中国太保": "cpic",
    "中国人寿": "china_life",
}
_MEMBER_TERMS = {
    "fvtpl_assets": ("交易性金融资产", "以公允价值计量且其变动计入当期损益的金融资产"),
    "debt_investment": ("债权投资",),
    "other_debt_investment": ("其他债权投资",),
    "other_equity_investment": ("其他权益工具投资",),
    # 中国人寿旧准则披露下的金融投资是隐式成员集合，而非仅 IFRS 9
    # 的四个金融资产项目。Golden 验收必须识别这些原始主表成员，不能
    # 因为缺少别名而把正确的 UI Anchor 误判为不匹配。
    "loans": ("贷款",),
    "term_deposits": ("定期存款",),
    "available_for_sale_assets": ("可供出售金融资产",),
    "held_to_maturity_investments": ("持有至到期投资",),
}

# The discovery/template layer can preserve a pre-IFRS-9 member identifier
# while Golden fixtures intentionally use the stable research identifier.  This
# is an identity alias only: labels, note references and amounts are still
# compared independently below.  Keep this mapping deliberately small and
# explicit; it is not a cross-company name-normalisation rule.
_CANONICAL_MEMBER_ALIASES = {
    "legacy_fvtpl_assets": "fvtpl_assets",
    "legacy_loans": "loans",
    "time_deposits": "term_deposits",
}

# A Golden filing can legitimately contain a current-period IFRS 9 member set
# and comparative-period IFRS 39 rows on the same physical statement page.
# The latter remain valuable certified evidence, but they cannot become a
# required condition for certifying the current-period Statement Anchor.
CURRENT_PERIOD_MEMBER_STATUS = "ACTIVE_CURRENT_PERIOD"


def _normalise(value: Any) -> str:
    return re.sub(r"[\s：:（）()，,\-—]", "", str(value or "")).lower()


def _amount(value: Any) -> int | None:
    if value is None:
        return None
    raw = str(value).strip()
    token = re.sub(r"[^0-9\-]", "", raw)
    try:
        if token in {"", "-"}:
            return None
        result = int(token)
        return -abs(result) if raw.startswith("(") and raw.endswith(")") else result
    except ValueError:
        return None


def _note_ordinal(value: Any) -> str:
    found = re.findall(r"\d+", str(value or ""))
    return found[-1] if found else ""


def _member_id(row: dict[str, Any]) -> str:
    for key in ("member_id", "canonical_concept_id", "member_table_id"):
        value = str(row.get(key) or "")
        value = _CANONICAL_MEMBER_ALIASES.get(value, value)
        if value in _MEMBER_TERMS:
            return value
    raw_label = str(row.get("member_table") or row.get("item") or row.get("raw_label") or "")
    direct_alias = _CANONICAL_MEMBER_ALIASES.get(raw_label)
    if direct_alias:
        return direct_alias
    label = _normalise(raw_label)
    # Prefer exact labels, then longest aliases.  Otherwise “债权投资” would
    # incorrectly swallow the more specific “其他债权投资”.
    for member_id, terms in _MEMBER_TERMS.items():
        if any(label == _normalise(term) for term in terms):
            return member_id
    candidates = [
        (len(_normalise(term)), member_id, term)
        for member_id, terms in _MEMBER_TERMS.items()
        for term in terms
    ]
    for _, member_id, term in sorted(candidates, reverse=True):
        normalised_term = _normalise(term)
        if normalised_term in label or label in normalised_term:
            return member_id
    return ""


def _current_amounts(row: dict[str, Any]) -> list[int]:
    raw = (
        row.get("statement_amount_normalized")
        or row.get("statement_amount_raw")
        or row.get("values")
        or row.get("value")
        or []
    )
    if not isinstance(raw, list):
        raw = [raw]
    certified = [value for value in (_amount(item) for item in raw) if value is not None]
    if certified:
        return certified
    # A scanned main statement cannot populate certified financial values.
    # It may, however, be compared with an independent Golden Anchor if each
    # token is explicitly bound to a period header and an amount column by
    # immutable OCR BBox evidence.  Keep this isolated from downstream
    # Capture/Canonical fields.
    spatial = row.get("anchor_amount_observations") or []
    return [
        value
        for value in (_amount(item.get("raw_value")) for item in spatial if isinstance(item, dict))
        if value is not None
    ]


def load_golden(company: str, report_year: str | int, *, root: Path = GOLDEN_ROOT) -> dict[str, Any] | None:
    company_dir = COMPANY_DIRS.get(str(company or ""))
    path = root / "companies" / str(company_dir or "") / str(report_year) / "golden_values.yaml"
    if not company_dir or not path.is_file():
        return None
    try:
        import yaml
        return dict(yaml.safe_load(path.read_text(encoding="utf-8")) or {}) | {"_path": str(path)}
    except Exception as exc:
        return {"_path": str(path), "_load_error": f"{type(exc).__name__}:{exc}"}


def load_page_anchors(company: str, report_year: str | int, *, root: Path = GOLDEN_ROOT) -> dict[str, Any] | None:
    company_dir = COMPANY_DIRS.get(str(company or ""))
    path = root / "companies" / str(company_dir or "") / str(report_year) / "page_anchors.yaml"
    if not company_dir or not path.is_file():
        return None
    try:
        import yaml
        return dict(yaml.safe_load(path.read_text(encoding="utf-8")) or {}) | {"_path": str(path)}
    except Exception as exc:
        return {"_path": str(path), "_load_error": f"{type(exc).__name__}:{exc}"}


def golden_member_contract(golden: dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
    """Partition independently certified facts by their reporting-period role.

    ``ACTIVE_CURRENT_PERIOD`` is the only status that may block Stage-A
    current-anchor certification.  Every other explicitly tagged row is kept
    as a historical variant: visible, auditable and still available to the
    child-table parity comparator, but never silently promoted to a current
    required member.  Older Golden fixtures without a status stay conservative
    and are treated as current requirements for backward compatibility.
    """
    current_required: list[dict[str, Any]] = []
    historical_variants: list[dict[str, Any]] = []
    for value in golden.get("values") or []:
        status = str(value.get("status") or "").strip()
        if not status or status == CURRENT_PERIOD_MEMBER_STATUS:
            current_required.append(value)
        else:
            historical_variants.append(value)
    return {
        "current_required_members": current_required,
        "historical_variants": historical_variants,
    }


def compare_child_target(
    company: str,
    report_year: str | int,
    *,
    member_label: str,
    note_reference: str,
    candidate_page: int | str | None,
    candidate_heading: str = "",
    root: Path = GOLDEN_ROOT,
) -> dict[str, Any]:
    """Compare a Stage-B note target against independently certified pages."""
    anchor = load_page_anchors(company, report_year, root=root)
    if anchor is None:
        return {"status": "NO_GOLDEN", "rows": []}
    if anchor.get("_load_error"):
        return {"status": "GOLDEN_UNAVAILABLE", "error": anchor["_load_error"], "rows": []}
    ordinal = _note_ordinal(note_reference)
    expected = next(
        (item for item in ((anchor.get("child_note_pages") or {}).get("notes") or [])
         if _note_ordinal(item.get("note_number")) == ordinal),
        None,
    )
    if expected is None:
        return {"status": "NO_GOLDEN_TARGET", "golden_path": anchor.get("_path"), "rows": []}
    expected_page = _amount(expected.get("pdf_page_number"))
    actual_page = _amount(candidate_page)
    expected_label = _normalise(expected.get("label"))
    actual_label = _normalise(member_label)
    heading = _normalise(candidate_heading)
    actual_member = _member_id({"member_table": member_label})
    expected_member = _member_id({"member_table": expected.get("label")})
    label_match = bool(
        actual_label
        and (
            (actual_member and actual_member == expected_member)
            or actual_label in expected_label
            or expected_label in actual_label
        )
    )
    heading_match = not heading or any(token in heading for token in (actual_label, expected_label))
    page_match = expected_page == actual_page
    status = "MATCH" if page_match and label_match and heading_match else "MISMATCH"
    return {
        "status": status,
        "golden_path": anchor.get("_path"),
        "expected_note": expected.get("note_number"),
        "expected_label": expected.get("label"),
        "expected_page": expected_page,
        "observed_note": note_reference,
        "observed_label": member_label,
        "observed_page": actual_page,
        "observed_heading": candidate_heading,
        "page_match": page_match,
        "label_match": label_match,
        "heading_match": heading_match,
    }


def compare_child_capture_csv(
    company: str,
    report_year: str | int,
    *,
    member_label: str,
    raw_long_path: Path | list[Path],
    root: Path = GOLDEN_ROOT,
) -> dict[str, Any]:
    """Compare actual captured child-table cells with independently marked rows."""
    golden = load_golden(company, report_year, root=root)
    if golden is None:
        return {"status": "NO_GOLDEN", "rows": []}
    if golden.get("_load_error"):
        return {"status": "GOLDEN_UNAVAILABLE", "error": golden["_load_error"], "rows": []}
    member = _member_id({"member_table": member_label})
    expected = next((row for row in golden.get("values") or [] if row.get("member_id") == member), None)
    if not expected or not expected.get("child_table"):
        return {"status": "NO_GOLDEN_CHILD", "rows": []}
    try:
        import pandas as pd
        import gc
        paths = raw_long_path if isinstance(raw_long_path, list) else [raw_long_path]
        frames = [pd.read_csv(path, dtype=str) for path in paths if Path(path).is_file()]
        if not frames:
            return {"status": "CAPTURE_UNREADABLE", "error": "NO_RAW_LONG_EVIDENCE", "rows": []}
        frame = pd.concat(frames, ignore_index=True)
        numeric = frame[frame.get("value_raw", pd.Series(index=frame.index, dtype=str)).notna()].copy()
        rows = []
        for expected_item in expected["child_table"].get("items") or []:
            label = _normalise(expected_item.get("raw_label"))
            candidates = numeric[
                numeric.apply(
                    lambda row: _normalise(row.get("normalized_item") or row.get("raw_item")) == label,
                    axis=1,
                )
            ]
            for key, expected_raw in expected_item.items():
                if not key.startswith("amount_"):
                    continue
                match = re.fullmatch(r"amount_(\d{4})(?:_(restated))?", key)
                if not match:
                    continue
                data_year, restated_marker = match.groups()
                period_rows = candidates[
                    candidates.apply(
                        lambda row: str(row.get("data_year") or row.get("year") or "") == data_year
                        and (not restated_marker or str(row.get("restated_flag") or row.get("restated") or "").lower() in {"true", "1"}),
                        axis=1,
                    )
                ]
                raw_values = period_rows["value_raw"].tolist() if "value_raw" in period_rows.columns else []
                observed_values = [_amount(value) for value in raw_values]
                observed_values = [value for value in observed_values if value is not None]
                expected_value = _amount(expected_raw)
                status = (
                    "MATCH" if len(observed_values) == 1 and observed_values[0] == expected_value
                    else "MISMATCH"
                )
                rows.append({
                    "member_id": member,
                    "item": expected_item.get("raw_label"),
                    "period": key,
                    "golden_value": expected_raw,
                    "observed_values": observed_values,
                    "status": status,
                })
        status = "MATCH" if rows and all(row["status"] == "MATCH" for row in rows) else "MISMATCH"
        return {"status": status, "golden_path": golden.get("_path"), "rows": rows}
    except Exception as exc:
        return {"status": "CAPTURE_UNREADABLE", "error": f"{type(exc).__name__}:{exc}", "rows": []}
    finally:
        try:
            del frame, numeric, frames
            gc.collect()
        except UnboundLocalError:
            pass


def compare_statement_anchor(company: str, report_year: str | int, child_rows: list[dict[str, Any]], *, root: Path = GOLDEN_ROOT) -> dict[str, Any]:
    """Compare current-period Stage-A facts without collapsing legacy variants.

    This function deliberately does *not* make a comparative-period Golden row
    a missing current member.  The returned ``historical_variants`` preserve
    those independently certified facts for UI evidence and later detail-table
    parity, while ``missing_current_members`` gives the exact blocking reason.
    """
    golden = load_golden(company, report_year, root=root)
    if golden is None:
        return {"status": "NO_GOLDEN", "company": company, "report_year": str(report_year), "rows": []}
    if golden.get("_load_error"):
        return {"status": "GOLDEN_UNAVAILABLE", "company": company, "report_year": str(report_year), "error": golden["_load_error"], "rows": []}
    contract = golden_member_contract(golden)
    actual = {member: row for row in child_rows if (member := _member_id(row))}
    rows = []
    missing_current_members: list[str] = []
    for expected in contract["current_required_members"]:
        member = str(expected.get("member_id") or "")
        lookup_member = _member_id({"member_id": member}) or member
        observed = actual.get(lookup_member)
        expected_amount = _amount(expected.get("current_amount_raw"))
        observed_amounts = _current_amounts(observed or {})
        note_match = bool(observed) and _note_ordinal(observed.get("note_reference_normalized") or observed.get("note_reference")) == _note_ordinal(expected.get("note_reference"))
        amount_match = expected_amount in observed_amounts
        status = "MATCH" if observed and note_match and amount_match else "MISMATCH"
        if status == "MISMATCH":
            missing_current_members.append(member)
        rows.append({
            "member_id": member,
            "golden_label": expected.get("raw_label"),
            "golden_note": expected.get("note_reference"),
            "golden_current_amount": expected.get("current_amount_raw"),
            "observed_label": (observed or {}).get("member_table") or (observed or {}).get("item") or (observed or {}).get("raw_label") or "未找到",
            "observed_note": (observed or {}).get("note_reference_normalized") or (observed or {}).get("note_reference") or "未找到",
            "observed_amounts": observed_amounts,
            "note_match": note_match,
            "amount_match": amount_match,
            "status": status,
        })
    historical_variants = [
        {
            "member_id": str(expected.get("member_id") or ""),
            "golden_label": expected.get("raw_label"),
            "golden_note": expected.get("note_reference"),
            "golden_status": expected.get("status"),
            "observed_in_current_anchor": str(expected.get("member_id") or "") in actual,
        }
        for expected in contract["historical_variants"]
    ]
    return {
        "status": "MATCH" if rows and all(row["status"] == "MATCH" for row in rows) else "MISMATCH",
        "company": company,
        "report_year": str(report_year),
        "golden_path": golden.get("_path"),
        "rows": rows,
        "current_required_member_ids": [
            str(expected.get("member_id") or "")
            for expected in contract["current_required_members"]
        ],
        "missing_current_members": missing_current_members,
        "historical_variants": historical_variants,
        "comparison_scope": "CURRENT_PERIOD_REQUIRED_MEMBERS_ONLY",
    }
