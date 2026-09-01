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


def _section_operator(row: pd.Series) -> Optional[int]:
    if _clean(row.get("row_type")) != "SECTION_HEADER":
        return None
    name = _clean(row.get("normalized_item") or row.get("raw_item"))
    if name == "减":
        return -1
    if name == "加":
        return 1
    return None


def _infer_formula(meta: pd.DataFrame, target_idx: int) -> dict[str, Any]:
    """
    Infer a structural reconciliation formula.

    Returns:
      component row orders
      per-component operators (+1/-1)
      pattern/confidence/reason

    Arithmetic is never used to choose membership.
    """
    target = meta.iloc[target_idx]
    target_level = int(target.get("row_level", 0))
    target_name = _clean(target.get("normalized_item") or target.get("raw_item"))
    target_type = _clean(target.get("row_type"))

    # 1) Leading parent/subtotal:
    #    小计
    #       A
    #       B
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

        if following:
            break
        if r_type in BOUNDARY_TYPES or r_level <= target_level:
            break

    if following:
        return {
            "orders": following,
            "operators": [1] * len(following),
            "pattern": "LEADING_PARENT_TOTAL",
            "confidence": (
                "HIGH" if all(
                    _clean(
                        meta[meta["row_order"] == o].iloc[0].get("parent_section")
                    ) == target_name
                    for o in following
                ) else "MEDIUM"
            ),
            "reason": "target后方连续更深层级/显式parent_section子项",
        }

    # 2) Net formula with an explicit 加:/减: section:
    #
    #    小计
    #    减:
    #      获取现金流
    #      履约现金流
    #    合计
    #
    #    => 合计 = 小计 - 获取现金流 - 履约现金流
    if target_type == "TOTAL" or target_name in {"合计", "总计"}:
        modifier_idx = None
        modifier_op = None
        for j in range(target_idx - 1, -1, -1):
            op = _section_operator(meta.iloc[j])
            if op is not None:
                modifier_idx = j
                modifier_op = op
                break
            # Another final total before any modifier means this pattern doesn't apply.
            if _is_total_row(meta.iloc[j]):
                break

        if modifier_idx is not None and modifier_op is not None:
            base_idx = None
            for j in range(modifier_idx - 1, -1, -1):
                if _is_total_row(meta.iloc[j]):
                    base_idx = j
                    break
                if _clean(meta.iloc[j].get("row_type")) == "SECTION_HEADER":
                    # Do not cross an unrelated section when searching for base.
                    continue

            component_rows = [
                int(meta.iloc[j]["row_order"])
                for j in range(modifier_idx + 1, target_idx)
                if _clean(meta.iloc[j].get("row_type")) != "SECTION_HEADER"
            ]
            if base_idx is not None and component_rows:
                base_order = int(meta.iloc[base_idx]["row_order"])
                return {
                    "orders": [base_order] + component_rows,
                    "operators": [1] + [modifier_op] * len(component_rows),
                    "pattern": (
                        "BASE_MINUS_COMPONENTS"
                        if modifier_op == -1 else
                        "BASE_PLUS_COMPONENTS"
                    ),
                    "confidence": "HIGH",
                    "reason": (
                        f"检测到显式{'减' if modifier_op == -1 else '加'}项section；"
                        "以前一TOTAL/SUBTOTAL为base，后续连续明细为调整项"
                    ),
                }

    # 3) Trailing total:
    #    A
    #    B
    #    ...
    #    小计/合计
    #
    # Use the preceding structural block. Text-only DETAIL rows do NOT break the
    # membership window; they remain children and may make arithmetic NOT_TESTABLE.
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
            if _clean(meta.iloc[j].get("row_type")) != "SECTION_HEADER"
            and not _is_total_row(meta.iloc[j])
        ]
        if preceding:
            return {
                "orders": preceding,
                "operators": [1] * len(preceding),
                "pattern": "TRAILING_TOTAL",
                "confidence": "HIGH" if boundary_reason != "表首" else "MEDIUM",
                "reason": f"{boundary_reason}之后至target之前的连续明细",
            }

    return {
        "orders": [],
        "operators": [],
        "pattern": "UNKNOWN",
        "confidence": "LOW",
        "reason": "未找到可信结构子项集合",
    }


