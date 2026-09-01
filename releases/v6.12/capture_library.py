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
      - ``SCOPE_BOUNDARY_CONFIRMED`` — an explicitly persisted ``PRIMARY_ONLY``
        policy stopped before confirmed continuation segments
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
    "SOFT_BOUNDARY_CONFIRMED",
    "SCOPE_BOUNDARY_CONFIRMED",
    "HUMAN_CONFIRMED",
}

CAPTURE_SCOPE_POLICIES = {
    "PRIMARY_ONLY",
    "PRIMARY_WITH_CONTINUATIONS",
    "ALL_NOTE_TABLES",
}
CONTINUATION_INCLUSIVE_POLICIES = {
    "PRIMARY_WITH_CONTINUATIONS",
    "ALL_NOTE_TABLES",
}
CONTINUATION_EXCLUDED_BY_POLICY = "CONTINUATION_EXCLUDED_BY_POLICY"
CONTINUATION_UNRESOLVED = "CONTINUATION_UNRESOLVED"
CERTIFIED_SCOPE_GOVERNANCE_BLOCKERS = (
    "CERTIFIED_SEGMENT_MANIFEST_REQUIRED",
    "CERTIFIED_SEGMENT_MANIFEST_DRIFT",
    "CERTIFIED_NOTE_TABLE_INVENTORY_REQUIRED",
)


def _scope_policy(
    result: dict[str, Any],
    scope_metadata: dict[str, Any] | None = None,
) -> str:
    stats = result.get("stats") or {}
    sources = [
        result,
        stats,
        result.get("metadata") or {},
        result.get("request_metadata") or {},
        scope_metadata or {},
    ]
    for source in sources:
        value = str(
            source.get("capture_scope_policy")
            or source.get("scope_policy")
            or ""
        ).strip().upper()
        if value in CAPTURE_SCOPE_POLICIES:
            return value
    return ""


def _machine_scope_value(result: dict[str, Any], *keys: str) -> Any:
    stats = result.get("stats") or {}
    boundary_evidence = stats.get("boundary_evidence") or {}
    for source in (result, stats, boundary_evidence):
        for key in keys:
            if key in source and source.get(key) is not None:
                return source.get(key)
    return None


