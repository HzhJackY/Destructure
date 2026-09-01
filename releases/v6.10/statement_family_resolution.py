"""Evidence-first statement-family resolution.

A research family is a semantic grouping, never a fabricated PDF row.  This
resolver therefore keeps source rows intact and supports three physical
presentations: an explicit source parent, a set of direct statement rows, and
a hybrid of both.  It deliberately does not calculate a family total.
"""
from __future__ import annotations

import re
import uuid
from typing import Any

from statement_anchored_family import compose_note_reference, normalize_text
from statement_note_navigation import locate_primary_statements, locate_note
from expected_member_resolver import resolve_expected_members


_NEW_MARKERS = ("交易性金融资产", "债权投资", "其他债权投资", "其他权益工具投资")
_LEGACY_MARKERS = ("可供出售金融资产", "持有至到期投资", "贷款及应收款项", "贷款")

# v6.10: member period status — separates current-period members from
# comparative-only legacy rows and items outside the family boundary.
MEMBER_PERIOD_STATUSES = {
    "ACTIVE_CURRENT_PERIOD",
    "ACTIVE_COMPARATIVE_PERIOD",
    "COMPARATIVE_ONLY_LEGACY_MEMBER",
    "INACTIVE_CURRENT_PERIOD",
    "OUTSIDE_FAMILY",
    "UNRESOLVED",
}


def _scope(text: str) -> str:
    head = normalize_text("\n".join(str(text or "").splitlines()[:20]))
    if "合并及公司资产负债表" in head:
        return "COMBINED_CONSOLIDATED_AND_PARENT"
    if "合并资产负债表" in head:
        return "CONSOLIDATED"
    if "资产负债表" in head:
        return "PARENT_COMPANY"
    return "UNKNOWN"


def _regime(labels: list[str]) -> str:
    compact = "|".join(normalize_text(x) for x in labels)
    has_new = any(normalize_text(x) in compact for x in _NEW_MARKERS)
    has_legacy = any(normalize_text(x) in compact for x in _LEGACY_MARKERS)
    if has_new and has_legacy:
        return "MIXED_TRANSITION_PRESENTATION"
    if has_new:
        return "NEW_FINANCIAL_INSTRUMENT_CLASSIFICATION"
    if has_legacy:
        return "LEGACY_FINANCIAL_ASSET_CLASSIFICATION"
    return "UNKNOWN"


def _member_semantics(member: dict[str, Any], regime: str) -> tuple[str, str]:
    """Return analysis bucket and conservative comparability.

    Registry membership is intentionally not a bridge between the pre-IFRS 9
    and new classifications.  In particular, AFS is not automatically other
    debt investment and HTM is not automatically debt investment.
    """
    payload = member.get("payload") or {}
    bucket = str(payload.get("canonical_analysis_bucket") or member["member_id"])
    declared = payload.get("comparability_status")
    if declared:
        return bucket, str(declared)
    if regime == "NEW_FINANCIAL_INSTRUMENT_CLASSIFICATION":
        return bucket, "EXACT"
    if regime == "LEGACY_FINANCIAL_ASSET_CLASSIFICATION":
        return bucket, "PARTIALLY_COMPARABLE"
    if regime == "MIXED_TRANSITION_PRESENTATION":
        return bucket, "UNRESOLVED"
    return bucket, "UNRESOLVED"


