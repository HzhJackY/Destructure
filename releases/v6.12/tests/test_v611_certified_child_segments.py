from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))

from hierarchical_child_discovery import (
    ChildDiscoveryRepository,FinancialNoteIndexService,
    HierarchicalChildTableDiscoveryService,
)
from metadata_registry import MetadataRegistry,now_iso
from v69_learning import list_structural_learning_candidates
from version import APP_VERSION,REGISTRY_SCHEMA_VERSION


def _repository(tmp_path:Path):
    registry=MetadataRegistry(tmp_path/"metadata.db")
    return registry,ChildDiscoveryRepository(registry)


def _seed_candidate(
    repository:ChildDiscoveryRepository, *,
    candidate_id:str="CANDIDATE_FIXTURE",
    note_reference:str="附注13",
    anchor_child_id:str="ANCHOR_CHILD_FIXTURE",
):
    created_at=now_iso()
    run={
        "discovery_run_id":"RUN_"+candidate_id,
        "source_pdf_id":"PDF_FIXTURE",
        "source_pdf_sha256":"SHA_FIXTURE",
        "anchor_id":"ANCHOR_FIXTURE",
        "anchor_child_id":anchor_child_id,
        "requested_scope":"CONSOLIDATED",
        "tiers_executed":["TIER_1"],
        "tiers_skipped":[],
        "early_stop_reason":"CERTIFIED_FIXTURE",
        "candidate_count_by_tier":{"TIER_1":1},
        "runtime_by_tier":{"TIER_1":0.1},
        "metrics":{"discovery_version":"fixture"},
        "status":"COMPLETED",
        "created_at":created_at,
    }
    candidate={
        "candidate_id":candidate_id,
        "discovery_run_id":run["discovery_run_id"],
        "anchor_child_id":run["anchor_child_id"],
        "retrieval_tier":"TIER_1",
        "retrieval_method":"FIXTURE",
        "retrieval_priority":1,
        "source_pdf_id":run["source_pdf_id"],
        "source_pdf_sha256":run["source_pdf_sha256"],
        "heading_id":"HEADING_FIXTURE",
        "raw_heading":"13 债权投资",
        "normalized_heading":"13债权投资",
        "section_type":"FINANCIAL_STATEMENT_NOTES",
        "start_page":195,
        "end_page_hint":197,
        "heading_bbox":{"x0":10,"top":20,"x1":200,"bottom":40},
        "note_reference":note_reference,
        "statement_scope_hint":"CONSOLIDATED",
        "base_score":1.0,
        "warning_codes":[],
        "hard_gate_summary":{"pass":True},
        "evidence_ref_ids":[],
        "created_at":created_at,
    }
    repository.save_run(run,[candidate])
    return candidate


def _link(candidate_id:str="CANDIDATE_FIXTURE"):
    return {
        "anchor_id":"ANCHOR_FIXTURE",
        "anchor_child_id":"ANCHOR_CHILD_FIXTURE",
        "candidate_id":candidate_id,
        "link_candidate_id":"LINK_CANDIDATE_FIXTURE",
        "table_family_id":"financial_investment",
        "member_table_id":"debt_investment",
        "subtable_role":"NOTE_DETAIL",
        "relation_type":"STATEMENT_TO_NOTE",
        "statement_scope":"CONSOLIDATED",
        "selected_candidate_id":candidate_id,
        "score_snapshot":{"certification_score":0.99},
        "evidence_snapshot":{},
    }


def _segments():
    return [
        {
            "certified_segment_id":"SEGMENT_PRIMARY",
            "order":0,
            "classification":"PRIMARY_TABLE",
            "start_page":195,
            "end_page":195,
            "bbox":{"x0":10,"top":50,"x1":500,"bottom":700},
            "header_signature":{"columns":["2025","2024"]},
            "period_signature":{"periods":["2025","2024"]},
            "amount_lane_signature":{"lane_count":2},
            "confidence":0.99,
            "evidence":{"title":"13 债权投资"},
        },
        {
            "certified_segment_id":"SEGMENT_CONTINUATION",
            "order":1,
            "classification":"CONTINUATION_SEGMENT",
            "start_page":196,
            "end_page":196,
            "bbox":{"x0":10,"top":40,"x1":500,"bottom":500},
            "continuation_of_segment_id":"SEGMENT_PRIMARY",
            "header_signature":{"columns":["2025","2024"]},
            "period_signature":{"periods":["2025","2024"]},
            "amount_lane_signature":{"lane_count":2},
            "confidence":0.97,
            "evidence":{"relation":"TOPOLOGY_AND_PAGE_ADJACENCY"},
        },
    ]


def _enriched(candidate:dict):
    return {
        **candidate,
        "container_page_range":[195,197],
        "possible_subtable_roles":["PRIMARY_AMOUNT_DETAIL"],
        "scope_evidence":{"requested":"CONSOLIDATED"},
        "period_evidence":{"years":["2025","2024"]},
        "unit_evidence":{"unit":"CNY_MILLION"},
        "lightweight_table_presence":True,
        "lightweight_header_signature":["2025","2024"],
        "lightweight_row_signature":["债权投资"],
        "amount_summary":{"number_count":2},
        "reconciliation_candidates":[{
            "relation":"EXACT_TOTAL","status":"PASS_EXACT",
        }],
        "certification_score":0.99,
        "score_breakdown":{
            "evidence_score":0.99,"penalties":0.0,
            "final_certification_score":0.99,
        },
        "hard_gate_results":{"note_table_inventory_complete":True},
        "positive_evidence":["NOTE_TABLE_INVENTORY_COMPLETE"],
        "negative_evidence":[],
        "enrichment_runtime_ms":1.0,
    }


def _complete_signature_coverage():
    return {
        "page_bbox":True,
        "period":True,
        "header":True,
        "amount_lanes":True,
        "source":"BOUNDED_NATIVE_TEXT",
    }


