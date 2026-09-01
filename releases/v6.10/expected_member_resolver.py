"""v6.10 expected-member resolver.

Replaces the static global member injection with a resolution-mode-aware,
presentation-regime-aware expected-member contract.  Inputs and outputs are
dict-based so this module does not import SQLite or any other infrastructure.
"""
from __future__ import annotations

from typing import Any


# Re-export the period status constants for callers.
ACTIVE_CURRENT_PERIOD = "ACTIVE_CURRENT_PERIOD"
ACTIVE_COMPARATIVE_PERIOD = "ACTIVE_COMPARATIVE_PERIOD"
COMPARATIVE_ONLY_LEGACY_MEMBER = "COMPARATIVE_ONLY_LEGACY_MEMBER"
INACTIVE_CURRENT_PERIOD = "INACTIVE_CURRENT_PERIOD"
OUTSIDE_FAMILY = "OUTSIDE_FAMILY"
UNRESOLVED = "UNRESOLVED"


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
) -> dict[str, Any]:
    """Return the expected-member contract for one statement occurrence.

    Parameters
    ----------
    resolution_mode:
        One of ``EXPLICIT_PARENT``, ``IMPLICIT_MEMBER_SET``, ``HYBRID``.
    presentation_regime:
        ``NEW_FINANCIAL_INSTRUMENT_CLASSIFICATION``,
        ``LEGACY_FINANCIAL_ASSET_CLASSIFICATION``,
        ``MIXED_TRANSITION_PRESENTATION``, or ``UNKNOWN``.
    registry_members:
        All family members from the registry, each with ``member_id``,
        ``required``, and ``payload`` that may contain ``presentation_regime``.
    actual_statement_rows:
        Rows parsed from the actual statement page.  Each row must have
        ``member_table`` (member_id) and ``member_period_status`` (one of
        the period status constants).

    Returns
    -------
    dict with keys:
      - ``required_current_members`` -- ACTIVE_CURRENT_PERIOD only
      - ``optional_current_members``
      - ``comparative_only_members``
      - ``outside_family_members``
      - ``unresolved_members``
      - ``resolution_contract_version``
    """
    member_regime_map: dict[str, str] = {}
    for m in registry_members:
        payload = m.get("payload") or {}
        member_regime_map[m["member_id"]] = str(
            payload.get("presentation_regime") or ""
        )

    required_current: list[str] = []
    optional_current: list[str] = []
    comparative_only: list[str] = []
    outside_family: list[str] = []
    unresolved: list[str] = []

    for row in actual_statement_rows:
        member_id = str(row.get("member_table") or "")
        period_status = str(row.get("member_period_status") or UNRESOLVED)
        member_regime = member_regime_map.get(member_id, "")

        if period_status == ACTIVE_CURRENT_PERIOD:
            if member_regime == "LEGACY_FINANCIAL_ASSET_CLASSIFICATION":
                # A legacy member active in a transition year is still
                # current-period — but mark it as optional unless the
                # resolution mode says otherwise.
                optional_current.append(member_id)
            else:
                required_current.append(member_id)
        elif period_status == COMPARATIVE_ONLY_LEGACY_MEMBER:
            comparative_only.append(member_id)
        elif period_status == OUTSIDE_FAMILY:
            outside_family.append(member_id)
        elif period_status == ACTIVE_COMPARATIVE_PERIOD:
            optional_current.append(member_id)
        else:
            unresolved.append(member_id)

    # In IMPLICIT_MEMBER_SET mode, all found members on the page are the
    # required set — the system cannot assume what is missing.
    if resolution_mode == "IMPLICIT_MEMBER_SET":
        required_current = list(dict.fromkeys(
            required_current + optional_current
        ))
        optional_current = []

    # In EXPLICIT_PARENT mode, only the parent's real descendants are
    # current-period members.  OUTSIDE_FAMILY and COMPARATIVE_ONLY_LEGACY
    # are excluded by definition.
    if resolution_mode == "EXPLICIT_PARENT":
        # OUTSIDE_FAMILY rows are already excluded from required_current.
        # COMPARATIVE_ONLY_LEGACY_MEMBER rows are also excluded.
        pass

    return {
        "required_current_members": required_current,
        "optional_current_members": optional_current,
        "comparative_only_members": comparative_only,
        "outside_family_members": outside_family,
        "unresolved_members": unresolved,
        "resolution_contract_version": definition_version,
    }
