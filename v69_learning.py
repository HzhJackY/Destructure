"""Versioned label contract and deterministic hierarchical backoff for v6.9.

No model in this module produces financial values.  It only ranks structural
candidates using certified human/machine labels and makes abstention explicit.
"""
from __future__ import annotations

import hashlib
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


def _json(value: Any) -> str:
    return json.dumps(value,ensure_ascii=False,sort_keys=True)


def propose_structural_learning_candidate(
    registry,*,adjudication_id:str,
) -> dict[str,Any]:
    """Persist a review-only proposal without changing rules or Golden facts."""
    from metadata_registry import now_iso
    with registry.connect() as conn:
        row=conn.execute(
            """SELECT a.*,c.source_pdf_sha256,c.discovery_run_id,
                      c.resolution_case_id
               FROM child_inventory_adjudications a
               JOIN child_inventory_resolution_cases c
                 ON c.resolution_case_id=a.resolution_case_id
               WHERE a.adjudication_id=?
                 AND a.adjudication_status='ACCEPTED'""",
            (str(adjudication_id),),
        ).fetchone()
        if not row:
            raise PermissionError("ACCEPTED_INVENTORY_ADJUDICATION_REQUIRED")
        existing=conn.execute(
            """SELECT * FROM structural_learning_candidates
               WHERE source_adjudication_id=?""",
            (str(adjudication_id),),
        ).fetchone()
        if existing:
            result=dict(existing)
            for field in ("feature_snapshot","label_snapshot","evidence"):
                result[field]=json.loads(result.pop(field+"_json") or "{}")
            return result
        effective=json.loads(row["effective_snapshot_json"] or "{}")
        decisions=json.loads(row["decisions_json"] or "{}")
        machine=json.loads(
            conn.execute(
                """SELECT machine_snapshot_json
                   FROM child_inventory_resolution_cases
                   WHERE resolution_case_id=?""",
                (row["resolution_case_id"],),
            ).fetchone()[0]
            or "{}"
        )
        feature_snapshot={
            "note_reference":machine.get("note_reference") or "",
            "logical_tables":[
                {
                    "logical_table_candidate_id":item.get(
                        "logical_table_candidate_id"
                    ),
                    "table_order":item.get("table_order"),
                    "machine_classification":item.get("classification")
                        or item.get("proposed_classification"),
                    "signature":dict(item.get("signature") or {}),
                    "segments":[
                        {
                            "segment_candidate_id":segment.get(
                                "segment_candidate_id"
                            ),
                            "machine_classification":segment.get(
                                "classification"
                            ) or segment.get("proposed_classification"),
                            "period_signature":dict(
                                segment.get("period_signature") or {}
                            ),
                            "header_signature":dict(
                                segment.get("header_signature") or {}
                            ),
                            "amount_lane_signature":dict(
                                segment.get("amount_lane_signature") or {}
                            ),
                        }
                        for segment in item.get("segments") or []
                    ],
                }
                for item in machine.get("logical_tables") or []
            ],
        }
        label_snapshot={
            "decisions":decisions,
            "effective_logical_tables":[
                {
                    "logical_table_candidate_id":item.get(
                        "logical_table_candidate_id"
                    ),
                    "classification":item.get("classification"),
                    "segments":[
                        {
                            "segment_candidate_id":segment.get(
                                "segment_candidate_id"
                            ),
                            "logical_table_candidate_id":segment.get(
                                "logical_table_candidate_id"
                            ),
                            "classification":segment.get("classification"),
                            "continuation_of_segment_candidate_id":segment.get(
                                "continuation_of_segment_candidate_id"
                            ),
                        }
                        for segment in item.get("segments") or []
                    ],
                }
                for item in effective.get("logical_tables") or []
            ],
        }
        learning_type="NOTE_TABLE_INVENTORY_SEMANTIC_OVERLAY_V1"
        fingerprint=hashlib.sha256(
            _json({
                "source_adjudication_id":adjudication_id,
                "learning_type":learning_type,
            }).encode("utf-8")
        ).hexdigest()
        learning_candidate_id="SLC_"+fingerprint[:24]
        now=now_iso()
        evidence={
            "resolution_case_id":row["resolution_case_id"],
            "source_adjudication_id":str(adjudication_id),
            "source_pdf_sha256":row["source_pdf_sha256"],
            "source_discovery_run_id":row["discovery_run_id"],
            "same_source_pdf_excluded":True,
            "same_discovery_run_excluded":True,
            "golden_write_permitted":False,
            "promotion_required":True,
        }
        conn.execute(
            """INSERT INTO structural_learning_candidates(
               learning_candidate_id,source_adjudication_id,
               source_pdf_sha256,source_discovery_run_id,learning_type,status,
               feature_snapshot_json,label_snapshot_json,evidence_json,
               producer_version,created_at,updated_at)
               VALUES(?,?,?,?,?,'PROPOSED',?,?,?,?,?,?)""",
            (
                learning_candidate_id,str(adjudication_id),
                str(row["source_pdf_sha256"] or ""),
                str(row["discovery_run_id"] or ""),learning_type,
                _json(feature_snapshot),_json(label_snapshot),_json(evidence),
                str(row["producer_version"] or ""),now,now,
            ),
        )
    return {
        "learning_candidate_id":learning_candidate_id,
        "source_adjudication_id":str(adjudication_id),
        "source_pdf_sha256":str(row["source_pdf_sha256"] or ""),
        "source_discovery_run_id":str(row["discovery_run_id"] or ""),
        "learning_type":learning_type,"status":"PROPOSED",
        "feature_snapshot":feature_snapshot,"label_snapshot":label_snapshot,
        "evidence":evidence,"producer_version":str(row["producer_version"] or ""),
        "created_at":now,"updated_at":now,
    }


def list_structural_learning_candidates(
    registry,*,source_pdf_sha256:str="",discovery_run_id:str="",
) -> list[dict[str,Any]]:
    """List proposals eligible for review, excluding their source PDF/run."""
    if not str(source_pdf_sha256 or "").strip() or not str(
        discovery_run_id or ""
    ).strip():
        raise ValueError("TARGET_SOURCE_CONTEXT_REQUIRED")
    clauses=["status='PROPOSED'"];params:list[Any]=[]
    if source_pdf_sha256:
        clauses.append("source_pdf_sha256<>?")
        params.append(str(source_pdf_sha256))
    if discovery_run_id:
        clauses.append("source_discovery_run_id<>?")
        params.append(str(discovery_run_id))
    with registry.connect() as conn:
        rows=conn.execute(
            "SELECT * FROM structural_learning_candidates WHERE "
            +" AND ".join(clauses)+" ORDER BY created_at",
            params,
        ).fetchall()
    output=[]
    for row in rows:
        item=dict(row)
        for field in ("feature_snapshot","label_snapshot","evidence"):
            item[field]=json.loads(item.pop(field+"_json") or "{}")
        output.append(item)
    return output


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
