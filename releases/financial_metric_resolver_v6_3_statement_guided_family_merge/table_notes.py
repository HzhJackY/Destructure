"""Immutable table-note evidence store for v6.3."""
from __future__ import annotations
import json, re, uuid
from datetime import datetime, timezone
from typing import Any

NOTE_SCOPES={"TABLE","ROW","COLUMN","CELL","FAMILY"}
CLASSIFICATIONS={"SCOPE_DEFINITION","ACCOUNTING_POLICY","RESTATEMENT","INCLUSION_EXCLUSION","CALCULATION_METHOD","UNIT_OR_PRESENTATION","OTHER"}

def classify_note(text: str) -> str:
    t=text.lower()
    if "重述" in t: return "RESTATEMENT"
    if "不包括" in t or "包括" in t: return "INCLUSION_EXCLUSION"
    if "单位" in t or "人民币" in t: return "UNIT_OR_PRESENTATION"
    if "按照" in t or "计量" in t: return "ACCOUNTING_POLICY"
    return "OTHER"

def note_record(raw_text: str, *, capture_id: str="", table_family: str="", member_table: str="", note_scope: str="TABLE", page: int|None=None, bbox: Any=None, **extra: Any) -> dict[str, Any]:
    if note_scope not in NOTE_SCOPES: raise ValueError("unsupported note_scope")
    normalized=re.sub(r"\s+"," ",raw_text).strip()
    return {"note_id":"NOTE_"+uuid.uuid4().hex, "capture_id":capture_id, "table_family":table_family, "member_table":member_table,
            "note_scope":note_scope, "target_row_path":extra.get("target_row_path"), "target_column_dimension":extra.get("target_column_dimension"),
            "note_marker":extra.get("note_marker",""), "raw_text":raw_text, "normalized_text":normalized, "page":page, "bbox":bbox,
            "classification":extra.get("classification") or classify_note(raw_text), "confidence":extra.get("confidence",1.0),
            "source_lineage":extra.get("source_lineage",{}), "created_at":datetime.now(timezone.utc).isoformat()}

def persist_note(registry, record: dict[str, Any]) -> None:
    with registry.connect() as conn:
        conn.execute("""INSERT INTO table_notes(note_id,capture_id,table_family,member_table,note_scope,target_row_path,target_column_dimension_json,note_marker,raw_text,normalized_text,page,bbox_json,classification,confidence,source_lineage_json,created_at)
        VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""", (record["note_id"],record["capture_id"],record["table_family"],record["member_table"],record["note_scope"],record["target_row_path"],json.dumps(record["target_column_dimension"],ensure_ascii=False),record["note_marker"],record["raw_text"],record["normalized_text"],record["page"],json.dumps(record["bbox"]),record["classification"],record["confidence"],json.dumps(record["source_lineage"],ensure_ascii=False),record["created_at"])) 
