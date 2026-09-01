"""v6.9 compound-note extraction primitives.

The module deliberately sits below the request/orchestrator layer: it never
creates a second production capture route.  It converts one immutable raw
table-capture result into a *note container* and one or more logical table
blocks.  Every block carries its own geometry, topology, semantic and
reconciliation evidence so a later manual split/merge remains auditable.
"""
from __future__ import annotations

import copy
import dataclasses
import hashlib
import json
import re
import uuid
from collections import defaultdict
from pathlib import Path
from typing import Any

from table_capture import (
    _FOOTNOTE_NUMERIC_SUFFIX_RE,
    TableCaptureResult,
    TableCell,
    TableColumn,
    TableRow,
    apply_item_label_normalization,
    stable_source_row_id,
)
from investment_portfolio_axis_semantics import (
    BY_ACCOUNTING_MEASUREMENT,
    BY_INVESTMENT_OBJECT,
    UNRESOLVED_AXIS_BOUNDARY,
    recognise_portfolio_axis_boundary,
    strip_recognised_axis_prefix,
)


NARRATIVE_TYPES = {"MEMO_TEXT", "NOTE_TEXT", "NARRATIVE", "TEXT"}
TOTAL_TOKENS = ("合计", "总计", "资产总额", "负债合计", "总资产", "总负债")
CLASSIFICATION_AXES = {
    "ASSET_TYPE",
    "MEASUREMENT_COMPOSITION",
    "LISTING_STATUS",
    "BY_INVESTMENT_OBJECT",
    "BY_ACCOUNTING_MEASUREMENT",
    "PORTFOLIO_SUMMARY",
    "UNRESOLVED",
}
BLOCK_TERMINAL_TYPES = {
    "NONE",
    "LOCAL_TOTAL",
    "INTERMEDIATE_TOTAL",
    "SECTION_TOTAL",
    "FINAL_TOTAL",
    "UNRESOLVED",
}


def collect_page_footnote_context(
    doc: Any,
    page_numbers: Sequence[int],
) -> dict[int, dict[str, Any]]:
    """Pre-collect same-page footnote numbers and font span geometries for pages."""
    page_evidence: dict[int, dict[str, Any]] = {}
    for page_number in sorted({int(p) for p in page_numbers if int(p) > 0 and int(p) <= len(doc)}):
        page = doc[page_number - 1]
        native_lines: list[dict[str, Any]] = []
        for block in page.get_text("dict").get("blocks") or []:
            if int(block.get("type", 0)) != 0:
                continue
            for line in block.get("lines") or []:
                spans = list(line.get("spans") or [])
                text = "".join(str(span.get("text") or "") for span in spans).strip()
                if text:
                    native_lines.append({
                        "text": text,
                        "bbox": list(line.get("bbox") or []),
                        "spans": spans,
                    })
        page_text = page.get_text("text") or ""
        note_blocks = re.split(r"(?:^|\n)\s*注\s*[：:]", page_text)[1:]
        note_markers = set()
        for nb in note_blocks:
            for nb_line in nb.splitlines():
                nb_line = nb_line.strip()
                m = re.match(r"^(?:[（(]\s*(\d{1,3})\s*[）)]|(\d{1,3})\s*[.．、])\s*(\S+)", nb_line)
                if m:
                    marker = m.group(1) or m.group(2)
                    note_markers.add(marker)
                elif nb_line.startswith(("投资组合", "资产负债", "利润表", "现金流量表")) or "年12月31日" in nb_line:
                    break
        page_evidence[page_number] = {
            "native_lines": native_lines,
            "note_markers": note_markers,
        }
    return page_evidence


def match_line_footnote_evidence(
    raw_label: str,
    page_no: int,
    page_footnote_context: dict[int, dict[str, Any]],
) -> list[dict[str, Any]]:
    """Match line label against pre-collected page footnote evidence."""
    identity_label = str(raw_label or "").strip()
    match = _FOOTNOTE_NUMERIC_SUFFIX_RE.search(identity_label)
    if not match:
        return []
    marker = str(match.group(match.lastgroup or ""))
    evidence: list[dict[str, Any]] = []
    page_data = page_footnote_context.get(int(page_no), {})
    physical_label = identity_label
    for native in page_data.get("native_lines") or []:
        native_text = str(native.get("text") or "").strip()
        if native_text != physical_label and not physical_label.endswith(native_text):
            continue
        spans = list(native.get("spans") or [])
        if len(spans) < 2:
            continue
        matched_suffix = None
        for span_count in range(1, min(4, len(spans))):
            candidate_spans = spans[-span_count:]
            joined_suffix_text = "".join(str(s.get("text") or "") for s in candidate_spans).strip()
            if _FOOTNOTE_NUMERIC_SUFFIX_RE.fullmatch(joined_suffix_text):
                matched_suffix = candidate_spans
                break
        if not matched_suffix:
            continue
        body_spans = spans[:-len(matched_suffix)]
        if not body_spans:
            continue
        body_size = max(float(span.get("size") or 0.0) for span in body_spans)
        suffix_size = max(float(span.get("size") or 0.0) for span in matched_suffix)
        body_origin_y = max(
            float((span.get("origin") or [0.0, 0.0])[1])
            for span in body_spans
        )
        suffix_origin_y = min(
            float((span.get("origin") or [0.0, body_origin_y])[1])
            for span in matched_suffix
        )
        if (
            body_size > 0.0
            and (
                suffix_size <= body_size * 0.8
                or suffix_origin_y <= body_origin_y - max(1.0, body_size * 0.15)
            )
        ):
            evidence.append({
                "marker": marker,
                "method": "NATIVE_SUPERSCRIPT_GEOMETRY",
                "page": int(page_no),
                "line_bbox": native.get("bbox"),
                "span": {
                    "text": "".join(str(s.get("text") or "") for s in matched_suffix),
                    "size": suffix_size,
                    "bbox": matched_suffix[-1].get("bbox"),
                    "origin": matched_suffix[-1].get("origin"),
                },
                "body_font_size": body_size,
            })
            break
    if marker in set(page_data.get("note_markers") or set()):
        evidence.append({
            "marker": marker,
            "method": "SAME_PAGE_FOOTNOTE_NUMBER",
            "page": int(page_no),
        })
    return evidence


def certify_direct_row_footnotes(
    result: TableCaptureResult,
    pdf_path: Path,
    certified_segments: list[dict[str, Any]],
) -> int:
    """Attach native evidence for numeric row-label footnotes.

    Raw labels are never rewritten.  The shared normalizer removes a suffix
    in parenthesized, bare or ``注+数字`` form only when either native
    superscript geometry or a matching numbered note on the same page is
    observed.
    """
    certified_pages = {
        int(segment.get("pdf_page_number") or segment.get("start_page"))
        for segment in certified_segments
        if str(segment.get("pdf_page_number") or segment.get("start_page") or "").isdigit()
    }
    candidate_rows = [
        row for row in result.rows
        if int(row.page) in certified_pages
        and _FOOTNOTE_NUMERIC_SUFFIX_RE.search(
            str(row.row_item_raw or row.raw_item or "").strip()
        )
    ]
    if not candidate_rows:
        return 0
    try:
        import fitz
        document = fitz.open(str(Path(pdf_path)))
        page_evidence = collect_page_footnote_context(
            document,
            sorted({int(row.page) for row in candidate_rows}),
        )
        document.close()
    except Exception:
        return 0

    certified = 0
    for row in candidate_rows:
        identity_label = str(row.row_item_raw or row.raw_item or "").strip()
        evidence = match_line_footnote_evidence(
            identity_label,
            int(row.page),
            page_evidence,
        )
        row.footnote_evidence = evidence
        apply_item_label_normalization(row, identity_label)
        if row.normalization_status == "CERTIFIED_NUMERIC_FOOTNOTE_REMOVED":
            certified += 1
    if certified:
        result.stats = {
            **dict(result.stats or {}),
            "certified_numeric_footnote_rows": certified,
            "row_label_normalization_contract": "RAW_IMMUTABLE__EVIDENCE_NORMALIZED_V1",
        }
    return certified
