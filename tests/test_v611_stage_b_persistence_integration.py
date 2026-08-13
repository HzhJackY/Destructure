"""v6.11 Stage B persistent, unified execution flow integration tests."""
from __future__ import annotations

import copy
import json
import sqlite3
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))

from metadata_registry import MetadataRegistry,now_iso
from capture_models import CaptureMode,CaptureRequest
from discovery_strategies import CertifiedTargetStrategy
from repositories.asset_governance_repository import AssetGovernanceRepository
from services.child_capture_execution_service import ChildCaptureExecutionService
from services.guided_capture_service import GuidedCaptureService
from services.research_batch_service import ResearchBatchService


class _FakeRunner:
    def __init__(self,registry):
        self.registry=registry

    def monitor(self,batch_id):
        with self.registry.connect() as conn:
            jobs=[
                dict(row) for row in conn.execute(
                    "SELECT * FROM jobs WHERE batch_id=? ORDER BY job_id",
                    (batch_id,),
                ).fetchall()
            ]
        counts={}
        for job in jobs:
            counts[job["status"]]=counts.get(job["status"],0)+1
        terminal={"SUCCESS","REVIEW_REQUIRED","FAILED","CANCELLED","SKIPPED"}
        complete=sum(counts.get(status,0) for status in terminal)
        return {
            "batch_id":batch_id,
            "total":len(jobs),
            "complete":complete,
            "progress":complete/len(jobs) if jobs else 1.0,
            "counts":counts,
            "jobs":jobs,
        }

    def retry_failed(self,*,batch_id,max_workers=3):
        return []


class _FakeGuidedCapture:
    """The one callback both Stage B adapters must use."""

    def __init__(self,registry):
        self.registry=registry
        self.calls=[]

    def execute(
        self,plan,*,pdf_path,research_batch_id,batch_id=None,
        max_workers=3,options=None,
    ):
        call_index=len(self.calls)+1
        batch_id=batch_id or f"BATCH_FIXTURE_{call_index}"
        job_id=f"JOB_FIXTURE_{call_index}"
        now=now_iso()
        detail=next(
            item for item in plan["items"]
            if item.get("member_table_role")=="NOTE_DETAIL"
        )
        payload={
            "capture_plan_id":plan["plan_id"],
            "plan_member_table":detail["member_table"],
            "capture_request":{
                "request_metadata":{"capture_plan_id":plan["plan_id"]},
            },
        }
        with self.registry.connect() as conn:
            conn.execute(
                """INSERT INTO jobs(
                   job_id,batch_id,job_type,status,progress,payload_json,
                   result_json,created_at,updated_at
                   ) VALUES(?,?,?,'QUEUED',0,?,'{}',?,?)""",
                (
                    job_id,batch_id,"TABLE_CAPTURE",
                    json.dumps(payload,ensure_ascii=False),now,now,
                ),
            )
        self.calls.append({
            "plan_id":plan["plan_id"],
            "pdf_path":str(pdf_path),
            "research_batch_id":research_batch_id,
            "callback":"GuidedCaptureService.execute",
            "options":dict(options or {}),
        })
        return {
            "research_batch_id":research_batch_id,
            "batch_id":batch_id,
            "jobs":[{"job_id":job_id,"batch_id":batch_id}],
            "blocked_items":[],
        }


class _StrictRepo:
    def certified_target(self,certified_link_id):
        return {
            "certified_link_id":certified_link_id,
            "source_pdf_id":"PDF_FIXTURE",
            "confirmed_note_pdf_page_index":1,
            "end_page":1,
            "target_heading":"明细表",
            "capture_query_title":"明细表",
            "member_table_id":"member_fixture",
            "logical_table_id":"LOGICAL_FIXTURE",
            "table_classification":"PRIMARY_TABLE",
            "segment_manifest_status":"CERTIFIED_SEGMENT_MANIFEST",
            "note_table_inventory_id":"INVENTORY_FIXTURE",
            "note_table_inventory_status":"COMPLETE",
            "certified_segments":[{
                "certified_segment_id":"CSEG_FIXTURE",
                "order":0,
                "classification":"PRIMARY_TABLE",
                "start_page":1,
                "end_page":1,
                "certification_status":"CERTIFIED",
            }],
            "note_reference":"NOTE_FIXTURE",
            "statement_scope":"CONSOLIDATED",
            "confidence":1.0,
            "status":"CERTIFIED_NOTE_TARGET",
            "evidence":{"fixture":True},
        }


class _StrictDiscovery:
    def __init__(self):
        self.repo=_StrictRepo()


