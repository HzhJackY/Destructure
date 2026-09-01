"""Golden v1.2 stable business-identity projection and validation.

The identity sidecar is derived only from independently certified Golden facts.
It never reads Capture output and never contains runtime ``source_row_id``.
"""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
import re
from typing import Any, Iterable


IDENTITY_CONTRACT_VERSION = "GOLDEN_IDENTITY_V1_2"
SIDECAR_FILENAME = "golden_identity_v1_2.yaml"
# A financial statement may show one physical GROUP row (``金融投资``) above
# several Registry member families.  It is a shared structural parent, not a
# cross-table hierarchy edge.  Keep this allow-list explicit so the normal
# same-member constraint remains fail-closed for every other parent relation.
_SHARED_STRUCTURAL_PARENT_MEMBER_IDS = frozenset({"financial_investment_parent"})


def sidecar_filename(family: str) -> str:
    return f"golden_identity_v1_2_{family}.yaml"


def _normalise_label(value: Any) -> str:
    return re.sub(r"\s+", "", str(value or "").replace("（", "(").replace("）", ")"))


def _identity_token(*parts: Any) -> str:
    raw = "|".join(_normalise_label(part) for part in parts)
    return sha256(raw.encode("utf-8")).hexdigest()[:20]


def period_identity(label: Any) -> str:
    text = re.sub(r"\s+", "", str(label or ""))
    full = re.search(r"((?:19|20)\d{2})年(\d{1,2})月(\d{1,2})日", text)
    if full:
        year, month, day = map(int, full.groups())
        return f"DATE:{year:04d}-{month:02d}-{day:02d}"
    year = re.search(r"((?:19|20)\d{2})年", text)
    return f"YEAR:{year.group(1)}" if year else "UNRESOLVED"


