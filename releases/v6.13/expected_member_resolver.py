"""Definition-owned expected-member contracts for statement occurrences.

The expected denominator is resolved from a versioned Research Definition /
Registry contract.  Actual statement rows are observations only: they may
increase the discovered numerator, but can never redefine what was expected.
"""
from __future__ import annotations

from typing import Any


ACTIVE_CURRENT_PERIOD = "ACTIVE_CURRENT_PERIOD"
ACTIVE_COMPARATIVE_PERIOD = "ACTIVE_COMPARATIVE_PERIOD"
COMPARATIVE_ONLY_LEGACY_MEMBER = "COMPARATIVE_ONLY_LEGACY_MEMBER"
INACTIVE_CURRENT_PERIOD = "INACTIVE_CURRENT_PERIOD"
OUTSIDE_FAMILY = "OUTSIDE_FAMILY"
UNRESOLVED = "UNRESOLVED"

NEW_REGIME = "NEW_FINANCIAL_INSTRUMENT_CLASSIFICATION"
LEGACY_REGIME = "LEGACY_FINANCIAL_ASSET_CLASSIFICATION"
MIXED_REGIME = "MIXED_TRANSITION_PRESENTATION"
UNKNOWN_REGIME = "UNKNOWN"
ACTIONABLE = "REVIEW_REQUIRED_ACTIONABLE"

# These are registered research dependencies, not members of the accounting
# statement family.  Do not duplicate release-owned members here: v6.13's
# versioned Registry contract includes ``time_deposits`` as a legacy direct
# member, while the explicit-parent boundary still excludes deposits that sit
# outside a newer ``金融投资`` block.
FINANCIAL_INVESTMENT_OUTSIDE_MEMBERS = {
    "long_term_equity",
}


def _dedupe(values: list[str] | tuple[str, ...] | set[str]) -> list[str]:
    return list(dict.fromkeys(str(value) for value in values if str(value or "")))


def _contract_payload(definition_contract: dict[str, Any] | None) -> dict[str, Any]:
    payload = dict(definition_contract or {})
    nested = payload.get("family_resolution_contract")
    return dict(nested) if isinstance(nested, dict) else payload


def _lane_contract(
    contract: dict[str, Any],
    presentation_regime: str,
    statement_scope: str,
) -> dict[str, Any]:
    regimes = dict(contract.get("expected_member_contracts") or {})
    regime_contract = regimes.get(presentation_regime) or regimes.get("*") or {}
    if not isinstance(regime_contract, dict):
        return {}
    # A regime may directly declare required/optional members, or split them
    # into scope lanes.
    if "required_members" in regime_contract or "optional_members" in regime_contract:
        return dict(regime_contract)
    lane = (
        regime_contract.get(statement_scope)
        or regime_contract.get("BOTH")
        or regime_contract.get("DEFAULT")
        or {}
    )
    return dict(lane) if isinstance(lane, dict) else {}


def _registry_contract(
    *,
    registry_members: list[dict[str, Any]],
    presentation_regime: str,
    outside_members: set[str],
) -> tuple[list[str], list[str]]:
    members = [
        member for member in registry_members
        if member.get("member_role") != "STATEMENT_ANCHOR"
        and str(member.get("member_id") or "") not in outside_members
    ]

    def regime_of(member: dict[str, Any]) -> str:
        return str((member.get("payload") or {}).get("presentation_regime") or "")

    if presentation_regime == LEGACY_REGIME:
        applicable = [member for member in members if regime_of(member) == LEGACY_REGIME]
        return _dedupe([member["member_id"] for member in applicable]), []
    if presentation_regime == NEW_REGIME:
        applicable = [member for member in members if regime_of(member) != LEGACY_REGIME]
        required = [member["member_id"] for member in applicable if bool(member.get("required"))]
        return _dedupe(required or [member["member_id"] for member in applicable]), []
    if presentation_regime == MIXED_REGIME:
        required = [
            member["member_id"] for member in members
            if regime_of(member) != LEGACY_REGIME
            and (bool(member.get("required")) or not any(bool(x.get("required")) for x in members))
        ]
        optional = [
            member["member_id"] for member in members
            if regime_of(member) == LEGACY_REGIME
        ]
        return _dedupe(required), _dedupe(optional)

    # UNKNOWN never guesses a regime.  Registry-required flags are still an
    # external denominator, but the final quality status remains actionable.
    required = [member["member_id"] for member in members if bool(member.get("required"))]
    return _dedupe(required), []