def _is_true(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return str(value or "").strip().upper() in {"1", "TRUE", "YES", "Y"}


def _issue_codes(
    result: dict[str, Any],
    scope_metadata: dict[str, Any] | None = None,
) -> set[str]:
    stats = result.get("stats") or {}
    boundary_evidence = stats.get("boundary_evidence") or {}
    values: list[Any] = []
    sources = [result, stats, boundary_evidence]
    if scope_metadata:
        sources.append(scope_metadata)
    for source in sources:
        for key in (
            "warnings",
            "warning_codes",
            "scope_warning_codes",
            "scope_issue_codes",
            "blocking_issues",
        ):
            raw = source.get(key)
            if isinstance(raw, (list, tuple, set)):
                values.extend(raw)
            elif raw:
                values.append(raw)
    codes: set[str] = set()
    for value in values:
        if isinstance(value, dict):
            value = (
                value.get("reason_code")
                or value.get("code")
                or value.get("status")
                or ""
            )
        text = str(value or "").strip().upper()
        if text:
            codes.add(text)
    return codes


def _segment_classification(segment: dict[str, Any]) -> str:
    return str(
        segment.get("classification")
        or segment.get("segment_classification")
        or ""
    ).strip().upper()


def _confirmed_continuation(segment: dict[str, Any]) -> bool:
    relation_status = str(
        segment.get("relation_status")
        or segment.get("status")
        or ""
    ).strip().upper()
    return bool(
        _segment_classification(segment) == "CONTINUATION_SEGMENT"
        and str(segment.get("continuation_of_segment_id") or "").strip()
        and relation_status not in {"UNRESOLVED", "REJECTED", "CANDIDATE"}
    )


def _unresolved_continuation(segment: dict[str, Any]) -> bool:
    reason_codes = {
        str(code or "").strip().upper()
        for code in (segment.get("reason_codes") or [])
    }
    candidate_relation = str(
        segment.get("candidate_relation") or ""
    ).strip().upper()
    return bool(
        _segment_classification(segment) == "UNRESOLVED"
        and candidate_relation == "CONTINUATION_SEGMENT"
        and (
            "CONTINUATION_RELATION_UNRESOLVED" in reason_codes
            or str(segment.get("relation_status") or "").strip().upper()
            == "UNRESOLVED"
        )
    )


def _excluded_manifest_contradicts_rows(
    result: dict[str, Any],
    manifest: list[dict[str, Any]],
) -> bool:
    excluded_ids = {
        str(item.get("segment_id") or "").strip()
        for item in manifest
        if str(item.get("segment_id") or "").strip()
    }
    ranges = []
    for item in manifest:
        start = item.get("row_order_start")
        end = item.get("row_order_end")
        if start is None or end is None:
            continue
        try:
            ranges.append((
                int(start),
                int(end),
                int(item.get("page_number") or item.get("page") or 0),
            ))
        except (TypeError, ValueError):
            continue
    for row in result.get("rows") or []:
        if _is_true(row.get("excluded_from_table_logic")):
            continue
        row_segment_id = str(
            row.get("physical_segment_id")
            or row.get("segment_id")
            or row.get("table_segment_id")
            or ""
        ).strip()
        if row_segment_id and row_segment_id in excluded_ids:
            return True
        try:
            row_order = int(row.get("row_order") or 0)
            row_page = int(row.get("page") or 0)
        except (TypeError, ValueError):
            continue
        for start, end, page in ranges:
            if start <= row_order <= end and (not page or not row_page or page == row_page):
                return True
    return False


def derive_capture_scope_state(
    result: dict[str, Any],
    *,
    scope_metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Return fail-closed scope-policy state from persisted machine evidence."""
    policy = _scope_policy(result, scope_metadata)
    stats = result.get("stats") or {}
    segments = list(stats.get("physical_table_segments") or [])
    raw_manifest = _machine_scope_value(
        result,
        "excluded_segment_manifest",
        "scope_excluded_segment_manifest",
    )
    manifest = [
        dict(item) for item in (raw_manifest or []) if isinstance(item, dict)
    ]
    codes = _issue_codes(result, scope_metadata)
    certified_scope_blockers = [
        code for code in CERTIFIED_SCOPE_GOVERNANCE_BLOCKERS if code in codes
    ]
    continuation_status = str(
        _machine_scope_value(result, "continuation_status") or ""
    ).strip().upper()
    scope_boundary_decision = str(
        _machine_scope_value(result, "scope_boundary_decision") or ""
    ).strip().upper()
    explicit_scope_limited = _is_true(
        _machine_scope_value(result, "capture_scope_limited")
    )
    continuation_unresolved = bool(
        CONTINUATION_UNRESOLVED in codes
        or continuation_status == "UNRESOLVED"
        or any(_unresolved_continuation(segment) for segment in segments)
    )
    confirmed_excluded = [
        segment for segment in manifest if _confirmed_continuation(segment)
    ]
    manifest_contradicts_rows = _excluded_manifest_contradicts_rows(
        result,
        confirmed_excluded,
    )
    policy_truncation_requested = scope_boundary_decision == "POLICY_TRUNCATION"
    policy_truncation_confirmed = bool(
        policy == "PRIMARY_ONLY"
        and explicit_scope_limited
        and policy_truncation_requested
        and confirmed_excluded
        and not continuation_unresolved
        and not manifest_contradicts_rows
    )
    continuation_excluded = bool(
        policy == "PRIMARY_ONLY"
        and (
            policy_truncation_confirmed
            or CONTINUATION_EXCLUDED_BY_POLICY in codes
        )
    )
    return {
        "capture_scope_policy": policy,
        "capture_scope_limited": bool(
            explicit_scope_limited or policy == "PRIMARY_ONLY"
        ),
        "scope_boundary_decision": scope_boundary_decision,
        "policy_truncation_requested": policy_truncation_requested,
        "policy_truncation_confirmed": policy_truncation_confirmed,
        "policy_evidence_incomplete": bool(
            (
                policy_truncation_requested
                and not policy_truncation_confirmed
            )
            or (
                policy == "PRIMARY_ONLY"
                and continuation_unresolved
            )
        ),
        "continuation_excluded_by_policy": continuation_excluded,
        "continuation_unresolved": continuation_unresolved,
        "continuation_unresolved_requires_block": bool(
            policy in CONTINUATION_INCLUSIVE_POLICIES
            and continuation_unresolved
        ),
        "certified_scope_blocking_issue_codes": certified_scope_blockers,
        "excluded_segment_count": len(confirmed_excluded),
        "excluded_manifest_contradicts_rows": manifest_contradicts_rows,
    }


def _certified_segment_boundary_is_safe(
    result: dict[str, Any],
    *,
    scope_metadata: dict[str, Any] | None,
) -> bool:
    from table_boundary_resolver import BoundaryReason

    stats = result.get("stats") or {}
    if str(stats.get("boundary_reason") or "").strip().lower() != (
        BoundaryReason.CERTIFIED_SEGMENT_BBOX.value
    ):
        return False
    metadata = dict(scope_metadata or {})
    try:
        contract_version = int(
            metadata.get("capture_scope_contract_version")
            or stats.get("capture_scope_contract_version")
            or 0
        )
    except (TypeError, ValueError):
        return False
    if contract_version != 2:
        return False

    machine_policy = str(
        stats.get("capture_scope_policy") or ""
    ).strip().upper()
    metadata_policy = str(
        metadata.get("capture_scope_policy") or ""
    ).strip().upper()
    if (
        machine_policy not in {"PRIMARY_ONLY", "ALL_NOTE_TABLES"}
        or (metadata_policy and metadata_policy != machine_policy)
    ):
        return False

    machine_validation = dict(
        stats.get("certified_segment_manifest_validation") or {}
    )
    metadata_validation = dict(
        metadata.get("certified_segment_manifest_validation") or {}
    )
    machine_inventory_validation = dict(
        stats.get("certified_note_table_inventory_validation") or {}
    )
    metadata_inventory_validation = dict(
        metadata.get("certified_note_table_inventory_validation") or {}
    )
    if (
        not machine_validation
        or (metadata_validation and metadata_validation != machine_validation)
        or not machine_inventory_validation
        or (
            metadata_inventory_validation
            and metadata_inventory_validation != machine_inventory_validation
        )
    ):
        return False
    validation = machine_validation
    inventory_validation = machine_inventory_validation
    if (
        str(validation.get("status") or "").strip().upper() != "VALID"
        or str(validation.get("manifest_status") or "").strip().upper()
        != "CERTIFIED_SEGMENT_MANIFEST"
        or list(validation.get("issue_codes") or [])
        or str(inventory_validation.get("status") or "").strip().upper()
        != "VALID"
        or list(inventory_validation.get("issue_codes") or [])
    ):
        return False

    certified_segments = [
        dict(segment)
        for segment in (validation.get("certified_segments") or [])
        if isinstance(segment, dict)
    ]
    discovered_segments = [
        dict(segment)
        for segment in (validation.get("discovered_segments") or [])
        if isinstance(segment, dict)
    ]
    validated_pairs = [
        dict(pair)
        for pair in (validation.get("validated_pairs") or [])
        if isinstance(pair, dict)
    ]
    if not (
        certified_segments
        and len(certified_segments)
        == len(discovered_segments)
        == len(validated_pairs)
    ):
        return False
    allowed_classifications = {
        "PRIMARY_TABLE",
        "CONTINUATION_SEGMENT",
        "SUPPLEMENTARY_TABLE",
    }
    if any(
        str(segment.get("certification_status") or "").strip().upper()
        != "CERTIFIED"
        or _segment_classification(segment) not in allowed_classifications
        for segment in certified_segments
    ):
        return False
    if any(
        _segment_classification(segment) not in allowed_classifications
        for segment in discovered_segments
    ):
        return False
    certified_segment_ids = [
        str(segment.get("certified_segment_id") or "").strip()
        for segment in certified_segments
    ]
    discovered_segment_ids = [
        str(segment.get("segment_id") or "").strip()
        for segment in discovered_segments
    ]
    certified_ids = [
        str(pair.get("certified_segment_id") or "").strip()
        for pair in validated_pairs
    ]
    discovered_ids = [
        str(pair.get("discovered_segment_id") or "").strip()
        for pair in validated_pairs
    ]
    if (
        any(not value for value in [*certified_ids, *discovered_ids])
        or len(set(certified_ids)) != len(certified_ids)
        or len(set(discovered_ids)) != len(discovered_ids)
        or set(certified_ids) != set(certified_segment_ids)
        or set(discovered_ids) != set(discovered_segment_ids)
    ):
        return False
    machine_selected_manifest = [
        dict(segment)
        for segment in (stats.get("selected_segment_manifest") or [])
        if isinstance(segment, dict)
    ]
    metadata_selected_manifest = [
        dict(segment)
        for segment in (metadata.get("selected_segment_manifest") or [])
        if isinstance(segment, dict)
    ]
    if (
        not machine_selected_manifest
        or (
            metadata_selected_manifest
            and metadata_selected_manifest != machine_selected_manifest
        )
    ):
        return False
    selected_ids = [
        str(segment.get("segment_id") or "").strip()
        for segment in machine_selected_manifest
    ]
    if (
        any(not value for value in selected_ids)
        or len(set(selected_ids)) != len(selected_ids)
        or set(selected_ids) != set(discovered_ids)
        or any(
            _segment_classification(segment) not in allowed_classifications
            for segment in machine_selected_manifest
        )
    ):
        return False
    physical_segments = [
        dict(segment)
        for segment in (stats.get("physical_table_segments") or [])
        if isinstance(segment, dict)
    ]
    physical_segment_ids = {
        str(segment.get("segment_id") or "").strip()
        for segment in physical_segments
        if str(segment.get("segment_id") or "").strip()
    }
    child_segment_ids = {
        str(value).strip()
        for value in (stats.get("physical_segment_ids") or [])
        if str(value).strip()
    }
    if (
        not set(selected_ids).issubset(physical_segment_ids)
        or (child_segment_ids and not child_segment_ids.issubset(set(selected_ids)))
    ):
        return False
    active_rows = [
        row
        for row in (result.get("rows") or [])
        if isinstance(row, dict)
        and not _is_true(row.get("excluded_from_table_logic"))
    ]
    if not active_rows or any(
        not str(
            row.get("physical_segment_id")
            or row.get("segment_id")
            or row.get("table_segment_id")
            or ""
        ).strip()
        or str(
            row.get("physical_segment_id")
            or row.get("segment_id")
            or row.get("table_segment_id")
            or ""
        ).strip()
        not in set(selected_ids)
        for row in active_rows
    ):
        return False
    required_matches = (
        "page",
        "classification",
        "header",
        "period",
        "lane",
        "continuation",
        "bbox",
    )
    return all(
        not list(pair.get("drift_fields") or [])
        and all(
            isinstance(pair.get(field), dict)
            and pair[field].get("match") is True
            for field in required_matches
        )
        for pair in validated_pairs
    )


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
        # Only an explicit SECTION row is a same-page block reset. A generic
        # DETAIL or SECTION_HEADER + DETAIL sequence is still ambiguous and
        # must not become a non-blocking warning.
        return any(
            str(row.get("row_role") or "").upper()=="SECTION"
            and bool(str(row.get("raw_item") or "").strip())
            for row in rows[total_idx+1:]
        )
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


def _terminal_total_with_labelled_post_rows_is_safe(
    result: dict[str, Any], *, reason: str, warnings: str
) -> tuple[bool, dict[str, Any]]:
    """Recognise a table that has a clear terminal TOTAL row followed only by
    labelled breakdown/memo rows (e.g. "其中：成本", "其中 / －成本").

    Unlike ``_explicit_terminal_total_is_safe``, this does NOT require the
    TOTAL to be the *last* row.  Unlike ``_page_terminal_reconciled_block_is_safe``,
    this does NOT require the table to reach the page bottom.

    Returns ``(is_safe, decision_evidence)`` where decision_evidence includes
    the terminal pattern, reconciled columns, and post-total row semantics.
    """
    evidence: dict[str, Any] = {
        "terminal_pattern": "",
        "terminal_total_row_id": None,
        "reconciled_leaf_columns": [],
        "post_total_row_ids": [],
        "post_total_semantic_roles": [],
        "continuation_signal": False,
        "contamination_signal": False,
        "final_boundary_decision": "",
    }

    # No cross-page / truncation evidence
    if any(token in (reason + " " + warnings).lower() for token in (
        "max_pages", "continu", "跨页", "续表",
    )):
        evidence["continuation_signal"] = True
        return False, evidence

    rows = list(result.get("rows") or [])
    if not rows:
        return False, evidence

    # Find the last TOTAL or explicit-sum row
    total_positions = [
        index for index, row in enumerate(rows)
        if str(row.get("row_role") or row.get("row_type") or "").upper() in {"TOTAL", "SUBTOTAL"}
        or str(row.get("raw_item") or row.get("row_item_raw") or "").strip() in {"合计", "总计", "资产合计", "负债合计"}
    ]
    if not total_positions:
        return False, evidence

    total_idx = total_positions[-1]
    total_row = rows[total_idx]
    evidence["terminal_total_row_id"] = total_row.get("row_id") or total_row.get("source_row_id")
    evidence["terminal_pattern"] = "RECONCILED_TOTAL_WITH_LABELLED_POST_TOTAL_ROWS"

    # Header topology must be consistent
    stats = result.get("stats") or {}
    topology = stats.get("v69_header_topology") or {}
    if not bool(topology.get("consistent")):
        return False, evidence

    # Reconciliation must pass
    reconciliation = stats.get("v69_reconciliation") or {}
    if str(reconciliation.get("status") or "").upper() != "PASS":
        return False, evidence

    # No post-total disclosure merge flag
    if stats.get("post_total_disclosure_not_merged"):
        return False, evidence

    # Every row after the total must be a labelled structural row.
    # v6.11: detect memo/whereof patterns ("其中", "of which", etc.)
    post_total_rows = rows[total_idx + 1:]
    if not post_total_rows:
        evidence["terminal_pattern"] = "EXPLICIT_TOTAL_AS_LAST_ROW"
        evidence["final_boundary_decision"] = "AUTO_HIGH_CONFIDENCE"
        return True, evidence

    for row in post_total_rows:
        role = str(row.get("row_role") or row.get("row_type") or "").upper()
        raw_label = str(row.get("raw_item") or row.get("row_item_raw") or "").strip()
        normalized_label = str(row.get("normalized_item") or row.get("row_item_normalized") or "").strip()

        # Composite label: "其中 / －成本" or similar split-label patterns
        composite_label = raw_label or normalized_label

        # Detect memo/whereof prefix
        is_memo = _is_post_total_memo_label(composite_label)

        # NOTE_TEXT / MEMO_TEXT → contamination
        if role in {"NOTE_TEXT", "MEMO_TEXT"}:
            evidence["contamination_signal"] = True
            return False, evidence
        # AMBIGUOUS role → can't trust
        if role == "AMBIGUOUS":
            return False, evidence
        # ANONYMOUS_NUMERIC_ROW → unlabeled spill
        if role == "ANONYMOUS_NUMERIC_ROW":
            return False, evidence
        # IMPLICIT_ROW_CANDIDATE → unresolved
        if role == "IMPLICIT_ROW_CANDIDATE":
            return False, evidence
        # No label at all
        if not composite_label:
            return False, evidence

        # v6.11: away from the page terminal region, accept only explicit
        # memo markers, explicit SECTION boundaries, or visibly indented
        # breakdown labels. A generic SECTION_HEADER + DETAIL sequence may be
        # continued table content and remains REVIEW_REQUIRED.
        explicit_section = role=="SECTION"
        indented_breakdown = (
            role=="DETAIL"
            and composite_label.startswith(("－","-","—","–"))
        )
        if not (is_memo or explicit_section or indented_breakdown):
            return False, evidence
        semantic_role = (
            "POST_TOTAL_MEMO_DETAIL" if is_memo
            else "POST_TOTAL_SECTION" if explicit_section
            else "POST_TOTAL_LABELLED_DETAIL"
        )
        evidence["post_total_semantic_roles"].append({
            "row_id": row.get("row_id") or row.get("source_row_id"),
            "raw_item": raw_label,
            "composite_label": composite_label,
            "post_total_semantic_role": semantic_role,
        })
        evidence["post_total_row_ids"].append(row.get("row_id") or row.get("source_row_id"))

    # Record reconciled leaf columns from the total row
    total_cells = total_row.get("cells") or []
    evidence["reconciled_leaf_columns"] = [
        {"column_ordinal": c.get("column_ordinal", i),
         "parsed_number": c.get("parsed_number") if isinstance(c, dict) else getattr(c, "parsed_number", None)}
        for i, c in enumerate(total_cells)
    ]

    evidence["final_boundary_decision"] = "AUTO_HIGH_CONFIDENCE"
    return True, evidence


def _is_post_total_memo_label(label: str) -> bool:
    """Detect whether a row label is a post-total memo/whereof marker.

    Recognises patterns like:
      - "其中：成本", "其中－成本", "其中 / －成本"
      - "of which: cost"
      - Composite labels where a prefix ("其中") is followed by a detail item
    """
    label_norm = str(label or "").strip()
    if not label_norm:
        return False
    # 其中 is the standard Chinese "of which" / whereof marker
    if label_norm.startswith("其中"):
        return True
    # Whereof / of which patterns (English/international)
    if label_norm.lower().startswith(("of which", "whereof")):
        return True
    # Composite: "其中 / －成本" or "其中：成本" (with slash/colon separator)
    if "/" in label_norm or "：" in label_norm or ":" in label_norm:
        parts = re.split(r"\s*/\s*|\s*[：:]\s*", label_norm, maxsplit=1)
        if parts and parts[0].strip().startswith("其中"):
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


def _normalise_boundary_reason(reason: str) -> str:
    """Map legacy resolver reason strings onto the canonical enum contract."""
    from table_boundary_resolver import BoundaryReason

    if reason.startswith("next_note_"):
        return BoundaryReason.NEXT_NOTE_ORDINAL.value
    if reason.startswith("next_peer_heading_"):
        return BoundaryReason.NEXT_PEER_HEADING.value
    return reason


def _footer_fallback_is_safe(
    result: dict[str, Any], *, warnings: str
) -> dict[str, Any]:
    """Composite completeness evidence for ``SAME_PAGE_FOOTER_FALLBACK``.

    SOFT_BOUNDARY_CONFIRMED requires: no truncation / continuation warning, a
    verified terminal total (TOTAL / 合计 / 总计) as the last logical row, no
    real rows after that total (only layout noise), and no rows beyond the
    captured end page.  The raw boundary confidence stays MEDIUM; the
    confidence basis is recorded as COMPOSITE_EVIDENCE.
    """
    joined = str(warnings or "").lower()
    if any(token in joined for token in (
        "max_pages", "continu", "跨页", "续表", "未发现下一附注编号"
    )):
        return {"safe": False, "evidence": {}}
    rows = list(result.get("rows") or [])
    from table_boundary_resolver import match_peer_note_heading, parse_note_ordinal

    boundary_evidence = (result.get("stats") or {}).get("boundary_evidence") or {}
    current_ordinal = parse_note_ordinal(
        boundary_evidence.get("current_note_reference")
    )
    for row in rows:
        if row.get("excluded_from_table_logic"):
            continue
        role = str(row.get("row_role") or row.get("row_type") or "").upper()
        label = str(
            row.get("raw_item") or row.get("row_item_raw")
            or row.get("normalized_item") or ""
        ).strip()
        if role == "NOTE_TEXT":
            return {"safe": False, "evidence": {}}
        matched = match_peer_note_heading(label) if label else None
        if matched and current_ordinal is not None and matched[0] > current_ordinal:
            return {"safe": False, "evidence": {}}
        if not label:
            raw_cells = [
                str(cell.get("raw") or "").strip()
                for cell in (row.get("cells") or [])
                if str(cell.get("raw") or "").strip()
            ]
            if raw_cells and all(
                re.fullmatch(r"20\d{2}(?:年(?:度|末|初)?)?", raw)
                for raw in raw_cells
            ):
                return {"safe": False, "evidence": {}}
    terminal_idx = None
    for i in range(len(rows) - 1, -1, -1):
        row = rows[i]
        if row.get("excluded_from_table_logic"):
            continue
        role = str(row.get("row_role") or row.get("row_type") or "").upper()
        label = str(
            row.get("raw_item") or row.get("row_item_raw")
            or row.get("normalized_item") or ""
        ).strip()
        if role == "TOTAL" or label in {"合计", "总计", "资产合计", "负债合计"}:
            terminal_idx = i
            break
    if terminal_idx is None:
        return {"safe": False, "evidence": {}}
    post = rows[terminal_idx + 1:]
    noise_only = all(
        row.get("excluded_from_table_logic")
        or str(row.get("row_role") or "") == "PAGE_NUMBER_NOISE"
        for row in post
    )
    if not noise_only:
        return {"safe": False, "evidence": {}}
    end_page = int(result.get("end_page") or 0)
    if any(int(r.get("page") or 0) > end_page for r in rows):
        return {"safe": False, "evidence": {}}
    return {
        "safe": True,
        "evidence": {
            "terminal_row_status": "CONFIRMED",
            "continuation_status": "NOT_DETECTED",
            "post_terminal_noise_only": True,
            "column_alignment_consistent": True,
            "capture_completeness": "HIGH",
            "confidence_basis": "COMPOSITE_EVIDENCE",
            "review_required": False,
            "terminal_row_index": terminal_idx,
        },
    }


def derive_boundary_status(
    result: dict[str, Any],
    *,
    scope_metadata: dict[str, Any] | None = None,
) -> str:
    """Adjudicate terminal table boundary status.

    Priority (highest first):
      1. ``HUMAN_ADJUDICATION`` — preserved verbatim, never auto-overridden.
      2. Strong spatial evidence (next-note ordinal, HIGH) —
         ``HARD_BOUNDARY_CONFIRMED``, overriding a machine-default preset.
      3. Composite medium evidence (same-page footer fallback + verified
         terminal total + post-terminal noise only) —
         ``SOFT_BOUNDARY_CONFIRMED`` (non-blocking).  Legacy auto-closure
         helpers remain for other reasons.
      4. Machine-derived ``REVIEW_REQUIRED`` is only the final fallback; a
         preset machine ``REVIEW_REQUIRED`` never short-circuits stronger
         evidence above.
    """
    from table_boundary_resolver import BoundaryReason

    explicit = str(result.get("boundary_status") or "").strip()
    source = str(
        result.get("boundary_status_source") or ""
    ).strip() or "MACHINE_DEFAULT"
    stats = result.get("stats") or {}
    reason = _normalise_boundary_reason(str(stats.get("boundary_reason") or ""))
    evidence = stats.get("boundary_evidence") or {}
    confidence = str(stats.get("boundary_confidence") or "")
    method = str(evidence.get("method") or "")
    warnings = " ".join(str(x) for x in (result.get("warnings") or []))
    engine = str(stats.get("engine") or "")
    scope_state = derive_capture_scope_state(
        result,
        scope_metadata=scope_metadata,
    )

    # 1. Human adjudication has the highest priority.
    if source == "HUMAN_ADJUDICATION":
        result["boundary_status_source"] = "HUMAN_ADJUDICATION"
        return explicit or "REVIEW_REQUIRED"

    # 2. A policy boundary is merge-ready only when the execution layer
    # explicitly proves that confirmed continuation segments were excluded
    # from table logic.  Policy intent alone never overrides PDF uncertainty.
    if scope_state["continuation_unresolved_requires_block"]:
        result["boundary_status_source"] = "MACHINE_DERIVED"
        return "CONTINUATION_REQUIRED"
    if scope_state["policy_truncation_requested"]:
        result["boundary_status_source"] = "MACHINE_DERIVED"
        return (
            "SCOPE_BOUNDARY_CONFIRMED"
            if scope_state["policy_truncation_confirmed"]
            else "REVIEW_REQUIRED"
        )

    if _certified_segment_boundary_is_safe(
        result,
        scope_metadata=scope_metadata,
    ):
        result["boundary_status_source"] = "MACHINE_DERIVED"
        return "HARD_BOUNDARY_CONFIRMED"

    # 3. Strong spatial evidence overrides a machine-default preset.
    if (
        reason == BoundaryReason.NEXT_NOTE_ORDINAL.value
        and confidence == "HIGH"
        and method == "NEXT_NOTE_ORDINAL"
        and evidence.get("next_note_verified", True) is not False
    ):
        result["boundary_status_source"] = "MACHINE_DERIVED"
        return "HARD_BOUNDARY_CONFIRMED"

    # 4a. Composite medium evidence: footer fallback with a verified terminal
    #     total and only post-terminal layout noise.
    if (
        reason == BoundaryReason.SAME_PAGE_FOOTER_FALLBACK.value
        and method == "SAME_PAGE_FOOTER_FALLBACK"
    ):
        composite = _footer_fallback_is_safe(result, warnings=warnings)
        if composite["safe"]:
            merged_evidence = dict(evidence)
            merged_evidence.update(composite["evidence"])
            stats["boundary_evidence"] = merged_evidence
            result["stats"] = stats
            result["boundary_status_source"] = "MACHINE_DERIVED"
            return "SOFT_BOUNDARY_CONFIRMED"
        result["boundary_status_source"] = "MACHINE_DERIVED"
        return "REVIEW_REQUIRED"

    # 4b. Legacy auto-closure evidence for other reasons.
    terminal_safe = _explicit_terminal_total_is_safe(
        result, reason=reason, warnings=warnings
    )
    page_safe, sub = _page_terminal_reconciled_block_is_safe(
        result, reason=reason, warnings=warnings
    )
    if terminal_safe or (page_safe and sub == "PAGE_TERMINAL_RECONCILED"):
        result["boundary_status_source"] = "MACHINE_DERIVED"
        return "AUTO_HIGH_CONFIDENCE"
    if page_safe and sub == "SAME_NOTE_DIFFERENT_BLOCK":
        result["boundary_status_source"] = "MACHINE_DERIVED"
        return "AUTO_ACCEPTED_WITH_NON_BLOCKING_WARNING"
    memo_safe, _ = _terminal_total_with_labelled_post_rows_is_safe(
        result, reason=reason, warnings=warnings
    )
    if memo_safe:
        result["boundary_status_source"] = "MACHINE_DERIVED"
        return "AUTO_HIGH_CONFIDENCE"

    if (
        "max_pages" in reason
        or "max_pages" in warnings
        or "未发现下一附注编号" in warnings
    ):
        result["boundary_status_source"] = "MACHINE_DERIVED"
        return "REVIEW_REQUIRED"
    if "LEGACY" in engine.upper():
        result["boundary_status_source"] = "MACHINE_DERIVED"
        return "REVIEW_REQUIRED"

    # 5. A stale explicit HARD flag must not override contradictory current
    #    evidence produced by an older next-peer implementation.
    if explicit == "HARD_BOUNDARY_CONFIRMED" and (
        reason == BoundaryReason.NEXT_PEER_HEADING.value
        or method == "NEXT_PEER_HEADING"
        or confidence in {"LOW", "MEDIUM"}
    ):
        result["boundary_status_source"] = "MACHINE_DERIVED"
        return "REVIEW_REQUIRED"

    # Machine-default REVIEW_REQUIRED is only the final fallback; already
    # derived / human ready statuses are preserved.
    result["boundary_status_source"] = "MACHINE_DERIVED"
    return explicit if explicit in MERGE_READY_STATUSES else "REVIEW_REQUIRED"


def derive_boundary_decision(
    result: dict[str, Any],
    *,
    scope_metadata: dict[str, Any] | None = None,
) -> TerminalBoundaryDecision:
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

    scope_state = derive_capture_scope_state(
        result,
        scope_metadata=scope_metadata,
    )
    status = derive_boundary_status(
        result,
        scope_metadata=scope_metadata,
    )
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
    if scope_state["capture_scope_policy"]:
        chain.append(
            f"capture_scope_policy={scope_state['capture_scope_policy']}"
        )
    if scope_state["capture_scope_limited"]:
        chain.append("capture_scope_limited=true")

    terminal_safe = _explicit_terminal_total_is_safe(result, reason=reason, warnings=warnings)
    page_safe, sub = _page_terminal_reconciled_block_is_safe(result, reason=reason, warnings=warnings)

    if status == "SCOPE_BOUNDARY_CONFIRMED":
        chain.append("scope_boundary_decision=POLICY_TRUNCATION")
        chain.append(
            f"excluded_continuation_segments={scope_state['excluded_segment_count']}"
        )
        decision.sub_decision = "POLICY_TRUNCATION"
        decision.warnings = [CONTINUATION_EXCLUDED_BY_POLICY]
    elif status == "CONTINUATION_REQUIRED":
        chain.append("continuation_relation=UNRESOLVED")
        decision.sub_decision = "CONTINUATION_UNRESOLVED"
    elif _certified_segment_boundary_is_safe(
        result,
        scope_metadata=scope_metadata,
    ):
        chain.append("certified_segment_manifest=VALID_RUNTIME_MATCH")
        decision.sub_decision = "CERTIFIED_SEGMENT_MANIFEST"
    elif terminal_safe:
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


def capture_readiness(
    result: dict[str, Any],
    *,
    scope_metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    scope_state = derive_capture_scope_state(
        result,
        scope_metadata=scope_metadata,
    )
    boundary = derive_boundary_status(
        result,
        scope_metadata=scope_metadata,
    )
    header = derive_header_status(result)
    boundary_ready = boundary in MERGE_READY_STATUSES
    header_ready = header in {"AUTO_CONFIRMED", "HUMAN_CONFIRMED"}
    blockers = []
    if not boundary_ready:
        blockers.append(f"BOUNDARY:{boundary}")
    if not header_ready:
        blockers.append(f"HEADER:{header}")
    if scope_state["continuation_unresolved_requires_block"]:
        blockers.append(CONTINUATION_UNRESOLVED)
    if scope_state["policy_evidence_incomplete"]:
        blockers.append("CAPTURE_SCOPE_POLICY_EVIDENCE_INCOMPLETE")
    blockers.extend(scope_state["certified_scope_blocking_issue_codes"])
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
    # Header topology remains an independent merge gate.  Arithmetic
    # reconciliation is retained as evidence, but a flat parent/child sum is
    # not reliable enough to block whole-table merge readiness.
    v69_topology = stats.get("v69_header_topology") or {}
    v69_reconciliation = stats.get("v69_reconciliation") or {}
    topology_ready = bool(v69_topology.get("consistent", True))
    reconciliation_ready = str(
        v69_reconciliation.get("status") or "NOT_TESTABLE"
    ).upper() != "FAIL"
    if not topology_ready:
        blockers.append("V69_HEADER_TOPOLOGY_AMBIGUOUS")
    if not reconciliation_ready:
        blockers.append("V69_RECONCILIATION_MISMATCH")
    blockers = list(dict.fromkeys(blockers))
    ready = not blockers
    non_blocking_warnings = []
    if (
        scope_state["continuation_excluded_by_policy"]
        and scope_state["policy_truncation_confirmed"]
    ):
        non_blocking_warnings.append(CONTINUATION_EXCLUDED_BY_POLICY)
    return {
        "boundary_status": boundary,
        "header_dimension_status": header,
        "semantic_status": "AUTO_CONFIRMED" if not mixed_count and not unresolved_implicit else "REVIEW_REQUIRED",
        "capture_quality_status": "READY" if ready else "REVIEW_REQUIRED",
        "mixed_cell_count": mixed_count,
        "unresolved_implicit_rows": unresolved_implicit,
        "v69_header_topology": v69_topology,
        "v69_reconciliation": v69_reconciliation,
        "capture_scope_policy": scope_state["capture_scope_policy"],
        "capture_scope_limited": scope_state["capture_scope_limited"],
        "scope_boundary_decision": scope_state["scope_boundary_decision"],
        "excluded_segment_count": scope_state["excluded_segment_count"],
        "non_blocking_warnings": non_blocking_warnings,
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


def _read_csv_optional(path: Path) -> pd.DataFrame:
    """Read a capture CSV, treating missing or empty files as empty frames.

    A block without amount columns serialises an empty DataFrame with
    utf-8-sig as a 5-byte BOM+newline file; ``pd.read_csv`` on it raises
    EmptyDataError.  Such a block is legitimate (memo-only rows) and must not
    fail the whole capture job.
    """
    path = Path(path)
    if not path.is_file():
        return pd.DataFrame()
    try:
        return pd.read_csv(path)
    except pd.errors.EmptyDataError:
        return pd.DataFrame()


def _rewrite_capture_excel(run_dir: Path) -> None:
    run_dir = Path(run_dir)
    official_long = _read_csv_optional(run_dir / "table_raw_long.csv")
    official_wide = _read_csv_optional(run_dir / "table_raw_wide.csv")
    dictionary = _read_csv_optional(run_dir / "table_item_dictionary.csv")
    machine_long = _read_csv_optional(run_dir / "machine_capture_full_long.csv")
    machine_wide = _read_csv_optional(run_dir / "machine_capture_full_wide.csv")
    excluded = _read_csv_optional(run_dir / "boundary_excluded_rows.csv")
    reconciliation = _read_csv_optional(run_dir / "table_reconciliation_audit.csv")
    parser_candidates = _read_csv_optional(run_dir / "header_parser_candidates.csv")
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
    result["boundary_status_source"] = "HUMAN_ADJUDICATION"
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
    payload = {
        **result,
        "boundary_status": "UNASSESSED",
        "boundary_status_source": "MACHINE_DEFAULT",
    }
    result["boundary_status"] = derive_boundary_status(payload)
    result["boundary_status_source"] = payload.get("boundary_status_source")
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
