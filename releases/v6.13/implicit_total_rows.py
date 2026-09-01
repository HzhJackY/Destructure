"""Evidence-preserving recovery for anonymous numeric total rows.

The parser never turns a blank PDF cell into the word ``合计``.  A derived
label is only added when immediate labelled breakdown rows arithmetically
reconcile to the anonymous row.

Observation types and derived statuses are set here to distinguish source rows
from derived rows, enabling downstream governance to treat optional derived
totals as non-blocking for merge eligibility.
"""
from __future__ import annotations

from typing import Any


BREAKDOWN_TOKENS = ("上市", "非上市", "境内", "境外", "国内", "国外", "一级市场", "二级市场")

# Derived row lifecycle states.  Only REQUIRED_DERIVED_TOTAL_UNRESOLVED blocks
# merge — all other states are informational or non-blocking.
DERIVED_VALIDATED = "DERIVED_VALIDATED"
DERIVED_REJECTED_NON_BLOCKING = "DERIVED_REJECTED_NON_BLOCKING"
DERIVED_EXCLUDED = "DERIVED_EXCLUDED"
SUPPRESSED_BY_EXPLICIT_TOTAL = "SUPPRESSED_BY_EXPLICIT_TOTAL"
REQUIRED_DERIVED_TOTAL_UNRESOLVED = "REQUIRED_DERIVED_TOTAL_UNRESOLVED"


def _values(row: Any) -> list[float | None]:
    return [cell.parsed_number for cell in getattr(row, "cells", [])]


def _close(left: float, right: float) -> bool:
    # Values are still in the table's display scale at this stage.  One final
    # displayed unit per child covers normal rounding without inventing a
    # unit conversion that the source did not disclose.
    return abs(float(left) - float(right)) <= max(1e-8, 2.0)


def recover_implicit_total_rows(rows: list[Any], *, parent_table: str) -> list[Any]:
    """Classify only auditable anonymous totals; retain all other blank rows.

    ``rows`` is intentionally duck-typed so extraction dataclasses retain the
    machine evidence while this module only enriches structural metadata.
    """
    for index, row in enumerate(rows):
        if getattr(row, "row_role", "") != "IMPLICIT_ROW_CANDIDATE":
            continue
        prior: list[Any] = []
        for previous in reversed(rows[max(0, index - 4):index]):
            # PDF footer text may be emitted after the table's numeric spans
            # even though its physical y-coordinate is below the anonymous
            # terminal row.  It is not a row-boundary signal and must not hide
            # the immediately preceding listed/unlisted breakdown.
            if str(getattr(previous, "row_role", "") or "") == "PAGE_FOOTER_NOISE":
                continue
            if getattr(previous, "raw_item", None) and getattr(previous, "cells", None):
                prior.append(previous)
            else:
                break
        prior.reverse()
        if len(prior) < 2:
            continue
        candidate = _values(row)
        if not candidate or any(value is None for value in candidate):
            continue
        # A note can show a separate memo block (for example cost and fair
        # value change) immediately before the final listed/unlisted split.
        # Test each contiguous suffix and retain the shortest auditable match.
        matched_rows: list[Any] | None = None
        for size in range(2, len(prior) + 1):
            candidate_rows = prior[-size:]
            labels = [str(getattr(x, "raw_item", "") or "") for x in candidate_rows]
            if not any(any(token in label for token in BREAKDOWN_TOKENS) for label in labels):
                continue
            child_values = [_values(x) for x in candidate_rows]
            matched = True
            for column, total in enumerate(candidate):
                parts = [values[column] for values in child_values if len(values) > column]
                if len(parts) != len(candidate_rows) or any(value is None for value in parts) or not _close(sum(parts), total):
                    matched = False
                    break
            if matched:
                matched_rows = candidate_rows
                break
        if not matched_rows:
            continue
        section = str(getattr(row, "parent_section", "") or "").strip()
        # ``其中`` is a structural marker, not an economic parent label.  The
        # table title is the only auditable inheritance source in that case.
        inherited_parent = parent_table if section in {"", "其中", "其中："} else section
        derived = f"{inherited_parent}总额"
        row.row_role = "IMPLICIT_TOTAL"
        row.row_type = "IMPLICIT_TOTAL"
        row.row_item_raw = None
        row.row_item_normalized = derived
        row.normalized_item = derived
        row.label_derivation = "DERIVED_FROM_PARENT_TABLE"
        row.derivation_method = "SUM_CHILDREN"
        row.derived_from_rows = [str(getattr(x, "raw_item", "")) for x in matched_rows]
        row.observation_type = "DERIVED_OBSERVATION"
        row.derived_status = DERIVED_REJECTED_NON_BLOCKING  # default until explicitly validated
        row.derivation_evidence = {
            "parent_table": inherited_parent,
            "derived_label": derived,
            "derivation_method": "SUM_CHILDREN",
            "child_row_orders": [getattr(x, "row_order", None) for x in matched_rows],
            "child_labels": row.derived_from_rows,
        }
    # Suppress implicit totals that have an explicit TOTAL sibling in the same
    # table block — the explicit total already covers the economic signal.
    _suppress_by_explicit_total(rows)
    return rows


def _suppress_by_explicit_total(rows: list[Any]) -> None:
    """Mark implicit totals as SUPPRESSED when an explicit TOTAL row exists
    in the same table block (same or adjacent parent section)."""
    explicit_positions = {
        idx for idx, r in enumerate(rows)
        if str(getattr(r, "row_role", "") or "").upper() == "TOTAL"
    }
    if not explicit_positions:
        return
    for idx, row in enumerate(rows):
        if str(getattr(row, "row_role", "") or "") != "IMPLICIT_TOTAL":
            continue
        # Check if any explicit total is within ±5 rows (same table block)
        near_explicit = any(
            abs(idx - ep) <= 5 for ep in explicit_positions
        )
        if near_explicit:
            row.derived_status = SUPPRESSED_BY_EXPLICIT_TOTAL
            row.suppressed_by = "EXPLICIT_TOTAL_SIBLING"
