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
GOLDEN_ROOT = PROJECT_ROOT / "golden_corpus" / "v1.2.0"
COMPANY_DIRS = {
    "中国平安": "ping_an",
    "新华保险": "new_china_life",
    "中国太保": "cpic",
    "中国人寿": "china_life",
    "中国人保": "picc",
    "中国人民保险集团股份有限公司": "picc",
}
PORTFOLIO_COMPANY_DIRS = {
    "中国平安": "ping_an",
    "中国平安保险集团股份有限公司": "ping_an",
    "新华保险": "new_china_life",
    "新华人寿保险股份有限公司": "new_china_life",
    "中国太保": "cpic_group",
    "中国太平洋保险集团股份有限公司": "cpic_group",
    "中国人寿": "china_life",
    "中国人寿保险股份有限公司": "china_life",
    "中国人保": "picc",
    "中国人民保险集团股份有限公司": "picc",
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


def _row_label_variants(row: Any) -> set[str]:
    """Return certified label variants without discarding source evidence.

    Capture keeps footnote-bearing source labels and may also project a parent
    section (for example ``其中`` + ``成本``).  Golden v1.1 stored both forms,
    so parity must recognise the explicit source/path variants rather than
    forcing one display spelling.
    """
    raw = str(row.get("raw_item") or "")
    normalized = str(row.get("normalized_item") or "")
    parent = str(row.get("parent_section") or "")
    variants = {
        value for value in (
            _normalise(raw),
            _normalise(normalized),
            _normalise(parent + raw),
            _normalise(parent + normalized),
        ) if value
    }
    if str(row.get("row_role") or "").upper() == "IMPLICIT_TOTAL":
        variants.add(_normalise("合计"))
    return variants


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
    raw_label = str(row.get("member_table") or row.get("item") or row.get("raw_label") or "").strip()
    # Runtime Capture requests carry the stable Registry identity directly.
    # Treating that identifier as a display label made every valid English
    # member_table_id miss the Golden child-table contract.
    canonical_raw_label = _CANONICAL_MEMBER_ALIASES.get(raw_label, raw_label)
    if canonical_raw_label in _MEMBER_TERMS:
        return canonical_raw_label
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


def load_portfolio_golden(
    company: str,
    report_year: str | int,
    *,
    root: Path = GOLDEN_ROOT,
) -> dict[str, Any] | None:
    key = _normalise(company)
    company_dir = next(
        (
            directory for alias, directory in PORTFOLIO_COMPANY_DIRS.items()
            if _normalise(alias) == key or _normalise(alias) in key or key in _normalise(alias)
        ),
        None,
    )
    path = root / "companies" / str(company_dir or "") / str(report_year) / "investment_portfolio_golden.yaml"
    if not company_dir or not path.is_file():
        return None
    try:
        import yaml
        return dict(yaml.safe_load(path.read_text(encoding="utf-8")) or {}) | {"_path": str(path)}
    except Exception as exc:
        return {"_path": str(path), "_load_error": f"{type(exc).__name__}:{exc}"}


def compare_portfolio_anchor(
    company: str,
    report_year: str | int,
    candidate: dict[str, Any],
    *,
    root: Path = GOLDEN_ROOT,
) -> dict[str, Any]:
    """Stage-A gate for direct portfolio source identity and topology.

    The comparator never adds rows, values or candidate evidence.  It only
    reports whether the machine-selected page/topology agrees with the
    independently maintained Golden corpus.
    """
    golden = load_portfolio_golden(company, report_year, root=root)
    if golden is None:
        return {"status": "NO_GOLDEN", "rows": []}
    if golden.get("_load_error"):
        return {"status": "GOLDEN_UNAVAILABLE", "error": golden["_load_error"], "rows": []}
    expected_pages = sorted({
        int(asset["physical_page_number"]) for asset in golden.get("physical_assets") or []
    })
    actual_page = _amount(
        candidate.get("statement_pdf_page_index")
        or candidate.get("candidate_note_pdf_page_index")
    )
    expected_members = sorted({
        str(block["member_id"])
        for asset in golden.get("physical_assets") or []
        for block in asset.get("blocks") or []
    })
    actual_members = sorted({
        str(child.get("member_table") or child.get("canonical_concept_id") or "")
        for child in candidate.get("child_rows") or []
        if str(child.get("member_table") or child.get("canonical_concept_id") or "")
    })
    expected_totals = sorted({
        int(block["current_period"]["amount"])
        for asset in golden.get("physical_assets") or []
        for block in asset.get("blocks") or []
    })
    evidence = dict(candidate.get("evidence") or {})
    actual_totals = [
        int(value) for value in evidence.get("reported_totals_locator_evidence") or []
        if isinstance(value, (int, float))
    ]
    expected_topology = str(golden.get("disclosure_topology") or "")
    actual_topology = str(candidate.get("disclosure_topology") or evidence.get("disclosure_topology") or "")
    expected_physical_count = len(golden.get("physical_assets") or [])
    actual_physical_count = int(
        (candidate.get("structure_evidence") or {}).get("physical_asset_count")
        or len({
            str(child.get("physical_asset_id") or "")
            for child in candidate.get("child_rows") or []
            if child.get("physical_asset_id")
        })
        or 1
    )
    checks = [
        ("物理页", expected_pages, [actual_page] if actual_page else []),
        ("披露拓扑", expected_topology, actual_topology),
        ("适用分类轴成员", expected_members, actual_members),
        ("物理资产数量", expected_physical_count, actual_physical_count),
        ("来源披露当期总额", expected_totals, actual_totals[:1]),
    ]
    rows = [
        {"核对项": label, "Golden": expected, "机器证据": actual, "结果": "MATCH" if expected == actual else "MISMATCH"}
        for label, expected, actual in checks
    ]
    return {
        "status": "MATCH" if all(row["结果"] == "MATCH" for row in rows) else "MISMATCH",
        "rows": rows,
        "golden_path": golden.get("_path"),
    }


def compare_portfolio_capture_rows(
    company: str,
    report_year: str | int,
    results_by_member: dict[str, dict[str, Any]],
    *,
    root: Path = GOLDEN_ROOT,
) -> dict[str, Any]:
    """Compare certified Capture rows with row-level portfolio Golden.

    This is a post-Capture acceptance check only.  It never mutates a Capture,
    fills a missing value, or promotes Golden data into machine evidence.
    """
    golden = load_portfolio_golden(company, report_year, root=root)
    if golden is None:
        return {"status": "NO_GOLDEN", "rows": []}
    if golden.get("_load_error"):
        return {
            "status": "GOLDEN_UNAVAILABLE",
            "error": golden["_load_error"],
            "rows": [],
        }

    from golden_identity import load_yaml, sidecar_filename, validate_identity_sidecar

    golden_path = Path(str(golden.get("_path") or ""))
    sidecar_path = golden_path.parent / sidecar_filename("investment_portfolio")
    if not sidecar_path.is_file():
        return {
            "status": "GOLDEN_IDENTITY_MISSING",
            "rows": [],
            "golden_path": golden.get("_path"),
            "expected_identity_path": str(sidecar_path),
        }
    sidecar = load_yaml(sidecar_path)
    identity_validation = validate_identity_sidecar(
        sidecar,
        expected_family="investment_portfolio",
        expected_definition_id="INVESTMENT_PORTFOLIO_V2",
    )
    if identity_validation.status != "PASS":
        return {
            "status": "GOLDEN_IDENTITY_INVALID",
            "rows": [],
            "golden_path": golden.get("_path"),
            "identity_issues": list(identity_validation.issues),
        }

    def label(value: Any) -> str:
        compact = re.sub(
            r"\s+",
            "",
            str(value or "").replace("（", "(").replace("）", ")"),
        )
        compact = re.sub(r"\((?:\d+|[一二三四五六七八九十]+)\)$", "", compact)
        compact = re.sub(r"(?:\d+|[一二三四五六七八九十]+)\)$", "", compact)
        aliases = {
            "以公允价值计量且其变动计入当期损益的金融资产":
                "以公允价值计量且变动计入当期损益的金融资产",
        }
        return aliases.get(compact, compact)

    def number(value: Any) -> int | float | None:
        if value in (None, ""):
            return None
        converted = float(value)
        return int(converted) if converted.is_integer() else converted

    identity_rows = list(sidecar.get("rows") or [])
    audit_rows: list[dict[str, Any]] = []
    for asset in golden.get("physical_assets") or []:
        for block in asset.get("blocks") or []:
            member_id = str(block.get("member_id") or "")
            capture = dict(results_by_member.get(member_id) or {})
            actual_rows = list(capture.get("rows") or [])
            if member_id != "portfolio_summary":
                summary_rows = list(
                    dict(results_by_member.get("portfolio_summary") or {}).get("rows")
                    or []
                )
                # The formal Capture stores the one physical portfolio total
                # as its own summary asset.  Golden repeats that same physical
                # total at the start of each classification-axis block.  For
                # parity only, project the shared source row into each axis;
                # do not duplicate it in Capture, Canonical or Merge.
                actual_rows.extend(
                    row for row in summary_rows
                    if str(row.get("row_type") or row.get("row_role") or "").upper()
                    in {"TOTAL", "SUBTOTAL", "CLASSIFICATION_TOTAL"}
                    or label(
                        row.get("row_item_normalized")
                        or row.get("normalized_item")
                        or row.get("row_item_raw")
                        or row.get("raw_item")
                    ) in {"投资资产", "投资资产(合计)", "投资资产（合计）", "投资资产合计"}
                )
            expected_rows = list(block.get("rows") or [])
            if not capture:
                audit_rows.append({
                    "member_id": member_id,
                    "row_order": None,
                    "field": "capture",
                    "golden": "PRESENT",
                    "machine": "MISSING",
                    "result": "MISMATCH",
                })
                continue
            expected_identities = sorted(
                (
                    row for row in identity_rows
                    if row.get("member_table_id") == member_id
                    and row.get("physical_table_id") == asset.get("asset_id")
                ),
                key=lambda row: int(row.get("source_row_order") or 0),
            )
            if len(expected_rows) != len(actual_rows) or len(expected_rows) != len(expected_identities):
                audit_rows.append({
                    "member_id": member_id,
                    "row_order": None,
                    "field": "row_count",
                    "golden": len(expected_rows),
                    "machine": len(actual_rows),
                    "result": "MISMATCH",
                })
            expected_by_key: dict[tuple[str, str, int], tuple[dict[str, Any], dict[str, Any]]] = {}
            for identity_row in expected_identities:
                source_order = int(identity_row.get("source_row_order") or 0)
                expected = next(
                    (row for row in expected_rows if int(row.get("row_order") or 0) == source_order),
                    {},
                )
                key = (
                    label(identity_row.get("semantic_parent_path") or "ROOT"),
                    label(identity_row.get("normalized_label")),
                    int(identity_row.get("occurrence") or 0),
                )
                expected_by_key[key] = (identity_row, expected)

            source_labels = {
                str(row.get("source_row_id") or ""): label(
                    row.get("row_item_normalized") or row.get("normalized_item")
                    or row.get("row_item_raw") or row.get("raw_item")
                )
                for row in actual_rows
                if row.get("source_row_id")
            }
            parent_ids = {
                str(row.get("parent_row_id"))
                for row in actual_rows if row.get("parent_row_id")
            }
            occurrences: dict[tuple[str, str], int] = {}
            actual_by_key: dict[tuple[str, str, int], dict[str, Any]] = {}
            for actual in actual_rows:
                actual_label = label(
                    actual.get("row_item_normalized") or actual.get("normalized_item")
                    or actual.get("row_item_raw") or actual.get("raw_item")
                )
                parent_path = source_labels.get(str(actual.get("parent_row_id") or ""), "ROOT")
                occurrence_key = (parent_path, actual_label)
                occurrences[occurrence_key] = occurrences.get(occurrence_key, 0) + 1
                actual_by_key[(parent_path, actual_label, occurrences[occurrence_key])] = actual

            def actual_cells(actual: dict[str, Any]) -> dict[int, Any]:
                return {
                    int(cell.get("column_ordinal")): cell.get("parsed_number")
                    for cell in actual.get("cells") or []
                    if cell.get("column_ordinal") is not None
                }

            def actual_kind(actual: dict[str, Any]) -> str:
                role = str(actual.get("row_type") or actual.get("row_role") or "").upper()
                return (
                    "GROUP"
                    if str(actual.get("source_row_id") or "") in parent_ids
                    or role == "SECTION_HEADER"
                    else "TOTAL"
                    if role in {"TOTAL", "SUBTOTAL", "CLASSIFICATION_TOTAL"}
                    else "DATA"
                )

            def expected_value_signature(expected: dict[str, Any]) -> tuple[Any, ...]:
                return tuple(number(expected.get(field)) for field in (
                    "current_amount", "current_ratio_percent",
                    "comparative_amount", "comparative_ratio_percent",
                ))

            def actual_value_signature(actual: dict[str, Any]) -> tuple[Any, ...]:
                cells = actual_cells(actual)
                return tuple(number(cells.get(index)) for index in range(4))

            exact_keys = sorted(set(expected_by_key) & set(actual_by_key))
            for identity_key in exact_keys:
                identity_row, expected = expected_by_key[identity_key]
                actual = actual_by_key[identity_key]
                cells = {
                    int(cell.get("column_ordinal")): cell.get("parsed_number")
                    for cell in actual.get("cells") or []
                    if cell.get("column_ordinal") is not None
                }
                observed_kind = actual_kind(actual)
                expected_raw = label(expected.get("raw_label"))
                actual_raw = label(actual.get("row_item_raw") or actual.get("raw_item"))
                audit_rows.append({
                    "member_id": member_id,
                    "golden_row_id": identity_row.get("golden_row_id"),
                    "source_row_id": actual.get("source_row_id"),
                    "identity_key": identity_key,
                    "row_order": identity_row.get("source_row_order"),
                    "field": "raw_label",
                    "golden": expected_raw,
                    "machine": actual_raw,
                    "result": "MATCH",
                    "audit_result": (
                        "MATCH" if expected_raw == actual_raw
                        else "DIFFERENT_NON_BLOCKING"
                    ),
                    "comparison_role": "LINEAGE_AUDIT_ONLY",
                })
                comparisons = {
                    "row_kind": (
                        str(expected.get("row_kind") or ""),
                        observed_kind,
                    ),
                    "current_amount": (
                        number(expected.get("current_amount")),
                        number(cells.get(0)),
                    ),
                    "current_ratio_percent": (
                        number(expected.get("current_ratio_percent")),
                        number(cells.get(1)),
                    ),
                    "comparative_amount": (
                        number(expected.get("comparative_amount")),
                        number(cells.get(2)),
                    ),
                    "comparative_ratio_percent": (
                        number(expected.get("comparative_ratio_percent")),
                        number(cells.get(3)),
                    ),
                }
                for field, (expected_value, actual_value) in comparisons.items():
                    audit_rows.append({
                        "member_id": member_id,
                        "golden_row_id": identity_row.get("golden_row_id"),
                        "source_row_id": actual.get("source_row_id"),
                        "identity_key": identity_key,
                        "row_order": identity_row.get("source_row_order"),
                        "field": field,
                        "golden": expected_value,
                        "machine": actual_value,
                        "result": (
                            "MATCH"
                            if expected_value == actual_value
                            else "MISMATCH"
                        ),
                    })

            unmatched_expected = set(expected_by_key) - set(actual_by_key)
            unmatched_actual = set(actual_by_key) - set(expected_by_key)
            expected_signatures: dict[tuple[Any, ...], list[tuple[str, str, int]]] = {}
            actual_signatures: dict[tuple[Any, ...], list[tuple[str, str, int]]] = {}
            for identity_key in unmatched_expected:
                _, expected = expected_by_key[identity_key]
                signature = (identity_key[1], *expected_value_signature(expected))
                expected_signatures.setdefault(signature, []).append(identity_key)
            for identity_key in unmatched_actual:
                actual = actual_by_key[identity_key]
                signature = (identity_key[1], *actual_value_signature(actual))
                actual_signatures.setdefault(signature, []).append(identity_key)

            diagnostic_pairs: list[tuple[tuple[str, str, int], tuple[str, str, int]]] = []
            for signature in sorted(set(expected_signatures) & set(actual_signatures), key=str):
                expected_keys = expected_signatures[signature]
                actual_keys = actual_signatures[signature]
                if len(expected_keys) == 1 and len(actual_keys) == 1:
                    expected_key, actual_key = expected_keys[0], actual_keys[0]
                    diagnostic_pairs.append((expected_key, actual_key))
                    unmatched_expected.remove(expected_key)
                    unmatched_actual.remove(actual_key)

            for expected_key, actual_key in diagnostic_pairs:
                identity_row, _ = expected_by_key[expected_key]
                actual = actual_by_key[actual_key]
                audit_rows.append({
                    "member_id": member_id,
                    "golden_row_id": identity_row.get("golden_row_id"),
                    "source_row_id": actual.get("source_row_id"),
                    "identity_key": expected_key,
                    "row_order": identity_row.get("source_row_order"),
                    "field": "semantic_identity",
                    "golden": expected_key,
                    "machine": actual_key,
                    "result": "MISMATCH",
                    "reason_code": "SEMANTIC_PARENT_PATH_OR_OCCURRENCE_MISMATCH",
                    "diagnostic_value_fingerprint_match": True,
                })
            for identity_key in sorted(unmatched_expected):
                identity_row, _ = expected_by_key[identity_key]
                audit_rows.append({
                    "member_id": member_id,
                    "golden_row_id": identity_row.get("golden_row_id"),
                    "source_row_id": None,
                    "identity_key": identity_key,
                    "row_order": identity_row.get("source_row_order"),
                    "field": "identity_presence",
                    "golden": identity_key,
                    "machine": "MISSING",
                    "result": "MISMATCH",
                    "reason_code": "GOLDEN_IDENTITY_NOT_IN_CAPTURE",
                })
            for identity_key in sorted(unmatched_actual):
                actual = actual_by_key[identity_key]
                audit_rows.append({
                    "member_id": member_id,
                    "golden_row_id": None,
                    "source_row_id": actual.get("source_row_id"),
                    "identity_key": identity_key,
                    "row_order": None,
                    "field": "identity_presence",
                    "golden": "MISSING",
                    "machine": identity_key,
                    "result": "MISMATCH",
                    "reason_code": "CAPTURE_IDENTITY_NOT_IN_GOLDEN",
                })
    return {
        "status": (
            "MATCH"
            if audit_rows
            and all(row["result"] == "MATCH" for row in audit_rows)
            else "MISMATCH"
        ),
        "rows": audit_rows,
        "golden_path": golden.get("_path"),
        "members_checked": sorted(results_by_member),
        "row_count": sum(
            len((results_by_member.get(member_id) or {}).get("rows") or [])
            for member_id in results_by_member
        ),
    }


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
    expected = next(
        (row for row in golden.get("values") or [] if _member_id(row) == member),
        None,
    )
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
                    lambda row: label in _row_label_variants(row),
                    axis=1,
                )
            ]
            expected_axis = str(expected_item.get("classification_axis") or "").strip()
            if expected_axis and "classification_axis" in candidates.columns:
                candidates = candidates[
                    candidates["classification_axis"].fillna("").astype(str).str.strip()
                    == expected_axis
                ]
            for key, expected_raw in expected_item.items():
                match = re.fullmatch(
                    r"(amount|amortized_cost|fair_value)_(\d{4})(?:_(restated))?",
                    key,
                )
                if not match:
                    continue
                metric, data_year, restated_marker = match.groups()
                period_rows = candidates[
                    candidates.apply(
                        lambda row: str(row.get("data_year") or row.get("year") or "") == data_year
                        and (not restated_marker or str(row.get("restated_flag") or row.get("restated") or "").lower() in {"true", "1"}),
                        axis=1,
                    )
                ]
                if metric != "amount" and "measure" in period_rows.columns:
                    measure_aliases = {
                        "amortized_cost": {"摊余成本", "amortizedcost"},
                        "fair_value": {"公允价值", "fairvalue"},
                    }[metric]
                    period_rows = period_rows[
                        period_rows["measure"].fillna("").apply(
                            lambda value: _normalise(value) in measure_aliases
                        )
                    ]
                raw_values = period_rows["value_raw"].tolist() if "value_raw" in period_rows.columns else []
                observed_values = [_amount(value) for value in raw_values]
                observed_values = [value for value in observed_values if value is not None]
                expected_value = _amount(expected_raw)
                if expected_value is None:
                    explicit_placeholders = [
                        value for value in raw_values
                        if str(value).strip() in {"-", "－", "–", "—", "不适用", "N/A", "n/a"}
                    ]
                    status = "MATCH" if explicit_placeholders else "MISMATCH"
                else:
                    # Repeated labels such as two axis-specific total rows are
                    # disambiguated by classification_axis when certified.  A
                    # legacy Golden without the axis still matches the exact
                    # certified value, while v1.2 identity validation reports
                    # the missing axis separately.
                    status = "MATCH" if expected_value in observed_values else "MISMATCH"
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
    # One transition statement may contain a current IFRS 9 row and a
    # comparative-only IFRS 39 row that intentionally project to the same
    # stable Golden member id.  A dict comprehension silently kept whichever
    # happened to be last, so the UI could compare Golden's current FVTPL
    # amount against a legitimate legacy ``不适用`` row.  Preserve every
    # candidate, then select the current-period source row by its own machine
    # evidence; Golden never supplies that identity decision.
    actual: dict[str, list[dict[str, Any]]] = {}
    for row in child_rows:
        member = _member_id(row)
        if member:
            actual.setdefault(member, []).append(row)

    def current_source_row(member_id: str) -> dict[str, Any] | None:
        candidates = list(actual.get(member_id) or [])
        if not candidates:
            return None

        def rank(row: dict[str, Any]) -> tuple[int, int, int]:
            raw_id = str(
                row.get("member_id") or row.get("canonical_concept_id")
                or row.get("member_table_id") or row.get("member_table") or ""
            )
            return (
                int(str(row.get("member_period_status") or "") == CURRENT_PERIOD_MEMBER_STATUS),
                int(raw_id == member_id),
                int(bool(_current_amounts(row))),
            )

        return max(candidates, key=rank)

    rows = []
    missing_current_members: list[str] = []
    for expected in contract["current_required_members"]:
        member = str(expected.get("member_id") or "")
        lookup_member = _member_id({"member_id": member}) or member
        observed = current_source_row(lookup_member)
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
            "observed_in_current_anchor": bool(actual.get(str(expected.get("member_id") or ""))),
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
