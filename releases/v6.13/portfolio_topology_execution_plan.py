"""Shared execution-plan contract for investment-portfolio topologies.

Both headless/offline callers and the Streamlit adapter consume this pure
projection.  It does not discover, certify, persist, or capture anything.
"""
from __future__ import annotations

from typing import Any, Iterable

from investment_portfolio_topology_contract import (
    INVESTMENT_PORTFOLIO_TOPOLOGY_CONTRACT,
)


PORTFOLIO_TOPOLOGY_EXECUTION_PLAN_VERSION = (
    "PORTFOLIO_TOPOLOGY_EXECUTION_PLAN_V1"
)
DIRECT_PHYSICAL_TABLE = "DIRECT_PHYSICAL_TABLE"
NOTE_CHILD_TABLE = "NOTE_CHILD_TABLE"

_TOPOLOGY_ALIASES = {
    "MULTI_NOTE_COMPONENTS_NO_TOTAL": (
        "MULTI_NOTE_COMPONENT_SET_NO_REPORTED_TOTAL"
    ),
}


def canonical_portfolio_topology(value: Any) -> str:
    topology = str(value or "").strip().upper()
    return _TOPOLOGY_ALIASES.get(topology, topology)


def _first(mapping: dict[str, Any], *keys: str) -> Any:
    for key in keys:
        value = mapping.get(key)
        if value not in (None, "", [], {}):
            return value
    return None


def _evidence(row: dict[str, Any]) -> dict[str, Any]:
    return dict(
        row.get("inline_note_reference_evidence")
        or row.get("evidence")
        or {}
    )


def _topology_from_occurrence(occurrence: dict[str, Any]) -> str:
    structure = dict(occurrence.get("structure_evidence") or {})
    evidence = dict(occurrence.get("evidence") or {})
    values = [
        occurrence.get("disclosure_topology"),
        structure.get("disclosure_topology"),
        evidence.get("disclosure_topology"),
    ]
    values.extend(
        _first(dict(child), "disclosure_topology")
        or _evidence(dict(child)).get("disclosure_topology")
        for child in occurrence.get("child_rows") or []
    )
    topologies = {
        canonical_portfolio_topology(value) for value in values if value
    }
    if len(topologies) != 1:
        return "" if not topologies else "CONFLICTING_TOPOLOGIES"
    return next(iter(topologies))


def portfolio_source_kind(row: dict[str, Any]) -> str:
    evidence = _evidence(row)
    explicit = str(
        _first(row, "portfolio_source_kind", "source_kind")
        or _first(evidence, "portfolio_source_kind", "source_kind")
        or ""
    ).upper()
    if explicit in {DIRECT_PHYSICAL_TABLE, NOTE_CHILD_TABLE}:
        return explicit
    if bool(row.get("direct_portfolio_table") or evidence.get("direct_portfolio_table")):
        return DIRECT_PHYSICAL_TABLE
    note_reference = str(
        _first(
            row,
            "note_reference_normalized",
            "note_reference",
            "inline_note_reference",
        )
        or _first(evidence, "normalized_note_reference", "note_reference")
        or ""
    ).strip()
    if note_reference or row.get("note_target_candidates"):
        return NOTE_CHILD_TABLE
    return "UNRESOLVED"


