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

from table_capture import TableCaptureResult, TableRow


NARRATIVE_TYPES = {"MEMO_TEXT", "NOTE_TEXT", "NARRATIVE", "TEXT"}
TOTAL_TOKENS = ("合计", "总计", "资产总额", "负债合计", "总资产", "总负债")


def _id(prefix: str, *parts: object) -> str:
    material = "|".join(str(p or "") for p in parts)
    return f"{prefix}_{hashlib.sha256(material.encode('utf-8')).hexdigest()[:18]}"


def _numeric_cells(row: TableRow) -> int:
    return sum(c.parsed_number is not None for c in row.cells)


def _looks_narrative(row: TableRow) -> bool:
    raw = str(row.raw_item or row.row_item_raw or "").strip()
    return bool(raw and (_numeric_cells(row) == 0 or row.row_type in NARRATIVE_TYPES) and len(raw) > 16)


def _looks_total(row: TableRow) -> bool:
    label = str(row.raw_item or row.row_item_raw or "")
    return any(token in label for token in TOTAL_TOKENS)


def _topology(rows: list[TableRow]) -> dict[str, Any]:
    widths = [_numeric_cells(r) for r in rows if _numeric_cells(r)]
    signatures = sorted(set(widths))
    return {
        "numeric_widths": signatures,
        "consistent": len(signatures) <= 1,
        "candidate_types": (["YEAR_VALUE"] if len(signatures) == 1 else ["AMBIGUOUS"]),
        "score": 1.0 if len(signatures) == 1 else 0.55,
    }


def _semantic_graph(rows: list[TableRow]) -> dict[str, Any]:
    relations: list[dict[str, Any]] = []
    previous = None
    for row in rows:
        label = str(row.raw_item or row.row_item_raw or "").strip()
        if not label:
            continue
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
        for ordinal, cell in enumerate(total.cells):
            if cell.parsed_number is None:
                continue
            values = [r.cells[ordinal].parsed_number for r in before if len(r.cells) > ordinal and r.cells[ordinal].parsed_number is not None]
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
    return {"status": "PASS" if all(x["pass"] for x in checks) else "WARNING", "checks": checks}


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
    rows: list[TableRow]
    start_pdf_page: int
    end_pdf_page: int
    bbox: dict[str, float]
    header_topology: dict[str, Any]
    semantic_graph: dict[str, Any]
    reconciliation: dict[str, Any]
    quality_status: str
    evidence: dict[str, Any]


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


def segment_table_blocks(result: TableCaptureResult) -> tuple[NoteContainer, list[TableBlock]]:
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
    groups: list[list[TableRow]] = []
    current: list[TableRow] = []
    previous_width: int | None = None
    split_reasons: list[str] = []
    for row in result.rows:
        width = _numeric_cells(row)
        source_change = bool(current and row.block_id and current[-1].block_id and row.block_id != current[-1].block_id)
        topology_change = bool(current and width and previous_width and width != previous_width and _looks_narrative(current[-1]))
        if current and (_looks_narrative(row) or source_change or topology_change):
            if len([r for r in current if _numeric_cells(r)]) >= 1:
                groups.append(current)
                split_reasons.append("NARRATIVE" if _looks_narrative(row) else "SOURCE_OR_TOPOLOGY")
            current = []
            if _looks_narrative(row):
                continue
        current.append(row)
        if width:
            previous_width = width
    if current:
        groups.append(current)
    if not groups:
        groups = [list(result.rows)]

    blocks: list[TableBlock] = []
    for order, rows in enumerate(groups):
        explicit = next((str(r.parent_section or r.raw_item or r.row_item_raw or "").strip() for r in rows if str(r.parent_section or "").strip()), "")
        title = explicit or (result.located_title if order == 0 else f"{result.located_title}（子表{order + 1}）")
        pages = [r.page for r in rows if r.page]
        boxes = [r.bbox or {} for r in rows if r.bbox]
        bbox = {"x0": min((b.get("x0", 0) for b in boxes), default=0), "top": min((b.get("top", 0) for b in boxes), default=0),
                "x1": max((b.get("x1", 0) for b in boxes), default=0), "bottom": max((b.get("bottom", 0) for b in boxes), default=0)}
        topology = _topology(rows)
        semantic = _semantic_graph(rows)
        reconciliation = _reconciliation(rows)
        status = "READY" if topology["consistent"] and reconciliation["status"] != "WARNING" else "REVIEW_REQUIRED"
        blocks.append(TableBlock(
            block_id=_id("BLOCK", container.container_id, order, title, pages), block_order=order,
            title=title, role="PRIMARY_TABLE" if order == 0 else "SECONDARY_TABLE", rows=rows,
            start_pdf_page=min(pages, default=result.start_page), end_pdf_page=max(pages, default=result.end_page),
            bbox=bbox, header_topology=topology, semantic_graph=semantic, reconciliation=reconciliation,
            quality_status=status, evidence={"split_reason": split_reasons[order - 1] if order else "PRIMARY", "layout_graph": layout},
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
    child.rows = block.rows
    child.stats = {**dict(result.stats or {}), "v69_block_id": block.block_id,
                   "v69_block_role": block.role, "v69_header_topology": block.header_topology,
                   "v69_reconciliation": block.reconciliation}
    child.warnings = list(result.warnings or []) + ([] if block.quality_status == "READY" else ["V69_BLOCK_REVIEW_REQUIRED"])
    return child


def serialise_block(block: TableBlock) -> dict[str, Any]:
    return {
        "block_id": block.block_id, "block_order": block.block_order, "title": block.title,
        "role": block.role, "start_pdf_page": block.start_pdf_page, "end_pdf_page": block.end_pdf_page,
        "bbox": block.bbox, "header_topology": block.header_topology,
        "semantic_graph": block.semantic_graph, "reconciliation": block.reconciliation,
        "quality_status": block.quality_status, "evidence": block.evidence,
    }
