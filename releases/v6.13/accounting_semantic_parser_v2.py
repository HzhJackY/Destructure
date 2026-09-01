"""Evidence-preserving accounting row-role ontology for v6.7."""
from __future__ import annotations

import re
import uuid
from typing import Any

ROW_ROLES = {"SECTION", "DETAIL", "BREAKDOWN_DETAIL", "SUBTOTAL", "TOTAL", "IMPLICIT_TOTAL", "GROSS_VALUE", "NET_VALUE", "ADJUSTMENT", "MEMO_TEXT", "NOTE_TEXT", "ANONYMOUS_NUMERIC_ROW"}

OBSERVATION_TYPES = {"SOURCE_OBSERVATION", "DERIVED_OBSERVATION"}

DERIVED_STATUSES = {
    "DERIVED_VALIDATED",
    "DERIVED_REJECTED_NON_BLOCKING",
    "DERIVED_EXCLUDED",
    "SUPPRESSED_BY_EXPLICIT_TOTAL",
    "REQUIRED_DERIVED_TOTAL_UNRESOLVED",
}

def infer_row_role(raw_item: str | None, row_type: str | None = None, *, has_value: bool = False) -> str:
    text = str(raw_item or "").strip()
    norm = re.sub(r"\s+", "", text)
    # Empty-label numeric rows default to ANONYMOUS_NUMERIC_ROW.
    # Only recover_implicit_total_rows() may upgrade them to IMPLICIT_TOTAL
    # after strict arithmetic reconciliation against ≥2 breakdown children.
    if not text and has_value: return "ANONYMOUS_NUMERIC_ROW"
    if row_type == "MEMO_TEXT" or any(x in norm for x in ("注：", "说明", "其中：")): return "MEMO_TEXT" if has_value is False else "NOTE_TEXT"
    if re.search(r"^(合计|总计|投资资产合计|总额)$", norm) or norm.endswith("合计"): return "TOTAL"
    if re.search(r"^(小计|其中|减：|加：)", norm): return "SUBTOTAL" if "计" in norm else "ADJUSTMENT"
    if norm.startswith("减") or "减：" in norm: return "ADJUSTMENT"
    if "净额" in norm or norm.startswith("净"): return "NET_VALUE"
    if "原值" in norm or "账面余额" in norm: return "GROSS_VALUE"
    if row_type == "SECTION" or (not has_value and text.endswith("：")): return "SECTION"
    return "DETAIL"

def build_semantic_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Assign stable row ids/path/roles without modifying raw amount evidence."""
    out=[]; parent_stack: list[tuple[int,str,str]]=[]
    for i,row in enumerate(rows):
        copy=dict(row); level=int(copy.get("row_level") or 0); raw=copy.get("raw_item")
        # Preserve any pre-assigned row_role (e.g. IMPLICIT_TOTAL from recovery).
        # Only infer when the caller has not already classified the row.
        pre_role = str(copy.get("row_role") or "")
        role = pre_role if pre_role else infer_row_role(raw, copy.get("row_type"), has_value=copy.get("value") is not None)
        while parent_stack and parent_stack[-1][0] >= level: parent_stack.pop()
        parent=parent_stack[-1] if parent_stack else None
        row_id=copy.get("source_row_id") or copy.get("row_id") or "ROW_"+uuid.uuid4().hex
        # observation_type defaults to SOURCE_OBSERVATION — only derived rows
        # (IMPLICIT_TOTAL after arithmetic verification) are marked DERIVED.
        observation_type = copy.get("observation_type", "SOURCE_OBSERVATION")
        if role == "IMPLICIT_TOTAL":
            observation_type = "DERIVED_OBSERVATION"
        existing_parent = copy.get("parent_row_id")
        copy.update({"row_id":row_id,"source_row_id":row_id,
                     "parent_row_id":existing_parent if existing_parent else (parent[1] if parent else None),"row_role":role,"row_level":level,
                     "row_path":" / ".join([parent[2],str(raw or copy.get("derived_item") or "[推导总额]")]) if parent else str(raw or copy.get("derived_item") or "[推导总额]"),
                     "observation_type": observation_type})
        if role == "IMPLICIT_TOTAL":
            copy.setdefault("derived_item", "推导总额"); copy.setdefault("label_derivation", "DERIVED_FROM_STRUCTURE")
        if role in {"SECTION","DETAIL","BREAKDOWN_DETAIL"} and raw:
            parent_stack.append((level,row_id,copy["row_path"]))
        out.append(copy)
    return out

def arithmetic_relationships(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Emit, never apply, unit-aware/rounding-aware relationship candidates."""
    relations=[]
    for position, row in enumerate(rows):
        if row.get("row_role") not in {"TOTAL","IMPLICIT_TOTAL","NET_VALUE"}: continue
        children=[x for x in rows if x.get("parent_row_id")==row.get("row_id") and x.get("value") is not None]
        # An implicit total is commonly a blank-label numeric row following a
        # breakdown, so it has no textual parent. Use the immediately preceding
        # sibling/breakdown rows as a candidate only; never alter the value.
        if not children and row.get("row_role") == "IMPLICIT_TOTAL":
            level = row.get("row_level")
            for previous in reversed(rows[:position]):
                if previous.get("row_role") == "SECTION" and int(previous.get("row_level") or 0) <= int(level or 0):
                    break
                if previous.get("value") is not None:
                    children.insert(0, previous)
        if not children: continue
        relations.append({"row_id":row["row_id"],"relationship":"SUM_CHILDREN" if row.get("row_role")!="NET_VALUE" else "GROSS_MINUS_ADJUSTMENT","derived_from_rows":[x["row_id"] for x in children],"unit":row.get("unit"),"rounding_aware":True,"status":"CANDIDATE_ONLY"})
    return relations