def _classify_period_status(
    row: dict[str, Any],
    *,
    regime: str,
    is_child_of_parent: bool,
    parent_present: bool,
    member_ids_in_family: set[str],
) -> str:
    """Classify a statement row's period status for v6.10 governance.

    Returns one of:
      - ``ACTIVE_CURRENT_PERIOD`` — current-classification member with a
        current-period amount
      - ``COMPARATIVE_ONLY_LEGACY_MEMBER`` — legacy member whose amount is
        missing or ``-``; only appears in comparative columns
      - ``OUTSIDE_FAMILY`` — row appears on the page but is not a descendant
        of the explicit parent boundary
      - ``UNRESOLVED`` — cannot determine status
    """
    member_id = str(row.get("member_table") or "")
    amount_str = str(row.get("statement_amount_raw") or "").strip()
    member_regime = str(
        (row.get("member", {}).get("payload") or {}).get("presentation_regime") or ""
    )

    # Rows that are registered members but not children of an explicit
    # parent are outside the family boundary (e.g. time_deposits on a
    # page that has a "金融投资" parent with NEW-classification children).
    if parent_present and not is_child_of_parent and member_id in member_ids_in_family:
        return "OUTSIDE_FAMILY"

    # A legacy member with no current-period amount is comparative-only.
    # The amount is ``-``, None, or a single dash when the item only
    # existed in the prior accounting regime.
    if regime == "MIXED_TRANSITION_PRESENTATION" and member_regime == "LEGACY_FINANCIAL_ASSET_CLASSIFICATION":
        if not amount_str or amount_str in {"-", "—", "–", "－", "N/A", "n/a"}:
            return "COMPARATIVE_ONLY_LEGACY_MEMBER"

    # Core member in the current regime with a real amount is active.
    if regime in {"NEW_FINANCIAL_INSTRUMENT_CLASSIFICATION", "MIXED_TRANSITION_PRESENTATION"}:
        if amount_str and amount_str not in {"-", "—", "–", "－"}:
            return "ACTIVE_CURRENT_PERIOD"

    # A member present in both periods.
    if amount_str and amount_str not in {"-", "—", "–", "－"}:
        return "ACTIVE_COMPARATIVE_PERIOD"

    return "UNRESOLVED"


def _is_descendant_of_parent(
    row_index: int,
    parent_index: int,
    all_line_indices: list[int],
) -> bool:
    """Heuristic: a row is a descendant if it appears after the parent and
    before any intervening non-child line (blank, header, or section break).

    When uncertain, returns False (conservative).
    """
    if parent_index < 0 or row_index <= parent_index:
        return False
    # Simple contiguity: child rows immediately follow the parent with no
    # large gaps.  A gap of >2 non-member lines suggests a new section.
    gap = row_index - parent_index
    if gap > 20:
        return False
    return True


