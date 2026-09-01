"""Versioned label contract and deterministic hierarchical backoff for v6.9.

No model in this module produces financial values.  It only ranks structural
candidates using certified human/machine labels and makes abstention explicit.
"""
from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from typing import Any


HIERARCHY = ("industry", "company", "filing_type", "statement_type", "scope", "table_family", "member_table")
DEFAULT_LABEL_SCHEMAS = {
    "BLOCK_ROLE_V1": {"values": ["PRIMARY_TABLE", "SECONDARY_TABLE", "NARRATIVE", "REJECTED"]},
    "HEADER_TOPOLOGY_V1": {"values": ["YEAR_VALUE", "VALUE_RATIO", "CREDIT_STAGE", "AMBIGUOUS"]},
    "SEMANTIC_RELATION_V1": {"values": ["TOTAL_OF", "COMPONENT_OF", "MEMO_OF", "NONE"]},
    "RECONCILIATION_V1": {"values": ["PASS", "WARNING", "NOT_TESTABLE"]},
    "ANCHOR_CANDIDATE_V1": {"values": ["SELECTED", "REJECTED", "ALTERNATIVE"]},
}


def seed_label_schemas(registry) -> int:
    from metadata_registry import now_iso
    changed=0
    with registry.connect() as conn:
        for schema_id,payload in DEFAULT_LABEL_SCHEMAS.items():
            exists=conn.execute("SELECT 1 FROM ml_label_schemas WHERE schema_id=?",(schema_id,)).fetchone()
            if not exists:
                conn.execute("INSERT INTO ml_label_schemas(schema_id,label_name,version,payload_json,created_at,updated_at) VALUES(?,?,?,?,?,?)",(schema_id,schema_id.rsplit('_',1)[0],"1",json.dumps(payload,ensure_ascii=False),now_iso(),now_iso()))
                changed += 1
    return changed


def label_entity(registry, *, schema_id: str, entity_type: str, entity_id: str, label_value: str, actor: str, evidence: dict[str,Any]) -> str:
    label_id="MLLBL_"+uuid.uuid4().hex
    from metadata_registry import now_iso
    with registry.connect() as conn:
        schema=conn.execute("SELECT payload_json FROM ml_label_schemas WHERE schema_id=? AND archived=0",(schema_id,)).fetchone()
        if not schema: raise ValueError("UNKNOWN_LABEL_SCHEMA")
        allowed=json.loads(schema["payload_json"]).get("values",[])
        if label_value not in allowed: raise ValueError("INVALID_LABEL_VALUE")
        conn.execute("INSERT INTO ml_labels(label_id,schema_id,entity_type,entity_id,label_value,actor,evidence_json,created_at) VALUES(?,?,?,?,?,?,?,?)",(label_id,schema_id,entity_type,entity_id,label_value,actor,json.dumps(evidence,ensure_ascii=False),now_iso()))
    return label_id


def hierarchical_rank(candidates: list[dict[str,Any]], context: dict[str,Any], certified_examples: list[dict[str,Any]], *, abstain_threshold: float=.70) -> dict[str,Any]:
    """Transparent similarity ranker; score is evidence, not a financial forecast."""
    scored=[]
    for candidate in candidates:
        evidence=[e for e in certified_examples if e.get("label") in {"ACCEPT","CONFIRMED","CONFIRMED_AUTO"}]
        levels=0
        for e in evidence:
            matches=sum(str(e.get(k) or "")==str(context.get(k) or "") and bool(context.get(k)) for k in HIERARCHY)
            levels=max(levels,matches)
        source=float(candidate.get("machine_confidence") or candidate.get("confidence") or 0.0)
        score=min(1.0, source*0.75 + (levels/len(HIERARCHY))*0.25)
        scored.append({**candidate,"v69_rank_score":score,"matched_hierarchy_levels":levels})
    scored.sort(key=lambda x:x["v69_rank_score"],reverse=True)
    if not scored or scored[0]["v69_rank_score"]<abstain_threshold:
        return {"status":"ABSTAIN","reason":"INSUFFICIENT_CERTIFIED_STRUCTURAL_EVIDENCE","candidates":scored}
    return {"status":"RANKED","selected":scored[0],"candidates":scored}
