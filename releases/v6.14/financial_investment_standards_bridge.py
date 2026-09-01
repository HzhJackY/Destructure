"""Financial-investment presentation identity and standards bridge projection.

This module is a pure projection owned by the formal Merge service.  It never
parses PDFs, changes source observations, or creates a second Merge pipeline.
"""
from __future__ import annotations

import json
from typing import Any

import pandas as pd

from research_definition_registry import (
    BUILTIN_MEMBERS,
    FINANCIAL_INVESTMENT_MEMBER_CONTRACT_VERSION,
)


BRIDGE_SCHEMA_VERSION = "FINANCIAL_INVESTMENT_STANDARDS_BRIDGE_V1"
BRIDGE_PROJECTION_COLUMNS = (
    "view_contract", "analysis_bridge_group", "bridge_rule_id",
    "bridge_source_side", "bridge_comparability_status",
    "bridge_projection_status", "source_final_value", "final_value",
    "bridge_semantic_key",
)
BRIDGE_AUDIT_COLUMNS = (
    "audit_status", "severity", "presentation_member_id",
    "presentation_regime", "analysis_bridge_group", "bridge_rule_id",
    "company", "report_year", "period_identity", "source_row_id",
    "source_member_ids", "bridge_semantic_key", "detail",
)
BRIDGE_WIDE_IDENTITY_COLUMNS = (
    "analysis_bridge_group", "bridge_comparability_status",
    "canonical_item", "semantic_parent_path",
)
_FINANCIAL_FAMILY_KEYS = {
    "financial_investment", "financial_investment_v1", "金融投资",
}
_MEMBER_SPECS = {
    str(item["member_id"]): dict(item)
    for item in BUILTIN_MEMBERS["financial_investment"]
    if item.get("member_role") != "STATEMENT_ANCHOR"
}


def _text(value: Any) -> str:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return ""
    text = str(value).strip()
    return "" if text.lower() in {"nan", "none", "<na>"} else text


def _is_financial_family(value: Any) -> bool:
    text = _text(value).lower()
    return text in _FINANCIAL_FAMILY_KEYS or "financial_investment" in text


def _memberships(value: Any) -> list[dict[str, Any]]:
    if isinstance(value, list):
        return [dict(item) for item in value if isinstance(item, dict)]
    if isinstance(value, tuple):
        return [dict(item) for item in value if isinstance(item, dict)]
    text = _text(value)
    if not text:
        return []
    try:
        parsed = json.loads(text)
    except (TypeError, ValueError, json.JSONDecodeError):
        return []
    return [dict(item) for item in parsed if isinstance(item, dict)] if isinstance(parsed, list) else []


def annotate_financial_investment_identity(frame: pd.DataFrame) -> pd.DataFrame:
    """Add V6 presentation/bridge identity without changing source values."""
    out = frame.copy()
    defaults = {
        "presentation_member_id": "",
        "presentation_regime": "",
        "canonical_analysis_bucket": "",
        "comparability_status": "",
        "analysis_bridge_groups": "[]",
        "member_contract_version": "",
    }
    for column, default in defaults.items():
        if column not in out.columns:
            out[column] = default
    if out.empty or "table_family" not in out.columns or "member_table" not in out.columns:
        return out

    for index, row in out.iterrows():
        if not _is_financial_family(row.get("table_family")):
            continue
        member_id = _text(row.get("presentation_member_id")) or _text(row.get("member_table"))
        spec = _MEMBER_SPECS.get(member_id) or {}
        out.at[index, "presentation_member_id"] = member_id
        out.at[index, "presentation_regime"] = (
            _text(row.get("presentation_regime"))
            or _text(spec.get("presentation_regime"))
            or "UNKNOWN"
        )
        out.at[index, "canonical_analysis_bucket"] = (
            _text(row.get("canonical_analysis_bucket"))
            or _text(spec.get("canonical_analysis_bucket"))
            or member_id
        )
        out.at[index, "comparability_status"] = (
            _text(row.get("comparability_status"))
            or _text(spec.get("comparability_status"))
            or "UNRESOLVED"
        )
        memberships = _memberships(row.get("analysis_bridge_groups")) or [
            dict(item) for item in spec.get("analysis_bridge_groups") or []
        ]
        out.at[index, "analysis_bridge_groups"] = json.dumps(
            memberships, ensure_ascii=False, sort_keys=True,
        )
        out.at[index, "member_contract_version"] = (
            _text(row.get("member_contract_version"))
            or FINANCIAL_INVESTMENT_MEMBER_CONTRACT_VERSION
        )
    return out


