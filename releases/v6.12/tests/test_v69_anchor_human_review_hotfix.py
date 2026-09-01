from __future__ import annotations

import json
import tempfile
from pathlib import Path

import pytest
from anchor_candidate_selection import (
    candidate_label,deduplicate_anchor_candidates,rank_and_preselect,
)
from final_data_review import review_final_data_columns
from discovery_registry import DiscoveryRegistry
from metadata_registry import MetadataRegistry
from repositories.asset_governance_repository import AssetGovernanceRepository
from services.asset_governance_services import (
    AssetLifecycleService,AssetQueryService,LogicalAssetService,MergeEligibilityService,
)
from services.review_service import ReviewService
from services.review_task_service import ReviewTaskService
from services.discovery_service import DiscoveryService
from v69_learning import seed_label_schemas


def _candidate(occurrence_id,page,scope="CONSOLIDATED",title="合并资产负债表",pdf="P1",score_variant=0):
    children=[]
    for index in range(4):
        children.append({
            "item":f"子项{index}","value":100+index,
            "note_reference_normalized":f"附注八-{11+index}",
            "data_year":"2023" if index%2==0 else "2022",
        })
    return {
        "occurrence_id":occurrence_id,"pdf_id":pdf,"company":"新华保险",
        "report_year":"2023","display_name":"金融投资","parent_text":"金融投资",
        "statement_type":"BALANCE_SHEET","source_table_title":title,
        "scope":scope,"statement_pdf_page_index":page,"child_rows":children,
        "evidence":{"period_headers":["2023","2022"],"unit":"CNY_MILLION",
                    "amount_columns_aligned":True,"bbox_verified":True,
                    "strategy_id":f"S{score_variant}"},
    }


def test_anchor_dedupe_ranking_preselection_and_auditable_label():
    best=_candidate("O_BEST",109)
    duplicate={**best,"occurrence_id":"O_DUP","evidence":{**best["evidence"],"strategy_id":"OTHER"}}
    low=_candidate("O_LOW",111,scope="PARENT_COMPANY",title="主要会计数据摘要")
    ranked=rank_and_preselect(
        [duplicate,low,best],
        {"scope_preference":"CONSOLIDATED","required_scopes":["CONSOLIDATED"]},
    )
    assert len(ranked["candidates"])==2
    assert ranked["candidates"][0]["total_score"]>ranked["candidates"][1]["total_score"]
    assert ranked["preselected_ids"]==[ranked["candidates"][0]["occurrence_id"]]
    assert ranked["candidates"][0]["duplicate_count"]==2
    assert ranked["candidates"][1]["hard_gates_passed"] is False
    label=candidate_label(ranked["candidates"][0])
    assert "推荐" in label and "PDF 109" in label and "4个子项" in label


def test_ambiguous_top_margin_has_no_preselection_and_scope_cardinality():
    first=_candidate("O1",109,pdf="P1")
    second=_candidate("O2",110,pdf="P1")
    ambiguous=rank_and_preselect([first,second],{"required_scopes":["CONSOLIDATED"]})
    assert ambiguous["preselected_ids"]==[]
    assert next(iter(ambiguous["scope_decisions"].values()))["status"]=="ANCHOR_SELECTION_REQUIRED"
    multi=rank_and_preselect([
        _candidate("A1",109,pdf="P1"),_candidate("A2",109,pdf="P2"),
        _candidate("PARENT",111,scope="PARENT_COMPANY",pdf="P1"),
    ],{"required_scopes":["CONSOLIDATED","PARENT_COMPANY"]})
    assert len(multi["preselected_ids"])==3
    assert len(set(multi["preselected_ids"]))==3


