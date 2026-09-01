#!/usr/bin/env python3
"""v6.6 source-aware member-table merge contract regression."""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from table_merge import build_structural_order, materialize_canonical  # noqa: E402


MEMBERS = [
    ("以公允价值计量且其变动计入当期损益的金融资产", "附注八-9", 1),
    ("债权投资", "附注八-10", 2),
    ("其他债权投资", "附注八-11", 3),
]


def row(member: str, note: str, member_order: int, item: str, value: float,
        run: str, *, family: str = "金融投资", role: str = "NOTE_DETAIL",
        row_path: str | None = None, scope: str = "CONSOLIDATED") -> dict:
    path = row_path or f"债券 / {item}"
    return {
        "capture_run_id": run,
        "table_id": "金融投资",
        "table_family": family,
        "member_table": member,
        "member_table_role": role,
        "member_table_order": member_order,
        "source_table_title": "合并资产负债表",
        "note_reference": note,
        "source_pdf": "中国平安2023年报.pdf",
        "company": "中国平安",
        "document_year": "2023",
        "year": "2023",
        "scope": scope,
        "restated": False,
        "period_type": "ANNUAL",
        "currency": "CNY",
        "unit": "百万元",
        "row_path": path,
        "canonical_key": f"金融投资::{member}::{role}::{path}",
        "canonical_section": "债券",
        "canonical_item": item,
        "value": float(value),
        "mapping_status": "AUTO_EXACT_IDENTITY",
        "column_ordinal": 0,
        "page": 221,
        "raw_item": item,
        "row_order": 1,
    }


def materialize(rows: list[dict]):
    mapped = pd.DataFrame(rows)
    metadata = pd.DataFrame([
        {"capture_run_id": r["capture_run_id"], "company": r["company"],
         "document_year": r["document_year"], "table_family": r.get("table_family", ""),
         "member_table": r.get("member_table", ""),
         "member_table_role": r.get("member_table_role", ""),
         "member_table_order": r.get("member_table_order", 999),
         "source_table_title": r.get("source_table_title", ""),
         "note_reference": r.get("note_reference", "")}
        for r in rows
    ]).drop_duplicates("capture_run_id")
    structural, _ = build_structural_order(mapped, metadata)
    return materialize_canonical(mapped, structural), structural


# Different members with identical row names/paths must remain independent.
parallel = [
    row(member, note, order, "政府债", 100 + order, f"RUN_{order}")
    for member, note, order in MEMBERS
]
(resolved, wide, conflicts), structural = materialize(parallel)
assert len(resolved) == 3
assert conflicts.empty, conflicts.to_dict("records")
assert set(resolved["member_table"]) == {m[0] for m in MEMBERS}
print("DIFFERENT_MEMBER_SAME_ROW_NO_CONFLICT_PASS")
print("ROW_PATH_MEMBER_SCOPED_PASS")
assert set(wide["member_table"]) == {m[0] for m in MEMBERS}
print("FINAL_WIDE_MEMBER_TABLE_VISIBLE_PASS")

# Same fully-qualified identity, same value: provenance is deduplicated.
same_value = [
    row(MEMBERS[0][0], MEMBERS[0][1], 1, "金融债", 201, "DUP_A"),
    row(MEMBERS[0][0], MEMBERS[0][1], 1, "金融债", 201, "DUP_B"),
]
(resolved, _, conflicts), _ = materialize(same_value)
assert len(resolved) == 1 and int(resolved.iloc[0]["source_count"]) == 2 and conflicts.empty
print("SAME_MEMBER_SAME_ROW_SAME_VALUE_DEDUP_PASS")

# Same fully-qualified identity, different values: a real blocking conflict.
true_conflict = [
    row(MEMBERS[1][0], MEMBERS[1][1], 2, "金融债", 301, "CONFLICT_A"),
    row(MEMBERS[1][0], MEMBERS[1][1], 2, "金融债", 399, "CONFLICT_B"),
]
(resolved, _, conflicts), _ = materialize(true_conflict)
assert len(conflicts) == 1
assert conflicts.iloc[0]["conflict_status"] == "VALUE_CONFLICT"
assert conflicts.iloc[0]["conflict_severity"] == "BLOCKING"
print("SAME_MEMBER_SAME_ROW_DIFFERENT_VALUE_BLOCK_PASS")

# Missing source identity is review-required and never treated as a value conflict.
missing_identity = [
    row("", "", 0, "政府债", 1, "MISSING_A"),
    row("", "", 0, "政府债", 2, "MISSING_B"),
]
for r in missing_identity:
    r["canonical_key"] = "金融投资::MISSING_SOURCE::政府债"
(resolved, _, conflicts), _ = materialize(missing_identity)
assert len(conflicts) == 1
assert conflicts.iloc[0]["conflict_status"] == "REVIEW_REQUIRED_SOURCE_IDENTITY"
assert conflicts.iloc[0]["conflict_severity"] == "WARNING"
print("MISSING_MEMBER_IDENTITY_REVIEW_REQUIRED_PASS")

# Generic totals must remain member scoped even when their labels are identical.
totals = [
    row(member, note, order, "合计", 1000 + order, f"TOTAL_{order}", row_path="合计")
    for member, note, order in MEMBERS
]
(resolved, wide, conflicts), structural = materialize(totals)
assert len(resolved) == 3 and conflicts.empty
assert len(wide[wide["canonical_item"] == "合计"]) == 3
print("GENERIC_TOTAL_ROWS_MEMBER_SCOPED_PASS")

# All rows share one column axis while retaining their member-table row axis.
value_columns = [c for c in wide.columns if "中国平安" in str(c)]
assert len(value_columns) == 1 and wide[value_columns[0]].notna().sum() == 3
print("COLUMN_ALIGNMENT_PRESERVED_PASS")

# Family order is member-table order, followed by each member's own order.
ordered_members = structural.sort_values("canonical_order")["member_table"].drop_duplicates().tolist()
assert ordered_members[:3] == [m[0] for m in MEMBERS], ordered_members
print("STRUCTURAL_ORDER_MEMBER_SCOPED_PASS")

print("V66_SOURCE_AWARE_MEMBER_MERGE_REGRESSION_PASS")