def _candidate_inventory(candidate:dict):
    logical_id="LTABLE_CANDIDATE_13"
    primary_segment_id="SEG_CAND_PRIMARY"
    continuation_segment_id="SEG_CAND_CONT"
    return {
        "note_table_inventory_candidate_id":"NTINV_CANDIDATE_13",
        "candidate_id":candidate["candidate_id"],
        "source_pdf_id":candidate["source_pdf_id"],
        "source_pdf_sha256":candidate["source_pdf_sha256"],
        "note_reference":candidate["note_reference"],
        "note_title":candidate["raw_heading"],
        "scan_start_page":195,
        "scan_end_page":197,
        "next_note_boundary_page":197,
        "peer_table_count":1,
        "scan_scope":{
            "boundary_status":"CONFIRMED_PEER_HEADING",
            "next_note_boundary_bbox":{"x0":10,"y0":400,"x1":200,"y1":420},
        },
        "inventory_status":"COMPLETE",
        "evidence":{
            "peer_table_boundary":{
                "classification":"PEER_TABLE","note_reference":"附注14",
                "title":"14 其他债权投资","page":197,
                "bbox":{"x0":10,"y0":400,"x1":200,"y1":420},
            },
        },
        "logical_tables":[{
            "logical_table_candidate_id":logical_id,
            "table_order":0,
            "classification":"PRIMARY_TABLE",
            "title":"13 债权投资",
            "start_page":195,
            "end_page":196,
            "bbox":{"pages":[195,196]},
            "signature":{"periods":["2025","2024"],"lane_count":2},
            "evidence":{"source":"NATIVE_PDF_LINES"},
            "confidence":0.99,
            "status":"READY",
            "segments":[{
                "segment_candidate_id":primary_segment_id,
                "logical_table_candidate_id":logical_id,
                "segment_order":0,
                "classification":"PRIMARY_TABLE",
                "start_page":195,"end_page":195,
                "bbox":{"page":195,"x0":10,"y0":50,"x1":500,"y1":700},
                "period_signature":{"period_labels":["2025","2024"]},
                "header_signature":{"labels":["2025","2024"],"leaf_count":2},
                "amount_lane_signature":{"lane_count":2,"anchor_ratios":[0.7,0.9]},
                "evidence":{
                    "source":"NATIVE_PDF_LINES",
                    "signature_coverage":_complete_signature_coverage(),
                },
                "confidence":0.99,"status":"READY",
            },{
                "segment_candidate_id":continuation_segment_id,
                "logical_table_candidate_id":logical_id,
                "segment_order":1,
                "classification":"CONTINUATION_SEGMENT",
                "start_page":196,"end_page":196,
                "bbox":{"page":196,"x0":10,"y0":40,"x1":500,"y1":500},
                "continuation_of_segment_candidate_id":primary_segment_id,
                "period_signature":{"period_labels":["2025","2024"]},
                "header_signature":{"labels":["2025","2024"],"leaf_count":2},
                "amount_lane_signature":{"lane_count":2,"anchor_ratios":[0.7,0.9]},
                "evidence":{
                    "source":"NATIVE_PDF_LINES",
                    "signature_coverage":_complete_signature_coverage(),
                },
                "confidence":0.97,"status":"READY",
            }],
        }],
    }


def _seed_and_certify_inventory(repository:ChildDiscoveryRepository):
    candidate=_seed_candidate(repository)
    inventory=_candidate_inventory(candidate)
    repository.save_enriched(_enriched(candidate),inventory=inventory)
    certified_inventory=repository.certify_note_table_inventory(
        inventory["note_table_inventory_candidate_id"],
        reviewer="reviewer",method="MANUAL_CERTIFY",reason="PDF structure reviewed",
    )
    return candidate,inventory,certified_inventory


def _supplementary_logical_candidate():
    logical_id="LTABLE_CANDIDATE_13_ECL"
    return {
        "logical_table_candidate_id":logical_id,
        "table_order":1,
        "classification":"SUPPLEMENTARY_TABLE",
        "title":"债权投资信用损失准备变动情况",
        "start_page":196,"end_page":196,
        "bbox":{"pages":[196]},
        "signature":{"periods":["2025"],"lane_count":4},
        "evidence":{"source":"NATIVE_PDF_LINES"},
        "confidence":0.96,"status":"READY",
        "segments":[{
            "segment_candidate_id":"SEG_CAND_ECL",
            "logical_table_candidate_id":logical_id,
            "segment_order":0,
            "classification":"SUPPLEMENTARY_TABLE",
            "start_page":196,"end_page":196,
            "bbox":{"page":196,"x0":10,"y0":520,"x1":500,"y1":700},
            "period_signature":{"period_labels":["2025"]},
            "header_signature":{
                "labels":["第一阶段","第二阶段","第三阶段","合计"],
                "leaf_count":4,
            },
            "amount_lane_signature":{
                "lane_count":4,"anchor_ratios":[0.4,0.58,0.75,0.9],
            },
            "evidence":{
                "source":"NATIVE_PDF_LINES",
                "signature_coverage":_complete_signature_coverage(),
                "consistency_audit":{
                    "note_identity_match":True,
                    "table_identity_match":False,
                    "topology_match":False,
                    "amount_lane_match":False,
                    "period_match":False,
                },
                "reason_codes":[
                    "INDEPENDENT_LOCAL_HEADER",
                    "AMOUNT_LANE_TOPOLOGY_RESET",
                    "PERIOD_AXIS_RESET",
                ],
            },
            "confidence":0.96,"status":"READY",
        }],
    }


def test_new_certification_requires_discovered_logical_table(tmp_path:Path):
    registry,repository=_repository(tmp_path)
    _seed_candidate(repository)

    with pytest.raises(
        PermissionError,match="LOGICAL_TABLE_CANDIDATE_REQUIRED",
    ):
        repository.certify(
            _link(),reviewer="reviewer",method="SELECT_RECOMMENDED",
        )
    with registry.connect() as conn:
        assert conn.execute(
            "SELECT COUNT(*) FROM certified_child_table_links"
        ).fetchone()[0]==0


def test_explicit_certified_segments_cannot_bypass_discovery(tmp_path:Path):
    _,repository=_repository(tmp_path)
    _seed_candidate(repository)
    with pytest.raises(
        PermissionError,
        match="CERTIFIED_SEGMENTS_MUST_PROMOTE_DISCOVERED_CANDIDATES",
    ):
        repository.certify(
            _link(),reviewer="reviewer",method="MANUAL_CERTIFY",
            certified_segments=_segments(),
        )


