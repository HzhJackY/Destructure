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
from typing import Any

from table_capture import TableCaptureResult, TableCell, TableColumn, TableRow


NARRATIVE_TYPES = {"MEMO_TEXT", "NOTE_TEXT", "NARRATIVE", "TEXT"}
TOTAL_TOKENS = ("合计", "总计", "资产总额", "负债合计", "总资产", "总负债")
CLASSIFICATION_AXES = {
    "ASSET_TYPE",
    "MEASUREMENT_COMPOSITION",
    "LISTING_STATUS",
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
_ASSET_SECTION_LABELS = {"债券", "债务工具", "权益工具"}
_MEASUREMENT_TOKENS = ("摊余成本", "累计公允价值变动", "公允价值变动")
_AXIS_TITLES = {
    "ASSET_TYPE": "按资产类型",
    "MEASUREMENT_COMPOSITION": "按计量构成",
    "LISTING_STATUS": "按上市状态",
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
    if preceding and any(_looks_total(row) for row in preceding):
        preceding_axis = "ASSET_TYPE"

    assignments: list[str] = []
    current = preceding_axis
    for index, signal in enumerate(signals):
        if signal:
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
    for index, row in enumerate(rows):
        label = str(row.raw_item or row.row_item_raw or "").strip()
        if not label:
            continue
        parent_label = str(row.parent_section or "").strip()
        if parent_label:
            parent_token = re.sub(r"\s+", "", parent_label).rstrip("：:")
            parent_row = next((
                candidate
                for candidate in reversed(rows[:index])
                if re.sub(
                    r"\s+",
                    "",
                    str(candidate.normalized_item or candidate.raw_item or ""),
                ).rstrip("：:") == parent_token
            ), None)
            relations.append({
                "type": "PARENT_OF",
                "parent": parent_label,
                "child": label,
                "parent_row_order": getattr(parent_row, "row_order", None),
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
            # “其中” is the measurement-composition parent only.  Once a
            # listing-status axis begins, inherited parser context must not
            # leak into the new block.
            if axis == "LISTING_STATUS" and re.sub(
                r"\s+", "", str(row.parent_section or "")
            ).strip("：:") == "其中":
                row.parent_section = None
                row.row_level = 0
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
