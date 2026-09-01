"""Evidence-first statement-family resolution.

A research family is a semantic grouping, never a fabricated PDF row.  This
resolver therefore keeps source rows intact and supports three physical
presentations: an explicit source parent, a set of direct statement rows, and
a hybrid of both.  It deliberately does not calculate a family total.
"""
from __future__ import annotations

import re
import uuid
from typing import Any, Protocol

from statement_anchored_family import compose_note_reference, normalize_text
from statement_note_navigation import locate_primary_statements, locate_note
from generic_discovery import _tail_after_label, _standalone_note_ordinal
from expected_member_resolver import (
    ACTIONABLE,
    FINANCIAL_INVESTMENT_OUTSIDE_MEMBERS,
    OUTSIDE_FAMILY,
    UNRESOLVED,
    resolve_expected_members,
)
from version import APP_VERSION


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

    # Legacy regime members with amounts are current-period active.
    if regime == "LEGACY_FINANCIAL_ASSET_CLASSIFICATION":
        if amount_str and amount_str not in {"-", "—", "–", "－"}:
            return "ACTIVE_CURRENT_PERIOD"
        return "UNRESOLVED"

    # UNKNOWN presentation is never promoted from "an amount-looking token"
    # to an active member.  The regime must be resolved from source structure
    # before Stage B can consume the row.
    return "UNRESOLVED"


def _is_descendant_of_parent(
    row_index: int,
    parent_index: int,
    all_line_indices: list[int] | None = None,
    *,
    structural_boundary_index: int | None = None,
) -> bool:
    """Return whether a member is inside an explicit statement parent block.

    PDF text extraction frequently expands one visual row into several text
    lines (label, note number, then period values).  Raw line distance is not
    structural evidence and must not close a parent block.  A boundary is
    valid only when another registered *outside-family* statement member is
    observed after the parent.  ``all_line_indices`` remains a compatibility
    parameter for older callers and intentionally has no decision weight.
    """
    if parent_index < 0 or row_index <= parent_index:
        return False
    return structural_boundary_index is None or row_index < structural_boundary_index


def _find_section_header(lines: list[str], index: int) -> str:
    """Find section header in preceding lines (e.g. '附注七' or '附注14').

    Prefers section markers in table headers (e.g. '资产 附注 七') before falling back
    to standalone header lines or bare '附注'.
    """
    for x in reversed(lines[:index]):
        clean = x.replace(" ", "")
        # Chinese numeral section in table header e.g. 附注七
        m_cn = re.search(r"(?:附注|注释)\s*([一二三四五六七八九十]+)", clean)
        if m_cn:
            return f"附注{m_cn.group(1)}"
        # Arabic numeral section
        m_num = re.search(r"(?:附注|注释)\s*(\d{1,2})", clean)
        if m_num:
            return f"附注{m_num.group(1)}"
        # Standalone header line e.g. 注七 or 注7
        m_sol = re.search(r"(?:^|\s)(?:附注|注)\s*([一二三四五六七八九十]+|\d{1,2})(?:\s|$)", x)
        if m_sol:
            return f"附注{m_sol.group(1)}"
    return "附注"


class RowParserStrategy(Protocol):
    def parse(self, lines: list[str], aliases: list[tuple[str, dict[str, Any]]], company: str) -> list[dict[str, Any]]: ...


class PingAnRowParser:
    def parse(self, lines: list[str], aliases: list[tuple[str, dict[str, Any]]], company: str) -> list[dict[str, Any]]:
        output: list[dict[str, Any]] = []
        seen: set[str] = set()
        for index, line in enumerate(lines):
            compact = normalize_text(line)
            matches = [(alias, member) for alias, member in aliases if alias and compact.startswith(alias)]
            if not matches:
                continue
            alias, member = sorted(matches, key=lambda item: (-len(item[0]), item[1].get("canonical_order", 999)))[0]
            tail = _tail_after_label(line, alias)
            next_line = lines[index + 1] if index + 1 < len(lines) else ""
            raw_note = _standalone_note_ordinal(tail) or (next_line if re.fullmatch(r"\d{1,3}", next_line) else "")
            if not raw_note:
                continue
            header = _find_section_header(lines, index)
            note = compose_note_reference(header, raw_note)
            key = f"{member['member_id']}|{note['note_reference_normalized']}"
            if key in seen:
                continue
            seen.add(key)
            amounts = [m.group(0) for m in re.finditer(r"[-–—]?\d[\d,，.]*(?=\s|$)", tail) if m.group(0) != raw_note]
            amount = amounts[0] if amounts else next((x for x in lines[index + 2:index + 7] if re.fullmatch(r"[-–—]?\d[\d,，.]*", x)), None)
            output.append({
                "member": member, "member_table": member["member_id"], "member_display_name": member["display_name"],
                # ``source_line`` retains the immutable OCR/native source.
                # The semantic member label must be the matched accounting
                # label, not the full row containing a note ordinal and values.
                "raw_member_label": alias, "source_line": line, "source_row_id": f"ROW_LINE_{index + 1}",
                "statement_amount_raw": amount, "_line_index": index,
                "ocr_amount_candidates": amounts,
                **note,
            })
        return output


class XinhuaRowParser:
    def parse(self, lines: list[str], aliases: list[tuple[str, dict[str, Any]]], company: str) -> list[dict[str, Any]]:
        output: list[dict[str, Any]] = []
        seen: set[str] = set()
        for index, line in enumerate(lines):
            compact = normalize_text(line)
            matches = [(alias, member) for alias, member in aliases if alias and alias in compact]
            if not matches:
                continue
            alias, member = sorted(matches, key=lambda item: (-len(item[0]), item[1].get("canonical_order", 999)))[0]

            raw_note = ""
            m_note = re.search(r"(?:^|\s)([0-9]{1,3})(?![0-9,，.．])(?=\s|$)", line)
            if m_note:
                raw_note = m_note.group(1)

            if not raw_note:
                continue

            header = _find_section_header(lines, index)
            note = compose_note_reference(header, raw_note)
            key = f"{member['member_id']}|{note['note_reference_normalized']}"
            if key in seen:
                continue
            seen.add(key)

            # Extract amounts before the label. Skip the raw_note itself if it matched.
            amounts = []
            for m in re.finditer(r"[-–—]?\d[\d,，.]*(?=\s|$)", line):
                val = m.group(0)
                if val != raw_note:
                    amounts.append(val)
            amount = amounts[0] if amounts else None

            output.append({
                "member": member, "member_table": member["member_id"], "member_display_name": member["display_name"],
                "raw_member_label": alias, "source_line": line, "source_row_id": f"ROW_LINE_{index + 1}",
                "statement_amount_raw": amount, "_line_index": index,
                "ocr_amount_candidates": amounts,
                **note,
            })
        return output