def _direct_targets(
    children: Iterable[dict[str, Any]], *, topology: str = ""
) -> list[dict[str, Any]]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for child in children:
        if portfolio_source_kind(child) != DIRECT_PHYSICAL_TABLE:
            continue
        evidence = _evidence(child)
        physical_id = str(
            _first(child, "physical_asset_id")
            or _first(evidence, "physical_asset_id")
            or ""
        )
        key = physical_id or "MISSING_PHYSICAL_ASSET_ID"
        grouped.setdefault(key, []).append(child)
    targets = []
    for physical_id, rows in grouped.items():
        first = rows[0]
        evidence = _evidence(first)
        members = list(dict.fromkeys(
            str(_first(row, "canonical_concept_id", "member_table", "member_id") or "")
            for row in rows
            if _first(row, "canonical_concept_id", "member_table", "member_id")
        ))
        logical_blocks = list(dict.fromkeys(
            str(_first(row, "logical_block_id") or _evidence(row).get("logical_block_id") or "")
            for row in rows
            if _first(row, "logical_block_id") or _evidence(row).get("logical_block_id")
        ))
        bbox = dict(_first(first, "physical_bbox") or evidence.get("physical_bbox") or {})
        page = _first(
            first,
            "candidate_note_pdf_page_index",
            "statement_pdf_page_index",
        ) or evidence.get("portfolio_page")
        targets.append({
            "target_id": physical_id,
            "source_kind": DIRECT_PHYSICAL_TABLE,
            "certification_target_type": DIRECT_PHYSICAL_TABLE,
            "physical_asset_id": physical_id,
            "member_table_ids": members,
            "logical_block_ids": logical_blocks,
            "classification_axes": list(dict.fromkeys(
                str(_first(row, "classification_axis") or _evidence(row).get("classification_axis") or "")
                for row in rows
                if _first(row, "classification_axis") or _evidence(row).get("classification_axis")
            )),
            "conditional_logical_members": list(
                (INVESTMENT_PORTFOLIO_TOPOLOGY_CONTRACT["topologies"]
                 .get(str(topology or _first(first, "disclosure_topology") or evidence.get("disclosure_topology") or ""), {})
                 .get("conditional_logical_members") or [])
            ),
            "page": int(page) if str(page or "").isdigit() else None,
            "bbox": bbox,
            "capture_role": "DIRECT_DISCLOSURE_TABLE",
            "required": True,
        })
    return targets


