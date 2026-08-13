"""v6.5 discovery evidence, statement anchors and certified capture plans.

Machine candidates are append-only.  Human actions are separate append-only
events; certified rows are a materialized, reproducible view of those events.
"""
from __future__ import annotations

import json
import sqlite3
import time
import uuid
from datetime import datetime, timezone
from typing import Any, Iterable


VALID_LABELS = {"ACCEPTED", "REJECTED", "OVERRIDDEN", "UNRESOLVED", "REVIEW_REQUIRED"}
VALID_SCOPES = {"REPORT_ONLY", "COMPANY_STATEMENT", "GLOBAL_CANDIDATE"}


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _dump(value: Any) -> str:
    return json.dumps(value or {}, ensure_ascii=False, sort_keys=True)


class DiscoveryRegistry:
    def __init__(self, registry):
        self.registry = registry

    def save_machine(self, row: dict[str, Any]) -> dict[str, Any]:
        payload = dict(row)
        payload.setdefault("discovery_id", "DISC_" + uuid.uuid4().hex)
        payload.setdefault("status", "NEEDS_REVIEW")
        payload.setdefault("created_at", now_iso())
        payload.setdefault("evidence", {})
        with self.registry.connect() as conn:
            conn.execute("""INSERT INTO machine_discoveries(
              discovery_id,pdf_id,company,normalized_company,report_year,filing_type,statement_type,
              display_name,table_family,statement_item,note_reference,statement_value,member_table,
              source_table_title,section_context,statement_page,note_page,locator_method,confidence,
              reconciliation_status,status,evidence_json,created_at,scope,note_reference_section,
              note_reference_item,note_reference_raw,note_reference_normalized,note_reference_status,
              statement_pdf_page_index,statement_printed_page,candidate_note_pdf_page_index,
              candidate_note_printed_page,confirmed_note_pdf_page_index,confirmed_note_printed_page,
              candidate_note_pages_json,bbox_json,candidate_cluster_id)
              VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""", (
              payload["discovery_id"], payload.get("pdf_id"), payload.get("company"),
              payload.get("normalized_company") or payload.get("company"), str(payload.get("report_year") or ""),
              payload.get("filing_type", "ANNUAL_REPORT"), payload.get("statement_type"), payload.get("display_name"),
              payload.get("table_family") or payload.get("display_name"), payload.get("statement_item"),
              str(payload.get("note_reference") or ""), payload.get("statement_value"), payload.get("member_table"),
              payload.get("source_table_title") or payload.get("member_table"), payload.get("section_context"),
              payload.get("statement_pdf_page_index") or payload.get("statement_page"), payload.get("candidate_note_pdf_page_index") or payload.get("note_page"), payload.get("locator_method"),
              float(payload.get("confidence") or 0), payload.get("reconciliation_status"), payload["status"],
              _dump(payload["evidence"]), payload["created_at"], payload.get("scope", "UNKNOWN"),
              payload.get("note_reference_section"), payload.get("note_reference_item"), payload.get("note_reference_raw"),
              payload.get("note_reference_normalized") or payload.get("note_reference"), payload.get("note_reference_status"),
              payload.get("statement_pdf_page_index") or payload.get("statement_page"), payload.get("statement_printed_page"),
              payload.get("candidate_note_pdf_page_index") or payload.get("note_page"), payload.get("candidate_note_printed_page"),
              payload.get("confirmed_note_pdf_page_index"), payload.get("confirmed_note_printed_page"),
              _dump(payload.get("candidate_note_pages") or []), _dump(payload.get("bbox") or {}), payload.get("candidate_cluster_id")))
        return payload

    def save_occurrence(self, row: dict[str, Any]) -> dict[str, Any]:
        """Append one discovered statement occurrence; no occurrence is deduplicated away."""
        payload = dict(row)
        payload.setdefault("occurrence_id", "OCC_" + uuid.uuid4().hex)
        payload.setdefault("created_at", now_iso())
        payload.setdefault("status", "NEEDS_ANCHOR_REVIEW")
        with self.registry.connect() as conn:
            conn.execute("""INSERT INTO statement_occurrences(
                occurrence_id,pdf_id,company,normalized_company,report_year,filing_type,statement_type,scope,
                display_name,table_family,source_table_title,statement_pdf_page_index,statement_printed_page,
                parent_text,child_rows_json,anchor_score,status,evidence_json,created_at)
                VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""", (
                payload["occurrence_id"], payload.get("pdf_id"), payload.get("company"),
                payload.get("normalized_company") or payload.get("company"), str(payload.get("report_year") or ""),
                payload.get("filing_type", "ANNUAL_REPORT"), payload.get("statement_type"), payload.get("scope", "UNKNOWN"),
                payload.get("display_name"), payload.get("table_family") or payload.get("display_name"),
                payload.get("source_table_title"), payload.get("statement_pdf_page_index"), payload.get("statement_printed_page"),
                payload.get("parent_text") or payload.get("display_name"), _dump(payload.get("child_rows") or []),
                payload.get("anchor_score"), payload["status"], _dump(payload.get("evidence") or {}), payload["created_at"]))
        return payload

    def get_occurrence(self, occurrence_id: str) -> dict[str, Any] | None:
        """Return persisted anchor state; plan materialisation must trust this,
        never a mutable Streamlit candidate collection."""
        with self.registry.connect() as conn:
            row = conn.execute("SELECT * FROM statement_occurrences WHERE occurrence_id=?", (occurrence_id,)).fetchone()
            adjudication = conn.execute(
                """SELECT chosen_scope FROM anchor_adjudications
                   WHERE occurrence_id=? AND label='ACCEPTED'
                   ORDER BY created_at DESC LIMIT 1""",
                (occurrence_id,),
            ).fetchone()
        if not row:
            return None
        item = dict(row)
        item["child_rows"] = json.loads(item.pop("child_rows_json") or "[]")
        item["evidence"] = json.loads(item.pop("evidence_json") or "{}")
        item["machine_scope"]=item.get("scope") or "UNKNOWN"
        if adjudication and str(adjudication["chosen_scope"] or "") in {
            "CONSOLIDATED","PARENT_COMPANY"
        }:
            item["scope"]=str(adjudication["chosen_scope"])
            item["evidence"]={
                **item["evidence"],
                "certified_scope_source":"HUMAN_ANCHOR_ADJUDICATION",
            }
        return item

    def is_anchor_certified(self, occurrence_id: str) -> bool:
        """Certification audit is the durable source of truth.

        `statement_occurrences.status` is a materialized convenience field and
        must never be allowed to erase an earlier human certification.
        """
        with self.registry.connect() as conn:
            row=conn.execute(
                """SELECT 1 FROM anchor_certification_audit
                   WHERE selected_candidate_id=? LIMIT 1""",
                (occurrence_id,),
            ).fetchone()
        return bool(row)

    def save_anchor_scores(self, candidates: Iterable[dict[str,Any]]) -> None:
        cands_list = list(candidates)
        for attempt in range(5):
            try:
                with self.registry.connect() as conn:
                    for row in cands_list:
                        score_id="ASCORE_"+uuid.uuid5(
                            uuid.NAMESPACE_URL,
                            f"{row['occurrence_id']}::{row['ranking_version']}",
                        ).hex
                        conn.execute(
                            """INSERT INTO anchor_candidate_scores(
                               score_id,occurrence_id,total_score,qualification_tier,
                               hard_gates_passed,ranking_version,score_components_json,
                               positive_evidence_json,negative_evidence_json,
                               hard_gate_results_json,recommendation_state,selection_state,created_at
                               ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)
                               ON CONFLICT(occurrence_id,ranking_version) DO UPDATE SET
                               total_score=excluded.total_score,
                               qualification_tier=excluded.qualification_tier,
                               hard_gates_passed=excluded.hard_gates_passed,
                               score_components_json=excluded.score_components_json,
                               positive_evidence_json=excluded.positive_evidence_json,
                               negative_evidence_json=excluded.negative_evidence_json,
                               hard_gate_results_json=excluded.hard_gate_results_json,
                               recommendation_state=excluded.recommendation_state,
                               selection_state=excluded.selection_state""",
                            (score_id,row["occurrence_id"],float(row["total_score"]),
                             row["qualification_tier"],int(bool(row["hard_gates_passed"])),
                             row["ranking_version"],_dump(row["score_components"]),
                             _dump(row["positive_evidence"]),_dump(row["negative_evidence"]),
                             _dump(row["hard_gate_results"]),row.get("recommendation_state"),
                             row.get("selection_state"),now_iso()),
                        )
                break
            except sqlite3.OperationalError as e:
                if "locked" in str(e).lower() and attempt < 4:
                    time.sleep(0.15 * (attempt + 1))
                else:
                    raise

    def sync_anchor_review_queue(self, ranking: dict[str,Any]) -> None:
        candidates=list(ranking.get("candidates") or [])
        by_group={}
        for row in candidates:
            key=(str(row.get("pdf_id") or ""),str(row.get("scope") or "UNKNOWN"),str(row.get("display_name") or ""))
            by_group.setdefault(key,[]).append(row)
        now=now_iso()
        with self.registry.connect() as conn:
            for (source,scope,display_name),rows in by_group.items():
                candidate_ids=[str(x["occurrence_id"]) for x in rows]
                placeholders=",".join("?" for _ in candidate_ids)
                certified_ids=set()
                if candidate_ids:
                    certified_ids={
                        str(x["selected_candidate_id"]) for x in conn.execute(
                            f"""SELECT DISTINCT selected_candidate_id
                                FROM anchor_certification_audit
                                WHERE selected_candidate_id IN ({placeholders})""",
                            candidate_ids,
                        ).fetchall()
                    }
                decision=(ranking.get("scope_decisions") or {}).get(f"{source}::{scope}") or {}
                status=(
                    "RESOLVED" if certified_ids else
                    "PENDING" if decision.get("status")=="ANCHOR_SELECTION_REQUIRED" else
                    "RECOMMENDED"
                )
                conn.execute(
                    """INSERT INTO anchor_review_queue(
                       anchor_review_item_id,source_pdf_id,statement_scope,display_name,
                       candidate_ids_json,primary_review_reason,severity,evidence_json,
                       status,created_at,updated_at
                       ) VALUES(?,?,?,?,?,'ANCHOR_SELECTION_REQUIRED','HIGH',?,?,?,?)
                       ON CONFLICT(source_pdf_id,statement_scope,display_name) DO UPDATE SET
                       candidate_ids_json=excluded.candidate_ids_json,
                       evidence_json=excluded.evidence_json,
                       status=CASE
                           WHEN anchor_review_queue.status='RESOLVED' THEN 'RESOLVED'
                           ELSE excluded.status END,
                       updated_at=excluded.updated_at""",
                    ("AREVIEW_"+uuid.uuid4().hex,source,scope,display_name,
                     _dump([x["occurrence_id"] for x in rows]),
                     _dump({"decision":decision,"ranking_version":ranking.get("ranking_version"),
                            "candidates":[{"id":x["occurrence_id"],"score":x["total_score"],
                                           "hard_gates":x["hard_gate_results"]} for x in rows]}),
                     status,now,now),
                )
                if certified_ids:
                    conn.executemany(
                        "UPDATE statement_occurrences SET status='ANCHOR_CERTIFIED' WHERE occurrence_id=?",
                        [(x,) for x in certified_ids],
                    )
                elif status=="PENDING":
                    conn.executemany(
                        """UPDATE statement_occurrences
                           SET status='ANCHOR_SELECTION_REQUIRED'
                           WHERE occurrence_id=?
                           AND status NOT IN ('ANCHOR_CERTIFIED','REJECTED')""",
                        [(x["occurrence_id"],) for x in rows],
                    )

    def list_anchor_review_queue(self,status:str="PENDING")->list[dict[str,Any]]:
        with self.registry.connect() as conn:
            rows=conn.execute(
                "SELECT * FROM anchor_review_queue WHERE status=? ORDER BY updated_at DESC",
                (status,),
            ).fetchall()
        return [dict(x)|{
            "candidate_ids":json.loads(x["candidate_ids_json"] or "[]"),
            "evidence":json.loads(x["evidence_json"] or "{}"),
        } for x in rows]

    def occurrences(self,occurrence_ids:Iterable[str])->list[dict[str,Any]]:
        return [row for row in (self.get_occurrence(x) for x in occurrence_ids) if row]

    def certify_note_target(self, occurrence_id: str, member_table: str, note_reference: str,
                            target: dict[str, Any]) -> dict[str, Any]:
        """Persist the user-confirmed target separately from machine candidates."""
        payload = dict(target)
        payload.setdefault("note_target_id", "NTARGET_" + uuid.uuid4().hex)
        payload.setdefault("status", "CERTIFIED_NOTE_TARGET")
        payload.setdefault("created_at", now_iso())
        with self.registry.connect() as conn:
            conn.execute("""INSERT INTO certified_note_targets(note_target_id,occurrence_id,member_table,note_reference,
              source_pdf_id,confirmed_note_pdf_page_index,target_heading,locator_method,confidence,status,evidence_json,actor,created_at)
              VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)""", (
              payload["note_target_id"], occurrence_id, member_table, note_reference, payload.get("source_pdf_id"),
              payload.get("confirmed_note_pdf_page_index"), payload.get("target_heading"), payload.get("locator_method"),
              float(payload.get("confidence") or 0), payload["status"], _dump(payload.get("evidence") or {}), payload.get("actor"), payload["created_at"]))
        return payload

    def save_clusters(self, clusters: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
        saved = []
        with self.registry.connect() as conn:
            for cluster in clusters:
                payload = dict(cluster)
                payload.setdefault("candidate_cluster_id", "CLUSTER_" + uuid.uuid4().hex)
                payload.setdefault("created_at", now_iso())
                payload.setdefault("status", "PENDING")
                conn.execute("""INSERT OR REPLACE INTO discovery_candidate_clusters(
                    cluster_id,normalized_company,report_year,display_name,statement_type,scope,member_table,
                    candidate_note_pdf_page_index,confidence,status,evidence_json,created_at)
                    VALUES(?,?,?,?,?,?,?,?,?,?,?,?)""", (
                    payload["candidate_cluster_id"], payload.get("normalized_company") or payload.get("company"),
                    str(payload.get("report_year") or ""), payload.get("display_name"), payload.get("statement_type"),
                    payload.get("scope", "UNKNOWN"), payload.get("member_table") or payload.get("statement_item"),
                    payload.get("candidate_note_pdf_page_index") or payload.get("note_page"), float(payload.get("confidence") or 0),
                    payload["status"], _dump(payload.get("evidence_members") or [payload.get("evidence") or {}]), payload["created_at"]))
                saved.append(payload)
        return saved

    def list_clusters(self, *, status: str | None = None, limit: int = 500) -> list[dict[str, Any]]:
        with self.registry.connect() as conn:
            rows = conn.execute("SELECT * FROM discovery_candidate_clusters " + ("WHERE status=? " if status else "") + "ORDER BY created_at DESC LIMIT ?", ([status] if status else []) + [int(limit)]).fetchall()
        return [dict(row) | {"evidence": json.loads(row["evidence_json"] or "[]")} for row in rows]

    def save_capture_plan(self, payload: dict[str, Any]) -> dict[str, Any]:
        plan = dict(payload); plan.setdefault("plan_id", "PLAN_" + uuid.uuid4().hex); plan.setdefault("created_at", now_iso()); plan.setdefault("status", "CERTIFIED")
        with self.registry.connect() as conn:
            conn.execute("INSERT INTO capture_plans(plan_id,pdf_id,table_family,status,anchor_occurrence_id,payload_json,created_at,updated_at,archived) VALUES(?,?,?,?,?,?,?,?,0)",
                         (plan["plan_id"], plan.get("pdf_id"), plan.get("table_family"), plan["status"], plan.get("anchor_occurrence_id"), _dump(plan), plan["created_at"], now_iso()))
            for i, item in enumerate(plan.get("items") or []):
                conn.execute("INSERT INTO capture_plan_items(item_id,plan_id,member_table,member_table_role,capture_mode,capture_order,note_reference,source_pdf_page_index,candidate_note_pdf_page_index,confirmed_note_pdf_page_index,status,payload_json,created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
                             ("PLANITEM_" + uuid.uuid4().hex, plan["plan_id"], item.get("member_table"), item.get("member_table_role"), item.get("capture_mode"), item.get("capture_order", i), item.get("note_reference"), item.get("source_pdf_page_index"), item.get("candidate_note_pdf_page_index"), item.get("confirmed_note_pdf_page_index"), item.get("status", "READY"), _dump(item), now_iso()))
        return plan

    def get_capture_plan(self, plan_id: str) -> dict[str, Any] | None:
        """Return one persisted Capture Plan with DB-backed item payloads."""
        with self.registry.connect() as conn:
            row = conn.execute(
                """SELECT * FROM capture_plans
                   WHERE plan_id=? AND archived=0""",
                (plan_id,),
            ).fetchone()
            if not row:
                return None
            items = conn.execute(
                """SELECT payload_json FROM capture_plan_items
                   WHERE plan_id=? ORDER BY capture_order,item_id""",
                (plan_id,),
            ).fetchall()
        plan = json.loads(row["payload_json"] or "{}")
        plan.update({
            "plan_id":str(row["plan_id"]),
            "pdf_id":row["pdf_id"],
            "table_family":row["table_family"],
            "status":row["status"],
            "anchor_occurrence_id":row["anchor_occurrence_id"],
            "items":[json.loads(item["payload_json"] or "{}") for item in items],
        })
        return plan

    def ensure_capture_plan(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Idempotently persist a plan and additive execution context."""
        plan = dict(payload)
        plan_id = str(plan.get("plan_id") or "")
        existing = self.get_capture_plan(plan_id) if plan_id else None
        if not existing:
            return self.save_capture_plan(plan)
        merged = dict(existing)
        changed = False
        for key in (
            "source_pdf_path","source_pdf_id","research_definition_id",
            "definition_version","company","report_year",
        ):
            if not merged.get(key) and plan.get(key):
                merged[key] = plan[key]
                changed = True
        if changed:
            with self.registry.connect() as conn:
                conn.execute(
                    """UPDATE capture_plans SET payload_json=?,updated_at=?
                       WHERE plan_id=?""",
                    (_dump(merged),now_iso(),plan_id),
                )
        return merged

    def adjudicate_anchor(self, occurrence_id: str, *, label: str, actor: str = "local_user",
                          reason: str = "", chosen_scope: str = "", override: dict[str, Any] | None = None) -> dict[str, Any]:
        """Keep anchor arbitration separate from machine occurrence evidence."""
        action_id = "ANCHOR_ADJ_" + uuid.uuid4().hex
        override = dict(override or {})
        with self.registry.connect() as conn:
            row = conn.execute("SELECT * FROM statement_occurrences WHERE occurrence_id=?", (occurrence_id,)).fetchone()
            if not row:
                raise KeyError(f"unknown occurrence {occurrence_id}")
            conn.execute("INSERT INTO anchor_adjudications(action_id,occurrence_id,label,actor,reason,chosen_scope,old_json,new_json,created_at) VALUES(?,?,?,?,?,?,?,?,?)",
                         (action_id, occurrence_id, label, actor, reason, chosen_scope, _dump(dict(row)), _dump(override), now_iso()))
            conn.execute("UPDATE statement_occurrences SET status=? WHERE occurrence_id=?", ("ANCHOR_CERTIFIED" if label == "ACCEPTED" else label, occurrence_id))
            if label == "ACCEPTED":
                audit_id="ANCHOR_AUDIT_"+uuid.uuid4().hex
                conn.execute(
                    """INSERT INTO anchor_certification_audit(
                       audit_id,occurrence_id,selection_method,recommended_candidate_id,
                       selected_candidate_id,candidate_score,score_evidence_snapshot_json,
                       alternative_candidates_json,override_reason,actor,created_at
                       ) VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
                    (audit_id,occurrence_id,
                     override.get("selection_method","HUMAN_OVERRIDE"),
                     override.get("recommended_candidate_id"),
                     override.get("selected_candidate_id",occurrence_id),
                     override.get("candidate_score"),
                     _dump(override.get("score_evidence_snapshot") or {}),
                     _dump(override.get("alternative_candidates") or []),
                     override.get("override_reason"),actor,now_iso()),
                )
                conn.execute(
                    """INSERT INTO ml_labels(
                       label_id,schema_id,entity_type,entity_id,label_value,actor,evidence_json,created_at
                       ) VALUES(?,?,?,?,?,?,?,?)""",
                    ("MLLBL_"+uuid.uuid4().hex,"ANCHOR_CANDIDATE_V1",
                     "STATEMENT_OCCURRENCE",occurrence_id,"SELECTED",actor,
                     _dump(override),now_iso()),
                )
                for alternative in override.get("alternative_candidates") or []:
                    alternative_id=str(alternative.get("occurrence_id") or "")
                    if alternative_id:
                        conn.execute(
                            """INSERT INTO ml_labels(
                               label_id,schema_id,entity_type,entity_id,label_value,actor,evidence_json,created_at
                               ) VALUES(?,?,?,?,?,?,?,?)""",
                            ("MLLBL_"+uuid.uuid4().hex,"ANCHOR_CANDIDATE_V1",
                             "STATEMENT_OCCURRENCE",alternative_id,"ALTERNATIVE",actor,
                             _dump({"selected_candidate_id":occurrence_id,**alternative}),
                             now_iso()),
                        )
                queue_rows=conn.execute(
                    "SELECT anchor_review_item_id,candidate_ids_json FROM anchor_review_queue WHERE status IN ('PENDING','RECOMMENDED')"
                ).fetchall()
                for queue_row in queue_rows:
                    if occurrence_id in json.loads(queue_row["candidate_ids_json"] or "[]"):
                        conn.execute(
                            "UPDATE anchor_review_queue SET status='RESOLVED',updated_at=? WHERE anchor_review_item_id=?",
                            (now_iso(),queue_row["anchor_review_item_id"]),
                        )
        return {"action_id": action_id, "occurrence_id": occurrence_id, "label": label}

    def bulk_adjudicate(self, discovery_ids: Iterable[str], **kwargs: Any) -> list[dict[str, Any]]:
        """Batch action records one immutable adjudication and training example per ID."""
        return [self.adjudicate(discovery_id, **kwargs) for discovery_id in discovery_ids]

    def bulk_adjudicate_anchors(self, occurrence_ids: Iterable[str], **kwargs: Any) -> list[dict[str, Any]]:
        """One audit decision per document-specific statement occurrence."""
        return [self.adjudicate_anchor(occurrence_id, **kwargs) for occurrence_id in occurrence_ids]

    def list_machine(self, *, status: str | None = None, company: str | None = None,
                     display_name: str | None = None, limit: int = 200, offset: int = 0) -> list[dict[str, Any]]:
        clauses, values = ["1=1"], []
        for column, value in (("status", status), ("normalized_company", company), ("display_name", display_name)):
            if value:
                clauses.append(f"{column}=?"); values.append(value)
        values.extend([max(1, int(limit)), max(0, int(offset))])
        with self.registry.connect() as conn:
            rows = conn.execute("SELECT * FROM machine_discoveries WHERE " + " AND ".join(clauses) +
                                " ORDER BY created_at DESC LIMIT ? OFFSET ?", values).fetchall()
        return [dict(row) | {"evidence": json.loads(row["evidence_json"] or "{}") } for row in rows]

    def list_review_queue(self, *, limit: int = 500) -> list[dict[str, Any]]:
        """Return an operational review projection without mutating evidence.

        ``machine_discoveries`` deliberately stays append-only, so filtering it
        by its original NEEDS_REVIEW status made rejected records look active
        forever.  This view joins only the latest human decision and lets the
        UI separate pending work from the historical audit archive.
        """
        with self.registry.connect() as conn:
            rows = conn.execute("""
                SELECT m.*, COALESCE(a.label, 'NEEDS_REVIEW') AS review_status,
                       a.created_at AS reviewed_at
                FROM machine_discoveries m
                LEFT JOIN discovery_adjudications a ON a.action_id = (
                    SELECT action_id FROM discovery_adjudications latest
                    WHERE latest.discovery_id=m.discovery_id
                    ORDER BY latest.created_at DESC, latest.action_id DESC LIMIT 1
                )
                ORDER BY COALESCE(a.created_at, m.created_at) DESC
                LIMIT ?
            """, (int(limit),)).fetchall()
        return [dict(row) | {"evidence": json.loads(row["evidence_json"] or "{}")} for row in rows]

    def adjudicate(self, discovery_id: str, *, label: str, actor: str = "local_user", reason: str = "",
                   scope: str = "COMPANY_STATEMENT", override: dict[str, Any] | None = None) -> dict[str, Any]:
        if label not in VALID_LABELS or scope not in VALID_SCOPES:
            raise ValueError("invalid discovery adjudication")
        action_id = "ADJ_" + uuid.uuid4().hex
        override = dict(override or {})
        with self.registry.connect() as conn:
            machine = conn.execute("SELECT * FROM machine_discoveries WHERE discovery_id=?", (discovery_id,)).fetchone()
            if not machine:
                raise KeyError(f"unknown discovery {discovery_id}")
            conn.execute("""INSERT INTO discovery_adjudications(action_id,discovery_id,label,actor,reason,scope,old_json,new_json,created_at)
                         VALUES(?,?,?,?,?,?,?,?,?)""", (action_id, discovery_id, label, actor, reason, scope,
                         _dump(dict(machine)), _dump(override), now_iso()))
            # Machine discovery is immutable. Review state lives in the
            # append-only adjudication/certified layers rather than rewriting
            # the source candidate.
            status = "CERTIFIED" if label in {"ACCEPTED", "OVERRIDDEN"} else label
            if label in {"ACCEPTED", "OVERRIDDEN"}:
                chosen = dict(machine)
                chosen.update({k: v for k, v in override.items() if v not in (None, "")})
                cert_id = "CERT_" + uuid.uuid4().hex
                conn.execute("""INSERT INTO certified_discoveries(
                  certified_id,discovery_id,company,normalized_company,report_year,filing_type,statement_type,
                  display_name,table_family,member_table,source_table_title,note_reference_pattern,section_context,
                  applicability_scope,status,confidence,success_count,rejection_count,archived,created_at,updated_at)
                  VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""", (
                  cert_id, discovery_id, chosen.get("company"), chosen.get("normalized_company") or chosen.get("company"),
                  str(chosen.get("report_year") or ""), chosen.get("filing_type", "ANNUAL_REPORT"), chosen.get("statement_type"),
                  chosen.get("display_name"), chosen.get("table_family") or chosen.get("display_name"), chosen.get("member_table"),
                  chosen.get("source_table_title") or chosen.get("member_table"), str(chosen.get("note_reference") or ""),
                  chosen.get("section_context"), scope, "ACTIVE", float(chosen.get("confidence") or 0), 1, 0, 0, now_iso(), now_iso()))
        self.training_examples(discovery_id)
        return {"action_id": action_id, "discovery_id": discovery_id, "label": label, "status": status}

    def add_missing(self, context: dict[str, Any], *, member_table: str, note_reference: str = "",
                    note_page: int | None = None, actor: str = "local_user", reason: str = "") -> dict[str, Any]:
        machine = self.save_machine(dict(context) | {"member_table": member_table, "note_reference": note_reference,
                                    "note_page": note_page, "locator_method": "HUMAN_ADD_MISSING",
                                    "confidence": 1.0, "status": "NEEDS_REVIEW", "evidence": {"human_seed": True}})
        return self.adjudicate(machine["discovery_id"], label="OVERRIDDEN", actor=actor, reason=reason,
                               override={"member_table": member_table, "note_reference": note_reference, "note_page": note_page})

    def fast_path(self, query: dict[str, Any]) -> list[dict[str, Any]]:
        """Return only structural candidates; caller must revalidate live evidence."""
        fields = ("normalized_company", "filing_type", "statement_type", "display_name")
        clauses, values = ["archived=0", "status='ACTIVE'"], []
        for field in fields:
            value = query.get(field)
            if value:
                clauses.append(f"{field}=?"); values.append(value)
        with self.registry.connect() as conn:
            rows = conn.execute("SELECT * FROM certified_discoveries WHERE " + " AND ".join(clauses) +
                                " ORDER BY success_count DESC, updated_at DESC LIMIT 50", values).fetchall()
        return [dict(x) for x in rows]

    def knowledge_summary(self, limit: int = 200) -> list[dict[str, Any]]:
        with self.registry.connect() as conn:
            rows = conn.execute("""SELECT normalized_company,filing_type,statement_type,display_name,table_family,member_table,
              COUNT(*) historical_instances,SUM(success_count) accepted_count,SUM(rejection_count) rejected_count,
              MAX(updated_at) last_used_at FROM certified_discoveries WHERE archived=0
              GROUP BY normalized_company,filing_type,statement_type,display_name,table_family,member_table
              ORDER BY last_used_at DESC LIMIT ?""", (int(limit),)).fetchall()
        return [dict(x) for x in rows]

    def archive_certified(self, certified_id: str, *, actor: str = "local_user", reason: str = "") -> None:
        with self.registry.connect() as conn:
            conn.execute("UPDATE certified_discoveries SET archived=1,updated_at=? WHERE certified_id=?", (now_iso(), certified_id))
            conn.execute("INSERT INTO registry_events(event_type,asset_type,asset_id,payload_json,created_at) VALUES(?,?,?,?,?)",
                         ("CERTIFIED_DISCOVERY_ARCHIVED", "CERTIFIED_DISCOVERY", certified_id, _dump({"actor": actor, "reason": reason}), now_iso()))

    def training_examples(self, discovery_id: str) -> None:
        with self.registry.connect() as conn:
            row = conn.execute("""SELECT m.*,a.label,a.reason,a.new_json,a.created_at adjudicated_at FROM machine_discoveries m
                                  JOIN discovery_adjudications a ON a.discovery_id=m.discovery_id
                                  WHERE m.discovery_id=? ORDER BY a.created_at DESC LIMIT 1""", (discovery_id,)).fetchone()
            if not row: return
            example_id = "TRN_" + uuid.uuid4().hex
            context = {k: row[k] for k in ("company", "normalized_company", "report_year", "filing_type", "statement_type", "display_name", "table_family", "member_table")}
            payload = {"machine_evidence": json.loads(row["evidence_json"] or "{}"), "override": json.loads(row["new_json"] or "{}"), "reason": row["reason"]}
            for dataset in ("discovery_training_examples", "note_locator_training_examples"):
                conn.execute(f"INSERT INTO {dataset}(example_id,discovery_id,context_json,machine_confidence,label,payload_json,created_at) VALUES(?,?,?,?,?,?,?)",
                             (example_id + dataset[:2], discovery_id, _dump(context), row["confidence"], row["label"], _dump(payload), row["adjudicated_at"]))