def test_incomplete_unresolved_inventory_persists_without_legacy_link(
    tmp_path:Path,
):
    registry,repository=_repository(tmp_path)
    candidate=_seed_candidate(repository)
    inventory=_candidate_inventory(candidate)
    inventory["inventory_status"]="INCOMPLETE"
    logical=inventory["logical_tables"][0]
    logical["classification"]="UNRESOLVED"
    logical["status"]="REVIEW_REQUIRED"
    logical["segments"][0]["classification"]="UNRESOLVED"
    logical["segments"][0]["status"]="REVIEW_REQUIRED"
    repository.save_enriched(_enriched(candidate),inventory=inventory)

    persisted=repository.candidate_inventory(candidate["candidate_id"])
    assert persisted is not None
    assert persisted["inventory_status"]=="INCOMPLETE"
    assert persisted["unresolved_table_count"]==1
    with pytest.raises(
        PermissionError,match="INCOMPLETE_NOTE_TABLE_INVENTORY_NOT_CERTIFIABLE",
    ):
        repository.certify_note_table_inventory(
            inventory["note_table_inventory_candidate_id"],
            reviewer="reviewer",method="MANUAL_CERTIFY",
        )

    service=HierarchicalChildTableDiscoveryService(
        repository,FinancialNoteIndexService(repository),
    )
    links=service.link_candidates(
        {"occurrence_id":"ANCHOR_FIXTURE"},
        {
            "anchor_child_id":"ANCHOR_CHILD_FIXTURE",
            "raw_label":"债权投资","statement_scope":"CONSOLIDATED",
            "report_year":"2025","inline_note_reference":"附注13",
        },
        [repository.cached_enriched(candidate["candidate_id"])],
        {"member_table_id":"debt_investment","canonical_title":"债权投资"},
    )
    assert links==[]
    with registry.connect() as conn:
        assert conn.execute(
            "SELECT COUNT(*) FROM child_table_link_candidates"
        ).fetchone()[0]==0


def _seed_unresolved_inventory(
    repository:ChildDiscoveryRepository,*,candidate_id:str="CANDIDATE_FIXTURE",
    suffix:str="",
):
    candidate=_seed_candidate(repository,candidate_id=candidate_id)
    inventory=_candidate_inventory(candidate)
    if suffix:
        inventory["note_table_inventory_candidate_id"]=(
            "NTINV_CANDIDATE_13_"+suffix
        )
        logical=inventory["logical_tables"][0]
        logical["logical_table_candidate_id"]="LTABLE_CANDIDATE_13_"+suffix
        primary,continuation=logical["segments"]
        primary["segment_candidate_id"]="SEG_CAND_PRIMARY_"+suffix
        primary["logical_table_candidate_id"]=(
            logical["logical_table_candidate_id"]
        )
        continuation["segment_candidate_id"]="SEG_CAND_CONT_"+suffix
        continuation["logical_table_candidate_id"]=(
            logical["logical_table_candidate_id"]
        )
        continuation["continuation_of_segment_candidate_id"]=(
            primary["segment_candidate_id"]
        )
    inventory["inventory_status"]="INCOMPLETE"
    logical=inventory["logical_tables"][0]
    logical["classification"]="UNRESOLVED"
    logical["status"]="REVIEW_REQUIRED"
    logical["segments"][0]["classification"]="UNRESOLVED"
    logical["segments"][0]["status"]="REVIEW_REQUIRED"
    repository.save_enriched(_enriched(candidate),inventory=inventory)
    case=repository.unresolved_inventory_cases(
        anchor_child_id=candidate["anchor_child_id"],
        candidate_ids=[candidate_id],
    )[0]
    return candidate,inventory,case


def _inventory_machine_rows(registry:MetadataRegistry,candidate_id:str):
    with registry.connect() as conn:
        logical=[tuple(row) for row in conn.execute(
            """SELECT logical_table_candidate_id,proposed_classification,
                      bbox_json,evidence_json,status,created_at,updated_at
               FROM child_logical_table_candidates WHERE candidate_id=?
               ORDER BY table_order""",
            (candidate_id,),
        ).fetchall()]
        segments=[tuple(row) for row in conn.execute(
            """SELECT s.segment_candidate_id,s.logical_table_candidate_id,
                      s.proposed_classification,s.start_page,s.end_page,
                      s.bbox_json,s.continuation_of_segment_candidate_id,
                      s.evidence_json,s.status,s.created_at,s.updated_at
               FROM child_table_segment_candidates s
               JOIN child_logical_table_candidates l
                 ON l.logical_table_candidate_id=s.logical_table_candidate_id
               WHERE l.candidate_id=? ORDER BY l.table_order,s.segment_order""",
            (candidate_id,),
        ).fetchall()]
    return logical,segments