def test_anchor_human_selection_persists_audit_and_ml_examples():
    with tempfile.TemporaryDirectory() as tmp:
        registry=MetadataRegistry(Path(tmp)/"metadata.db")
        seed_label_schemas(registry)
        store=DiscoveryRegistry(registry)
        best=store.save_occurrence(_candidate("SELECTED",109))
        alternative=store.save_occurrence(_candidate("ALTERNATIVE",110))
        ranked=rank_and_preselect([best,alternative],{"required_scopes":["CONSOLIDATED"]})
        store.save_anchor_scores(ranked["candidates"])
        store.adjudicate_anchor(
            "SELECTED",label="ACCEPTED",actor="tester",reason="逐页确认",
            chosen_scope="CONSOLIDATED",
            override={
                "selection_method":"HUMAN_CONFIRMED_RECOMMENDATION",
                "recommended_candidate_id":"SELECTED",
                "selected_candidate_id":"SELECTED",
                "candidate_score":ranked["candidates"][0]["total_score"],
                "score_evidence_snapshot":ranked["candidates"][0]["score_components"],
                "alternative_candidates":[{"occurrence_id":"ALTERNATIVE"}],
            },
        )
        with registry.connect() as conn:
            audit=conn.execute("SELECT * FROM anchor_certification_audit").fetchall()
            labels=conn.execute(
                "SELECT entity_id,label_value FROM ml_labels WHERE schema_id='ANCHOR_CANDIDATE_V1'"
            ).fetchall()
            scores=conn.execute("SELECT * FROM anchor_candidate_scores").fetchall()
        assert len(scores)==2 and len(audit)==1
        assert {(x["entity_id"],x["label_value"]) for x in labels}=={
            ("SELECTED","SELECTED"),("ALTERNATIVE","ALTERNATIVE"),
        }
        # Re-ranking an ambiguous group must never downgrade a human-certified
        # anchor.  The audit is durable truth and repairs the materialized state.
        with registry.connect() as conn:
            conn.execute(
                "UPDATE statement_occurrences SET status='ANCHOR_SELECTION_REQUIRED' WHERE occurrence_id='SELECTED'"
            )
        store.sync_anchor_review_queue(ranked)
        assert store.get_occurrence("SELECTED")["status"]=="ANCHOR_CERTIFIED"
        assert store.is_anchor_certified("SELECTED") is True
        service=DiscoveryService(store,Path(tmp))
        plan=service.certified_capture_plan(
            {**store.get_occurrence("SELECTED"),"child_rows":best["child_rows"]},
            certified_ids=[],certified_targets={},
        )
        assert plan["anchor_occurrence_id"]=="SELECTED"


def test_final_data_column_checks_detect_last_period_and_count_risks():
    result={
        "columns":[
            {"raw_header_path":"2022","data_year":"2022"},
            {"raw_header_path":"2023","data_year":"2023"},
        ],
        "rows":[{"row_order":1,"raw_item":"政府债","values":["2023"]}],
    }
    review=review_final_data_columns(result)
    codes={x["reason_code"] for x in review["issues"]}
    assert "VALUE_COLUMN_COUNT_MISMATCH" in codes
    assert "NUMERIC_TOKEN_ORIGIN_AMBIGUOUS" in codes
    assert "PERIOD_COLUMN_SWAP_RISK" in codes
    assert "LAST_COLUMN_MAPPING_UNCERTAIN" in codes


def test_implicit_total_rows_do_not_create_false_last_column_review():
    result={
        "columns":[
            {"raw_header_path":"2023","data_year":"2023"},
            {"raw_header_path":"2022","data_year":"2022"},
        ],
        "rows":[
            {"row_order":i,"raw_item":None,"row_role":"IMPLICIT_TOTAL","values":[]}
            for i in range(1,15)
        ],
    }
    review=review_final_data_columns(result)
    assert review["last_column_check"]["status"]=="NOT_APPLICABLE"
    assert review["last_column_check"]["rows_with_last_token"]==0
    assert review["last_column_check"]["row_count"]==0
    assert review["last_column_check"]["excluded_derived_rows"]==14
    assert "LAST_COLUMN_MAPPING_UNCERTAIN" not in {
        x["reason_code"] for x in review["issues"]
    }


