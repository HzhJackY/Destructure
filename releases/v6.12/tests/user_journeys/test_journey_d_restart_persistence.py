"""Journey D: Stage B state survives a fresh application service instance."""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT))

from discovery_registry import DiscoveryRegistry
from metadata_registry import MetadataRegistry,now_iso
from services.child_capture_execution_service import ChildCaptureExecutionService
from services.research_batch_service import ResearchBatchService


class _RegistryRunner:
    def __init__(self,registry):
        self.registry=registry

    def monitor(self,batch_id):
        with self.registry.connect() as conn:
            rows=conn.execute(
                "SELECT status FROM jobs WHERE batch_id=?",(batch_id,)
            ).fetchall()
        counts={}
        for row in rows:
            counts[row["status"]]=counts.get(row["status"],0)+1
        terminal={"SUCCESS","REVIEW_REQUIRED","FAILED","CANCELLED","SKIPPED"}
        complete=sum(counts.get(status,0) for status in terminal)
        return {
            "batch_id":batch_id,
            "total":len(rows),
            "complete":complete,
            "progress":complete/len(rows) if rows else 1.0,
            "counts":counts,
            "jobs":[],
        }

    def retry_failed(self,*,batch_id,max_workers=3):
        return []


def test_stage_b_execution_restores_from_db_after_new_service_instance(
    tmp_path,
):
    db_path=tmp_path/"metadata.db"
    registry=MetadataRegistry(db_path)
    plan={
        "plan_id":"PLAN_RESTART_FIXTURE",
        "status":"CERTIFIED",
        "anchor_occurrence_id":"ANCHOR_RESTART_FIXTURE",
        "pdf_id":"PDF_RESTART_FIXTURE",
        "source_pdf_path":str(tmp_path/"fixture.pdf"),
        "table_family":"family_fixture",
        "anchor":{"member_table":"anchor_fixture","scope":"CONSOLIDATED"},
        "items":[{
            "member_table":"member_fixture",
            "member_table_role":"NOTE_DETAIL",
            "capture_mode":"NOTE_DETAIL",
            "capture_order":1,
            "status":"READY",
            "confirmed_note_pdf_page_index":1,
            "certified_note_target":{"status":"CERTIFIED_NOTE_TARGET"},
        }],
    }
    DiscoveryRegistry(registry).save_capture_plan(plan)
    research=ResearchBatchService(registry).create(
        display_name="restart_fixture",
        table_family="family_fixture",
        payload={"stage":"CERTIFIED_CAPTURE_PLAN"},
    )
    research_batch_id=research["research_batch_id"]
    batch_id="BATCH_RESTART_FIXTURE"
    batch=ResearchBatchService(registry)
    batch.attach(research_batch_id,plan_id=plan["plan_id"],role="PLAN")
    batch.attach(
        research_batch_id,source_batch_id=batch_id,role="SOURCE_BATCH"
    )
    session_key="STAGEB_RESTART_FIXTURE"
    now=now_iso()
    with registry.connect() as conn:
        conn.execute(
            """INSERT INTO stage_b_execution_sessions(
               session_key,entry_origin,display_name,scope,
               research_definition_id,definition_version,status,
               research_batch_id,plan_ids_json,batch_ids_json,
               callback_key,workspace_route,workspace_filter_json,
               created_at,updated_at
               ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                session_key,"UNIFIED","restart_fixture","CONSOLIDATED",
                "","", "EXECUTING",research_batch_id,
                json.dumps([plan["plan_id"]]),json.dumps([batch_id]),
                "GuidedCaptureService.execute","逻辑资产工作区",
                json.dumps({"research_batch_id":research_batch_id}),
                now,now,
            ),
        )
        conn.execute(
            """INSERT INTO jobs(
               job_id,batch_id,job_type,status,progress,payload_json,
               result_json,created_at,updated_at
               ) VALUES(?,?,?,'SUCCESS',1,?,'{}',?,?)""",
            (
                "JOB_RESTART_FIXTURE",batch_id,"TABLE_CAPTURE",
                json.dumps({"capture_plan_id":plan["plan_id"]}),now,now,
            ),
        )

    # A new Registry and service object models an application process restart.
    reopened=MetadataRegistry(db_path)
    service=ChildCaptureExecutionService(
        registry=reopened,
        capture_service=None,
        table_capture_runner=_RegistryRunner(reopened),
        research_batch_service=ResearchBatchService(reopened),
    )
    restored=service.restore_execution(session_key)

    assert restored["research_batch_id"]==research_batch_id
    assert restored["batch_ids"]==[batch_id]
    assert restored["plan_ids"]==[plan["plan_id"]]
    assert restored["plans"][0]["plan_id"]==plan["plan_id"]
    assert restored["progress"][0]["进度"]=="100%"
    assert restored["all_terminal"] is True
    assert restored["workspace_filter"]=={
        "research_batch_id":research_batch_id,
    }


def test_journey_d_never_reads_or_creates_production_data_home():
    source=Path(__file__).read_text(encoding="utf-8")
    assert "Path." + "home()" not in source
    assert "FinancialMetric" + "ResolverData" not in source