_ASSET_SECTION_LABELS = {"债券", "债务工具", "权益工具"}
_MEASUREMENT_TOKENS = ("摊余成本", "累计公允价值变动", "公允价值变动")
_AXIS_TITLES = {
    "ASSET_TYPE": "按资产类型",
    "MEASUREMENT_COMPOSITION": "按计量构成",
    "LISTING_STATUS": "按上市状态",
    "BY_INVESTMENT_OBJECT": "投资组合（按投资对象）",
    "BY_ACCOUNTING_MEASUREMENT": "投资组合（按会计计量）",
    "PORTFOLIO_SUMMARY": "投资组合（总览）",
}
_PLACEHOLDER_RE = re.compile(
    r"^(?:[-–—－]+|不适用|不適用|N[/／]A)$",
    re.IGNORECASE,
)


def _id(prefix: str, *parts: object) -> str:
    material = "|".join(str(p or "") for p in parts)
    return f"{prefix}_{hashlib.sha256(material.encode('utf-8')).hexdigest()[:18]}"


def _numeric_cells(row: TableRow) -> int:
    return sum(c.parsed_number is not None for c in row.cells)


def _cell_state(cell: TableCell) -> str:
    """Classify a cell as NUMERIC / PLACEHOLDER / EMPTY / UNPARSEABLE.

    A legal placeholder must be an explicit dash/not-applicable token AND be
    aligned to a known amount column (``column_ordinal`` set by the upstream
    token-to-column alignment).  Table rules, footers and unaligned strokes
    never become amount slots; an unaligned token stays UNPARSEABLE so the
    table is sent to review instead of silently passing.
    """
    if cell.parsed_number is not None:
        return "NUMERIC"
    raw = str(cell.raw or "").strip()
    if not raw:
        return "EMPTY"
    if _PLACEHOLDER_RE.match(raw) and cell.column_ordinal is not None:
        return "PLACEHOLDER"
    return "UNPARSEABLE"


def _annotate_cell_states(rows: list[TableRow]) -> None:
    for row in rows:
        for cell in row.cells:
            cell.cell_state = _cell_state(cell)


def _amount_slots(
    row: TableRow,
    active_ordinals: set[int] | None = None,
) -> int:
    """Return the aligned width of the observed amount columns.

    Spatial extraction may omit an empty leading or trailing cell while the
    surviving numeric cell still carries its certified anchor ordinal.
    """
    aligned_ordinals = {
        int(cell.column_ordinal)
        for cell in row.cells
        if getattr(cell, "cell_state", None) in {"NUMERIC", "PLACEHOLDER"}
        and cell.column_ordinal is not None
        and int(cell.column_ordinal) >= 0
    }
    if not aligned_ordinals:
        return 0
    if active_ordinals:
        ordinal_positions = {
            ordinal: index
            for index, ordinal in enumerate(sorted(active_ordinals))
        }
        relative_ordinals = {
            ordinal_positions[ordinal]
            for ordinal in aligned_ordinals
            if ordinal in ordinal_positions
        }
        return max(relative_ordinals) + 1 if relative_ordinals else 0
    return max(aligned_ordinals) + 1


def _looks_narrative(row: TableRow) -> bool:
    raw = str(row.raw_item or row.row_item_raw or "").strip()
    return bool(raw and (_numeric_cells(row) == 0 or row.row_type in NARRATIVE_TYPES) and len(raw) > 16)


def _looks_total(row: TableRow) -> bool:
    role = str(row.row_role or row.row_type or "").upper()
    label = str(row.raw_item or row.row_item_raw or "")
    return role in {"TOTAL", "IMPLICIT_TOTAL"} or any(
        token in label for token in TOTAL_TOKENS
    )


def _compact_label(row: TableRow) -> str:
    return re.sub(
        r"\s+",
        "",
        str(row.raw_item or row.row_item_raw or row.normalized_item or ""),
    ).strip("：:")


def _measurement_signal(rows: list[TableRow], index: int) -> bool:
    label = _compact_label(rows[index])
    if any(token in label for token in _MEASUREMENT_TOKENS):
        return True
    if label != "其中":
        return False
    # A standalone “其中：” is only an axis boundary when nearby labelled rows
    # provide measurement-basis evidence.  This avoids treating every whereof
    # memo as a new table block.
    for candidate in rows[index + 1:index + 4]:
        next_label = _compact_label(candidate)
        if any(token in next_label for token in _MEASUREMENT_TOKENS):
            return True
    return False


def _axis_signal(rows: list[TableRow], index: int) -> str | None:
    label = _compact_label(rows[index])
    portfolio_boundary = recognise_portfolio_axis_boundary(label)
    if portfolio_boundary.is_boundary:
        role = str(rows[index].row_role or rows[index].row_type or "").upper()
        structural_evidence = (
            bool(_numeric_cells(rows[index]))
            or role in {"SECTION", "SECTION_HEADER"}
            or any(_numeric_cells(row) for row in rows[index + 1:index + 4])
        )
        if structural_evidence and portfolio_boundary.classification_axis in {
            BY_INVESTMENT_OBJECT, BY_ACCOUNTING_MEASUREMENT,
        }:
            return portfolio_boundary.classification_axis
        if (
            structural_evidence
            and portfolio_boundary.classification_axis == UNRESOLVED_AXIS_BOUNDARY
        ):
            return "UNRESOLVED"
    if label in _ASSET_SECTION_LABELS:
        return "ASSET_TYPE"
    if _measurement_signal(rows, index):
        return "MEASUREMENT_COMPOSITION"
    if re.fullmatch(r"(?:境内|境外)?(?:非|未)?上市(?:部分)?", label):
        return "LISTING_STATUS"
    return None


def _unknown_section_boundary(rows: list[TableRow], index: int) -> bool:
    """Detect an evidenced but unclassified peer disclosure boundary.

    A short explicit heading after an evidenced total is not prose, and it is
    unsafe to inherit the preceding classification axis when numeric rows
    follow it.  Preserve the disclosure as its own UNRESOLVED block so the
    review gate, rather than vocabulary guessing, decides its disposition.
    """
    row = rows[index]
    role = str(row.row_role or row.row_type or "").upper()
    if role not in {"SECTION", "SECTION_HEADER"} or _axis_signal(rows, index):
        return False
    if not _compact_label(row):
        return False
    if not any(_has_evidenced_total(candidate) for candidate in rows[:index]):
        return False
    candidates = rows[index:index + 4]
    return any(_numeric_cells(candidate) for candidate in candidates)


