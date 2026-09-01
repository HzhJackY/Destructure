"""Single-source Stage-A evidence for financial-statement anchors.

This module owns bounded page evidence only. It accepts native PDF words or
the existing Fast Index OCR words, never creates Capture values, and keeps the
source of every geometry decision explicit.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, replace
from math import ceil
from pathlib import Path
import re
from typing import Any, Iterable

import fitz

from financial_metric_pdf_resolver import file_sha256, parse_number
from financial_investment_period_contract import financial_member_contract_snapshot
from period_identity import normalize_period_token
from statement_anchored_family import normalize_text


EVIDENCE_SCHEMA = "STATEMENT_ANCHOR_EVIDENCE_V2"
_NUMBER = re.compile(r"^[\(（]?[-－—–]?\d[\d,，]*(?:\.\d+)?[\)）]?$|^(?:-|—|–|不适用)$")
_CN_DIGITS = {"零": 0, "一": 1, "二": 2, "三": 3, "四": 4, "五": 5,
              "六": 6, "七": 7, "八": 8, "九": 9}
_CN_UNITS = {"十": 10, "百": 100, "千": 1000}


@dataclass(frozen=True)
class ReportPeriodContext:
    report_year: int
    period_type: str = "ANNUAL"
    quarter: int | None = None
    as_of_date: str | None = None


@dataclass(frozen=True)
class PeriodColumnEvidence:
    period_label: str
    period_year: int | None
    period_role: str
    bbox: dict[str, float]
    period_identity: str | None = None
    period_precision: str = "UNRESOLVED"
    period_quarter: int | None = None
    period_half: int | None = None
    column_index: int = 0
    x_range: tuple[float, float] = (0.0, 0.0)


@dataclass(frozen=True)
class MemberRowEvidence:
    member_table: str
    raw_label: str
    label_bbox: dict[str, float]
    source_row_id: str
    parent_relation: str
    note_reference: str | None
    note_reference_status: str
    amount_cells: tuple[dict[str, Any], ...]
    presentation_regime: str = "UNKNOWN"
    member_period_status: str = "UNRESOLVED"
    binding_row_bbox: dict[str, float] | None = None
    source_line_index: int | None = None
    identity_source: str = "NATIVE_PDF_WORDS"
    value_source: str = "NATIVE_PDF_WORDS"
    alignment_evidence: dict[str, Any] | None = None
    presentation_member_id: str | None = None
    canonical_analysis_bucket: str | None = None
    comparability_status: str = "UNRESOLVED"
    analysis_bridge_groups: tuple[dict[str, Any], ...] = ()
    period_applicability: tuple[dict[str, Any], ...] = ()


@dataclass(frozen=True)
class StatementAnchorEvidenceV2:
    schema_version: str
    pdf_sha256: str
    physical_page_group: tuple[int, ...]
    statement_type: str
    source_statement_scope: str
    scope_evidence_source: str
    scope_confidence: float
    scope_conflict_reason: str | None
    title: str
    title_bbox: dict[str, float] | None
    unit: str | None
    period_columns: tuple[PeriodColumnEvidence, ...]
    note_column_bbox: dict[str, float] | None
    members: tuple[MemberRowEvidence, ...]
    parent_identity: str
    native_value_geometry_present: bool
    geometry_evidence_mode: str = "NATIVE"
    geometry_source: str = "NATIVE_PDF_WORDS"
    period_geometry_verified: bool = False
    note_geometry_verified: bool = False
    row_binding_verified: bool = False
    value_geometry_verified: bool = False
    ocr_spatial_geometry_verified: bool = False
    topology_hypotheses: tuple[dict[str, Any], ...] = ()
    selected_topology_id: str | None = None
    native_ocr_conflicts: tuple[dict[str, Any], ...] = ()
    recovery_stage: str = "NATIVE_DISCOVERY"
    page_cache_identity: dict[str, Any] | None = None
    presentation_regime: str = "UNKNOWN"
    member_contract_snapshot: dict[str, Any] | None = None
    required_current_members: tuple[str, ...] = ()
    optional_current_members: tuple[str, ...] = ()
    historical_variant_members: tuple[str, ...] = ()
    comparative_only_members: tuple[str, ...] = ()
    member_period_matrix: tuple[dict[str, Any], ...] = ()
    required_current_member_status_valid: bool = False

    def payload(self) -> dict[str, Any]:
        return asdict(self)


Word = tuple[float, float, float, float, str]


def _row_observation_key(row: Any) -> str:
    """Return the physical row key used for note/value binding.

    ``member_table`` is a presentation concept and can legitimately occur on
    more than one physical row.  It must never be used as a cell join key.
    """
    if isinstance(row, MemberRowEvidence):
        return str(row.source_row_id or "")
    return str(
        row.get("source_row_id")
        or f"ROW_LINE_{row.get('line_index', 'UNRESOLVED')}"
    )


def _bbox(words: Iterable[Word]) -> dict[str, float] | None:
    values = list(words)
    if not values:
        return None
    return {"x0": min(x0 for x0, _, _, _, _ in values), "y0": min(y0 for _, y0, _, _, _ in values),
            "x1": max(x1 for _, _, x1, _, _ in values), "y1": max(y1 for _, _, _, y1, _ in values)}


def _median(values: list[float], default: float) -> float:
    usable = sorted(value for value in values if value > 0)
    return usable[len(usable) // 2] if usable else default


def _clean_token(value: Any) -> str:
    return str(value or "").strip().replace("”", "").replace("“", "")


def _lines_from_words(words: Iterable[tuple]) -> list[list[Word]]:
    tokens = [(float(word[0]), float(word[1]), float(word[2]), float(word[3]), _clean_token(word[4]))
              for word in words if len(word) >= 5 and _clean_token(word[4])]
    tokens.sort(key=lambda item: ((item[1] + item[3]) / 2, item[0]))
    tolerance = max(5.0, _median([item[3] - item[1] for item in tokens], 12.0) * 0.65)
    rows: list[list[Word]] = []
    for token in tokens:
        center = (token[1] + token[3]) / 2
        if rows:
            previous_center = sum((item[1] + item[3]) / 2 for item in rows[-1]) / len(rows[-1])
            if abs(center - previous_center) <= tolerance:
                rows[-1].append(token)
                continue
        rows.append([token])
    return [sorted(row, key=lambda item: item[0]) for row in rows]


def _line_text(words: Iterable[Word]) -> str:
    return "".join(token for *_, token in words)


def _compact(value: Any) -> str:
    return re.sub(r"\s+", "", str(value or "")).replace("（", "(").replace("）", ")")


def scope_from_statement_text(text: str, *, previous_statement_scope: str | None = None,
                              directory_scope: str | None = None) -> tuple[str, str, float, str | None]:
    """Resolve scope in contractual order; never infer it from page order."""
    head = normalize_text("\n".join(str(text or "").splitlines()[:36]))
    has_statement = any(
        k in head for k in [
            "资产负债表", "資產負債表", "财务状况表", "財務狀況表",
            "statementoffinancialposition", "balancesheet",
        ]
    )
    if has_statement and any(k in head for k in ["合并及公司", "合併及公司", "合并和公司", "合併和公司"]):
        return "COMBINED_CONSOLIDATED_AND_PARENT", "FORMAL_TITLE", 1.0, None
    if has_statement and any(k in head for k in ["母公司", "本公司", "公司资产负债表", "公司資產負債表", "公司財務狀況表", "companystatementoffinancialposition"]):
        return "PARENT_COMPANY", "FORMAL_TITLE", 1.0, None
    if has_statement and any(k in head for k in ["合并", "合併", "集团", "集團", "consolidated", "group"]):
        return "CONSOLIDATED", "FORMAL_TITLE", 1.0, None
    if has_statement and any(k in head for k in ["续表", "續表", "续", "續", "continued"]) and previous_statement_scope:
        return previous_statement_scope, "STATEMENT_CONTINUATION", 0.85, None
    if directory_scope in {"CONSOLIDATED", "PARENT_COMPANY", "COMBINED_CONSOLIDATED_AND_PARENT"}:
        return directory_scope, "DIRECTORY_OR_SECTION_EVIDENCE", 0.60, None
    return "UNKNOWN", "UNKNOWN", 0.0, "NO_FORMAL_SCOPE_EVIDENCE"


def _period_role(parsed: dict[str, Any], context: ReportPeriodContext) -> str:
    year = parsed.get("period_year")
    if year != context.report_year:
        return "COMPARATIVE" if isinstance(year, int) and year < context.report_year else "RESTATED_OR_OTHER"
    kind = context.period_type.upper()
    if kind == "QUARTERLY":
        if parsed.get("period_quarter") == context.quarter:
            return "CURRENT"
        return "CURRENT_YEAR_AMBIGUOUS" if parsed.get("period_precision") == "YEAR" else "RESTATED_OR_OTHER"
    if kind in {"INTERIM", "HALF_YEAR"}:
        if parsed.get("period_half") == 1:
            return "CURRENT"
        return "CURRENT_YEAR_AMBIGUOUS" if parsed.get("period_precision") == "YEAR" else "RESTATED_OR_OTHER"
    return "CURRENT"


def _period_candidates(lines: list[list[Word]], context: ReportPeriodContext, page_width: float) -> list[PeriodColumnEvidence]:
    rows: list[list[tuple[dict[str, Any], list[Word]]]] = []
    for row in lines[:48]:
        hits: list[tuple[dict[str, Any], list[Word]]] = []
        median_height = _median([word[3] - word[1] for word in row], 12.0)
        for start in range(len(row)):
            selected: list[Word] = []
            for end in range(start, min(len(row), start + 7)):
                word = row[end]
                if selected and word[0] - selected[-1][2] > max(16.0, median_height * 2.0):
                    break
                selected.append(word)
                parsed = normalize_period_token("".join(item[4] for item in selected))
                if parsed and parsed.get("period_identity") and parsed.get("period_year"):
                    hits.append((parsed, list(selected)))
        chosen: list[tuple[dict[str, Any], list[Word]]] = []
        for parsed, words in sorted(hits, key=lambda item: (-len(item[1]), item[1][0][0])):
            if any(set(words) <= set(old_words) for _, old_words in chosen):
                continue
            chosen.append((parsed, words))
        if len(chosen) >= 2:
            rows.append(chosen)
    if not rows:
        return []
    selected = max(rows, key=lambda row: (len(row), sum(item[1][0][1] for item in row) / len(row)))
    raw_columns: list[tuple[dict[str, Any], dict[str, float]]] = []
    for parsed, words in sorted(selected, key=lambda item: item[1][0][0]):
        box = _bbox(words)
        if not box:
            continue
        center = (box["x0"] + box["x1"]) / 2
        if any(abs(center - (old_box["x0"] + old_box["x1"]) / 2) < 8 for _, old_box in raw_columns):
            continue
        raw_columns.append((parsed, box))
    output: list[PeriodColumnEvidence] = []
    for index, (parsed, box) in enumerate(raw_columns):
        right = raw_columns[index + 1][1]["x0"] if index + 1 < len(raw_columns) else page_width + 1.0
        output.append(PeriodColumnEvidence(
            period_label=str(parsed.get("period_label") or parsed.get("source_period_label") or ""),
            period_year=parsed.get("period_year"), period_role=_period_role(parsed, context), bbox=box,
            period_identity=parsed.get("period_identity"), period_precision=str(parsed.get("period_precision") or "UNRESOLVED"),
            period_quarter=parsed.get("period_quarter"), period_half=parsed.get("period_half"),
            column_index=index, x_range=(box["x0"], right)))
    return output


def _cn_number(raw: str) -> int | None:
    if raw.isdigit():
        return int(raw)
    total = 0
    current = 0
    for char in raw:
        if char in _CN_DIGITS:
            current = _CN_DIGITS[char]
        elif char in _CN_UNITS:
            total += max(1, current) * _CN_UNITS[char]
            current = 0
        else:
            return None
    return total + current if total + current else None


def _note_reference(raw: str, ordinal_cap: int) -> tuple[str | None, list[int], str | None]:
    compact = _compact(raw)
    if not compact or not re.fullmatch(r"(?:附注|注释|注)?[一二三四五六七八九十百千\d、,，.\-()]+", compact):
        return None, [], "NOTE_GRAMMAR_INVALID"
    values = [_cn_number(item) for item in re.findall(r"\d+|[一二三四五六七八九十百千]+", compact)]
    if not values or any(value is None for value in values):
        return None, [], "NOTE_GRAMMAR_INVALID"
    normalized = [int(value) for value in values if value is not None]
    if any(value < 1 or value > ordinal_cap for value in normalized):
        return None, normalized, "NOTE_ORDINAL_OVER_CAP"
    return compact, normalized, None


def _sequence_shape(values: list[int]) -> str:
    if len(values) < 2:
        return "INSUFFICIENT"
    if len(set(values)) == 1:
        return "STABLE_REPEAT"
    if all(right == left + 1 for left, right in zip(values, values[1:])):
        return "CONSECUTIVE_ASCENDING"
    if all(right >= left for left, right in zip(values, values[1:])):
        return "NON_DECREASING_WITH_GAPS"
    return "NON_MONOTONIC"


def _note_header_candidates(lines: list[list[Word]], periods: list[PeriodColumnEvidence], median_height: float) -> list[tuple[str, dict[str, float]]]:
    if not periods:
        return []
    header_y = sum(column.bbox["y0"] for column in periods) / len(periods)
    output: list[tuple[str, dict[str, float]]] = []
    for row in lines[:48]:
        row_y = sum((word[1] + word[3]) / 2 for word in row) / len(row)
        # 期间标签与“附注”常分属两层表头。PDF/OCR 的行距会显著放大，
        # 因此这里保留足以覆盖双层表头的垂直窗口；最终仍必须由成员行
        # 的同 lane 编号、期间列排他和格式规则共同认证，不能凭标题入选。
        if abs(row_y - header_y) > max(180.0, median_height * 12.0):
            continue
        for start in range(len(row)):
            parts: list[Word] = []
            for end in range(start, min(len(row), start + 4)):
                word = row[end]
                if parts and word[0] - parts[-1][2] > max(14.0, median_height * 2.0):
                    break
                parts.append(word)
                compact = _compact("".join(item[4] for item in parts))
                if re.fullmatch(r"(?:附注|注释|注)(?:[一二三四五六七八九十百千\d]+)?", compact):
                    box = _bbox(parts)
                    if box:
                        output.append((compact, box))
    unique: list[tuple[str, dict[str, float]]] = []
    for label, box in output:
        if not any(abs(box["x0"] - old[1]["x0"]) < 5 and abs(box["y0"] - old[1]["y0"]) < 5 for old in unique):
            unique.append((label, box))
    return unique


def _scalar_number(raw: str) -> float | int | None:
    parsed = parse_number(raw)
    return parsed[0] if isinstance(parsed, tuple) and len(parsed) >= 3 and parsed[2] else (parsed if not isinstance(parsed, tuple) else None)


def _period_value_status(raw: str, value: float | int | None) -> str:
    compact = _compact(raw)
    if compact == "不适用":
        return "NOT_APPLICABLE"
    if compact in {"-", "—", "–", "－"}:
        return "LEGAL_DASH"
    return "VALUE_PRESENT" if value is not None else "UNRESOLVED"


def _member_period_status(cells: list[dict[str, Any]], *, member_table: str, contract: dict[str, Any]) -> str:
    current = [cell for cell in cells if cell.get("period_role") == "CURRENT"]
    comparative = [cell for cell in cells if cell.get("period_role") != "CURRENT"]
    current_statuses = {str(cell.get("period_value_status") or "") for cell in current}
    comparative_statuses = {str(cell.get("period_value_status") or "") for cell in comparative}
    if "VALUE_PRESENT" in current_statuses:
        return "ACTIVE_CURRENT_PERIOD"
    if (
        member_table in set(contract.get("legacy_members") or [])
        and current_statuses <= {"NOT_APPLICABLE", "LEGAL_DASH"}
        and comparative_statuses & {"VALUE_PRESENT", "LEGAL_DASH"}
    ):
        return "COMPARATIVE_ONLY_LEGACY_MEMBER"
    if (
        ("NOT_APPLICABLE" in current_statuses or not current)
        and comparative_statuses & {"VALUE_PRESENT", "LEGAL_DASH"}
    ):
        return (
            "COMPARATIVE_ONLY_LEGACY_MEMBER"
            if member_table in set(contract.get("legacy_members") or [])
            else "ACTIVE_COMPARATIVE_PERIOD"
        )
    if "LEGAL_DASH" in current_statuses:
        return "ACTIVE_CURRENT_PERIOD"
    if current_statuses == {"NOT_APPLICABLE"}:
        return "INACTIVE_CURRENT_PERIOD"
    return "UNRESOLVED"


def _resolve_ambiguous_member(
    matches: list[tuple[str, str]], cells: list[dict[str, Any]], contract: dict[str, Any],
    *, observed_members: set[str] | None = None,
) -> str:
    """Resolve equal-label cross-regime identities using period affiliation.

    Alias length still removes substring matches such as ``债权投资`` inside
    ``其他债权投资``.  Only equal longest aliases remain ambiguous.  In a
    transition filing, an active current value belongs to the current lane;
    a row that is unavailable in the current column but active in a comparative
    column belongs to the historical lane.  This prevents presentation regime
    alone from deciding the identity of the formal long FVTPL label.
    """
    longest = max((len(alias) for _, alias in matches), default=0)
    candidates = list(dict.fromkeys(member for member, alias in matches if len(alias) == longest))
    if len(candidates) == 1:
        return candidates[0]
    current_statuses = {
        str(cell.get("period_value_status") or "")
        for cell in cells if cell.get("period_role") == "CURRENT"
    }
    comparative_statuses = {
        str(cell.get("period_value_status") or "")
        for cell in cells if cell.get("period_role") != "CURRENT"
    }
    current_lane = list(dict.fromkeys([
        *(contract.get("required_current_members") or []),
        *(contract.get("optional_current_members") or []),
    ]))
    historical_lane = list(dict.fromkeys([
        *(contract.get("comparative_only_members") or []),
        *(contract.get("historical_variant_members") or []),
        *(contract.get("legacy_members") or []),
    ]))
    if current_statuses & {"VALUE_PRESENT", "LEGAL_DASH"}:
        preferred = next((member for member in current_lane if member in candidates), None)
        if preferred:
            return preferred
    if (
        (not current_statuses or current_statuses == {"NOT_APPLICABLE"})
        and comparative_statuses & {"VALUE_PRESENT", "LEGAL_DASH"}
    ):
        preferred = next((member for member in historical_lane if member in candidates), None)
        if preferred:
            return preferred
    # Native pages with missing numeric geometry still expose the sequence of
    # labels.  In a mixed transition presentation, a preceding unambiguous
    # "交易性金融资产" has already consumed current FVTPL; the subsequent long
    # equal-alias label must keep the unused historical identity for Hybrid
    # OCR binding rather than being silently deduplicated into current FVTPL.
    if not cells and observed_members:
        unseen = next((member for member in candidates if member not in observed_members), None)
        if unseen:
            return unseen
    return next((member for member in current_lane if member in candidates), candidates[0])


def _member_rows(
    lines: list[list[Word]], *, page: int, periods: list[PeriodColumnEvidence],
    parent_aliases: Iterable[str], member_contract: dict[str, Any],
    prefer_unseen_ambiguous: bool = False,
) -> list[dict[str, Any]]:
    aliases = {
        str(spec.get("member_table") or ""): tuple(
            normalize_text(item) for item in spec.get("aliases") or [] if normalize_text(item)
        )
        for spec in member_contract.get("members") or []
        if spec.get("member_table")
    }
    regimes = {
        str(spec.get("member_table") or ""): str(spec.get("presentation_regime") or "UNKNOWN")
        for spec in member_contract.get("members") or []
    }
    specs = {
        str(spec.get("member_table") or ""): dict(spec)
        for spec in member_contract.get("members") or []
        if spec.get("member_table")
    }
    parent_terms = {normalize_text(value) for value in parent_aliases if value}
    first_amount_x = min((column.x_range[0] for column in periods), default=float("inf"))
    parent_seen = False
    output: list[dict[str, Any]] = []
    for line_index, row in enumerate(lines):
        text = _line_text(row)
        normalized = normalize_text(text)
        if any(term and term in normalized for term in parent_terms):
            parent_seen = True
        matches = [(member, alias) for member, values in aliases.items() for alias in values if alias and alias in normalized]
        label_source_rows = [row]
        # Long accounting labels are frequently wrapped immediately before the
        # line that owns the note/value cells.  Reconstruct only that bounded
        # two-line label case: the prior fragment must contain no numeric cell,
        # while the current line must contain a numeric/NA token.  This mirrors
        # the existing family resolver without merging unrelated data rows.
        if not matches and line_index > 0:
            previous = lines[line_index - 1]
            previous_has_value = any(_NUMBER.fullmatch(word[4].replace("，", ",")) for word in previous)
            current_has_value = any(_NUMBER.fullmatch(word[4].replace("，", ",")) for word in row)
            if not previous_has_value and current_has_value:
                combined = normalize_text(_line_text(previous) + text)
                matches = [
                    (member, alias) for member, values in aliases.items()
                    for alias in values if alias and alias in combined
                ]
                if matches:
                    label_source_rows = [previous, row]
        if not matches:
            continue
        label_words = [word for source_row in label_source_rows for word in source_row if word[0] < first_amount_x]
        cells: list[dict[str, Any]] = []
        for word in row:
            raw = word[4]
            if not _NUMBER.fullmatch(raw.replace("，", ",")):
                continue
            value = _scalar_number(raw)
            center = (word[0] + word[2]) / 2
            column = next((item for item in periods if item.x_range[0] <= center < item.x_range[1]), None)
            if column:
                cells.append({"period_label": column.period_label, "period_year": column.period_year, "period_role": column.period_role,
                              "period_identity": column.period_identity, "raw": raw, "value": value, "bbox": _bbox([word]),
                              "period_value_status": _period_value_status(raw, value),
                              "column_index": column.column_index, "line_index": line_index})
        longest = max((len(alias) for _, alias in matches), default=0)
        member_candidates = list(dict.fromkeys(
            member_id for member_id, alias in matches if len(alias) == longest
        ))
        member = _resolve_ambiguous_member(
            matches, cells, member_contract,
            observed_members={str(item["member_table"]) for item in output} if prefer_unseen_ambiguous else None,
        )
        status = _member_period_status(cells, member_table=member, contract=member_contract)
        spec = specs.get(member) or {}
        period_applicability = [{
            "period_identity": cell.get("period_identity"),
            "period_role": cell.get("period_role"),
            "status": cell.get("period_value_status"),
            "applicable": cell.get("period_value_status") != "NOT_APPLICABLE",
        } for cell in cells]
        output.append({"member_table": member, "raw_label": _line_text(label_words).strip() or text.strip(),
                       "presentation_member_id": str(spec.get("presentation_member_id") or member),
                       "label_bbox": _bbox(label_words) or _bbox(row) or {}, "source_row_id": f"V2_P{page}_L{line_index}",
                       "parent_relation": "EXPLICIT_CHILD_OF_PARENT" if parent_seen else "IMPLICIT_MEMBER_SET",
                       "amount_cells": cells, "line_index": line_index, "row": row,
                       "presentation_regime": regimes.get(member, "UNKNOWN"),
                       "member_period_status": status,
                       "canonical_analysis_bucket": str(spec.get("canonical_analysis_bucket") or member),
                       "comparability_status": str(spec.get("comparability_status") or "UNRESOLVED"),
                       "analysis_bridge_groups": [dict(item) for item in spec.get("analysis_bridge_groups") or []],
                       "period_applicability": period_applicability,
                       "member_candidates": member_candidates,
                       "alias_ambiguous": len(member_candidates) > 1})
    current_lane = set(member_contract.get("required_current_members") or []) | set(
        member_contract.get("optional_current_members") or []
    )
    legacy_lane = set(member_contract.get("legacy_members") or []) | set(
        member_contract.get("historical_variant_members") or []
    )
    explicitly_active_current = {
        item["member_table"]
        for item in output
        if not item.get("alias_ambiguous")
        and any(
            cell.get("period_role") == "CURRENT"
            and cell.get("period_value_status") == "VALUE_PRESENT"
            for cell in item["amount_cells"]
        )
    }
    for item in output:
        candidates = list(item.get("member_candidates") or [])
        if len(candidates) <= 1:
            continue
        current_candidates = [member_id for member_id in candidates if member_id in current_lane]
        historical_candidates = [member_id for member_id in candidates if member_id in legacy_lane]
        current_statuses = {
            str(cell.get("period_value_status") or "")
            for cell in item["amount_cells"] if cell.get("period_role") == "CURRENT"
        }
        comparative_statuses = {
            str(cell.get("period_value_status") or "")
            for cell in item["amount_cells"] if cell.get("period_role") != "CURRENT"
        }
        if (
            historical_candidates
            and any(member_id in explicitly_active_current for member_id in current_candidates)
            and "VALUE_PRESENT" not in current_statuses
            and comparative_statuses & {"VALUE_PRESENT", "LEGAL_DASH"}
        ):
            member = historical_candidates[0]
            spec = specs.get(member) or {}
            item.update({
                "member_table": member,
                "presentation_member_id": str(spec.get("presentation_member_id") or member),
                "presentation_regime": regimes.get(member, "UNKNOWN"),
                "member_period_status": _member_period_status(
                    item["amount_cells"], member_table=member, contract=member_contract,
                ),
                "canonical_analysis_bucket": str(spec.get("canonical_analysis_bucket") or member),
                "comparability_status": str(spec.get("comparability_status") or "UNRESOLVED"),
                "analysis_bridge_groups": [dict(value) for value in spec.get("analysis_bridge_groups") or []],
            })
    # Preserve every physical occurrence.  Current-vs-historical selection is
    # a period-aware projection performed after note/value cells are bound to
    # their source row; collapsing here can manufacture cross-row tuples.
    return output


def _select_note_topology(member_rows: list[dict[str, Any]], headers: list[tuple[str, dict[str, float]]], periods: list[PeriodColumnEvidence], page_count: int, median_height: float) -> tuple[dict[str, Any] | None, list[dict[str, Any]]]:
    ordinal_cap = min(999, max(99, int(ceil(page_count / 2))))
    hypotheses: list[dict[str, Any]] = []
    for ordinal, (header, box) in enumerate(headers):
        pad = max(12.0, median_height * 1.25)
        lane = {"x0": max(0.0, box["x0"] - pad), "x1": box["x1"] + pad, "y0": box["y0"], "y1": box["y1"]}
        # 用实际表头而非容差扩展后的 lane 判断列冲突。扩展仅用于吸收
        # OCR/BBox 浮动；若拿它判断，很容易把紧邻的金额列误判为重叠。
        overlaps = any(not (box["x1"] <= col.bbox["x0"] or box["x0"] >= col.bbox["x1"]) for col in periods)
        observations: dict[str, dict[str, Any]] = {}
        over_cap = False
        for member in member_rows:
            tokens = [word for word in member["row"] if lane["x0"] <= (word[0] + word[2]) / 2 <= lane["x1"]]
            reference, numbers, error = _note_reference("".join(word[4] for word in tokens), ordinal_cap)
            over_cap = over_cap or error == "NOTE_ORDINAL_OVER_CAP"
            if reference:
                row_key = _row_observation_key(member)
                observations[row_key] = {
                    "reference": reference, "numbers": numbers,
                    "bbox": _bbox(tokens),
                    "source_row_id": row_key,
                    "member_table": member.get("member_table"),
                }
        values = [entry["numbers"][-1] for entry in observations.values() if entry["numbers"]]
        shape = _sequence_shape(values)
        accepted = len(observations) >= 2 and not over_cap and not overlaps and shape != "NON_MONOTONIC"
        hypotheses.append({"topology_id": f"NOTE_TOPOLOGY_{ordinal + 1}", "header": header, "bbox": lane, "ordinal_cap": ordinal_cap,
                           "valid_member_count": len(observations), "sequence_shape": shape, "over_cap": over_cap,
                           "overlaps_period_header": overlaps, "accepted": accepted, "observations": observations,
                           "score": len(observations) * 10 + (4 if shape == "CONSECUTIVE_ASCENDING" else 2 if shape in {"STABLE_REPEAT", "NON_DECREASING_WITH_GAPS"} else 0)})
    accepted = [item for item in hypotheses if item["accepted"]]
    return (max(accepted, key=lambda item: item["score"]) if accepted else None), hypotheses


def _unit(text: str) -> str | None:
    compact = normalize_text(text)
    return next((value for value in ("人民币百万元", "人民币千元", "人民币元") if value in compact), None)


def _page_evidence(*, words: list[tuple], text: str, page: int, page_width: float, page_count: int, context: ReportPeriodContext, parent_aliases: Iterable[str], member_contract: dict[str, Any], source: str) -> dict[str, Any]:
    lines = _lines_from_words(words)
    median_height = _median([word[3] - word[1] for row in lines for word in row], 12.0)
    # Fast Index/Tesseract words are expressed in rendered-pixel coordinates,
    # while native PyMuPDF words use PDF points.  The final column must end at
    # the coordinate system's real right edge, not the native page width.
    effective_page_width = max(float(page_width), max((word[2] for row in lines for word in row), default=0.0))
    periods = _period_candidates(lines, context, effective_page_width)
    source_rows = _member_rows(
        lines, page=page, periods=periods, parent_aliases=parent_aliases,
        member_contract=member_contract,
        prefer_unseen_ambiguous=(source == "NATIVE_PDF_WORDS" and not periods),
    )
    allowed_current = set(member_contract.get("required_current_members") or []) | set(
        member_contract.get("optional_current_members") or []
    )
    # Native aliases are identity evidence even when native table geometry is
    # incomplete.  Keep historical members here so Hybrid OCR can bind their
    # numeric rows without letting OCR spelling redefine their member_table.
    if source != "NATIVE_PDF_WORDS" or periods:
        source_rows = [
            row for row in source_rows
            if row["member_table"] in allowed_current
            or row["member_period_status"] in {
                "COMPARATIVE_ONLY_LEGACY_MEMBER", "ACTIVE_COMPARATIVE_PERIOD",
            }
        ]
    selected_note, hypotheses = _select_note_topology(source_rows, _note_header_candidates(lines, periods, median_height), periods, page_count, median_height)
    members: list[MemberRowEvidence] = []
    for member in source_rows:
        note = (selected_note or {}).get("observations", {}).get(_row_observation_key(member), {})
        members.append(MemberRowEvidence(
            member_table=member["member_table"], raw_label=member["raw_label"],
            label_bbox=member["label_bbox"], source_row_id=member["source_row_id"],
            parent_relation=member["parent_relation"], note_reference=note.get("reference"),
            note_reference_status="EXPLICIT_CERTIFIED_NOTE_COLUMN" if note else "NOTE_REFERENCE_UNRESOLVED",
            amount_cells=tuple(member["amount_cells"]),
            presentation_regime=member["presentation_regime"],
            member_period_status=member["member_period_status"],
            binding_row_bbox=_bbox(member["row"]), source_line_index=member["line_index"],
            identity_source=source, value_source=source,
            alignment_evidence={"status": "NATIVE_DIRECT" if source == "NATIVE_PDF_WORDS" else "OCR_ALIAS_RESOLVED"},
            presentation_member_id=member.get("presentation_member_id") or member["member_table"],
            canonical_analysis_bucket=member.get("canonical_analysis_bucket") or member["member_table"],
            comparability_status=member.get("comparability_status") or "UNRESOLVED",
            analysis_bridge_groups=tuple(member.get("analysis_bridge_groups") or []),
            period_applicability=tuple(member.get("period_applicability") or []),
        ))
    title_row = next((row for row in lines[:32] if "资产负债表" in _line_text(row) or "财务状况表" in _line_text(row)), None)
    scope, scope_source, scope_confidence, scope_conflict = scope_from_statement_text(text)
    required = list(member_contract.get("required_current_members") or [])
    valid_current_by_row = {
        member.source_row_id: [
            cell for cell in member.amount_cells
            if cell["period_role"] == "CURRENT"
            and cell.get("period_value_status") in {"VALUE_PRESENT", "LEGAL_DASH"}
        ]
        for member in members
    }
    active_rows_by_member = {
        member_id: [
            member for member in members
            if member.member_table == member_id and valid_current_by_row.get(member.source_row_id)
        ]
        for member_id in set(required)
    }
    # A required member must resolve to exactly one active physical row.  Two
    # rows with the same presentation identity are a real selection ambiguity,
    # not permission to choose one by list order.
    required_status_valid = bool(required) and all(
        len(active_rows_by_member.get(member_id) or []) == 1
        for member_id in required
    )
    current_cells = [cell for cells in valid_current_by_row.values() for cell in cells]
    current_members = {
        member.member_table for member in members
        if valid_current_by_row.get(member.source_row_id)
    }
    value_verified = bool(periods and (required_status_valid if required else current_cells and current_members))
    required_rows = [member for member in members if member.member_table in set(required)]
    row_binding_verified = bool(
        value_verified
        and all(member.label_bbox for member in required_rows or members)
        and all(
            cell.get("line_index") is not None and cell.get("bbox")
            for member in required_rows or members
            for cell in valid_current_by_row.get(member.source_row_id, [])
        )
    )
    comparative_only = [member.member_table for member in members if member.member_period_status == "COMPARATIVE_ONLY_LEGACY_MEMBER"]
    matrix = [{
        "member_table": member.member_table,
        "presentation_member_id": member.presentation_member_id or member.member_table,
        "source_row_id": member.source_row_id,
        "presentation_regime": member.presentation_regime,
        "member_period_status": member.member_period_status,
        "canonical_analysis_bucket": member.canonical_analysis_bucket,
        "comparability_status": member.comparability_status,
        "analysis_bridge_groups": [dict(item) for item in member.analysis_bridge_groups],
        "period_applicability": [dict(item) for item in member.period_applicability],
        "period_values": [{
            "period_identity": cell.get("period_identity"),
            "period_role": cell.get("period_role"),
            "period_value_status": cell.get("period_value_status"),
            "raw": cell.get("raw"),
            "value": cell.get("value"),
        } for cell in member.amount_cells],
    } for member in members]
    return {"scope": scope, "scope_source": scope_source, "scope_confidence": scope_confidence, "scope_conflict": scope_conflict,
            "title": _line_text(title_row or []).strip(), "title_bbox": _bbox(title_row or []), "unit": _unit(text), "periods": periods,
            "members": members, "parent_identity": "EXPLICIT_PARENT" if any(member.parent_relation == "EXPLICIT_CHILD_OF_PARENT" for member in members) else "IMPLICIT_MEMBER_SET",
            "value_verified": value_verified, "period_verified": bool(periods and any(column.period_role == "CURRENT" for column in periods)),
            "note_verified": selected_note is not None, "row_binding_verified": row_binding_verified,
            "required_current_member_status_valid": required_status_valid,
            "comparative_only_members": comparative_only, "member_period_matrix": matrix,
            "topology_hypotheses": hypotheses, "selected_topology_id": (selected_note or {}).get("topology_id"),
            "source": source, "lines": lines, "page_count": page_count, "median_height": median_height}


def _context(report_year: str | int, report_period_context: ReportPeriodContext | dict[str, Any] | None) -> ReportPeriodContext:
    if isinstance(report_period_context, ReportPeriodContext):
        return report_period_context
    raw = dict(report_period_context or {})
    return ReportPeriodContext(int(raw.get("report_year") or report_year), str(raw.get("period_type") or "ANNUAL"),
                               int(raw["quarter"]) if raw.get("quarter") not in {None, ""} else None, raw.get("as_of_date"))


def _same_periods(left: list[PeriodColumnEvidence], right: list[PeriodColumnEvidence]) -> bool:
    return [column.period_identity for column in left] == [column.period_identity for column in right]


def _word_key(word: Word) -> tuple[float, float, float, float, str]:
    return (round(float(word[0]), 4), round(float(word[1]), 4), round(float(word[2]), 4), round(float(word[3]), 4), str(word[4]))


def _normalize_ocr_words_to_pdf_points(
    words: list[tuple], metadata: dict[str, Any] | None, *, page_width: float, page_height: float,
) -> tuple[list[Word], dict[tuple[float, float, float, float, str], dict[str, Any]], dict[str, Any] | None]:
    """Convert Fast-Index OCR geometry to PDF points, or refuse Hybrid use.

    OCR text remains useful without this metadata, but a mixed Native/OCR row
    binding must never compare raster pixels to PDF points by guesswork.
    """
    raw = dict((metadata or {}).get("ocr_geometry_metadata") or {})
    if raw.get("geometry_schema_version") != "FAST_INDEX_OCR_GEOMETRY_V2":
        return [], {}, None
    space = str(raw.get("coordinate_space") or "")
    if space == "PDF_POINTS":
        scale_x = scale_y = 1.0
    elif space == "RASTER_PIXELS":
        render_width = float(raw.get("render_width") or 0)
        render_height = float(raw.get("render_height") or 0)
        if render_width <= 0 or render_height <= 0:
            return [], {}, None
        scale_x, scale_y = page_width / render_width, page_height / render_height
    else:
        return [], {}, None
    normalized: list[Word] = []
    provenance: dict[tuple[float, float, float, float, str], dict[str, Any]] = {}
    for word in words:
        if len(word) < 5 or not _clean_token(word[4]):
            continue
        result: Word = (
            float(word[0]) * scale_x, float(word[1]) * scale_y,
            float(word[2]) * scale_x, float(word[3]) * scale_y, _clean_token(word[4]),
        )
        normalized.append(result)
        provenance[_word_key(result)] = {
            "raw_bbox": {"x0": float(word[0]), "y0": float(word[1]), "x1": float(word[2]), "y1": float(word[3])},
            "raw_coordinate_space": space,
            "normalized_coordinate_space": "PDF_POINTS",
            "geometry_metadata": raw,
        }
    return normalized, provenance, {
        **raw, "normalized_coordinate_space": "PDF_POINTS", "normalization_scale_x": scale_x,
        "normalization_scale_y": scale_y,
    }


def _amount_cells_for_row(
    row: list[Word], *, periods: list[PeriodColumnEvidence], line_index: int,
    provenance: dict[tuple[float, float, float, float, str], dict[str, Any]],
) -> list[dict[str, Any]]:
    cells: list[dict[str, Any]] = []
    for word in row:
        raw = word[4]
        if not _NUMBER.fullmatch(raw.replace("，", ",")):
            continue
        center = (word[0] + word[2]) / 2
        column = next((item for item in periods if item.x_range[0] <= center < item.x_range[1]), None)
        if column is None:
            continue
        value = _scalar_number(raw)
        cells.append({
            "period_label": column.period_label, "period_year": column.period_year,
            "period_role": column.period_role, "period_identity": column.period_identity,
            "raw": raw, "value": value, "bbox": _bbox([word]),
            "bbox_coordinate_space": "PDF_POINTS", "source_bbox": provenance.get(_word_key(word), {}).get("raw_bbox"),
            "source_coordinate_space": provenance.get(_word_key(word), {}).get("raw_coordinate_space"),
            "period_value_status": _period_value_status(raw, value),
            "column_index": column.column_index, "line_index": line_index,
        })
    return cells


def _anonymous_ocr_rows(
    lines: list[list[Word]], *, periods: list[PeriodColumnEvidence], page_count: int,
    median_height: float, provenance: dict[tuple[float, float, float, float, str], dict[str, Any]],
) -> tuple[list[dict[str, Any]], dict[str, Any] | None, list[dict[str, Any]]]:
    """Extract OCR numeric rows without asking OCR text to resolve member identity."""
    provisional: list[dict[str, Any]] = []
    for line_index, row in enumerate(lines):
        cells = _amount_cells_for_row(row, periods=periods, line_index=line_index, provenance=provenance)
        by_column: dict[int, int] = {}
        for cell in cells:
            by_column[cell["column_index"]] = by_column.get(cell["column_index"], 0) + 1
        if not cells or any(count > 1 for count in by_column.values()):
            continue
        provisional.append({
            "member_table": f"OCR_ROW_{line_index}", "row": row, "line_index": line_index,
            "source_row_id": f"OCR_ROW_{line_index}",
            "bbox": _bbox(row) or {}, "amount_cells": cells,
        })
    selected_note, hypotheses = _select_note_topology(
        provisional, _note_header_candidates(lines, periods, median_height), periods, page_count, median_height,
    )
    note_observations = dict((selected_note or {}).get("observations") or {})
    first_amount_x = min((item.x_range[0] for item in periods), default=float("inf"))
    note_box = dict((selected_note or {}).get("bbox") or {})
    for row in provisional:
        note = dict(note_observations.get(_row_observation_key(row)) or {})
        label_words = [
            word for word in row["row"]
            if word[0] < first_amount_x and not (
                note_box and note_box["x0"] <= (word[0] + word[2]) / 2 <= note_box["x1"]
            )
        ]
        row["ocr_label_text"] = _line_text(label_words).strip()
        row["note_reference"] = note.get("reference")
        row["note_bbox"] = note.get("bbox")
        row["note_reference_status"] = "EXPLICIT_CERTIFIED_NOTE_COLUMN" if note else "NOTE_REFERENCE_UNRESOLVED"
    return provisional, selected_note, hypotheses


def _vertical_alignment(native_box: dict[str, float] | None, ocr_box: dict[str, float] | None) -> dict[str, float]:
    if not native_box or not ocr_box:
        return {"overlap_ratio": 0.0, "center_distance": float("inf"), "height_reference": 0.0}
    n_height = max(0.0, native_box["y1"] - native_box["y0"])
    o_height = max(0.0, ocr_box["y1"] - ocr_box["y0"])
    overlap = max(0.0, min(native_box["y1"], ocr_box["y1"]) - max(native_box["y0"], ocr_box["y0"]))
    return {
        "overlap_ratio": overlap / min(n_height, o_height) if min(n_height, o_height) else 0.0,
        "center_distance": abs((native_box["y0"] + native_box["y1"]) / 2 - (ocr_box["y0"] + ocr_box["y1"]) / 2),
        "height_reference": max(n_height, o_height),
    }


def _select_hybrid_note_topology(
    assignments: list[tuple[MemberRowEvidence, dict[str, Any], dict[str, Any]]],
    hypotheses: list[dict[str, Any]],
) -> dict[str, Any] | None:
    """Accept a local, aligned run when the full page has later unrelated notes."""
    ranked: list[dict[str, Any]] = []
    for hypothesis in hypotheses:
        if hypothesis.get("over_cap") or hypothesis.get("overlaps_period_header"):
            continue
        observations = dict(hypothesis.get("observations") or {})
        selected = [observations.get(_row_observation_key(row)) for _, row, _ in assignments]
        selected = [entry for entry in selected if entry and entry.get("numbers")]
        values = [entry["numbers"][-1] for entry in selected]
        shape = _sequence_shape(values)
        if len(selected) < 2 or shape == "NON_MONOTONIC":
            continue
        ranked.append({
            **hypothesis, "accepted_for_hybrid_alignment": True,
            "aligned_member_count": len(selected), "aligned_sequence_shape": shape,
            "score": int(hypothesis.get("score") or 0) + len(selected) * 100,
        })
    return max(ranked, key=lambda item: item["score"]) if ranked else None


def _hybrid_native_identity_ocr_values(
    native: dict[str, Any], ocr: dict[str, Any], *, contract: dict[str, Any],
    ocr_provenance: dict[tuple[float, float, float, float, str], dict[str, Any]],
) -> tuple[dict[str, Any] | None, list[dict[str, Any]]]:
    """Bind Native member identities to OCR numeric rows; never OCR-relabel them."""
    conflicts: list[dict[str, Any]] = []
    periods = list(ocr.get("periods") or [])
    if not periods:
        return None, [{"status": "OCR_PERIODS_UNRESOLVED"}]
    if native.get("periods") and not _same_periods(native["periods"], periods):
        return None, [{"field": "period_columns", "status": "NATIVE_OCR_CONFLICT"}]
    lines = list(ocr.get("lines") or [])
    rows, selected_note, hypotheses = _anonymous_ocr_rows(
        lines, periods=periods, page_count=int(ocr.get("page_count") or 0),
        median_height=float(ocr.get("median_height") or 12.0), provenance=ocr_provenance,
    )
    assignments: list[tuple[MemberRowEvidence, dict[str, Any], dict[str, Any]]] = []
    used_rows: set[int] = set()
    for member in native.get("members") or []:
        binding_box = member.binding_row_bbox or member.label_bbox
        candidates: list[tuple[dict[str, Any], dict[str, Any]]] = []
        note_mismatches: list[str] = []
        native_note = _compact(member.note_reference)
        for row in rows:
            metrics = _vertical_alignment(binding_box, row.get("bbox"))
            geometry_ok = (
                metrics["overlap_ratio"] >= 0.60
                or metrics["center_distance"] <= 0.45 * metrics["height_reference"]
            )
            if not geometry_ok:
                continue
            ocr_note = _compact(row.get("note_reference"))
            if native_note and ocr_note and ocr_note != native_note:
                note_mismatches.append(str(row.get("note_reference") or ""))
                continue
            if not native_note and metrics["overlap_ratio"] < 0.75:
                continue
            candidates.append((row, metrics))
        if len(candidates) != 1:
            conflicts.append({
                "member_table": member.member_table,
                "status": "NATIVE_OCR_CONFLICT" if note_mismatches else (
                    "OCR_ROW_ALIGNMENT_AMBIGUOUS" if len(candidates) > 1 else "OCR_ROW_ALIGNMENT_NOT_FOUND"
                ),
                "field": "note_reference" if note_mismatches else None,
                "ocr_note_candidates": note_mismatches,
                "candidate_count": len(candidates),
            })
            continue
        row, metrics = candidates[0]
        if row["line_index"] in used_rows:
            conflicts.append({"member_table": member.member_table, "status": "OCR_ROW_REUSED", "ocr_line_index": row["line_index"]})
            continue
        used_rows.add(row["line_index"])
        assignments.append((member, row, metrics))
    if conflicts:
        return None, conflicts
    native_order = [member.source_line_index if member.source_line_index is not None else index for index, member in enumerate(native.get("members") or [])]
    ocr_order = [row["line_index"] for _, row, _ in assignments]
    if any(right <= left for left, right in zip(ocr_order, ocr_order[1:])) or native_order != sorted(native_order):
        return None, [{"status": "OCR_ROW_ALIGNMENT_NON_MONOTONIC"}]
    selected_note = _select_hybrid_note_topology(assignments, hypotheses) or selected_note
    note_observations = dict((selected_note or {}).get("observations") or {})
    for member, row, _ in assignments:
        ocr_note = (note_observations.get(_row_observation_key(row)) or {}).get("reference")
        row["note_reference"] = ocr_note
        if member.note_reference and _compact(member.note_reference) != _compact(ocr_note):
            conflicts.append({
                "member_table": member.member_table, "field": "note_reference",
                "native": member.note_reference, "ocr": ocr_note, "status": "NATIVE_OCR_CONFLICT",
            })
    if conflicts:
        return None, conflicts
    projected: list[MemberRowEvidence] = []
    for member, row, metrics in assignments:
        status = _member_period_status(row["amount_cells"], member_table=member.member_table, contract=contract)
        period_applicability = tuple({
            "period_identity": cell.get("period_identity"),
            "period_role": cell.get("period_role"),
            "status": cell.get("period_value_status"),
            "applicable": cell.get("period_value_status") != "NOT_APPLICABLE",
        } for cell in row["amount_cells"])
        projected.append(replace(
            member, amount_cells=tuple(row["amount_cells"]), member_period_status=status,
            period_applicability=period_applicability,
            identity_source="NATIVE_PDF_WORDS", value_source="FAST_INDEX_OCR_WORDS",
            alignment_evidence={
                "status": "HYBRID_ALIGNED", "ocr_line_index": row["line_index"],
                "ocr_row_bbox": row["bbox"], "vertical_overlap_ratio": round(metrics["overlap_ratio"], 4),
                "vertical_center_distance": round(metrics["center_distance"], 4),
                "native_note_reference": member.note_reference, "ocr_note_reference": row.get("note_reference"),
                "note_consistent": bool(not member.note_reference or _compact(member.note_reference) == _compact(row.get("note_reference"))),
                "ocr_label_diagnostic": row.get("ocr_label_text"),
                "selected_note_topology_id": (selected_note or {}).get("topology_id"),
            },
        ))
    required = set(contract.get("required_current_members") or [])
    active_by_id = {
        member_id: [
            member for member in projected
            if member.member_table == member_id and any(
                cell.get("period_role") == "CURRENT"
                and cell.get("period_value_status") in {"VALUE_PRESENT", "LEGAL_DASH"}
                for cell in member.amount_cells
            )
        ]
        for member_id in required
    }
    if not required or not all(len(active_by_id.get(member_id) or []) == 1 for member_id in required):
        return None, [{"status": "OCR_REQUIRED_CURRENT_MEMBER_ALIGNMENT_INCOMPLETE"}]
    matrix = [{
        "member_table": member.member_table,
        "presentation_member_id": member.presentation_member_id or member.member_table,
        "source_row_id": member.source_row_id,
        "presentation_regime": member.presentation_regime,
        "member_period_status": member.member_period_status,
        "canonical_analysis_bucket": member.canonical_analysis_bucket,
        "comparability_status": member.comparability_status,
        "analysis_bridge_groups": [dict(item) for item in member.analysis_bridge_groups],
        "period_applicability": [dict(item) for item in member.period_applicability],
        "period_values": [{
            "period_identity": cell.get("period_identity"), "period_role": cell.get("period_role"),
            "period_value_status": cell.get("period_value_status"), "raw": cell.get("raw"), "value": cell.get("value"),
        } for cell in member.amount_cells],
    } for member in projected]
    return {
        **native, "periods": periods, "members": projected,
        "value_verified": True, "period_verified": any(column.period_role == "CURRENT" for column in periods),
        "note_verified": bool(native.get("note_verified")), "row_binding_verified": True,
        "required_current_member_status_valid": True,
        "comparative_only_members": [member.member_table for member in projected if member.member_period_status == "COMPARATIVE_ONLY_LEGACY_MEMBER"],
        "member_period_matrix": matrix, "topology_hypotheses": hypotheses,
        "selected_topology_id": (selected_note or {}).get("topology_id"),
        "source": "NATIVE_LABELS+FAST_INDEX_OCR_VALUES",
    }, conflicts


def build_statement_anchor_evidence_v2(pdf_path: Path, page_number: int, report_year: str | int, *, parent_aliases: Iterable[str] = (), member_contract: dict[str, Any] | None = None, previous_statement_scope: str | None = None, directory_scope: str | None = None, ocr_words: list[tuple] | None = None, ocr_metadata: dict[str, Any] | None = None, report_period_context: ReportPeriodContext | dict[str, Any] | None = None, recovery_stage: str = "NATIVE_DISCOVERY") -> StatementAnchorEvidenceV2:
    """Build bounded native/OCR evidence; downstream Capture still owns values."""
    pdf_path = Path(pdf_path)
    context = _context(report_year, report_period_context)
    contract = dict(member_contract or financial_member_contract_snapshot({}))
    with fitz.open(str(pdf_path)) as document:
        page = document[int(page_number) - 1]
        native_text = page.get_text("text")
        native_words = [tuple(word[:5]) for word in page.get_text("words")]
        page_width, page_height, page_count = float(page.rect.width), float(page.rect.height), len(document)
    native = _page_evidence(words=native_words, text=native_text, page=int(page_number), page_width=page_width, page_count=page_count, context=context, parent_aliases=parent_aliases, member_contract=contract, source="NATIVE_PDF_WORDS")
    if native["scope"] == "UNKNOWN":
        native["scope"], native["scope_source"], native["scope_confidence"], native["scope_conflict"] = scope_from_statement_text(native_text, previous_statement_scope=previous_statement_scope, directory_scope=directory_scope)
    selected, conflicts, mode = native, [], "NATIVE"
    normalized_ocr_metadata: dict[str, Any] | None = None
    if ocr_words:
        normalized_words, provenance, normalized_ocr_metadata = _normalize_ocr_words_to_pdf_points(
            list(ocr_words), ocr_metadata, page_width=page_width, page_height=page_height,
        )
        if not normalized_ocr_metadata:
            conflicts.append({"field": "ocr_geometry_metadata", "status": "OCR_GEOMETRY_METADATA_REQUIRED"})
        else:
            ocr_text = "\n".join(" ".join(word[4] for word in row) for row in _lines_from_words(normalized_words))
            ocr = _page_evidence(
                words=normalized_words, text=ocr_text, page=int(page_number), page_width=page_width,
                page_count=page_count, context=context, parent_aliases=parent_aliases,
                member_contract=contract, source="FAST_INDEX_OCR_WORDS",
            )
            # Native scope/title/unit/parent/member identity are immutable source
            # facts in Hybrid mode.  OCR only provides bounded row geometry.
            if native["scope"] != "UNKNOWN" and ocr["scope"] not in {"UNKNOWN", native["scope"]}:
                conflicts.append({"field": "source_statement_scope", "native": native["scope"], "ocr": ocr["scope"], "status": "NATIVE_OCR_CONFLICT"})
            if not native["value_verified"] and not conflicts:
                hybrid, hybrid_conflicts = _hybrid_native_identity_ocr_values(
                    native, ocr, contract=contract, ocr_provenance=provenance,
                )
                if hybrid is not None:
                    selected = hybrid
                    mode = "HYBRID_NATIVE_IDENTITY_OCR_VALUES"
                else:
                    conflicts.extend(hybrid_conflicts)
            elif conflicts:
                mode = "NATIVE_OCR_CONFLICT"
    if conflicts and mode != "HYBRID_NATIVE_IDENTITY_OCR_VALUES":
        mode = "NATIVE_OCR_CONFLICT" if any(item.get("status") == "NATIVE_OCR_CONFLICT" for item in conflicts) else "OCR_ALIGNMENT_UNRESOLVED"
    note_box = next((item.get("bbox") for item in selected["topology_hypotheses"] if item.get("topology_id") == selected["selected_topology_id"]), None)
    return StatementAnchorEvidenceV2(
        schema_version=EVIDENCE_SCHEMA, pdf_sha256=file_sha256(pdf_path),
        physical_page_group=(int(page_number),), statement_type="BALANCE_SHEET",
        source_statement_scope=selected["scope"], scope_evidence_source=selected["scope_source"],
        scope_confidence=selected["scope_confidence"], scope_conflict_reason=selected["scope_conflict"],
        title=selected["title"], title_bbox=selected["title_bbox"], unit=selected["unit"],
        period_columns=tuple(selected["periods"]), note_column_bbox=note_box,
        members=tuple(selected["members"]), parent_identity=selected["parent_identity"],
        native_value_geometry_present=bool(native["value_verified"]),
        geometry_evidence_mode=mode, geometry_source=selected["source"],
        period_geometry_verified=bool(selected["period_verified"]),
        note_geometry_verified=bool(selected["note_verified"]),
        row_binding_verified=bool(selected["row_binding_verified"]),
        value_geometry_verified=bool(selected["value_verified"] and not conflicts),
        ocr_spatial_geometry_verified=bool(mode == "HYBRID_NATIVE_IDENTITY_OCR_VALUES"),
        topology_hypotheses=tuple(selected["topology_hypotheses"]),
        selected_topology_id=selected["selected_topology_id"],
        native_ocr_conflicts=tuple(conflicts), recovery_stage=recovery_stage,
        page_cache_identity=dict(normalized_ocr_metadata or ocr_metadata or {}) if ocr_words else None,
        presentation_regime=str(contract.get("presentation_regime") or "UNKNOWN"),
        member_contract_snapshot=contract,
        required_current_members=tuple(contract.get("required_current_members") or []),
        optional_current_members=tuple(contract.get("optional_current_members") or []),
        historical_variant_members=tuple(contract.get("historical_variant_members") or []),
        comparative_only_members=tuple(selected.get("comparative_only_members") or []),
        member_period_matrix=tuple(selected.get("member_period_matrix") or []),
        required_current_member_status_valid=bool(selected.get("required_current_member_status_valid")),
    )