def reconciliation_audit_from_long(long_df: pd.DataFrame) -> pd.DataFrame:
    columns = [
        "target_row_order","target_item","target_row_type","pattern",
        "child_row_orders","child_items","component_operators","formula_expression",
        "dimension_key","year","scope","restated","unit",
        "reported_total","calculated_sum","difference","difference_ratio",
        "confidence","status","inference_reason",
    ]
    if long_df.empty or "row_order" not in long_df.columns:
        return pd.DataFrame(columns=columns)

    meta = _row_meta(long_df)
    if meta.empty:
        return pd.DataFrame(columns=columns)

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

        formula = _infer_formula(meta, target_idx)
        child_orders = formula["orders"]
        operators = formula["operators"]
        pattern = formula["pattern"]
        confidence = formula["confidence"]
        reason = formula["reason"]

        target_order = int(target["row_order"])
        target_item = _clean(target.get("raw_item") or target.get("normalized_item"))
        child_meta = meta[meta["row_order"].isin(child_orders)].copy()
        child_item_map = {
            int(r["row_order"]): str(r["raw_item"])
            for _, r in child_meta.iterrows()
        }
        child_items = [child_item_map.get(o, "") for o in child_orders]

        target_values = work[
            (pd.to_numeric(work["row_order"], errors="coerce") == target_order)
            & work["value"].notna()
        ]

        operator_text = " | ".join("+" if x == 1 else "-" for x in operators)
        formula_expression = " ".join(
            f"{'+' if op == 1 else '-'}[{order}:{item}]"
            for order, item, op in zip(child_orders, child_items, operators)
        ).lstrip("+").strip()

        if target_values.empty:
            results.append({
                "target_row_order":target_order,"target_item":target_item,
                "target_row_type":target.get("row_type"),"pattern":pattern,
                "child_row_orders":" | ".join(map(str,child_orders)),
                "child_items":" | ".join(child_items),
                "component_operators":operator_text,
                "formula_expression":formula_expression,
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
                "component_operators":operator_text,
                "formula_expression":formula_expression,
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

            # Plain trailing/leading sums should not contain nested totals, because
            # that risks double counting. Formula patterns explicitly allow their
            # first component to be a base subtotal.
            if pattern in {"TRAILING_TOTAL", "LEADING_PARENT_TOTAL"}:
                nested = child_meta[child_meta.apply(_is_total_row, axis=1)]
                if not nested.empty:
                    results.append({
                        **base,
                        "calculated_sum":None,"difference":None,"difference_ratio":None,
                        "status":"WARNING_COMPONENT_SCOPE_AMBIGUOUS",
                        "inference_reason":reason+"；候选子项中含嵌套TOTAL/SUBTOTAL，避免重复计算",
                    })
                    continue

            component_values = []
            missing_orders = []
            units_seen = set()

            for order, operator in zip(child_orders, operators):
                g = work[
                    (pd.to_numeric(work["row_order"], errors="coerce") == order)
                    & work["value"].notna()
                ].copy()
                if dim_col in g:
                    g = g[g[dim_col].fillna("").astype(str) == str(tv.get(dim_col) or "")]
                if g.empty:
                    missing_orders.append(order)
                    continue

                vals = [float(x) for x in g["value"].dropna().tolist()]
                unique_vals = []
                for val in vals:
                    if not any(abs(val-u) <= max(1e-8, abs(u)*1e-10) for u in unique_vals):
                        unique_vals.append(val)
                if len(unique_vals) != 1:
                    missing_orders.append(order)
                    continue

                row_units = {
                    _clean(x)
                    for x in g.get("unit", pd.Series(dtype=str)).tolist()
                    if _clean(x)
                }
                units_seen.update(row_units)
                component_values.append(operator * unique_vals[0])

            if missing_orders:
                results.append({
                    **base,
                    "calculated_sum":None,"difference":None,"difference_ratio":None,
                    "status":"WARNING_COMPONENT_SCOPE_AMBIGUOUS",
                    "inference_reason":(
                        reason
                        + "；部分候选成员在该数据窗口缺值/值不唯一："
                        + ",".join(map(str, missing_orders))
                    ),
                })
                continue

            if unit and units_seen and (len(units_seen) != 1 or unit not in units_seen):
                results.append({
                    **base,
                    "calculated_sum":None,"difference":None,"difference_ratio":None,
                    "status":"WARNING_COMPONENT_SCOPE_AMBIGUOUS",
                    "inference_reason":reason+"；成员单位与target不一致",
                })
                continue

            calculated = float(sum(component_values))
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

    def _write_summary() -> None:
        (run_dir / "reconciliation_summary.json").write_text(
            json.dumps({
                "rows": 0, "warnings": 0, "not_testable": 0, "passes": 0,
            }, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    if not official.exists() or official.stat().st_size <= 0:
        pd.DataFrame().to_csv(out, index=False, encoding="utf-8-sig")
        _write_summary()
        return out
    try:
        df = pd.read_csv(official)
    except pd.errors.EmptyDataError:
        pd.DataFrame().to_csv(out, index=False, encoding="utf-8-sig")
        _write_summary()
        return out
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