def test_unresolved_case_adjudication_is_semantic_append_only_and_certifiable(
    tmp_path:Path,
):
    registry,repository=_repository(tmp_path)
    candidate,inventory,case=_seed_unresolved_inventory(repository)
    assert case["case_status"]=="OPEN"
    assert case["resolution_state"]=="UNRESOLVED"
    assert repository.unresolved_inventory_cases(
        candidate_ids=[candidate["candidate_id"]]
    )[0]["resolution_case_id"]==case["resolution_case_id"]
    before=_inventory_machine_rows(registry,candidate["candidate_id"])

    logical=inventory["logical_tables"][0]
    root_segment=logical["segments"][0]
    adjudication=repository.adjudicate_inventory_case(
        case["resolution_case_id"],reviewer="reviewer",
        reason="直接核对现有候选的表意维度",
        decisions={
            "logical_tables":[{
                "logical_table_candidate_id":logical[
                    "logical_table_candidate_id"
                ],
                "classification":"PRIMARY_TABLE",
            }],
            "segments":[{
                "segment_candidate_id":root_segment["segment_candidate_id"],
                "logical_table_candidate_id":logical[
                    "logical_table_candidate_id"
                ],
                "classification":"PRIMARY_TABLE",
                "continuation_of_segment_candidate_id":None,
            }],
        },
    )
    assert _inventory_machine_rows(registry,candidate["candidate_id"])==before
    assert repository.candidate_inventory(candidate["candidate_id"])[
        "inventory_status"
    ]=="INCOMPLETE"
    effective=repository.effective_candidate_inventory(
        candidate["candidate_id"]
    )
    assert effective["inventory_status"]=="COMPLETE"
    assert effective["unresolved_table_count"]==0
    assert effective["logical_tables"][0]["classification"]=="PRIMARY_TABLE"
    assert effective["logical_tables"][0]["segments"][1][
        "classification"
    ]=="CONTINUATION_SEGMENT"

    certified=repository.certify_note_table_inventory(
        inventory["note_table_inventory_candidate_id"],
        reviewer="reviewer",method="HUMAN_INVENTORY_ADJUDICATION_V1",
        source_adjudication_id=adjudication["adjudication_id"],
    )
    assert certified["source_adjudication_id"]==adjudication["adjudication_id"]
    service=HierarchicalChildTableDiscoveryService(
        repository,FinancialNoteIndexService(repository),
    )
    links=service.link_candidates(
        {"occurrence_id":"ANCHOR_FIXTURE","table_family":"financial_investment"},
        {
            "anchor_child_id":"ANCHOR_CHILD_FIXTURE",
            "raw_label":"债权投资","statement_scope":"CONSOLIDATED",
            "report_year":"2025","inline_note_reference":"附注13",
        },
        [repository.cached_enriched(candidate["candidate_id"])],
        {"member_table_id":"debt_investment","canonical_title":"债权投资"},
    )
    assignment=service.assign_global(
        "ANCHOR_FIXTURE","CONSOLIDATED",
        {"ANCHOR_CHILD_FIXTURE":links},
    )
    assert assignment["decisions"][0]["status"]=="AUTO_CERTIFIED"
    assert len(assignment["certified_links"])==1
    assert adjudication["learning_candidate"]["status"]=="PROPOSED"
    assert list_structural_learning_candidates(
        registry,source_pdf_sha256=candidate["source_pdf_sha256"],
        discovery_run_id="OTHER_RUN",
    )==[]
    assert list_structural_learning_candidates(
        registry,source_pdf_sha256="OTHER_SHA",
        discovery_run_id="OTHER_RUN",
    )[0]["source_adjudication_id"]==adjudication["adjudication_id"]
    with pytest.raises(ValueError,match="TARGET_SOURCE_CONTEXT_REQUIRED"):
        list_structural_learning_candidates(registry)
    with registry.connect() as conn:
        with pytest.raises(
            sqlite3.IntegrityError,
            match="CHILD_INVENTORY_ADJUDICATION_APPEND_ONLY",
        ):
            conn.execute(
                """UPDATE child_inventory_adjudications
                   SET reason='overwrite' WHERE adjudication_id=?""",
                (adjudication["adjudication_id"],),
            )
        with pytest.raises(
            sqlite3.IntegrityError,
            match="STRUCTURAL_LEARNING_CANDIDATE_APPEND_ONLY",
        ):
            conn.execute(
                """DELETE FROM structural_learning_candidates
                   WHERE source_adjudication_id=?""",
                (adjudication["adjudication_id"],),
            )


@pytest.mark.parametrize("forbidden_key",[
    "page","start_page","end_page","bbox","source_pdf_id",
    "segment_manifest",
])
def test_inventory_adjudication_rejects_physical_input(
    tmp_path:Path,forbidden_key:str,
):
    registry,repository=_repository(tmp_path)
    _,inventory,case=_seed_unresolved_inventory(repository)
    logical=inventory["logical_tables"][0]
    with pytest.raises(ValueError,match="ADJUDICATION_SEMANTIC_FIELDS_ONLY"):
        repository.adjudicate_inventory_case(
            case["resolution_case_id"],reviewer="reviewer",reason="test",
            decisions={
                "logical_tables":[{
                    "logical_table_candidate_id":logical[
                        "logical_table_candidate_id"
                    ],
                    "classification":"PRIMARY_TABLE",
                    forbidden_key:"FORBIDDEN",
                }],
            },
        )
    with registry.connect() as conn:
        assert conn.execute(
            "SELECT COUNT(*) FROM child_inventory_adjudications"
        ).fetchone()[0]==0
        assert conn.execute(
            "SELECT COUNT(*) FROM structural_learning_candidates"
        ).fetchone()[0]==0


def test_inventory_adjudication_rejects_cross_inventory_candidate_ids(
    tmp_path:Path,
):
    registry,repository=_repository(tmp_path)
    _,first_inventory,first_case=_seed_unresolved_inventory(repository)
    _,second_inventory,_=_seed_unresolved_inventory(
        repository,candidate_id="CANDIDATE_SECOND",suffix="SECOND",
    )
    first_logical=first_inventory["logical_tables"][0]
    second_logical=second_inventory["logical_tables"][0]
    with pytest.raises(
        PermissionError,match="LOGICAL_CANDIDATE_NOT_IN_INVENTORY_CASE",
    ):
        repository.adjudicate_inventory_case(
            first_case["resolution_case_id"],reviewer="reviewer",reason="test",
            decisions={
                "logical_tables":[{
                    "logical_table_candidate_id":second_logical[
                        "logical_table_candidate_id"
                    ],
                    "classification":"PRIMARY_TABLE",
                }],
                "segments":[{
                    "segment_candidate_id":first_logical["segments"][0][
                        "segment_candidate_id"
                    ],
                    "logical_table_candidate_id":first_logical[
                        "logical_table_candidate_id"
                    ],
                    "classification":"PRIMARY_TABLE",
                    "continuation_of_segment_candidate_id":None,
                }],
            },
        )
    with registry.connect() as conn:
        assert conn.execute(
            "SELECT COUNT(*) FROM child_inventory_adjudications"
        ).fetchone()[0]==0


def test_manual_candidate_and_legacy_mapping_actions_are_forbidden(
    tmp_path:Path,
):
    _,repository=_repository(tmp_path)
    service=HierarchicalChildTableDiscoveryService(
        repository,FinancialNoteIndexService(repository),
    )
    with pytest.raises(
        PermissionError,match="MANUAL_CHILD_TABLE_CANDIDATE_FORBIDDEN",
    ):
        service.manual_add_candidate(
            tmp_path/"missing.pdf",{}, {}, {},"CONSOLIDATED",
            page=1,title="债权投资",
        )
    with pytest.raises(PermissionError,match="MANUAL_ADD_LINK_FORBIDDEN"):
        repository.review_mapping(
            "ANCHOR_CHILD_FIXTURE","MANUAL_ADD_LINK",reviewer="reviewer",
        )


