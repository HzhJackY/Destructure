from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from unittest.mock import patch

from metadata_registry import MetadataRegistry,now_iso
from repositories.asset_governance_repository import AssetGovernanceRepository
from repositories.capture_repository import CaptureRepository
from services.asset_governance_services import (
    AssetLifecycleService,AssetQueryService,LogicalAssetService,
    MergeEligibilityService,ReviewInboxService,
)
from services.capture_version_service import CaptureVersionService
from services.review_service import ReviewService
from inspection_route import REASON_TAB,route_from_review


def _register(registry,logical,company,member,capture_id,run_path,*,certified):
    registry.upsert_capture({
        "capture_id":capture_id,"run_path":str(run_path),"company":company,
        "document_year":"2023","table_query":member,"table_family_id":"金融投资",
        "producer_version":"v6.9","merge_ready":certified,
    })
    return logical.register_capture(
        capture_id=capture_id,metadata={
            "company":company,"document_year":"2023","table_family":"金融投资",
            "member_table":member,"member_table_role":"NOTE_DETAIL",
            "research_definition_id":"FINANCIAL_INVESTMENT_V1",
            "definition_version":"1","scope":"CONSOLIDATED",
        },processing_status="COMPLETED",registration_status="REGISTERED",
        quality_status="READY" if certified else "REVIEW_REQUIRED",
        review_status="CONFIRMED_AUTO" if certified else "PENDING",certified=certified,
    )


def test_atomic_review_route_merge_bundle_and_immutable_revision():
    with tempfile.TemporaryDirectory() as tmp:
        root=Path(tmp); registry=MetadataRegistry(root/"metadata.db")
        repo=AssetGovernanceRepository(registry); captures=CaptureRepository(registry)
        logical=LogicalAssetService(repo,"v6.9"); lifecycle=AssetLifecycleService(repo,"v6.9")
        query=AssetQueryService(repo); merge=MergeEligibilityService(query)
        inbox=ReviewInboxService(repo); review=ReviewService(repo,lifecycle,merge); inbox.configure(review)
        version_service=CaptureVersionService(repo,captures,inbox,{"table_captures":root},"v6.9")
        run_a=root/"CAP_A";run_b=root/"CAP_B";run_a.mkdir();run_b.mkdir()
        for run in (run_a,run_b):
            (run/"capture_metadata.json").write_text(json.dumps({"run_id":run.name}),encoding="utf-8")
            (run/"table_capture_result.json").write_text(json.dumps({"rows":[]}),encoding="utf-8")
        a=_register(registry,logical,"新华保险","债权投资-A","CAP_A",run_a,certified=True)
        b=_register(registry,logical,"新华保险","债权投资-B","CAP_B",run_b,certified=False)
        inbox.route(logical_asset_id=b["logical_asset"]["logical_asset_id"],capture_id="CAP_B",
                    reasons=["HEADER_REVIEW_REQUIRED"],evidence={"page":109})
        row=inbox.list(status="PENDING")[0]
        route=route_from_review(row)
        assert route.logical_asset_id==b["logical_asset"]["logical_asset_id"]
        assert route.capture_version_id=="CAP_B"
        assert route.initial_tab=="表头拓扑"

        with registry.connect() as conn:
            conn.execute("""INSERT INTO note_containers(
                container_id,source_pdf_sha256,note_title,start_pdf_page,end_pdf_page,
                context_json,layout_graph_json,created_at
            ) VALUES('N1','sha','附注12',109,110,'{}','{}',?)""",(now_iso(),))
            conn.execute("""INSERT INTO capture_bundles(
                bundle_id,container_id,status,payload_json,created_at,updated_at
            ) VALUES('B1','N1','REVIEW_REQUIRED','{}',?,?)""",(now_iso(),now_iso()))
            for index,(block,capture,asset) in enumerate((
                ("BLK_A","CAP_A",a["logical_asset"]["logical_asset_id"]),
                ("BLK_B","CAP_B",b["logical_asset"]["logical_asset_id"]),
            )):
                conn.execute("""INSERT INTO table_blocks(
                    block_id,container_id,block_order,block_title,block_role,
                    bbox_json,header_topology_json,semantic_graph_json,reconciliation_json,
                    quality_status,status,evidence_json,created_at
                ) VALUES(?,?,?,?,?,'{}','{}','{}','{}','READY','CAPTURED','{}',?)""",
                (block,"N1",index,block,"PRIMARY_TABLE" if index==0 else "SECONDARY_TABLE",now_iso()))
                conn.execute("""INSERT INTO capture_bundle_children(
                    bundle_id,block_id,capture_id,logical_asset_id,child_order,status,payload_json,created_at
                ) VALUES('B1',?,?,?,?, 'CAPTURED','{}',?)""",
                (block,capture,asset,index,now_iso()))
        assert repo.recalculate_bundle_status("CAP_B")=="PARTIALLY_REVIEW_REQUIRED"
        before_count=len(inbox.list(status="PENDING"))
        outcome=review.adjudicate_capture(capture_id="CAP_B",action="CONFIRMED",reason="fixture confirmed")
        assert outcome["after"]["review_status"]=="CONFIRMED_HUMAN"
        assert outcome["after"]["asset_status"]=="CERTIFIED_ACTIVE"
        assert outcome["merge_eligible_after_commit"] is True
        assert len(inbox.list(status="PENDING"))==before_count-1
        assert repo.bundle_detail("CAP_B")["bundle"]["status"]=="READY"
        assert repo.review_history("CAP_B")[0]["action"]=="CONFIRMED"

        with patch("services.capture_version_service.sync_capture_run",return_value={"status":"OK"}):
            revision=version_service.create_structure_revision(
                capture_id="CAP_B",revision_type="MOVE_BOUNDARY",
                payload={"y":456.0},table_block_id="BLK_B",
            )
        new_id=revision["new_capture_id"]
        assert (Path(captures.get(new_id)["run_path"])/"human_structure_revision.json").is_file()
        assert captures.get("CAP_B") is not None
        new_detail=repo.capture_detail(new_id)
        assert new_detail["review_status"]=="PENDING"
        assert new_detail["quality_status"]=="REVIEW_REQUIRED"
        assert repo.bundle_detail(new_id)["bundle"]["status"]=="PARTIALLY_REVIEW_REQUIRED"
        review.adjudicate_capture(capture_id=new_id,action="CONFIRMED",reason="revision checked")
        assert repo.capture_detail("CAP_B")["asset_status"]=="SUPERSEDED"
        assert repo.capture_detail(new_id)["asset_status"]=="CERTIFIED_ACTIVE"
        assert repo.bundle_detail(new_id)["bundle"]["status"]=="READY"