class StatementFamilyResolver:
    """Resolve a registry-defined family while preserving statement evidence."""

    def resolve(self, *, index, family: dict[str, Any], members: list[dict[str, Any]],
                company: str, report_year: str, filing_type: str) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        contract = dict((family.get("payload") or {}).get("family_resolution_contract") or {})
        allowed = set(contract.get("allowed_resolution_modes") or ["EXPLICIT_PARENT"])
        parent_aliases = [normalize_text(x) for x in contract.get("explicit_parent_aliases") or []]
        wanted_scope = (family.get("payload") or {}).get("preferred_scope") or "CONSOLIDATED"
        statement_pages = set(locate_primary_statements(index).get("BALANCE_SHEET", []))
        if not statement_pages:
            return [], []

        member_lookup = self._member_lookup(members)
        core_ids = set((family.get("payload") or {}).get("core_members") or [])
        direct_ids = set(contract.get("direct_member_concepts") or [])
        # Legacy direct members are a declared, versioned part of the family
        # contract.  It is safe to identify them, not safe to bridge them.
        if not direct_ids:
            direct_ids = {m["member_id"] for m in members if (m.get("payload") or {}).get("direct_member", False)}

        candidates: list[dict[str, Any]] = []
        resolutions: list[dict[str, Any]] = []
        for rec in index:
            source_scope = _scope(rec.text)
            if rec.page_number not in statement_pages or source_scope not in {wanted_scope, "COMBINED_CONSOLIDATED_AND_PARENT"}:
                continue
            rows = self._parse_rows(rec.text, member_lookup)
            if not rows:
                continue
            self._apply_page_regime_members(rows, members)
            parent = self._find_parent(rec.text, parent_aliases)
            explicit_rows = [row for row in rows if row["member_table"] in core_ids]
            direct_rows = [row for row in rows if row["member_table"] in direct_ids]

            # A direct set is valid only when its members are explicitly
            # allowed by the definition contract.  We never pull in a merely
            # investment-looking row by keyword.
            if parent and explicit_rows:
                selected = list(explicit_rows)
                origins = {id(row): "EXPLICIT_CHILD_ROW" for row in explicit_rows}
                # A real source parent plus current-classification children is
                # a closed statement block. Legacy direct rows elsewhere on
                # the same page (for example 定期存款、长期股权投资) may look
                # investment-related, but are not children of that parent.
                # Combining them would both over-capture the block and create
                # an unsupported old/new accounting-regime bridge.
                mode = "EXPLICIT_PARENT"
            elif parent and direct_rows:
                # Some reports use a literal parent for an all-legacy set.
                # These are source children of that parent, not a HYBRID with
                # a different regime. Keep the physical parent relationship.
                selected = list(direct_rows)
                origins = {id(row): "EXPLICIT_CHILD_ROW" for row in direct_rows}
                mode = "EXPLICIT_PARENT"
            elif direct_rows and "IMPLICIT_MEMBER_SET" in allowed:
                selected = list(direct_rows)
                origins = {id(row): "DIRECT_STATEMENT_ROW" for row in direct_rows}
                mode = "IMPLICIT_MEMBER_SET"
            else:
                continue

            # An explicit parent may only filter the declared core, while an
            # implicit family must not manufacture that parent as a source row.
            raw_parent_present = mode in {"EXPLICIT_PARENT", "HYBRID"}
            raw_parent_label = parent["label"] if raw_parent_present else None
            raw_parent_row_id = parent["row_id"] if raw_parent_present else None
            labels = [row["raw_member_label"] for row in selected]
            regime = _regime(labels)
            resolution_id = "SFR_" + uuid.uuid4().hex

            # v6.10: classify period status for each selected row
            parent_index = parent.get("_line_index", -1) if parent else -1
            all_indices = [row.get("_line_index", -1) for row in rows]
            member_ids_in_family = {m["member_id"] for m in members}
            period_statuses: dict[str, str] = {}
            for row in selected:
                row_idx = row.get("_line_index", -1)
                is_child = _is_descendant_of_parent(row_idx, parent_index, all_indices) if parent else True
                status = _classify_period_status(
                    row,
                    regime=regime,
                    is_child_of_parent=is_child,
                    parent_present=bool(parent),
                    member_ids_in_family=member_ids_in_family,
                )
                period_statuses[row["member_table"]] = status

            # v6.10: resolve expected members using the centralized contract
            rows_with_status = [
                {**row, "member_period_status": period_statuses.get(row["member_table"], "UNRESOLVED")}
                for row in selected
            ]
            expected = resolve_expected_members(
                resolution_mode=mode,
                presentation_regime=regime,
                report_year=str(report_year),
                statement_scope=wanted_scope,
                source_parent_boundary=parent,
                definition_version=family.get("definition_version", ""),
                registry_members=members,
                actual_statement_rows=rows_with_status,
            )

            evidence = {
                "statement_page_text_excerpt": rec.text[:2200],
                "selected_member_labels": labels,
                "raw_parent_found": bool(parent),
                "contract_modes": sorted(allowed),
                "direct_member_concepts": sorted(direct_ids),
                "explicit_member_concepts": sorted(core_ids),
                "member_period_statuses": period_statuses,
                "current_period_members": [k for k, v in period_statuses.items() if v == "ACTIVE_CURRENT_PERIOD"],
                "comparative_only_members": [k for k, v in period_statuses.items() if v == "COMPARATIVE_ONLY_LEGACY_MEMBER"],
                "outside_family_members": [k for k, v in period_statuses.items() if v == "OUTSIDE_FAMILY"],
                "expected_members": expected,
                "source_rows": [{
                    "row_id": row["source_row_id"],
                    "label": row["raw_member_label"],
                    "member_table": row["member_table"],
                    "source_pdf_page_index": rec.page_number,
                    "origin": origins[id(row)],
                } for row in selected],
            }
            resolutions.append({
                "resolution_id": resolution_id,
                "source_pdf_id": "", "source_pdf_sha256": "",
                "company": company, "report_year": str(report_year), "requested_scope": wanted_scope,
                "family_id": family["family_id"], "resolution_mode": mode,
                "source_statement_anchor_id": f"STMT_{rec.page_number}",
                "raw_parent_row_id": raw_parent_row_id,
                "raw_parent_label": raw_parent_label,
                "derived_family_label": family["display_name"],
                "derived_family_label_is_source_text": raw_parent_present,
                "member_count": len(selected), "member_ids": [x["member_table"] for x in selected],
                "family_total_status": "NOT_REPORTED",
                "reported_family_total_raw": None, "derived_family_total_raw": None,
                "presentation_regime": regime,
                "member_period_statuses": period_statuses,
                "current_period_members": [k for k, v in period_statuses.items() if v == "ACTIVE_CURRENT_PERIOD"],
                "comparative_only_members": [k for k, v in period_statuses.items() if v == "COMPARATIVE_ONLY_LEGACY_MEMBER"],
                "outside_family_members": [k for k, v in period_statuses.items() if v == "OUTSIDE_FAMILY"],
                "quality_status": "RESOLVED",
                "review_status": "REVIEW_REQUIRED" if mode != "EXPLICIT_PARENT" else "NEEDS_REVIEW",
                "evidence": evidence, "producer_version": "v6.10",
                "statement_pdf_page_index": rec.page_number,
            })
            for sequence, row in enumerate(selected, 1):
                note_ref = row["note_reference_normalized"]
                page, method, confidence = None, "UNRESOLVED", 0.0
                if note_ref:
                    page, method, confidence = locate_note(index, note_reference=note_ref, item=row["raw_member_label"], section_context="")
                bucket, comparability = _member_semantics(row["member"], regime)
                origin = origins[id(row)]
                period_status = period_statuses.get(row["member_table"], "UNRESOLVED")
                candidates.append({
                    "discovery_id": "SFM_" + uuid.uuid4().hex,
                    "statement_family_member_id": "SFM_" + uuid.uuid4().hex,
                    "statement_family_resolution_id": resolution_id,
                    "company": company, "normalized_company": company,
                    "report_year": str(report_year), "filing_type": filing_type,
                    "statement_type": "BALANCE_SHEET", "scope": wanted_scope,
                    "source_statement_scope": source_scope,
                    "display_name": family["display_name"], "table_family": family["family_id"],
                    "definition_version": family["definition_version"],
                    "statement_item": row["raw_member_label"], "member_table": row["member_table"],
                    "member_display_name": row["member_display_name"],
                    "canonical_concept_id": row["member_table"],
                    "member_period_status": period_status,
                    "canonical_analysis_bucket": bucket,
                    "raw_member_label": row["raw_member_label"],
                    "normalized_member_label": normalize_text(row["raw_member_label"]),
                    "member_origin": origin, "row_level": 1,
                    "row_order": sequence, "row_path": row["raw_member_label"], "row_bbox": None,
                    "source_row_id": row["source_row_id"], "raw_parent_row_id": raw_parent_row_id if origin == "EXPLICIT_CHILD_ROW" else None,
                    "presentation_regime": regime, "comparability_status": comparability,
                    "family_total_status": "NOT_REPORTED",
                    "statement_amount_raw": row["statement_amount_raw"], "statement_amount_normalized": None,
                    "note_reference": note_ref, "note_reference_normalized": note_ref,
                    "note_reference_section": row["note_reference_section"], "note_reference_item": row["note_reference_item"],
                    "note_reference_raw": row["note_reference_raw"], "note_reference_status": row["note_reference_status"],
                    "inline_note_reference": note_ref, "inline_note_reference_evidence": row["note_reference_raw"],
                    "statement_pdf_page_index": rec.page_number,
                    "candidate_note_pdf_page_index": page, "candidate_note_pages": [page] if page else [],
                    "locator_method": method, "confidence": confidence,
                    "status": "NEEDS_REVIEW" if note_ref and page else "REVIEW_REQUIRED",
                    "source_table_title": "合并资产负债表",
                    "evidence": {**evidence, "source_line": row["source_line"], "member_origin": origin},
                })
        return candidates, resolutions

    @staticmethod
    def _member_lookup(members: list[dict[str, Any]]) -> list[tuple[str, dict[str, Any]]]:
        lookup: list[tuple[str, dict[str, Any]]] = []
        for member in members:
            if member.get("member_role") == "STATEMENT_ANCHOR":
                continue
            for alias in [member["display_name"], *(member.get("payload") or {}).get("aliases", [])]:
                token = normalize_text(alias)
                if token:
                    lookup.append((token, member))
        return lookup

    @staticmethod
    def _apply_page_regime_members(rows: list[dict[str, Any]], members: list[dict[str, Any]]) -> None:
        """Resolve duplicate label definitions only from page-level evidence.

        The FVTPL label exists in both legacy and current presentations.  The
        surrounding registered rows, not a company/year special case, decide
        which semantic member owns that physical row.
        """
        regime = _regime([row["raw_member_label"] for row in rows])
        if regime != "LEGACY_FINANCIAL_ASSET_CLASSIFICATION":
            return
        legacy_fvtpl = next((m for m in members if m["member_id"] == "legacy_fvtpl_assets"), None)
        if not legacy_fvtpl:
            return
        target = normalize_text(legacy_fvtpl["display_name"])
        for row in rows:
            if normalize_text(row["raw_member_label"]) == target:
                row["member"] = legacy_fvtpl
                row["member_table"] = legacy_fvtpl["member_id"]
                row["member_display_name"] = legacy_fvtpl["display_name"]

    @staticmethod
    def _find_parent(text: str, aliases: list[str]) -> dict[str, str] | None:
        for index, line in enumerate(str(text or "").splitlines()):
            compact = normalize_text(line).strip("：:")
            if compact in aliases:
                return {"label": line.strip(), "row_id": f"ROW_LINE_{index + 1}", "_line_index": index}
        return None

    @staticmethod
    def _parse_rows(text: str, aliases: list[tuple[str, dict[str, Any]]]) -> list[dict[str, Any]]:
        lines = [line.strip() for line in str(text or "").splitlines() if line.strip()]
        output: list[dict[str, Any]] = []
        seen: set[str] = set()
        for index, line in enumerate(lines):
            compact = normalize_text(line)
            matches = [(alias, member) for alias, member in aliases if alias and compact == alias]
            if not matches:
                continue
            # Exact duplicate labels are expected for legacy/new definitions.
            # Prefer the member whose declared regime matches the source label;
            # without that evidence retain registry order rather than guessing.
            _, member = sorted(matches, key=lambda item: (-len(item[0]), item[1].get("canonical_order", 999)))[0]
            raw_note = lines[index + 1] if index + 1 < len(lines) else ""
            if not re.fullmatch(r"\d{1,3}", raw_note):
                continue
            header = next((x for x in reversed(lines[:index]) if re.fullmatch(r"(?:附注|注)[一二三四五六七八九十百\d]+", normalize_text(x))), "附注")
            note = compose_note_reference(header, raw_note)
            key = f"{member['member_id']}|{note['note_reference_normalized']}"
            if key in seen:
                continue
            seen.add(key)
            amount = next((x for x in lines[index + 2:index + 7] if re.fullmatch(r"[-–—]?\d[\d,，.]*", x)), None)
            output.append({
                "member": member, "member_table": member["member_id"], "member_display_name": member["display_name"],
                "raw_member_label": line, "source_line": line, "source_row_id": f"ROW_LINE_{index + 1}",
                "statement_amount_raw": amount, "_line_index": index,
                **note,
            })
        return output