def test_human_review_queue_requires_open_unresolved_inventory_case(
    tmp_path:Path,
):
    registry,repository=_repository(tmp_path)
    service=HierarchicalChildTableDiscoveryService(
        repository,FinancialNoteIndexService(repository),
    )
    assignment=service.assign_global(
        "ANCHOR_WITHOUT_CASE","CONSOLIDATED",{"UNKNOWN_CHILD":[]},
    )
    assert assignment["decisions"][0]["status"]=="AUTOMATION_REPAIR_REQUIRED"
    with registry.connect() as conn:
        assert conn.execute(
            "SELECT COUNT(*) FROM child_mapping_review_queue"
        ).fetchone()[0]==0

    _,_,case=_seed_unresolved_inventory(repository)
    assignment=service.assign_global(
        "ANCHOR_FIXTURE","CONSOLIDATED",{"ANCHOR_CHILD_FIXTURE":[]},
    )
    assert assignment["decisions"][0]["status"]==(
        "UNRESOLVED_INVENTORY_REVIEW_REQUIRED"
    )
    with registry.connect() as conn:
        queued=dict(conn.execute(
            "SELECT * FROM child_mapping_review_queue"
        ).fetchone())
    assert queued["resolution_case_id"]==case["resolution_case_id"]
    with pytest.raises(
        PermissionError,match="OPEN_UNRESOLVED_INVENTORY_CASE_REQUIRED",
    ):
        repository.enqueue_child_review(
            anchor_id="ANCHOR_FIXTURE",
            anchor_child_id="ANCHOR_CHILD_FIXTURE",
            logical_asset_id="",source_pdf_id="PDF_FIXTURE",
            statement_scope="CONSOLIDATED",candidate_ids=[],
            resolution_case_id="MISSING_CASE",reason="test",evidence={},
        )


def test_invalid_segment_relations_fail_before_link_insert(tmp_path:Path):
    registry,repository=_repository(tmp_path)
    candidate=_seed_candidate(repository)
    inventory=_candidate_inventory(candidate)
    inventory["logical_tables"][0]["segments"][0][
        "classification"
    ]="SUPPLEMENTARY_TABLE"
    with pytest.raises(
        ValueError,match="LOGICAL_TABLE_ROOT_SEGMENT_CLASSIFICATION_MISMATCH",
    ):
        repository.save_enriched(_enriched(candidate),inventory=inventory)
    with registry.connect() as conn:
        count=conn.execute(
            "SELECT COUNT(*) FROM certified_child_table_links"
        ).fetchone()[0]
        inventory_count=conn.execute(
            "SELECT COUNT(*) FROM child_note_table_inventories"
        ).fetchone()[0]
    assert count==0
    assert inventory_count==0


def test_logical_candidate_segments_are_promoted_with_remapped_parent(
    tmp_path:Path,
):
    _,repository=_repository(tmp_path)
    _,inventory,certified_inventory=_seed_and_certify_inventory(repository)

    certified=repository.certify(
        {**_link(),"logical_table_candidate_id":"LTABLE_CANDIDATE_13"},
        reviewer="reviewer",method="CERTIFY_LOGICAL_TABLE_CANDIDATE",
    )
    target=repository.certified_target(certified["certified_link_id"])

    assert target["logical_table_candidate_id"]=="LTABLE_CANDIDATE_13"
    assert target["logical_table_id"]=="LTABLE_CANDIDATE_13"
    assert target["segment_manifest_status"]=="CERTIFIED_SEGMENT_MANIFEST"
    assert target["note_table_inventory_id"]==certified_inventory[
        "note_table_inventory_id"
    ]
    assert target["note_table_inventory_status"]=="COMPLETE"
    assert target["confirmed_note_pdf_page_index"]==195
    assert target["end_page"]==196
    primary,continuation=target["certified_segments"]
    assert continuation["continuation_of_segment_id"]==primary[
        "certified_segment_id"
    ]
    assert primary["evidence"]["source_segment_candidate_id"]==(
        "SEG_CAND_PRIMARY"
    )
    cached=repository.candidate_inventory(inventory[
        "candidate_id"
    ])
    assert cached["note_table_inventory_candidate_id"]==(
        "NTINV_CANDIDATE_13"
    )
    assert [item["classification"] for item in cached["logical_tables"]]==[
        "PRIMARY_TABLE",
    ]


def test_one_enriched_note_inventory_expands_to_independent_logical_links(
    tmp_path:Path,
):
    registry,repository=_repository(tmp_path)
    candidate=_seed_candidate(repository)
    inventory=_candidate_inventory(candidate)
    inventory["logical_tables"].append(_supplementary_logical_candidate())
    repository.save_enriched(_enriched(candidate),inventory=inventory)
    enriched=repository.cached_enriched(candidate["candidate_id"])
    service=HierarchicalChildTableDiscoveryService(
        repository,FinancialNoteIndexService(repository),
    )
    anchor={"occurrence_id":"ANCHOR_FIXTURE"}
    child={
        "anchor_child_id":"ANCHOR_CHILD_FIXTURE",
        "raw_label":"债权投资","statement_scope":"CONSOLIDATED",
        "report_year":"2025","inline_note_reference":"附注13",
    }
    links=service.link_candidates(
        anchor,child,[enriched],
        {"member_table_id":"debt_investment","canonical_title":"债权投资"},
    )

    assert [item["table_classification"] for item in links]==[
        "PRIMARY_TABLE","SUPPLEMENTARY_TABLE",
    ]
    assert [item["logical_table_candidate_id"] for item in links]==[
        "LTABLE_CANDIDATE_13","LTABLE_CANDIDATE_13_ECL",
    ]
    assert links[1]["proposed_subtable_role"]=="LOSS_ALLOWANCE_ROLLFORWARD"
    with registry.connect() as conn:
        persisted=conn.execute(
            """SELECT logical_table_candidate_id
               FROM child_table_link_candidates ORDER BY ranking_position"""
        ).fetchall()
    assert [row[0] for row in persisted]==[
        "LTABLE_CANDIDATE_13","LTABLE_CANDIDATE_13_ECL",
    ]