def _period_values_from_portfolio(row: dict[str, Any], block: dict[str, Any]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for role, prefix, period_key in (
        ("CURRENT", "current", "current_period"),
        ("COMPARATIVE", "comparative", "comparative_period"),
    ):
        period = dict(block.get(period_key) or {})
        for measure, value_key, unit in (
            ("AMOUNT", f"{prefix}_amount", "RMB_MILLION"),
            ("RATIO", f"{prefix}_ratio_percent", "PERCENT"),
        ):
            result.append(
                {
                    "period_role": role,
                    "period_label": str(period.get("label") or ""),
                    "period_identity": period_identity(period.get("label")),
                    "measure": measure,
                    "unit": unit,
                    "value": row.get(value_key),
                }
            )
    if "change_percent" in row:
        result.append(
            {
                "period_role": "PERIOD_CHANGE",
                "period_label": "期间变动",
                "period_identity": "PERIOD_CHANGE",
                "measure": "CHANGE_PERCENT",
                "unit": "PERCENT",
                "value": row.get("change_percent"),
            }
        )
    return result


def _portfolio_rows(golden: dict[str, Any]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    tables: list[dict[str, Any]] = []
    rows: list[dict[str, Any]] = []
    for asset in golden.get("physical_assets") or []:
        physical_table_id = str(asset.get("asset_id") or "")
        tables.append(
            {
                "physical_table_id": physical_table_id,
                "physical_page_number": asset.get("physical_page_number"),
                "printed_page_number": asset.get("printed_page_number"),
                "title": asset.get("title"),
                "unit": asset.get("unit"),
                "table_classification": "DIRECT_PHYSICAL_TABLE",
            }
        )
        for block in asset.get("blocks") or []:
            member_id = str(block.get("member_id") or "")
            axis = str(block.get("classification_axis") or "")
            occurrences: Counter[tuple[str, str]] = Counter()
            active_parent_id: str | None = None
            active_parent_path = "ROOT"
            row_identity_by_order: dict[int, tuple[str, str]] = {}
            for source_row in block.get("rows") or []:
                normalized = _normalise_label(source_row.get("normalized_label") or source_row.get("raw_label"))
                row_kind = str(source_row.get("row_kind") or "DATA")
                # A new peer group closes the previous group before its own
                # identity is created.  Final totals also belong to the block
                # root; they close a local group but never inherit it.
                has_explicit_parent = "parent_row_order" in source_row
                explicit_parent_order = source_row.get("parent_row_order")
                if has_explicit_parent and explicit_parent_order is not None:
                    parent_record = row_identity_by_order.get(int(explicit_parent_order))
                    if parent_record is None:
                        raise ValueError(
                            f"GOLDEN_PARENT_ROW_ORDER_NOT_FOUND:{physical_table_id}:"
                            f"{member_id}:{source_row.get('row_order')}:{explicit_parent_order}"
                        )
                    parent_id, parent_path = parent_record
                elif has_explicit_parent or row_kind in {"GROUP", "TOTAL"}:
                    parent_id = None
                    parent_path = "ROOT"
                else:
                    parent_id = active_parent_id
                    parent_path = active_parent_path
                occurrence_key = (parent_path, normalized)
                occurrences[occurrence_key] += 1
                occurrence = occurrences[occurrence_key]
                row_id = "GROW_" + _identity_token(
                    golden.get("golden_id"), physical_table_id, member_id, axis,
                    parent_path, normalized, occurrence,
                )
                rows.append(
                    {
                        "golden_row_id": row_id,
                        "physical_table_id": physical_table_id,
                        "member_table_id": member_id,
                        "classification_axis": axis,
                        "raw_label": source_row.get("raw_label"),
                        "normalized_label": source_row.get("normalized_label"),
                        "parent_golden_row_id": parent_id,
                        "semantic_parent_path": parent_path,
                        "occurrence": occurrence,
                        "row_kind": row_kind,
                        "source_row_order": source_row.get("row_order"),
                        "period_values": _period_values_from_portfolio(source_row, block),
                    }
                )
                row_identity_by_order[int(source_row.get("row_order") or 0)] = (
                    row_id, normalized,
                )
                if row_kind == "GROUP":
                    active_parent_id = row_id
                    active_parent_path = normalized
                elif row_kind == "TOTAL" or (
                    has_explicit_parent and explicit_parent_order is None
                ):
                    active_parent_id = None
                    active_parent_path = "ROOT"
    return tables, rows


def _financial_child_table_id(
    filing_id: str, member_id: str, child: dict[str, Any],
) -> str:
    classification = str(child.get("classification") or "PRIMARY_TABLE").upper()
    suffix = (
        "HISTORICAL_COMPARATIVE"
        if classification == "HISTORICAL_COMPARATIVE_TABLE"
        else "PRIMARY"
    )
    return f"{filing_id}::{member_id}::{suffix}"


def _financial_rows(golden: dict[str, Any], filing: dict[str, Any]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    tables: list[dict[str, Any]] = []
    rows: list[dict[str, Any]] = []
    filing_id = str(filing.get("filing_id") or golden.get("fixture_id") or "")
    for member in golden.get("values") or []:
        member_id = str(member.get("member_id") or "")
        main_table_id = f"{filing_id}::MAIN_STATEMENT"
        main_label = member.get("raw_label")
        main_row_id = "GROW_" + _identity_token(filing_id, main_table_id, member_id, main_label, 1)
        report_year = str(filing.get("report_year") or "")
        member_status = str(member.get("status") or "")
        is_restated_comparative = member_status == "RESTATED_COMPARATIVE_PERIOD"
        if is_restated_comparative:
            comparative_year = str(
                member.get("comparative_year")
                or (int(report_year) - 1 if report_year.isdigit() else "")
            )
            amount_label = f"{comparative_year}年重述"
            amount_identity = f"YEAR:{comparative_year}"
            amount_value = member.get(
                "comparative_amount_raw", member.get("current_amount_raw")
            )
            amount_role = "COMPARATIVE"
        else:
            amount_label = report_year + "年"
            amount_identity = period_identity(amount_label)
            amount_value = member.get("current_amount_raw")
            amount_role = "CURRENT"
        rows.append(
            {
                "golden_row_id": main_row_id,
                "physical_table_id": main_table_id,
                "member_table_id": member_id,
                "classification_axis": "FINANCIAL_INVESTMENT_MEMBER_SET",
                "raw_label": main_label,
                "normalized_label": main_label,
                "parent_golden_row_id": None,
                "semantic_parent_path": "ROOT",
                "occurrence": 1,
                "row_kind": (
                    "HISTORICAL_MEMBER" if is_restated_comparative else "MEMBER"
                ),
                "source_row_order": None,
                "period_values": [{
                    "period_role": amount_role,
                    "period_label": amount_label,
                    "period_identity": amount_identity,
                    "measure": "AMOUNT",
                    "unit": "SOURCE_DECLARED",
                    "value": amount_value,
                }],
            }
        )
        child = dict(member.get("child_table") or {})
        if not child:
            continue
        physical_table_id = _financial_child_table_id(
            filing_id, member_id, child,
        )
        tables.append(
            {
                "physical_table_id": physical_table_id,
                "physical_page_number": child.get("pdf_page_number"),
                "printed_page_number": child.get("printed_page_label"),
                "title": child.get("note_title"),
                "unit": child.get("unit"),
                "table_classification": child.get("classification") or "PRIMARY_TABLE",
            }
        )
        occurrences: Counter[tuple[str, str, str]] = Counter()
        active_parent_by_axis: dict[str, tuple[str, str]] = {}
        row_identity_by_order: dict[int, tuple[str, str, str, str]] = {}
        for row_order, item in enumerate(child.get("items") or [], 1):
            normalized = _normalise_label(item.get("normalized_label") or item.get("raw_label"))
            axis = str(
                item.get("classification_axis")
                or child.get("classification_axis")
                or "ASSET_TYPE"
            )
            row_kind = str(item.get("row_kind") or "DATA")
            has_explicit_parent = "parent_row_order" in item
            explicit_parent_order = item.get("parent_row_order")
            if has_explicit_parent and explicit_parent_order is not None:
                parent_record = row_identity_by_order.get(int(explicit_parent_order))
                if parent_record is None:
                    raise ValueError(
                        f"GOLDEN_PARENT_ROW_ORDER_NOT_FOUND:{physical_table_id}:"
                        f"{member_id}:{row_order}:{explicit_parent_order}"
                    )
                parent_id, parent_path, parent_axis, parent_kind = parent_record
                if parent_axis != axis:
                    raise ValueError(
                        f"GOLDEN_PARENT_AXIS_MISMATCH:{physical_table_id}:"
                        f"{member_id}:{row_order}:{explicit_parent_order}"
                    )
                if parent_kind != "GROUP":
                    raise ValueError(
                        f"GOLDEN_PARENT_KIND_INVALID:{physical_table_id}:"
                        f"{member_id}:{row_order}:{explicit_parent_order}"
                    )
            elif has_explicit_parent or row_kind in {"GROUP", "TOTAL"}:
                parent_id = None
                parent_path = "ROOT"
            else:
                parent_id, parent_path = active_parent_by_axis.get(axis, (None, "ROOT"))
            occurrence_key = (axis, parent_path, normalized)
            occurrences[occurrence_key] += 1
            occurrence = occurrences[occurrence_key]
            row_id = "GROW_" + _identity_token(
                filing_id, physical_table_id, member_id, axis,
                parent_path, normalized, occurrence,
            )
            period_values: list[dict[str, Any]] = []
            for key, value in item.items():
                match = re.fullmatch(
                    r"amount_((?:19|20)\d{2})(_restated)?", str(key)
                )
                if match:
                    year = match.group(1)
                    is_restated = bool(match.group(2))
                    period_values.append(
                        {
                            "period_role": "CURRENT" if year == str(filing.get("report_year")) else "COMPARATIVE",
                            "period_label": f"{year}年重述" if is_restated else f"{year}年",
                            "period_identity": f"YEAR:{year}",
                            "measure": "AMOUNT",
                            "unit": child.get("unit") or "SOURCE_DECLARED",
                            "value": value,
                        }
                    )
            rows.append(
                {
                    "golden_row_id": row_id,
                    "physical_table_id": physical_table_id,
                    "member_table_id": member_id,
                    "classification_axis": axis,
                    "raw_label": item.get("raw_label"),
                    "normalized_label": item.get("normalized_label") or item.get("raw_label"),
                    "parent_golden_row_id": parent_id,
                    "semantic_parent_path": parent_path,
                    "occurrence": occurrence,
                    "row_kind": row_kind,
                    "source_row_order": row_order,
                    "period_values": period_values,
                }
            )
            row_path = normalized if parent_path == "ROOT" else f"{parent_path}/{normalized}"
            row_identity_by_order[row_order] = (row_id, row_path, axis, row_kind)
            if row_kind == "GROUP":
                active_parent_by_axis[axis] = (row_id, row_path)
            elif row_kind == "TOTAL" or (
                has_explicit_parent and explicit_parent_order is None
            ):
                active_parent_by_axis.pop(axis, None)
    return tables, rows


def _financial_supplementary_rows(
    supplementary: dict[str, Any], filing: dict[str, Any],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    tables: list[dict[str, Any]] = []
    rows: list[dict[str, Any]] = []
    filing_id = str(filing.get("filing_id") or "")
    for schedule in supplementary.get("supplementary_schedules") or []:
        schedule_id = str(schedule.get("schedule_id") or "")
        physical_table_id = f"{filing_id}::{schedule_id}"
        tables.append({
            "physical_table_id": physical_table_id,
            "physical_page_number": schedule.get("pdf_page_number"),
            "printed_page_number": schedule.get("printed_page_label"),
            "title": schedule.get("schedule_title"),
            "unit": schedule.get("unit"),
            "table_classification": schedule.get("classification") or "SUPPLEMENTARY_TABLE",
        })
        item_groups = [
            (key, value)
            for key, value in schedule.items()
            if (key == "items" or re.fullmatch(r"items_\d{4}", str(key)))
            and isinstance(value, list)
        ]
        for group_key, group_items in item_groups:
            logical_block_id = (
                schedule_id if group_key == "items" else f"{schedule_id}::{group_key}"
            )
            occurrences: Counter[str] = Counter()
            for row_order, item in enumerate(group_items, 1):
                normalized = _normalise_label(
                    item.get("normalized_label") or item.get("raw_label")
                )
                occurrences[normalized] += 1
                occurrence = occurrences[normalized]
                row_id = "GROW_" + _identity_token(
                    filing_id, physical_table_id, logical_block_id, normalized, occurrence,
                )
                label_text = str(item.get("raw_label") or "")
                resolved_period = period_identity(label_text)
                if resolved_period == "UNRESOLVED":
                    fallback_year = re.search(
                        r"(?:19|20)\d{2}", f"{group_key}|{schedule_id}"
                    )
                    if fallback_year:
                        resolved_period = f"YEAR:{fallback_year.group(0)}"
                    elif filing.get("report_year"):
                        resolved_period = f"YEAR:{filing['report_year']}"
                period_values = [
                    {
                        "period_role": "SCHEDULE",
                        "period_label": label_text,
                        "period_identity": resolved_period,
                        "measure": str(key).upper(),
                        "unit": schedule.get("unit") or "SOURCE_DECLARED",
                        "value": value,
                    }
                    for key, value in item.items()
                    if key not in {"raw_label", "normalized_label", "row_kind"}
                ]
                rows.append({
                    "golden_row_id": row_id,
                    "physical_table_id": physical_table_id,
                    "member_table_id": logical_block_id,
                    "classification_axis": "SUPPLEMENTARY_SCHEDULE",
                    "raw_label": item.get("raw_label"),
                    "normalized_label": item.get("normalized_label") or item.get("raw_label"),
                    "parent_golden_row_id": None,
                    "semantic_parent_path": "ROOT",
                    "occurrence": occurrence,
                    "row_kind": item.get("row_kind") or "DATA",
                    "source_row_order": row_order,
                    "period_values": period_values,
                })
    return tables, rows


def build_identity_sidecar(
    *, family: str, golden: dict[str, Any], filing: dict[str, Any] | None = None,
    supplementary: dict[str, Any] | None = None,
) -> dict[str, Any]:
    filing = dict(filing or {})
    if family == "investment_portfolio":
        tables, rows = _portfolio_rows(golden)
        source = dict(golden.get("source") or {})
        filing_identity = {
            "company_id": golden.get("company_id"),
            "legal_entity_name": golden.get("legal_entity_name"),
            "report_year": golden.get("report_year"),
            "source_scope": golden.get("source_scope"),
            "canonical_pdf_filename": source.get("canonical_pdf_filename"),
            "pdf_sha256": source.get("pdf_sha256"),
            "page_count": source.get("page_count"),
            "source_type": source.get("source_type"),
        }
        definition_id = "INVESTMENT_PORTFOLIO_V2"
        source_golden_id = golden.get("golden_id")
    elif family == "financial_investment":
        tables, rows = _financial_rows(golden, filing)
        supplementary_tables, supplementary_rows = _financial_supplementary_rows(
            dict(supplementary or {}), filing,
        )
        tables.extend(supplementary_tables)
        rows.extend(supplementary_rows)
        filing_identity = {
            "company_id": filing.get("company_id"),
            "legal_entity_name": filing.get("company_legal_name"),
            "report_year": filing.get("report_year"),
            "source_scope": "CONSOLIDATED",
            "canonical_pdf_filename": filing.get("canonical_pdf_filename"),
            "pdf_sha256": filing.get("pdf_sha256"),
            "page_count": filing.get("page_count"),
            "source_type": filing.get("report_type"),
        }
        definition_id = "FINANCIAL_INVESTMENT_V1"
        source_golden_id = golden.get("fixture_id")
    else:
        raise ValueError(f"UNSUPPORTED_REGISTRY_FAMILY:{family}")
    return {
        "identity_contract_version": IDENTITY_CONTRACT_VERSION,
        "definition_id": definition_id,
        "family": family,
        "source_golden_id": source_golden_id,
        "filing_identity": filing_identity,
        "physical_tables": tables,
        "rows": rows,
        "identity_provenance": "DERIVED_FROM_CERTIFIED_GOLDEN_FACTS_NOT_RUNTIME_CAPTURE",
    }


@dataclass(frozen=True)
class IdentityValidation:
    status: str
    issues: tuple[str, ...]
    row_count: int
    table_count: int


def validate_identity_sidecar(
    sidecar: dict[str, Any], *, strict: bool = True,
    expected_family: str | None = None,
    expected_definition_id: str | None = None,
) -> IdentityValidation:
    issues: list[str] = []
    if sidecar.get("identity_contract_version") != IDENTITY_CONTRACT_VERSION:
        issues.append("IDENTITY_CONTRACT_VERSION_MISSING_OR_UNSUPPORTED")
    if expected_family and sidecar.get("family") != expected_family:
        issues.append("CROSS_REGISTRY_GOLDEN_IDENTITY")
    if expected_definition_id and sidecar.get("definition_id") != expected_definition_id:
        issues.append("RESEARCH_DEFINITION_IDENTITY_MISMATCH")
    filing = dict(sidecar.get("filing_identity") or {})
    for field in (
        "company_id", "legal_entity_name", "report_year", "source_scope",
        "canonical_pdf_filename", "pdf_sha256", "page_count", "source_type",
    ):
        if filing.get(field) in (None, ""):
            issues.append(f"FILING_IDENTITY_MISSING:{field}")
    if filing.get("pdf_sha256") and not re.fullmatch(r"[0-9a-fA-F]{64}", str(filing["pdf_sha256"])):
        issues.append("FILING_IDENTITY_INVALID_SHA256")
    tables = list(sidecar.get("physical_tables") or [])
    table_ids = [str(item.get("physical_table_id") or "") for item in tables]
    if len(table_ids) != len(set(table_ids)):
        issues.append("DUPLICATE_PHYSICAL_TABLE_ID")
    table_id_set = set(table_ids)
    rows = list(sidecar.get("rows") or [])
    row_ids = [str(item.get("golden_row_id") or "") for item in rows]
    if len(row_ids) != len(set(row_ids)):
        issues.append("DUPLICATE_GOLDEN_ROW_ID")
    row_id_set = set(row_ids)
    rows_by_id = {
        str(item.get("golden_row_id") or ""): item
        for item in rows if item.get("golden_row_id")
    }
    for row in rows:
        row_id = str(row.get("golden_row_id") or "")
        if not row_id:
            issues.append("GOLDEN_ROW_ID_MISSING")
        if (
            str(row.get("physical_table_id") or "") not in table_id_set
            and row.get("row_kind") not in {"MEMBER", "HISTORICAL_MEMBER"}
        ):
            issues.append(f"ROW_PHYSICAL_TABLE_MISSING:{row_id}")
        parent = row.get("parent_golden_row_id")
        if parent and parent not in row_id_set:
            issues.append(f"DANGLING_GOLDEN_PARENT:{row_id}")
        if parent and parent == row_id:
            issues.append(f"SELF_GOLDEN_PARENT:{row_id}")
        parent_row = rows_by_id.get(str(parent or "")) or {}
        if parent_row:
            row_scope = (
                row.get("physical_table_id"), row.get("member_table_id"),
                row.get("classification_axis"),
            )
            parent_scope = (
                parent_row.get("physical_table_id"), parent_row.get("member_table_id"),
                parent_row.get("classification_axis"),
            )
            same_physical_and_axis = (
                row_scope[0] == parent_scope[0]
                and row_scope[2] == parent_scope[2]
            )
            shared_structural_parent = (
                str(parent_row.get("member_table_id") or "")
                in _SHARED_STRUCTURAL_PARENT_MEMBER_IDS
                and str(parent_row.get("row_kind") or "") == "GROUP"
            )
            if not same_physical_and_axis or (
                row_scope[1] != parent_scope[1] and not shared_structural_parent
            ):
                issues.append(f"GOLDEN_PARENT_SCOPE_MISMATCH:{row_id}")
            if str(parent_row.get("row_kind") or "") != "GROUP":
                issues.append(f"GOLDEN_PARENT_KIND_INVALID:{row_id}")
        parent_label = _normalise_label(parent_row.get("normalized_label")) if parent_row else ""
        parent_prefix = _normalise_label(parent_row.get("semantic_parent_path")) if parent_row else ""
        expected_parent_path = (
            f"{parent_prefix}/{parent_label}"
            if parent_prefix and parent_prefix != "ROOT" and parent_label
            else parent_label or "ROOT"
        )
        declared_parent_path = _normalise_label(row.get("semantic_parent_path") or "ROOT")
        if declared_parent_path != expected_parent_path:
            issues.append(
                f"GOLDEN_PARENT_PATH_MISMATCH:{row_id}:"
                f"{declared_parent_path}!={expected_parent_path}"
            )
        if not isinstance(row.get("occurrence"), int) or int(row.get("occurrence") or 0) < 1:
            issues.append(f"ROW_OCCURRENCE_INVALID:{row_id}")
        for value in row.get("period_values") or []:
            if value.get("period_identity") in (None, "", "UNRESOLVED"):
                issues.append(f"PERIOD_IDENTITY_UNRESOLVED:{row_id}")
            if value.get("measure") in (None, "") or value.get("unit") in (None, ""):
                issues.append(f"PERIOD_MEASURE_OR_UNIT_MISSING:{row_id}")
    # Detect parent cycles without inferring or repairing a hierarchy.
    parents = {str(row.get("golden_row_id")): row.get("parent_golden_row_id") for row in rows}
    for row_id in row_id_set:
        seen: set[str] = set()
        current: str | None = row_id
        while current:
            if current in seen:
                issues.append(f"GOLDEN_PARENT_CYCLE:{row_id}")
                break
            seen.add(current)
            current = parents.get(current)
    status = "PASS" if not issues else ("FAIL" if strict else "REVIEW_REQUIRED")
    return IdentityValidation(status, tuple(sorted(set(issues))), len(rows), len(tables))


def validate_identity_source_consistency(
    sidecar: dict[str, Any], source_golden: dict[str, Any], *,
    filing: dict[str, Any] | None = None, strict: bool = True,
    expected_family: str | None = None,
    expected_definition_id: str | None = None,
) -> IdentityValidation:
    """Fail closed when independently governed Golden files contradict each other.

    ``validate_identity_sidecar`` proves that one sidecar is internally coherent.
    This validator additionally proves that its filing and physical-table
    identities still point to the source Golden facts in the same filing
    directory.  It never repairs either source and never reads runtime Capture.
    """
    base = validate_identity_sidecar(
        sidecar, strict=strict, expected_family=expected_family,
        expected_definition_id=expected_definition_id,
    )
    issues = set(base.issues)
    family = str(sidecar.get("family") or "")
    expected_source_id = source_golden.get("golden_id") or source_golden.get("fixture_id")
    if sidecar.get("source_golden_id") != expected_source_id:
        issues.add("SOURCE_GOLDEN_IDENTITY_MISMATCH")

    tables = list(sidecar.get("physical_tables") or [])
    tables_by_id = {
        str(table.get("physical_table_id") or ""): table
        for table in tables
        if table.get("physical_table_id")
    }
    sidecar_rows_by_source = {
        (
            str(row.get("physical_table_id") or ""),
            str(row.get("member_table_id") or ""),
            int(row.get("source_row_order") or 0),
        ): row
        for row in sidecar.get("rows") or []
        if row.get("source_row_order") is not None
    }

    if family == "investment_portfolio":
        for asset in source_golden.get("physical_assets") or []:
            physical_table_id = str(asset.get("asset_id") or "")
            table = tables_by_id.get(physical_table_id)
            if not table:
                issues.add(f"SOURCE_PHYSICAL_TABLE_MISSING:{physical_table_id}")
                continue
            expected_page = asset.get("physical_page_number")
            if table.get("physical_page_number") != expected_page:
                issues.add(
                    f"PHYSICAL_TABLE_PAGE_SOURCE_MISMATCH:{physical_table_id}:"
                    f"{table.get('physical_page_number')}!={expected_page}"
                )
            for block in asset.get("blocks") or []:
                member_id = str(block.get("member_id") or "")
                for source_row in block.get("rows") or []:
                    source_order = int(source_row.get("row_order") or 0)
                    sidecar_row = sidecar_rows_by_source.get(
                        (physical_table_id, member_id, source_order)
                    )
                    if not sidecar_row:
                        issues.add(
                            f"SOURCE_GOLDEN_ROW_MISSING:{physical_table_id}:"
                            f"{member_id}:{source_order}"
                        )
                        continue
                    source_kind = str(source_row.get("row_kind") or "DATA")
                    if str(sidecar_row.get("row_kind") or "") != source_kind:
                        issues.add(
                            f"SOURCE_GOLDEN_ROW_KIND_MISMATCH:"
                            f"{sidecar_row.get('golden_row_id')}"
                        )
                    if "parent_row_order" in source_row:
                        parent_order = source_row.get("parent_row_order")
                        expected_parent_id = None
                        if parent_order is not None:
                            parent_sidecar = sidecar_rows_by_source.get(
                                (physical_table_id, member_id, int(parent_order))
                            )
                            if not parent_sidecar:
                                issues.add(
                                    f"SOURCE_GOLDEN_PARENT_ROW_MISSING:"
                                    f"{physical_table_id}:{member_id}:{parent_order}"
                                )
                            else:
                                expected_parent_id = parent_sidecar.get("golden_row_id")
                        if sidecar_row.get("parent_golden_row_id") != expected_parent_id:
                            issues.add(
                                f"SOURCE_GOLDEN_PARENT_MISMATCH:"
                                f"{sidecar_row.get('golden_row_id')}"
                            )
    elif family == "financial_investment":
        filing_payload = dict(filing or {})
        filing_id = str(filing_payload.get("filing_id") or source_golden.get("fixture_id") or "")
        expected_primary_tables, expected_primary_rows = _financial_rows(
            source_golden, filing_payload,
        )
        expected_member_rows = [
            row for row in expected_primary_rows
            if row.get("row_kind") in {"MEMBER", "HISTORICAL_MEMBER"}
        ]
        actual_member_rows = [
            row for row in sidecar.get("rows") or []
            if row.get("row_kind") in {"MEMBER", "HISTORICAL_MEMBER"}
        ]
        if Counter(str(row.get("member_table_id") or "") for row in actual_member_rows) != Counter(
            str(row.get("member_table_id") or "") for row in expected_member_rows
        ):
            issues.add("SOURCE_GOLDEN_MEMBER_SET_MISMATCH")

        expected_members_by_id = {
            str(row.get("member_table_id") or ""): row for row in expected_member_rows
        }
        actual_members_by_id = {
            str(row.get("member_table_id") or ""): row for row in actual_member_rows
        }
        for member_id in sorted(set(expected_members_by_id) & set(actual_members_by_id)):
            expected_row = expected_members_by_id[member_id]
            actual_row = actual_members_by_id[member_id]
            for field in (
                "physical_table_id", "raw_label", "normalized_label",
                "classification_axis", "period_values",
            ):
                if actual_row.get(field) != expected_row.get(field):
                    issues.add(f"SOURCE_GOLDEN_MEMBER_ROW_MISMATCH:{member_id}:{field}")

        expected_primary_table_ids = {
            str(table.get("physical_table_id") or "")
            for table in expected_primary_tables
        }
        source_table_classes = {
            "PRIMARY_TABLE", "HISTORICAL_COMPARATIVE_TABLE",
        }
        actual_primary_table_ids = {
            str(table.get("physical_table_id") or "")
            for table in tables
            if str(table.get("table_classification") or "").upper()
            in source_table_classes
        }
        if actual_primary_table_ids != expected_primary_table_ids:
            issues.add("SOURCE_PRIMARY_TABLE_SET_MISMATCH")

        expected_primary_rows_by_source = {
            (
                str(row.get("physical_table_id") or ""),
                str(row.get("member_table_id") or ""),
                int(row.get("source_row_order") or 0),
            ): row
            for row in expected_primary_rows
            if row.get("source_row_order") is not None
        }
        actual_primary_rows_by_source = {
            (
                str(row.get("physical_table_id") or ""),
                str(row.get("member_table_id") or ""),
                int(row.get("source_row_order") or 0),
            ): row
            for row in sidecar.get("rows") or []
            if row.get("source_row_order") is not None
            and str(row.get("physical_table_id") or "")
            in actual_primary_table_ids
        }
        if set(actual_primary_rows_by_source) != set(expected_primary_rows_by_source):
            issues.add("SOURCE_PRIMARY_ROW_SET_MISMATCH")
        for row_key in sorted(
            set(expected_primary_rows_by_source) & set(actual_primary_rows_by_source)
        ):
            expected_row = expected_primary_rows_by_source[row_key]
            actual_row = actual_primary_rows_by_source[row_key]
            for field in (
                "raw_label", "normalized_label", "row_kind", "period_values",
            ):
                if actual_row.get(field) != expected_row.get(field):
                    issues.add(
                        f"SOURCE_PRIMARY_ROW_MISMATCH:{row_key[0]}:"
                        f"{row_key[1]}:{row_key[2]}:{field}"
                    )

        for member in source_golden.get("values") or []:
            child = dict(member.get("child_table") or {})
            if not child:
                continue
            member_id = str(member.get("member_id") or "")
            physical_table_id = _financial_child_table_id(
                filing_id, member_id, child,
            )
            table = tables_by_id.get(physical_table_id)
            if not table:
                issues.add(f"SOURCE_PHYSICAL_TABLE_MISSING:{physical_table_id}")
                continue
            expected_page = child.get("pdf_page_number")
            if table.get("physical_page_number") != expected_page:
                issues.add(
                    f"PHYSICAL_TABLE_PAGE_SOURCE_MISMATCH:{physical_table_id}:"
                    f"{table.get('physical_page_number')}!={expected_page}"
                )

    filing_source = dict(filing or {})
    if family == "investment_portfolio":
        source = dict(source_golden.get("source") or {})
        filing_source = {
            "company_id": source_golden.get("company_id"),
            "legal_entity_name": source_golden.get("legal_entity_name"),
            "report_year": source_golden.get("report_year"),
            "source_scope": source_golden.get("source_scope"),
            "canonical_pdf_filename": source.get("canonical_pdf_filename"),
            "pdf_sha256": source.get("pdf_sha256"),
            "page_count": source.get("page_count"),
            "source_type": source.get("source_type"),
        }
    elif family == "financial_investment" and filing_source:
        filing_source = {
            "company_id": filing_source.get("company_id"),
            "legal_entity_name": filing_source.get("company_legal_name"),
            "report_year": filing_source.get("report_year"),
            "source_scope": "CONSOLIDATED",
            "canonical_pdf_filename": filing_source.get("canonical_pdf_filename"),
            "pdf_sha256": filing_source.get("pdf_sha256"),
            "page_count": filing_source.get("page_count"),
            "source_type": filing_source.get("report_type"),
        }
    if filing_source:
        sidecar_filing = dict(sidecar.get("filing_identity") or {})
        for field, expected in filing_source.items():
            if sidecar_filing.get(field) != expected:
                issues.add(f"FILING_IDENTITY_SOURCE_MISMATCH:{field}")

    status = "PASS" if not issues else ("FAIL" if strict else "REVIEW_REQUIRED")
    return IdentityValidation(
        status, tuple(sorted(issues)), base.row_count, base.table_count,
    )


def load_yaml(path: Path) -> dict[str, Any]:
    import yaml

    return dict(yaml.safe_load(path.read_text(encoding="utf-8")) or {})


def dump_yaml(path: Path, payload: dict[str, Any]) -> None:
    import yaml

    path.write_text(
        yaml.safe_dump(payload, allow_unicode=True, sort_keys=False, width=120),
        encoding="utf-8",
    )
