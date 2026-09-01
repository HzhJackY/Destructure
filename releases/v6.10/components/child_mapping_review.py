"""Human child-table mapping review inside the unified workspace."""
from __future__ import annotations

from pathlib import Path
from typing import Any

import pandas as pd


def _amount_text(row: dict[str, Any]) -> str:
    """Render persisted source amounts without treating an empty list as missing evidence."""
    value = row.get("statement_amount_normalized") or row.get("statement_amount_raw")
    if value in (None, "", "[]"):
        return "缺失（阻断认证）"
    if isinstance(value, str):
        return value
    return "；".join(str(item) for item in value) if isinstance(value, list) else str(value)


def render_child_mapping_review(st,backend,detail:dict[str,Any])->None:
    logical_asset_id=str(detail.get("logical_asset_id") or "")
    anchor_id=str(detail.get("statement_anchor_id") or detail.get("anchor_id") or "")
    rows=backend.child_discovery_repository.mapping_workspace(
        logical_asset_id=logical_asset_id,anchor_id=anchor_id,
    )
    st.subheader("子表映射")
    st.caption("以主报表子项为中心审核候选附注表。预选只是建议，只有人工确认后才形成 CertifiedChildTableLink。")
    if not rows:
        st.info("当前资产尚未生成 AnchorChildConcept 或子表候选。请先从研究引导抓取完成 Anchor 认证与分级发现。")
        return
    by_child={}
    for row in rows:by_child.setdefault(row["anchor_child_id"],[]).append(row)
    for child_id,candidates in by_child.items():
        base=candidates[0]
        with st.expander(
            f"{base['raw_label']}｜主表金额 {_amount_text(base)}｜"
            f"{base.get('statement_scope') or 'UNKNOWN'}",
            expanded=any(x.get("is_preselected") for x in candidates),
        ):
            available=[x for x in candidates if x.get("candidate_id")]
            if not available:
                st.warning("未找到对应子表候选。")
                if st.button("确认无对应子表",key=f"v610_no_child_{child_id}"):
                    backend.child_discovery_repository.review_mapping(
                        child_id,"NO_CORRESPONDING_CHILD_TABLE",reviewer="USER",
                        reason="人工确认无对应附注子表",
                    )
                    st.success("已记录。")
                manual_pdf=st.text_input(
                    "手动候选 PDF 路径",
                    value=str(detail.get("source_pdf_path") or ""),
                    key=f"v610_empty_manual_pdf_{child_id}",
                )
                manual_page=st.number_input(
                    "手动候选 PDF 页码",min_value=1,value=1,
                    key=f"v610_empty_manual_page_{child_id}",
                )
                manual_title=st.text_input(
                    "手动候选附注标题",value=base["raw_label"],
                    key=f"v610_empty_manual_title_{child_id}",
                )
                if st.button("从正式附注索引添加候选",key=f"v610_empty_manual_add_{child_id}"):
                    try:
                        backend.hierarchical_child_discovery_service.manual_add_candidate(
                            Path(manual_pdf),{"occurrence_id":base["anchor_id"]},base,
                            {"member_table_id":base["canonical_concept_id"],
                             "canonical_title":base["raw_label"],
                             "primary_subtable_roles":["PRIMARY_AMOUNT_DETAIL"]},
                            str(base.get("statement_scope") or "UNKNOWN"),
                            page=int(manual_page),title=manual_title,
                        )
                        st.success("已添加候选；请刷新后审核。")
                    except (ValueError,OSError) as exc:
                        st.error(f"未能添加：{exc}")
                continue
            primary=[x for x in available if x.get("proposed_subtable_role")=="PRIMARY_AMOUNT_DETAIL"]
            supplementary=[x for x in available if x.get("proposed_subtable_role")!="PRIMARY_AMOUNT_DETAIL"]
            if not primary:
                st.error("未找到可认证的主金额明细候选；不能以补充披露替代主表子项。")
                primary=available
            labels={
                f"{'推荐｜' if x.get('is_recommended') else ''}{x['certification_score']:.2f}｜"
                f"PDF {x['start_page']}｜{x['raw_heading']}｜{x['retrieval_method']}":x
                for x in primary
            }
            default=next((i for i,x in enumerate(labels.values()) if x.get("is_preselected")),0)
            selected_label=st.radio("主金额明细（必须选一张）",list(labels),index=default,key=f"v610_link_{child_id}")
            selected=labels[selected_label]
            selected_supplementary=[]
            if supplementary:
                st.caption("补充披露不参与主金额唯一分配；可按需独立认证。")
                for candidate in supplementary:
                    checked=st.checkbox(
                        f"补充｜{candidate['proposed_subtable_role']}｜{candidate['certification_score']:.2f}｜"
                        f"PDF {candidate['start_page']}｜{candidate['raw_heading']}",
                        value=bool(candidate.get("is_supplementary_recommended")),
                        key=f"v610_supp_select_{candidate['link_candidate_id']}",
                    )
                    if checked:
                        selected_supplementary.append(candidate)
            cols=st.columns([1.2,1])
            with cols[0]:
                pdf=Path(str(selected.get("source_pdf_id") or ""))
                if pdf.is_file():
                    from pdf_evidence import page_preview
                    preview=page_preview(pdf,int(selected["start_page"])-1,[selected["raw_heading"],base["raw_label"]])
                    if preview.get("status")=="OK":st.image(preview["png"],use_container_width=True)
                    else:st.warning("PDF 证据预览不可用。")
            with cols[1]:
                st.dataframe(pd.DataFrame([{
                    "召回层级":selected["retrieval_tier"],
                    "方法":selected["retrieval_method"],
                    "关系":selected.get("reconciliation_relation"),
                    "勾稽":selected.get("reconciliation_status"),
                    "角色":selected.get("proposed_subtable_role"),
                    "附注":selected.get("note_reference") or "无显式引用",
                    "警告":"、".join(selected.get("warning_codes") or selected.get("blocking_warnings") or []),
                }]),use_container_width=True,hide_index=True)
                with st.expander("评分与门禁证据",expanded=False):
                    st.json({"score":selected.get("score_breakdown"),
                             "hard_gates":selected.get("hard_gate_results")})
            reason=st.text_input("人工判断依据（可选）",key=f"v610_reason_{child_id}")
            actions=st.columns(4)
            if actions[0].button("确认推荐/所选",key=f"v610_confirm_{child_id}"):
                method="HUMAN_CONFIRMED_RECOMMENDATION" if selected.get("is_recommended") else "HUMAN_OVERRIDE"
                payload={
                        **selected,"table_family_id":detail.get("table_family_id") or "UNKNOWN",
                        "member_table_id":selected["proposed_member_table_id"],
                        "subtable_role":selected["proposed_subtable_role"],
                        "relation_type":selected["proposed_relation_type"],
                        "selected_candidate_id":selected["candidate_id"],
                        "recommended_candidate_id":next((x["candidate_id"] for x in available if x.get("is_recommended")),None),
                        "alternative_candidates":[x["candidate_id"] for x in available if x["candidate_id"]!=selected["candidate_id"]],
                        "score_snapshot":{"certification_score":selected["certification_score"],
                                          "breakdown":selected.get("score_breakdown")},
                        "evidence_snapshot":{"hard_gates":selected.get("hard_gate_results")},
                        "reconciliation_result":{"relation":selected.get("reconciliation_relation"),
                                                 "status":selected.get("reconciliation_status")},
                        "research_definition_id":detail.get("research_definition_id"),
                        "definition_version":detail.get("definition_version"),
                    }
                backend.child_discovery_repository.certify(
                    payload,reviewer="USER",method=method,reason=reason,
                )
                st.success("已认证主金额子表关系。")
            if actions[1].button("认证所选补充表",key=f"v610_supp_{child_id}"):
                if not selected_supplementary:
                    st.info("未选择补充表。")
                for candidate in selected_supplementary:
                    payload={
                        **candidate,"table_family_id":detail.get("table_family_id") or "UNKNOWN",
                        "member_table_id":candidate["proposed_member_table_id"],
                        "subtable_role":candidate["proposed_subtable_role"],
                        "relation_type":candidate["proposed_relation_type"],
                        "selected_candidate_id":candidate["candidate_id"],
                        "recommended_candidate_id":candidate["candidate_id"],
                        "alternative_candidates":[],
                        "score_snapshot":{"certification_score":candidate["certification_score"],"breakdown":candidate.get("score_breakdown")},
                        "evidence_snapshot":{"hard_gates":candidate.get("hard_gate_results")},
                        "reconciliation_result":{"relation":candidate.get("reconciliation_relation"),"status":candidate.get("reconciliation_status")},
                        "research_definition_id":detail.get("research_definition_id"),"definition_version":detail.get("definition_version"),
                    }
                    backend.child_discovery_repository.certify(payload,reviewer="USER",method="HUMAN_CONFIRMED_SUPPLEMENTARY",reason=reason)
                if selected_supplementary:
                    st.success(f"已认证 {len(selected_supplementary)} 个补充披露。")
            if actions[2].button("拒绝该候选",key=f"v610_reject_{child_id}"):
                backend.child_discovery_repository.review_mapping(
                    child_id,"REJECT_LINK",reviewer="USER",
                    selected_candidate_id=selected["candidate_id"],reason=reason,
                )
                st.success("已记录拒绝。")
            if actions[3].button("标记需要继续查找",key=f"v610_abstain_{child_id}"):
                backend.child_discovery_repository.review_mapping(
                    child_id,"ABSTAIN",reviewer="USER",reason=reason,
                )
                st.warning("已保留为待处理。")
            with st.expander("手动搜索并添加候选",expanded=False):
                manual_pdf=st.text_input(
                    "PDF 路径",
                    value=str(selected.get("source_pdf_id") or detail.get("source_pdf_path") or ""),
                    key=f"v610_manual_pdf_{child_id}",
                )
                manual_page=st.number_input(
                    "PDF 页码",min_value=1,value=max(1,int(selected.get("start_page") or 1)),
                    key=f"v610_manual_page_{child_id}",
                )
                manual_title=st.text_input(
                    "附注标题",value=str(selected.get("raw_heading") or base["raw_label"]),
                    key=f"v610_manual_title_{child_id}",
                )
                if st.button("从正式附注索引添加",key=f"v610_manual_add_{child_id}"):
                    try:
                        backend.hierarchical_child_discovery_service.manual_add_candidate(
                            Path(manual_pdf),
                            {"occurrence_id":base["anchor_id"]},
                            {
                                **base,
                                "raw_label":base["raw_label"],
                                "statement_amount_normalized":base.get("statement_amount_normalized"),
                            },
                            {
                                "member_table_id":base["canonical_concept_id"],
                                "canonical_title":base["raw_label"],
                                "primary_subtable_roles":["PRIMARY_AMOUNT_DETAIL"],
                            },
                            str(base.get("statement_scope") or "UNKNOWN"),
                            page=int(manual_page),title=manual_title,
                        )
                        backend.child_discovery_repository.review_mapping(
                            child_id,"MANUAL_ADD_LINK",reviewer="USER",
                            reason=reason or "人工从正式附注索引添加候选",
                            evidence={"page":int(manual_page),"title":manual_title,
                                      "source_pdf_id":manual_pdf},
                        )
                        st.success("已添加候选；重新打开该子项即可审核。")
                    except (ValueError,OSError) as exc:
                        st.error(f"未能添加：{exc}")