def test_unique_complete_inventory_auto_certifies_all_logical_links_idempotently(
    tmp_path:Path,
):
    registry,repository=_repository(tmp_path)
    candidate=_seed_candidate(repository)
    inventory=_candidate_inventory(candidate)
    inventory["logical_tables"].append(_supplementary_logical_candidate())
    repository.save_enriched(_enriched(candidate),inventory=inventory)
    service=HierarchicalChildTableDiscoveryService(
        repository,FinancialNoteIndexService(repository),
    )
    anchor={
        "occurrence_id":"ANCHOR_FIXTURE",
        "table_family":"financial_investment",
    }
    child={
        "anchor_child_id":"ANCHOR_CHILD_FIXTURE",
        "raw_label":"债权投资","statement_scope":"CONSOLIDATED",
        "report_year":"2025","inline_note_reference":"附注13",
        "research_definition_id":"RD_FIXTURE",
        "definition_version":"1.0",
    }
    links=service.link_candidates(
        anchor,child,[repository.cached_enriched(candidate["candidate_id"])],
        {"member_table_id":"debt_investment","canonical_title":"债权投资"},
    )

    first=service.assign_global(
        anchor["occurrence_id"],"CONSOLIDATED",
        {child["anchor_child_id"]:links},
    )
    second=service.assign_global(
        anchor["occurrence_id"],"CONSOLIDATED",
        {child["anchor_child_id"]:links},
    )

    assert first["decisions"][0]["status"]=="AUTO_CERTIFIED"
    assert len(first["certified_links"])==2
    assert second["decisions"][0]["status"]=="AUTO_CERTIFIED"
    assert {
        item["certified_link_id"] for item in first["certified_links"]
    }=={
        item["certified_link_id"] for item in second["certified_links"]
    }
    with registry.connect() as conn:
        assert conn.execute(
            "SELECT COUNT(*) FROM certified_note_table_inventories"
        ).fetchone()[0]==1
        assert conn.execute(
            "SELECT COUNT(*) FROM certified_child_table_links"
        ).fetchone()[0]==2
        methods={row[0] for row in conn.execute(
            "SELECT certification_method FROM certified_child_table_links"
        ).fetchall()}
    assert methods=={"AUTO_PROMOTE_CERTIFIED_LOGICAL_TABLE_V1"}


def test_recertification_of_certified_note_container_adopts_existing_links(
    tmp_path:Path,
):
    """Re-discovery of the same note container reuses certified evidence.

    A second anchor run for the same PDF and note ordinal creates a fresh
    candidate/inventory tree with new candidate IDs.  When the container is
    content-equivalent (same member tables/classifications) and the PDF digest
    has not drifted, auto-certification must adopt the existing certified
    links instead of failing with ``NOTE_TABLE_INVENTORY_ID_MISMATCH`` and
    leaving Stage B with no certified plans.
    """
    registry,repository=_repository(tmp_path)
    service=HierarchicalChildTableDiscoveryService(
        repository,FinancialNoteIndexService(repository),
    )
    contract={"member_table_id":"debt_investment","canonical_title":"债权投资"}

    # First certification: container 附注13 under anchor A.
    candidate=_seed_candidate(repository)
    inventory=_candidate_inventory(candidate)
    repository.save_enriched(_enriched(candidate),inventory=inventory)
    anchor_a={"occurrence_id":"ANCHOR_FIXTURE_A",
              "table_family":"financial_investment"}
    child_a={"anchor_child_id":"ANCHOR_CHILD_FIXTURE_A",
             "raw_label":"债权投资","statement_scope":"CONSOLIDATED",
             "report_year":"2025","inline_note_reference":"附注13",
             "research_definition_id":"RD_FIXTURE","definition_version":"1.0"}
    links_a=service.link_candidates(
        anchor_a,child_a,
        [repository.cached_enriched(candidate["candidate_id"])],contract,
    )
    first=service.assign_global(
        anchor_a["occurrence_id"],"CONSOLIDATED",
        {child_a["anchor_child_id"]:links_a},
    )
    assert first["decisions"][0]["status"]=="AUTO_CERTIFIED"
    assert len(first["certified_links"])==1

    # Re-discovery under a new anchor: fresh candidate/inventory/logical ids,
    # same PDF digest and note ordinal, same member/classification set.
    candidate_b=_seed_candidate(
        repository,
        candidate_id="CANDIDATE_FIXTURE_B",
        note_reference="附注13",
        anchor_child_id="ANCHOR_CHILD_FIXTURE_B",
    )
    inventory_b=_candidate_inventory(candidate_b)
    inventory_b["note_table_inventory_candidate_id"]=(
        "NTINV_CANDIDATE_13_NEW"
    )
    inventory_b["logical_tables"][0]["logical_table_candidate_id"]=(
        "LTABLE_CANDIDATE_13_NEW"
    )
    segment_map={
        "SEG_CAND_PRIMARY":"SEG_CAND_PRIMARY_NEW",
        "SEG_CAND_CONT":"SEG_CAND_CONT_NEW",
    }
    for segment in inventory_b["logical_tables"][0]["segments"]:
        segment["segment_candidate_id"]=segment_map[
            segment["segment_candidate_id"]
        ]
        segment["logical_table_candidate_id"]="LTABLE_CANDIDATE_13_NEW"
        parent=segment.get("continuation_of_segment_candidate_id")
        if parent:
            segment["continuation_of_segment_candidate_id"]=segment_map[parent]
    repository.save_enriched(_enriched(candidate_b),inventory=inventory_b)
    anchor_b={"occurrence_id":"ANCHOR_FIXTURE_B",
              "table_family":"financial_investment"}
    child_b={"anchor_child_id":"ANCHOR_CHILD_FIXTURE_B",
             "raw_label":"债权投资","statement_scope":"CONSOLIDATED",
             "report_year":"2025","inline_note_reference":"附注13",
             "research_definition_id":"RD_FIXTURE","definition_version":"1.0"}
    links_b=service.link_candidates(
        anchor_b,child_b,
        [repository.cached_enriched(candidate_b["candidate_id"])],contract,
    )
    second=service.assign_global(
        anchor_b["occurrence_id"],"CONSOLIDATED",
        {child_b["anchor_child_id"]:links_b},
    )

    assert second["decisions"][0]["status"]=="AUTO_CERTIFIED"
    assert len(second["certified_links"])==1
    assert second["certified_links"][0]["certified_link_id"]==(
        first["certified_links"][0]["certified_link_id"]
    )
    with registry.connect() as conn:
        assert conn.execute(
            "SELECT COUNT(*) FROM certified_note_table_inventories"
        ).fetchone()[0]==1
        assert conn.execute(
            "SELECT COUNT(*) FROM certified_child_table_links"
        ).fetchone()[0]==1