def _expected_sets(
    *,
    definition_contract: dict[str, Any] | None,
    registry_members: list[dict[str, Any]],
    presentation_regime: str,
    statement_scope: str,
) -> tuple[list[str], list[str], set[str], str]:
    contract = _contract_payload(definition_contract)
    outside = set(FINANCIAL_INVESTMENT_OUTSIDE_MEMBERS)
    outside.update(str(value) for value in contract.get("outside_family_members") or [])
    outside.update(
        str(member.get("member_id") or "")
        for member in registry_members
        if bool((member.get("payload") or {}).get("outside_family"))
    )
    lane = _lane_contract(contract, presentation_regime, statement_scope)
    required = _dedupe(list(lane.get("required_members") or []))
    optional = _dedupe(list(lane.get("optional_members") or []))

    if not required:
        fallback_required = _dedupe(list(contract.get("required_members") or []))
        fallback_optional = _dedupe(list(contract.get("optional_members") or []))
        if presentation_regime == LEGACY_REGIME:
            member_regimes = {
                str(member.get("member_id") or ""): str(
                    (member.get("payload") or {}).get("presentation_regime") or ""
                )
                for member in registry_members
            }
            fallback_required = [
                member_id for member_id in fallback_required
                if member_regimes.get(member_id) == LEGACY_REGIME
            ]
            fallback_optional = [
                member_id for member_id in fallback_optional
                if member_regimes.get(member_id) == LEGACY_REGIME
            ]
        if fallback_required:
            required, optional = fallback_required, fallback_optional
        else:
            required, optional = _registry_contract(
                registry_members=registry_members,
                presentation_regime=presentation_regime,
                outside_members=outside,
            )

    required = [member_id for member_id in required if member_id not in outside]
    optional = [
        member_id for member_id in optional
        if member_id not in outside and member_id not in required
    ]
    version = str(
        contract.get("contract_version")
        or contract.get("resolution_contract_version")
        or ""
    )
    return required, optional, outside, version


def _resolve_expected_members_core(
    *,
    resolution_mode: str,
    presentation_regime: str,
    report_year: str,
    statement_scope: str,
    source_parent_boundary: dict[str, Any] | None,
    definition_version: str,
    definition_contract: dict[str, Any] | None,
    registry_members: list[dict[str, Any]],
    actual_statement_rows: list[dict[str, Any]],
) -> dict[str, Any]:
    required, optional, outside_contract, contract_version = _expected_sets(
        definition_contract=definition_contract,
        registry_members=registry_members,
        presentation_regime=presentation_regime,
        statement_scope=statement_scope,
    )
    required_set = set(required)
    optional_set = set(optional)

    discovered: list[str] = []
    comparative_only: list[str] = []
    outside: list[str] = []
    unresolved: list[str] = []
    unexpected: list[str] = []
    inactive: list[str] = []
    missing_native_value_evidence: list[str] = []

    for row in actual_statement_rows:
        member_id = str(row.get("member_table") or "")
        if not member_id:
            continue
        period_status = str(row.get("member_period_status") or UNRESOLVED)
        if member_id in outside_contract or period_status == OUTSIDE_FAMILY:
            outside.append(member_id)
            continue

        discovered.append(member_id)
        if period_status == COMPARATIVE_ONLY_LEGACY_MEMBER:
            comparative_only.append(member_id)
        elif period_status == INACTIVE_CURRENT_PERIOD:
            inactive.append(member_id)
        elif period_status not in {ACTIVE_CURRENT_PERIOD, ACTIVE_COMPARATIVE_PERIOD}:
            unresolved.append(member_id)

        if member_id not in required_set and member_id not in optional_set:
            unexpected.append(member_id)
        if (
            bool(row.get("ocr_used"))
            or row.get("native_value_geometry_present") is False
            or str(row.get("value_evidence_status") or "").startswith("REJECTED_OCR")
        ):
            missing_native_value_evidence.append(member_id)

    discovered = _dedupe(discovered)
    comparative_only = _dedupe(comparative_only)
    outside = _dedupe(outside)
    unresolved = _dedupe(unresolved)
    unexpected = _dedupe(unexpected)
    inactive = _dedupe(inactive)
    missing_native_value_evidence = _dedupe(missing_native_value_evidence)
    discovered_required = [member_id for member_id in required if member_id in set(discovered)]
    missing_required = [member_id for member_id in required if member_id not in set(discovered)]
    numerator = len(discovered_required)
    denominator = len(required)
    coverage_ratio = round(numerator / denominator, 6) if denominator else None

    blockers: list[str] = []
    if presentation_regime == UNKNOWN_REGIME:
        blockers.append("PRESENTATION_REGIME_UNKNOWN")
    if not denominator:
        blockers.append("EXPECTED_MEMBER_DENOMINATOR_EMPTY")
    if missing_required:
        blockers.append("EXPECTED_REQUIRED_MEMBERS_MISSING")
    if unresolved:
        blockers.append("MEMBER_PERIOD_STATUS_UNRESOLVED")
    if missing_native_value_evidence:
        blockers.append("NATIVE_VALUE_GEOMETRY_REQUIRED")
    if unexpected:
        blockers.append("UNEXPECTED_FAMILY_MEMBERS")
    quality = ACTIONABLE if blockers else "RESOLVED"

    return {
        "required_current_members": required,
        "optional_current_members": optional,
        "discovered_members": discovered,
        "discovered_required_members": discovered_required,
        "missing_required_members": missing_required,
        "unexpected_members": unexpected,
        "comparative_only_members": comparative_only,
        "outside_family_members": outside,
        "outside_family_contract_members": sorted(outside_contract),
        "inactive_current_members": inactive,
        "unresolved_members": unresolved,
        "missing_native_value_evidence_members": missing_native_value_evidence,
        "coverage_numerator": numerator,
        "coverage_denominator": denominator,
        "coverage_ratio": coverage_ratio,
        "coverage_status": "PASS" if not blockers else ACTIONABLE,
        "quality_status": quality,
        "review_status": quality,
        "actionable_reasons": blockers,
        "resolution_contract_version": contract_version or definition_version,
        "expected_member_contract_version": (
            contract_version or definition_version
        ),
        "definition_version": definition_version,
        "presentation_regime": presentation_regime,
        "statement_scope": statement_scope,
        "report_year": str(report_year),
        "resolution_mode": resolution_mode,
        "source_parent_boundary_present": bool(source_parent_boundary),
    }


