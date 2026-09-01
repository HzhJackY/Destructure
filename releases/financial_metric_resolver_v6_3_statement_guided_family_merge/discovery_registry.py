"""v6.4 durable discovery evidence, adjudication and knowledge services.

Machine candidates are append-only.  Human actions are separate append-only
events; certified rows are a materialized, reproducible view of those events.
"""
from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from typing import Any, Iterable


VALID_LABELS = {"ACCEPTED", "REJECTED", "OVERRIDDEN", "UNRESOLVED"}
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
              reconciliation_status,status,evidence_json,created_at)
              VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""", (
              payload["discovery_id"], payload.get("pdf_id"), payload.get("company"),
              payload.get("normalized_company") or payload.get("company"), str(payload.get("report_year") or ""),
              payload.get("filing_type", "ANNUAL_REPORT"), payload.get("statement_type"), payload.get("display_name"),
              payload.get("table_family") or payload.get("display_name"), payload.get("statement_item"),
              str(payload.get("note_reference") or ""), payload.get("statement_value"), payload.get("member_table"),
              payload.get("source_table_title") or payload.get("member_table"), payload.get("section_context"),
              payload.get("statement_page"), payload.get("note_page"), payload.get("locator_method"),
              float(payload.get("confidence") or 0), payload.get("reconciliation_status"), payload["status"],
              _dump(payload["evidence"]), payload["created_at"]))
        return payload

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
            status = "CERTIFIED" if label in {"ACCEPTED", "OVERRIDDEN"} else label
            conn.execute("UPDATE machine_discoveries SET status=? WHERE discovery_id=?", (status, discovery_id))
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
