"""Registry-derived member/period contract for financial-investment anchors.

This module is deliberately small: it projects the existing Research Definition
registry contract into the shape consumed by StatementAnchorEvidenceV2.  It does
not discover pages, parse values, or create a second family resolver.
"""
from __future__ import annotations

from typing import Any

from research_definition_registry import (
    BUILTIN_MEMBERS,
    FINANCIAL_INVESTMENT_EXPECTED_MEMBER_CONTRACTS,
    FINANCIAL_INVESTMENT_LEGACY_MEMBERS,
    FINANCIAL_INVESTMENT_MEMBER_CONTRACT_VERSION,
    FINANCIAL_INVESTMENT_NEW_MEMBERS,
    FINANCIAL_INVESTMENT_STANDARDS_BRIDGE_RULES,
)


_KNOWN_REGIMES = {
    "NEW_FINANCIAL_INSTRUMENT_CLASSIFICATION",
    "LEGACY_FINANCIAL_ASSET_CLASSIFICATION",
    "MIXED_TRANSITION_PRESENTATION",
    "UNKNOWN",
}


def _member_specs() -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    for raw in BUILTIN_MEMBERS["financial_investment"]:
        if raw.get("member_role") == "STATEMENT_ANCHOR" or raw.get("outside_family"):
            continue
        payload = dict(raw.get("payload") or {})
        aliases = [str(raw.get("display_name") or ""), *(raw.get("aliases") or []), *(payload.get("aliases") or [])]
        output.append({
            "member_table": str(raw["member_id"]),
            "presentation_member_id": str(raw["member_id"]),
            "display_name": str(raw.get("display_name") or raw["member_id"]),
            "aliases": list(dict.fromkeys(value for value in aliases if value)),
            "presentation_regime": str(raw.get("presentation_regime") or payload.get("presentation_regime") or "UNKNOWN"),
            "canonical_analysis_bucket": str(raw.get("canonical_analysis_bucket") or raw["member_id"]),
            "comparability_status": str(raw.get("comparability_status") or "EXACT"),
            "analysis_bridge_groups": [dict(item) for item in raw.get("analysis_bridge_groups") or []],
        })
    return output


def _candidate_regime(candidate: dict[str, Any]) -> str:
    evidence = dict(candidate.get("evidence") or {})
    values = [
        candidate.get("presentation_regime"),
        evidence.get("presentation_regime"),
        *[row.get("presentation_regime") for row in candidate.get("child_rows") or []],
    ]
    return next((str(value) for value in values if str(value or "") in _KNOWN_REGIMES), "UNKNOWN")


def _lane(regime: str, scope: str) -> dict[str, Any]:
    regime_contract = dict(
        FINANCIAL_INVESTMENT_EXPECTED_MEMBER_CONTRACTS.get(regime)
        or FINANCIAL_INVESTMENT_EXPECTED_MEMBER_CONTRACTS["UNKNOWN"]
    )
    return dict(
        regime_contract.get(scope)
        or regime_contract.get("CONSOLIDATED")
        or next(iter(regime_contract.values()), {})
    )


def _resolved_aliases(specs: list[dict[str, Any]], regime: str) -> list[dict[str, Any]]:
    """Expose both identities for the long FVTPL label.

    A filing-level ``presentation_regime`` is not enough to decide this label:
    a formally new-regime annual report can show the pre-transition FVTPL line
    as ``不适用`` beside a current ``交易性金融资产`` row.  Removing the legacy
    alias at contract construction loses that row before the row-level period
    resolver can see it.  Keep both aliases and let ``_resolve_ambiguous_member``
    select the current or historical identity from its actual period cells.
    """
    del regime  # the row, rather than the filing label, owns this distinction
    return [{**spec, "aliases": list(spec["aliases"])} for spec in specs]


def financial_member_contract_snapshot(candidate: dict[str, Any]) -> dict[str, Any]:
    """Return the candidate's immutable Registry member-lane snapshot."""
    evidence = dict(candidate.get("evidence") or {})
    existing = dict(evidence.get("member_contract_snapshot") or candidate.get("member_contract_snapshot") or {})
    # V4 snapshots encoded the filing-level alias suppression above.  They are
    # still useful for their historical lane facts, but must be projected onto
    # the V5 Registry alias vocabulary before Stage A makes a row identity.
    if (
        existing.get("contract_version") == FINANCIAL_INVESTMENT_MEMBER_CONTRACT_VERSION
        and existing.get("members")
        and existing.get("required_current_members") is not None
    ):
        return existing

    regime = str(existing.get("presentation_regime") or _candidate_regime(candidate))
    source_scope = str(
        candidate.get("source_statement_scope")
        or candidate.get("scope")
        or evidence.get("source_statement_scope")
        or "CONSOLIDATED"
    )
    contract_scope = "CONSOLIDATED" if source_scope == "COMBINED_CONSOLIDATED_AND_PARENT" else source_scope
    lane = _lane(regime, contract_scope)
    required = list(
        candidate.get("required_current_members")
        or evidence.get("required_current_members")
        or existing.get("required_current_members")
        or lane.get("current_required_members")
        or lane.get("required_members")
        or []
    )
    optional = list(
        candidate.get("optional_current_members")
        or evidence.get("optional_current_members")
        or existing.get("optional_current_members")
        or lane.get("optional_members")
        or []
    )
    historical = list(
        candidate.get("historical_variant_members")
        or evidence.get("historical_variant_members")
        or existing.get("historical_variant_members")
        or lane.get("historical_variant_members")
        or []
    )
    comparative = list(
        candidate.get("comparative_only_members")
        or evidence.get("comparative_only_members")
        or existing.get("comparative_only_members")
        or [
            str(row.get("member_table") or "")
            for row in candidate.get("child_rows") or []
            if row.get("member_period_status") == "COMPARATIVE_ONLY_LEGACY_MEMBER"
        ]
    )
    return {
        "contract_version": FINANCIAL_INVESTMENT_MEMBER_CONTRACT_VERSION,
        "presentation_regime": regime,
        "statement_scope": source_scope,
        "required_current_members": list(dict.fromkeys(required)),
        "optional_current_members": list(dict.fromkeys(optional)),
        "historical_variant_members": list(dict.fromkeys(historical)),
        "comparative_only_members": list(dict.fromkeys(value for value in comparative if value)),
        "new_members": list(FINANCIAL_INVESTMENT_NEW_MEMBERS),
        "legacy_members": list(FINANCIAL_INVESTMENT_LEGACY_MEMBERS),
        "physical_row_identity": "SOURCE_ROW_ID__PERIOD_IDENTITY",
        "filing_level_member_mutual_exclusion": False,
        "standards_bridge_rules": [dict(rule) for rule in FINANCIAL_INVESTMENT_STANDARDS_BRIDGE_RULES],
        "members": _resolved_aliases(_member_specs(), regime),
    }


def expected_member_union(snapshot: dict[str, Any]) -> list[str]:
    return list(dict.fromkeys([
        *(snapshot.get("required_current_members") or []),
        *(snapshot.get("optional_current_members") or []),
        *(snapshot.get("historical_variant_members") or []),
        *(snapshot.get("comparative_only_members") or []),
    ]))