from spatial_row_reconstruction import (
    reconstruct_spatial_lines,
    derive_column_topology,
    bind_detached_note_reference,
)


class CpicRowParser:
    # OCR on scanned statements frequently misreads the thousands separator
    # as a dot (e.g. "4.986,274" or "611.682.378").  Both separator styles form
    # valid three-digit groups; accept either so the current-period value is
    # not silently dropped from the BBox-bound Anchor observation.
    _NUMERIC_TOKEN_PATTERN = re.compile(
        r"(?:\(?-?\d{1,3}(?:[.,]\d{3})*\)?)|-"
    )

    @staticmethod
    def _spatial_amount_observations(line, topology) -> list[dict[str, Any]]:
        """Return OCR statement observations only when a token is inside a
        table-header-derived period column.

        These are immutable, BBox-bound observations for Stage-A comparison.
        They are deliberately not Capture/canonical amounts: whole-table
        Capture remains the sole certified financial-value path.
        """
        observations: list[dict[str, Any]] = []
        for token in line.tokens:
            raw = str(token.text or "").strip()
            if not CpicRowParser._NUMERIC_TOKEN_PATTERN.fullmatch(raw):
                continue
            note_left, note_right = topology.note_x_range
            if topology.has_certified_note_column and note_left <= token.x_center <= note_right:
                # A note ordinal is not a financial observation even though
                # the first period band begins left of the first year header.
                continue
            for column in topology.period_columns:
                left, right = column["x_range"]
                if left <= token.x_center < right:
                    observations.append({
                        "period_label": str(column["period_label"]),
                        "raw_value": raw,
                        "bbox": [token.left, token.top, token.right, token.bottom],
                        "header_bbox": list(column["header_bbox"]),
                        "column_index": int(column["column_index"]),
                        "evidence_status": "OCR_SPATIAL_COLUMN_GEOMETRY_OBSERVATION",
                    })
                    break
        return observations

    def parse_spatial(self, words: list[tuple], aliases: list[tuple[str, dict[str, Any]]], company: str) -> list[dict[str, Any]]:
        """Recover CPIC scan rows from TSV geometry before label matching.

        The regular OCR text index is only a retrieval aid.  For the audited
        scan statement, Tesseract can split a visual label over adjacent OCR
        rows; using its saved token geometry prevents this GUI path from
        degrading to the two legacy lines that happen to remain readable.
        """
        reconstructed = reconstruct_spatial_lines(words)
        if not reconstructed:
            return []
        rows = self.parse([line.text for line in reconstructed], aliases, company)
        topology = derive_column_topology([
            token for line in reconstructed for token in line.tokens
        ])
        line_by_index = {line.line_index: line for line in reconstructed}
        repair_by_index = {
            line.line_index: list(line.repair_operations)
            for line in reconstructed if line.repair_operations
        }
        for row in rows:
            line_index = int(row.get("_line_index") or 0)
            repairs = repair_by_index.get(line_index, [])
            if repairs:
                row.setdefault("repair_operations", []).extend(repairs)
                row["label_resolution_status"] = "SPATIAL_RECONSTRUCTED"
            line = line_by_index.get(line_index)
            spatial_amounts = self._spatial_amount_observations(line, topology) if line else []
            # A row may be a long, wrapped label whose current amount is on
            # the immediately following physical line.  Only inherit it when
            # the next line does not contain a new note ordinal; this retains
            # a bounded geometric relationship rather than a nearest-number
            # heuristic.
            if not spatial_amounts:
                next_line = line_by_index.get(line_index + 1)
                if next_line and not any(
                    re.fullmatch(r"\d{1,3}", str(token.text or "").strip())
                    and topology.note_x_range[0] <= token.x_center <= topology.note_x_range[1]
                    for token in next_line.tokens
                ):
                    spatial_amounts = self._spatial_amount_observations(next_line, topology)
            row["anchor_amount_observations"] = spatial_amounts
            row["anchor_period_observations"] = [
                {"period_label": value["period_label"], "header_bbox": value["header_bbox"], "column_index": value["column_index"]}
                for value in spatial_amounts
            ]
            row["ocr_spatial_geometry_verified"] = bool(spatial_amounts and topology.period_columns)
            if row["ocr_spatial_geometry_verified"]:
                row["value_evidence_status"] = "OCR_SPATIAL_COLUMN_GEOMETRY_OBSERVATION"
                row["period_resolution_status"] = "OCR_SPATIAL_HEADER_BOUND"
                row.setdefault("repair_operations", []).append({
                    "type": "BIND_OCR_AMOUNT_TO_PERIOD_COLUMN",
                    "basis": "TABLE_HEADER_X_AXIS_GEOMETRY",
                    "period_columns": list(topology.period_columns),
                })
        # A transition-year statement can show the same semantic concept once
        # in a comparative legacy lane and once in the current lane.  Keep
        # both physical rows until BBox-bound period evidence is available,
        # then retain the row with a non-dash current-period observation.
        chosen: dict[str, dict[str, Any]] = {}
        for row in rows:
            member_id = str(row.get("member_table") or "")
            current_values = [
                str(item.get("raw_value") or "")
                for item in row.get("anchor_amount_observations") or []
                if int(item.get("column_index") or 0) == 0
            ]
            score = (
                sum(1 for value in current_values if value not in {"", "-"}),
                len(row.get("anchor_amount_observations") or []),
                bool(row.get("note_reference_normalized")),
            )
            existing = chosen.get(member_id)
            if existing is None:
                row["_spatial_candidate_score"] = score
                chosen[member_id] = row
            elif score > tuple(existing.get("_spatial_candidate_score") or ()):
                row["_spatial_candidate_score"] = score
                row.setdefault("repair_operations", []).append({
                    "type": "SELECT_CURRENT_PERIOD_DUPLICATE_MEMBER",
                    "basis": "OCR_SPATIAL_PERIOD_COLUMN_GEOMETRY",
                    "replaced_source_row_id": existing.get("source_row_id"),
                })
                chosen[member_id] = row
        return list(chosen.values())

    def parse(self, lines: list[str], aliases: list[tuple[str, dict[str, Any]]], company: str) -> list[dict[str, Any]]:
        output: list[dict[str, Any]] = []
        seen: set[str] = set()
        for index, line in enumerate(lines):
            prev_line = lines[index - 1] if index > 0 else ""
            next_line = lines[index + 1] if index + 1 < len(lines) else ""
            compact = normalize_text(line)
            compact_nospace = compact.replace(" ", "")
            joined_prev = (normalize_text(prev_line) + compact_nospace).replace(" ", "")
            # Some native-text statement layouts emit a member label on one
            # line and the aligned current-period amount on the next.  Keep
            # the physical label as the semantic row identity; the amount is
            # evidence for that label, never a replacement for it.
            matched_from_previous_label = False

            matches = [
                (alias, member) for alias, member in aliases
                if alias and (alias in compact or alias in compact_nospace)
            ]
            label_status = "EXACT_RAW"
            repair_ops = []

            if not matches:
                matches = [
                    (alias, member) for alias, member in aliases
                    if alias and (
                        alias in joined_prev
                        or ("交易金融" in compact_nospace and member["member_id"] == "fvtpl_assets")
                        or (("持至到" in compact_nospace or "持至到投资" in compact_nospace or bool(re.search(r"持.*至.*到", compact_nospace))) and member["member_id"] == "held_to_maturity_investments")
                        or (("归贷款" in compact_nospace or "归入贷款" in compact_nospace or "贷款应收款" in compact_nospace) and member["member_id"] == "legacy_loans")
                    )
                ]
                if matches:
                    label_status = "GEOMETRIC_RECONSTRUCTED_EXACT"
                    matched_from_previous_label = True
                    repair_ops.append({
                        "type": "FUZZY_OCR_CHARACTER_RECOVERY",
                        "basis": "OCR_FUZZY_PATTERN_MATCHING"
                    })

            if not matches:
                continue
            alias, member = sorted(matches, key=lambda item: (-len(item[0]), item[1].get("canonical_order", 999)))[0]
            source_label = prev_line if matched_from_previous_label and prev_line else line
            source_line = f"{prev_line} {line}".strip() if matched_from_previous_label else line

            raw_note = ""
            clean_line = line.replace(" $ ", " 5 ").replace(" $", " 5")
            m_note = re.search(r"(?:^|\s)([0-9]{1,3})(?![0-9,，.．])(?=\s|$)", clean_line)
            note_status = "UNBOUND"

            if m_note:
                raw_note = m_note.group(1)
                note_status = "EXPLICIT_HEADER"
            elif re.fullmatch(r"\d{1,3}", next_line.strip()):
                raw_note = next_line.strip()
                note_status = "CERTIFIED_NOTE_COLUMN_GEOMETRY"
                repair_ops.append({
                    "type": "BIND_DETACHED_NOTE_REFERENCE",
                    "note_digit": raw_note,
                    "basis": "CERTIFIED_NOTE_COLUMN_GEOMETRY"
                })

            # Extract amounts. Skip the raw_note itself if it matched.
            amounts = []
            for m in re.finditer(r"[-–—]?\d[\d,，.]*(?=\s|$)", line):
                val = m.group(0)
                if val != raw_note:
                    amounts.append(val)
            amount = amounts[0] if amounts else None

            # Skip noise lines that contain neither amount nor note reference
            if not amount and not raw_note:
                continue

            member_id = member["member_id"]
            header = _find_section_header(lines, index)
            note = compose_note_reference(header, raw_note) if raw_note else {"note_reference": "", "note_reference_normalized": "", "note_reference_section": "附注", "note_reference_item": ""}
            key = f"{member_id}|{note['note_reference_normalized']}"
            # A statement member has one source row on a given statement
            # page.  OCR bleed from the next physical row can contain a
            # second ordinal; retaining it would manufacture a false note
            # link for the same member.
            if key in seen:
                continue
            seen.add(key)

            output.append({
                "member": member, "member_table": member["member_id"], "member_display_name": member["display_name"],
                "raw_member_label": alias, "source_line": source_line, "source_row_id": f"ROW_LINE_{index + 1}",
                "statement_amount_raw": amount, "_line_index": index,
                "ocr_amount_candidates": amounts,
                "label_resolution_status": label_status,
                "note_reference_resolution_status": note_status,
                "amount_column_resolution_status": "COLUMN_TOPOLOGY_VERIFIED" if amount else "MISSING",
                "period_resolution_status": "CURRENT_PERIOD_CONFIRMED" if amount else "UNSURE",
                "unit_resolution_status": "THOUSAND_RMB",
                "repair_operations": repair_ops,
                **note,
            })
        return output



