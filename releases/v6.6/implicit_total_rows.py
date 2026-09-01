"""Evidence-preserving recovery for anonymous numeric total rows.

The parser never turns a blank PDF cell into the word ``合计``.  A derived
label is only added when immediate labelled breakdown rows arithmetically
reconcile to the anonymous row.
"""
from __future__ import annotations

from typing import Any


BREAKDOWN_TOKENS = ("上市", "非上市", "境内", "境外", "国内", "国外", "一级市场", "二级市场")


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
        row.derivation_evidence = {
            "parent_table": inherited_parent,
            "derived_label": derived,
            "derivation_method": "SUM_CHILDREN",
            "child_row_orders": [getattr(x, "row_order", None) for x in matched_rows],
            "child_labels": row.derived_from_rows,
        }
    return rows
