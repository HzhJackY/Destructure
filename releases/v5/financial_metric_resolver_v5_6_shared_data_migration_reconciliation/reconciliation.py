#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Warning-only total/subtotal reconciliation audit.

Principle:
STRUCTURE -> inferred membership
ARITHMETIC -> validation

Arithmetic is never used to search for a combination of rows that happens to
match a reported total, and this module never changes extracted values.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Optional

import pandas as pd


TOTAL_NAMES = {"合计", "总计", "小计"}
TOTAL_TYPES = {"TOTAL", "SUBTOTAL", "CLASSIFICATION_TOTAL"}
BOUNDARY_TYPES = {"SECTION_HEADER", "TOTAL", "SUBTOTAL", "CLASSIFICATION_TOTAL"}


def _clean(x: Any) -> str:
    if x is None or (isinstance(x, float) and pd.isna(x)):
        return ""
    return str(x).strip().rstrip("：:")


def _row_meta(long_df: pd.DataFrame) -> pd.DataFrame:
    cols = [
        c for c in [
            "row_order", "row_type", "row_level", "parent_section",
            "raw_item", "normalized_item",
        ]
        if c in long_df.columns
    ]
    meta = long_df[cols].drop_duplicates(subset=["row_order"], keep="first").copy()
    meta["row_order"] = pd.to_numeric(meta["row_order"], errors="coerce")
    meta = meta.dropna(subset=["row_order"]).sort_values("row_order", kind="stable")
    meta["row_order"] = meta["row_order"].astype(int)
    if "row_level" not in meta:
        meta["row_level"] = 0
    meta["row_level"] = pd.to_numeric(meta["row_level"], errors="coerce").fillna(0).astype(int)
    for c in ["row_type","parent_section","raw_item","normalized_item"]:
        if c not in meta:
            meta[c] = ""
        meta[c] = meta[c].fillna("").astype(str)
    return meta


def _is_total_row(row: pd.Series) -> bool:
    name = _clean(row.get("normalized_item") or row.get("raw_item"))
    typ = _clean(row.get("row_type"))
    return typ in TOTAL_TYPES or name in TOTAL_NAMES


def _infer_children(meta: pd.DataFrame, target_idx: int) -> tuple[list[int], str, str, str]:
    """
    Return (child_row_orders, pattern, confidence, reason).
    """
    target = meta.iloc[target_idx]
    target_order = int(target["row_order"])
    target_level = int(target.get("row_level", 0))
    target_name = _clean(target.get("normalized_item") or target.get("raw_item"))
    target_type = _clean(target.get("row_type"))

    # 1) Leading parent/subtotal: children immediately below and structurally deeper,
    # or explicitly assigned to parent_section == target item.
    following = []
    for j in range(target_idx + 1, len(meta)):
        r = meta.iloc[j]
        r_level = int(r.get("row_level", 0))
        r_parent = _clean(r.get("parent_section"))
        r_type = _clean(r.get("row_type"))

        is_explicit_child = bool(target_name) and r_parent == target_name
        is_deeper = r_level > target_level
        if is_explicit_child or is_deeper:
            following.append(int(r["row_order"]))
            continue

        # once children started, same/higher structural level ends group
        if following:
            break

        # no child started and immediate next row is same-level boundary -> not leading
        if r_type in BOUNDARY_TYPES or r_level <= target_level:
            break

    if following:
        return (
            following,
            "LEADING_PARENT_TOTAL",
            "HIGH" if all(
                _clean(meta[meta["row_order"] == o].iloc[0].get("parent_section")) == target_name
                for o in following
            ) else "MEDIUM",
            "target后方连续更深层级/显式parent_section子项",
        )

    # 2) Trailing total: use contiguous rows since last structural boundary.
    if target_type in {"TOTAL", "SUBTOTAL"} or target_name in TOTAL_NAMES:
        start_idx = 0
        boundary_reason = "表首"
        for j in range(target_idx - 1, -1, -1):
            r = meta.iloc[j]
            r_type = _clean(r.get("row_type"))
            if r_type in BOUNDARY_TYPES:
                start_idx = j + 1
                boundary_reason = f"前一结构边界 row {int(r['row_order'])} {r_type}"
                break

        preceding = [
            int(meta.iloc[j]["row_order"])
            for j in range(start_idx, target_idx)
            if not _is_total_row(meta.iloc[j])
        ]
        if preceding:
            return (
                preceding,
                "TRAILING_TOTAL",
                "HIGH" if boundary_reason != "表首" else "MEDIUM",
                f"{boundary_reason}之后至target之前的连续明细",
            )

    return [], "UNKNOWN", "LOW", "未找到可信结构子项集合"