def test_review_reason_backfill_tasks_and_final_gate_are_idempotent():
    with tempfile.TemporaryDirectory() as tmp:
        root=Path(tmp);run=root/"CAP";run.mkdir()
        (run/"table_capture_result.json").write_text(json.dumps({
            "columns":[{"raw_header_path":"2023","data_year":"2023"}],
            "rows":[{"row_order":1,"raw_item":"资产","values":[100]}],
            "unit":"CNY_MILLION","header_dimension_status":"CONFIRMED",
            "stats":{"v69_reconciliation":{"status":"PASS"}},
        },ensure_ascii=False),encoding="utf-8")
        registry=MetadataRegistry(root/"metadata.db")
        repo=AssetGovernanceRepository(registry)
        registry.upsert_capture({
            "capture_id":"CAP","run_path":str(run),"company":"新华保险",
            "document_year":"2023","table_query":"交易性金融资产",
            "producer_version":"v6.11","merge_ready":False,
        })
        logical=LogicalAssetService(repo,"v6.11")
        registered=logical.register_capture(
            capture_id="CAP",metadata={"company":"新华保险","document_year":"2023",
                                      "member_table":"交易性金融资产","scope":"UNKNOWN"},
            processing_status="COMPLETED",registration_status="REGISTERED",
            quality_status="REVIEW_REQUIRED",review_status="PENDING",certified=False,
        )
        tasks=ReviewTaskService(repo)
        first=tasks.materialize("CAP")
        with registry.connect() as conn:
            count1=conn.execute("select count(*) n from review_issues").fetchone()["n"]
        second=tasks.materialize("CAP")
        with registry.connect() as conn:
            count2=conn.execute("select count(*) n from review_issues").fetchone()["n"]
        assert count1==count2
        codes={x["reason_code"] for x in first["issues"]}
        assert {"RESEARCH_DEFINITION_MISSING","TABLE_FAMILY_MISSING",
                "STATEMENT_SCOPE_UNKNOWN"}<=codes
        assert first["can_final_confirm"] is False
        for task in first["blocking_tasks"]:
            tasks.decide_task(
                "CAP",task["task_type"],"OVERRIDDEN",
                reason="测试：已人工检查，但身份字段仍需正式修订",
            )
        with pytest.raises(PermissionError,match="FINAL_CONFIRM_IDENTITY_INCOMPLETE"):
            tasks.validate_final_confirm("CAP")
        with registry.connect() as conn:
            decisions=conn.execute(
                "SELECT * FROM review_task_decisions WHERE capture_version_id='CAP'"
            ).fetchall()
        assert len(decisions)==len(first["blocking_tasks"])


def test_workspace_contract_is_human_readable_and_json_is_advanced_only():
    text=(Path(__file__).resolve().parents[1]/"components"/"capture_inspection_panel.py").read_text(encoding="utf-8")
    assert "高级信息 / 原始元数据" in text
    assert "待处理问题" in text and "阻断认证任务" in text
    assert "最终数据复核" in text
    review=(Path(__file__).resolve().parents[1]/"components"/"review_action_panel.py").read_text(encoding="utf-8")
    assert "审核进度" in review
    assert "高级模式：原始 JSON Override" in review
    assert "最终确认已锁定" in review


def test_guided_anchor_review_shows_pdf_business_evidence_and_clears_stale_stage_b():
    text=(Path(__file__).resolve().parents[1]/"guided_workflow_ui.py").read_text(encoding="utf-8")
    assert "候选主报表原页" in text
    assert "人工判断依据" in text
    assert "主表金额" in text and "附注编号" in text
    assert "高级信息：机器评分、门禁和算法版本" in text
    assert "v66_resolved_occurrences" in text and "session_state.pop(key,None)" in text
    assert "该主报表只是历史会话中的候选" in text
    assert "backend.discovery_registry.get_occurrence" in text


@pytest.mark.skipif(
    not Path(r"C:\dev\AXA_research\docu\新华保险2023年报.pdf").exists(),
    reason="本地真实夹具不可用",
)
def test_real_xinhua_2023_anchor_ranking_recommends_formal_statement_page():
    from backend_context import build_backend_services
    from data_home import ensure_data_home
    root=Path(__file__).resolve().parents[1]
    with tempfile.TemporaryDirectory() as tmp:
        backend=build_backend_services(ensure_data_home(Path(tmp),root/"metric_aliases.json"))
        discovered=backend.generic_discovery_service.discover(
            pdf_path=Path(r"C:\dev\AXA_research\docu\新华保险2023年报.pdf"),
            definition_id="FINANCIAL_INVESTMENT_V1",company="新华保险",report_year="2023",
        )
        occurrences=[
            backend.discovery_service.build_occurrence(
                context=dict(x)|{"pdf_id":r"C:\dev\AXA_research\docu\新华保险2023年报.pdf"},
                parent_text=x["parent_text"],child_rows=x["child_rows"],
                source_table_title=x["source_table_title"],scope=x.get("scope","UNKNOWN"),
            ) for x in discovered["occurrences"]
        ]
        ranking=backend.discovery_service.rank_anchor_candidates(
            occurrences,required_scopes=["CONSOLIDATED"],
        )
        page109=[x for x in ranking["candidates"] if x.get("statement_pdf_page_index")==109]
        assert page109,page109
        assert ranking["candidates"][0]["statement_pdf_page_index"]==109
        assert ranking["candidates"][0]["total_score"]>=0.85
        assert ranking["candidates"][0]["hard_gates_passed"] is True
        assert ranking["preselected_ids"]==[ranking["candidates"][0]["occurrence_id"]]