def _bridge_identity(row: Any) -> str:
    axis = _text(row.get("classification_axis")) or "UNRESOLVED"
    if axis == "UNRESOLVED":
        block_id = _text(row.get("table_block_id"))
        axis = f"UNRESOLVED::{block_id or 'NO_BLOCK'}"
    parts = {
        "COMPANY": _text(row.get("company")),
        "GROUP": _text(row.get("analysis_bridge_group")),
        "AXIS": axis,
        "ITEM": _text(row.get("canonical_item") or row.get("normalized_item") or row.get("raw_item")),
        "PARENT": _text(row.get("semantic_parent_path") or row.get("row_path")) or "ROOT",
        "OCCURRENCE": _text(row.get("semantic_occurrence")) or "1",
        "REPORT": _text(row.get("report_year") or row.get("document_year")),
        "PERIOD": _text(row.get("period_identity") or row.get("period_label")),
        "SCOPE": _text(row.get("statement_scope") or row.get("scope")),
        "MEASURE": _text(row.get("measure")),
        "UNIT": _text(row.get("unit")),
        "RESTATED": _text(row.get("restated_flag") or row.get("restated")),
    }
    return "||".join(f"{key}::{value or 'UNRESOLVED'}" for key, value in parts.items())


def project_financial_investment_views(
    resolved_long: pd.DataFrame,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Return original, bridge-long, bridge-wide and bridge-audit projections."""
    annotated = annotate_financial_investment_identity(resolved_long)
    if annotated.empty or "table_family" not in annotated.columns:
        return pd.DataFrame(), pd.DataFrame(), pd.DataFrame(), pd.DataFrame()
    original = annotated[
        annotated["table_family"].map(_is_financial_family)
    ].copy().reset_index(drop=True)
    if original.empty:
        return original, pd.DataFrame(), pd.DataFrame(), pd.DataFrame()
    original["view_contract"] = "SOURCE_PRESENTATION_EXACT_V1"
    original["source_value"] = original.get("final_value", original.get("value"))

    bridge_rows: list[dict[str, Any]] = []
    audit_rows: list[dict[str, Any]] = []
    for _, source in original.iterrows():
        member_id = _text(source.get("presentation_member_id"))
        memberships = _memberships(source.get("analysis_bridge_groups"))
        source_value = source.get("source_value")
        if not memberships:
            audit_rows.append({
                "audit_status": "NO_STANDARDS_BRIDGE",
                "severity": "INFO",
                "presentation_member_id": member_id,
                "presentation_regime": _text(source.get("presentation_regime")),
                "company": _text(source.get("company")),
                "report_year": _text(source.get("report_year")),
                "period_identity": _text(source.get("period_identity")),
                "source_row_id": _text(source.get("source_row_id") or source.get("source_row_ids")),
                "detail": "该来源成员不参与新旧准则桥接，仍完整保留在原始口径视图。",
            })
            continue
        for membership in memberships:
            row = source.to_dict()
            rule_id = _text(membership.get("bridge_rule_id"))
            comparability = _text(membership.get("comparability_status")) or "UNRESOLVED"
            certified_disaggregation = (
                _text(source.get("bridge_certification_status")) == "CERTIFIED_DISAGGREGATION"
                and _text(source.get("certified_bridge_rule_id")) == rule_id
            )
            projection_status = "BRIDGE_READY"
            bridge_value = source_value
            if comparability == "PARTIALLY_COMPARABLE":
                projection_status = "BRIDGE_READY_PARTIAL_COMPARABILITY"
                audit_rows.append({
                    "audit_status": "PARTIAL_COMPARABILITY",
                    "severity": "WARNING",
                    "presentation_member_id": member_id,
                    "presentation_regime": _text(source.get("presentation_regime")),
                    "analysis_bridge_group": _text(membership.get("analysis_bridge_group")),
                    "bridge_rule_id": rule_id,
                    "company": _text(source.get("company")),
                    "report_year": _text(source.get("report_year")),
                    "period_identity": _text(source.get("period_identity")),
                    "source_row_id": _text(source.get("source_row_id") or source.get("source_row_ids")),
                    "detail": "允许在同一研究组并列展示，但不声明来源分类完全等价。",
                })
            elif comparability == "DISAGGREGATION_REQUIRED" and not certified_disaggregation:
                projection_status = "BLOCKED_DISAGGREGATION_REQUIRED"
                bridge_value = None
                audit_rows.append({
                    "audit_status": projection_status,
                    "severity": "BLOCKING_FOR_BRIDGE_ONLY",
                    "presentation_member_id": member_id,
                    "presentation_regime": _text(source.get("presentation_regime")),
                    "analysis_bridge_group": _text(membership.get("analysis_bridge_group")),
                    "bridge_rule_id": rule_id,
                    "company": _text(source.get("company")),
                    "report_year": _text(source.get("report_year")),
                    "period_identity": _text(source.get("period_identity")),
                    "source_row_id": _text(source.get("source_row_id") or source.get("source_row_ids")),
                    "detail": "缺少经认证的债务/权益或摊余成本组成拆分，桥接值保持为空。",
                })
            row.update({
                "view_contract": BRIDGE_SCHEMA_VERSION,
                "analysis_bridge_group": _text(membership.get("analysis_bridge_group")),
                "bridge_rule_id": rule_id,
                "bridge_source_side": _text(membership.get("source_side")),
                "bridge_comparability_status": comparability,
                "bridge_projection_status": projection_status,
                "source_final_value": source_value,
                "final_value": bridge_value,
            })
            row["bridge_semantic_key"] = _bridge_identity(row)
            bridge_rows.append(row)

    bridge_columns = list(original.columns) + [
        column for column in BRIDGE_PROJECTION_COLUMNS
        if column not in original.columns
    ]
    bridge = pd.DataFrame(bridge_rows, columns=bridge_columns)
    if not bridge.empty:
        active = bridge[bridge["final_value"].notna()].copy()
        for identity, group in active.groupby("bridge_semantic_key", sort=False, dropna=False):
            if len(group) <= 1:
                continue
            indexes = list(group.index)
            bridge.loc[indexes, "final_value"] = None
            bridge.loc[indexes, "bridge_projection_status"] = "BRIDGE_AMBIGUOUS_SOURCE_SET"
            audit_rows.append({
                "audit_status": "BRIDGE_AMBIGUOUS_SOURCE_SET",
                "severity": "BLOCKING_FOR_BRIDGE_ONLY",
                "analysis_bridge_group": _text(group["analysis_bridge_group"].iloc[0]),
                "company": _text(group["company"].iloc[0]),
                "report_year": _text(group["report_year"].iloc[0]),
                "period_identity": _text(group["period_identity"].iloc[0]),
                "source_member_ids": "|".join(sorted(set(group["presentation_member_id"].astype(str)))),
                "bridge_semantic_key": str(identity),
                "detail": "同一桥接身份和期间存在多个有效来源；禁止求和或按顺序取值。",
            })

    audit = pd.DataFrame(audit_rows, columns=list(BRIDGE_AUDIT_COLUMNS))
    safe = bridge[
        bridge.get("final_value", pd.Series(dtype="float64")).notna()
    ].copy() if not bridge.empty else pd.DataFrame()
    if safe.empty:
        wide = pd.DataFrame(columns=list(BRIDGE_WIDE_IDENTITY_COLUMNS))
    else:
        safe["bridge_document_column"] = safe.apply(
            lambda row: " | ".join([
                f"company={_text(row.get('company'))}",
                f"report_year={_text(row.get('report_year'))}",
                f"period={_text(row.get('period_identity'))}",
                f"measure={_text(row.get('measure'))}",
                f"unit={_text(row.get('unit'))}",
            ]), axis=1,
        )
        index_columns = [
            column for column in (
                "analysis_bridge_group", "bridge_comparability_status",
                "classification_axis", "canonical_item",
                "semantic_parent_path", "semantic_occurrence",
            ) if column in safe.columns
        ]
        duplicate = safe.duplicated(index_columns + ["bridge_document_column"], keep=False)
        if duplicate.any():
            bad_indexes = list(safe.index[duplicate])
            bridge.loc[bad_indexes, "final_value"] = None
            bridge.loc[bad_indexes, "bridge_projection_status"] = "BRIDGE_WIDE_IDENTITY_CONFLICT"
            audit = pd.concat([audit, pd.DataFrame([{
                "audit_status": "BRIDGE_WIDE_IDENTITY_CONFLICT",
                "severity": "BLOCKING_FOR_BRIDGE_ONLY",
                "detail": "桥接宽表键仍存在多个来源，相关值未进入宽表。",
            }])], ignore_index=True)
            safe = safe.loc[~duplicate].copy()
        wide = safe.pivot(
            index=index_columns,
            columns="bridge_document_column",
            values="final_value",
        ).reset_index() if not safe.empty else pd.DataFrame(columns=index_columns)
        wide.columns.name = None
    return original, bridge.reset_index(drop=True), wide, audit.reset_index(drop=True)
