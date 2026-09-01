"""Immutable Capture-version revisions used by the unified inspection panel."""
from __future__ import annotations

import datetime as dt
import json
import shutil
import uuid
from pathlib import Path
from typing import Any

from registry_bridge import sync_capture_run


class CaptureVersionService:
    def __init__(self, governance_repository, capture_repository, review_inbox_service, paths, producer_version: str):
        self.repo=governance_repository
        self.capture_repo=capture_repository
        self.inbox=review_inbox_service
        self.paths=paths
        self.producer_version=producer_version

    def detail(self, capture_id: str):
        return self.repo.capture_detail(capture_id)

    def versions(self, logical_asset_id: str):
        return self.repo.capture_versions(logical_asset_id)

    def bundle(self, capture_id: str):
        return self.repo.bundle_detail(capture_id)

    def review_history(self, capture_id: str):
        return self.repo.review_history(capture_id)

    def usage(self, capture_id: str):
        return self.repo.asset_usage(capture_id)

    def create_structure_revision(
        self, *, capture_id: str, revision_type: str, payload: dict[str,Any],
        actor: str = "USER", table_block_id: str | None = None,
    ) -> dict[str,Any]:
        """Create a new version while preserving the old machine evidence."""
        source=self.repo.capture_detail(capture_id)
        if not source: raise KeyError(capture_id)
        if source["asset_status"] in {"SUPERSEDED","INVALIDATED","TRASHED","ARCHIVED"}:
            raise PermissionError("HISTORICAL_VERSION_READONLY")
        run=Path(str(source.get("run_path") or ""))
        if not run.is_dir(): raise FileNotFoundError(run)
        new_id=f"{run.name}__revision_{dt.datetime.now().strftime('%Y%m%dT%H%M%S')}_{uuid.uuid4().hex[:6]}"
        target=run.with_name(new_id)
        shutil.copytree(run,target)
        revision={
            "revision_type":revision_type,"payload":payload,"actor":actor,
            "source_capture_id":capture_id,"table_block_id":table_block_id,
            "created_at":dt.datetime.now().astimezone().isoformat(timespec="seconds"),
        }
        (target/"human_structure_revision.json").write_text(
            json.dumps(revision,ensure_ascii=False,indent=2),encoding="utf-8"
        )
        metadata_path=target/"capture_metadata.json"
        metadata=json.loads(metadata_path.read_text(encoding="utf-8")) if metadata_path.exists() else {}
        metadata.update({"run_id":new_id,"structure_revision":revision,"producer_version":self.producer_version})
        metadata_path.write_text(json.dumps(metadata,ensure_ascii=False,indent=2),encoding="utf-8")
        if revision_type=="IDENTITY_OVERRIDE":
            result_path=target/"table_capture_result.json"
            if result_path.is_file():
                result=json.loads(result_path.read_text(encoding="utf-8"))
                if payload.get("currency_unit"):
                    result["unit"]=payload["currency_unit"]
                    context=dict(result.get("document_context") or {})
                    context["currency_unit"]=payload["currency_unit"]
                    context["human_override_source"]="IDENTITY_OVERRIDE"
                    result["document_context"]=context
                result_path.write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding="utf-8")
        sync=sync_capture_run(target)
        # registry_bridge normally registers the copied run in production. A
        # repository-local fallback keeps the transaction correct in tests and
        # alternate DATA_HOME deployments without guessing financial data.
        if sync.get("status")!="OK":
            raise RuntimeError(f"REVISION_REGISTRY_SYNC_FAILED:{sync}")
        if self.capture_repo.get(new_id) is None:
            with self.repo.registry.connect() as conn:
                original=conn.execute("SELECT * FROM captures WHERE capture_id=?",(capture_id,)).fetchone()
                if not original: raise RuntimeError("SOURCE_CAPTURE_REGISTRY_RECORD_MISSING")
                record=dict(original)
                record.update({
                    "capture_id":new_id,"run_path":str(target),
                    "producer_version":self.producer_version,
                    "created_at":revision["created_at"],"updated_at":revision["created_at"],
                })
                columns=[row["name"] for row in conn.execute("PRAGMA table_info(captures)").fetchall()]
                names=[name for name in columns if name in record]
                conn.execute(
                    f"INSERT INTO captures({','.join(names)}) VALUES({','.join('?' for _ in names)})",
                    tuple(record[name] for name in names),
                )
        target_logical_asset_id=source["logical_asset_id"]
        if revision_type=="IDENTITY_OVERRIDE":
            identity={
                "company_id":source.get("company_id"),"filing_type":source.get("filing_type"),
                "report_year":source.get("report_year"),"statement_scope":source.get("statement_scope"),
                "research_project_id":source.get("research_project_id"),
                "research_task_id":source.get("research_task_id"),
                "research_batch_id":source.get("research_batch_id"),
                "research_definition_id":source.get("research_definition_id"),
                "definition_version":source.get("definition_version"),
                "table_family_id":source.get("table_family_id"),
                "member_table_id":source.get("member_table_id"),
                "logical_source_role":source.get("logical_source_role"),
            }
            identity.update({k:v for k,v in payload.items() if v not in {None,"","保持机器结果"}})
            target_logical_asset_id=self.repo.get_or_create_logical_asset(
                identity | {"derivation_evidence":{
                    "source_capture_id":capture_id,"revision_type":revision_type,
                    "human_identity_override":payload,
                }}
            )["logical_asset_id"]
        version=self.repo.register_capture_version(
            logical_asset_id=target_logical_asset_id,capture_id=new_id,
            producer_version=self.producer_version,processing_status="COMPLETED",
            registration_status="REGISTERED",quality_status="REVIEW_REQUIRED",
            review_status="PENDING",certified=False,
        )
        revision_id="SREV_"+uuid.uuid4().hex
        with self.repo.registry.connect() as conn:
            if table_block_id:
                source_block=conn.execute(
                    """SELECT tb.*,cbc.bundle_id,cbc.child_order
                       FROM table_blocks tb JOIN capture_bundle_children cbc ON cbc.block_id=tb.block_id
                       WHERE tb.block_id=? AND cbc.capture_id=?""",
                    (table_block_id,capture_id),
                ).fetchone()
                if source_block:
                    source_block=dict(source_block)
                    new_block_id="BLOCKREV_"+uuid.uuid4().hex
                    evidence=json.loads(source_block.get("evidence_json") or "{}")
                    evidence["human_revision"]={"revision_id":revision_id,"revision_type":revision_type,"payload":payload}
                    conn.execute(
                        """INSERT INTO table_blocks(
                            block_id,container_id,block_order,block_title,block_role,start_pdf_page,
                            end_pdf_page,bbox_json,header_topology_json,semantic_graph_json,
                            reconciliation_json,quality_status,status,evidence_json,created_at
                        ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                        (new_block_id,source_block["container_id"],source_block["block_order"],
                         source_block["block_title"],source_block["block_role"],
                         source_block["start_pdf_page"],source_block["end_pdf_page"],
                         source_block["bbox_json"],source_block["header_topology_json"],
                         source_block["semantic_graph_json"],source_block["reconciliation_json"],
                         "REVIEW_REQUIRED","REVIEW_REQUIRED",
                         json.dumps(evidence,ensure_ascii=False),revision["created_at"]),
                    )
                    conn.execute(
                        "UPDATE capture_bundle_children SET status='SUPERSEDED' WHERE bundle_id=? AND block_id=? AND capture_id=?",
                        (source_block["bundle_id"],table_block_id,capture_id),
                    )
                    conn.execute(
                        """INSERT INTO capture_bundle_children(
                            bundle_id,block_id,capture_id,logical_asset_id,child_order,status,payload_json,created_at
                        ) VALUES(?,?,?,?,?,'REVIEW_REQUIRED',?,?)""",
                        (source_block["bundle_id"],new_block_id,new_id,source["logical_asset_id"],
                         source_block["child_order"],json.dumps({"revision_id":revision_id},ensure_ascii=False),
                         revision["created_at"]),
                    )
            conn.execute(
                """INSERT INTO structure_revisions(
                    revision_id,logical_asset_id,source_capture_id,new_capture_id,
                    table_block_id,revision_type,actor,payload_json,created_at
                ) VALUES(?,?,?,?,?,?,?,?,?)""",
                (revision_id,target_logical_asset_id,capture_id,new_id,table_block_id,
                 revision_type,actor,json.dumps(payload,ensure_ascii=False),revision["created_at"]),
            )
        self.repo.recalculate_bundle_status(new_id)
        self.inbox.route(
            logical_asset_id=target_logical_asset_id,capture_id=new_id,
            reasons=["STRUCTURE_REVIEW_REQUIRED"],
            evidence={"revision_id":revision_id,"source_capture_id":capture_id,
                      "revision_type":revision_type,"table_block_id":table_block_id},
        )
        return {"revision_id":revision_id,"new_capture_id":new_id,
                "logical_asset_id":target_logical_asset_id,"capture_version":version}
