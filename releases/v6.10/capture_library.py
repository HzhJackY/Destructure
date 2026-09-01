#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Capture Library + boundary adjudication for v5.3.

Machine extraction is immutable:
  machine_capture_full_long.csv
  machine_capture_full_wide.csv

Research / merge-facing outputs are adjudicated:
  table_raw_long.csv
  table_raw_wide.csv

When automatic hard end-boundary is unavailable, a reviewer selects the last
valid row_order directly from the extracted output. Rows after that cutoff are
preserved as excluded audit evidence, not deleted.
"""

from __future__ import annotations

import datetime as dt
import json
import shutil
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

import fitz
import pandas as pd


@dataclass
class TerminalBoundaryDecision:
    """Structured evidence for a terminal table boundary decision.

    ``status`` is the adjudicated boundary status:
      - ``AUTO_HIGH_CONFIDENCE`` — strong evidence, auto-closed
      - ``AUTO_ACCEPTED_WITH_NON_BLOCKING_WARNING`` — sufficient evidence with
        low-risk caveat; merge-ready but annotated
      - ``REVIEW_REQUIRED`` — human must verify the last valid row
      - ``CONTINUATION_REQUIRED`` — cross-page or cross-block continuation needed
      - ``FAILED`` — boundary adjudication could not complete
    """
    status: str = "UNASSESSED"
    reason: str = ""
    sub_decision: str = ""
    evidence_chain: list[str] = field(default_factory=list)
    method: str = ""
    confidence: str = ""
    warnings: list[str] = field(default_factory=list)


MERGE_READY_STATUSES = {
    "HARD_BOUNDARY_CONFIRMED",
    "AUTO_HIGH_CONFIDENCE",
    "AUTO_ACCEPTED_WITH_NON_BLOCKING_WARNING",
    "HUMAN_CONFIRMED",
}


def _explicit_terminal_total_is_safe(result: dict[str, Any], *, reason: str, warnings: str) -> bool:
    """Return true only for a self-contained, explicitly totalled table.

    A next-note heading is strong evidence, but it is not the only valid PDF
    boundary.  Short note tables frequently end on an explicit ``合计`` row
    and the next disclosure starts outside the captured region.  Do not use
    this shortcut when the extractor signals continuation/truncation.
    """
    if any(token in (reason + " " + warnings).lower() for token in (
        "max_pages", "continu", "跨页", "续表",
    )):
        return False
    rows = list(result.get("rows") or [])
    if not rows:
        return False
    last = rows[-1]
    role = str(last.get("row_role") or last.get("row_type") or "").upper()
    label = str(
        last.get("raw_item") or last.get("row_item_raw")
        or last.get("normalized_item") or ""
    ).strip()
    return role == "TOTAL" or label in {"合计", "总计", "资产合计", "负债合计"}


def _page_terminal_reconciled_block_is_safe(
    result: dict[str, Any], *, reason: str, warnings: str
) -> tuple[bool, str]:
    """Recognise a complete table block that naturally ends at a PDF page.

    A note can contain several tables.  The next *note* heading is useful
    evidence, but it is not required when the selected table has a reconciled
    total, reaches the terminal area of its page, and only contains a labelled
    ``其中``/composition breakdown after that total.  This deliberately does
    not accept tables without an arithmetic/structural terminal signal, so a
    genuine cross-page continuation remains review-required.

    Returns ``(is_safe, sub_decision)`` where sub_decision describes the
    specific safety condition met.
    """
    if reason != "boundary_unresolved" or "max_pages" in warnings.lower():
        return False, ""
    stats = result.get("stats") or {}
    evidence = stats.get("boundary_evidence") or {}
    if str(evidence.get("method") or "") != "NO_PEER_HEADING_FOUND":
        return False, ""
    if stats.get("post_total_disclosure_not_merged"):
        return False, ""
    reconciliation = stats.get("v69_reconciliation") or {}
    if str(reconciliation.get("status") or "").upper() != "PASS":
        return False, ""
    topology = stats.get("v69_header_topology") or {}
    if not bool(topology.get("consistent")):
        return False, ""
    rows = list(result.get("rows") or [])
    if not rows:
        return False, ""
    total_positions = [
        index for index, row in enumerate(rows)
        if str(row.get("row_role") or row.get("row_type") or "").upper() in {"TOTAL", "SUBTOTAL"}
        or str(row.get("raw_item") or row.get("row_item_raw") or "").strip() in {"合计", "总计"}
    ]
    if not total_positions:
        return False, ""
    # Any material after the total must remain a labelled composition/breakdown
    # row.  Prose, anonymous values and ambiguous rows mean this is not safe.
    for row in rows[total_positions[-1] + 1:]:
        role = str(row.get("row_role") or row.get("row_type") or "").upper()
        label = str(row.get("raw_item") or row.get("row_item_raw") or "").strip()
        if role in {"NOTE_TEXT", "MEMO_TEXT", "AMBIGUOUS", "IMPLICIT_ROW_CANDIDATE"}:
            return False, ""
        if not label:
            return False, ""
    roi = stats.get("roi") or {}
    try:
        terminal_y = float(roi.get("end_y") or 0)
        last_bbox = rows[-1].get("bbox") or rows[-1].get("source_bbox") or {}
        last_y = float(last_bbox.get("y1") or last_bbox.get("bottom") or 0)
    except (TypeError, ValueError, AttributeError):
        return False, ""
    # The final record must reach the lower page region.  This distinguishes a
    # naturally completed page from a mid-page truncation that simply lacks a
    # following note heading.
    if not (terminal_y > 0 and last_y / terminal_y >= 0.80):
        # v6.10: when reconciliation and topology pass but the table sits in
        # mid-page (e.g. same note has another table block below), check
        # whether the next page starts a new table block rather than a
        # continuation — i.e. the next page's first heading resets the header
        # signature.  If the conditions are otherwise met except for page
        # position, return a non-blocking warning instead of requiring review.
        if _same_note_different_block_signal(result, rows, total_positions[-1]):
            return True, "SAME_NOTE_DIFFERENT_BLOCK"
        return False, ""
    return True, "PAGE_TERMINAL_RECONCILED"


def _same_note_different_block_signal(
    result: dict[str, Any], rows: list[dict[str, Any]], total_idx: int
) -> bool:
    """Detect that the next page contains a different table block within the
    same note — not a continuation of the current table.

    Heuristics:
    1. The next page's first labelled row has a different header signature
       (row_label pattern reset), OR
    2. There is a clear SECTION row immediately after the total that starts a
       new semantic block on the same page or next page.
    """
    stats = result.get("stats") or {}
    next_page_info = stats.get("next_page_first_rows") or {}
    if not next_page_info:
        # Look for a SECTION row after the total within the current page
        post_total = rows[total_idx + 1:]
        section_after = [
            r for r in post_total
            if str(r.get("row_role") or "").upper() in {"SECTION", "DETAIL"}
            and r.get("raw_item")
        ]
        if section_after:
            return True
        return False
    # Check if next page's first labelled row looks like a new table heading
    first_label = str(next_page_info.get("first_label") or "")
    first_role = str(next_page_info.get("first_role") or "").upper()
    if first_role in {"SECTION", "NOTE_TEXT"}:
        return True
    # If next page starts with paragraph text rather than table data, it's a
    # new block
    if first_label and not any(
        str(r.get("raw_item") or "") == first_label for r in rows
    ):
        return True
    return False


def is_orphan_numeric_noise(rows: list[dict[str, Any]], index: int) -> bool:
    """Detect a layout residue, never rewrite the immutable source row.

    A blank-label one/two-digit token between two labelled rows is commonly a
    footnote marker split into the numeric column.  It is not an implicit
    economic row.  Larger values, mixed text, endpoints and label-bearing rows
    remain review-required.
    """
    if index <= 0 or index >= len(rows) - 1:
        return False
    row = rows[index]
    if str(row.get("row_role") or "") != "IMPLICIT_ROW_CANDIDATE":
        return False
    if row.get("raw_item") or row.get("row_item_raw"):
        return False
    cells = list(row.get("cells") or [])
    if len(cells) != 1:
        return False
    token = str(cells[0].get("raw") or cells[0].get("raw_value") or "").strip()
    if not token.isdigit() or len(token) > 2:
        return False
    before, after = rows[index - 1], rows[index + 1]
    return bool(
        (before.get("raw_item") or before.get("row_item_raw"))
        and (after.get("raw_item") or after.get("row_item_raw"))
    )


def human_layout_noise_orders(result: dict[str, Any]) -> set[int]:
    """Return only explicitly adjudicated layout-noise rows.

    The machine row is retained verbatim in ``rows``.  A reviewer decision is
    stored separately so a revision can exclude a page marker, footer residue,
    or other non-economic token from official/merge-facing outputs without
    rewriting the underlying extraction evidence.
    """
    orders: set[int] = set()
    for decision in result.get("human_row_noise_review") or []:
        if str(decision.get("decision") or "") != "LAYOUT_NOISE_EXCLUDED":
            continue
        try:
            orders.add(int(decision.get("row_order")))
        except (TypeError, ValueError):
            continue
    return orders


def derive_boundary_status(result: dict[str, Any]) -> str:
    """Adjudicate terminal table boundary status.

    Returns one of:
      - ``HARD_BOUNDARY_CONFIRMED`` — explicit next-note ordinal found
      - ``AUTO_HIGH_CONFIDENCE`` — strong auto-closure evidence
      - ``AUTO_ACCEPTED_WITH_NON_BLOCKING_WARNING`` — sufficient evidence with
        low-risk caveat (e.g. same-note different-block)
      - ``REVIEW_REQUIRED`` — human must verify
    """
    explicit = str(result.get("boundary_status") or "").strip()
    stats = result.get("stats") or {}
    reason = str(stats.get("boundary_reason") or "")
    evidence = stats.get("boundary_evidence") or {}
    confidence = str(stats.get("boundary_confidence") or "")
    method = str(evidence.get("method") or "")
    warnings = " ".join(str(x) for x in (result.get("warnings") or []))

    # --- explicit persisted status re-evaluation ---
    if explicit == "REVIEW_REQUIRED":
        terminal_safe = _explicit_terminal_total_is_safe(result, reason=reason, warnings=warnings)
        page_safe, sub = _page_terminal_reconciled_block_is_safe(result, reason=reason, warnings=warnings)
        if terminal_safe or (page_safe and sub == "PAGE_TERMINAL_RECONCILED"):
            return "AUTO_HIGH_CONFIDENCE"
        if page_safe and sub == "SAME_NOTE_DIFFERENT_BLOCK":
            return "AUTO_ACCEPTED_WITH_NON_BLOCKING_WARNING"

    # A stale explicit HARD flag must not override contradictory current
    # evidence produced by an older next-peer implementation.
    if explicit == "HARD_BOUNDARY_CONFIRMED" and (
        reason.startswith("next_peer_heading_")
        or method == "NEXT_PEER_HEADING"
        or confidence in {"LOW", "MEDIUM"}
    ):
        return "REVIEW_REQUIRED"
    if explicit and explicit != "UNASSESSED":
        return explicit

    engine = str(stats.get("engine") or "")

    if (
        reason.startswith("next_note_")
        and confidence == "HIGH"
        and method == "NEXT_NOTE_ORDINAL"
    ):
        return "HARD_BOUNDARY_CONFIRMED"

    # --- auto-closure evaluation ---
    terminal_safe = _explicit_terminal_total_is_safe(result, reason=reason, warnings=warnings)
    page_safe, sub = _page_terminal_reconciled_block_is_safe(result, reason=reason, warnings=warnings)
    if terminal_safe or (page_safe and sub == "PAGE_TERMINAL_RECONCILED"):
        return "AUTO_HIGH_CONFIDENCE"
    if page_safe and sub == "SAME_NOTE_DIFFERENT_BLOCK":
        return "AUTO_ACCEPTED_WITH_NON_BLOCKING_WARNING"

    if "max_pages" in reason or "max_pages" in warnings or "未发现下一附注编号" in warnings:
        return "REVIEW_REQUIRED"
    if "LEGACY" in engine.upper():
        return "REVIEW_REQUIRED"

    return "REVIEW_REQUIRED"


def derive_boundary_decision(result: dict[str, Any]) -> TerminalBoundaryDecision:
    """Return a structured :class:`TerminalBoundaryDecision` with evidence chain.

    Use this when the caller needs the sub-decision and evidence trail in
    addition to the final status string.
    """
    stats = result.get("stats") or {}
    evidence = stats.get("boundary_evidence") or {}
    reason = str(stats.get("boundary_reason") or "")
    method = str(evidence.get("method") or "")
    confidence = str(stats.get("boundary_confidence") or "")
    warnings = " ".join(str(x) for x in (result.get("warnings") or []))

    status = derive_boundary_status(result)
    decision = TerminalBoundaryDecision(
        status=status,
        reason=reason,
        method=method,
        confidence=confidence,
    )

    # Build evidence chain
    chain = []
    if method:
        chain.append(f"method={method}")
    if confidence:
        chain.append(f"confidence={confidence}")
    if reason:
        chain.append(f"reason={reason}")

    terminal_safe = _explicit_terminal_total_is_safe(result, reason=reason, warnings=warnings)
    page_safe, sub = _page_terminal_reconciled_block_is_safe(result, reason=reason, warnings=warnings)

    if terminal_safe:
        chain.append("explicit_terminal_total_safe")
        decision.sub_decision = "EXPLICIT_TOTAL"
    elif page_safe:
        chain.append(f"page_terminal_safe:{sub}")
        decision.sub_decision = sub
    elif "max_pages" in reason or "max_pages" in warnings:
        chain.append("max_pages_truncation")
        decision.sub_decision = "TRUNCATION"
    else:
        decision.sub_decision = "INCONCLUSIVE"

    reconciliation = stats.get("v69_reconciliation") or {}
    if reconciliation:
        chain.append(f"reconciliation={reconciliation.get('status', 'UNKNOWN')}")
    topology = stats.get("v69_header_topology") or {}
    if topology:
        chain.append(f"topology_consistent={topology.get('consistent', False)}")

    decision.evidence_chain = chain
    return decision



def derive_header_status(result: dict[str, Any]) -> str:
    from header_review import derive_header_dimension_status
    return derive_header_dimension_status(result)


def capture_readiness(result: dict[str, Any]) -> dict[str, Any]:
    boundary = derive_boundary_status(result)
    header = derive_header_status(result)
    boundary_ready = boundary in MERGE_READY_STATUSES
    header_ready = header in {"AUTO_CONFIRMED", "HUMAN_CONFIRMED"}
    blockers = []
    if not boundary_ready:
        blockers.append(f"BOUNDARY:{boundary}")
    if not header_ready:
        blockers.append(f"HEADER:{header}")
    stats = result.get("stats") or {}
    rows = list(result.get("rows") or [])
    boundary_review = result.get("boundary_review") or {}
    cutoff = (
        boundary_review.get("last_included_row_order")
        if str(boundary_review.get("status") or "") == "HUMAN_CONFIRMED"
        else None
    )
    if cutoff is not None:
        rows = [
            row for row in rows
            if int(row.get("row_order") or 0) <= int(cutoff)
        ]
    mixed_from_rows = sum(
        1
        for row in rows
        for cell in (row.get("cells") or [])
        if str(cell.get("cell_role") or "") == "MIXED"
    )
    mixed_count = (
        mixed_from_rows
        if cutoff is not None
        else max(int(stats.get("mixed_cell_count") or 0), mixed_from_rows)
    )
    if mixed_count:
        blockers.append(f"MIXED_CELL:{mixed_count}")
    unresolved_implicit = 0
    human_noise = human_layout_noise_orders(result)
    for index, row in enumerate(rows):
        if not bool(row.get("cells")):
            continue
        try:
            row_order = int(row.get("row_order") or 0)
        except (TypeError, ValueError):
            row_order = 0
        if row_order in human_noise:
            continue
        role = str(row.get("row_role") or "")
        # v6.10: ANONYMOUS_NUMERIC_ROW is the default for blank-label numeric
        # rows — it is not an unresolved implicit row.  Only the legacy
        # IMPLICIT_ROW_CANDIDATE (pre-v6.10) or fully anonymous rows without
        # any role signal require human review.
        if role == "ANONYMOUS_NUMERIC_ROW":
            continue  # not unresolved — default classification, not a blocker
        if role == "IMPLICIT_TOTAL":
            ds = str(row.get("derived_status") or "")
            if ds in ("DERIVED_EXCLUDED", "SUPPRESSED_BY_EXPLICIT_TOTAL"):
                continue  # explicitly excluded or suppressed — not a blocker
            if ds != "REQUIRED_DERIVED_TOTAL_UNRESOLVED":
                continue  # non-blocking derived total — not a blocker
            # Only REQUIRED_DERIVED_TOTAL_UNRESOLVED is a genuine blocker
            unresolved_implicit += 1
            continue
        if role == "IMPLICIT_ROW_CANDIDATE" and not is_orphan_numeric_noise(rows, index):
            unresolved_implicit += 1
        elif not role and row.get("raw_item") is None:
            # Legacy schemas had no row_role.  An anonymous numeric row is not
            # merge-safe unless it was explicitly certified as IMPLICIT_TOTAL.
            unresolved_implicit += 1
    if unresolved_implicit:
        blockers.append(f"IMPLICIT_ROW_UNRESOLVED:{unresolved_implicit}")
    # v6.9 adds a third, independent quality gate.  A visually plausible
    # table with ambiguous header topology or an explicit arithmetic warning
    # must remain reviewable rather than silently becoming merge-ready.
    v69_topology = stats.get("v69_header_topology") or {}
    v69_reconciliation = stats.get("v69_reconciliation") or {}
    topology_ready = bool(v69_topology.get("consistent", True))
    reconciliation_ready = str(v69_reconciliation.get("status") or "NOT_TESTABLE") != "WARNING"
    if not topology_ready:
        blockers.append("V69_HEADER_TOPOLOGY_AMBIGUOUS")
    if not reconciliation_ready:
        blockers.append("V69_RECONCILIATION_WARNING")
    ready = boundary_ready and header_ready and not mixed_count and not unresolved_implicit and topology_ready and reconciliation_ready
    return {
        "boundary_status": boundary,
        "header_dimension_status": header,
        "semantic_status": "AUTO_CONFIRMED" if not mixed_count and not unresolved_implicit else "REVIEW_REQUIRED",
        "capture_quality_status": "READY" if ready else "REVIEW_REQUIRED",
        "mixed_cell_count": mixed_count,
        "unresolved_implicit_rows": unresolved_implicit,
        "v69_header_topology": v69_topology,
        "v69_reconciliation": v69_reconciliation,
        "merge_ready": ready,
        "merge_blockers": blockers,
    }


def load_capture_result(run_dir: Path) -> dict[str, Any]:
    path = Path(run_dir) / "table_capture_result.json"
    return json.loads(path.read_text(encoding="utf-8"))


def save_capture_result(run_dir: Path, data: dict[str, Any]) -> None:
    path = Path(run_dir) / "table_capture_result.json"
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def ensure_capture_metadata(
    run_dir: Path,
    source_pdf_display: Optional[str] = None,
    table_query: Optional[str] = None,
) -> dict[str, Any]:
    run_dir = Path(run_dir)
    path = run_dir / "capture_metadata.json"
    result = load_capture_result(run_dir)

    if path.exists():
        data = json.loads(path.read_text(encoding="utf-8"))
    else:
        source_pdf_display = source_pdf_display or str(result.get("pdf_name") or "")
        source_pdf_display = re.sub(r"^[0-9a-fA-F]{12}_", "", source_pdf_display)
        table_query = table_query or str(result.get("table_query") or "")
        note_no = str(result.get("note_number") or "").strip()
        label = " · ".join(
            x for x in [
                Path(source_pdf_display).stem,
                f"{note_no}. {table_query}" if note_no else table_query,
            ]
            if x
        )
        data = {
            "run_id": run_dir.name,
            "display_name": label or run_dir.name,
            "note": "",
            "source_pdf_display": source_pdf_display,
            "table_query": table_query,
            "created_at": dt.datetime.fromtimestamp(run_dir.stat().st_mtime).isoformat(timespec="seconds"),
        }

    data.setdefault("lifecycle_status", "ACTIVE")
    data.setdefault("pre_trash_status", None)
    data.setdefault("batch_id", f"LEGACY_SINGLE::{run_dir.name}")
    data.setdefault("producer_version", str(result.get("producer_version") or "legacy"))
    data.setdefault("header_parser", str((result.get("stats") or {}).get("header_parser") or "legacy"))
    data.setdefault("asset_schema_version", "6.1")

    readiness = capture_readiness(result)
    data["boundary_status"] = readiness["boundary_status"]
    data["header_dimension_status"] = readiness["header_dimension_status"]
    data["semantic_status"] = readiness["semantic_status"]
    data["capture_quality_status"] = readiness["capture_quality_status"]
    data["mixed_cell_count"] = readiness["mixed_cell_count"]
    data["unresolved_implicit_rows"] = readiness["unresolved_implicit_rows"]
    lifecycle = str(data.get("lifecycle_status") or "ACTIVE")
    blockers = list(readiness["merge_blockers"])
    if lifecycle != "ACTIVE":
        blockers.append(f"LIFECYCLE:{lifecycle}")
    data["merge_ready"] = bool(readiness["merge_ready"] and lifecycle == "ACTIVE")
    data["merge_blockers"] = blockers
    data["start_page"] = result.get("start_page")
    data["end_page"] = result.get("end_page")
    data["row_count_machine"] = len(result.get("rows") or [])

    official_long = run_dir / "table_raw_long.csv"
    if official_long.exists():
        try:
            df = pd.read_csv(official_long)
            data["row_count_official"] = int(df["row_order"].nunique()) if "row_order" in df else len(df)
        except Exception:
            data["row_count_official"] = None

    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return data


def update_capture_metadata(
    run_dir: Path,
    display_name: Optional[str] = None,
    note: Optional[str] = None,
) -> dict[str, Any]:
    data = ensure_capture_metadata(run_dir)
    if display_name is not None:
        data["display_name"] = str(display_name).strip() or data.get("display_name") or Path(run_dir).name
    if note is not None:
        data["note"] = str(note)
    (Path(run_dir) / "capture_metadata.json").write_text(
        json.dumps(data, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return data


def ensure_machine_full_artifacts(run_dir: Path) -> None:
    run_dir = Path(run_dir)
    pairs = [
        ("table_raw_long.csv", "machine_capture_full_long.csv"),
        ("table_raw_wide.csv", "machine_capture_full_wide.csv"),
    ]
    for src_name, machine_name in pairs:
        src = run_dir / src_name
        dst = run_dir / machine_name
        if src.exists() and not dst.exists():
            shutil.copy2(src, dst)


def _dictionary_from_long(long_df: pd.DataFrame) -> pd.DataFrame:
    if long_df.empty:
        return pd.DataFrame(columns=[
            "normalized_item", "example_raw_item", "canonical_item",
            "category", "mapping_status", "mapping_note",
        ])
    work = long_df.copy()
    if "row_type" in work:
        work = work[work["row_type"].astype(str) != "SECTION_HEADER"]
    rows = []
    seen = set()
    for _, row in work.iterrows():
        norm = str(row.get("normalized_item") or "").strip()
        if not norm or norm in seen:
            continue
        seen.add(norm)
        rows.append({
            "normalized_item": norm,
            "example_raw_item": row.get("raw_item"),
            "canonical_item": "",
            "category": "",
            "mapping_status": "UNMAPPED",
            "mapping_note": "",
        })
    return pd.DataFrame(rows)


def _wide_filter_by_row_order(full_wide: pd.DataFrame, cutoff: int) -> pd.DataFrame:
    if full_wide.empty or "row_order" not in full_wide.columns:
        return full_wide.copy()
    return full_wide[pd.to_numeric(full_wide["row_order"], errors="coerce") <= int(cutoff)].copy()


def _rewrite_capture_excel(run_dir: Path) -> None:
    run_dir = Path(run_dir)
    official_long = pd.read_csv(run_dir / "table_raw_long.csv") if (run_dir / "table_raw_long.csv").exists() else pd.DataFrame()
    official_wide = pd.read_csv(run_dir / "table_raw_wide.csv") if (run_dir / "table_raw_wide.csv").exists() else pd.DataFrame()
    dictionary = pd.read_csv(run_dir / "table_item_dictionary.csv") if (run_dir / "table_item_dictionary.csv").exists() else pd.DataFrame()
    machine_long = pd.read_csv(run_dir / "machine_capture_full_long.csv") if (run_dir / "machine_capture_full_long.csv").exists() else pd.DataFrame()
    machine_wide = pd.read_csv(run_dir / "machine_capture_full_wide.csv") if (run_dir / "machine_capture_full_wide.csv").exists() else pd.DataFrame()
    excluded = pd.read_csv(run_dir / "boundary_excluded_rows.csv") if (run_dir / "boundary_excluded_rows.csv").exists() else pd.DataFrame()
    reconciliation = pd.read_csv(run_dir / "table_reconciliation_audit.csv") if (run_dir / "table_reconciliation_audit.csv").exists() else pd.DataFrame()
    parser_candidates = pd.DataFrame()
    parser_candidates_path = run_dir / "header_parser_candidates.csv"
    if parser_candidates_path.exists() and parser_candidates_path.stat().st_size > 3:
        try:
            parser_candidates = pd.read_csv(parser_candidates_path)
        except pd.errors.EmptyDataError:
            parser_candidates = pd.DataFrame()
    result_data = {}
    result_path = run_dir / "table_capture_result.json"
    if result_path.exists():
        try:
            result_data = json.loads(result_path.read_text(encoding="utf-8"))
        except Exception:
            result_data = {}
    arbitration = (result_data.get("stats") or {}).get("header_arbitration") or {}
    topology_review = result_data.get("column_topology_review") or {}

    with pd.ExcelWriter(run_dir / "table_capture.xlsx", engine="openpyxl") as writer:
        official_long.to_excel(writer, sheet_name="raw_long", index=False)
        official_wide.to_excel(writer, sheet_name="raw_wide", index=False)
        dictionary.to_excel(writer, sheet_name="item_dictionary", index=False)
        machine_long.to_excel(writer, sheet_name="machine_full_long", index=False)
        machine_wide.to_excel(writer, sheet_name="machine_full_wide", index=False)
        excluded.to_excel(writer, sheet_name="boundary_excluded", index=False)
        reconciliation.to_excel(writer, sheet_name="reconciliation", index=False)
        parser_candidates.to_excel(writer, sheet_name="header_candidates", index=False)
        pd.DataFrame([{
            "mode": arbitration.get("mode"),
            "auto_selected_parser": arbitration.get("auto_selected_parser"),
            "selected_parser": arbitration.get("selected_parser"),
            "selection_reason": arbitration.get("selection_reason"),
            "auto_abstain": arbitration.get("auto_abstain"),
        }]).to_excel(writer, sheet_name="header_arbitration", index=False)
        pd.DataFrame(topology_review.get("actions") or []).to_excel(
            writer, sheet_name="topology_review", index=False
        )


def initialize_capture_library_run(
    run_dir: Path,
    source_pdf_display: str,
    table_query: str,
    *,
    batch_id: Optional[str] = None,
    supersedes_capture_id: Optional[str] = None,
) -> dict[str, Any]:
    run_dir = Path(run_dir)
    ensure_machine_full_artifacts(run_dir)

    result = load_capture_result(run_dir)
    result["boundary_status"] = derive_boundary_status(result)
    result.setdefault("boundary_review", None)
    save_capture_result(run_dir, result)

    from reconciliation import write_reconciliation_audit
    write_reconciliation_audit(run_dir)
    metadata = ensure_capture_metadata(
        run_dir,
        source_pdf_display=source_pdf_display,
        table_query=table_query,
    )
    from asset_management import ensure_asset_metadata, set_capture_batch
    metadata = ensure_asset_metadata(
        run_dir,
        batch_id=batch_id,
        supersedes_capture_id=supersedes_capture_id,
    )
    if batch_id:
        metadata = set_capture_batch(
            run_dir,
            batch_id,
            supersedes_capture_id=supersedes_capture_id,
        )
    _rewrite_capture_excel(run_dir)
    try:
        from registry_bridge import sync_capture_run
        sync_capture_run(run_dir)
    except Exception:
        pass
    return ensure_capture_metadata(run_dir)


def apply_boundary_review(
    run_dir: Path,
    last_included_row_order: int,
    reviewer_note: str = "",
) -> dict[str, Any]:
    run_dir = Path(run_dir)
    ensure_machine_full_artifacts(run_dir)

    machine_long_path = run_dir / "machine_capture_full_long.csv"
    machine_wide_path = run_dir / "machine_capture_full_wide.csv"
    if not machine_long_path.exists():
        raise FileNotFoundError("缺少 machine_capture_full_long.csv，无法做可审计边界裁决。")

    full_long = pd.read_csv(machine_long_path)
    full_wide = pd.read_csv(machine_wide_path) if machine_wide_path.exists() else pd.DataFrame()

    if "row_order" not in full_long.columns:
        raise ValueError("机器长表缺少 row_order，无法指定最后有效记录。")

    row_orders = pd.to_numeric(full_long["row_order"], errors="coerce")
    valid_orders = sorted({int(x) for x in row_orders.dropna().tolist()})
    cutoff = int(last_included_row_order)
    if cutoff not in valid_orders:
        raise ValueError(f"指定 row_order={cutoff} 不存在。")

    official_long = full_long[row_orders <= cutoff].copy()
    excluded = full_long[row_orders > cutoff].copy()
    official_wide = _wide_filter_by_row_order(full_wide, cutoff)
    dictionary = _dictionary_from_long(official_long)

    official_long.to_csv(run_dir / "table_raw_long.csv", index=False, encoding="utf-8-sig")
    official_wide.to_csv(run_dir / "table_raw_wide.csv", index=False, encoding="utf-8-sig")
    dictionary.to_csv(run_dir / "table_item_dictionary.csv", index=False, encoding="utf-8-sig")
    excluded.to_csv(run_dir / "boundary_excluded_rows.csv", index=False, encoding="utf-8-sig")

    last_rows = full_long[row_orders == cutoff]
    last_item = (
        str(last_rows["raw_item"].dropna().iloc[0])
        if "raw_item" in last_rows and not last_rows["raw_item"].dropna().empty
        else ""
    )

    review = {
        "status": "HUMAN_CONFIRMED",
        "last_included_row_order": cutoff,
        "last_included_raw_item": last_item,
        "excluded_table_rows": int(excluded["row_order"].nunique()) if "row_order" in excluded else 0,
        "excluded_long_records": int(len(excluded)),
        "reviewed_at": dt.datetime.now().isoformat(timespec="seconds"),
        "reviewer_note": str(reviewer_note or ""),
    }
    (run_dir / "boundary_review.json").write_text(
        json.dumps(review, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    result = load_capture_result(run_dir)
    result["boundary_status"] = "HUMAN_CONFIRMED"
    result["boundary_review"] = review
    save_capture_result(run_dir, result)

    # Rebuild official outputs using any effective human-reviewed header
    # dimensions. This prevents a boundary review from overwriting header fixes.
    from header_review import rematerialize_official_capture
    materialized = rematerialize_official_capture(run_dir)

    metadata = ensure_capture_metadata(run_dir)
    metadata["boundary_status"] = "HUMAN_CONFIRMED"
    metadata["row_count_official"] = int(materialized.get("official_table_rows", 0))
    (run_dir / "capture_metadata.json").write_text(
        json.dumps(metadata, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    _rewrite_capture_excel(run_dir)
    try:
        from registry_bridge import sync_capture_run
        sync_capture_run(run_dir)
    except Exception:
        pass
    return review


def reset_boundary_review(run_dir: Path) -> None:
    run_dir = Path(run_dir)
    ensure_machine_full_artifacts(run_dir)
    shutil.copy2(run_dir / "machine_capture_full_long.csv", run_dir / "table_raw_long.csv")
    if (run_dir / "machine_capture_full_wide.csv").exists():
        shutil.copy2(run_dir / "machine_capture_full_wide.csv", run_dir / "table_raw_wide.csv")
    full_long = pd.read_csv(run_dir / "table_raw_long.csv")
    _dictionary_from_long(full_long).to_csv(
        run_dir / "table_item_dictionary.csv",
        index=False,
        encoding="utf-8-sig",
    )
    (run_dir / "boundary_excluded_rows.csv").unlink(missing_ok=True)
    (run_dir / "boundary_review.json").unlink(missing_ok=True)

    result = load_capture_result(run_dir)
    result["boundary_status"] = derive_boundary_status({
        **result,
        "boundary_status": "UNASSESSED",
    })
    result["boundary_review"] = None
    save_capture_result(run_dir, result)
    from header_review import rematerialize_official_capture
    rematerialize_official_capture(run_dir)
    ensure_capture_metadata(run_dir)
    try:
        from registry_bridge import sync_capture_run
        sync_capture_run(run_dir)
    except Exception:
        pass


def capture_merge_ready(run_dir: Path) -> bool:
    result = load_capture_result(run_dir)
    meta = ensure_capture_metadata(run_dir)
    return bool(
        capture_readiness(result)["merge_ready"]
        and str(meta.get("lifecycle_status") or "ACTIVE") == "ACTIVE"
    )


def capture_record(run_dir: Path) -> dict[str, Any]:
    run_dir = Path(run_dir)
    meta = ensure_capture_metadata(run_dir)
    result = load_capture_result(run_dir)
    readiness = capture_readiness(result)
    return {
        **meta,
        "run_dir": str(run_dir),
        "run_id": run_dir.name,
        "boundary_status": readiness["boundary_status"],
        "header_dimension_status": readiness["header_dimension_status"],
        "merge_blockers": meta.get("merge_blockers") or readiness["merge_blockers"],
        "pdf_name": result.get("pdf_name"),
        "table_query": result.get("table_query"),
        "note_number": result.get("note_number"),
        "start_page": result.get("start_page"),
        "end_page": result.get("end_page"),
        "merge_ready": bool(
            readiness["merge_ready"]
            and str(meta.get("lifecycle_status") or "ACTIVE") == "ACTIVE"
        ),
    }


def list_capture_records(table_capture_dir: Path) -> list[dict[str, Any]]:
    root = Path(table_capture_dir)
    rows = []
    for p in root.iterdir():
        if not p.is_dir() or p.name == "_trash":
            continue
        if (p / "table_capture_result.json").exists():
            try:
                rows.append(capture_record(p))
            except Exception:
                continue
    rows.sort(key=lambda r: Path(r["run_dir"]).stat().st_mtime, reverse=True)
    return rows


def soft_delete_capture(run_dir: Path, trash_dir: Path) -> Path:
    run_dir = Path(run_dir)
    trash_dir = Path(trash_dir)
    trash_dir.mkdir(parents=True, exist_ok=True)
    target = trash_dir / run_dir.name
    if target.exists():
        target = trash_dir / f"{run_dir.name}__{dt.datetime.now().strftime('%Y%m%dT%H%M%S')}"
    return Path(shutil.move(str(run_dir), str(target)))


def restore_capture(trashed_dir: Path, table_capture_dir: Path) -> Path:
    trashed_dir = Path(trashed_dir)
    table_capture_dir = Path(table_capture_dir)
    target = table_capture_dir / trashed_dir.name
    if target.exists():
        target = table_capture_dir / f"{trashed_dir.name}__restored_{dt.datetime.now().strftime('%Y%m%dT%H%M%S')}"
    return Path(shutil.move(str(trashed_dir), str(target)))


def permanent_delete_capture(trashed_dir: Path) -> None:
    shutil.rmtree(Path(trashed_dir))


def render_pdf_page_png(
    pdf_path: Path,
    page_no: int,
    max_width: int = 1400,
) -> bytes:
    doc = fitz.open(str(pdf_path))
    try:
        if page_no < 1 or page_no > doc.page_count:
            raise ValueError(f"PDF页码超出范围：{page_no}")
        page = doc[page_no - 1]
        zoom = min(2.0, max_width / max(float(page.rect.width), 1.0))
        pix = page.get_pixmap(matrix=fitz.Matrix(zoom, zoom), alpha=False)
        return pix.tobytes("png")
    finally:
        doc.close()