def test_reason_to_tab_contract_is_complete_for_required_reasons():
    assert REASON_TAB["BOUNDARY_REVIEW_REQUIRED"]=="附注容器与表块"
    assert REASON_TAB["HEADER_REVIEW_REQUIRED"]=="表头拓扑"
    assert REASON_TAB["STRUCTURE_REVIEW_REQUIRED"]=="行结构"
    assert REASON_TAB["RECONCILIATION_WARNING"]=="勾稽与质量"
    assert REASON_TAB["UNIT_REVIEW_REQUIRED"]=="Canonical 数据"


def test_reject_and_unresolved_never_become_merge_eligible():
    with tempfile.TemporaryDirectory() as tmp:
        root=Path(tmp); registry=MetadataRegistry(root/"metadata.db")
        repo=AssetGovernanceRepository(registry); captures=CaptureRepository(registry)
        logical=LogicalAssetService(repo,"v6.9"); lifecycle=AssetLifecycleService(repo,"v6.9")
        merge=MergeEligibilityService(AssetQueryService(repo))
        review=ReviewService(repo,lifecycle,merge)
        for capture_id,action in (("CAP_REJECT","REJECTED"),("CAP_UNRESOLVED","UNRESOLVED")):
            run=root/capture_id; run.mkdir()
            _register(registry,logical,"中国平安",capture_id,capture_id,run,certified=False)
            result=review.adjudicate_capture(
                capture_id=capture_id,action=action,reason=f"fixture {action.lower()}",
            )
            assert result["merge_eligible_after_commit"] is False
            detail=repo.capture_detail(capture_id)
            assert detail["review_status"]==action
            if action=="REJECTED":
                assert detail["asset_status"]=="INVALIDATED"