def test_incomplete_supplementary_signature_cannot_auto_certify(
    tmp_path:Path,
):
    registry,repository=_repository(tmp_path)
    candidate=_seed_candidate(repository)
    inventory=_candidate_inventory(candidate)
    supplementary=_supplementary_logical_candidate()
    supplementary["segments"][0]["evidence"]["signature_coverage"][
        "period"
    ]=False
    inventory["logical_tables"].append(supplementary)
    repository.save_enriched(_enriched(candidate),inventory=inventory)
    service=HierarchicalChildTableDiscoveryService(
        repository,FinancialNoteIndexService(repository),
    )
    anchor={
        "occurrence_id":"ANCHOR_FIXTURE",
        "table_family":"financial_investment",
    }
    child={
        "anchor_child_id":"ANCHOR_CHILD_FIXTURE",
        "raw_label":"债权投资","statement_scope":"CONSOLIDATED",
        "report_year":"2025","inline_note_reference":"附注13",
    }
    links=service.link_candidates(
        anchor,child,[repository.cached_enriched(candidate["candidate_id"])],
        {"member_table_id":"debt_investment","canonical_title":"债权投资"},
    )

    assignment=service.assign_global(
        anchor["occurrence_id"],"CONSOLIDATED",
        {child["anchor_child_id"]:links},
    )

    assert assignment["decisions"][0]["status"]=="AUTOMATION_REPAIR_REQUIRED"
    assert assignment["decisions"][0]["unresolved_reason"]==(
        "AUTOMATIC_SEGMENT_SIGNATURE_COVERAGE_REQUIRED"
    )
    with registry.connect() as conn:
        assert conn.execute(
            "SELECT COUNT(*) FROM certified_note_table_inventories"
        ).fetchone()[0]==0
        assert conn.execute(
            "SELECT COUNT(*) FROM certified_child_table_links"
        ).fetchone()[0]==0


def test_same_note_requires_one_inventory_id(tmp_path:Path):
    _,repository=_repository(tmp_path)
    _,_,certified_inventory=_seed_and_certify_inventory(repository)
    repository.certify(
        {
            **_link(),"logical_table_candidate_id":"LTABLE_CANDIDATE_13",
            "note_table_inventory_id":certified_inventory[
                "note_table_inventory_id"
            ],
            "note_table_inventory_status":"COMPLETE",
        },
        reviewer="reviewer",method="MANUAL_CERTIFY",
    )
    with pytest.raises(ValueError,match="NOTE_TABLE_INVENTORY_ID_MISMATCH"):
        repository.certify(
            {
                **_link(),"logical_table_candidate_id":"LTABLE_CANDIDATE_13",
                "note_table_inventory_id":"OTHER_INVENTORY_13",
                "note_table_inventory_status":"COMPLETE",
            },
            reviewer="reviewer",method="MANUAL_CERTIFY",
        )


