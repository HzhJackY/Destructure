"""v6.2 财务表结构解析：保留机器证据之外的可审核派生结构。"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any
import math
import re
import json

import pandas as pd


TOTAL_TOKENS = ("小计", "合计", "总计", "总额")
UNIT_SCALE = {"元": 1.0, "千元": 1_000.0, "万元": 10_000.0, "百万元": 1_000_000.0, "亿元": 100_000_000.0}


def _text(value: Any) -> str:
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return ""
    return re.sub(r"\s+", "", str(value)).strip()


def rounding_tolerance(unit: Any, child_count: int = 1, values_are_yuan: bool = True) -> float:
    """Return a conservative display-rounding tolerance in the stored value scale."""
    base = UNIT_SCALE.get(_text(unit), 1.0)
    # A displayed component can differ by half a final display unit.  Use one
    # whole unit per displayed component, then allow the subtotal's own rounding.
    tolerance = base * max(1, int(child_count) + 1)
    return tolerance if values_are_yuan else max(1e-8, float(child_count + 1))


def values_close(left: float, right: float, *, unit: Any, child_count: int = 1, values_are_yuan: bool = True) -> tuple[bool, float]:
    tolerance = rounding_tolerance(unit, child_count, values_are_yuan)
    difference = abs(float(left) - float(right))
    return difference <= tolerance, difference


@dataclass(frozen=True)
class StructureEdge:
    row_order: int
    parent_row_order: int | None
    row_path: str
    confidence: float
    evidence: str


def infer_row_structure(long_df: pd.DataFrame) -> pd.DataFrame:
    """Infer a row tree from explicit sections, level, ordering and subtotal cues.

    This never edits ``table_capture_result.json``. It returns a derived view
    with ``row_path`` and provenance so a reviewer can override it later.
    """
    if long_df.empty:
        return long_df.copy()
    out = long_df.copy()
    required = ["row_order", "normalized_item", "parent_section", "row_type", "row_level"]
    for col in required:
        if col not in out:
            out[col] = None
    structural = out[required].drop_duplicates("row_order", keep="first").copy()
    structural["_order"] = pd.to_numeric(structural["row_order"], errors="coerce").fillna(10**9).astype(int)
    structural = structural.sort_values("_order", kind="stable")

    stack: list[dict[str, Any]] = []
    edges: list[StructureEdge] = []
    for _, row in structural.iterrows():
        order = int(row["_order"])
        label = _text(row.get("normalized_item")) or f"ROW_{order}"
        parent_section = _text(row.get("parent_section"))
        row_type = _text(row.get("row_type"))
        level_raw = pd.to_numeric(row.get("row_level"), errors="coerce")
        level = int(level_raw) if not pd.isna(level_raw) else 0
        is_total = any(token in label for token in TOTAL_TOKENS) or "TOTAL" in row_type.upper() or "SUBTOTAL" in row_type.upper()

        if level <= 0:
            stack.clear()
        else:
            while stack and stack[-1]["level"] >= level:
                stack.pop()
        parent = stack[-1] if stack else None
        confidence, evidence = 0.35, ["ORDER"]
        if parent_section:
            candidates = [x for x in reversed(stack) if x["label"] == parent_section]
            if candidates:
                parent = candidates[0]
                confidence, evidence = 0.82, ["EXPLICIT_PARENT_SECTION", "ORDER"]
            else:
                confidence, evidence = 0.58, ["PARENT_SECTION_UNMATCHED", "ORDER"]
        elif level > 0 and parent is not None:
            confidence, evidence = 0.66, ["ROW_LEVEL", "ORDER"]
        if is_total:
            confidence = max(confidence, 0.72)
            evidence.append("TOTAL_SUBTOTAL_CUE")

        parent_path = parent["path"] if parent else ""
        path = f"{parent_path} / {label}" if parent_path else label
        edges.append(StructureEdge(order, parent["order"] if parent else None, path, min(confidence, .99), "+".join(evidence)))
        # Totals close a local calculation rather than becoming a parent.
        if not is_total:
            stack.append({"order": order, "level": level, "label": label, "path": path})

    edge_df = pd.DataFrame([e.__dict__ for e in edges]).rename(columns={"row_order": "_structure_row_order"})
    out["_structure_row_order"] = pd.to_numeric(out["row_order"], errors="coerce").fillna(-1).astype(int)
    out = out.merge(edge_df, on="_structure_row_order", how="left")
    out = out.drop(columns=["_structure_row_order"])
    out = out.rename(columns={"parent_row_order": "parent_row_order", "confidence": "structure_confidence", "evidence": "structure_evidence"})
    return out


def ensure_row_paths(df: pd.DataFrame) -> pd.DataFrame:
    if "row_path" in df and df["row_path"].notna().all():
        return df.copy()
    return infer_row_structure(df)


def subtotal_validation(long_df: pd.DataFrame) -> pd.DataFrame:
    """Warning-only arithmetic checks with unit-aware rounding tolerance."""
    df = ensure_row_paths(long_df)
    if df.empty or "value" not in df:
        return pd.DataFrame()
    rows = df[df["value"].notna()].copy()
    rows["_order"] = pd.to_numeric(rows["row_order"], errors="coerce")
    dims = [c for c in ("column_ordinal", "year", "scope", "restated") if c in rows]
    results: list[dict[str, Any]] = []
    # Only verify explicit parent rows: children share a prefix in the derived path.
    structural = rows[["row_order", "row_path", "normalized_item", "unit"]].drop_duplicates("row_order")
    for _, parent in structural.iterrows():
        parent_label = _text(parent.get("normalized_item"))
        parent_path = _text(parent.get("row_path"))
        if not parent_path or any(token in parent_label for token in TOTAL_TOKENS):
            continue
        child_orders = structural.loc[
            structural["row_path"].astype(str).str.startswith(parent_path + " / ") &
            # ``row_path`` contains verbatim PDF labels.  Parent labels can
            # include parentheses and other regex metacharacters, so this must
            # be escaped before being used as the structural prefix pattern.
            ~structural["row_path"].astype(str).str.contains(re.escape(parent_path) + r" / .* / ", regex=True),
            "row_order",
        ].tolist()
        if len(child_orders) < 2:
            continue
        parent_rows = rows[rows["row_order"] == parent["row_order"]]
        for _, p in parent_rows.iterrows():
            selector = rows["row_order"].isin(child_orders)
            for dim in dims:
                selector &= rows[dim].fillna("<NA>").astype(str) == str(p.get(dim) if pd.notna(p.get(dim)) else "<NA>")
            children = rows[selector]
            if len(children) < 2:
                continue
            child_sum = float(children["value"].sum())
            ok, difference = values_close(float(p["value"]), child_sum, unit=p.get("unit"), child_count=len(children), values_are_yuan=(_text(p.get("unit")) == "元"))
            exact = difference <= max(1e-8, abs(float(p["value"])) * 1e-10)
            results.append({
                "parent_row_order": p["row_order"], "parent_row_path": parent_path,
                "column_ordinal": p.get("column_ordinal"), "parent_value": p["value"],
                "children_sum": child_sum, "difference": difference, "unit": p.get("unit"),
                "tolerance": rounding_tolerance(p.get("unit"), len(children), _text(p.get("unit")) == "元"),
                "status": "PASS" if exact else ("PASS_WITH_ROUNDING" if ok else "WARNING"),
                "evidence": "ROW_PATH_CHILDREN+UNIT_AWARE_ROUNDING",
            })
    # Anonymous rows recovered by v6.6 retain their original NULL label but
    # carry a derived-from chain.  Validate that chain independently from the
    # ordinary row-path hierarchy; it is evidence only and never changes data.
    if "row_role" in rows and "derived_from_rows" in rows:
        implicit = rows[rows["row_role"].astype(str) == "IMPLICIT_TOTAL"].drop_duplicates("row_order")
        for _, total in implicit.iterrows():
            raw_chain = total.get("derived_from_rows")
            try:
                labels = json.loads(raw_chain) if isinstance(raw_chain, str) else list(raw_chain or [])
            except (TypeError, ValueError, json.JSONDecodeError):
                labels = []
            if len(labels) < 2:
                continue
            total_rows = rows[rows["row_order"] == total["row_order"]]
            for _, target in total_rows.iterrows():
                selector = rows["normalized_item"].astype(str).isin([str(x) for x in labels])
                for dim in dims:
                    selector &= rows[dim].fillna("<NA>").astype(str) == str(target.get(dim) if pd.notna(target.get(dim)) else "<NA>")
                children = rows[selector]
                if len(children) < len(labels):
                    continue
                child_sum = float(children["value"].sum())
                ok, difference = values_close(float(target["value"]), child_sum, unit=target.get("unit"), child_count=len(labels), values_are_yuan=(_text(target.get("unit")) == "元"))
                exact = difference <= max(1e-8, abs(float(target["value"])) * 1e-10)
                results.append({
                    "parent_row_order": target["row_order"], "parent_row_path": target.get("row_path"),
                    "column_ordinal": target.get("column_ordinal"), "parent_value": target["value"],
                    "children_sum": child_sum, "difference": difference, "unit": target.get("unit"),
                    "tolerance": rounding_tolerance(target.get("unit"), len(labels), _text(target.get("unit")) == "元"),
                    "status": "PASS_EXACT" if exact else ("PASS_ROUNDING" if ok else "WARNING_MISMATCH"),
                    "evidence": "IMPLICIT_TOTAL_SUM_CHILDREN",
                })
    return pd.DataFrame(results)