def _axis_assignments(rows: list[TableRow]) -> list[str]:
    signals = [_axis_signal(rows, index) for index in range(len(rows))]
    signals = [
        (
            "UNRESOLVED"
            if signal is None and _unknown_section_boundary(rows, index)
            else signal
        )
        for index, signal in enumerate(signals)
    ]
    signalled = [index for index, signal in enumerate(signals) if signal]
    if not signalled:
        return ["UNRESOLVED"] * len(rows)

    first_signal = signalled[0]
    preceding = rows[:first_signal]
    preceding_axis = "UNRESOLVED"
    first_axis = signals[first_signal]
    if first_axis in {
        "BY_INVESTMENT_OBJECT", "BY_ACCOUNTING_MEASUREMENT"
    }:
        # A numeric prefix is a separately disclosed summary, not part of the
        # first classification axis.  Structural title/unit rows are retained
        # in the same physical prefix and removed only by summary normalisation.
        preceding_axis = (
            "PORTFOLIO_SUMMARY"
            if any(_numeric_cells(row) for row in preceding)
            else first_axis
        )
    elif preceding and any(_looks_total(row) for row in preceding):
        preceding_axis = "ASSET_TYPE"

    assignments: list[str] = []
    current = preceding_axis
    for index, signal in enumerate(signals):
        if signal:
            if (
                current in {
                    "BY_INVESTMENT_OBJECT", "BY_ACCOUNTING_MEASUREMENT"
                }
                and signal in {
                    "ASSET_TYPE", "MEASUREMENT_COMPOSITION", "LISTING_STATUS"
                }
            ):
                # Fine-grained vocabulary inside a certified portfolio axis is
                # row semantics, not another physical/logical table boundary.
                pass
            else:
                current = signal
        elif index == 0 and first_signal == 0 and current == "UNRESOLVED":
            current = signals[first_signal] or "UNRESOLVED"
        assignments.append(current or "UNRESOLVED")
    return assignments


def _bbox_coordinate(
    bbox: dict[str, Any],
    primary: str,
    fallback: str,
) -> float | None:
    value = bbox.get(primary, bbox.get(fallback))
    if value is None:
        return None
    try:
        return round(float(value), 4)
    except (TypeError, ValueError):
        return None


def _row_physical_anchor(row: TableRow) -> dict[str, Any]:
    bbox = dict(row.bbox or {})
    return {
        "page": row.page,
        "bbox": [
            _bbox_coordinate(bbox, "x0", "left"),
            _bbox_coordinate(bbox, "y0", "top"),
            _bbox_coordinate(bbox, "x1", "right"),
            _bbox_coordinate(bbox, "y1", "bottom"),
        ],
        "label": _compact_label(row),
        "row_type": str(row.row_type or row.row_role or ""),
        "values": [
            (
                cell.raw
                if str(cell.raw or "").strip()
                else cell.parsed_number
            )
            for cell in row.cells
        ],
    }