def reconciliation_audit_from_long(long_df: pd.DataFrame) -> pd.DataFrame:
    columns = [
        "target_row_order","target_item","target_row_type","pattern",
        "child_row_orders","child_items","dimension_key","year","scope","restated",
        "unit","reported_total","calculated_sum","difference","difference_ratio",
        "confidence","status","inference_reason",
    ]
    if long_df.empty or "row_order" not in long_df.columns:
        return pd.DataFrame(columns=columns)

    meta = _row_meta(long_df)
    if meta.empty:
        return pd.DataFrame(columns=columns)

    # Use physical column identity first; fall back to semantic dimensions.
    dim_col = "column_dimension_key" if "column_dimension_key" in long_df.columns else None
    if dim_col is None:
        work = long_df.copy()
        work["_dim"] = work.apply(
            lambda r: f"{_clean(r.get('year'))}|{_clean(r.get('scope'))}|"
                      f"{'RESTATED' if bool(r.get('restated')) else 'ORIGINAL'}",
            axis=1,
        )
        dim_col = "_dim"
    else:
        work = long_df.copy()

    results = []
    for target_idx in range(len(meta)):
        target = meta.iloc[target_idx]
        if not _is_total_row(target):
            continue

        child_orders, pattern, confidence, reason = _infer_children(meta, target_idx)
        target_order = int(target["row_order"])
        target_item = _clean(target.get("raw_item") or target.get("normalized_item"))
        child_meta = meta[meta["row_order"].isin(child_orders)]
        child_items = child_meta["raw_item"].astype(str).tolist() if not child_meta.empty else []

        # Nested totals/subtotals inside child set can cause double counting.
        nested = child_meta[
            child_meta.apply(_is_total_row, axis=1)
        ] if not child_meta.empty else pd.DataFrame()

        target_values = work[
            (pd.to_numeric(work["row_order"], errors="coerce") == target_order)
            & work["value"].notna()
        ]

        if target_values.empty:
            results.append({
                "target_row_order":target_order,"target_item":target_item,
                "target_row_type":target.get("row_type"),"pattern":pattern,
                "child_row_orders":" | ".join(map(str,child_orders)),
                "child_items":" | ".join(child_items),
                "confidence":confidence,
                "status":"NOT_TESTABLE_NO_TARGET_VALUE",
                "inference_reason":reason,
            })
            continue

        for _, tv in target_values.iterrows():
            dim = _clean(tv.get(dim_col))
            year, scope = _clean(tv.get("year")), _clean(tv.get("scope"))
            restated = bool(tv.get("restated"))
            unit = _clean(tv.get("unit"))
            reported = float(tv["value"])

            base = {
                "target_row_order":target_order,
                "target_item":target_item,
                "target_row_type":target.get("row_type"),
                "pattern":pattern,
                "child_row_orders":" | ".join(map(str,child_orders)),
                "child_items":" | ".join(child_items),
                "dimension_key":dim,
                "year":year,"scope":scope,"restated":restated,"unit":unit,
                "reported_total":reported,
                "confidence":confidence,
                "inference_reason":reason,
            }

            if not child_orders:
                results.append({
                    **base,
                    "calculated_sum":None,"difference":None,"difference_ratio":None,
                    "status":"NOT_TESTABLE_NO_CONFIDENT_CHILD_SET",
                })
                continue

            if not nested.empty:
                results.append({
                    **base,
                    "calculated_sum":None,"difference":None,"difference_ratio":None,
                    "status":"WARNING_COMPONENT_SCOPE_AMBIGUOUS",
                    "inference_reason":reason+"；候选子项中含嵌套TOTAL/SUBTOTAL，避免重复计算",
                })
                continue

            children = work[
                pd.to_numeric(work["row_order"], errors="coerce").isin(child_orders)
                & work["value"].notna()
            ].copy()
            if dim_col in children:
                children = children[children[dim_col].fillna("").astype(str) == str(tv.get(dim_col) or "")]

            if children.empty or children["row_order"].nunique() != len(set(child_orders)):
                results.append({
                    **base,
                    "calculated_sum":None,"difference":None,"difference_ratio":None,
                    "status":"WARNING_COMPONENT_SCOPE_AMBIGUOUS",
                    "inference_reason":reason+"；部分候选子项在该数据窗口缺值",
                })
                continue

            units = {_clean(x) for x in children.get("unit", pd.Series(dtype=str)).tolist() if _clean(x)}
            if unit and units and (len(units) != 1 or unit not in units):
                results.append({
                    **base,
                    "calculated_sum":None,"difference":None,"difference_ratio":None,
                    "status":"WARNING_COMPONENT_SCOPE_AMBIGUOUS",
                    "inference_reason":reason+"；子项单位与target不一致",
                })
                continue

            calculated = float(children["value"].astype(float).sum())
            diff = calculated - reported
            ratio = abs(diff) / max(abs(reported), 1e-12)
            exact_tol = max(1e-8, abs(reported) * 1e-12)
            rounding_tol = max(0.02, abs(reported) * 1e-8)
            if abs(diff) <= exact_tol:
                status = "PASS_EXACT"
            elif abs(diff) <= rounding_tol:
                status = "PASS_ROUNDING"
            else:
                status = "WARNING_SUM_MISMATCH"

            results.append({
                **base,
                "calculated_sum":calculated,
                "difference":diff,
                "difference_ratio":ratio,
                "status":status,
            })

    return pd.DataFrame(results, columns=columns)


def write_reconciliation_audit(run_dir: Path) -> Path:
    run_dir = Path(run_dir)
    official = run_dir / "table_raw_long.csv"
    out = run_dir / "table_reconciliation_audit.csv"
    if not official.exists():
        pd.DataFrame().to_csv(out,index=False,encoding="utf-8-sig")
        return out
    df = pd.read_csv(official)
    audit = reconciliation_audit_from_long(df)
    audit.to_csv(out,index=False,encoding="utf-8-sig")

    summary = {
        "rows":len(audit),
        "warnings":int(audit["status"].astype(str).str.startswith("WARNING").sum()) if not audit.empty else 0,
        "not_testable":int(audit["status"].astype(str).str.startswith("NOT_TESTABLE").sum()) if not audit.empty else 0,
        "passes":int(audit["status"].astype(str).str.startswith("PASS").sum()) if not audit.empty else 0,
    }
    (run_dir/"reconciliation_summary.json").write_text(
        json.dumps(summary,ensure_ascii=False,indent=2),encoding="utf-8"
    )
    return out