def _service(tmp_path):
    registry=MetadataRegistry(tmp_path/"metadata.db")
    with registry.connect() as conn:
        conn.execute(
            """INSERT INTO certified_note_table_inventories(
               note_table_inventory_id,note_table_inventory_candidate_id,
               source_pdf_id,source_pdf_sha256,note_reference,note_title,
               scan_start_page,scan_end_page,next_note_boundary_page,
               logical_table_ids_json,inventory_snapshot_json,
               inventory_status,certification_method,certification_status,
               reviewer,certified_at,producer_version,created_at
               ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                "INVENTORY_FIXTURE",None,"PDF_FIXTURE","SHA_FIXTURE",
                "NOTE_FIXTURE","明细表",1,1,2,
                '["LOGICAL_FIXTURE"]','{"fixture":true}',"COMPLETE",
                "HUMAN_CONFIRMED","CERTIFIED","reviewer",now_iso(),
                "v6.11",now_iso(),
            ),
        )
    guided=_FakeGuidedCapture(registry)
    svc=ChildCaptureExecutionService(
        registry=registry,
        capture_service=None,
        table_capture_runner=_FakeRunner(registry),
        research_batch_service=ResearchBatchService(registry),
        guided_capture_service=guided,
        hierarchical_child_discovery_service=_StrictDiscovery(),
    )
    return registry,guided,svc


def _pdf(tmp_path):
    path=tmp_path/"fixture.pdf"
    path.write_bytes(b"%PDF-fixture")
    return path


def _strict_link(pdf_path):
    return {
        "certified_link_id":"CLINK_FIXTURE",
        "anchor_id":"ANCHOR_FIXTURE",
        "anchor_child_id":"ANCHOR_CHILD_FIXTURE",
        "table_family_id":"family_fixture",
        "member_table_id":"member_fixture",
        "statement_scope":"CONSOLIDATED",
        "research_definition_id":"DEFINITION_FIXTURE",
        "definition_version":"VERSION_FIXTURE",
        "pdf_id":"PDF_FIXTURE",
        "pdf_path":str(pdf_path),
        "certification_status":"CERTIFIED",
    }


def _compat_plan(pdf_path):
    return {
        "plan_id":"PLAN_COMPAT_FIXTURE",
        "status":"CERTIFIED",
        "plan_status":"CERTIFIED",
        "anchor_occurrence_id":"OCCURRENCE_FIXTURE",
        "pdf_id":"PDF_FIXTURE",
        "source_pdf_id":"PDF_FIXTURE",
        "source_pdf_path":str(pdf_path),
        "table_family":"family_fixture",
        "research_definition_id":"DEFINITION_FIXTURE",
        "definition_version":"VERSION_FIXTURE",
        "anchor":{
            "member_table":"anchor_fixture",
            "scope":"CONSOLIDATED",
            "source_table_title":"主表",
        },
        "items":[
            {
                "member_table":"anchor_fixture",
                "member_table_role":"STATEMENT_ANCHOR",
                "capture_mode":"MATERIALIZE_ANCHOR",
                "capture_order":0,
                "status":"READY",
            },
            {
                "member_table":"member_fixture",
                "member_table_role":"NOTE_DETAIL",
                "capture_mode":"NOTE_DETAIL",
                "capture_order":1,
                "note_reference":"NOTE_FIXTURE",
                "confirmed_note_pdf_page_index":1,
                "status":"READY",
                "certified_note_target":{
                    "status":"CERTIFIED_NOTE_TARGET",
                    "source_pdf_id":"PDF_FIXTURE",
                    "target_heading":"明细表",
                    "capture_query_title":"明细表",
                    "confirmed_note_pdf_page_index":1,
                    "note_reference":"NOTE_FIXTURE",
                    "member_table_id":"member_fixture",
                    "logical_table_id":"LOGICAL_FIXTURE",
                    "table_classification":"PRIMARY_TABLE",
                    "segment_manifest_status":"CERTIFIED_SEGMENT_MANIFEST",
                    "note_table_inventory_id":"INVENTORY_FIXTURE",
                    "note_table_inventory_status":"COMPLETE",
                    "certified_segments":[{
                        "certified_segment_id":"CSEG_FIXTURE",
                        "order":0,
                        "classification":"PRIMARY_TABLE",
                        "start_page":1,
                        "end_page":1,
                        "certification_status":"CERTIFIED",
                    }],
                },
            },
        ],
    }


def _supplementary_item(source_item):
    item=copy.deepcopy(source_item)
    item["member_table"]="supplementary_fixture"
    item["capture_order"]=2
    target=item["certified_note_target"]
    target["certified_link_id"]="CLINK_SUPPLEMENTARY"
    target["member_table_id"]="supplementary_fixture"
    target["logical_table_id"]="LOGICAL_SUPPLEMENTARY"
    target["table_classification"]="SUPPLEMENTARY_TABLE"
    target["certified_segments"]=[{
        "certified_segment_id":"CSEG_SUPPLEMENTARY",
        "order":0,
        "classification":"SUPPLEMENTARY_TABLE",
        "start_page":1,
        "end_page":1,
        "certification_status":"CERTIFIED",
    }]
    return item


def _append_continuation(target, *, segment_id, parent_id):
    target["certified_segments"].append({
        "certified_segment_id":segment_id,
        "order":len(target["certified_segments"]),
        "classification":"CONTINUATION_SEGMENT",
        "continuation_of_segment_id":parent_id,
        "start_page":2,
        "end_page":2,
        "certification_status":"CERTIFIED",
    })


def test_v1_primary_only_keeps_legacy_primary_and_excludes_supplementary(
    tmp_path,
):
    _,_,svc=_service(tmp_path)
    plan=_compat_plan(_pdf(tmp_path))
    primary=plan["items"][1]
    primary_target=primary["certified_note_target"]
    primary_target["segment_manifest_status"]="LEGACY_PRIMARY_ANCHOR_ONLY"
    primary_target["note_table_inventory_status"]="LEGACY_UNVERIFIED"
    primary_target["certified_segments"]=[]
    plan["items"].append(_supplementary_item(primary))

    scoped=svc._plan_for_capture_scope(
        plan,{
            "capture_scope_contract_version":1,
            "capture_scope_policy":"PRIMARY_ONLY",
        },
    )

    details=[
        item for item in scoped["items"]
        if item.get("member_table_role")=="NOTE_DETAIL"
    ]
    assert [item["member_table"] for item in details]==["member_fixture"]
    assert details[0]["status"]=="READY"
    assert scoped["certified_scope_selection"]["excluded_items"][0][
        "exclusion_reason"
    ]=="EXCLUDED_BY_CAPTURE_SCOPE_POLICY"


def test_v2_primary_only_includes_full_primary_manifest(tmp_path):
    _,_,svc=_service(tmp_path)
    plan=_compat_plan(_pdf(tmp_path))
    primary=plan["items"][1]
    _append_continuation(
        primary["certified_note_target"],
        segment_id="CSEG_FIXTURE_CONTINUATION",
        parent_id="CSEG_FIXTURE",
    )
    plan["items"].append(_supplementary_item(primary))

    scoped=svc._plan_for_capture_scope(
        plan,{
            "capture_scope_contract_version":2,
            "capture_scope_policy":"PRIMARY_ONLY",
            "selected_logical_table_ids":[],
        },
    )

    details=[
        item for item in scoped["items"]
        if item.get("member_table_role")=="NOTE_DETAIL"
    ]
    assert [item["member_table"] for item in details]==["member_fixture"]
    assert details[0]["status"]=="READY"
    assert [
        segment["certified_segment_id"]
        for segment in details[0]["certified_note_target"]["certified_segments"]
    ]==["CSEG_FIXTURE"]
    assert [
        segment["certified_segment_id"]
        for segment in details[0]["certified_note_target"][
            "excluded_certified_segments"
        ]
    ]==["CSEG_FIXTURE_CONTINUATION"]
    assert scoped["certified_scope_selection"]["excluded_items"][0][
        "exclusion_reason"
    ]=="EXCLUDED_BY_LOGICAL_TABLE_SELECTION"


def test_v2_missing_explicit_logical_identity_is_not_treated_as_primary(
    tmp_path,
):
    _,_,svc=_service(tmp_path)
    plan=_compat_plan(_pdf(tmp_path))
    target=plan["items"][1]["certified_note_target"]
    target.pop("logical_table_id")
    target.pop("table_classification")

    scoped=svc._plan_for_capture_scope(
        plan,{
            "capture_scope_contract_version":2,
            "capture_scope_policy":"PRIMARY_ONLY",
            "selected_logical_table_ids":[],
        },
    )

    detail=next(
        item for item in scoped["items"]
        if item.get("member_table_role")=="NOTE_DETAIL"
    )
    assert detail["status"]=="REVIEW_REQUIRED"
    assert set(detail["blocking_issue_codes"])=={
        "CERTIFIED_LOGICAL_TABLE_REQUIRED",
        "CERTIFIED_PRIMARY_LOGICAL_TABLE_REQUIRED",
    }


def test_continuation_policy_blocks_legacy_manifest(tmp_path):
    _,_,svc=_service(tmp_path)
    plan=_compat_plan(_pdf(tmp_path))
    target=plan["items"][1]["certified_note_target"]
    target["segment_manifest_status"]="LEGACY_PRIMARY_ANCHOR_ONLY"
    target["certified_segments"]=[]

    scoped=svc._plan_for_capture_scope(
        plan,{
            "capture_scope_contract_version":1,
            "capture_scope_policy":"PRIMARY_WITH_CONTINUATIONS",
        },
    )
    detail=scoped["items"][1]

    assert detail["status"]=="REVIEW_REQUIRED"
    assert detail["blocking_issue_codes"]==[
        "CERTIFIED_SEGMENT_MANIFEST_REQUIRED"
    ]


def test_all_note_tables_requires_independent_certified_inventory(tmp_path):
    registry,_,svc=_service(tmp_path)
    plan=_compat_plan(_pdf(tmp_path))
    with registry.connect() as conn:
        conn.execute(
            "DELETE FROM certified_note_table_inventories "
            "WHERE note_table_inventory_id='INVENTORY_FIXTURE'"
        )

    scoped=svc._plan_for_capture_scope(
        plan,{
            "capture_scope_contract_version":1,
            "capture_scope_policy":"ALL_NOTE_TABLES",
        },
    )
    detail=scoped["items"][1]

    assert detail["status"]=="REVIEW_REQUIRED"
    assert "CERTIFIED_NOTE_TABLE_INVENTORY_REQUIRED" in detail[
        "blocking_issue_codes"
    ]


def test_all_note_tables_requires_exact_inventory_logical_table_set(tmp_path):
    registry,_,svc=_service(tmp_path)
    plan=_compat_plan(_pdf(tmp_path))
    with registry.connect() as conn:
        conn.execute(
            """UPDATE certified_note_table_inventories
               SET logical_table_ids_json=?
               WHERE note_table_inventory_id='INVENTORY_FIXTURE'""",
            ('["LOGICAL_FIXTURE","LOGICAL_SUPPLEMENTARY"]',),
        )

    missing=svc._plan_for_capture_scope(
        plan,{
            "capture_scope_contract_version":1,
            "capture_scope_policy":"ALL_NOTE_TABLES",
        },
    )
    assert "CERTIFIED_NOTE_TABLE_INVENTORY_REQUIRED" in missing["items"][1][
        "blocking_issue_codes"
    ]

    plan["items"].append(_supplementary_item(plan["items"][1]))
    complete=svc._plan_for_capture_scope(
        plan,{
            "capture_scope_contract_version":1,
            "capture_scope_policy":"ALL_NOTE_TABLES",
        },
    )
    details=[
        item for item in complete["items"]
        if item.get("member_table_role")=="NOTE_DETAIL"
    ]
    assert [item["status"] for item in details]==["READY","READY"]
    assert [
        item["certified_note_target"]["table_classification"]
        for item in details
    ]==["PRIMARY_TABLE","SUPPLEMENTARY_TABLE"]


def test_v2_selected_supplementary_includes_its_full_manifest(tmp_path):
    registry,_,svc=_service(tmp_path)
    plan=_compat_plan(_pdf(tmp_path))
    supplementary=_supplementary_item(plan["items"][1])
    _append_continuation(
        supplementary["certified_note_target"],
        segment_id="CSEG_SUPPLEMENTARY_CONTINUATION",
        parent_id="CSEG_SUPPLEMENTARY",
    )
    plan["items"].append(supplementary)
    with registry.connect() as conn:
        conn.execute(
            """UPDATE certified_note_table_inventories
               SET logical_table_ids_json=?
               WHERE note_table_inventory_id='INVENTORY_FIXTURE'""",
            ('["LOGICAL_FIXTURE","LOGICAL_SUPPLEMENTARY"]',),
        )

    scoped=svc._plan_for_capture_scope(
        plan,{
            "capture_scope_contract_version":2,
            "capture_scope_policy":"SELECTED_NOTE_TABLES",
            "selected_logical_table_ids":["LOGICAL_SUPPLEMENTARY"],
        },
    )

    details=[
        item for item in scoped["items"]
        if item.get("member_table_role")=="NOTE_DETAIL"
    ]
    assert [item["status"] for item in details]==["READY","READY"]
    assert [
        segment["certified_segment_id"]
        for segment in details[1]["certified_note_target"]["certified_segments"]
    ]==["CSEG_SUPPLEMENTARY","CSEG_SUPPLEMENTARY_CONTINUATION"]
    assert scoped["certified_scope_selection"]["selected_logical_table_ids"]==[
        "LOGICAL_SUPPLEMENTARY"
    ]


def test_v2_selected_supplementary_accepts_bare_inventory_note_ordinal(
    tmp_path,
):
    registry,_,svc=_service(tmp_path)
    plan=_compat_plan(_pdf(tmp_path))
    supplementary=_supplementary_item(plan["items"][1])
    supplementary["note_reference"]="附注十二-13"
    supplementary["certified_note_target"]["note_reference"]="附注十二-13"
    plan["items"].append(supplementary)
    with registry.connect() as conn:
        conn.execute(
            """UPDATE certified_note_table_inventories
               SET note_reference=?,logical_table_ids_json=?
               WHERE note_table_inventory_id='INVENTORY_FIXTURE'""",
            ('13','["LOGICAL_FIXTURE","LOGICAL_SUPPLEMENTARY"]'),
        )

    scoped=svc._plan_for_capture_scope(
        plan,{
            "capture_scope_contract_version":2,
            "capture_scope_policy":"SELECTED_NOTE_TABLES",
            "selected_logical_table_ids":["LOGICAL_SUPPLEMENTARY"],
        },
    )

    selected=next(
        item for item in scoped["items"]
        if (item.get("certified_note_target") or {}).get(
            "table_classification"
        )=="SUPPLEMENTARY_TABLE"
    )
    assert selected["status"]=="READY"
    assert not selected.get("blocking_issue_codes")


def test_request_level_selected_ids_do_not_block_an_individual_plan(tmp_path):
    registry,_,svc=_service(tmp_path)
    plan=_compat_plan(_pdf(tmp_path))
    supplementary=_supplementary_item(plan["items"][1])
    supplementary["certified_note_target"]["logical_table_id"]="LOGICAL_A"
    plan["items"].append(supplementary)
    with registry.connect() as conn:
        conn.execute(
            """UPDATE certified_note_table_inventories
               SET logical_table_ids_json=?
               WHERE note_table_inventory_id='INVENTORY_FIXTURE'""",
            ('["LOGICAL_FIXTURE","LOGICAL_A","LOGICAL_B"]',),
        )

    scoped=svc._plan_for_capture_scope(
        plan,{
            "capture_scope_contract_version":2,
            "capture_scope_policy":"SELECTED_NOTE_TABLES",
            "selected_logical_table_ids":["LOGICAL_A","LOGICAL_B"],
        },
        available_supplementary_ids={"LOGICAL_A","LOGICAL_B"},
    )

    details=[
        item for item in scoped["items"]
        if item.get("member_table_role")=="NOTE_DETAIL"
    ]
    assert [item["status"] for item in details]==["READY","READY"]
    assert scoped["certified_scope_selection"][
        "invalid_selected_logical_table_ids"
    ]==[]
    assert scoped["certified_scope_selection"][
        "selected_logical_table_ids"
    ]==["LOGICAL_A"]


def test_guided_capture_creates_one_job_per_selected_logical_target(tmp_path):
    registry,_,svc=_service(tmp_path)
    pdf_path=_pdf(tmp_path)
    plan=_compat_plan(pdf_path)
    supplementary_a=_supplementary_item(plan["items"][1])
    supplementary_a["member_table"]="supplementary_a"
    supplementary_a["certified_note_target"].update({
        "certified_link_id":"CLINK_SUPPLEMENTARY_A",
        "logical_table_id":"LOGICAL_A",
        "certified_segments":[{
            "certified_segment_id":"CSEG_A",
            "order":0,
            "classification":"SUPPLEMENTARY_TABLE",
            "start_page":1,
            "end_page":1,
            "certification_status":"CERTIFIED",
        }],
    })
    supplementary_b=copy.deepcopy(supplementary_a)
    supplementary_b["member_table"]="supplementary_b"
    supplementary_b["capture_order"]=3
    supplementary_b["certified_note_target"].update({
        "certified_link_id":"CLINK_SUPPLEMENTARY_B",
        "logical_table_id":"LOGICAL_B",
        "certified_segments":[{
            "certified_segment_id":"CSEG_B",
            "order":0,
            "classification":"SUPPLEMENTARY_TABLE",
            "start_page":1,
            "end_page":1,
            "certification_status":"CERTIFIED",
        }],
    })
    plan["items"].extend([supplementary_a,supplementary_b])
    with registry.connect() as conn:
        conn.execute(
            """UPDATE certified_note_table_inventories
               SET logical_table_ids_json=?
               WHERE note_table_inventory_id='INVENTORY_FIXTURE'""",
            ('["LOGICAL_FIXTURE","LOGICAL_A","LOGICAL_B"]',),
        )
    scope={
        "capture_scope_contract_version":2,
        "capture_scope_policy":"SELECTED_NOTE_TABLES",
        "selected_logical_table_ids":["LOGICAL_A","LOGICAL_B"],
    }
    scoped=svc._plan_for_capture_scope(plan,scope)

    class _CaptureSubmitter:
        def __init__(self):
            self.requests=[]

        def submit_batch(self,requests,**kwargs):
            self.requests=list(requests)
            return [
                {"job_id":f"JOB_{index}","batch_id":kwargs["batch_id"]}
                for index,_ in enumerate(self.requests,1)
            ]

    submitter=_CaptureSubmitter()
    result=GuidedCaptureService(
        registry=registry,
        capture_service=submitter,
        audit_dir=tmp_path,
    ).execute(scoped,pdf_path=pdf_path,options=scope)

    assert len(result["jobs"])==3
    targets=[request.request_metadata["certified_target"] for request in submitter.requests]
    assert [
        target["logical_table_id"] for target in targets
    ]==["LOGICAL_FIXTURE","LOGICAL_A","LOGICAL_B"]
    assert [
        [segment["certified_segment_id"] for segment in target["certified_segments"]]
        for target in targets
    ]==[["CSEG_FIXTURE"],["CSEG_A"],["CSEG_B"]]
    assert [
        request.selected_logical_table_ids for request in submitter.requests
    ]==[("LOGICAL_FIXTURE",),("LOGICAL_A",),("LOGICAL_B",)]
    assert [
        tuple(request.request_metadata["certified_target"]["selected_logical_table_ids"])
        for request in submitter.requests
    ]==[("LOGICAL_FIXTURE",),("LOGICAL_A",),("LOGICAL_B",)]


def test_guided_primary_only_keeps_request_selection_empty(tmp_path):
    registry,_,svc=_service(tmp_path)
    pdf_path=_pdf(tmp_path)
    plan=_compat_plan(pdf_path)
    scope={
        "capture_scope_contract_version":2,
        "capture_scope_policy":"PRIMARY_ONLY",
        "selected_logical_table_ids":[],
    }
    scoped=svc._plan_for_capture_scope(plan,scope)

    class _CaptureSubmitter:
        def __init__(self):
            self.requests=[]

        def submit_batch(self,requests,**kwargs):
            self.requests=list(requests)
            return [{"job_id":"JOB_PRIMARY","batch_id":kwargs["batch_id"]}]

    submitter=_CaptureSubmitter()
    GuidedCaptureService(
        registry=registry,
        capture_service=submitter,
        audit_dir=tmp_path,
    ).execute(scoped,pdf_path=pdf_path,options=scope)

    assert len(submitter.requests)==1
    request=submitter.requests[0]
    assert request.capture_scope_policy=="PRIMARY_ONLY"
    assert request.selected_logical_table_ids==()
    assert request.request_metadata["certified_target"][
        "selected_logical_table_ids"
    ]==[]
    assert request.request_metadata["certified_target"][
        "logical_table_id"
    ]=="LOGICAL_FIXTURE"


@pytest.mark.parametrize(
    ("target_heading","stale_query","expected_query"),
    [
        (
            "11.  债权投资（仅适用2023年）",
            "债权投资(仅适用2023年)",
            "债权投资（仅适用2023年）",
        ),
        ("7.\uffa0债权投资","\u1160债权投资","\uffa0债权投资"),
        ("5.\uffa0 债权投资","\u1160 债权投资","\uffa0 债权投资"),
    ],
)
def test_guided_capture_prefers_certified_pdf_literal_heading(
    tmp_path,target_heading,stale_query,expected_query,
):
    registry,_,_=_service(tmp_path)
    pdf_path=_pdf(tmp_path)
    plan=_compat_plan(pdf_path)
    target=plan["items"][1]["certified_note_target"]
    target["target_heading"]=target_heading
    target["capture_query_title"]=stale_query

    class _CaptureSubmitter:
        def __init__(self):
            self.requests=[]

        def submit_batch(self,requests,**kwargs):
            self.requests=list(requests)
            return [{"job_id":"JOB_LITERAL","batch_id":kwargs["batch_id"]}]

    submitter=_CaptureSubmitter()
    GuidedCaptureService(
        registry=registry,
        capture_service=submitter,
        audit_dir=tmp_path,
    ).execute(plan,pdf_path=pdf_path)

    assert len(submitter.requests)==1
    request=submitter.requests[0]
    assert request.request_metadata["table_query"]==expected_query
    assert request.request_metadata["certified_target"]["target_heading"]==target_heading
    assert request.request_metadata["certified_target"]["confirmed_note_pdf_page_index"]==1
    assert request.request_metadata["certified_target"]["certified_segments"][0]["certified_segment_id"]=="CSEG_FIXTURE"


def test_certified_target_strategy_uses_literal_title_and_logical_bbox():
    request=CaptureRequest.new(
        capture_mode=CaptureMode.CERTIFIED_TARGET,
        source_pdf_path="fixture.pdf",
        source_pdf_id="PDF_FIXTURE",
        member_table_id="other_debt_investment",
    )
    candidate={
        "source_pdf_id":"PDF_FIXTURE",
        "confirmed_note_pdf_page_index":197,
        "end_page":197,
        "target_heading":"14 其他债权投资::SUPPLEMENTARY::8b62bb0dc69a",
        "capture_query_title":"14 其他债权投资::SUPPLEMENTARY::8b62bb0dc69a",
        "note_reference":"附注十二-14",
        "status":"CERTIFIED_NOTE_TARGET",
        "evidence":{
            "logical_table_bbox":{
                "pages":[{
                    "page":197,
                    "bbox":{"x0":0.0,"y0":0.0,"x1":595.276,"y1":787.743},
                }],
            },
        },
    }

    target=CertifiedTargetStrategy().resolve_target(candidate,{"request":request})

    assert target.title=="其他债权投资"
    assert target.start_page==197
    assert target.end_page==197
    assert target.note_reference=="附注十二-14"
    assert target.bbox==(0.0,0.0,595.276,787.743)


@pytest.mark.parametrize(
    ("classification","logical_table_id"),
    [
        ("PRIMARY_TABLE","LOGICAL_FIXTURE"),
        ("PEER_TABLE","LOGICAL_PEER"),
        ("CONTINUATION_SEGMENT","LOGICAL_CONTINUATION"),
        (None,"LOGICAL_MISSING"),
    ],
)
def test_v2_rejects_non_supplementary_logical_table_selection(
    tmp_path,classification,logical_table_id,
):
    _,_,svc=_service(tmp_path)
    plan=_compat_plan(_pdf(tmp_path))
    if classification not in {None,"PRIMARY_TABLE"}:
        item=_supplementary_item(plan["items"][1])
        item["certified_note_target"]["logical_table_id"]=logical_table_id
        item["certified_note_target"]["table_classification"]=classification
        plan["items"].append(item)

    scoped=svc._plan_for_capture_scope(
        plan,{
            "capture_scope_contract_version":2,
            "capture_scope_policy":"SELECTED_NOTE_TABLES",
            "selected_logical_table_ids":[logical_table_id],
        },
    )

    selection=scoped["certified_scope_selection"]
    assert selection["invalid_selected_logical_table_ids"]==[logical_table_id]
    assert selection["issue_codes"]==[
        "CERTIFIED_LOGICAL_TABLE_NOT_SELECTABLE"
    ]
    detail=next(
        item for item in scoped["items"]
        if item.get("member_table_role")=="NOTE_DETAIL"
    )
    assert detail["status"]=="REVIEW_REQUIRED"


@pytest.mark.parametrize("entry_origin",["STRICT","COMPAT"])
def test_both_entry_adapters_use_same_persisted_plan_callback_and_lineage(
    tmp_path,entry_origin,
):
    registry,guided,svc=_service(tmp_path)
    pdf_path=_pdf(tmp_path)
    session_key=svc.execution_session_key(
        display_name="family_fixture",
        research_definition={
            "definition_id":"DEFINITION_FIXTURE",
            "definition_version":"VERSION_FIXTURE",
        },
        scope="CONSOLIDATED",
    )
    kwargs={
        "display_name":"family_fixture",
        "research_definition":{
            "definition_id":"DEFINITION_FIXTURE",
            "definition_version":"VERSION_FIXTURE",
        },
        "scope":"CONSOLIDATED",
        "session_key":session_key,
        "entry_origin":entry_origin,
        "capture_scope_contract_version":2,
        "capture_scope_policy":"PRIMARY_ONLY",
        "selected_logical_table_ids":[],
        "selected_block_roles":[],
        "selected_block_ids":[],
    }
    if entry_origin=="STRICT":
        kwargs.update({
            "certified_links":[_strict_link(pdf_path)],
            "source_pdf_map":{"PDF_FIXTURE":pdf_path},
        })
    else:
        kwargs["plans"]=[_compat_plan(pdf_path)]

    prepared=svc.preview_capture_plans(**kwargs)
    assert prepared["session_key"]==session_key
    assert prepared["status"]=="PLANNED"
    assert prepared["capture_scope"]=={
        "capture_scope_contract_version":2,
        "capture_scope_policy":"PRIMARY_ONLY",
        "selected_logical_table_ids":[],
        "selected_block_roles":[],
        "selected_block_ids":[],
    }
    assert len(prepared["plans"])==1
    plan=prepared["plans"][0]
    assert plan["plan_id"]
    assert plan["source_pdf_path"]==str(pdf_path)
    with registry.connect() as conn:
        assert conn.execute(
            "SELECT COUNT(*) n FROM capture_plans"
        ).fetchone()["n"]==0
        assert conn.execute(
            "SELECT COUNT(*) n FROM stage_b_execution_sessions"
        ).fetchone()["n"]==0
    assert any(
        item.get("member_table_role")=="NOTE_DETAIL"
        and (item.get("certified_note_target") or {}).get("status")
            =="CERTIFIED_NOTE_TARGET"
        for item in plan["items"]
    )

    result=svc.create_execution_batch(**kwargs)
    assert result["callback_key"]=="GuidedCaptureService.execute"
    assert result["workspace_route"]=="逻辑资产工作区"
    assert result["workspace_filter"]=={
        "research_batch_id":result["research_batch_id"],
    }
    assert len(guided.calls)==1
    assert guided.calls[0]["callback"]=="GuidedCaptureService.execute"
    assert guided.calls[0]["options"]==prepared["capture_scope"]

    with registry.connect() as conn:
        persisted_plans=conn.execute(
            "SELECT COUNT(*) n FROM capture_plans"
        ).fetchone()["n"]
        session=conn.execute(
            "SELECT * FROM stage_b_execution_sessions WHERE session_key=?",
            (session_key,),
        ).fetchone()
        research_payload=json.loads(conn.execute(
            """SELECT payload_json FROM research_batches
               WHERE research_batch_id=?""",
            (result["research_batch_id"],),
        ).fetchone()["payload_json"])
        roles=[
            row["role"] for row in conn.execute(
                """SELECT role FROM research_batch_members
                   WHERE research_batch_id=? ORDER BY role""",
                (result["research_batch_id"],),
            ).fetchall()
        ]
    assert persisted_plans==1
    assert session["research_batch_id"]==result["research_batch_id"]
    assert json.loads(session["plan_ids_json"])==result["plan_ids"]
    assert json.loads(session["batch_ids_json"])==result["batch_ids"]
    assert json.loads(session["capture_scope_json"])==prepared["capture_scope"]
    assert research_payload["capture_scope"]==prepared["capture_scope"]
    assert roles==["PLAN","SOURCE_BATCH"]
    versioned=svc.persist_capture_scope(
        session_key,
        capture_scope_contract_version=2,
        capture_scope_policy="SELECTED_NOTE_TABLES",
        selected_logical_table_ids=["LOGICAL_OTHER"],
        selected_block_roles=[],selected_block_ids=[],
    )
    assert versioned["session_key"].startswith(session_key + "__V")
    assert versioned["capture_scope"]["capture_scope_policy"]=="SELECTED_NOTE_TABLES"
    assert svc.latest_execution_session_key(session_key)==versioned["session_key"]
    assert svc.restore_execution(session_key)["capture_scope"]==prepared["capture_scope"]
    assert svc.restore_execution(versioned["session_key"])["capture_scope"]["capture_scope_policy"]=="SELECTED_NOTE_TABLES"


def test_new_service_instance_restores_progress_review_queue_and_workspace(
    tmp_path,
):
    registry,guided,svc=_service(tmp_path)
    pdf_path=_pdf(tmp_path)
    session_key=svc.execution_session_key(
        display_name="family_fixture",
        research_definition={
            "definition_id":"DEFINITION_FIXTURE",
            "definition_version":"VERSION_FIXTURE",
        },
        scope="CONSOLIDATED",
    )
    created=svc.create_execution_batch(
        display_name="family_fixture",
        plans=[_compat_plan(pdf_path)],
        research_definition={
            "definition_id":"DEFINITION_FIXTURE",
            "definition_version":"VERSION_FIXTURE",
        },
        scope="CONSOLIDATED",
        session_key=session_key,
        entry_origin="COMPAT",
    )
    batch_id=created["batch_ids"][0]
    research_batch_id=created["research_batch_id"]

    registry.upsert_capture({
        "capture_id":"CAPTURE_FIXTURE",
        "run_path":str(tmp_path/"capture"),
        "pdf_name":"fixture.pdf",
        "company":"COMPANY_FIXTURE",
        "document_year":"YEAR_FIXTURE",
        "table_query":"member_fixture",
        "table_family_id":"family_fixture",
        "producer_version":"v6.11",
        "batch_id":batch_id,
        "merge_ready":False,
    })
    governance=AssetGovernanceRepository(registry)
    asset=governance.get_or_create_logical_asset({
        "company_id":"COMPANY_FIXTURE",
        "filing_type":"ANNUAL_REPORT",
        "report_year":"YEAR_FIXTURE",
        "statement_scope":"CONSOLIDATED",
        "research_project_id":"PROJECT_FIXTURE",
        "research_task_id":"TASK_FIXTURE",
        "research_batch_id":research_batch_id,
        "research_definition_id":"DEFINITION_FIXTURE",
        "definition_version":"VERSION_FIXTURE",
        "table_family_id":"family_fixture",
        "member_table_id":"member_fixture",
        "logical_source_role":"NOTE_DETAIL",
    })
    governance.register_capture_version(
        logical_asset_id=asset["logical_asset_id"],
        capture_id="CAPTURE_FIXTURE",
        producer_version="v6.11",
        processing_status="COMPLETED",
        registration_status="REGISTERED",
        quality_status="REVIEW_REQUIRED",
        review_status="PENDING",
        certified=False,
        asset_status="ACTIVE",
    )
    governance.enqueue_review(
        logical_asset_id=asset["logical_asset_id"],
        capture_id="CAPTURE_FIXTURE",
        primary_reason="PDF_BOUNDARY_UNCERTAIN",
        evidence={"fixture":True},
    )
    with registry.connect() as conn:
        conn.execute(
            """UPDATE jobs SET status='REVIEW_REQUIRED',progress=1,
               target_asset_id=?,updated_at=? WHERE batch_id=?""",
            ("CAPTURE_FIXTURE",now_iso(),batch_id),
        )
        # Simulate an app/process stop after durable lineage was attached but
        # before the execution-session batch snapshot was refreshed.
        conn.execute(
            """UPDATE stage_b_execution_sessions SET batch_ids_json='[]'
               WHERE session_key=?""",
            (session_key,),
        )

    restarted=ChildCaptureExecutionService(
        registry=registry,
        capture_service=None,
        table_capture_runner=_FakeRunner(registry),
        research_batch_service=ResearchBatchService(registry),
        guided_capture_service=_FakeGuidedCapture(registry),
        hierarchical_child_discovery_service=_StrictDiscovery(),
    )
    restored=restarted.restore_execution(session_key)

    assert restored["executed"] is True
    assert restored["research_batch_id"]==research_batch_id
    assert restored["batch_ids"]==[batch_id]
    assert restored["all_terminal"] is True
    assert restored["progress"][0]["进度"]=="100%"
    assert restored["review_queue"][0]["capture_id"]=="CAPTURE_FIXTURE"
    assert restored["review_queue"][0]["logical_asset_id"]==asset["logical_asset_id"]
    assert restored["workspace_filter"]=={
        "research_batch_id":research_batch_id,
    }
    assert restored["capture_scope"]=={
        "capture_scope_contract_version":2,
        "capture_scope_policy":"PRIMARY_ONLY",
        "selected_logical_table_ids":[],
        "selected_block_roles":[],
        "selected_block_ids":[],
    }

    # Re-submit after restart is idempotent and does not invoke the callback.
    again=restarted.create_execution_batch(
        display_name="family_fixture",
        session_key=session_key,
        entry_origin="COMPAT",
    )
    assert again["batch_ids"]==[batch_id]
    assert restarted.guided_capture.calls==[]


def test_stage_b_ui_has_one_db_restored_panel_and_one_workspace_route():
    workflow=(ROOT/"guided_workflow_ui.py").read_text(encoding="utf-8")
    panel=(
        ROOT/"components"/"child_capture_execution_panel.py"
    ).read_text(encoding="utf-8")
    workspace=(ROOT/"asset_workspace_ui.py").read_text(encoding="utf-8")
    service=(
        ROOT/"services"/"child_capture_execution_service.py"
    ).read_text(encoding="utf-8")

    assert workflow.count("render_child_capture_execution_panel(")==1
    assert "v610_strict_child" not in workflow
    assert "v610_compat_child" not in workflow
    # Certification with zero certified links must fail closed instead of
    # silently falling back to a stale historical execution session.
    assert (
        "阶段 A 认证已完成，但本次没有产生任何 CertifiedChildTableLink"
        in workflow
    )
    assert "系统不会用历史会话计划代替本次认证结果" in workflow
    # The panel restores from the DB before any session_state write; reading
    # the sticky active-session key first is required to resume the latest
    # versioned session and does not mutate business state.
    assert panel.index("restore_execution(")<panel.index("st_obj.session_state[")
    assert "Capture Plan" in panel
    assert "PRIMARY_ONLY" in panel
    assert "_CAPTURE_SCOPE_LABELS" not in panel
    assert "主表及其续表（不含补充子表）" not in panel
    assert "CaptureScopePolicy.SELECTED_NOTE_TABLES.value" in panel
    assert "selected_logical_table_ids" in panel
    assert "_primary_" in panel and "disabled=True" in panel
    assert "_supplementary_" in panel
    # The confirm button must forward the same certified inventory/plan shown
    # by the read-only preview, so a first-use explicit submission atomically
    # persists plans + session + scope (offline-pipeline contract).
    submit_snippet = panel.split("create_execution_batch(",1)[1].split(
        "st_obj.session_state",1
    )[0]
    assert "certified_links=certified_links" in submit_snippet
    assert "source_pdf_map=source_pdf_map" in submit_snippet
    assert "plans=plans" in submit_snippet
    # Stage B uses the shared presentation vocabulary; persisted enum tokens
    # remain unchanged.
    assert "from presentation_labels import CLASSIFICATION_LABELS" in panel
    assert '_PRIMARY_LABEL = CLASSIFICATION_LABELS["PRIMARY_TABLE"]' in panel
    assert (
        '_SUPPLEMENTARY_LABEL = CLASSIFICATION_LABELS["SUPPLEMENTARY_TABLE"]'
        in panel
    )
    assert 'f"{_PRIMARY_LABEL}｜' in panel
    assert 'f"{_SUPPLEMENTARY_LABEL}｜' in panel
    assert "主表｜" not in panel
    assert "补充表｜" not in panel
    assert "asset_workspace_filter" in panel
    assert "routed_filters" in workspace
    assert '("research_batch_id","研究批次")' in workspace
    assert "进入合表" not in panel
    assert "capture_readiness" not in service


def test_existing_stage_b_session_schema_migrates_capture_scope_column(
    tmp_path,
):
    database=tmp_path/"legacy_metadata.db"
    with sqlite3.connect(database) as conn:
        conn.execute("""CREATE TABLE stage_b_execution_sessions(
            session_key TEXT PRIMARY KEY,
            entry_origin TEXT NOT NULL,
            display_name TEXT NOT NULL,
            scope TEXT,
            research_definition_id TEXT,
            definition_version TEXT,
            status TEXT NOT NULL,
            research_batch_id TEXT,
            plan_ids_json TEXT NOT NULL,
            batch_ids_json TEXT NOT NULL,
            callback_key TEXT NOT NULL,
            workspace_route TEXT NOT NULL,
            workspace_filter_json TEXT NOT NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )""")
        conn.execute("""INSERT INTO stage_b_execution_sessions(
            session_key,entry_origin,display_name,scope,
            research_definition_id,definition_version,status,
            research_batch_id,plan_ids_json,batch_ids_json,
            callback_key,workspace_route,workspace_filter_json,
            created_at,updated_at
        ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",(
            "STAGEB_LEGACY","COMPAT","legacy","CONSOLIDATED",
            "DEF_LEGACY","V1","EXECUTING","RB_LEGACY",
            '["PLAN_LEGACY"]','["BATCH_LEGACY"]',
            "GuidedCaptureService.execute","逻辑资产工作区","{}",
            "2026-01-01T00:00:00+08:00","2026-01-01T00:00:00+08:00",
        ))
    registry=MetadataRegistry(database)
    with registry.connect() as conn:
        columns={
            row[1] for row in conn.execute(
                "PRAGMA table_info(stage_b_execution_sessions)"
            ).fetchall()
        }
        legacy=dict(conn.execute(
            """SELECT * FROM stage_b_execution_sessions
               WHERE session_key='STAGEB_LEGACY'"""
        ).fetchone())
    assert "capture_scope_json" in columns
    assert legacy["status"]=="EXECUTING"
    assert legacy["research_batch_id"]=="RB_LEGACY"
    assert legacy["plan_ids_json"]=='["PLAN_LEGACY"]'
    assert legacy["capture_scope_json"]=="{}"
