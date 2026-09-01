"""Unified batch execution service for Stage B certified child capture.

Both the strict-child-mapping flow and the explicit-note-target compat flow
use this service so that batch tracking, progress monitoring, retry, and
review-queue construction are identical.  The compat flow becomes a thin
adapter that only differs in how it builds the CaptureRequest list.
"""
from __future__ import annotations

import copy
import json
import hashlib
import re
import uuid
from pathlib import Path
from typing import Any

from capture_models import (
    CAPTURE_SCOPE_CONTRACT_VERSION,
    LEGACY_CAPTURE_SCOPE_CONTRACT_VERSION,
    CaptureScopePolicy,
    normalise_capture_scope_contract,
    normalise_capture_scope_selection,
)


class ChildCaptureExecutionService:
    """Submit, monitor, retry, and route certified-child capture batches."""

    CALLBACK_KEY = "GuidedCaptureService.execute"
    WORKSPACE_ROUTE = "逻辑资产工作区"

    def __init__(
        self,
        registry: Any,
        capture_service: Any,
        table_capture_runner: Any,
        research_batch_service: Any,
        guided_capture_service: Any | None = None,
        capture_version_service: Any | None = None,
        hierarchical_child_discovery_service: Any | None = None,
        capture_orchestrator: Any | None = None,
    ) -> None:
        self.registry = registry
        self.capture_service = capture_service
        self.runner = table_capture_runner
        self.research_batch = research_batch_service
        self.guided_capture = guided_capture_service
        self.capture_version = capture_version_service
        self.child_discovery = hierarchical_child_discovery_service
        self.orchestrator = capture_orchestrator

    # ------------------------------------------------------------------
    # Persistent Capture Plan and execution-session preparation
    # ------------------------------------------------------------------

    @staticmethod
    def execution_session_key(
        *, display_name: str,
        research_definition: dict[str, Any] | None = None,
        scope: str = "",
    ) -> str:
        """Return the entry-origin-independent Stage B session key."""
        definition = dict(research_definition or {})
        identity = {
            "display_name":str(display_name or "").strip(),
            "research_definition_id":str(
                definition.get("definition_id")
                or definition.get("research_definition_id")
                or ""
            ),
            "definition_version":str(
                definition.get("definition_version") or ""
            ),
            "scope":str(scope or ""),
        }
        digest = hashlib.sha256(
            json.dumps(
                identity,ensure_ascii=False,sort_keys=True,
                separators=(",",":"),
            ).encode("utf-8")
        ).hexdigest()[:24]
        return "STAGEB_"+digest

    @staticmethod
    def _base_execution_session_key(session_key: str) -> str:
        """Return the stable, unversioned identity for an execution session."""
        value = str(session_key or "")
        return value.split("__V", 1)[0]

    @classmethod
    def _versioned_execution_session_key(
        cls, base_session_key: str, plan_ids: list[str],
        capture_scope: dict[str, Any],
    ) -> str:
        identity = {
            "base_session_key":cls._base_execution_session_key(base_session_key),
            "plan_ids":sorted({str(value) for value in plan_ids}),
            "capture_scope":dict(capture_scope),
        }
        digest = hashlib.sha256(
            json.dumps(
                identity,ensure_ascii=False,sort_keys=True,
                separators=(",",":"),
            ).encode("utf-8")
        ).hexdigest()[:24]
        return f"{identity['base_session_key']}__V{digest}"

    @staticmethod
    def _session_is_locked(row: Any | None) -> bool:
        if not row:
            return False
        return bool(row["research_batch_id"]) or str(
            row["status"] or ""
        ).upper() in {"SUBMITTING", "EXECUTING", "TERMINAL"}

    @staticmethod
    def _row_plan_ids(row: Any | None) -> list[str]:
        if not row:
            return []
        try:
            values = json.loads(row["plan_ids_json"] or "[]")
        except (TypeError, json.JSONDecodeError):
            raise ValueError("INVALID_STAGE_B_PLAN_ID_STATE")
        return [str(value) for value in values]

    def _latest_matching_session(
        self, base_session_key: str, plan_ids: list[str],
    ) -> Any | None:
        """Find the newest persisted version carrying the current plan set."""
        base = self._base_execution_session_key(base_session_key)
        with self.registry.connect() as conn:
            rows = conn.execute(
                """SELECT * FROM stage_b_execution_sessions
                   WHERE session_key=? OR session_key GLOB ?
                   ORDER BY updated_at DESC,session_key DESC""",
                (base, f"{base}__V*"),
            ).fetchall()
        wanted = sorted({str(value) for value in plan_ids})
        for row in rows:
            if sorted(set(self._row_plan_ids(row))) == wanted:
                return row
        return None

    def _latest_execution_session_row(self, base_session_key: str) -> Any | None:
        """Return the newest persisted session row for this base identity."""
        base = self._base_execution_session_key(base_session_key)
        with self.registry.connect() as conn:
            rows = conn.execute(
                """SELECT * FROM stage_b_execution_sessions
                   WHERE session_key=? OR session_key GLOB ?
                   ORDER BY updated_at DESC,session_key DESC""",
                (base, f"{base}__V*"),
            ).fetchall()
        return rows[0] if rows else None

    def latest_execution_session_key(self, base_session_key: str) -> str | None:
        """Return the newest persisted session key for a base session."""
        row = self._latest_execution_session_row(base_session_key)
        return str(row["session_key"]) if row else None

    def _create_versioned_session(
        self, existing: Any, *, base_session_key: str,
        plan_ids: list[str], capture_scope: dict[str, Any],
    ) -> str:
        """Create or reuse a clean PLANNED snapshot for a changed request."""
        version_key = self._versioned_execution_session_key(
            base_session_key,plan_ids,capture_scope,
        )
        target = self._execution_session_row(version_key)
        if target:
            return version_key
        now = self._now()
        definition_id = str(existing["research_definition_id"] or "")
        definition_version = str(existing["definition_version"] or "")
        with self.registry.connect() as conn:
            conn.execute(
                """INSERT INTO stage_b_execution_sessions(
                   session_key,entry_origin,display_name,scope,
                   research_definition_id,definition_version,status,
                   research_batch_id,plan_ids_json,batch_ids_json,
                   callback_key,workspace_route,workspace_filter_json,
                   capture_scope_json,created_at,updated_at
                   ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    version_key,str(existing["entry_origin"] or "UNIFIED"),
                    str(existing["display_name"] or ""),
                    str(existing["scope"] or ""),definition_id,
                    definition_version,"PLANNED",None,
                    json.dumps(list(dict.fromkeys(str(x) for x in plan_ids)),ensure_ascii=False),
                    "[]",str(existing["callback_key"] or self.CALLBACK_KEY),
                    str(existing["workspace_route"] or self.WORKSPACE_ROUTE),
                    "{}",json.dumps(capture_scope,ensure_ascii=False),
                    now,now,
                ),
            )
        return version_key

    def _create_replay_session(self, existing: Any) -> str:
        """Create a clean execution attempt from an already submitted session.

        This method is reached only by an explicit submit action.  It keeps the
        certified plan and scope snapshot but starts with fresh Research Batch
        and source-batch lineage, so historical Capture evidence is preserved.
        """
        if not existing:
            raise KeyError("STAGE_B_EXECUTION_SESSION_NOT_FOUND")
        base_session_key = self._base_execution_session_key(
            str(existing["session_key"])
        )
        plan_ids = self._row_plan_ids(existing)
        capture_scope = self._capture_scope_from_row(existing)
        version_stem = self._versioned_execution_session_key(
            base_session_key,plan_ids,capture_scope,
        )
        replay_key = f"{version_stem}__R{uuid.uuid4().hex[:12]}"
        now = self._now()
        with self.registry.connect() as conn:
            conn.execute(
                """INSERT INTO stage_b_execution_sessions(
                   session_key,entry_origin,display_name,scope,
                   research_definition_id,definition_version,status,
                   research_batch_id,plan_ids_json,batch_ids_json,
                   callback_key,workspace_route,workspace_filter_json,
                   capture_scope_json,created_at,updated_at
                   ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    replay_key,str(existing["entry_origin"] or "UNIFIED"),
                    str(existing["display_name"] or ""),
                    str(existing["scope"] or ""),
                    str(existing["research_definition_id"] or ""),
                    str(existing["definition_version"] or ""),
                    "PLANNED",None,
                    json.dumps(plan_ids,ensure_ascii=False),"[]",
                    str(existing["callback_key"] or self.CALLBACK_KEY),
                    str(existing["workspace_route"] or self.WORKSPACE_ROUTE),
                    "{}",json.dumps(capture_scope,ensure_ascii=False),
                    now,now,
                ),
            )
        return replay_key

    def prepare_capture_plans(
        self, *, display_name: str,
        certified_links: list[dict[str, Any]] | None = None,
        source_pdf_map: dict[str, Path] | None = None,
        plans: list[dict[str, Any]] | None = None,
        research_definition: dict[str, Any] | None = None,
        scope: str = "",
        session_key: str | None = None,
        entry_origin: str = "UNIFIED",
        capture_scope_contract_version: int | None = None,
        capture_scope_policy: str | CaptureScopePolicy | None = None,
        selected_logical_table_ids: list[str] | tuple[str, ...] | None = None,
        selected_block_roles: list[str] | tuple[str, ...] | None = None,
        selected_block_ids: list[str] | tuple[str, ...] | None = None,
        persist: bool = True,
    ) -> dict[str, Any]:
        """Prepare the Stage B capture-plan state.

        When ``persist`` is true, the plan and session rows are written to the
        registry.  When false, the same normalized state is returned as a
        read-only preview and no business state is mutated.
        """
        session_key = session_key or self.execution_session_key(
            display_name=display_name,
            research_definition=research_definition,
            scope=scope,
        )
        base_session_key = self._base_execution_session_key(session_key)
        existing = self._execution_session_row(session_key)
        scope_supplied = any(value is not None for value in (
            capture_scope_contract_version,capture_scope_policy,
            selected_logical_table_ids,selected_block_roles,selected_block_ids,
        ))
        candidates: list[dict[str, Any]] = []
        if certified_links:
            candidates.extend(
                self._strict_links_to_plans(
                    certified_links,
                    source_pdf_map=source_pdf_map,
                    research_definition=research_definition,
                    scope=scope,
                )
            )
        candidates.extend(dict(plan) for plan in (plans or []))
        if not candidates:
            if scope_supplied:
                if not persist:
                    preview = self.restore_execution(session_key)
                    preview["capture_scope"] = self._resolve_capture_scope(
                        existing,
                        capture_scope_contract_version=capture_scope_contract_version,
                        capture_scope_policy=capture_scope_policy,
                        selected_logical_table_ids=selected_logical_table_ids,
                        selected_block_roles=selected_block_roles,
                        selected_block_ids=selected_block_ids,
                    )
                    return preview
                return self.persist_capture_scope(
                    session_key,
                    capture_scope_contract_version=capture_scope_contract_version,
                    capture_scope_policy=capture_scope_policy,
                    selected_logical_table_ids=selected_logical_table_ids,
                    selected_block_roles=selected_block_roles,
                    selected_block_ids=selected_block_ids,
                )
            return self.restore_execution(session_key)

        persisted: list[dict[str, Any]] = []
        if persist:
            from discovery_registry import DiscoveryRegistry
            store = DiscoveryRegistry(self.registry)
            for candidate in candidates:
                normalised = self._normalise_plan_context(
                    candidate,
                    source_pdf_map=source_pdf_map,
                    research_definition=research_definition,
                )
                persisted.append(store.ensure_capture_plan(normalised))
        else:
            for candidate in candidates:
                persisted.append(self._normalise_plan_context(
                    candidate,
                    source_pdf_map=source_pdf_map,
                    research_definition=research_definition,
                ))

        plan_ids = list(dict.fromkeys(
            str(plan["plan_id"]) for plan in persisted
        ))
        if not scope_supplied:
            matching = self._latest_matching_session(base_session_key,plan_ids)
            if matching is not None:
                session_key = str(matching["session_key"])
                existing = matching
        current_scope = self._capture_scope_from_row(existing)
        capture_scope = self._resolve_capture_scope(
            existing,
            capture_scope_contract_version=capture_scope_contract_version,
            capture_scope_policy=capture_scope_policy,
            selected_logical_table_ids=selected_logical_table_ids,
            selected_block_roles=selected_block_roles,
            selected_block_ids=selected_block_ids,
        )
        existing_plan_ids = self._row_plan_ids(existing)
        if existing and self._session_is_locked(existing) and (
            sorted(set(existing_plan_ids)) != sorted(set(plan_ids))
            or capture_scope != current_scope
        ):
            if not persist:
                existing = self._latest_execution_session_row(session_key)
                if existing is None:
                    existing = self._execution_session_row(session_key)
            if persist:
                session_key = self._create_versioned_session(
                    existing,base_session_key=base_session_key,
                    plan_ids=plan_ids,capture_scope=capture_scope,
                )
                existing = self._execution_session_row(session_key)
        batch_ids = (
            json.loads(existing["batch_ids_json"] or "[]") if existing else []
        )
        existing_origin = str(existing["entry_origin"]) if existing else ""
        effective_origin = str(entry_origin or "UNIFIED").upper()
        if existing_origin and existing_origin != effective_origin:
            effective_origin = "UNIFIED"
        definition = dict(research_definition or {})
        now = self._now()
        status = str(existing["status"]) if existing else "PLANNED"
        research_batch_id = (
            str(existing["research_batch_id"] or "") if existing else ""
        )
        batch_ids = (
            json.loads(existing["batch_ids_json"] or "[]") if existing else []
        )
        workspace_filter = (
            json.loads(existing["workspace_filter_json"] or "{}")
            if existing else {}
        )
        if not persist:
            preview = self.restore_execution(
                str(existing["session_key"]) if existing else session_key
            )
            preview["session_key"] = session_key
            preview["entry_origin"] = effective_origin
            preview["status"] = (
                str(existing["status"]) if existing else "PLANNED"
            )
            preview["research_batch_id"] = research_batch_id or ""
            preview["plan_ids"] = plan_ids
            preview["plans"] = persisted
            preview["batch_ids"] = batch_ids
            preview["progress"] = self.monitor_all(batch_ids) if batch_ids else []
            preview["all_terminal"] = self.all_terminal(batch_ids) if batch_ids else False
            preview["review_queue"] = (
                self.build_review_queue(research_batch_id)
                if research_batch_id else []
            )
            preview["callback_key"] = self.CALLBACK_KEY
            preview["workspace_route"] = self.WORKSPACE_ROUTE
            preview["workspace_filter"] = (
                {"research_batch_id": research_batch_id}
                if research_batch_id else workspace_filter
            )
            preview["capture_scope"] = capture_scope
            preview["job_count"] = sum(
                int(item.get("总作业") or 0)
                for item in preview.get("progress") or []
            )
            preview["blocked_count"] = 0
            return preview
        with self.registry.connect() as conn:
            conn.execute(
                """INSERT INTO stage_b_execution_sessions(
                   session_key,entry_origin,display_name,scope,
                   research_definition_id,definition_version,status,
                   research_batch_id,plan_ids_json,batch_ids_json,
                   callback_key,workspace_route,workspace_filter_json,
                   capture_scope_json,created_at,updated_at
                   ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                   ON CONFLICT(session_key) DO UPDATE SET
                   entry_origin=excluded.entry_origin,
                   display_name=excluded.display_name,
                   scope=excluded.scope,
                   research_definition_id=excluded.research_definition_id,
                   definition_version=excluded.definition_version,
                   plan_ids_json=excluded.plan_ids_json,
                   capture_scope_json=excluded.capture_scope_json,
                   updated_at=excluded.updated_at""",
                (
                    session_key,effective_origin,display_name.strip(),scope,
                    str(
                        definition.get("definition_id")
                        or definition.get("research_definition_id")
                        or ""
                    ),
                    str(definition.get("definition_version") or ""),
                    status,research_batch_id or None,
                    json.dumps(plan_ids,ensure_ascii=False),
                    json.dumps(batch_ids,ensure_ascii=False),
                    self.CALLBACK_KEY,self.WORKSPACE_ROUTE,
                    json.dumps(workspace_filter,ensure_ascii=False),
                    json.dumps(capture_scope,ensure_ascii=False),
                    str(existing["created_at"]) if existing else now,now,
                ),
            )
        return self.restore_execution(session_key)

    def preview_capture_plans(
        self, *, display_name: str,
        certified_links: list[dict[str, Any]] | None = None,
        source_pdf_map: dict[str, Path] | None = None,
        plans: list[dict[str, Any]] | None = None,
        research_definition: dict[str, Any] | None = None,
        scope: str = "",
        session_key: str | None = None,
        entry_origin: str = "UNIFIED",
        capture_scope_contract_version: int | None = None,
        capture_scope_policy: str | CaptureScopePolicy | None = None,
        selected_logical_table_ids: list[str] | tuple[str, ...] | None = None,
        selected_block_roles: list[str] | tuple[str, ...] | None = None,
        selected_block_ids: list[str] | tuple[str, ...] | None = None,
    ) -> dict[str, Any]:
        """Return the current Capture Plan preview without persisting it."""
        return self.prepare_capture_plans(
            display_name=display_name,
            certified_links=certified_links,
            source_pdf_map=source_pdf_map,
            plans=plans,
            research_definition=research_definition,
            scope=scope,
            session_key=session_key,
            entry_origin=entry_origin,
            capture_scope_contract_version=capture_scope_contract_version,
            capture_scope_policy=capture_scope_policy,
            selected_logical_table_ids=selected_logical_table_ids,
            selected_block_roles=selected_block_roles,
            selected_block_ids=selected_block_ids,
            persist=False,
        )

    def restore_execution(self,session_key: str) -> dict[str, Any]:
        """Reconstruct Stage B state only from Registry, Job, and Inbox rows."""
        row = self._execution_session_row(session_key)
        if not row:
            capture_scope = self._capture_scope_payload()
            return {
                "session_key":session_key,
                "entry_origin":"",
                "status":"NOT_PLANNED",
                "executed":False,
                "research_batch_id":"",
                "plan_ids":[],
                "plans":[],
                "batch_ids":[],
                "progress":[],
                "all_terminal":False,
                "review_queue":[],
                "callback_key":self.CALLBACK_KEY,
                "workspace_route":self.WORKSPACE_ROUTE,
                "workspace_filter":{},
                "capture_scope":capture_scope,
                "job_count":0,
                "blocked_count":0,
                "submitted_plan_ids":[],
                "all_plans_submitted":False,
            }
        plan_ids = [
            str(value)
            for value in json.loads(row["plan_ids_json"] or "[]")
        ]
        batch_ids = [
            str(value)
            for value in json.loads(row["batch_ids_json"] or "[]")
        ]
        research_batch_id = str(row["research_batch_id"] or "")
        if research_batch_id:
            with self.registry.connect() as conn:
                linked_batch_ids = [
                    str(item["source_batch_id"])
                    for item in conn.execute(
                        """SELECT DISTINCT source_batch_id
                           FROM research_batch_members
                           WHERE research_batch_id=?
                             AND role='SOURCE_BATCH'
                             AND status='ACTIVE'
                             AND source_batch_id IS NOT NULL""",
                        (research_batch_id,),
                    ).fetchall()
                ]
            batch_ids = list(dict.fromkeys(batch_ids+linked_batch_ids))
        from discovery_registry import DiscoveryRegistry
        store = DiscoveryRegistry(self.registry)
        plans = [
            plan for plan in (
                store.get_capture_plan(plan_id) for plan_id in plan_ids
            ) if plan
        ]
        progress = self.monitor_all(batch_ids) if batch_ids else []
        all_terminal = self.all_terminal(batch_ids) if batch_ids else False
        review_queue = (
            self.build_review_queue(research_batch_id)
            if research_batch_id else []
        )
        status = str(row["status"])
        submitted: set[str] = set()
        all_plans_submitted = False
        if batch_ids:
            submitted = self._submitted_plan_ids(batch_ids)
            all_plans_submitted = set(plan_ids).issubset(submitted)
            status = (
                "TERMINAL" if all_terminal and all_plans_submitted
                else "EXECUTING" if all_plans_submitted
                else "SUBMITTING"
            )
        workspace_filter = json.loads(row["workspace_filter_json"] or "{}")
        capture_scope = self._capture_scope_from_row(row)
        if research_batch_id:
            workspace_filter = {"research_batch_id":research_batch_id}
        return {
            "session_key":session_key,
            "entry_origin":str(row["entry_origin"]),
            "status":status,
            "executed":bool(research_batch_id),
            "research_batch_id":research_batch_id,
            "plan_ids":plan_ids,
            "plans":plans,
            "batch_ids":batch_ids,
            "progress":progress,
            "all_terminal":all_terminal,
            "review_queue":review_queue,
            "callback_key":str(row["callback_key"]),
            "workspace_route":str(row["workspace_route"]),
            "workspace_filter":workspace_filter,
            "capture_scope":capture_scope,
            "job_count":sum(int(item.get("总作业") or 0) for item in progress),
            "blocked_count":0,
            "submitted_plan_ids":sorted(submitted),
            "all_plans_submitted":all_plans_submitted,
        }

    # ------------------------------------------------------------------
    # Batch creation
    # ------------------------------------------------------------------

    @staticmethod
    def _compact_identity(value: Any) -> str:
        return "".join(str(value or "").split())

    @classmethod
    def _note_references_match(cls,left: Any,right: Any) -> bool:
        left_value = cls._compact_identity(left)
        right_value = cls._compact_identity(right)
        if not left_value or not right_value or left_value == right_value:
            return True
        from table_boundary_resolver import parse_note_ordinal
        left_ordinal = parse_note_ordinal(left_value)
        right_ordinal = parse_note_ordinal(right_value)
        if left_ordinal is None or right_ordinal is None:
            return False
        bare_pattern = re.compile(
            r"^[（(]?(?:\d{1,3}|[零〇一二三四五六七八九十百]{1,5})"
            r"[）)]?[.．、]?$"
        )
        return left_ordinal == right_ordinal and bool(
            bare_pattern.fullmatch(left_value)
            or bare_pattern.fullmatch(right_value)
        )

    @staticmethod
    def _certified_segment_scope(
        target: dict[str, Any],policy: str, *,
        contract_version: int = LEGACY_CAPTURE_SCOPE_CONTRACT_VERSION,
    ) -> tuple[list[dict[str, Any]],list[dict[str, Any]],list[str]]:
        try:
            contract_version = int(contract_version)
        except (TypeError,ValueError):
            contract_version = LEGACY_CAPTURE_SCOPE_CONTRACT_VERSION
        policy = (
            policy.value
            if isinstance(policy,CaptureScopePolicy)
            else str(policy or CaptureScopePolicy.PRIMARY_ONLY.value)
        ).strip().upper()
        manifest_status = str(
            target.get("segment_manifest_status")
            or "LEGACY_PRIMARY_ANCHOR_ONLY"
        ).strip().upper()
        table_classification = str(
            target.get("table_classification") or "PRIMARY_TABLE"
        ).strip().upper()
        raw_segments = target.get("certified_segments") or []
        segments = [
            dict(segment) for segment in raw_segments
            if isinstance(segment,dict)
        ]
        def _segment_order(segment: dict[str, Any]) -> tuple[int,int,str]:
            raw_order = segment.get("order")
            try:
                order = int(raw_order)
            except (TypeError,ValueError):
                order = 10_000
            raw_page = (
                segment.get("start_page")
                or segment.get("pdf_page_number")
                or segment.get("page")
            )
            try:
                page = int(raw_page)
            except (TypeError,ValueError):
                page = 10_000
            segment_id = str(
                segment.get("certified_segment_id")
                or segment.get("segment_id")
                or ""
            )
            return order,page,segment_id

        segments.sort(key=_segment_order)
        include_continuations = policy in {
            CaptureScopePolicy.PRIMARY_WITH_CONTINUATIONS.value,
            CaptureScopePolicy.SELECTED_NOTE_TABLES.value,
            CaptureScopePolicy.ALL_NOTE_TABLES.value,
        }
        if contract_version != CAPTURE_SCOPE_CONTRACT_VERSION and not include_continuations:
            return segments[:1],segments[1:],[]
        if (
            manifest_status != "CERTIFIED_SEGMENT_MANIFEST"
            or not segments
        ):
            return [],segments,["CERTIFIED_SEGMENT_MANIFEST_REQUIRED"]

        seen: set[str] = set()
        invalid = False
        for index,segment in enumerate(segments):
            segment_id = str(
                segment.get("certified_segment_id")
                or segment.get("segment_id")
                or ""
            ).strip()
            classification = str(
                segment.get("classification") or ""
            ).strip().upper()
            certification_status = str(
                segment.get("certification_status") or "CERTIFIED"
            ).strip().upper()
            parent_id = str(
                segment.get("continuation_of_segment_id") or ""
            ).strip()
            if (
                not segment_id
                or certification_status != "CERTIFIED"
                or (
                    index == 0
                    and classification != table_classification
                )
                or (
                    index > 0
                    and (
                        classification != "CONTINUATION_SEGMENT"
                        or not parent_id
                        or parent_id not in seen
                    )
                )
            ):
                invalid = True
            seen.add(segment_id)
        if invalid:
            return [],segments,["CERTIFIED_SEGMENT_MANIFEST_REQUIRED"]
        if include_continuations:
            return segments,[],[]
        return segments[:1],segments[1:],[]

    def _certified_inventory_gate(
        self,target: dict[str, Any],
    ) -> tuple[dict[str, Any] | None,list[str]]:
        inventory_id = str(
            target.get("note_table_inventory_id") or ""
        ).strip()
        if (
            not inventory_id
            or str(
                target.get("note_table_inventory_status") or ""
            ).strip().upper() != "COMPLETE"
        ):
            return None,["CERTIFIED_NOTE_TABLE_INVENTORY_REQUIRED"]
        with self.registry.connect() as conn:
            row = conn.execute(
                """SELECT * FROM certified_note_table_inventories
                   WHERE note_table_inventory_id=?""",
                (inventory_id,),
            ).fetchone()
        if not row:
            return None,["CERTIFIED_NOTE_TABLE_INVENTORY_REQUIRED"]
        inventory = dict(row)
        if (
            str(inventory.get("inventory_status") or "").upper()
            != "COMPLETE"
            or str(inventory.get("certification_status") or "").upper()
            != "CERTIFIED"
            or (
                str(inventory.get("source_pdf_id") or "")
                != str(target.get("source_pdf_id") or "")
            )
            or (
                not self._note_references_match(
                    inventory.get("note_reference"),
                    target.get("note_reference"),
                )
            )
        ):
            return inventory,["CERTIFIED_NOTE_TABLE_INVENTORY_REQUIRED"]
        try:
            logical_table_ids = json.loads(
                inventory.get("logical_table_ids_json") or "[]"
            )
        except (TypeError,json.JSONDecodeError):
            logical_table_ids = []
        if not isinstance(logical_table_ids,list) or not logical_table_ids:
            return inventory,["CERTIFIED_NOTE_TABLE_INVENTORY_REQUIRED"]
        inventory["logical_table_ids"] = [
            str(value) for value in logical_table_ids if str(value)
        ]
        logical_table_id = str(
            target.get("logical_table_id")
            or target.get("member_table_id")
            or ""
        )
        if logical_table_id not in set(inventory["logical_table_ids"]):
            return inventory,["CERTIFIED_NOTE_TABLE_INVENTORY_REQUIRED"]
        return inventory,[]

    def _plan_for_capture_scope(
        self,plan: dict[str, Any],capture_scope: dict[str, Any],
        *, available_supplementary_ids: set[str] | None = None,
    ) -> dict[str, Any]:
        (
            contract_version,policy,logical_table_ids,roles,block_ids,
        ) = normalise_capture_scope_contract(
            capture_scope.get("capture_scope_contract_version"),
            capture_scope.get("capture_scope_policy"),
            capture_scope.get("selected_logical_table_ids"),
            capture_scope.get("selected_block_roles"),
            capture_scope.get("selected_block_ids"),
        )
        normalised_scope = {
            "capture_scope_contract_version":contract_version,
            "capture_scope_policy":policy,
            "selected_logical_table_ids":list(logical_table_ids),
            "selected_block_roles":list(roles),
            "selected_block_ids":list(block_ids),
        }
        if contract_version == LEGACY_CAPTURE_SCOPE_CONTRACT_VERSION:
            return self._plan_for_capture_scope_v1(plan,normalised_scope)
        return self._plan_for_capture_scope_v2(
            plan,normalised_scope,
            available_supplementary_ids=available_supplementary_ids,
        )

    def _plan_for_capture_scope_v2(
        self,plan: dict[str, Any],capture_scope: dict[str, Any],
        *, available_supplementary_ids: set[str] | None = None,
    ) -> dict[str, Any]:
        policy = str(capture_scope["capture_scope_policy"])
        requested_logical_ids = set(
            capture_scope.get("selected_logical_table_ids") or []
        )
        execution_plan = copy.deepcopy(plan)
        selected_items: list[dict[str, Any]] = []
        excluded_items: list[dict[str, Any]] = []
        plan_logical_ids: set[str] = set()
        selectable_supplementary_ids: set[str] = set()
        primary_count = 0

        for source_item in list(execution_plan.get("items") or []):
            if source_item.get("member_table_role") != "NOTE_DETAIL":
                selected_items.append(source_item)
                continue
            item = dict(source_item)
            target = dict(item.get("certified_note_target") or {})
            logical_table_id = str(
                target.get("logical_table_id") or ""
            ).strip()
            table_classification = str(
                target.get("table_classification") or ""
            ).strip().upper()
            explicit_logical_target = bool(
                logical_table_id
                and table_classification in {
                    "PRIMARY_TABLE","SUPPLEMENTARY_TABLE",
                }
            )
            if logical_table_id:
                plan_logical_ids.add(logical_table_id)
            if not explicit_logical_target:
                include = table_classification not in {
                    "PEER_TABLE","UNRESOLVED","CONTINUATION_SEGMENT",
                }
            elif table_classification == "PRIMARY_TABLE":
                primary_count += 1
                include = True
            elif table_classification == "SUPPLEMENTARY_TABLE":
                if logical_table_id:
                    selectable_supplementary_ids.add(logical_table_id)
                include = logical_table_id in requested_logical_ids
            else:
                include = False

            if not include:
                excluded_items.append({
                    **item,
                    "exclusion_reason": (
                        "EXCLUDED_BY_LOGICAL_TABLE_SELECTION"
                        if table_classification == "SUPPLEMENTARY_TABLE"
                        else "NON_SELECTABLE_LOGICAL_TABLE_CLASSIFICATION"
                    ),
                })
                continue

            issues: list[str] = []
            if (
                not explicit_logical_target
                or str(target.get("status") or "")
                != "CERTIFIED_NOTE_TARGET"
            ):
                issues.append("CERTIFIED_LOGICAL_TABLE_REQUIRED")
            if explicit_logical_target:
                selected_segments,excluded_segments,segment_issues = (
                    self._certified_segment_scope(
                        target,policy,
                        contract_version=CAPTURE_SCOPE_CONTRACT_VERSION,
                    )
                )
            else:
                selected_segments = []
                excluded_segments = list(
                    target.get("certified_segments") or []
                )
                segment_issues = []
            issues.extend(segment_issues)
            if table_classification == "SUPPLEMENTARY_TABLE":
                _,inventory_issues = self._certified_inventory_gate(target)
                issues.extend(inventory_issues)
            item["certified_note_target"] = {
                **target,
                "capture_scope_contract_version":(
                    CAPTURE_SCOPE_CONTRACT_VERSION
                ),
                "capture_scope_policy":policy,
                "selected_logical_table_ids":list(
                    capture_scope.get("selected_logical_table_ids") or []
                ),
                "certified_segments":selected_segments,
                "full_certified_segment_manifest":list(
                    target.get("certified_segments") or []
                ),
                "excluded_certified_segments":excluded_segments,
            }
            if issues:
                item["status"] = "REVIEW_REQUIRED"
                item["blocking_issue_codes"] = list(dict.fromkeys(issues))
            selected_items.append(item)

        selection_authority_ids = (
            set(available_supplementary_ids)
            if available_supplementary_ids is not None
            else selectable_supplementary_ids
        )
        invalid_selected_ids = requested_logical_ids - selection_authority_ids
        plan_issue_codes: list[str] = []
        if invalid_selected_ids:
            plan_issue_codes.append("CERTIFIED_LOGICAL_TABLE_NOT_SELECTABLE")
        if primary_count == 0:
            plan_issue_codes.append("CERTIFIED_PRIMARY_LOGICAL_TABLE_REQUIRED")
        if plan_issue_codes:
            for item in selected_items:
                if item.get("member_table_role") != "NOTE_DETAIL":
                    continue
                item["status"] = "REVIEW_REQUIRED"
                item["blocking_issue_codes"] = list(dict.fromkeys([
                    *list(item.get("blocking_issue_codes") or []),
                    *plan_issue_codes,
                ]))

        execution_plan["items"] = selected_items
        execution_plan["certified_scope_selection"] = {
            "capture_scope_contract_version":(
                CAPTURE_SCOPE_CONTRACT_VERSION
            ),
            "capture_scope_policy":policy,
            "selected_logical_table_ids":sorted(
                requested_logical_ids.intersection(
                    selectable_supplementary_ids
                )
            ),
            "selected_certified_link_ids":[
                str((item.get("certified_note_target") or {}).get(
                    "certified_link_id"
                ) or "")
                for item in selected_items
                if item.get("member_table_role") == "NOTE_DETAIL"
            ],
            "invalid_selected_logical_table_ids":sorted(
                invalid_selected_ids
            ),
            "issue_codes":plan_issue_codes,
            "excluded_items":excluded_items,
        }
        return execution_plan

    def _plan_for_capture_scope_v1(
        self,plan: dict[str, Any],capture_scope: dict[str, Any],
    ) -> dict[str, Any]:
        policy,_,_ = normalise_capture_scope_selection(
            capture_scope.get("capture_scope_policy"),
            capture_scope.get("selected_block_roles"),
            capture_scope.get("selected_block_ids"),
        )
        execution_plan = copy.deepcopy(plan)
        selected_items: list[dict[str, Any]] = []
        excluded_items: list[dict[str, Any]] = []
        inventory_members: dict[str,set[str]] = {}
        inventory_expected: dict[str,set[str]] = {}
        inventory_item_indexes: dict[str,list[int]] = {}

        for source_item in list(execution_plan.get("items") or []):
            if source_item.get("member_table_role") != "NOTE_DETAIL":
                selected_items.append(source_item)
                continue
            item = dict(source_item)
            target = dict(item.get("certified_note_target") or {})
            table_classification = str(
                target.get("table_classification") or "PRIMARY_TABLE"
            ).strip().upper()
            if table_classification not in {
                "PRIMARY_TABLE","SUPPLEMENTARY_TABLE",
            }:
                item["status"] = "REVIEW_REQUIRED"
                item["blocking_issue_codes"] = [
                    "CERTIFIED_LOGICAL_TABLE_REQUIRED"
                ]
                selected_items.append(item)
                continue
            if (
                policy != CaptureScopePolicy.ALL_NOTE_TABLES.value
                and table_classification == "SUPPLEMENTARY_TABLE"
            ):
                excluded_items.append({
                    **item,
                    "exclusion_reason":"EXCLUDED_BY_CAPTURE_SCOPE_POLICY",
                })
                continue

            selected_segments,excluded_segments,issues = (
                self._certified_segment_scope(target,policy)
            )
            inventory: dict[str, Any] | None = None
            if policy == CaptureScopePolicy.ALL_NOTE_TABLES.value:
                inventory,inventory_issues = self._certified_inventory_gate(
                    target
                )
                issues.extend(inventory_issues)
            scoped_target = {
                **target,
                "capture_scope_contract_version":(
                    LEGACY_CAPTURE_SCOPE_CONTRACT_VERSION
                ),
                "certified_segments":selected_segments,
                "full_certified_segment_manifest":list(
                    target.get("certified_segments") or []
                ),
                "excluded_certified_segments":excluded_segments,
                "capture_scope_policy":policy,
            }
            item["certified_note_target"] = scoped_target
            if issues:
                item["status"] = "REVIEW_REQUIRED"
                item["blocking_issue_codes"] = list(dict.fromkeys(issues))
            selected_items.append(item)

            if inventory is not None:
                inventory_id = str(
                    target.get("note_table_inventory_id") or ""
                )
                logical_table_id = str(
                    target.get("logical_table_id")
                    or target.get("member_table_id")
                    or ""
                )
                inventory_members.setdefault(inventory_id,set()).add(
                    logical_table_id
                )
                inventory_expected[inventory_id] = set(
                    inventory.get("logical_table_ids") or []
                )
                inventory_item_indexes.setdefault(inventory_id,[]).append(
                    len(selected_items)-1
                )

        if policy == CaptureScopePolicy.ALL_NOTE_TABLES.value:
            for inventory_id,expected in inventory_expected.items():
                if not expected or inventory_members.get(inventory_id,set()) != expected:
                    for index in inventory_item_indexes.get(inventory_id,[]):
                        item = selected_items[index]
                        item["status"] = "REVIEW_REQUIRED"
                        item["blocking_issue_codes"] = list(dict.fromkeys([
                            *list(item.get("blocking_issue_codes") or []),
                            "CERTIFIED_NOTE_TABLE_INVENTORY_REQUIRED",
                        ]))

        execution_plan["items"] = selected_items
        execution_plan["certified_scope_selection"] = {
            "capture_scope_contract_version":(
                LEGACY_CAPTURE_SCOPE_CONTRACT_VERSION
            ),
            "capture_scope_policy":policy,
            "selected_logical_table_ids":[],
            "selected_certified_link_ids":[
                str((item.get("certified_note_target") or {}).get(
                    "certified_link_id"
                ) or "")
                for item in selected_items
                if item.get("member_table_role") == "NOTE_DETAIL"
            ],
            "excluded_items":excluded_items,
        }
        return execution_plan

    def create_execution_batch(
        self,
        *,
        display_name: str,
        certified_links: list[dict[str, Any]] | None = None,
        source_pdf_map: dict[str, Path] | None = None,
        plans: list[dict[str, Any]] | None = None,
        research_definition: dict[str, Any] | None = None,
        scope: str = "",
        session_key: str | None = None,
        entry_origin: str = "UNIFIED",
        capture_scope_contract_version: int | None = None,
        capture_scope_policy: str | CaptureScopePolicy | None = None,
        selected_logical_table_ids: list[str] | tuple[str, ...] | None = None,
        selected_block_roles: list[str] | tuple[str, ...] | None = None,
        selected_block_ids: list[str] | tuple[str, ...] | None = None,
        create_new_attempt: bool = False,
    ) -> dict[str, Any]:
        """Execute only persisted plans through one callback and lineage."""
        session_key = session_key or self.execution_session_key(
            display_name=display_name,
            research_definition=research_definition,
            scope=scope,
        )
        scope_selection_supplied = any(value is not None for value in (
            capture_scope_contract_version,capture_scope_policy,
            selected_logical_table_ids,selected_block_roles,selected_block_ids,
        ))
        if certified_links or plans:
            state = self.prepare_capture_plans(
                display_name=display_name,
                certified_links=certified_links,
                source_pdf_map=source_pdf_map,
                plans=plans,
                research_definition=research_definition,
                scope=scope,
                session_key=session_key,
                entry_origin=entry_origin,
                capture_scope_contract_version=capture_scope_contract_version,
                capture_scope_policy=capture_scope_policy,
                selected_logical_table_ids=selected_logical_table_ids,
                selected_block_roles=selected_block_roles,
                selected_block_ids=selected_block_ids,
            )
        elif scope_selection_supplied:
            state = self.persist_capture_scope(
                session_key,
                capture_scope_contract_version=capture_scope_contract_version,
                capture_scope_policy=capture_scope_policy,
                selected_logical_table_ids=selected_logical_table_ids,
                selected_block_roles=selected_block_roles,
                selected_block_ids=selected_block_ids,
            )
        else:
            state = self.restore_execution(session_key)
        session_key = str(state.get("session_key") or session_key)
        if (
            create_new_attempt
            and bool(state.get("all_plans_submitted"))
            and not bool(state.get("all_terminal"))
        ):
            raise RuntimeError("STAGE_B_EXECUTION_STILL_ACTIVE")
        if create_new_attempt and bool(state.get("all_plans_submitted")):
            existing = self._execution_session_row(session_key)
            session_key = self._create_replay_session(existing)
            state = self.restore_execution(session_key)
        submitted_plan_ids = self._submitted_plan_ids(state["batch_ids"])
        if (
            state["batch_ids"]
            and set(state["plan_ids"]).issubset(submitted_plan_ids)
        ):
            return state
        persisted_plans = list(state["plans"])
        if not persisted_plans:
            return state
        capture_scope = dict(state["capture_scope"])
        available_supplementary_ids: set[str] | None = None
        if (
            int(capture_scope.get("capture_scope_contract_version") or 1)
            == CAPTURE_SCOPE_CONTRACT_VERSION
        ):
            available_supplementary_ids = {
                str(target.get("logical_table_id") or "")
                for plan in persisted_plans
                for item in (plan.get("items") or [])
                if item.get("member_table_role") == "NOTE_DETAIL"
                for target in [dict(item.get("certified_note_target") or {})]
                if str(target.get("table_classification") or "").upper()
                == "SUPPLEMENTARY_TABLE"
                and str(target.get("status") or "")
                == "CERTIFIED_NOTE_TARGET"
                and str(target.get("segment_manifest_status") or "").upper()
                == "CERTIFIED_SEGMENT_MANIFEST"
                and bool(target.get("certified_segments"))
                and str(
                    target.get("note_table_inventory_status") or ""
                ).upper() == "COMPLETE"
                and str(target.get("logical_table_id") or "")
            }
            requested_logical_ids = set(
                capture_scope.get("selected_logical_table_ids") or []
            )
            missing_logical_ids = sorted(
                requested_logical_ids - available_supplementary_ids
            )
            if missing_logical_ids:
                raise PermissionError(
                    "CERTIFIED_SELECTED_LOGICAL_TABLE_REQUIRED:"
                    + ",".join(missing_logical_ids)
                )
        if not self.guided_capture:
            raise RuntimeError("GUIDED_CAPTURE_SERVICE_REQUIRED")

        research_batch_id = str(state.get("research_batch_id") or "")
        if not research_batch_id:
            definition = dict(research_definition or {})
            session_row = self._execution_session_row(session_key)
            research = self.research_batch.create(
                display_name=f"{display_name.strip()}_研究引导抓取",
                table_family=display_name.strip(),
                payload={
                    "source_pdf_count":len({
                        str(plan.get("source_pdf_id") or plan.get("pdf_id") or "")
                        for plan in persisted_plans
                    }),
                    "plan_ids":state["plan_ids"],
                    "stage":"CERTIFIED_CAPTURE_PLAN",
                    "stage_b_session_key":session_key,
                    "callback_key":self.CALLBACK_KEY,
                    "entry_origin":state.get("entry_origin") or entry_origin,
                    "capture_scope":dict(state["capture_scope"]),
                },
                research_definition_id=(
                    definition.get("definition_id")
                    or (
                        str(session_row["research_definition_id"] or "")
                        if session_row else None
                    )
                ),
                definition_version=(
                    definition.get("definition_version")
                    or (
                        str(session_row["definition_version"] or "")
                        if session_row else None
                    )
                ),
            )
            research_batch_id = str(research["research_batch_id"])
            with self.registry.connect() as conn:
                conn.execute(
                    """UPDATE stage_b_execution_sessions
                       SET status='SUBMITTING',research_batch_id=?,
                           workspace_filter_json=?,updated_at=?
                       WHERE session_key=?""",
                    (
                        research_batch_id,
                        json.dumps(
                            {"research_batch_id":research_batch_id},
                            ensure_ascii=False,
                        ),
                        self._now(),session_key,
                    ),
                )

        batch_ids: list[str] = list(state["batch_ids"])
        total_jobs = 0
        total_blocked = 0
        for plan in persisted_plans:
            if str(plan["plan_id"]) in submitted_plan_ids:
                continue
            self._attach_once(
                research_batch_id,plan_id=str(plan["plan_id"]),role="PLAN",
            )
            pdf_path = self._resolve_plan_pdf(plan)
            if not pdf_path:
                total_blocked += len([
                    item for item in plan.get("items") or []
                    if item.get("member_table_role")=="NOTE_DETAIL"
                ])
                continue
            execution_plan = self._plan_for_capture_scope(
                plan,dict(state["capture_scope"]),
                available_supplementary_ids=available_supplementary_ids,
            )
            result = self.guided_capture.execute(
                execution_plan,pdf_path=pdf_path,
                research_batch_id=research_batch_id,
                options=dict(state["capture_scope"]),
            )
            batch_id = str(result.get("batch_id") or "")
            if batch_id:
                batch_ids = list(dict.fromkeys(batch_ids+[batch_id]))
                self._attach_once(
                    research_batch_id,
                    source_batch_id=batch_id,
                    role="SOURCE_BATCH",
                )
                with self.registry.connect() as conn:
                    conn.execute(
                        """UPDATE stage_b_execution_sessions
                           SET status='SUBMITTING',batch_ids_json=?,updated_at=?
                           WHERE session_key=?""",
                        (
                            json.dumps(batch_ids,ensure_ascii=False),
                            self._now(),session_key,
                        ),
                    )
            total_jobs += len(result.get("jobs") or [])
            total_blocked += len(result.get("blocked_items") or [])
        workspace_filter = {"research_batch_id":research_batch_id}
        with self.registry.connect() as conn:
            conn.execute(
                """UPDATE stage_b_execution_sessions
                   SET status=?,research_batch_id=?,batch_ids_json=?,
                       workspace_filter_json=?,updated_at=?
                   WHERE session_key=?""",
                (
                    "EXECUTING" if batch_ids else "PLANNED",
                    research_batch_id,
                    json.dumps(batch_ids,ensure_ascii=False),
                    json.dumps(workspace_filter,ensure_ascii=False),
                    self._now(),session_key,
                ),
            )
        restored = self.restore_execution(session_key)
        restored["job_count"] = total_jobs
        restored["blocked_count"] = total_blocked
        return restored

    def persist_capture_scope(
        self,session_key: str, *,
        capture_scope_contract_version: int | None = None,
        capture_scope_policy: str | CaptureScopePolicy | None = None,
        selected_logical_table_ids: list[str] | tuple[str, ...] | None = None,
        selected_block_roles: list[str] | tuple[str, ...] | None = None,
        selected_block_ids: list[str] | tuple[str, ...] | None = None,
    ) -> dict[str, Any]:
        """Persist an explicit pre-submit scope selection and freeze it after submit."""
        existing = self._execution_session_row(session_key)
        if not existing:
            raise KeyError(f"STAGE_B_EXECUTION_SESSION_NOT_FOUND:{session_key}")
        capture_scope = self._resolve_capture_scope(
            existing,
            capture_scope_contract_version=capture_scope_contract_version,
            capture_scope_policy=capture_scope_policy,
            selected_logical_table_ids=selected_logical_table_ids,
            selected_block_roles=selected_block_roles,
            selected_block_ids=selected_block_ids,
        )
        current_scope = self._capture_scope_from_row(existing)
        if capture_scope == current_scope:
            return self.restore_execution(session_key)
        plan_ids = self._row_plan_ids(existing)
        if self._session_is_locked(existing):
            version_key = self._versioned_execution_session_key(
                session_key,plan_ids,capture_scope,
            )
            target = self._execution_session_row(version_key)
            if target is None:
                version_key = self._create_versioned_session(
                    existing,base_session_key=session_key,
                    plan_ids=plan_ids,capture_scope=capture_scope,
                )
            return self.restore_execution(version_key)
        with self.registry.connect() as conn:
            conn.execute(
                """UPDATE stage_b_execution_sessions
                   SET capture_scope_json=?,updated_at=? WHERE session_key=?""",
                (
                    json.dumps(capture_scope,ensure_ascii=False),
                    self._now(),session_key,
                ),
            )
        return self.restore_execution(session_key)

    # ------------------------------------------------------------------
    # Progress monitoring
    # ------------------------------------------------------------------

    def monitor_batch(self, batch_id: str) -> dict[str, Any]:
        """Return batch progress summary from the table capture runner."""
        return self.runner.monitor(batch_id)

    def monitor_all(
        self, batch_ids: list[str]
    ) -> list[dict[str, Any]]:
        """Return progress for all batch IDs."""
        rows: list[dict[str, Any]] = []
        for bid in batch_ids:
            summary = self.monitor_batch(bid)
            rows.append({
                "批次": bid,
                "总作业": summary["total"],
                "已完成": summary["complete"],
                "运行中": summary["counts"].get("RUNNING", 0),
                "失败": summary["counts"].get("FAILED", 0),
                "进度": f"{summary['progress']:.0%}",
            })
        return rows

    def all_terminal(self, batch_ids: list[str]) -> bool:
        """True when all jobs in all batches have reached a terminal state."""
        if not batch_ids:
            return False
        for bid in batch_ids:
            summary = self.monitor_batch(bid)
            terminal = summary["complete"] + summary["counts"].get("FAILED", 0) + summary["counts"].get("SKIPPED", 0)
            if terminal < summary["total"]:
                return False
        return True

    # ------------------------------------------------------------------
    # Retry
    # ------------------------------------------------------------------

    def retry_failed(self, batch_id: str, max_workers: int = 3) -> list[dict[str, Any]]:
        """Re-submit failed jobs in a batch."""
        return self.runner.retry_failed(batch_id=batch_id, max_workers=max_workers)

    def failed_batch_ids(self, batch_ids: list[str]) -> list[str]:
        """Return batch IDs that have at least one FAILED job."""
        failed: list[str] = []
        for bid in batch_ids:
            summary = self.monitor_batch(bid)
            if summary["counts"].get("FAILED", 0) > 0:
                failed.append(bid)
        return failed

    # ------------------------------------------------------------------
    # Review queue construction
    # ------------------------------------------------------------------

    def build_review_queue(
        self, research_batch_id: str
    ) -> list[dict[str, Any]]:
        """Read the authoritative persisted Review Inbox for this batch."""
        if not self.registry:
            return []
        with self.registry.connect() as conn:
            rows = conn.execute(
                """SELECT DISTINCT
                   rq.review_item_id,rq.capture_id,rq.logical_asset_id,
                   rq.primary_review_reason,
                   rq.secondary_review_reasons_json,
                   cv.quality_status,cv.review_status,
                   la.company_id,la.report_year,la.table_family_id,
                   la.member_table_id
                   FROM review_queue rq
                   JOIN capture_versions cv
                     ON cv.capture_id=rq.capture_id
                   JOIN logical_assets la
                     ON la.logical_asset_id=rq.logical_asset_id
                   JOIN jobs j ON j.target_asset_id=rq.capture_id
                   JOIN research_batch_members m ON m.source_batch_id = j.batch_id
                   WHERE m.research_batch_id = ? AND m.status = 'ACTIVE'
                     AND rq.status='PENDING'
                     AND cv.is_current=1
                   ORDER BY rq.capture_id""",
                (research_batch_id,),
            ).fetchall()
        review_entries = []
        for source in rows:
            row = dict(source)
            secondary = json.loads(
                row.get("secondary_review_reasons_json") or "[]"
            )
            blockers = [
                str(row.get("primary_review_reason") or ""),
                *[str(value) for value in secondary],
            ]
            review_entries.append({
                "review_item_id":str(row["review_item_id"]),
                "capture_id":str(row["capture_id"]),
                "logical_asset_id":str(row["logical_asset_id"]),
                "company_id":row.get("company_id"),
                "report_year":row.get("report_year"),
                "table_family_id":row.get("table_family_id"),
                "member_table_id":row.get("member_table_id"),
                "capture_quality":row.get("quality_status"),
                "quality_blockers":"；".join(
                    value for value in blockers if value
                ),
                "initial_tab": "审核",
                "return_route": "整表批量工作台",
            })
        return review_entries

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _capture_scope_payload(
        capture_scope_contract_version: int | None = None,
        capture_scope_policy: str | CaptureScopePolicy | None = None,
        selected_logical_table_ids: list[str] | tuple[str, ...] | None = None,
        selected_block_roles: list[str] | tuple[str, ...] | None = None,
        selected_block_ids: list[str] | tuple[str, ...] | None = None,
    ) -> dict[str, Any]:
        (
            contract_version,policy,logical_table_ids,roles,block_ids,
        ) = normalise_capture_scope_contract(
            capture_scope_contract_version,
            capture_scope_policy,
            selected_logical_table_ids,
            selected_block_roles,
            selected_block_ids,
        )
        return {
            "capture_scope_contract_version":contract_version,
            "capture_scope_policy":policy,
            "selected_logical_table_ids":list(logical_table_ids),
            "selected_block_roles":list(roles),
            "selected_block_ids":list(block_ids),
        }

    @classmethod
    def _capture_scope_from_row(cls,row: Any | None) -> dict[str, Any]:
        if not row:
            return cls._capture_scope_payload(
                CAPTURE_SCOPE_CONTRACT_VERSION,
            )
        keys = set(row.keys()) if hasattr(row,"keys") else set(row)
        raw = row["capture_scope_json"] if "capture_scope_json" in keys else "{}"
        try:
            payload = json.loads(raw or "{}")
        except (TypeError,json.JSONDecodeError) as exc:
            raise ValueError("INVALID_STAGE_B_CAPTURE_SCOPE_STATE") from exc
        if not isinstance(payload,dict):
            raise ValueError("INVALID_STAGE_B_CAPTURE_SCOPE_STATE")
        contract_version = payload.get("capture_scope_contract_version")
        if contract_version is None:
            contract_version = LEGACY_CAPTURE_SCOPE_CONTRACT_VERSION
        return cls._capture_scope_payload(
            contract_version,
            payload.get("capture_scope_policy"),
            payload.get("selected_logical_table_ids"),
            payload.get("selected_block_roles"),
            payload.get("selected_block_ids"),
        )

    @classmethod
    def _resolve_capture_scope(
        cls,existing: Any | None, *,
        capture_scope_contract_version: int | None,
        capture_scope_policy: str | CaptureScopePolicy | None,
        selected_logical_table_ids: list[str] | tuple[str, ...] | None,
        selected_block_roles: list[str] | tuple[str, ...] | None,
        selected_block_ids: list[str] | tuple[str, ...] | None,
    ) -> dict[str, Any]:
        current = cls._capture_scope_from_row(existing)
        supplied = any(value is not None for value in (
            capture_scope_contract_version,capture_scope_policy,
            selected_logical_table_ids,selected_block_roles,selected_block_ids,
        ))
        if not supplied:
            return current
        requested = cls._capture_scope_payload(
            capture_scope_contract_version=(
                capture_scope_contract_version
                if capture_scope_contract_version is not None
                else current["capture_scope_contract_version"]
            ),
            capture_scope_policy=(
                capture_scope_policy
                if capture_scope_policy is not None
                else current["capture_scope_policy"]
            ),
            selected_logical_table_ids=(
                selected_logical_table_ids
                if selected_logical_table_ids is not None
                else current["selected_logical_table_ids"]
            ),
            selected_block_roles=(
                selected_block_roles
                if selected_block_roles is not None
                else current["selected_block_roles"]
            ),
            selected_block_ids=(
                selected_block_ids
                if selected_block_ids is not None
                else current["selected_block_ids"]
            ),
        )
        return requested

    def _strict_links_to_plans(
        self,links: list[dict[str, Any]], *,
        source_pdf_map: dict[str, Path] | None,
        research_definition: dict[str, Any] | None,
        scope: str,
    ) -> list[dict[str, Any]]:
        """Collapse certified child links into one plan per Statement Anchor.

        A ``CertifiedChildTableLink`` is deliberately one record per member
        table: each note detail has its own evidence, page and certification.
        It is *not* a Capture Plan.  The former adapter mistook that record
        granularity for execution-plan granularity and emitted one synthetic
        anchor per child.  Apart from duplicate plans/jobs, this discarded the
        real statement title and page in favour of ``anchor_id`` placeholders.

        The family-level identity below preserves the actual execution
        boundary: source filing + certified anchor + research family + scope.
        Different PDF filings, anchors, families or scopes remain isolated;
        only sibling NOTE_DETAIL targets of the same anchor are aggregated.
        """
        if not self.child_discovery:
            raise RuntimeError("STRICT_CAPTURE_PLAN_ADAPTER_NOT_CONFIGURED")
        definition = dict(research_definition or {})
        from discovery_registry import DiscoveryRegistry

        store = DiscoveryRegistry(self.registry)
        grouped: dict[tuple[str, str, str, str], list[dict[str, Any]]] = {}
        for link in links:
            if str(link.get("certification_status") or "") != "CERTIFIED":
                continue
            certified_link_id = str(link.get("certified_link_id") or "")
            if not certified_link_id:
                raise ValueError("CERTIFIED_LINK_ID_REQUIRED")
            target = self.child_discovery.repo.certified_target(
                certified_link_id
            )
            source_pdf_id = str(
                target.get("source_pdf_id")
                or link.get("pdf_id")
                or ""
            )
            source_path = self._source_path(
                link,target,source_pdf_map=source_pdf_map,
            )
            anchor_id = str(link.get("anchor_id") or "")
            if not anchor_id:
                raise ValueError("CERTIFIED_ANCHOR_ID_REQUIRED")
            member_table = str(
                link.get("member_table_id")
                or target.get("member_table_id")
                or ""
            )
            statement_scope = str(
                link.get("statement_scope")
                or target.get("statement_scope")
                or scope
                or "UNKNOWN"
            )
            family = str(link.get("table_family_id") or "")
            group_key = (source_pdf_id, anchor_id, family, statement_scope)
            grouped.setdefault(group_key, []).append({
                "link":dict(link),
                "target":dict(target),
                "source_path":source_path,
                "member_table":member_table,
                "certified_link_id":certified_link_id,
            })

        plans: list[dict[str, Any]] = []
        for (source_pdf_id, anchor_id, family, statement_scope), siblings in grouped.items():
            # The Anchor occurrence is the source of statement evidence.  A
            # link may carry a display label but cannot substitute the source
            # table title, page or parent/child evidence.
            occurrence = store.get_occurrence(anchor_id) or {}
            first_link = siblings[0]["link"]
            portfolio_execution_plan: dict[str, Any] | None = None
            if (
                family == "investment_portfolio"
                or str(first_link.get("research_definition_id") or "")
                == "INVESTMENT_PORTFOLIO_V2"
            ):
                from portfolio_topology_execution_plan import (
                    build_portfolio_topology_execution_plan,
                    evaluate_portfolio_certification_readiness,
                )

                if not occurrence:
                    raise PermissionError(
                        "PORTFOLIO_TOPOLOGY_OCCURRENCE_REQUIRED:"
                        + anchor_id
                    )
                portfolio_execution_plan = (
                    build_portfolio_topology_execution_plan(occurrence)
                )
                readiness = evaluate_portfolio_certification_readiness(
                    portfolio_execution_plan,
                    [entry["link"] for entry in siblings],
                )
                if readiness["status"] != "READY_FOR_CAPTURE_PLAN":
                    details = [
                        *list(readiness.get("blocking_issue_codes") or []),
                        *list(readiness.get("missing_target_ids") or []),
                    ]
                    raise PermissionError(
                        "PORTFOLIO_TOPOLOGY_CERTIFICATION_INCOMPLETE:"
                        + ",".join(dict.fromkeys(str(value) for value in details))
                    )
            source_path = next(
                (entry["source_path"] for entry in siblings if entry["source_path"]),
                "",
            )
            definition_id = str(
                first_link.get("research_definition_id")
                or definition.get("definition_id")
                or ""
            )
            definition_version = str(
                first_link.get("definition_version")
                or definition.get("definition_version")
                or ""
            )
            identity = {
                "source_pdf_id":source_pdf_id,
                "anchor_occurrence_id":anchor_id,
                "table_family":family,
                "scope":statement_scope,
                "research_definition_id":definition_id,
                "definition_version":definition_version,
                # A plan is an immutable snapshot of the certified target
                # inventory.  Reusing the old family-only ID after links were
                # added made ensure_capture_plan() return stale items and
                # silently omitted valid primary tables from Stage B.
                "certified_target_ids":sorted(
                    str(entry["certified_link_id"]) for entry in siblings
                ),
            }
            plan_id = "PLAN_STRICT_" + hashlib.sha256(
                json.dumps(identity, ensure_ascii=False, sort_keys=True).encode("utf-8")
            ).hexdigest()[:24]
            anchor_member = str(
                occurrence.get("display_name")
                or first_link.get("source_parent_table_id")
                or family
                or anchor_id
            )
            anchor = {
                "member_table":anchor_member,
                "member_table_role":"STATEMENT_ANCHOR",
                "source_table_title":str(
                    occurrence.get("source_table_title")
                    or first_link.get("source_table_title")
                    or ""
                ),
                "scope":str(occurrence.get("scope") or statement_scope),
                "statement_type":str(occurrence.get("statement_type") or "UNKNOWN"),
                "statement_pdf_page_index":occurrence.get("statement_pdf_page_index"),
                "statement_printed_page":occurrence.get("statement_printed_page"),
                "parent_text":occurrence.get("parent_text") or anchor_member,
                "child_rows":list(occurrence.get("child_rows") or []),
                "machine_evidence":dict(occurrence.get("evidence") or {}),
            }
            items: list[dict[str, Any]] = [{
                "member_table":anchor_member,
                "member_table_role":"STATEMENT_ANCHOR",
                "capture_mode":"MATERIALIZE_ANCHOR",
                "capture_order":0,
                "source_pdf_page_index":anchor.get("statement_pdf_page_index"),
                "source_printed_page":anchor.get("statement_printed_page"),
                "status":"READY",
            }]
            seen_links: set[str] = set()
            def _strict_link_order(entry: dict[str, Any]) -> tuple[int,int,int,str,str]:
                link = entry["link"]
                target = entry["target"]
                classification = str(
                    target.get("table_classification")
                    or link.get("table_classification")
                    or "PRIMARY_TABLE"
                ).strip().upper()
                classification_order = {
                    "PRIMARY_TABLE": 0,
                    "CONTINUATION_SEGMENT": 1,
                    "SUPPLEMENTARY_TABLE": 2,
                    "PEER_TABLE": 3,
                    "UNRESOLVED": 4,
                }.get(classification,5)
                raw_table_order = link.get("member_table_order")
                if raw_table_order is None:
                    raw_table_order = target.get("member_table_order")
                try:
                    table_order = int(raw_table_order)
                except (TypeError,ValueError):
                    table_order = 10_000
                raw_page = (
                    target.get("confirmed_note_pdf_page_index")
                    or target.get("candidate_note_pdf_page_index")
                )
                try:
                    page_order = int(raw_page)
                except (TypeError,ValueError):
                    page_order = 10_000
                return (
                    classification_order,
                    table_order,
                    page_order,
                    str(entry["member_table"]),
                    str(entry["certified_link_id"]),
                )

            ordered_siblings = sorted(siblings,key=_strict_link_order)
            for order, entry in enumerate(ordered_siblings, start=1):
                if entry["certified_link_id"] in seen_links:
                    continue
                seen_links.add(entry["certified_link_id"])
                target = entry["target"]
                items.append({
                    "member_table":entry["member_table"],
                    "member_table_role":"NOTE_DETAIL",
                    "capture_mode":(
                        "DIRECT_PORTFOLIO_TABLE"
                        if str(entry["link"].get("relation_type") or "")
                        == "DIRECT_PORTFOLIO_WHOLE_TABLE"
                        else "NOTE_DETAIL"
                    ),
                    "capture_order":order,
                    "note_reference":target.get("note_reference"),
                    "candidate_note_pdf_page_index":target.get("candidate_note_pdf_page_index"),
                    "confirmed_note_pdf_page_index":target.get("confirmed_note_pdf_page_index"),
                    "status":"READY",
                    "certified_note_target":{
                        **target,
                        "member_table_id":entry["member_table"],
                        "status":"CERTIFIED_NOTE_TARGET",
                        "certified_note_target_id":entry["certified_link_id"],
                    },
                })
            plans.append({
                "plan_id":plan_id,
                "status":"CERTIFIED",
                "plan_status":"CERTIFIED",
                "entry_origin":"STRICT",
                "anchor_occurrence_id":anchor_id,
                "pdf_id":source_pdf_id,
                "source_pdf_id":source_pdf_id,
                "source_pdf_path":source_path,
                "table_family":family,
                "research_definition_id":definition_id,
                "definition_version":definition_version,
                "company":(
                    occurrence.get("normalized_company")
                    or occurrence.get("company")
                    or first_link.get("company")
                ),
                "report_year":(
                    occurrence.get("report_year")
                    or first_link.get("report_year")
                ),
                "anchor":anchor,
                "items":items,
                "portfolio_topology_execution_plan":portfolio_execution_plan,
            })
        return plans

    def _normalise_plan_context(
        self,plan: dict[str, Any], *,
        source_pdf_map: dict[str, Path] | None,
        research_definition: dict[str, Any] | None,
    ) -> dict[str, Any]:
        out = dict(plan)
        definition = dict(research_definition or {})
        out.setdefault(
            "research_definition_id",
            definition.get("definition_id")
            or definition.get("research_definition_id")
            or "",
        )
        out.setdefault(
            "definition_version",
            definition.get("definition_version") or "",
        )
        if not out.get("source_pdf_path"):
            source_id = str(
                out.get("source_pdf_id") or out.get("pdf_id") or ""
            )
            candidate = (source_pdf_map or {}).get(source_id)
            if candidate:
                out["source_pdf_path"] = str(Path(candidate))
        return out

    @staticmethod
    def _source_path(
        link: dict[str, Any],target: dict[str, Any], *,
        source_pdf_map: dict[str, Path] | None,
    ) -> str:
        direct = link.get("pdf_path") or target.get("source_pdf_path")
        if direct:
            return str(Path(str(direct)))
        source_id = str(
            target.get("source_pdf_id") or link.get("pdf_id") or ""
        )
        mapped = (source_pdf_map or {}).get(source_id)
        return str(Path(mapped)) if mapped else ""

    def _execution_session_row(self,session_key: str):
        if not self.registry:
            return None
        with self.registry.connect() as conn:
            return conn.execute(
                """SELECT * FROM stage_b_execution_sessions
                   WHERE session_key=?""",
                (session_key,),
            ).fetchone()

    def _attach_once(
        self,research_batch_id: str, *, plan_id: str | None = None,
        source_batch_id: str | None = None,role: str,
    ) -> None:
        with self.registry.connect() as conn:
            exists = conn.execute(
                """SELECT 1 FROM research_batch_members
                   WHERE research_batch_id=?
                     AND COALESCE(plan_id,'')=?
                     AND COALESCE(source_batch_id,'')=?
                     AND role=?""",
                (
                    research_batch_id,str(plan_id or ""),
                    str(source_batch_id or ""),role,
                ),
            ).fetchone()
        if not exists:
            self.research_batch.attach(
                research_batch_id,plan_id=plan_id,
                source_batch_id=source_batch_id,role=role,
            )

    def _submitted_plan_ids(self,batch_ids: list[str]) -> set[str]:
        if not self.registry or not batch_ids:
            return set()
        placeholders=",".join("?" for _ in batch_ids)
        with self.registry.connect() as conn:
            rows=conn.execute(
                f"""SELECT payload_json FROM jobs
                    WHERE batch_id IN ({placeholders})""",
                tuple(batch_ids),
            ).fetchall()
        submitted=set()
        for row in rows:
            payload=json.loads(row["payload_json"] or "{}")
            plan_id=str(
                payload.get("capture_plan_id")
                or (
                    (payload.get("capture_request") or {})
                    .get("request_metadata") or {}
                ).get("capture_plan_id")
                or ""
            )
            if plan_id:
                submitted.add(plan_id)
        return submitted

    @staticmethod
    def _now() -> str:
        from metadata_registry import now_iso
        return now_iso()

    @staticmethod
    def _resolve_plan_pdf(plan: dict[str, Any]) -> Path | None:
        """Resolve a PDF path from a capture plan."""
        source = plan.get("source_pdf_path") or plan.get("source_pdf")
        if source:
            p = Path(source)
            if p.is_file():
                return p
        # Try alternative keys
        for key in ("pdf_path", "anchor_pdf_path", "source_pdf_id"):
            val = plan.get(key)
            if val:
                p = Path(str(val))
                if p.is_file():
                    return p
        return None