def _stable_block_id(
    container_id: str,
    axis: str,
    rows: list[TableRow],
) -> str:
    """Build identity from immutable physical/content evidence, never order."""
    anchor = {
        "container_id": container_id,
        "classification_axis": axis,
        "rows": [_row_physical_anchor(row) for row in rows],
    }
    material = json.dumps(
        anchor,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return _id("BLOCK", material)


def _has_evidenced_total(row: TableRow) -> bool:
    role = str(row.row_role or row.row_type or "").upper()
    if role == "IMPLICIT_TOTAL":
        return bool(row.derivation_method or row.derivation_evidence)
    return role in {"TOTAL", "SUBTOTAL"} or _looks_total(row)


def _block_terminal_type(rows: list[TableRow], *, is_final_block: bool) -> str:
    rows = [
        row for row in rows
        if not getattr(row, "excluded_from_table_logic", False)
    ]
    if not rows:
        return "UNRESOLVED"
    total_positions = [
        index for index, row in enumerate(rows) if _has_evidenced_total(row)
    ]
    if not total_positions:
        return "UNRESOLVED" if is_final_block else "NONE"
    if total_positions[-1] == len(rows) - 1:
        return "FINAL_TOTAL" if is_final_block else "LOCAL_TOTAL"
    if any(
        str(rows[index].row_role or rows[index].row_type or "").upper() == "SUBTOTAL"
        or _compact_label(rows[index]).startswith("小计")
        for index in total_positions
    ):
        return "INTERMEDIATE_TOTAL"
    return "SECTION_TOTAL"


def _topology(
    rows: list[TableRow],
    columns: list[TableColumn] | None = None,
) -> dict[str, Any]:
    """Derive header topology from aligned amount slots.

    Priority: explicit period-header count > column-aligned slot occupancy >
    per-row parsed numeric counts (fallback only).  A row whose only missing
    value is a legal dash placeholder keeps its full slot width; a row with a
    genuinely missing token/bbox/placeholder stays ambiguous.  ``cell_state``
    is annotated on every cell so the audit evidence keeps NUMERIC /
    PLACEHOLDER / EMPTY / UNPARSEABLE semantics.
    """
    rows = [r for r in rows if not getattr(r, "excluded_from_table_logic", False)]
    _annotate_cell_states(rows)
    active_ordinals = {
        int(column.ordinal)
        for column in (columns or [])
        if column is not None and column.ordinal is not None
    }
    parsed_widths = sorted({_numeric_cells(r) for r in rows if _numeric_cells(r)})
    slot_widths = sorted({
        _amount_slots(r, active_ordinals)
        for r in rows
        if _amount_slots(r, active_ordinals)
    })
    placeholder_cells = [
        c for r in rows for c in r.cells
        if getattr(c, "cell_state", None) == "PLACEHOLDER"
    ]
    unresolved_cells = [
        c for r in rows for c in r.cells
        if getattr(c, "cell_state", None) == "UNPARSEABLE"
    ]
    header_labels = [
        str(c.header_raw) for c in (columns or []) if c is not None
    ]
    expected = len(header_labels) if header_labels else 0
    alignment_consistent = all(
        c.column_ordinal is not None for c in placeholder_cells
    )

    if expected >= 1:
        slot_consistent = slot_widths == [expected]
        consistent = bool(slot_consistent and not unresolved_cells)
        if consistent:
            reason = (
                "HEADER_ALIGNED_WITH_DISCLOSED_PLACEHOLDERS"
                if placeholder_cells else "ALL_SLOTS_PARSED"
            )
            candidate_types = (
                ["TWO_PERIOD_COLUMNS"] if expected == 2
                else (["YEAR_VALUE"] if expected == 1 else ["ALIGNED_HEADER"])
            )
            score = 0.95 if placeholder_cells else 1.0
        elif unresolved_cells:
            reason = "UNRESOLVED_CELLS"
            candidate_types = ["AMBIGUOUS"]
            score = 0.55
        else:
            reason = "MISSING_SLOTS"
            candidate_types = ["AMBIGUOUS"]
            score = 0.55
    else:
        consistent = bool(len(slot_widths) <= 1 and not unresolved_cells)
        candidate_types = (
            ["YEAR_VALUE"] if len(slot_widths) == 1 else ["AMBIGUOUS"]
        )
        if consistent:
            reason = (
                "HEADER_ALIGNED_WITH_DISCLOSED_PLACEHOLDERS"
                if placeholder_cells else "ALL_SLOTS_PARSED"
            )
            score = 0.95 if placeholder_cells else 1.0
        else:
            reason = "UNRESOLVED_CELLS" if unresolved_cells else "AMBIGUOUS"
            score = 0.55

    return {
        "numeric_widths": parsed_widths,
        "parsed_numeric_widths": parsed_widths,
        "expected_numeric_columns": expected,
        "header_labels": header_labels,
        "occupied_slot_widths": slot_widths,
        "placeholder_tokens": sorted({str(c.raw).strip() for c in placeholder_cells}),
        "placeholder_cell_count": len(placeholder_cells),
        "unresolved_cell_count": len(unresolved_cells),
        "column_alignment_consistent": alignment_consistent,
        "consistent": consistent,
        "candidate_types": candidate_types,
        "topology_reason": reason,
        "score": score,
    }


def _semantic_graph(rows: list[TableRow]) -> dict[str, Any]:
    relations: list[dict[str, Any]] = []
    previous = None
    row_by_id = {row.source_row_id: row for row in rows if getattr(row, "source_row_id", None)}
    for index, row in enumerate(rows):
        label = str(row.raw_item or row.row_item_raw or "").strip()
        if not label:
            continue
        parent_id = getattr(row, "parent_row_id", None)
        parent_row = row_by_id.get(parent_id) if parent_id else None
        parent_label = str(getattr(parent_row, "normalized_item", None) or getattr(parent_row, "raw_item", None) or row.parent_section or "").strip()
        if parent_id and parent_row:
            relations.append({
                "type": "PARENT_OF",
                "parent": parent_label,
                "child": label,
                "parent_source_row_id": parent_id,
                "child_source_row_id": getattr(row, "source_row_id", None),
                "parent_row_order": getattr(parent_row, "row_order", None),
                "child_row_order": row.row_order,
            })
        elif parent_label:
            # v6.13 Node 4: Uncertified text hint without formal parent edge is recorded as an unresolved hint only.
            relations.append({
                "type": "UNRESOLVED_PARENT_HINT",
                "hint_parent_section": parent_label,
                "child": label,
                "child_row_order": row.row_order,
            })
        if _looks_total(row) and previous:
            relations.append({"type": "TOTAL_OF_PRECEDING", "total": label, "before": previous})
        previous = label
    return {"nodes": [str(r.raw_item or r.row_item_raw or "") for r in rows], "relations": relations}


def _reconciliation(rows: list[TableRow]) -> dict[str, Any]:
    """Non-destructive arithmetic evidence.  We do not fabricate missing totals."""
    totals = [r for r in rows if _looks_total(r) and _numeric_cells(r)]
    if not totals:
        return {"status": "NOT_TESTABLE", "checks": []}
    checks = []
    for total in totals:
        # A table total can only be checked against explicit preceding values;
        # label-only/narrative rows are excluded by construction.
        before = rows[: rows.index(total)]
        for cell in total.cells:
            if cell.parsed_number is None:
                continue
            ordinal = int(cell.column_ordinal)
            values = []
            for row in before:
                by_ordinal = {
                    int(candidate.column_ordinal): candidate.parsed_number
                    for candidate in row.cells
                    if candidate.column_ordinal is not None
                }
                if by_ordinal.get(ordinal) is not None:
                    values.append(by_ordinal[ordinal])
            if not values:
                continue
            observed = sum(values)
            tolerance = max(1.0, abs(cell.parsed_number) * 0.005)
            checks.append({"total_row": total.raw_item, "column": ordinal,
                           "reported": cell.parsed_number, "sum_preceding": observed,
                           "pass": abs(cell.parsed_number - observed) <= tolerance,
                           "tolerance": tolerance})
    if not checks:
        return {"status": "NOT_TESTABLE", "checks": []}
    # Preserve the arithmetic fact for audit.  The decision reducer decides
    # whether this fact is blocking; parent/child hierarchies can make a
    # flat preceding-row sum unsuitable as a merge gate.
    return {"status": "PASS" if all(x["pass"] for x in checks) else "MISMATCH", "checks": checks}


@dataclasses.dataclass(frozen=True)
class NoteContainer:
    container_id: str
    source_pdf_sha256: str
    note_reference: str | None
    note_title: str
    start_pdf_page: int
    end_pdf_page: int
    layout_evidence: dict[str, Any]


@dataclasses.dataclass
class TableBlock:
    block_id: str
    block_order: int
    title: str
    role: str
    classification_axis: str
    block_terminal_type: str
    rows: list[TableRow]
    start_pdf_page: int
    end_pdf_page: int
    bbox: dict[str, float]
    header_topology: dict[str, Any]
    semantic_graph: dict[str, Any]
    reconciliation: dict[str, Any]
    quality_status: str
    evidence: dict[str, Any]
    segment_classification: str = "UNRESOLVED"
    continuation_of_segment_id: str | None = None
    physical_segment_ids: list[str] = dataclasses.field(default_factory=list)


def build_layout_evidence(result: TableCaptureResult) -> dict[str, Any]:
    nodes = []
    edges = []
    for index, row in enumerate(result.rows):
        bbox = row.bbox or {}
        node = {"id": f"r{index}", "kind": "row", "page": row.page,
                "label": row.raw_item or row.row_item_raw or "", "bbox": bbox,
                "numeric_cells": _numeric_cells(row), "row_type": row.row_type}
        nodes.append(node)
        if index:
            edges.append({"from": f"r{index-1}", "to": f"r{index}", "type": "VERTICAL_ADJACENCY"})
    return {"nodes": nodes, "edges": edges, "extractor": "v6.9-layout-graph"}


def _source_column_ordinals(rows: list[TableRow]) -> list[int]:
    return sorted({
        int(cell.column_ordinal)
        for row in rows
        for cell in row.cells
        if cell.column_ordinal is not None
    })


def _declared_source_column_ordinals(
    result: TableCaptureResult,
    rows: list[TableRow],
) -> list[int]:
    logical_block_ids = {
        str(row.block_id or "")
        for row in rows
        if row.block_id and not getattr(row, "excluded_from_table_logic", False)
    }
    matching_groups = [
        group
        for group in ((result.stats or {}).get("vertical_period_column_groups") or [])
        if str(group.get("block_id") or "") in logical_block_ids
    ]
    if len(matching_groups) == 1:
        return sorted({
            int(ordinal)
            for ordinal in matching_groups[0].get("source_column_ordinals") or []
        })
    physical_ids = {
        str(
            getattr(row, "physical_segment_id", None)
            or row.block_id
            or ""
        )
        for row in rows
        if (
            getattr(row, "physical_segment_id", None)
            or row.block_id
        ) and not getattr(row, "excluded_from_table_logic", False)
    }
    physical_groups = [
        group
        for group in ((result.stats or {}).get("physical_segment_column_groups") or [])
        if str(group.get("segment_id") or "") in physical_ids
    ]
    physical_ordinal_sets = {
        tuple(sorted(int(ordinal) for ordinal in group.get("source_column_ordinals") or []))
        for group in physical_groups
    }
    if len(physical_ordinal_sets) == 1:
        return list(next(iter(physical_ordinal_sets)))
    return _source_column_ordinals(rows)


def _columns_for_block(
    result: TableCaptureResult,
    rows: list[TableRow],
) -> list[TableColumn]:
    vertical_groups = (result.stats or {}).get("vertical_period_column_groups") or []
    physical_groups = (result.stats or {}).get("physical_segment_column_groups") or []
    if not vertical_groups and not physical_groups:
        return list(result.columns)
    active = set(_declared_source_column_ordinals(result, rows))
    return [column for column in result.columns if int(column.ordinal) in active]


def segment_table_blocks(
    result: TableCaptureResult,
    *,
    classification_axis_hint: str | None = None,
) -> tuple[NoteContainer, list[TableBlock]]:
    """Segment a capture conservatively.

    Splits require a layout/semantic boundary (narrative separator, explicit
    source-block change, or materially incompatible numeric topology). If no
    evidence exists, the result stays one block rather than inventing tables.
    """
    layout = build_layout_evidence(result)
    container = NoteContainer(
        container_id=_id("NOTE", result.pdf_sha256, result.note_number, result.start_page, result.table_query),
        source_pdf_sha256=result.pdf_sha256, note_reference=result.note_number,
        note_title=result.located_title or result.table_query, start_pdf_page=result.start_page,
        end_pdf_page=result.end_page, layout_evidence=layout,
    )
    # First preserve the v6.9 narrative/source boundaries, then split each
    # evidence chunk by classification-axis transitions.  Totals alone never
    # end the note container.
    chunks: list[tuple[list[TableRow], str]] = []
    current: list[TableRow] = []
    next_reason = "PRIMARY"
    last_active_segment_id: str | None = None
    for row in result.rows:
        if getattr(row, "excluded_from_table_logic", False):
            if current:
                current.append(row)
            continue
        active_segment_id = str(row.block_id or "")
        source_change = bool(
            current
            and active_segment_id
            and last_active_segment_id
            and active_segment_id != last_active_segment_id
        )
        if _looks_narrative(row) or source_change:
            if current and any(_numeric_cells(item) for item in current):
                chunks.append((current, next_reason))
            current = []
            last_active_segment_id = None
            if _looks_narrative(row):
                next_reason = "NARRATIVE_SEPARATOR"
                continue
            next_reason = "SOURCE_BLOCK_CHANGE"
        current.append(row)
        if active_segment_id:
            last_active_segment_id = active_segment_id
    if current and any(_numeric_cells(item) for item in current):
        chunks.append((current, next_reason))
    if not chunks:
        chunks = [(list(result.rows), "PRIMARY")]

    groups: list[tuple[list[TableRow], str, str]] = []
    for chunk, chunk_reason in chunks:
        assignments = _axis_assignments(chunk)
        if (
            assignments
            and set(assignments) == {"UNRESOLVED"}
            and classification_axis_hint in CLASSIFICATION_AXES - {"UNRESOLVED"}
        ):
            assignments = [classification_axis_hint] * len(chunk)
        active_rows: list[TableRow] = []
        active_axis: str | None = None
        active_reason = chunk_reason
        for row, axis in zip(chunk, assignments):
            if active_rows and axis != active_axis:
                groups.append((active_rows, active_axis or "UNRESOLVED", active_reason))
                active_rows = []
                active_reason = "CLASSIFICATION_AXIS_TRANSITION"
            active_axis = axis
            active_rows.append(row)
        if active_rows:
            groups.append((active_rows, active_axis or "UNRESOLVED", active_reason))

    blocks: list[TableBlock] = []
    for order, (source_rows, axis, split_reason) in enumerate(groups):
        axis = axis if axis in CLASSIFICATION_AXES else "UNRESOLVED"
        role = "PRIMARY_TABLE" if order == 0 else "SECONDARY_TABLE"
        terminal_type = _block_terminal_type(
            source_rows,
            is_final_block=order == len(groups) - 1,
        )
        terminal_type = (
            terminal_type
            if terminal_type in BLOCK_TERMINAL_TYPES
            else "UNRESOLVED"
        )
        title = _AXIS_TITLES.get(
            axis,
            result.located_title
            if order == 0
            else f"{result.located_title}（子表{order + 1}）",
        )
        pages = [r.page for r in source_rows if r.page]
        block_id = _stable_block_id(container.container_id, axis, source_rows)
        rows = copy.deepcopy(source_rows)
        for row in rows:
            row.container_id = container.container_id
            row.table_block_id = block_id
            row.block_order = order
            row.classification_axis = axis
            row.block_role = role
            row.block_terminal_type = terminal_type
            # Block segmentation owns only logical-block dimensions.  It must
            # not rewrite a source-row hierarchy edge; an axis-boundary
            # disagreement is retained in block evidence for review.
        boxes = [r.bbox or {} for r in rows if r.bbox]
        bbox = {
            "x0": min((b.get("x0", b.get("left", 0)) for b in boxes), default=0),
            "top": min((b.get("top", b.get("y0", 0)) for b in boxes), default=0),
            "x1": max((b.get("x1", b.get("right", 0)) for b in boxes), default=0),
            "bottom": max((b.get("bottom", b.get("y1", 0)) for b in boxes), default=0),
        }
        source_column_ordinals = _declared_source_column_ordinals(
            result,
            rows,
        )
        physical_segment_ids = list(dict.fromkeys(
            str(
                getattr(row, "physical_segment_id", None)
                or row.block_id
                or ""
            )
            for row in rows
            if (
                getattr(row, "physical_segment_id", None)
                or row.block_id
            ) and not getattr(row, "excluded_from_table_logic", False)
        ))
        if len(physical_segment_ids) > 1:
            raise ValueError(
                "TABLE_BLOCK_SPANS_MULTIPLE_PHYSICAL_SEGMENTS:"
                f"{physical_segment_ids}"
            )
        physical_segment_records = [
            dict(segment)
            for segment in ((result.stats or {}).get("physical_table_segments") or [])
            if str(segment.get("segment_id") or "") in physical_segment_ids
        ]
        segment_classifications = {
            str(segment.get("classification") or "UNRESOLVED")
            for segment in physical_segment_records
        }
        segment_classification = (
            next(iter(segment_classifications))
            if len(segment_classifications) == 1
            else "UNRESOLVED"
        )
        continuation_parents = {
            str(segment.get("continuation_of_segment_id") or "")
            for segment in physical_segment_records
            if segment.get("continuation_of_segment_id")
        }
        continuation_of_segment_id = (
            next(iter(continuation_parents))
            if len(continuation_parents) == 1
            else None
        )
        topology = _topology(rows, _columns_for_block(result, rows))
        semantic = _semantic_graph(rows)
        reconciliation = _reconciliation(rows)
        unresolved_numeric_block = (
            axis == "UNRESOLVED"
            and terminal_type == "UNRESOLVED"
            and any(_numeric_cells(row) for row in rows)
        )
        status = (
            "READY"
            if (
                topology["consistent"]
                and not unresolved_numeric_block
            )
            else "REVIEW_REQUIRED"
        )
        blocks.append(TableBlock(
            block_id=block_id, block_order=order,
            title=title, role=role, classification_axis=axis,
            block_terminal_type=terminal_type, rows=rows,
            start_pdf_page=min(pages, default=result.start_page), end_pdf_page=max(pages, default=result.end_page),
            bbox=bbox, header_topology=topology, semantic_graph=semantic, reconciliation=reconciliation,
            quality_status=status, evidence={
                "split_reason": split_reason,
                "classification_axis": axis,
                "block_terminal_type": terminal_type,
                "unresolved_numeric_block": unresolved_numeric_block,
                "source_column_ordinals": source_column_ordinals,
                "physical_segment_relation": physical_segment_records,
                "layout_graph": layout,
            },
            segment_classification=segment_classification,
            continuation_of_segment_id=continuation_of_segment_id,
            physical_segment_ids=physical_segment_ids,
        ))
    return container, blocks


def restore_certified_direct_group_rows(
    result: TableCaptureResult,
    pdf_path: Path,
    certified_segments: list[dict[str, Any]],
) -> int:
    """Restore native label-only hierarchy rows merged into the next data row.

    The spatial parser intentionally carries a pending label forward when it
    has no numeric cells.  In a certified direct portfolio table that pending
    label can be an explicit group row (for example, a bond/equity group), not
    a wrapped data-row label.  We split only when the native line is inside the
    certified ROI, directly precedes the data row, and is an exact prefix of
    the machine label.  Golden values are never consulted.
    """
    if len(certified_segments) != 1 or not result.rows:
        return 0
    segment = certified_segments[0]
    try:
        page_number = int(
            segment.get("pdf_page_number") or segment.get("start_page")
        )
    except (TypeError, ValueError):
        return 0
    certified_bbox = segment.get("bbox") or {}
    if not isinstance(certified_bbox, dict):
        return 0
    try:
        x0 = float(certified_bbox["x0"])
        y0 = float(certified_bbox["y0"])
        x1 = float(certified_bbox["x1"])
        y1 = float(certified_bbox["y1"])
    except (KeyError, TypeError, ValueError):
        return 0
    try:
        import fitz

        document = fitz.open(str(Path(pdf_path)))
        page = document[page_number - 1]
        native_lines = []
        for block in page.get_text("dict").get("blocks") or []:
            if int(block.get("type", 0)) != 0:
                continue
            for line in block.get("lines") or []:
                bbox = line.get("bbox") or ()
                if len(bbox) != 4:
                    continue
                line_x0, line_y0, line_x1, line_y1 = map(float, bbox)
                raw_label = "".join(
                    str(span.get("text") or "")
                    for span in line.get("spans") or []
                )
                label = raw_label.strip()
                if (
                    label
                    and line_x0 >= x0 - 2.0
                    and line_x1 <= x0 + (x1 - x0) * 0.48
                    and line_y0 >= y0 - 2.0
                    and line_y1 <= y1 + 2.0
                    and not re.search(
                        r"\d",
                        re.sub(r"[（(]\d+[）)]", "", label),
                    )
                    and not any(token in label for token in (
                        "投资组合（", "投资组合(", "人民币百万元",
                        "账面值", "占总额比例", "注：", "注:",
                    ))
                ):
                    native_lines.append({
                        "label": label,
                        "indented": bool(raw_label[:1].isspace()),
                        "bbox": {
                            "x0": line_x0,
                            "top": line_y0,
                            "x1": line_x1,
                            "bottom": line_y1,
                        },
                    })
        document.close()
    except Exception:
        return 0

    # v6.13 P0-1: Spatial Capture is the sole writer of source_row_id/parent_row_id.
    # Direct recovery retains conflict detection as audit evidence without mutating
    # any TableRow identities or injecting secondary rows.
    emitted_labels: set[str] = set()
    split_discrepancies: list[dict[str, Any]] = []
    for row in result.rows:
        raw_label = str(row.raw_item or row.row_item_raw or "").strip()
        row_bbox = row.bbox or {}
        try:
            row_y0 = float(row_bbox.get("y0", row_bbox.get("top")))
        except (TypeError, ValueError):
            row_y0 = -1.0
        matches = []
        for native in native_lines:
            parent = str(native["label"] or "").strip()
            parent_bottom = float(native["bbox"]["bottom"])
            if (
                parent
                and parent not in emitted_labels
                and raw_label.startswith(parent)
                and len(raw_label) > len(parent)
                and row_y0 >= 0
                and 0.0 <= row_y0 - parent_bottom <= 12.0
            ):
                matches.append(native)
        if matches:
            native = max(matches, key=lambda item: item["bbox"]["bottom"])
            parent = str(native["label"])
            child_label = raw_label[len(parent):].strip()
            if child_label:
                split_discrepancies.append({
                    "row_source_id": row.source_row_id,
                    "row_label": raw_label,
                    "native_prefix": parent,
                    "native_remainder": child_label,
                    "source_bbox": dict(native["bbox"]),
                    "decision": "AUDIT_ONLY_NO_IDENTITY_MUTATION",
                })
                emitted_labels.add(parent)

    native_cursor = 0
    hierarchy_audit: list[dict[str, Any]] = []
    for row in result.rows:
        row_label = str(row.raw_item or row.row_item_raw or "").strip()
        matched_index = None
        for index in range(native_cursor, len(native_lines)):
            if str(native_lines[index]["label"]) == row_label:
                matched_index = index
                break
        if matched_index is None:
            continue
        native = native_lines[matched_index]
        native_cursor = matched_index + 1
        if bool(native.get("indented")) != bool(row.parent_row_id or row.parent_section):
            hierarchy_audit.append({
                "row_source_id": row.source_row_id,
                "row_label": row_label,
                "native_indented": bool(native.get("indented")),
                "certified_parent_row_id": row.parent_row_id,
                "certified_parent_section": row.parent_section,
                "decision": "AUDIT_ONLY_NO_IDENTITY_MUTATION",
            })
    if hierarchy_audit or split_discrepancies:
        result.stats = {
            **dict(result.stats or {}),
            "direct_native_hierarchy_audit": hierarchy_audit,
            "direct_native_split_discrepancies": split_discrepancies,
        }
    return len(split_discrepancies)


def _normalise_certified_direct_logical_axis_rows(
    title: str,
    source_rows: list[TableRow],
    classification_axis: str = "",
) -> list[TableRow]:
    """Remove axis headings and join one-line physical label continuations."""
    rows = copy.deepcopy(source_rows)
    compact_title = re.sub(r"\s+", "", str(title or "")).strip("：:")

    def label(row: TableRow) -> str:
        return str(row.row_item_raw or row.raw_item or "").strip()

    def compact(value: str) -> str:
        return re.sub(r"\s+", "", value).strip("：:")

    expected_axis = str(classification_axis or "").upper()
    if not expected_axis:
        title_boundary = recognise_portfolio_axis_boundary(title)
        if title_boundary.classification_axis in {
            BY_INVESTMENT_OBJECT, BY_ACCOUNTING_MEASUREMENT,
        }:
            expected_axis = str(title_boundary.classification_axis)
    if expected_axis == "PORTFOLIO_SUMMARY":
        # A summary exists only because its prefix contains numeric source rows.
        # Do not emit physical table titles, units or other structural rows as
        # synthetic data; directly adjacent label continuations are handled by
        # the existing continuation join below.
        summary_rows: list[TableRow] = []
        for index, row in enumerate(rows):
            if _numeric_cells(row):
                summary_rows.append(row)
                continue
            row_kind = str(row.row_type or row.row_role or "").upper()
            if row_kind != "SECTION_HEADER" or index + 1 >= len(rows):
                continue
            following = rows[index + 1]
            parent_x0 = float((row.bbox or {}).get("x0", 0.0) or 0.0)
            child_x0 = float((following.bbox or {}).get("x0", 0.0) or 0.0)
            if _numeric_cells(following) and child_x0 > parent_x0 + 4.0:
                summary_rows.append(row)
        rows = summary_rows
    else:
        cleaned: list[TableRow] = []
        for row in rows:
            boundary = recognise_portfolio_axis_boundary(label(row))
            if (
                not _numeric_cells(row)
                and boundary.classification_axis == expected_axis
                and compact(label(row)) == boundary.matched_prefix
            ):
                # Delete the heading itself only.  Never slice away preceding
                # physical rows, which may be valid summary disclosures.
                continue
            if _numeric_cells(row):
                stripped, matched_heading = strip_recognised_axis_prefix(
                    label(row), expected_axis
                )
                if matched_heading and stripped:
                    row.row_item_raw = stripped
                    apply_item_label_normalization(row, stripped)
                    row.label_derivation = "CERTIFIED_AXIS_TITLE_PREFIX_REMOVED"
            cleaned.append(row)
        rows = cleaned

    output: list[TableRow] = []
    index = 0
    while index < len(rows):
        row = rows[index]
        row_kind = str(row.row_type or row.row_role or "").upper()
        if _numeric_cells(row) and index + 1 < len(rows):
            continuation = rows[index + 1]
            current_label = compact(label(row))
            continuation_label = compact(label(continuation))
            continuation_boundary = recognise_portfolio_axis_boundary(
                continuation_label
            )
            current_bbox = row.bbox or {}
            continuation_bbox = continuation.bbox or {}
            try:
                vertical_gap = float(
                    continuation_bbox.get("y0", continuation_bbox.get("top"))
                ) - float(current_bbox.get("y1", current_bbox.get("bottom")))
            except (TypeError, ValueError):
                vertical_gap = 999.0
            if (
                not _numeric_cells(continuation)
                and current_label.endswith("的")
                and 0 < len(continuation_label) <= 12
                and int(row.page) == int(continuation.page)
                and -8.0 <= vertical_gap <= 14.0
                and not continuation_boundary.is_boundary
            ):
                joined = compact(current_label + continuation_label)
                row.footnote_evidence = list(row.footnote_evidence or []) + list(continuation.footnote_evidence or [])
                row.footnote_markers = tuple(dict.fromkeys(list(row.footnote_markers or ()) + list(continuation.footnote_markers or ())))
                row.row_item_raw = joined
                apply_item_label_normalization(row, joined)
                row.label_derivation = "PHYSICAL_TRAILING_LABEL_CONTINUATION_JOIN"
                row.derivation_evidence = {
                    "method": "NUMERIC_ROW_WITH_TRAILING_TEXT_CONTINUATION",
                    "source_labels": [label(row), label(continuation)],
                    "vertical_gap": vertical_gap,
                }
                output.append(row)
                index += 2
                continue
        if row_kind == "SECTION_HEADER" and not _numeric_cells(row):
            parent_x0 = float((row.bbox or {}).get("x0", 0.0) or 0.0)
            children: list[TableRow] = []
            cursor = index + 1
            while cursor < len(rows):
                candidate = rows[cursor]
                candidate_x0 = float(
                    (candidate.bbox or {}).get("x0", 0.0) or 0.0
                )
                if candidate_x0 <= parent_x0 + 4.0:
                    break
                if _numeric_cells(candidate):
                    children.append(candidate)
                cursor += 1
            if len(children) == 1 and index + 1 < len(rows) and children[0] is rows[index + 1]:
                child = children[0]
                joined = compact(label(row) + label(child))
                child.footnote_evidence = list(child.footnote_evidence or []) + list(row.footnote_evidence or [])
                child.footnote_markers = tuple(dict.fromkeys(list(child.footnote_markers or ()) + list(row.footnote_markers or ())))
                child.row_item_raw = joined
                apply_item_label_normalization(child, joined)
                child.label_derivation = "PHYSICAL_WRAPPED_LABEL_JOIN"
                child.derivation_evidence = {
                    "method": "SINGLE_INDENTED_NUMERIC_CHILD_CONTINUATION",
                    "source_labels": [label(row), label(children[0])],
                }
                output.append(child)
                index += 2
                continue
        output.append(row)
        index += 1

    for order, row in enumerate(output, start=1):
        row.row_order = order
    return output


def _numeric_row_identity(row: TableRow) -> str:
    """Immutable numeric source-row identity used by the conservation gate."""
    anchor = _row_physical_anchor(row)
    # Labels may be normalised (heading-prefix removal or physical continuation
    # join); page, bbox and source values are the immutable source-row identity.
    anchor.pop("label", None)
    anchor.pop("row_type", None)
    return json.dumps(anchor, ensure_ascii=False, sort_keys=True)


def _assert_direct_numeric_row_conservation(
    source_blocks: list[TableBlock], normalised_blocks: list[TableBlock]
) -> None:
    from collections import Counter

    before = Counter(
        _numeric_row_identity(row)
        for block in source_blocks for row in list(getattr(block, "rows", []) or [])
        if _numeric_cells(row)
    )
    after = Counter(
        _numeric_row_identity(row)
        for block in normalised_blocks for row in list(getattr(block, "rows", []) or [])
        if _numeric_cells(row)
    )
    if before != after:
        raise ValueError(
            "DIRECT_LOGICAL_AXIS_NUMERIC_ROW_CONSERVATION_FAILED:"
            f"missing={list((before-after).elements())[:3]};"
            f"duplicated={list((after-before).elements())[:3]}"
        )


def coalesce_certified_physical_table_blocks(
    result: TableCaptureResult,
    container: NoteContainer,
    blocks: list[TableBlock],
    *,
    physical_asset_id: str,
    title: str,
    classification_axis: str,
    preserve_logical_axes: bool = False,
) -> list[TableBlock]:
    """Preserve one certified direct-disclosure table as one capture block.

    ``segment_table_blocks`` remains the mandatory generic segmentation step.
    A direct portfolio table, however, is already bounded and certified by its
    physical asset ROI.  Semantic labels inside that ROI must not create note
    child tables.  This helper therefore coalesces only blocks that resolve to
    the same single physical segment; it fails closed for mixed segments.
    """
    if not blocks:
        raise ValueError("DIRECT_PHYSICAL_TABLE_BLOCK_REQUIRED")
    physical_segment_ids = list(dict.fromkeys(
        segment_id
        for block in blocks
        for segment_id in list(block.physical_segment_ids or [])
        if str(segment_id).strip()
    ))
    if len(physical_segment_ids) != 1:
        raise ValueError(
            "DIRECT_PHYSICAL_TABLE_SEGMENT_IDENTITY_CONFLICT:"
            f"{physical_segment_ids}"
        )
    if preserve_logical_axes:
        # The certified asset is one physical ROI but its disclosed axis
        # transitions are independent logical assets.  Keep the generic
        # segmentation results and only stamp their common physical identity.
        source_blocks = copy.deepcopy(blocks)
        for block in blocks:
            if getattr(block, "rows", None):
                block.rows = _normalise_certified_direct_logical_axis_rows(
                    block.title,
                    list(block.rows),
                    str(block.classification_axis or ""),
                )
                block.header_topology = _topology(
                    block.rows,
                    _columns_for_block(result, block.rows),
                )
                block.semantic_graph = _semantic_graph(block.rows)
                block.reconciliation = _reconciliation(block.rows)
                block.quality_status = (
                    "READY"
                    if block.header_topology["consistent"]
                    else "REVIEW_REQUIRED"
                )
            block.evidence = {
                **dict(block.evidence or {}),
                "physical_asset_id": physical_asset_id,
                "certified_direct_physical_table": True,
            }
        _assert_direct_numeric_row_conservation(source_blocks, blocks)
        return blocks
    rows = copy.deepcopy(list(result.rows))
    if not rows or not any(_numeric_cells(row) for row in rows):
        raise ValueError("DIRECT_PHYSICAL_TABLE_NUMERIC_ROWS_REQUIRED")
    block_id = _id(
        "BLOCK",
        container.container_id,
        "DIRECT_PHYSICAL_TABLE",
        physical_asset_id,
        classification_axis,
    )
    terminal_type = _block_terminal_type(rows, is_final_block=True)
    terminal_type = (
        terminal_type
        if terminal_type in BLOCK_TERMINAL_TYPES
        else "UNRESOLVED"
    )
    for row in rows:
        row.container_id = container.container_id
        row.table_block_id = block_id
        row.block_order = 0
        row.classification_axis = classification_axis
        row.block_role = "PRIMARY_TABLE"
        row.block_terminal_type = terminal_type
    boxes = [row.bbox or {} for row in rows if row.bbox]
    bbox = {
        "x0": min(
            (box.get("x0", box.get("left", 0)) for box in boxes),
            default=0,
        ),
        "top": min(
            (box.get("top", box.get("y0", 0)) for box in boxes),
            default=0,
        ),
        "x1": max(
            (box.get("x1", box.get("right", 0)) for box in boxes),
            default=0,
        ),
        "bottom": max(
            (box.get("bottom", box.get("y1", 0)) for box in boxes),
            default=0,
        ),
    }
    topology = _topology(rows, _columns_for_block(result, rows))
    reconciliation = _reconciliation(rows)
    status = "READY" if topology["consistent"] else "REVIEW_REQUIRED"
    segment_classifications = {
        str(block.segment_classification or "UNRESOLVED").upper()
        for block in blocks
    }
    segment_classification = (
        next(iter(segment_classifications))
        if len(segment_classifications) == 1
        else "UNRESOLVED"
    )
    return [TableBlock(
        block_id=block_id,
        block_order=0,
        title=str(title or result.located_title or result.table_query),
        role="PRIMARY_TABLE",
        classification_axis=str(classification_axis or "UNRESOLVED"),
        block_terminal_type=terminal_type,
        rows=rows,
        start_pdf_page=min(
            (row.page for row in rows if row.page),
            default=result.start_page,
        ),
        end_pdf_page=max(
            (row.page for row in rows if row.page),
            default=result.end_page,
        ),
        bbox=bbox,
        header_topology=topology,
        semantic_graph=_semantic_graph(rows),
        reconciliation=reconciliation,
        quality_status=status,
        evidence={
            "split_reason": "CERTIFIED_DIRECT_PHYSICAL_TABLE",
            "classification_axis": classification_axis,
            "block_terminal_type": terminal_type,
            "source_column_ordinals": _declared_source_column_ordinals(
                result,
                rows,
            ),
            "physical_asset_id": physical_asset_id,
            "physical_segment_ids": physical_segment_ids,
            "coalesced_semantic_block_ids": [
                block.block_id for block in blocks
            ],
            "layout_graph": container.layout_evidence,
        },
        segment_classification=segment_classification,
        continuation_of_segment_id=None,
        physical_segment_ids=physical_segment_ids,
    )]


def materialize_block_result(result: TableCaptureResult, block: TableBlock) -> TableCaptureResult:
    """Create a child result without rewriting any raw cells or values."""
    child = copy.deepcopy(result)
    child.table_query = block.title
    child.located_title = block.title
    child.start_page = block.start_pdf_page
    child.end_page = block.end_pdf_page
    child.pages = sorted(set(r.page for r in block.rows if r.page)) or [block.start_pdf_page]
    child.rows = copy.deepcopy(block.rows)
    source_ordinals = list(block.evidence.get("source_column_ordinals") or [])
    all_ordinals = {int(column.ordinal) for column in result.columns}
    if source_ordinals and set(source_ordinals) != all_ordinals:
        selected_columns = [
            copy.deepcopy(column)
            for column in result.columns
            if int(column.ordinal) in set(source_ordinals)
        ]
        ordinal_map = {
            int(column.ordinal): index
            for index, column in enumerate(selected_columns)
        }
        for index, column in enumerate(selected_columns):
            column.ordinal = index
            column.source_column_index = index + 1
        for row in child.rows:
            remapped_cells = []
            for cell in row.cells:
                old_ordinal = int(cell.column_ordinal)
                if old_ordinal not in ordinal_map:
                    continue
                cell.column_ordinal = ordinal_map[old_ordinal]
                cell.source_column_index = ordinal_map[old_ordinal] + 1
                remapped_cells.append(cell)
            row.cells = remapped_cells
        child.columns = selected_columns
    child.stats = {**dict(result.stats or {}), "v69_block_id": block.block_id,
                   "v69_block_role": block.role, "v69_header_topology": block.header_topology,
                   "v69_reconciliation": block.reconciliation,
                   "container_id": block.rows[0].container_id if block.rows else None,
                   "table_block_id": block.block_id,
                   "block_order": block.block_order,
                   "classification_axis": block.classification_axis,
                   "block_role": block.role,
                   "block_terminal_type": block.block_terminal_type,
                   "segment_classification": block.segment_classification,
                   "continuation_of_segment_id": block.continuation_of_segment_id,
                   "physical_segment_ids": list(block.physical_segment_ids),
                   "vertical_period_source_ordinals": source_ordinals}
    child.warnings = list(result.warnings or []) + ([] if block.quality_status == "READY" else ["V69_BLOCK_REVIEW_REQUIRED"])
    return child


def serialise_block(block: TableBlock) -> dict[str, Any]:
    return {
        "block_id": block.block_id, "block_order": block.block_order, "title": block.title,
        "role": block.role, "classification_axis": block.classification_axis,
        "segment_classification": block.segment_classification,
        "continuation_of_segment_id": block.continuation_of_segment_id,
        "physical_segment_ids": list(block.physical_segment_ids),
        "block_terminal_type": block.block_terminal_type,
        "start_pdf_page": block.start_pdf_page, "end_pdf_page": block.end_pdf_page,
        "bbox": block.bbox, "header_topology": block.header_topology,
        "semantic_graph": block.semantic_graph, "reconciliation": block.reconciliation,
        "quality_status": block.quality_status, "evidence": block.evidence,
    }