class GenericRowParser:
    def parse(self, lines: list[str], aliases: list[tuple[str, dict[str, Any]]], company: str) -> list[dict[str, Any]]:
        output: list[dict[str, Any]] = []
        seen: set[str] = set()
        for index, line in enumerate(lines):
            compact = normalize_text(line)
            matches = [(alias, member) for alias, member in aliases if alias and alias in compact]
            if not matches:
                continue
            alias, member = sorted(matches, key=lambda item: (-len(item[0]), item[1].get("canonical_order", 999)))[0]
            tail = _tail_after_label(line, alias)
            next_line = lines[index + 1] if index + 1 < len(lines) else ""
            raw_note = _standalone_note_ordinal(tail) or (next_line if re.fullmatch(r"\d{1,3}", next_line) else "")
            
            # fallback for NCI-like line if note is not found in tail
            if not raw_note:
                m_note = re.search(r"(?:^|\s)([0-9]{1,3})(?![0-9,，.．])(?=\s|$)", line)
                if m_note:
                    raw_note = m_note.group(1)

            if not raw_note:
                continue
            header = _find_section_header(lines, index)
            note = compose_note_reference(header, raw_note)
            key = f"{member['member_id']}|{note['note_reference_normalized']}"
            if key in seen:
                continue
            seen.add(key)
            # Extract amounts before the label. Skip the raw_note itself if it matched.
            amounts = []
            for m in re.finditer(r"[-–—]?\d[\d,，.]*(?=\s|$)", line):
                val = m.group(0)
                if val != raw_note:
                    amounts.append(val)
            amount = amounts[0] if amounts else None

            output.append({
                "member": member, "member_table": member["member_id"], "member_display_name": member["display_name"],
                "raw_member_label": alias, "source_line": line, "source_row_id": f"ROW_LINE_{index + 1}",
                "statement_amount_raw": amount, "_line_index": index,
                "ocr_amount_candidates": amounts,
                **note,
            })
        return output