def test_v15_migrates_legacy_link_and_creates_adjudication_tables(
    tmp_path:Path,
):
    database=tmp_path/"legacy.db"
    with sqlite3.connect(database) as conn:
        conn.execute("""CREATE TABLE schema_meta(
            key TEXT PRIMARY KEY,value TEXT NOT NULL,updated_at TEXT NOT NULL
        )""")
        conn.execute(
            "INSERT INTO schema_meta VALUES(?,?,?)",
            ("registry_schema_version","14",now_iso()),
        )
        conn.execute("""CREATE TABLE child_mapping_review_queue(
            queue_id TEXT PRIMARY KEY,anchor_id TEXT NOT NULL,
            anchor_child_id TEXT NOT NULL,logical_asset_id TEXT,
            source_pdf_id TEXT NOT NULL,statement_scope TEXT NOT NULL,
            status TEXT NOT NULL,primary_review_reason TEXT NOT NULL,
            candidate_ids_json TEXT NOT NULL,evidence_json TEXT NOT NULL,
            producer_version TEXT NOT NULL,created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            UNIQUE(anchor_child_id,statement_scope)
        )""")
        conn.execute("""CREATE TABLE certified_note_table_inventories(
            note_table_inventory_id TEXT PRIMARY KEY,
            note_table_inventory_candidate_id TEXT,
            source_pdf_id TEXT NOT NULL,source_pdf_sha256 TEXT NOT NULL,
            note_reference TEXT NOT NULL,note_title TEXT NOT NULL,
            scan_start_page INTEGER NOT NULL,scan_end_page INTEGER NOT NULL,
            next_note_boundary_page INTEGER,logical_table_ids_json TEXT NOT NULL,
            inventory_snapshot_json TEXT NOT NULL,inventory_status TEXT NOT NULL,
            certification_method TEXT NOT NULL,certification_status TEXT NOT NULL,
            reviewer TEXT NOT NULL,certified_at TEXT NOT NULL,
            producer_version TEXT NOT NULL,created_at TEXT NOT NULL,
            UNIQUE(note_table_inventory_candidate_id)
        )""")
        conn.execute("""CREATE TABLE certified_child_table_links(
            certified_link_id TEXT PRIMARY KEY,
            member_table_id TEXT NOT NULL
        )""")
        conn.execute(
            "INSERT INTO certified_child_table_links VALUES(?,?)",
            ("CLINK_LEGACY","legacy_member"),
        )
    registry=MetadataRegistry(database)
    registry.initialize_schema()
    registry.initialize_schema()
    with registry.connect() as conn:
        link_columns={
            row[1] for row in conn.execute(
                "PRAGMA table_info(certified_child_table_links)"
            ).fetchall()
        }
        legacy=dict(conn.execute(
            """SELECT * FROM certified_child_table_links
               WHERE certified_link_id='CLINK_LEGACY'"""
        ).fetchone())
        tables={
            row[0] for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }
        logical_candidate_columns={
            row[1] for row in conn.execute(
                "PRAGMA table_info(child_logical_table_candidates)"
            ).fetchall()
        }
        segment_candidate_columns={
            row[1] for row in conn.execute(
                "PRAGMA table_info(child_table_segment_candidates)"
            ).fetchall()
        }
        certified_segment_columns={
            row[1] for row in conn.execute(
                "PRAGMA table_info(certified_child_table_segments)"
            ).fetchall()
        }
        inventory_candidate_columns={
            row[1] for row in conn.execute(
                "PRAGMA table_info(child_note_table_inventories)"
            ).fetchall()
        }
        certified_inventory_columns={
            row[1] for row in conn.execute(
                "PRAGMA table_info(certified_note_table_inventories)"
            ).fetchall()
        }
        link_candidate_columns={
            row[1] for row in conn.execute(
                "PRAGMA table_info(child_table_link_candidates)"
            ).fetchall()
        }
        review_queue_columns={
            row[1] for row in conn.execute(
                "PRAGMA table_info(child_mapping_review_queue)"
            ).fetchall()
        }
        triggers={
            row[0] for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='trigger'"
            ).fetchall()
        }
    assert {
        "logical_table_id","table_classification","segment_manifest_status",
        "note_table_inventory_id","note_table_inventory_status",
        "logical_table_candidate_id",
    }.issubset(link_columns)
    assert legacy["logical_table_id"]=="legacy_member"
    assert legacy["table_classification"]=="PRIMARY_TABLE"
    assert legacy["segment_manifest_status"]=="LEGACY_PRIMARY_ANCHOR_ONLY"
    assert legacy["note_table_inventory_status"]=="LEGACY_UNVERIFIED"
    assert {
        "child_note_table_inventories","child_logical_table_candidates",
        "child_table_segment_candidates","certified_note_table_inventories",
        "certified_child_table_segments","child_inventory_resolution_cases",
        "child_inventory_adjudications","structural_learning_candidates",
    }.issubset(tables)
    assert {
        "logical_table_candidate_id","candidate_id","table_order",
        "note_table_inventory_candidate_id",
        "proposed_classification","title","start_page","end_page",
        "bbox_json","signature_json","evidence_json","confidence",
        "status","producer_version","created_at","updated_at",
    }.issubset(logical_candidate_columns)
    assert {
        "segment_candidate_id","logical_table_candidate_id","segment_order",
        "proposed_classification","start_page","end_page","bbox_json",
        "continuation_of_segment_candidate_id","period_signature_json",
        "header_signature_json","amount_lane_signature_json","evidence_json",
        "confidence","status","producer_version","created_at","updated_at",
    }.issubset(segment_candidate_columns)
    assert {
        "certified_segment_id","certified_link_id","order","classification",
        "start_page","end_page","bbox_json","continuation_of_segment_id",
        "header_signature_json","period_signature_json",
        "amount_lane_signature_json","confidence","evidence_json",
        "certification_status","reviewer","certified_at","producer_version",
    }.issubset(certified_segment_columns)
    assert {
        "note_table_inventory_candidate_id","candidate_id","source_pdf_id",
        "source_pdf_sha256","note_reference","note_title",
        "scan_start_page","scan_end_page","next_note_boundary_page",
        "scan_scope_json","logical_table_count","peer_table_count",
        "unresolved_table_count","inventory_status","evidence_json",
        "producer_version","created_at","updated_at",
    }.issubset(inventory_candidate_columns)
    assert {
        "note_table_inventory_id","note_table_inventory_candidate_id",
        "source_pdf_id","source_pdf_sha256","note_reference","note_title",
        "scan_start_page","scan_end_page","next_note_boundary_page",
        "logical_table_ids_json","inventory_snapshot_json",
        "inventory_status","certification_method","certification_status",
        "source_adjudication_id","reviewer","certified_at",
        "producer_version","created_at",
    }.issubset(certified_inventory_columns)
    assert "logical_table_candidate_id" in link_candidate_columns
    assert "resolution_case_id" in review_queue_columns
    assert {
        "trg_child_inventory_adjudications_no_update",
        "trg_child_inventory_adjudications_no_delete",
        "trg_structural_learning_candidates_no_update",
        "trg_structural_learning_candidates_no_delete",
    }.issubset(triggers)
    assert registry.get_meta("registry_schema_version")==str(
        REGISTRY_SCHEMA_VERSION
    )=="15"


def test_v15_inventory_parents_are_idempotent_and_one_to_one(tmp_path:Path):
    registry=MetadataRegistry(tmp_path/"metadata.db")
    registry.initialize_schema()
    registry.initialize_schema()
    created_at=now_iso()
    with registry.connect() as conn:
        conn.execute(
            """INSERT INTO child_note_table_inventories(
               note_table_inventory_candidate_id,candidate_id,source_pdf_id,
               source_pdf_sha256,note_reference,note_title,scan_start_page,
               scan_end_page,next_note_boundary_page,scan_scope_json,
               logical_table_count,peer_table_count,unresolved_table_count,
               inventory_status,evidence_json,producer_version,created_at,
               updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                "INV_CANDIDATE","CANDIDATE_FIXTURE","PDF_FIXTURE",
                "SHA_FIXTURE","附注13","13 债权投资",195,197,198,"{}",
                2,1,0,"COMPLETE",'{"peer_retained":true}',APP_VERSION,
                created_at,created_at,
            ),
        )
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
                "INVENTORY_CERTIFIED","INV_CANDIDATE","PDF_FIXTURE",
                "SHA_FIXTURE","附注13","13 债权投资",195,197,198,
                '["LOGICAL_PRIMARY","LOGICAL_SUPPLEMENTARY"]',
                '{"peer_tables":["PEER_14"],"unresolved_tables":[]}',
                "COMPLETE","HUMAN_CONFIRMED","CERTIFIED","reviewer",
                created_at,APP_VERSION,created_at,
            ),
        )
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                """INSERT INTO certified_note_table_inventories(
                   note_table_inventory_id,note_table_inventory_candidate_id,
                   source_pdf_id,source_pdf_sha256,note_reference,note_title,
                   scan_start_page,scan_end_page,next_note_boundary_page,
                   logical_table_ids_json,inventory_snapshot_json,
                   inventory_status,certification_method,
                   certification_status,reviewer,certified_at,
                   producer_version,created_at
                   ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    "INVENTORY_DUPLICATE","INV_CANDIDATE","PDF_FIXTURE",
                    "SHA_FIXTURE","附注13","13 债权投资",195,197,198,
                    '["LOGICAL_PRIMARY"]','{}',"COMPLETE",
                    "HUMAN_CONFIRMED","CERTIFIED","reviewer",created_at,
                    APP_VERSION,created_at,
                ),
            )
