"""SQLite persistence for v6.8 capture workflow and logical asset governance."""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import uuid
from typing import Any, Iterable


def _now() -> str:
    return dt.datetime.now().astimezone().isoformat(timespec="seconds")


def _json(value: Any) -> str:
    return json.dumps(value if value is not None else {}, ensure_ascii=False, sort_keys=True)


class AssetGovernanceRepository:
    def __init__(self, registry):
        self.registry = registry

    @staticmethod
    def _mark_merges_stale(conn, capture_ids: Iterable[str], reason: str) -> None:
        ids = [str(x) for x in capture_ids if x]
        if not ids:
            return
        marks = ",".join("?" for _ in ids)
        merge_ids = [str(row["merge_id"]) for row in conn.execute(
            f"SELECT DISTINCT merge_id FROM merge_sources WHERE capture_id IN ({marks})", ids
        ).fetchall()]
        if merge_ids:
            merge_marks = ",".join("?" for _ in merge_ids)
            conn.execute(
                f"UPDATE merge_projects SET dependency_status=?,updated_at=? WHERE merge_id IN ({merge_marks})",
                [reason, _now(), *merge_ids],
            )

    def save_request(self, request, status: str = "QUEUED") -> None:
        row = request.to_dict()
        with self.registry.connect() as conn:
            conn.execute(
                """INSERT INTO capture_requests(
                    request_id,request_type,capture_mode,research_project_id,research_task_id,
                    research_batch_id,research_definition_id,definition_version,table_family_id,
                    member_table_id,source_pdf_id,source_pdf_sha256,discovery_strategy_id,priority,
                    retry_of_request_id,producer_version,status,payload_json,requested_by,requested_at,updated_at
                ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                ON CONFLICT(request_id) DO UPDATE SET status=excluded.status,
                    payload_json=excluded.payload_json,updated_at=excluded.updated_at""",
                (
                    row["request_id"], row["request_type"], row["capture_mode"],
                    row.get("research_project_id"), row.get("research_task_id"),
                    row.get("research_batch_id"), row.get("research_definition_id"),
                    row.get("definition_version"), row.get("table_family_id"),
                    row.get("member_table_id"), row.get("source_pdf_id"),
                    row.get("source_pdf_sha256"), row.get("discovery_strategy_id"),
                    int(row.get("priority") or 100), row.get("retry_of_request_id"),
                    row.get("producer_version"), status, _json(row), row.get("requested_by"),
                    row.get("requested_at") or _now(), _now(),
                ),
            )

    def update_request(self, request_id: str, status: str, **payload: Any) -> None:
        with self.registry.connect() as conn:
            existing = conn.execute(
                "SELECT payload_json FROM capture_requests WHERE request_id=?", (request_id,)
            ).fetchone()
            body = json.loads(existing["payload_json"] or "{}") if existing else {}
            body.update(payload)
            conn.execute(
                "UPDATE capture_requests SET status=?,payload_json=?,updated_at=? WHERE request_id=?",
                (status, _json(body), _now(), request_id),
            )

    def save_target(self, request_id: str, target) -> None:
        row = target.to_dict()
        with self.registry.connect() as conn:
            conn.execute(
                """INSERT OR REPLACE INTO capture_request_targets(
                    request_id,target_id,strategy_id,certification_status,payload_json,created_at
                ) VALUES(?,?,?,?,?,?)""",
                (request_id, row["target_id"], row["strategy_id"],
                 row["certification_status"], _json(row), _now()),
            )

    def save_strategy_execution(
        self, *, request_id: str, strategy_id: str, status: str,
        candidates: list[dict[str, Any]], selected_target_id: str = "",
        abstain_reason: str = "",
    ) -> str:
        execution_id = "STRAT_" + uuid.uuid4().hex
        with self.registry.connect() as conn:
            conn.execute(
                """INSERT INTO strategy_executions(
                    execution_id,request_id,strategy_id,status,candidate_count,
                    selected_target_id,abstain_reason,evidence_json,created_at,finished_at
                ) VALUES(?,?,?,?,?,?,?,?,?,?)""",
                (execution_id, request_id, strategy_id, status, len(candidates),
                 selected_target_id or None, abstain_reason or None,
                 _json({"candidates": candidates}), _now(), _now()),
            )
        return execution_id

    @staticmethod
    def identity_payload(metadata: dict[str, Any]) -> dict[str, str]:
        return {
            "company_id": str(metadata.get("company_id") or metadata.get("company") or "").strip(),
            "filing_type": str(metadata.get("filing_type") or "ANNUAL_REPORT").strip(),
            "report_year": str(metadata.get("report_year") or metadata.get("document_year") or "").strip(),
            "statement_scope": str(metadata.get("statement_scope") or metadata.get("scope") or "UNKNOWN").strip(),
            "research_project_id": str(metadata.get("research_project_id") or "").strip(),
            "research_task_id": str(metadata.get("research_task_id") or "").strip(),
            "research_batch_id": str(metadata.get("research_batch_id") or "").strip(),
            "research_definition_id": str(metadata.get("research_definition_id") or "").strip(),
            "definition_version": str(metadata.get("definition_version") or "").strip(),
            "table_family_id": str(metadata.get("table_family_id") or metadata.get("table_family") or "").strip(),
            "member_table_id": str(metadata.get("member_table_id") or metadata.get("member_table") or metadata.get("table_query") or "").strip(),
            "logical_source_role": str(metadata.get("logical_source_role") or metadata.get("member_table_role") or "COMPONENT").strip(),
        }

    def get_or_create_logical_asset(self, metadata: dict[str, Any]) -> dict[str, Any]:
        identity = self.identity_payload(metadata)
        identity_key = hashlib.sha256(_json(identity).encode("utf-8")).hexdigest()
        with self.registry.connect() as conn:
            row = conn.execute(
                "SELECT * FROM logical_assets WHERE identity_key=?", (identity_key,)
            ).fetchone()
            if not row:
                logical_asset_id = "LASSET_" + uuid.uuid4().hex
                conn.execute(
                    """INSERT INTO logical_assets(
                        logical_asset_id,identity_key,company_id,filing_type,report_year,
                        statement_scope,research_project_id,research_task_id,research_batch_id,research_definition_id,
                        definition_version,table_family_id,member_table_id,logical_source_role,
                        direct_asset_status,archived_by_parent,identity_confidence,
                        derivation_evidence_json,current_capture_id,created_at,updated_at
                    ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,'ACTIVE',0,?,?,NULL,?,?)""",
                    (
                        logical_asset_id, identity_key, identity["company_id"], identity["filing_type"],
                        identity["report_year"], identity["statement_scope"],
                        identity["research_project_id"], identity["research_task_id"],
                        identity["research_batch_id"], identity["research_definition_id"], identity["definition_version"],
                        identity["table_family_id"], identity["member_table_id"],
                        identity["logical_source_role"], float(metadata.get("identity_confidence") or 1.0),
                        _json(metadata.get("derivation_evidence") or identity), _now(), _now(),
                    ),
                )
                row = conn.execute(
                    "SELECT * FROM logical_assets WHERE logical_asset_id=?", (logical_asset_id,)
                ).fetchone()
        return dict(row)

    def register_capture_version(
        self, *, logical_asset_id: str, capture_id: str, producer_version: str,
        processing_status: str, registration_status: str, quality_status: str,
        review_status: str, certified: bool,
    ) -> dict[str, Any]:
        with self.registry.connect() as conn:
            existing = conn.execute(
                "SELECT * FROM capture_versions WHERE capture_id=?", (capture_id,)
            ).fetchone()
            if existing:
                return dict(existing)
            number = int(conn.execute(
                "SELECT COALESCE(MAX(capture_version),0)+1 n FROM capture_versions WHERE logical_asset_id=?",
                (logical_asset_id,),
            ).fetchone()["n"])
            current = conn.execute(
                "SELECT capture_id FROM capture_versions WHERE logical_asset_id=? AND is_current=1",
                (logical_asset_id,),
            ).fetchone()
            supersedes = str(current["capture_id"]) if current else None
            # "Current" means the latest working Capture Version, not
            # "already certified".  Conflating both concepts left every
            # REVIEW_REQUIRED asset without a current version and made final
            # human certification impossible.
            make_current = bool(registration_status == "REGISTERED")
            if make_current:
                conn.execute(
                    """UPDATE capture_versions SET is_current=0,asset_status='SUPERSEDED',
                       superseded_by_capture_id=?,updated_at=?
                       WHERE logical_asset_id=? AND is_current=1""",
                    (capture_id, _now(), logical_asset_id),
                )
                if supersedes:
                    self._mark_merges_stale(
                        conn, [supersedes], "STALE_NEW_CURRENT_VERSION_AVAILABLE"
                    )
            conn.execute(
                """INSERT INTO capture_versions(
                    logical_asset_id,capture_id,capture_version,is_current,processing_status,
                    registration_status,quality_status,review_status,asset_status,
                    supersedes_capture_id,superseded_by_capture_id,producer_version,created_at,updated_at
                ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    logical_asset_id, capture_id, number, int(make_current), processing_status,
                    registration_status, quality_status, review_status,
                    "CERTIFIED_ACTIVE" if certified else "ACTIVE", supersedes, None,
                    producer_version, _now(), _now(),
                ),
            )
            if make_current:
                conn.execute(
                    "UPDATE logical_assets SET current_capture_id=?,updated_at=? WHERE logical_asset_id=?",
                    (capture_id, _now(), logical_asset_id),
                )
            row = conn.execute(
                "SELECT * FROM capture_versions WHERE capture_id=?", (capture_id,)
            ).fetchone()
        return dict(row)

    def transition(
        self, *, logical_asset_id: str | None, capture_id: str | None,
        previous_status: str | None, new_status: str, actor: str,
        reason: str, evidence: dict[str, Any] | None = None,
        source_ui_action: str = "", producer_version: str = "",
    ) -> str:
        transition_id = "TRANS_" + uuid.uuid4().hex
        with self.registry.connect() as conn:
            conn.execute(
                """INSERT INTO asset_status_transitions(
                    transition_id,logical_asset_id,capture_id,previous_status,new_status,
                    actor,reason,evidence_json,source_ui_action,producer_version,created_at
                ) VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
                (transition_id, logical_asset_id, capture_id, previous_status, new_status,
                 actor, reason, _json(evidence), source_ui_action, producer_version, _now()),
            )
        return transition_id

    def enqueue_review(
        self, *, logical_asset_id: str, capture_id: str, primary_reason: str,
        secondary_reasons: Iterable[str] = (), severity: str = "MEDIUM",
        recommended_action: str = "REVIEW", evidence: dict[str, Any] | None = None,
    ) -> str:
        review_id = "REVIEW_" + uuid.uuid4().hex
        with self.registry.connect() as conn:
            conn.execute(
                """INSERT INTO review_queue(
                    review_item_id,logical_asset_id,capture_id,primary_review_reason,
                    secondary_review_reasons_json,severity,recommended_action,
                    evidence_summary_json,status,created_at,updated_at
                ) VALUES(?,?,?,?,?,?,?,?, 'PENDING',?,?)
                ON CONFLICT(capture_id) DO UPDATE SET
                    primary_review_reason=excluded.primary_review_reason,
                    secondary_review_reasons_json=excluded.secondary_review_reasons_json,
                    severity=excluded.severity,recommended_action=excluded.recommended_action,
                    evidence_summary_json=excluded.evidence_summary_json,status='PENDING',
                    updated_at=excluded.updated_at""",
                (review_id, logical_asset_id, capture_id, primary_reason,
                 _json(list(secondary_reasons)), severity, recommended_action,
                 _json(evidence), _now(), _now()),
            )
        return review_id

    def resolve_review(
        self, capture_id: str, status: str, *, actor: str = "USER",
        reason: str = "", override: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        with self.registry.connect() as conn:
            version = conn.execute(
                "SELECT * FROM capture_versions WHERE capture_id=?", (capture_id,)
            ).fetchone()
            if not version:
                raise KeyError(capture_id)
            logical_asset_id = str(version["logical_asset_id"])
            action = str(status).upper()
            before = dict(version)
            capture_evidence = conn.execute(
                """SELECT run_path,pdf_name,producer_version,updated_at
                   FROM captures WHERE capture_id=?""",
                (capture_id,),
            ).fetchone()
            before["machine_evidence_reference"] = (
                dict(capture_evidence) if capture_evidence else {"capture_id": capture_id}
            )
            if action in {"CONFIRMED", "CONFIRMED_HUMAN", "CONFIRMED_AUTO", "CONFIRMED_OVERRIDE"}:
                review_status = {
                    "CONFIRMED": "CONFIRMED_HUMAN",
                    "CONFIRMED_HUMAN": "CONFIRMED_HUMAN",
                    "CONFIRMED_AUTO": "CONFIRMED_AUTO",
                    "CONFIRMED_OVERRIDE": "CONFIRMED_OVERRIDE",
                }[action]
                old = conn.execute(
                    "SELECT capture_id FROM capture_versions WHERE logical_asset_id=? AND is_current=1 AND capture_id<>?",
                    (logical_asset_id, capture_id),
                ).fetchone()
                if old:
                    conn.execute(
                        """UPDATE capture_versions SET is_current=0,asset_status='SUPERSEDED',
                           superseded_by_capture_id=?,updated_at=? WHERE capture_id=?""",
                        (capture_id, _now(), old["capture_id"]),
                    )
                    self._mark_merges_stale(
                        conn, [old["capture_id"]], "STALE_NEW_CURRENT_VERSION_AVAILABLE"
                    )
                conn.execute(
                    """UPDATE capture_versions SET is_current=1,quality_status='READY',
                       review_status=?,asset_status='CERTIFIED_ACTIVE',
                       supersedes_capture_id=COALESCE(supersedes_capture_id,?),updated_at=?
                       WHERE capture_id=?""",
                    (review_status, old["capture_id"] if old else None, _now(), capture_id),
                )
                conn.execute(
                    "UPDATE logical_assets SET current_capture_id=?,updated_at=? WHERE logical_asset_id=?",
                    (capture_id, _now(), logical_asset_id),
                )
                queue_status = review_status
            elif action == "REJECTED":
                conn.execute(
                    """UPDATE capture_versions SET is_current=0,review_status='REJECTED',
                       asset_status='INVALIDATED',updated_at=? WHERE capture_id=?""",
                    (_now(), capture_id),
                )
                conn.execute(
                    """UPDATE logical_assets SET current_capture_id=
                       CASE WHEN current_capture_id=? THEN NULL ELSE current_capture_id END,
                       updated_at=? WHERE logical_asset_id=?""",
                    (capture_id, _now(), logical_asset_id),
                )
                queue_status = "REJECTED"
                self._mark_merges_stale(conn, [capture_id], "STALE_SOURCE_INVALIDATED")
            elif action in {"UNRESOLVED", "REVIEW_REQUIRED"}:
                conn.execute(
                    """UPDATE capture_versions SET review_status='UNRESOLVED',
                       quality_status='REVIEW_REQUIRED',updated_at=? WHERE capture_id=?""",
                    (_now(), capture_id),
                )
                queue_status = "UNRESOLVED"
            else:
                raise ValueError(f"UNSUPPORTED_REVIEW_ACTION:{status}")
            conn.execute(
                "UPDATE review_queue SET status=?,updated_at=? WHERE capture_id=?",
                (queue_status, _now(), capture_id),
            )
            if action in {"CONFIRMED","CONFIRMED_HUMAN","CONFIRMED_AUTO","CONFIRMED_OVERRIDE"}:
                conn.execute(
                    """UPDATE review_tasks SET status='CONFIRMED',reviewer=?,decision=?,
                       updated_at=? WHERE capture_version_id=? AND task_type='FINAL_CERTIFICATION'""",
                    (actor,action,_now(),capture_id),
                )
            conn.execute(
                """INSERT INTO asset_status_transitions(
                    transition_id,logical_asset_id,capture_id,previous_status,new_status,
                    actor,reason,evidence_json,source_ui_action,producer_version,created_at
                   ) VALUES(?,?,?,?,?,?,'REVIEW_ADJUDICATION',?,'CAPTURE_INSPECTION_PANEL','v6.9',?)""",
                ("TRANS_" + uuid.uuid4().hex, logical_asset_id, capture_id,
                 str(version["asset_status"]), "CERTIFIED_ACTIVE" if action.startswith("CONFIRMED") else action,
                 actor, _json({"reason": reason, "override": override or {}}), _now()),
            )
            after_row = conn.execute(
                "SELECT * FROM capture_versions WHERE capture_id=?", (capture_id,)
            ).fetchone()
            after = dict(after_row)
            merge_eligible = bool(
                after["is_current"]
                and after["registration_status"] == "REGISTERED"
                and after["quality_status"] == "READY"
                and after["review_status"] in {"CONFIRMED_AUTO", "CONFIRMED_HUMAN", "CONFIRMED_OVERRIDE"}
                and after["asset_status"] == "CERTIFIED_ACTIVE"
            )
            impact = {
                "review_queue_removed_from_default": queue_status != "PENDING",
                "merge_eligible": merge_eligible,
                "superseded_capture_id": after.get("supersedes_capture_id"),
            }
            conn.execute(
                """INSERT INTO capture_review_records(
                    review_record_id,logical_asset_id,capture_id,action,actor,reason,
                    override_json,before_json,after_json,impact_json,created_at
                ) VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
                ("CRVW_" + uuid.uuid4().hex, logical_asset_id, capture_id, action,
                 actor, reason, _json(override), _json(before), _json(after),
                 _json(impact), _now()),
            )
            self._recalculate_bundle_status_in_tx(conn, capture_id)
        return {"before": before, "after": after, "impact": impact}

    def _recalculate_bundle_status_in_tx(self, conn, capture_id: str) -> str | None:
        bundle = conn.execute(
            "SELECT bundle_id FROM capture_bundle_children WHERE capture_id=?", (capture_id,)
        ).fetchone()
        if not bundle:
            return None
        rows = conn.execute(
            """SELECT cbc.capture_id,tb.quality_status AS block_quality,
                      cv.quality_status,cv.review_status,cv.asset_status
               FROM capture_bundle_children cbc
               JOIN table_blocks tb ON tb.block_id=cbc.block_id
               LEFT JOIN capture_versions cv ON cv.capture_id=cbc.capture_id
               WHERE cbc.bundle_id=? AND cbc.status<>'SUPERSEDED'""",
            (bundle["bundle_id"],),
        ).fetchall()
        ready = [
            bool(row["quality_status"] == "READY"
                 and row["review_status"] in {"CONFIRMED_AUTO","CONFIRMED_HUMAN","CONFIRMED_OVERRIDE"}
                 and row["asset_status"] == "CERTIFIED_ACTIVE")
            for row in rows
        ]
        status = "READY" if rows and all(ready) else (
            "PARTIALLY_REVIEW_REQUIRED" if any(ready) else "REVIEW_REQUIRED"
        )
        conn.execute(
            "UPDATE capture_bundles SET status=?,updated_at=? WHERE bundle_id=?",
            (status, _now(), bundle["bundle_id"]),
        )
        return status

    def capture_detail(self, capture_id: str) -> dict[str, Any] | None:
        with self.registry.connect() as conn:
            row = conn.execute(
                """SELECT cv.*,la.company_id,la.filing_type,la.report_year,la.statement_scope,
                          la.research_project_id,la.research_task_id,la.research_batch_id,
                          la.research_definition_id,la.definition_version,la.table_family_id,
                          la.member_table_id,la.logical_source_role,la.direct_asset_status,
                          c.run_path,c.table_query,c.pdf_name,c.source_pdf_display,c.pdf_id,
                          p.path AS pdf_path
                   FROM capture_versions cv
                   JOIN logical_assets la ON la.logical_asset_id=cv.logical_asset_id
                   LEFT JOIN captures c ON c.capture_id=cv.capture_id
                   LEFT JOIN pdf_assets p ON p.pdf_id=c.pdf_id
                   WHERE cv.capture_id=?""",
                (capture_id,),
            ).fetchone()
        return dict(row) if row else None

    def bundle_detail(self, capture_id: str) -> dict[str, Any] | None:
        with self.registry.connect() as conn:
            bundle = conn.execute(
                """SELECT cb.* FROM capture_bundles cb
                   JOIN capture_bundle_children cbc ON cbc.bundle_id=cb.bundle_id
                   WHERE cbc.capture_id=?""", (capture_id,)
            ).fetchone()
            if not bundle:
                return None
            children = [
                dict(row) for row in conn.execute(
                    """SELECT cbc.*,tb.block_title,tb.block_role,tb.start_pdf_page,
                              tb.end_pdf_page,tb.bbox_json,tb.header_topology_json,
                              tb.semantic_graph_json,tb.reconciliation_json,
                              tb.quality_status AS block_quality_status,tb.status AS block_status,
                              cv.capture_version,cv.quality_status,cv.review_status,cv.asset_status
                       FROM capture_bundle_children cbc
                       JOIN table_blocks tb ON tb.block_id=cbc.block_id
                       LEFT JOIN capture_versions cv ON cv.capture_id=cbc.capture_id
                       WHERE cbc.bundle_id=? AND cbc.status<>'SUPERSEDED'
                       ORDER BY cbc.child_order""",
                    (bundle["bundle_id"],),
                ).fetchall()
            ]
        return {"bundle": dict(bundle), "children": children}

    def recalculate_bundle_status(self, capture_id: str) -> str | None:
        with self.registry.connect() as conn:
            return self._recalculate_bundle_status_in_tx(conn,capture_id)

    def review_history(self, capture_id: str) -> list[dict[str, Any]]:
        with self.registry.connect() as conn:
            return [dict(row) for row in conn.execute(
                "SELECT * FROM capture_review_records WHERE capture_id=? ORDER BY created_at DESC",
                (capture_id,),
            ).fetchall()]

    def asset_usage(self, capture_id: str) -> dict[str, list[dict[str, Any]]]:
        usage: dict[str, list[dict[str, Any]]] = {}
        with self.registry.connect() as conn:
            tables = {row["name"] for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()}
            if "merge_sources" in tables:
                usage["merge_sources"] = [dict(row) for row in conn.execute(
                    "SELECT * FROM merge_sources WHERE capture_id=?", (capture_id,)
                ).fetchall()]
            if "capture_bundle_children" in tables:
                usage["capture_bundles"] = [dict(row) for row in conn.execute(
                    "SELECT * FROM capture_bundle_children WHERE capture_id=?", (capture_id,)
                ).fetchall()]
            usage["stale_flags"] = [dict(row) for row in conn.execute(
                "SELECT * FROM downstream_stale_flags WHERE capture_id=?", (capture_id,)
            ).fetchall()]
        return usage

    def list_review(self, **filters: Any) -> list[dict[str, Any]]:
        where, params = ["la.direct_asset_status='ACTIVE'", "la.archived_by_parent=0"], []
        if not filters.get("include_completed"):
            where.append(
                "cv.asset_status NOT IN ('CERTIFIED_ACTIVE','ARCHIVED','SUPERSEDED','INVALIDATED','TRASHED')"
            )
        if not filters.get("include_completed") and not filters.get("status"):
            where.append("rq.status='PENDING'")
        for column in ("status", "severity", "primary_review_reason"):
            if filters.get(column):
                where.append(f"rq.{column}=?")
                params.append(str(filters[column]))
        for column in (
            "company_id", "report_year", "statement_scope", "research_project_id",
            "research_task_id", "research_batch_id", "research_definition_id",
            "definition_version", "table_family_id", "member_table_id",
        ):
            if filters.get(column):
                where.append(f"la.{column}=?")
                params.append(str(filters[column]))
        for column in ("quality_status", "review_status", "asset_status", "producer_version", "is_current"):
            if filters.get(column) is not None:
                where.append(f"cv.{column}=?")
                params.append(filters[column])
        if filters.get("source_pdf"):
            where.append("(c.pdf_name LIKE ? OR c.source_pdf_display LIKE ?)")
            token = f"%{filters['source_pdf']}%"
            params.extend((token, token))
        if filters.get("search"):
            token = f"%{filters['search']}%"
            where.append(
                "(la.company_id LIKE ? OR la.table_family_id LIKE ? OR "
                "la.member_table_id LIKE ? OR c.pdf_name LIKE ? OR c.table_query LIKE ?)"
            )
            params.extend([token] * 5)
        if filters.get("recent_days"):
            where.append("rq.updated_at >= datetime('now', ?)")
            params.append(f"-{max(1, int(filters['recent_days']))} days")
        sql = """SELECT rq.*,la.company_id,la.report_year,la.statement_scope,
                 la.research_project_id,la.research_task_id,la.research_batch_id,
                 la.research_definition_id,la.definition_version,
                 la.table_family_id,la.member_table_id,cv.capture_version,cv.is_current,
                 cv.quality_status,cv.review_status,cv.asset_status,cv.producer_version,
                 c.pdf_id,c.pdf_name,c.source_pdf_display,c.run_path,c.table_query,
                 p.path AS pdf_path
                 FROM review_queue rq
                 JOIN logical_assets la ON la.logical_asset_id=rq.logical_asset_id
                 JOIN capture_versions cv ON cv.capture_id=rq.capture_id
                 LEFT JOIN captures c ON c.capture_id=rq.capture_id
                 LEFT JOIN pdf_assets p ON p.pdf_id=c.pdf_id"""
        if where:
            sql += " WHERE " + " AND ".join(where)
        sort_field = str(filters.get("sort_by") or "severity")
        sort_direction = "ASC" if str(filters.get("sort_direction") or "DESC").upper() == "ASC" else "DESC"
        review_sort = {
            "severity": "CASE rq.severity WHEN 'CRITICAL' THEN 0 WHEN 'HIGH' THEN 1 WHEN 'MEDIUM' THEN 2 ELSE 3 END",
            "updated_at": "rq.updated_at",
            "created_at": "rq.created_at",
            "company_id": "la.company_id",
            "report_year": "la.report_year",
        }.get(sort_field, "rq.updated_at")
        sql += f" ORDER BY {review_sort} {sort_direction},rq.updated_at DESC"
        limit = max(1, min(int(filters.get("page_size") or 200), 1000))
        page = max(1, int(filters.get("page") or 1))
        sql += " LIMIT ? OFFSET ?"
        params.extend((limit, (page - 1) * limit))
        with self.registry.connect() as conn:
            return [dict(row) for row in conn.execute(sql, params).fetchall()]

    def save_view(self, *, kind: str, display_name: str, filters: dict[str, Any],
                  sort: dict[str, Any] | None = None, owner: str = "USER",
                  view_id: str | None = None) -> str:
        table = {"REVIEW": "saved_review_views", "ASSET": "saved_asset_views"}[kind]
        view_id = view_id or f"{kind}_VIEW_" + uuid.uuid4().hex
        with self.registry.connect() as conn:
            conn.execute(
                f"""INSERT INTO {table}(view_id,display_name,owner,filters_json,sort_json,created_at,updated_at)
                    VALUES(?,?,?,?,?,?,?)
                    ON CONFLICT(view_id) DO UPDATE SET display_name=excluded.display_name,
                    filters_json=excluded.filters_json,sort_json=excluded.sort_json,updated_at=excluded.updated_at""",
                (view_id, display_name, owner, _json(filters), _json(sort), _now(), _now()),
            )
        return view_id

    def list_views(self, kind: str) -> list[dict[str, Any]]:
        table = {"REVIEW": "saved_review_views", "ASSET": "saved_asset_views"}[kind]
        with self.registry.connect() as conn:
            rows = [dict(row) for row in conn.execute(
                f"SELECT * FROM {table} ORDER BY updated_at DESC"
            ).fetchall()]
        for row in rows:
            row["filters"] = json.loads(row.pop("filters_json") or "{}")
            row["sort"] = json.loads(row.pop("sort_json") or "{}")
        return rows

    def delete_view(self, kind: str, view_id: str) -> None:
        table = {"REVIEW": "saved_review_views", "ASSET": "saved_asset_views"}[kind]
        with self.registry.connect() as conn:
            conn.execute(f"DELETE FROM {table} WHERE view_id=?", (view_id,))

    def search_assets(
        self, *, filters: dict[str, Any] | None = None, include_archived: bool = False,
        pagination: dict[str, Any] | None = None, sort: dict[str, Any] | None = None,
        search: str = "",
    ) -> list[dict[str, Any]]:
        filters = dict(filters or {})
        pagination = dict(pagination or {})
        sort = dict(sort or {})
        where, params = [], []
        if not include_archived:
            where.append("la.direct_asset_status='ACTIVE'")
            where.append("la.archived_by_parent=0")
            where.append(
                "cv.asset_status NOT IN ('ARCHIVED','TRASHED','SUPERSEDED','INVALIDATED')"
            )
        for field in (
            "company_id", "filing_type", "report_year", "statement_scope",
            "research_project_id", "research_task_id", "research_batch_id",
            "research_definition_id", "definition_version", "table_family_id",
            "member_table_id", "logical_source_role", "direct_asset_status",
        ):
            if filters.get(field):
                where.append(f"la.{field}=?")
                params.append(str(filters[field]))
        for field in (
            "quality_status", "review_status", "asset_status", "producer_version",
            "processing_status", "registration_status", "is_current",
        ):
            if filters.get(field) is not None:
                where.append(f"cv.{field}=?")
                params.append(filters[field])
        if filters.get("source_pdf"):
            token = f"%{filters['source_pdf']}%"
            where.append("(c.pdf_name LIKE ? OR c.source_pdf_display LIKE ?)")
            params.extend((token, token))
        query = str(search or filters.get("search") or "").strip()
        if query:
            token = f"%{query}%"
            where.append(
                "(la.company_id LIKE ? OR la.table_family_id LIKE ? OR "
                "la.member_table_id LIKE ? OR la.logical_asset_id LIKE ? OR "
                "c.pdf_name LIKE ? OR c.table_query LIKE ?)"
            )
            params.extend([token] * 6)
        sql = """SELECT la.*,cv.capture_version,cv.capture_id,cv.is_current,
                 cv.processing_status,cv.registration_status,cv.quality_status,
                 cv.review_status,cv.asset_status,c.run_path,c.table_query,
                 c.pdf_id,c.pdf_name,c.source_pdf_display,p.path AS pdf_path
                 FROM logical_assets la
                 JOIN capture_versions cv ON cv.logical_asset_id=la.logical_asset_id
                 LEFT JOIN captures c ON c.capture_id=cv.capture_id
                 LEFT JOIN pdf_assets p ON p.pdf_id=c.pdf_id"""
        if where:
            sql += " WHERE " + " AND ".join(where)
        sort_field = {
            "company_id": "la.company_id",
            "report_year": "la.report_year",
            "table_family_id": "la.table_family_id",
            "member_table_id": "la.member_table_id",
            "updated_at": "cv.updated_at",
            "created_at": "cv.created_at",
            "capture_version": "cv.capture_version",
            "asset_status": "cv.asset_status",
        }.get(str(sort.get("field") or ""), "la.company_id")
        direction = "ASC" if str(sort.get("direction") or "ASC").upper() == "ASC" else "DESC"
        sql += f" ORDER BY {sort_field} {direction},la.report_year DESC,la.table_family_id,la.member_table_id,cv.capture_version DESC"
        limit = max(1, min(int(pagination.get("page_size") or 500), 2000))
        page = max(1, int(pagination.get("page") or 1))
        sql += " LIMIT ? OFFSET ?"
        params.extend((limit, (page - 1) * limit))
        with self.registry.connect() as conn:
            return [dict(row) for row in conn.execute(sql, params).fetchall()]

    def current_merge_eligible(self, filters: dict[str, Any] | None = None) -> list[dict[str, Any]]:
        return [
            row for row in self.search_assets(filters=filters)
            if row["is_current"] and row["registration_status"] == "REGISTERED"
            and row["quality_status"] == "READY"
            and row["review_status"] in {"CONFIRMED_AUTO", "CONFIRMED_HUMAN", "CONFIRMED_OVERRIDE"}
            and row["asset_status"] == "CERTIFIED_ACTIVE"
            and str(row.get("research_definition_id") or "").strip()
            and str(row.get("definition_version") or "").strip()
            and str(row.get("table_family_id") or "").strip()
            and str(row.get("statement_scope") or "UNKNOWN").upper() not in {"", "UNKNOWN", "NONE"}
        ]

    def get_logical_asset(self, logical_asset_id: str) -> dict[str, Any] | None:
        with self.registry.connect() as conn:
            row = conn.execute(
                "SELECT * FROM logical_assets WHERE logical_asset_id=?", (logical_asset_id,)
            ).fetchone()
        return dict(row) if row else None

    def capture_versions(self, logical_asset_id: str) -> list[dict[str, Any]]:
        with self.registry.connect() as conn:
            return [dict(row) for row in conn.execute(
                "SELECT * FROM capture_versions WHERE logical_asset_id=? ORDER BY capture_version DESC",
                (logical_asset_id,),
            ).fetchall()]

    def lineage(self, logical_asset_id: str) -> dict[str, Any]:
        return {
            "logical_asset": self.get_logical_asset(logical_asset_id),
            "versions": self.capture_versions(logical_asset_id),
        }

    def archive_parent(self, *, target_type: str, target_id: str, actor: str,
                       reason: str, restore: bool = False) -> list[str]:
        column = {
            "RESEARCH_PROJECT": "research_project_id",
            "RESEARCH_TASK": "research_task_id",
            "RESEARCH_BATCH": "research_batch_id",
        }[target_type]
        with self.registry.connect() as conn:
            ids = [str(row["logical_asset_id"]) for row in conn.execute(
                f"SELECT logical_asset_id FROM logical_assets WHERE {column}=?", (target_id,)
            ).fetchall()]
            conn.execute(
                f"UPDATE logical_assets SET archived_by_parent=?,updated_at=? WHERE {column}=?",
                (0 if restore else 1, _now(), target_id),
            )
            conn.execute(
                """INSERT INTO archive_operations(operation_id,target_type,target_id,action,actor,reason,payload_json,created_at)
                   VALUES(?,?,?,?,?,?,?,?)""",
                ("ARCH_" + uuid.uuid4().hex, target_type, target_id,
                 "RESTORE" if restore else "ARCHIVE", actor, reason,
                 _json({"affected_logical_assets": ids}), _now()),
            )
        return ids

    def set_capture_lifecycle(
        self, capture_ids: Iterable[str], *, status: str, actor: str,
        reason: str, restore: bool = False,
    ) -> list[str]:
        changed = []
        with self.registry.connect() as conn:
            for capture_id in map(str, capture_ids):
                row = conn.execute(
                    "SELECT * FROM capture_versions WHERE capture_id=?", (capture_id,)
                ).fetchone()
                if not row:
                    continue
                previous = str(row["asset_status"])
                target = status
                if restore:
                    transition = conn.execute(
                        """SELECT evidence_json FROM asset_status_transitions
                           WHERE capture_id=? AND new_status IN ('ARCHIVED','TRASHED','INVALIDATED')
                           ORDER BY created_at DESC LIMIT 1""", (capture_id,)
                    ).fetchone()
                    evidence = json.loads(transition["evidence_json"] or "{}") if transition else {}
                    target = str(evidence.get("previous_status") or
                                 ("CERTIFIED_ACTIVE" if row["is_current"] else "ACTIVE"))
                is_current = int(evidence.get("previous_is_current", row["is_current"])) if restore else int(row["is_current"])
                if target in {"TRASHED", "INVALIDATED"}:
                    is_current = 0
                    conn.execute(
                        """UPDATE logical_assets SET current_capture_id=
                           CASE WHEN current_capture_id=? THEN NULL ELSE current_capture_id END,
                           updated_at=? WHERE logical_asset_id=?""",
                        (capture_id, _now(), row["logical_asset_id"]),
                    )
                conn.execute(
                    "UPDATE capture_versions SET asset_status=?,is_current=?,updated_at=? WHERE capture_id=?",
                    (target, is_current, _now(), capture_id),
                )
                if restore and is_current:
                    conn.execute(
                        "UPDATE logical_assets SET current_capture_id=?,updated_at=? WHERE logical_asset_id=?",
                        (capture_id, _now(), row["logical_asset_id"]),
                    )
                self._mark_merges_stale(
                    conn, [capture_id],
                    "STALE_SOURCE_INVALIDATED" if target == "INVALIDATED" else
                    "STALE_SOURCE_ARCHIVED" if target in {"ARCHIVED", "TRASHED"} else "CURRENT",
                )
                conn.execute(
                    """INSERT INTO asset_status_transitions(
                        transition_id,logical_asset_id,capture_id,previous_status,new_status,
                        actor,reason,evidence_json,source_ui_action,producer_version,created_at
                       ) VALUES(?,?,?,?,?,?,?,?,?,'v6.8',?)""",
                    ("TRANS_" + uuid.uuid4().hex, row["logical_asset_id"], capture_id,
                     previous, target, actor, reason,
                     _json({"previous_status": previous,
                            "previous_is_current": int(row["is_current"]), "restore": restore}),
                     "ASSET_MANAGEMENT", _now()),
                )
                changed.append(capture_id)
        return changed

    def archive(self, logical_asset_ids: Iterable[str], *, actor: str, reason: str, restore: bool = False) -> list[str]:
        ids = [str(x) for x in logical_asset_ids]
        action = "RESTORE" if restore else "ARCHIVE"
        with self.registry.connect() as conn:
            for asset_id in ids:
                versions = [dict(row) for row in conn.execute(
                    "SELECT capture_id,asset_status FROM capture_versions WHERE logical_asset_id=?",
                    (asset_id,),
                ).fetchall()]
                if restore:
                    op = conn.execute(
                        """SELECT payload_json FROM archive_operations
                           WHERE target_type='LOGICAL_ASSET' AND target_id=? AND action='ARCHIVE'
                           ORDER BY created_at DESC LIMIT 1""", (asset_id,)
                    ).fetchone()
                    payload = json.loads(op["payload_json"] or "{}") if op else {}
                    prior = dict(payload.get("version_statuses") or {})
                    direct = str(payload.get("direct_asset_status") or "ACTIVE")
                else:
                    prior = {row["capture_id"]: row["asset_status"] for row in versions}
                    direct = "ARCHIVED"
                conn.execute(
                    "UPDATE logical_assets SET direct_asset_status=?,updated_at=? WHERE logical_asset_id=?",
                    (direct, _now(), asset_id),
                )
                for row in versions:
                    status = str(prior.get(row["capture_id"]) or ("ACTIVE" if restore else "ARCHIVED"))
                    conn.execute(
                        "UPDATE capture_versions SET asset_status=?,updated_at=? WHERE capture_id=?",
                        (status if restore else "ARCHIVED", _now(), row["capture_id"]),
                    )
                if not restore:
                    self._mark_merges_stale(
                        conn, [row["capture_id"] for row in versions], "STALE_SOURCE_ARCHIVED"
                    )
                conn.execute(
                    """INSERT INTO archive_operations(operation_id,target_type,target_id,action,actor,reason,payload_json,created_at)
                       VALUES(?,?,?,?,?,?,?,?)""",
                    ("ARCH_" + uuid.uuid4().hex, "LOGICAL_ASSET", asset_id, action,
                    actor, reason, _json({
                        "restore": restore,
                        "direct_asset_status": "ACTIVE" if not restore else direct,
                        "version_statuses": prior,
                    }), _now()),
                )
        return ids

    def bootstrap_existing_captures(self, producer_version: str) -> dict[str, int]:
        created_versions = 0
        with self.registry.connect() as conn:
            assets_before = int(conn.execute("SELECT COUNT(*) n FROM logical_assets").fetchone()["n"])
        with self.registry.connect() as conn:
            rows = conn.execute(
                """SELECT c.*,cs.table_family,cs.member_table,
                   cs.source_table_title,cs.note_reference
                   FROM captures c LEFT JOIN capture_semantics cs ON cs.capture_id=c.capture_id
                   WHERE c.is_trashed=0
                   ORDER BY COALESCE(c.created_at,c.updated_at) ASC"""
            ).fetchall()
        for row in rows:
            data = dict(row)
            asset = self.get_or_create_logical_asset(data)
            with self.registry.connect() as conn:
                exists = conn.execute(
                    "SELECT 1 FROM capture_versions WHERE capture_id=?", (data["capture_id"],)
                ).fetchone()
            if not exists:
                merge_ready = False
                blockers: list[str] = []
                try:
                    from pathlib import Path
                    from capture_library import capture_readiness
                    evidence_path = Path(str(data.get("run_path") or "")) / "table_capture_result.json"
                    evidence = json.loads(evidence_path.read_text(encoding="utf-8"))
                    readiness = capture_readiness(evidence)
                    merge_ready = bool(readiness.get("merge_ready"))
                    blockers = list(readiness.get("merge_blockers") or [])
                except Exception as exc:
                    blockers = [f"BOOTSTRAP_EVIDENCE:{type(exc).__name__}"]
                self.register_capture_version(
                    logical_asset_id=asset["logical_asset_id"], capture_id=data["capture_id"],
                    producer_version=str(data.get("producer_version") or producer_version),
                    processing_status="COMPLETED", registration_status="REGISTERED",
                    quality_status="READY" if merge_ready else "REVIEW_REQUIRED",
                    review_status="CONFIRMED_AUTO" if merge_ready else "PENDING",
                    certified=merge_ready,
                )
                if not merge_ready:
                    self.enqueue_review(
                        logical_asset_id=asset["logical_asset_id"], capture_id=data["capture_id"],
                        primary_reason=blockers[0] if blockers else "BOOTSTRAP_REVIEW_REQUIRED",
                        secondary_reasons=blockers[1:], evidence={"bootstrap": True},
                    )
                created_versions += 1
        repaired_currentless=0
        with self.registry.connect() as conn:
            currentless=conn.execute(
                """SELECT la.logical_asset_id
                   FROM logical_assets la
                   WHERE NOT EXISTS (
                       SELECT 1 FROM capture_versions cv
                       WHERE cv.logical_asset_id=la.logical_asset_id
                         AND cv.is_current=1
                   )"""
            ).fetchall()
            for asset_row in currentless:
                asset_id=str(asset_row["logical_asset_id"])
                latest=conn.execute(
                    """SELECT capture_id FROM capture_versions
                       WHERE logical_asset_id=?
                         AND asset_status NOT IN ('TRASHED','ARCHIVED','INVALIDATED')
                       ORDER BY capture_version DESC LIMIT 1""",
                    (asset_id,),
                ).fetchone()
                if not latest:
                    continue
                current_id=str(latest["capture_id"])
                conn.execute(
                    """UPDATE capture_versions
                       SET asset_status='SUPERSEDED',
                           superseded_by_capture_id=?,updated_at=?
                       WHERE logical_asset_id=? AND capture_id<>?
                         AND asset_status='ACTIVE'""",
                    (current_id,_now(),asset_id,current_id),
                )
                previous=conn.execute(
                    """SELECT capture_id FROM capture_versions
                       WHERE logical_asset_id=? AND capture_id<>?
                         AND asset_status='SUPERSEDED'
                       ORDER BY capture_version DESC LIMIT 1""",
                    (asset_id,current_id),
                ).fetchone()
                conn.execute(
                    """UPDATE capture_versions SET is_current=1,
                       supersedes_capture_id=COALESCE(supersedes_capture_id,?),
                       updated_at=? WHERE capture_id=?""",
                    (str(previous["capture_id"]) if previous else None,_now(),current_id),
                )
                conn.execute(
                    """UPDATE logical_assets SET current_capture_id=?,updated_at=?
                       WHERE logical_asset_id=?""",
                    (current_id,_now(),asset_id),
                )
                repaired_currentless+=1
        with self.registry.connect() as conn:
            assets_after = int(conn.execute("SELECT COUNT(*) n FROM logical_assets").fetchone()["n"])
        return {
            "logical_assets_created": assets_after-assets_before,
            "capture_versions_created": created_versions,
            "currentless_assets_repaired":repaired_currentless,
        }