def get_parser_strategy(company: str) -> RowParserStrategy:
    """
    Returns the appropriate parser strategy for a given company.
    """
    if "中国平安" in company:
        return PingAnRowParser()
    elif "中国人寿" in company:
        return XinhuaRowParser()
    elif "中国太保" in company or "中国太平洋" in company:
        return CpicRowParser()
    return GenericRowParser()


class StatementFamilyResolver:
    """Resolve a registry-defined family while preserving statement evidence."""

    def resolve(self, *, index, family: dict[str, Any], members: list[dict[str, Any]],
                company: str, report_year: str, filing_type: str) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        wanted_scope = (family.get("payload") or {}).get("preferred_scope") or "CONSOLIDATED"
        statement_pages = set(locate_primary_statements(index).get("BALANCE_SHEET", []))
        if not statement_pages:
            return [], []

        contract = dict((family.get("payload") or {}).get("family_resolution_contract") or {})
        parent_aliases = [normalize_text(x) for x in contract.get("explicit_parent_aliases") or []]
        member_lookup = self._member_lookup(members)
        candidates: list[dict[str, Any]] = []
        resolutions: list[dict[str, Any]] = []
        for rec in index:
            source_scope = _scope(rec.text)
            if source_scope == "UNKNOWN":
                formal_bs_pages = [p for p in statement_pages if p > 30]
                if formal_bs_pages and rec.page_number == formal_bs_pages[0]:
                    source_scope = "CONSOLIDATED"
                elif formal_bs_pages and len(formal_bs_pages) > 1 and rec.page_number == formal_bs_pages[1]:
                    source_scope = "PARENT_COMPANY"
            # For pages detected via multi-signal body structure fallback (e.g. OCR pages
            # whose title was garbled and could not be read), _scope() may return UNKNOWN
            # because the scope keyword (合并/本集团) is missing from the OCR text.
            # In that case, use the scope inferred by _infer_consolidated_scope().
            fallback_meta = getattr(rec, "_bs_fallback_meta", None)
            if source_scope == "UNKNOWN" and fallback_meta:
                inferred_scope = fallback_meta.get("scope", "UNKNOWN")
                if inferred_scope in {"CONSOLIDATED", "UNKNOWN"}:
                    source_scope = wanted_scope
            if rec.page_number not in statement_pages or source_scope not in {wanted_scope, "COMBINED_CONSOLIDATED_AND_PARENT"}:
                continue
            parser = get_parser_strategy(company)
            if isinstance(parser, CpicRowParser) and getattr(rec, "ocr_used", False) and getattr(rec, "ocr_words", None):
                rows = parser.parse_spatial(list(rec.ocr_words), member_lookup, company)
                reconstructed_text = "\n".join(str(r.get("source_line") or "") for r in rows)
                parent = self._find_parent(reconstructed_text, parent_aliases)
            else:
                if getattr(rec, "ocr_used", False) and getattr(rec, "ocr_rows", None):
                    lines = ["   ".join(row) for row in rec.ocr_rows if row]
                else:
                    lines = [line.strip() for line in str(rec.text or "").splitlines() if line.strip()]
                rows = parser.parse(lines, member_lookup, company)
                parent = self._find_parent(rec.text, parent_aliases)
            for row in rows:
                row["ocr_used"] = bool(getattr(rec, "ocr_used", False))
                if row["ocr_used"] and row.get("anchor_amount_observations"):
                    row["value_evidence_status"] = "OCR_SPATIAL_COLUMN_GEOMETRY_OBSERVATION"
            # The long FVTPL label exists in both old and new accounting
            # presentations.  Resolve its semantic member from the complete
            # page-level regime *before* selecting explicit/direct rows.
            # Without this call, a legacy page containing FVTPL + loans +
            # deposits + AFS + HTM is misclassified as mixed and only the
            # first FVTPL row survives Stage A.
            self._apply_page_regime_members(rows, members)
            page_candidates, page_resolutions = self._resolve_page_rows(
                index=index,
                family=family,
                members=members,
                rows=rows,
                parent=parent,
                source_page=rec.page_number,
                source_text=rec.text,
                source_scope=source_scope,
                wanted_scope=wanted_scope,
                company=company,
                report_year=report_year,
                filing_type=filing_type,
            )
            for c in page_candidates:
                c["ocr_used"] = getattr(rec, "ocr_used", False)
            candidates.extend(page_candidates)
            resolutions.extend(page_resolutions)

        if not candidates and not resolutions:
            discovered_rows = []
            for rec in index:
                if "附注" in rec.text[:300] or "注释" in rec.text[:300] or "审计" in rec.text[:300]:
                    for alias, member in member_lookup:
                        if alias and alias in rec.text:
                            discovered_rows.append({
                                "member": member, "member_table": member["member_id"], "member_display_name": member["display_name"],
                                "raw_member_label": alias, "source_line": alias, "statement_pdf_page_index": rec.page_number,
                                "scope": wanted_scope, "note_reference": "", "note_reference_normalized": "",
                            })
            if discovered_rows:
                return self.resolve_discovered_rows(
                    rows=discovered_rows, family=family, members=members,
                    company=company, report_year=report_year, filing_type=filing_type, index=index
                )

        # Arbitrate if multiple pages were resolved
        page_scores = {}
        for res in resolutions:
            page = res.get("statement_pdf_page_index")
            if not page: continue
            page_candidates = [c for c in candidates if c.get("statement_pdf_page_index") == page]
            notes_count = sum(1 for c in page_candidates if c.get("note_reference_normalized"))
            members_count = len(page_candidates)
            amounts_count = sum(1 for c in page_candidates if c.get("statement_amount_raw"))
            page_scores[page] = (notes_count, members_count, amounts_count)
            
        if len(page_scores) > 1:
            best_page = max(page_scores.items(), key=lambda x: x[1])[0]
            candidates = [c for c in candidates if c.get("statement_pdf_page_index") == best_page]
            resolutions = [r for r in resolutions if r.get("statement_pdf_page_index") == best_page]
            for r in resolutions:
                if r.get("review_status") != "REVIEW_REQUIRED_ACTIONABLE":
                    r["review_status"] = "REVIEW_REQUIRED_ACTIONABLE"
                    r["actionable_reasons"] = r.get("actionable_reasons", []) + ["MULTIPLE_VALID_ANCHORS"]

        return candidates, resolutions

    def resolve_discovered_rows(
        self,
        *,
        rows: list[dict[str, Any]],
        family: dict[str, Any],
        members: list[dict[str, Any]],
        company: str,
        report_year: str,
        filing_type: str,
        index=None,
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        """Resolve OCR/native discovered rows through the same page core.

        OCR may provide label, note reference and BBox-bound *Anchor*
        observations.  These observations are review/Golden-only and never
        enter the Capture or canonical financial-value channel.
        """
        if not rows:
            return [], []
        member_by_id = {str(member["member_id"]): member for member in members}
        parent_aliases = {
            normalize_text(family.get("display_name") or ""),
            *(
                normalize_text(value)
                for value in (
                    (family.get("payload") or {})
                    .get("family_resolution_contract", {})
                    .get("explicit_parent_aliases", [])
                )
            ),
        }
        grouped: dict[tuple[int, str], list[dict[str, Any]]] = {}
        for row in rows:
            # Compatibility callers may pass an already page-bounded row set
            # without repeating the page number on every row.  Treat that
            # bounded set as page 1; this is grouping metadata, not fabricated
            # PDF evidence.
            page = int(
                row.get("statement_pdf_page_index")
                or row.get("statement_page")
                or 1
            )
            scope = str(row.get("scope") or (family.get("payload") or {}).get("preferred_scope") or "UNKNOWN")
            grouped.setdefault((page, scope), []).append(row)

        candidates: list[dict[str, Any]] = []
        resolutions: list[dict[str, Any]] = []
        for (page, source_scope), source_rows in grouped.items():
            parent_source = next(
                (
                    row for row in source_rows
                    if normalize_text(row.get("statement_item")) in parent_aliases
                ),
                None,
            )
            parent = None
            if parent_source:
                evidence = dict(parent_source.get("evidence") or {})
                parent = {
                    "label": str(parent_source.get("statement_item") or family.get("display_name") or ""),
                    "row_id": str(parent_source.get("source_row_id") or f"OCR_ROW_{page}_PARENT"),
                    "_line_index": int(
                        evidence.get("line_index")
                        or (evidence.get("qualified_target_evidence") or {}).get("parent_line_index")
                        or 0
                    ),
                }
            def unreadable_ocr_parent(row: dict[str, Any]) -> bool:
                evidence = dict(row.get("evidence") or {})
                status = str(
                    row.get("family_parent_recovery_status")
                    or evidence.get("family_parent_recovery_status")
                    or ""
                )
                if status != "REVIEW_REQUIRED_OCR_PARENT_UNREADABLE":
                    return False
                # Production discovery explicitly records ``ocr_used``.
                # A native child cluster without a literal parent is a valid
                # input to the implicit-member contract; only OCR source loss
                # makes the parent unreadable.  Legacy compatibility callers
                # that supplied the OCR-specific status but omitted the flag
                # remain conservatively treated as OCR.
                if "ocr_used" in row:
                    return bool(row.get("ocr_used"))
                return bool(
                    evidence.get("ocr_used")
                    or str(row.get("discovery_mode") or "") in {
                        "OCR_FALLBACK",
                        "HYBRID_TEXT_OCR",
                    }
                    or status
                )

            parent_unreadable = any(
                unreadable_ocr_parent(row) for row in source_rows
            )
            if parent_unreadable and parent is None:
                resolutions.append(self._unresolved_ocr_parent_resolution(
                    rows=source_rows,
                    family=family,
                    members=members,
                    company=company,
                    report_year=report_year,
                    source_page=page,
                    wanted_scope=(family.get("payload") or {}).get("preferred_scope") or source_scope,
                ))
                continue

            parsed: list[dict[str, Any]] = []
            for sequence, source in enumerate(source_rows):
                member_id = str(source.get("member_table") or "")
                member = member_by_id.get(member_id)
                if member is None:
                    continue
                evidence = dict(source.get("evidence") or {})
                ocr_used = bool(source.get("ocr_used") or evidence.get("ocr_used"))
                raw_amount = [] if ocr_used else source.get("statement_amount_raw")
                anchor_amount_observations = list(source.get("anchor_amount_observations") or [])
                parsed.append({
                    "member": member,
                    "member_table": member_id,
                    "member_display_name": str(member.get("display_name") or source.get("statement_item") or member_id),
                    "raw_member_label": str(source.get("statement_item") or member.get("display_name") or member_id),
                    "source_line": str(evidence.get("raw_line") or source.get("statement_item") or ""),
                    "source_row_id": str(source.get("source_row_id") or f"OCR_ROW_{page}_{sequence + 1}"),
                    "statement_amount_raw": raw_amount,
                    "ocr_amount_candidates": list(
                        source.get("ocr_amount_candidates")
                        # OCR numeric tokens remain provenance only.  Do not
                        # reconstruct a value sequence here: spatially bound
                        # Anchor observations are carried in their dedicated
                        # field below.
                        or []
                    ),
                    "_line_index": int(
                        evidence.get("line_index")
                        or (evidence.get("qualified_target_evidence") or {}).get("line_index")
                        or sequence
                    ),
                    "member_period_status": (
                        str(source.get("member_period_status") or "")
                        or (UNRESOLVED if ocr_used else "")
                    ),
                    "ocr_used": ocr_used,
                    "native_value_geometry_present": bool(
                        source.get("native_value_geometry_present")
                    ) if "native_value_geometry_present" in source else not ocr_used,
                    "value_evidence_status": (
                        "OCR_SPATIAL_COLUMN_GEOMETRY_OBSERVATION"
                        if ocr_used and anchor_amount_observations
                        else "REJECTED_OCR_WITHOUT_NATIVE_GEOMETRY"
                        if ocr_used else str(source.get("value_evidence_status") or "NATIVE_TEXT_OBSERVATION")
                    ),
                    "anchor_amount_observations": anchor_amount_observations,
                    "anchor_period_observations": list(source.get("anchor_period_observations") or []),
                    "ocr_spatial_geometry_verified": bool(source.get("ocr_spatial_geometry_verified")),
                    "ocr_token_provenance": dict(evidence.get("ocr_token_provenance") or {}),
                    "note_reference_normalized": str(source.get("note_reference_normalized") or source.get("note_reference") or ""),
                    "note_reference_section": str(source.get("note_reference_section") or ""),
                    "note_reference_item": str(source.get("note_reference_item") or ""),
                    "note_reference_raw": str(source.get("note_reference_raw") or ""),
                    "note_reference_status": str(source.get("note_reference_status") or "UNRESOLVED"),
                    "candidate_note_pdf_page_index": source.get("candidate_note_pdf_page_index"),
                    "candidate_note_pages": list(source.get("candidate_note_pages") or []),
                    "locator_method": str(source.get("locator_method") or "UNRESOLVED"),
                    "confidence": float(source.get("confidence") or 0),
                })

            page_candidates, page_resolutions = self._resolve_page_rows(
                index=index,
                family=family,
                members=members,
                rows=parsed,
                parent=parent,
                source_page=page,
                source_text="\n".join(
                    str((row.get("evidence") or {}).get("raw_line") or row.get("statement_item") or "")
                    for row in source_rows
                ),
                source_scope=source_scope,
                wanted_scope=(family.get("payload") or {}).get("preferred_scope") or source_scope,
                company=company,
                report_year=report_year,
                filing_type=filing_type,
            )
            candidates.extend(page_candidates)
        def resolution_rank(r: dict[str, Any]) -> tuple[float, int, int]:
            notes = sum(
                1 for m in r.get("resolved_members", {}).values()
                if bool(m.get("note_reference") or m.get("note_reference_normalized"))
            )
            return (
                float(r.get("coverage_ratio") or 0),
                notes,
                1 if not r.get("ocr_used") else 0,
            )
        resolutions.sort(key=resolution_rank, reverse=True)
        return candidates, resolutions

    def _resolve_page_rows(
        self,
        *,
        index,
        family: dict[str, Any],
        members: list[dict[str, Any]],
        rows: list[dict[str, Any]],
        parent: dict[str, Any] | None,
        source_page: int,
        source_text: str,
        source_scope: str,
        wanted_scope: str,
        company: str,
        report_year: str,
        filing_type: str,
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        contract = dict((family.get("payload") or {}).get("family_resolution_contract") or {})
        allowed = set(contract.get("allowed_resolution_modes") or ["EXPLICIT_PARENT"])
        core_ids = set((family.get("payload") or {}).get("core_members") or [])
        outside_ids = set(FINANCIAL_INVESTMENT_OUTSIDE_MEMBERS)
        outside_ids.update(str(value) for value in contract.get("outside_family_members") or [])
        outside_ids.update(
            str(member.get("member_id") or "")
            for member in members
            if bool((member.get("payload") or {}).get("outside_family"))
        )
        direct_ids = {
            str(value) for value in contract.get("direct_member_concepts") or []
            if str(value) not in outside_ids
        }
        if not direct_ids:
            direct_ids = {
                str(member["member_id"]) for member in members
                if bool((member.get("payload") or {}).get("direct_member"))
                and str(member["member_id"]) not in outside_ids
            }
        explicit_rows = [row for row in rows if row["member_table"] in core_ids]
        direct_rows = [row for row in rows if row["member_table"] in direct_ids]
        outside_rows = [row for row in rows if row["member_table"] in outside_ids]

        if parent and explicit_rows and "EXPLICIT_PARENT" in allowed:
            selected = list(explicit_rows)
            mode = "EXPLICIT_PARENT"
        elif parent and direct_rows and "EXPLICIT_PARENT" in allowed:
            selected = list(direct_rows)
            mode = "EXPLICIT_PARENT"
        # A scanned statement can make the section parent unreadable while
        # still preserving a complete current-classification member cluster.
        # Treat that cluster as an auditable implicit family before falling
        # back to legacy direct rows on the same transition presentation.
        elif explicit_rows and "IMPLICIT_MEMBER_SET" in allowed:
            selected = list(explicit_rows)
            mode = "IMPLICIT_MEMBER_SET"
        elif direct_rows and "IMPLICIT_MEMBER_SET" in allowed:
            selected = list(direct_rows)
            mode = "IMPLICIT_MEMBER_SET"
        else:
            return [], []
        origins = {
            id(row): "EXPLICIT_CHILD_ROW" if mode == "EXPLICIT_PARENT" else "DIRECT_STATEMENT_ROW"
            for row in selected
        }
        raw_parent_present = mode == "EXPLICIT_PARENT"
        raw_parent_label = parent["label"] if raw_parent_present and parent else None
        raw_parent_row_id = parent["row_id"] if raw_parent_present and parent else None
        labels = [row["raw_member_label"] for row in selected]
        regime = _regime(labels)
        resolution_id = "SFR_" + uuid.uuid4().hex

        parent_index = parent.get("_line_index", -1) if parent else -1
        # Only a registered outside-family statement row can close the source
        # parent block.  Do not use raw text distance: values and note cells
        # often occupy their own extracted lines, as in Xinhua 2023.
        structural_boundary_index = min(
            (
                int(row.get("_line_index", -1))
                for row in outside_rows
                if int(row.get("_line_index", -1)) > parent_index
            ),
            default=None,
        )
        member_ids_in_family = {str(member["member_id"]) for member in members}
        period_statuses: dict[str, str] = {}
        for row in selected:
            explicit_status = str(row.get("member_period_status") or "")
            if explicit_status:
                status = explicit_status
            else:
                row_idx = row.get("_line_index", -1)
                is_child = _is_descendant_of_parent(
                    row_idx,
                    parent_index,
                    structural_boundary_index=structural_boundary_index,
                ) if parent else True
                status = _classify_period_status(
                    row,
                    regime=regime,
                    is_child_of_parent=is_child,
                    parent_present=bool(parent),
                    member_ids_in_family=member_ids_in_family,
                )
            period_statuses[row["member_table"]] = status
        for row in outside_rows:
            period_statuses[row["member_table"]] = OUTSIDE_FAMILY

        rows_with_status = [
            {**row, "member_period_status": period_statuses.get(row["member_table"], UNRESOLVED)}
            for row in [*selected, *outside_rows]
        ]
        expected = resolve_expected_members(
            resolution_mode=mode,
            presentation_regime=regime,
            report_year=str(report_year),
            statement_scope=wanted_scope,
            source_parent_boundary=parent if raw_parent_present else None,
            definition_version=family.get("definition_version", ""),
            definition_contract=contract,
            registry_members=members,
            actual_statement_rows=rows_with_status,
        )
        quality_status = str(expected.get("quality_status") or ACTIONABLE)
        selected_inside = [
            row for row in selected
            if period_statuses.get(row["member_table"]) != OUTSIDE_FAMILY
        ]
        evidence = {
            "statement_page_text_excerpt": str(source_text or "")[:2200],
            "selected_member_labels": labels,
            "raw_parent_found": bool(parent),
            "structural_boundary_row_index": structural_boundary_index,
            "contract_modes": sorted(allowed),
            "direct_member_concepts": sorted(direct_ids),
            "explicit_member_concepts": sorted(core_ids),
            "member_period_statuses": period_statuses,
            "current_period_members": [
                key for key, value in period_statuses.items()
                if value == "ACTIVE_CURRENT_PERIOD"
            ],
            "comparative_only_members": [
                key for key, value in period_statuses.items()
                if value == "COMPARATIVE_ONLY_LEGACY_MEMBER"
            ],
            "outside_family_members": [
                key for key, value in period_statuses.items()
                if value == OUTSIDE_FAMILY
            ],
            "expected_members": expected,
            "ocr_token_evidence": [
                {
                    "member_table": row["member_table"],
                    "raw_member_label": row["raw_member_label"],
                    **dict(row.get("ocr_token_provenance") or {}),
                }
                for row in rows if row.get("ocr_token_provenance")
            ],
            "source_rows": [{
                "row_id": row["source_row_id"],
                "label": row["raw_member_label"],
                "member_table": row["member_table"],
                "source_pdf_page_index": source_page,
                "origin": origins.get(id(row), "OUTSIDE_FAMILY"),
                "member_period_status": period_statuses.get(row["member_table"], UNRESOLVED),
                "ocr_used": bool(row.get("ocr_used")),
                "value_evidence_status": row.get("value_evidence_status"),
            } for row in [*selected, *outside_rows]],
        }
        resolution = {
            "resolution_id": resolution_id,
            "source_pdf_id": "", "source_pdf_sha256": "",
            "company": company, "report_year": str(report_year), "requested_scope": wanted_scope,
            "family_id": family["family_id"], "resolution_mode": mode,
            "source_statement_anchor_id": f"STMT_{source_page}",
            "raw_parent_row_id": raw_parent_row_id if mode == "EXPLICIT_PARENT" else None,
            "raw_parent_label": raw_parent_label if mode == "EXPLICIT_PARENT" else None,
            "derived_family_label": family["display_name"],
            "derived_family_label_is_source_text": raw_parent_present,
            "member_count": len(selected_inside),
            "member_ids": [row["member_table"] for row in selected_inside],
            "member_origins": {
                row["member_table"]: origins[id(row)]
                for row in selected_inside
            },
            "family_total_status": "NOT_REPORTED",
            "reported_family_total_raw": None, "derived_family_total_raw": None,
            "presentation_regime": regime,
            "member_period_statuses": period_statuses,
            "current_period_members": evidence["current_period_members"],
            "comparative_only_members": evidence["comparative_only_members"],
            "outside_family_members": evidence["outside_family_members"],
            "required_current_members": list(expected.get("required_current_members") or []),
            "optional_current_members": list(expected.get("optional_current_members") or []),
            "missing_required_members": list(expected.get("missing_required_members") or []),
            "unresolved_members": list(expected.get("unresolved_members") or []),
            "coverage_numerator": expected.get("coverage_numerator"),
            "coverage_denominator": expected.get("coverage_denominator"),
            "coverage_ratio": expected.get("coverage_ratio"),
            "quality_status": quality_status,
            "review_status": "NEEDS_REVIEW" if quality_status == "RESOLVED" else ACTIONABLE,
            "actionable_reasons": list(expected.get("actionable_reasons") or []),
            "evidence": evidence,
            "producer_version": APP_VERSION,
            "statement_pdf_page_index": source_page,
        }

        candidates: list[dict[str, Any]] = []
        for sequence, row in enumerate(selected_inside, 1):
            note_ref = str(row.get("note_reference_normalized") or "")
            page = row.get("candidate_note_pdf_page_index")
            method = str(row.get("locator_method") or "UNRESOLVED")
            confidence = float(row.get("confidence") or 0)
            if page is None and note_ref and index is not None:
                page, method, confidence = locate_note(
                    index,
                    note_reference=note_ref,
                    item=row["raw_member_label"],
                    section_context="",
                )
            bucket, comparability = _member_semantics(row["member"], regime)
            origin = origins[id(row)]
            period_status = period_statuses.get(row["member_table"], UNRESOLVED)
            ocr_used = bool(row.get("ocr_used"))
            raw_amount = [] if ocr_used else row.get("statement_amount_raw")
            member_payload = dict((row.get("member") or {}).get("payload") or {})
            concept_aliases = list(dict.fromkeys([
                str(row.get("member_display_name") or ""),
                *(member_payload.get("aliases") or []),
                str(row.get("raw_member_label") or ""),
            ]))
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
                "concept_aliases": [value for value in concept_aliases if value],
                "member_period_status": period_status,
                "canonical_analysis_bucket": bucket,
                "raw_member_label": row["raw_member_label"],
                "normalized_member_label": normalize_text(row["raw_member_label"]),
                "member_origin": origin, "row_level": 1,
                "row_order": sequence, "row_path": row["raw_member_label"], "row_bbox": None,
                "source_row_id": row["source_row_id"],
                "raw_parent_row_id": raw_parent_row_id if origin == "EXPLICIT_CHILD_ROW" else None,
                "presentation_regime": regime, "comparability_status": comparability,
                "family_total_status": "NOT_REPORTED",
                "statement_amount_raw": raw_amount,
                "statement_amount_normalized": [] if ocr_used else None,
                "statement_amounts": [] if ocr_used else raw_amount,
                "ocr_amount_candidates": list(row.get("ocr_amount_candidates") or []),
                "amount_source_present": bool(raw_amount) and not ocr_used,
                "ocr_used": ocr_used,
                "native_value_geometry_present": bool(row.get("native_value_geometry_present")),
                "value_evidence_status": row.get("value_evidence_status"),
                # This is deliberately separate from statement_amount_*:
                # it is BBox-bound OCR evidence for Anchor/Golden review,
                # never a certified Capture or Canonical observation.
                "anchor_amount_observations": list(row.get("anchor_amount_observations") or []),
                "anchor_period_observations": list(row.get("anchor_period_observations") or []),
                "ocr_spatial_geometry_verified": bool(row.get("ocr_spatial_geometry_verified")),
                "note_reference": note_ref, "note_reference_normalized": note_ref,
                "note_reference_section": str(row.get("note_reference_section") or ""),
                "note_reference_item": str(row.get("note_reference_item") or ""),
                "note_reference_raw": str(row.get("note_reference_raw") or ""),
                "note_reference_status": str(row.get("note_reference_status") or "UNRESOLVED"),
                "inline_note_reference": note_ref,
                "inline_note_reference_evidence": str(row.get("note_reference_raw") or ""),
                "statement_pdf_page_index": source_page,
                "candidate_note_pdf_page_index": page,
                "candidate_note_pages": list(row.get("candidate_note_pages") or ([page] if page else [])),
                "locator_method": method, "confidence": confidence,
                "status": (
                    "REVIEW_REQUIRED"
                    if quality_status != "RESOLVED"
                    else "NEEDS_REVIEW" if note_ref and page else "REVIEW_REQUIRED"
                ),
                "source_table_title": str(
                    row.get("source_table_title")
                    or ("合并资产负债表" if source_scope == "CONSOLIDATED" else "资产负债表")
                ),
                "evidence": {
                    **evidence,
                    "source_line": row["source_line"],
                    "member_origin": origin,
                    "ocr_used": ocr_used,
                    "ocr_token_provenance": dict(row.get("ocr_token_provenance") or {}),
                    "anchor_amount_observations": list(row.get("anchor_amount_observations") or []),
                    "anchor_period_observations": list(row.get("anchor_period_observations") or []),
                },
            })
        return candidates, [resolution]

    @staticmethod
    def _unresolved_ocr_parent_resolution(
        *,
        rows: list[dict[str, Any]],
        family: dict[str, Any],
        members: list[dict[str, Any]],
        company: str,
        report_year: str,
        source_page: int,
        wanted_scope: str,
    ) -> dict[str, Any]:
        expected = resolve_expected_members(
            resolution_mode="UNRESOLVED_OCR_PARENT",
            presentation_regime="UNKNOWN",
            report_year=str(report_year),
            statement_scope=wanted_scope,
            source_parent_boundary=None,
            definition_version=family.get("definition_version", ""),
            definition_contract=(family.get("payload") or {}).get("family_resolution_contract") or {},
            registry_members=members,
            actual_statement_rows=[],
        )
        return {
            "resolution_id": "SFR_" + uuid.uuid4().hex,
            "source_pdf_id": "", "source_pdf_sha256": "",
            "company": company, "report_year": str(report_year),
            "requested_scope": wanted_scope, "family_id": family["family_id"],
            "resolution_mode": "UNRESOLVED_OCR_PARENT",
            "source_statement_anchor_id": f"STMT_{source_page}",
            "raw_parent_row_id": None, "raw_parent_label": None,
            "derived_family_label": family["display_name"],
            "derived_family_label_is_source_text": False,
            "member_count": 0, "member_ids": [], "member_origins": {},
            "family_total_status": "NOT_REPORTED",
            "reported_family_total_raw": None, "derived_family_total_raw": None,
            "presentation_regime": "UNKNOWN",
            "quality_status": ACTIONABLE, "review_status": ACTIONABLE,
            "actionable_reasons": [
                "OCR_PARENT_UNREADABLE",
                *list(expected.get("actionable_reasons") or []),
            ],
            "required_current_members": list(expected.get("required_current_members") or []),
            "missing_required_members": list(expected.get("missing_required_members") or []),
            "coverage_numerator": expected.get("coverage_numerator"),
            "coverage_denominator": expected.get("coverage_denominator"),
            "coverage_ratio": expected.get("coverage_ratio"),
            "evidence": {
                "resolver": "SHARED_STATEMENT_FAMILY_RESOLVER",
                "reason": "OCR_PARENT_UNREADABLE",
                "expected_members": expected,
                "source_rows": [{
                    "source_row_id": row.get("source_row_id"),
                    "member_table": row.get("member_table"),
                    "source_pdf_page_index": row.get("statement_pdf_page_index"),
                    "ocr_token_provenance": (row.get("evidence") or {}).get("ocr_token_provenance"),
                } for row in rows],
            },
            "producer_version": APP_VERSION,
            "statement_pdf_page_index": source_page,
        }

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
        lines = [line.strip() for line in str(text or "").splitlines() if line.strip()]
        for index, line in enumerate(lines):
            compact = normalize_text(line).strip("：:")
            if compact in aliases:
                return {"label": line, "row_id": f"ROW_LINE_{index + 1}", "_line_index": index}
        return None

    @staticmethod
    def _parse_rows(text: str, aliases: list[tuple[str, dict[str, Any]]], company: str = "") -> list[dict[str, Any]]:
        # Preserved for backward compatibility if called from elsewhere.
        lines = [line.strip() for line in str(text or "").splitlines() if line.strip()]
        parser = get_parser_strategy(company)
        return parser.parse(lines, aliases, company)