class ChinaLifeImplicitMemberContract:
    """Parentless, regime-driven implicit-member contract.

    The historical name identifies the disclosure pattern that motivated the
    contract.  The implementation contains no company, filename, year, page,
    or amount switch and is safe for any matching implicit presentation.
    """

    @staticmethod
    def resolve(
        *,
        presentation_regime: str,
        statement_scope: str,
        definition_version: str,
        definition_contract: dict[str, Any] | None,
        registry_members: list[dict[str, Any]],
        actual_statement_rows: list[dict[str, Any]],
        report_year: str = "",
    ) -> dict[str, Any]:
        result = _resolve_expected_members_core(
            resolution_mode="IMPLICIT_MEMBER_SET",
            presentation_regime=presentation_regime,
            report_year=report_year,
            statement_scope=statement_scope,
            source_parent_boundary=None,
            definition_version=definition_version,
            definition_contract=definition_contract,
            registry_members=registry_members,
            actual_statement_rows=actual_statement_rows,
        )
        result.update({
            "raw_parent_row_id": None,
            "raw_parent_label": None,
            "derived_parent_is_source_text": False,
            "implicit_member_contract": "CHINA_LIFE_IMPLICIT_MEMBER_CONTRACT_V1",
        })
        return result


def resolve_expected_members(
    *,
    resolution_mode: str,
    presentation_regime: str,
    report_year: str,
    statement_scope: str,
    source_parent_boundary: dict[str, Any] | None,
    definition_version: str,
    registry_members: list[dict[str, Any]],
    actual_statement_rows: list[dict[str, Any]],
    definition_contract: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if resolution_mode == "IMPLICIT_MEMBER_SET":
        return ChinaLifeImplicitMemberContract.resolve(
            presentation_regime=presentation_regime,
            report_year=report_year,
            statement_scope=statement_scope,
            definition_version=definition_version,
            definition_contract=definition_contract,
            registry_members=registry_members,
            actual_statement_rows=actual_statement_rows,
        )
    return _resolve_expected_members_core(
        resolution_mode=resolution_mode,
        presentation_regime=presentation_regime,
        report_year=report_year,
        statement_scope=statement_scope,
        source_parent_boundary=source_parent_boundary,
        definition_version=definition_version,
        definition_contract=definition_contract,
        registry_members=registry_members,
        actual_statement_rows=actual_statement_rows,
    )