def _note_targets(children: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    targets = []
    for order, child in enumerate(children):
        if portfolio_source_kind(child) != NOTE_CHILD_TABLE:
            continue
        evidence = _evidence(child)
        member_id = str(
            _first(child, "canonical_concept_id", "member_table", "member_id")
            or "portfolio_components"
        )
        note_reference = str(
            _first(
                child,
                "note_reference_normalized",
                "note_reference",
                "inline_note_reference",
            )
            or _first(evidence, "normalized_note_reference", "note_reference")
            or ""
        )
        target_id = str(
            _first(child, "anchor_child_id", "source_discovery_id")
            or f"NOTE::{order}::{member_id}::{note_reference}"
        )
        targets.append({
            "target_id": target_id,
            "source_kind": NOTE_CHILD_TABLE,
            "certification_target_type": NOTE_CHILD_TABLE,
            "member_table_ids": [member_id],
            "note_reference": note_reference,
            "candidate_count": len(child.get("note_target_candidates") or []),
            "capture_role": "NOTE_COMPONENT",
            "required": bool(child.get("required_for_topology", True)),
        })
    return targets


def build_portfolio_topology_execution_plan(
    occurrence: dict[str, Any],
) -> dict[str, Any]:
    """Project one filing occurrence into the shared five-topology plan."""
    topology = _topology_from_occurrence(occurrence)
    contract = dict(
        INVESTMENT_PORTFOLIO_TOPOLOGY_CONTRACT.get("topologies", {}).get(
            topology, {}
        )
    )
    policy = dict(contract.get("execution_policy") or {})
    children = [dict(row) for row in occurrence.get("child_rows") or []]
    direct_targets = _direct_targets(children, topology=topology)
    note_targets = _note_targets(children)
    targets = [*direct_targets, *note_targets]
    present_kinds = {target["source_kind"] for target in targets}
    required_kinds = set(policy.get("required_source_kinds") or [])
    allowed_kinds = set(policy.get("allowed_source_kinds") or [])
    issues: list[str] = []
    if not contract:
        issues.append("PORTFOLIO_TOPOLOGY_UNSUPPORTED_OR_UNRESOLVED")
    for source_kind in sorted(required_kinds - present_kinds):
        issues.append(f"REQUIRED_{source_kind}_SOURCE_MISSING")
    for source_kind in sorted(present_kinds - allowed_kinds):
        issues.append(f"{source_kind}_NOT_ALLOWED_FOR_TOPOLOGY")
    for target in direct_targets:
        if not target["physical_asset_id"] or target["physical_asset_id"] == "MISSING_PHYSICAL_ASSET_ID":
            issues.append("DIRECT_PHYSICAL_ASSET_ID_REQUIRED")
        if target["page"] is None:
            issues.append("DIRECT_PHYSICAL_PAGE_REQUIRED")
        if not all(key in target["bbox"] for key in ("x0", "y0", "x1", "y1")):
            issues.append("DIRECT_PHYSICAL_BBOX_REQUIRED")
    for target in note_targets:
        if target["required"] and not target["note_reference"]:
            issues.append("NOTE_COMPONENT_REFERENCE_REQUIRED")
    if topology == "DIRECT_COMPOUND_TABLE":
        if len(direct_targets) != 1:
            issues.append("COMPOUND_TABLE_REQUIRES_ONE_PHYSICAL_ASSET")
        if len(direct_targets) == 1 and len(direct_targets[0]["logical_block_ids"]) < 2:
            issues.append("COMPOUND_TABLE_REQUIRES_MULTIPLE_LOGICAL_BLOCKS")
    if topology == "DIRECT_SEPARATE_TABLES_SAME_PAGE" and len(direct_targets) < 2:
        issues.append("SEPARATE_TABLES_REQUIRE_MULTIPLE_PHYSICAL_ASSETS")
    if topology == "DIRECT_SINGLE_AXIS_TABLE" and len(direct_targets) != 1:
        issues.append("SINGLE_AXIS_REQUIRES_ONE_PHYSICAL_ASSET")
    issues = list(dict.fromkeys(issues))
    route = str(policy.get("ui_route") or "UNRESOLVED")
    return {
        "plan_contract_version": PORTFOLIO_TOPOLOGY_EXECUTION_PLAN_VERSION,
        "topology_contract_version": INVESTMENT_PORTFOLIO_TOPOLOGY_CONTRACT.get("contract_version"),
        "occurrence_id": str(occurrence.get("occurrence_id") or ""),
        "pdf_id": str(occurrence.get("pdf_id") or ""),
        "company": str(occurrence.get("company") or ""),
        "report_year": str(occurrence.get("report_year") or ""),
        "scope": str(occurrence.get("scope") or "UNKNOWN"),
        "topology": topology,
        "ui_route": route,
        "stage_a_review_mode": policy.get("stage_a_review_mode"),
        "stage_b_certification_targets": list(
            policy.get("stage_b_certification_targets") or []
        ),
        "required_source_kinds": sorted(required_kinds),
        "allowed_source_kinds": sorted(allowed_kinds),
        "direct_targets": direct_targets,
        "note_targets": note_targets,
        "certification_targets": targets,
        "aggregation_policy": policy.get("aggregation_policy"),
        "reported_total_policy": contract.get("reported_total_policy"),
        "readiness": "READY_FOR_STAGE_A_REVIEW" if not issues else "REVIEW_REQUIRED",
        "blocking_issue_codes": issues,
        "counts": {
            "direct_physical_targets": len(direct_targets),
            "note_child_targets": len(note_targets),
            "logical_blocks": sum(len(row["logical_block_ids"]) for row in direct_targets),
        },
    }


def certification_target_for_concept(
    plan: dict[str, Any], concept: dict[str, Any]
) -> dict[str, Any] | None:
    """Return the plan target governing a persisted Stage-B concept."""
    source_kind = portfolio_source_kind(concept)
    evidence = _evidence(concept)
    physical_id = str(
        _first(concept, "physical_asset_id")
        or evidence.get("physical_asset_id")
        or ""
    )
    member_id = str(
        _first(concept, "canonical_concept_id", "member_table", "member_id")
        or ""
    )
    for target in plan.get("certification_targets") or []:
        if target.get("source_kind") != source_kind:
            continue
        if source_kind == DIRECT_PHYSICAL_TABLE and target.get("physical_asset_id") == physical_id:
            return dict(target)
        if source_kind == NOTE_CHILD_TABLE and (
            str(target.get("target_id") or "")
            == str(concept.get("anchor_child_id") or "")
            or member_id in (target.get("member_table_ids") or [])
        ):
            return dict(target)
    return None


def portfolio_topology_ui_summary(plan: dict[str, Any]) -> dict[str, Any]:
    """Small side-effect-free model used by Streamlit and static tests."""
    route = str(plan.get("ui_route") or "UNRESOLVED")
    labels = {
        "DIRECT_ONLY": ("认证直接物理表", "直接物理表 ROI"),
        "NOTE_ONLY": ("认证附注来源", "附注子表链接"),
        "HYBRID": ("认证直接表与附注组件", "直接 ROI + 附注子表链接"),
    }
    stage_a, stage_b = labels.get(route, ("审核投资组合来源", "待解析认证目标"))
    return {
        "topology": plan.get("topology"),
        "route": route,
        "stage_a_action": stage_a,
        "stage_b_action": stage_b,
        "direct_target_count": (plan.get("counts") or {}).get("direct_physical_targets", 0),
        "note_target_count": (plan.get("counts") or {}).get("note_child_targets", 0),
        "logical_block_count": (plan.get("counts") or {}).get("logical_blocks", 0),
        "aggregation_policy": plan.get("aggregation_policy"),
        "readiness": plan.get("readiness"),
        "blocking_issue_codes": list(plan.get("blocking_issue_codes") or []),
    }


def evaluate_portfolio_certification_readiness(
    plan: dict[str, Any],
    certified_links: Iterable[dict[str, Any]],
) -> dict[str, Any]:
    """Fail closed until every topology-required source has a certified link."""
    links = [
        dict(link) for link in certified_links
        if str(link.get("certification_status") or "") == "CERTIFIED"
    ]
    direct_ids = {
        str(
            link.get("logical_table_id")
            or link.get("physical_asset_id")
            or ""
        )
        for link in links
        if str(link.get("relation_type") or "")
        == "DIRECT_PORTFOLIO_WHOLE_TABLE"
    }
    note_child_ids = {
        str(link.get("anchor_child_id") or "")
        for link in links
        if str(link.get("relation_type") or "")
        != "DIRECT_PORTFOLIO_WHOLE_TABLE"
    }
    missing: list[str] = []
    for target in plan.get("certification_targets") or []:
        if not bool(target.get("required", True)):
            continue
        if target.get("source_kind") == DIRECT_PHYSICAL_TABLE:
            target_id = str(target.get("physical_asset_id") or "")
            if target_id not in direct_ids:
                missing.append(str(target.get("target_id") or target_id))
        elif target.get("source_kind") == NOTE_CHILD_TABLE:
            target_id = str(target.get("target_id") or "")
            if target_id not in note_child_ids:
                missing.append(target_id)
    issues = list(plan.get("blocking_issue_codes") or [])
    if missing:
        issues.append("REQUIRED_PORTFOLIO_CERTIFICATION_TARGETS_MISSING")
    return {
        "status": "READY_FOR_CAPTURE_PLAN" if not issues else "REVIEW_REQUIRED",
        "missing_target_ids": missing,
        "blocking_issue_codes": list(dict.fromkeys(issues)),
        "certified_direct_physical_ids": sorted(x for x in direct_ids if x),
        "certified_note_child_ids": sorted(x for x in note_child_ids if x),
    }
