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


def project_certified_row_hierarchy(
    rows: pd.DataFrame,
    *,
    allow_legacy_compatibility: bool = False,
) -> pd.DataFrame:
    """Project display paths from the certified source-row graph.

    This is a consumer-side projection only. It never infers or mutates a
    parent edge. ``row_order`` is used solely to preserve source display order.
    """
    out = rows.copy()
    if out.empty:
        for column in (
            "hierarchy_parent_label", "hierarchy_parent_path", "hierarchy_path",
            "hierarchy_level", "hierarchy_status",
        ):
            if column not in out.columns:
                out[column] = pd.Series(dtype="object")
        return out

    for column in (
        "source_row_id", "parent_row_id", "normalized_item", "raw_item", "row_order",
        "parent_section",
    ):
        if column not in out.columns:
            out[column] = None

    # Legacy Capture Long files commonly contain an all-empty parent column.
    # pandas infers that column as float64 (or an immutable Arrow string array),
    # but the compatibility projection may need to materialize a certified
    # string parent ID below.  Keep identity columns in a writable object
    # container before any projection/merge assignment.
    for column in ("source_row_id", "parent_row_id"):
        out[column] = out[column].astype("object")

    structural = out[
        [
            "source_row_id", "parent_row_id", "normalized_item", "raw_item",
            "row_order", "parent_section",
        ]
    ].drop_duplicates().copy()
    structural["_source_id"] = structural["source_row_id"].map(_text)
    structural["_parent_id"] = structural["parent_row_id"].map(_text)
    structural["_label"] = structural["normalized_item"].map(_text)
    missing_label = structural["_label"].eq("")
    structural.loc[missing_label, "_label"] = structural.loc[missing_label, "raw_item"].map(_text)
    structural["_row_order"] = pd.to_numeric(structural["row_order"], errors="coerce")
    structural = structural.sort_values("_row_order", kind="stable")

    # A prior compatibility projection may have persisted a synthetic legacy
    # ID based on an old row order. If a caller later reorders/splits those
    # rows, discard only that synthetic ID and regenerate it from the current
    # source order; certified IDs are never regenerated.
    legacy_ids = structural["_source_id"].str.startswith("LEGACY_ROW_ORDER::")
    for source_id, group in structural[legacy_ids].groupby("_source_id", sort=False):
        if group["row_order"].nunique(dropna=False) > 1:
            structural.loc[group.index, "_source_id"] = ""

    if structural["_source_id"].eq("").any():
        if not allow_legacy_compatibility:
            missing_orders = structural.loc[
                structural["_source_id"].eq(""), "row_order"
            ].tolist()
            raise ValueError(f"SOURCE_ROW_ID_REQUIRED:{missing_orders}")
        order_occurrences: dict[str, int] = {}
        for index in structural.index[structural["_source_id"].eq("")]:
            order = _text(structural.at[index, "row_order"])
            occurrence = order_occurrences.get(order, 0) + 1
            order_occurrences[order] = occurrence
            suffix = f"::{occurrence}" if occurrence > 1 else ""
            structural.at[index, "_source_id"] = f"LEGACY_ROW_ORDER::{order}{suffix}"

        # Explicit compatibility adapter for old immutable Captures. New
        # Captures never enter this branch and therefore never consume legacy
        # parent labels as certified edges.
        prior_labels: dict[str, list[str]] = {}
        for index, row in structural.iterrows():
            source_id = _text(row.get("_source_id"))
            parent_label = _text(row.get("parent_section"))
            if not _text(row.get("_parent_id")) and parent_label:
                candidates = prior_labels.get(parent_label, [])
                if len(candidates) == 1:
                    structural.at[index, "_parent_id"] = candidates[0]
            label = _text(row.get("_label"))
            if label and source_id not in prior_labels.setdefault(label, []):
                prior_labels[label].append(source_id)

    duplicate_ids = structural.loc[
        structural["_source_id"].duplicated(keep=False), "_source_id"
    ].unique().tolist()
    if duplicate_ids:
        raise ValueError(f"SOURCE_ROW_ID_NOT_UNIQUE:{duplicate_ids}")

    records = {
        row["_source_id"]: row
        for _, row in structural.iterrows()
    }
    projected: dict[str, dict[str, Any]] = {}

    def resolve(source_id: str, active: tuple[str, ...] = ()) -> dict[str, Any]:
        if source_id in projected:
            return projected[source_id]
        if source_id in active:
            cycle = " -> ".join((*active, source_id))
            raise ValueError(f"PARENT_ROW_ID_CYCLE:{cycle}")
        row = records[source_id]
        label = _text(row.get("_label")) or source_id
        parent_id = _text(row.get("_parent_id"))
        compatibility = source_id.startswith("LEGACY_ROW_ORDER::")
        if not parent_id:
            result = {
                "projected_parent_row_id": "",
                "hierarchy_parent_label": "",
                "hierarchy_parent_path": "",
                "hierarchy_path": label,
                "hierarchy_level": 0,
                "hierarchy_status": (
                    "LEGACY_IDENTITY_COMPATIBILITY" if compatibility else "CERTIFIED_ROOT"
                ),
            }
        elif parent_id not in records:
            result = {
                "projected_parent_row_id": parent_id,
                "hierarchy_parent_label": "",
                "hierarchy_parent_path": f"UNRESOLVED_PARENT::{parent_id}",
                "hierarchy_path": f"UNRESOLVED_PARENT::{parent_id} / {label}",
                "hierarchy_level": None,
                "hierarchy_status": "PARENT_ROW_ID_UNRESOLVED",
            }
        else:
            parent = resolve(parent_id, (*active, source_id))
            parent_label = _text(records[parent_id].get("_label")) or parent_id
            result = {
                "projected_parent_row_id": parent_id,
                "hierarchy_parent_label": parent_label,
                "hierarchy_parent_path": parent["hierarchy_path"],
                "hierarchy_path": f"{parent['hierarchy_path']} / {label}",
                "hierarchy_level": (
                    int(parent["hierarchy_level"]) + 1
                    if parent["hierarchy_level"] is not None else None
                ),
                "hierarchy_status": (
                    parent["hierarchy_status"]
                    if parent["hierarchy_status"] != "CERTIFIED_ROOT"
                    else "CERTIFIED_PARENT_GRAPH"
                ),
            }
        projected[source_id] = result
        return result

    for source_id in records:
        resolve(source_id)

    projection = pd.DataFrame([
        {"_source_id": source_id, **values}
        for source_id, values in projected.items()
    ])
    out["_source_id"] = out["source_row_id"].map(_text)
    if allow_legacy_compatibility and (
        out["_source_id"].eq("").any()
        or out["_source_id"].str.startswith("LEGACY_ROW_ORDER::").any()
    ):
        legacy_map = {}
        for _, row in structural.iterrows():
            if row["_source_id"].startswith("LEGACY_ROW_ORDER::"):
                legacy_map.setdefault(_text(row["row_order"]), row["_source_id"])
        legacy_rows = (
            out["_source_id"].eq("")
            | out["_source_id"].str.startswith("LEGACY_ROW_ORDER::")
        )
        out.loc[legacy_rows, "_source_id"] = out.loc[legacy_rows, "row_order"].map(
            lambda value: legacy_map.get(_text(value), "")
        )
    out["source_row_id"] = out["_source_id"]
    projection_columns = [
        column for column in projection.columns if column != "_source_id"
    ]
    out = out.drop(columns=[column for column in projection_columns if column in out.columns])
    out = out.merge(projection, on="_source_id", how="left").drop(columns=["_source_id"])
    empty_parent = out["parent_row_id"].map(_text).eq("")
    out.loc[empty_parent, "parent_row_id"] = out.loc[
        empty_parent, "projected_parent_row_id"
    ]
    out = out.drop(columns=["projected_parent_row_id"])
    # ``row_path`` remains a compatibility/display projection, never an input.
    out["row_path"] = out["hierarchy_path"]
    return out


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
    required = [
        "row_order", "source_row_id", "parent_row_id", "normalized_item",
        "parent_section", "row_type", "row_level",
    ]
    for col in required:
        if col not in out:
            out[col] = None
    structural = out[required].drop_duplicates("row_order", keep="first").copy()
    structural["_order"] = pd.to_numeric(structural["row_order"], errors="coerce").fillna(10**9).astype(int)
    structural = structural.sort_values("_order", kind="stable")

    stack: list[dict[str, Any]] = []
    rows_by_source_id: dict[str, dict[str, Any]] = {}
    for _, item in structural.iterrows():
        source_id = _text(item.get("source_row_id"))
        if source_id:
            rows_by_source_id[source_id] = {
                "order": int(item["_order"]),
                "label": _text(item.get("normalized_item")),
                "path": "",
            }
    edges: list[StructureEdge] = []
    for _, row in structural.iterrows():
        order = int(row["_order"])
        label = _text(row.get("normalized_item")) or f"ROW_{order}"
        parent_section = _text(row.get("parent_section"))
        certified_parent_id = _text(row.get("parent_row_id"))
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
        if certified_parent_id:
            parent = rows_by_source_id.get(certified_parent_id)
            if parent is not None:
                confidence, evidence = 1.0, ["CERTIFIED_PARENT_ROW_ID"]
            else:
                confidence, evidence = 0.0, ["PARENT_ROW_ID_UNRESOLVED"]
        elif parent_section:
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
        source_id = _text(row.get("source_row_id"))
        if source_id in rows_by_source_id:
            rows_by_source_id[source_id]["path"] = path
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
    if "hierarchy_path" in df and df["hierarchy_path"].notna().all():
        out = df.copy()
        out["row_path"] = out["hierarchy_path"]
        return out
    if "source_row_id" in df and df["source_row_id"].notna().any():
        projected = project_certified_row_hierarchy(df, allow_legacy_compatibility=True)
        out = df.copy()
        out["row_path"] = projected["hierarchy_path"]
        return out
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
