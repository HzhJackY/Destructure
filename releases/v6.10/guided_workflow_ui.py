"""Streamlit adapter for the v6.5 guided path.

The adapter intentionally keeps planning separate from manual capture.  It only
submits a capture plan after an explicit two-stage review.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pandas as pd
from anchor_candidate_selection import candidate_label
from hierarchical_child_discovery import StatementScopeSelection

EVIDENCE_LABELS = {
    "exact_parent_match": "目标父行与研究目标完全一致",
    "normalized_parent_match": "规范化后的父行名称一致",
    "formal_statement_region": "位于正式财务主报表区域",
    "statement_type_match": "主报表类型符合研究定义",
    "scope_match": "合并/公司口径符合研究定义",
    "continuous_children": "父行下方存在连续子项",
    "inline_note_references": "子项含可沿用的行内附注编号",
    "valid_note_format": "附注编号格式有效",
    "amount_completeness": "当期/对比期金额列可识别",
    "period_completeness": "期间表头完整",
    "unit_context": "单位上下文可追溯",
    "scope_context": "报表口径上下文明确",
    "column_alignment": "金额列几何对齐",
}


def _human_anchor_evidence(candidate: dict[str, Any]) -> list[dict[str, str]]:
    positive = set(candidate.get("positive_evidence") or [])
    return [
        {"人工核对点": label, "系统判断": "符合" if key in positive else "未确认"}
        for key, label in EVIDENCE_LABELS.items()
    ]


def _anchor_children(candidate: dict[str, Any]) -> list[dict[str, Any]]:
    rows = []
    for child in candidate.get("child_rows") or []:
        values = child.get("values")
        if values is None:
            value = child.get("value")
            values = [] if value is None else [value]
        rows.append({
            "子项": child.get("member_table") or child.get("item") or "",
            "主表金额": " / ".join(str(x) for x in values),
            "附注编号": child.get("note_reference_normalized") or child.get("note_reference") or "未识别",
        })
    return rows


def _safe_pdf_page(value: Any) -> int | None:
    """Accept legacy SQLite NULL/NaN values without pretending they are pages."""
    if value is None or pd.isna(value):
        return None
    try:
        page = int(float(value))
    except (TypeError, ValueError):
        return None
    return page if page > 0 else None


def _show_pdf_preview(container, preview: dict[str, Any], label: str) -> bool:
    """Render review evidence without letting a bad PDF/page crash Streamlit."""
    if preview.get("status") != "OK" or not preview.get("png"):
        container.warning(
            f"{label}不可用：{preview.get('error') or preview.get('status') or 'UNKNOWN_PREVIEW_ERROR'}"
        )
        return False
    container.caption(
        f"{label}：PDF {preview['pdf_page_index']}（印刷页 "
        f"{preview.get('printed_page') or '未识别'}）· "
        f"{preview.get('evidence_level') or 'UNAVAILABLE'}"
    )
    container.image(preview["png"], use_container_width=True)
    return True


def _resolve_pdf_path(record: dict[str, Any], backend=None) -> Path | None:
    """Resolve a filesystem path even when the stored PDF identity is opaque."""
    for raw in (
        record.get("pdf_path"),
        record.get("source_pdf"),
        record.get("source_pdf_path"),
        record.get("pdf_id"),
    ):
        value = str(raw or "").strip()
        if value.lower().startswith("pdf::"):
            value = value[5:]
        candidate = Path(value) if value else None
        if candidate and candidate.is_file():
            return candidate
    pdf_id = str(record.get("pdf_id") or "")
    if backend is not None and pdf_id:
        for asset in backend.pdf_service.list(limit=5000):
            if str(asset.get("pdf_id") or "") == pdf_id:
                candidate = Path(str(asset.get("path") or ""))
                if candidate.is_file():
                    return candidate
    return None


def render_guided_capture(st, backend, selected_pdfs: list[Path], infer_dimensions) -> None:
    st.subheader("研究引导抓取：发现 → 审核 → 认证计划 → 一键抓取")
    st.caption("该路径只输入一次研究目标；认证后不再重复选择目标表或表族。手工抓取在下方高级区独立保留。")
    definitions = backend.research_definition_service.definitions() if hasattr(backend, "research_definition_service") else []
    definition_map = {"（不使用 Registry，临时自由输入）": None} | {f"{x['display_name']} · {x['definition_version']}": x for x in definitions}
    definition_label = st.selectbox("Research Definition（推荐，可复现）", list(definition_map), key="v67_definition_select")
    selected_definition = definition_map[definition_label]
    default_name = selected_definition["display_name"] if selected_definition else ""
    display_name = st.text_input("研究目标 / display_name", value=default_name, placeholder="例如：金融投资、保险合同负债、投资收益", key="v65_display_name")
    scope_label=st.radio(
        "财务报表口径",
        ["合并财务报表（默认）","母公司财务报表","两者都需要"],
        horizontal=True,key="v610_scope_selector",
    )
    requested_scope={
        "合并财务报表（默认）":"CONSOLIDATED",
        "母公司财务报表":"PARENT_COMPANY",
        "两者都需要":"BOTH",
    }[scope_label]
    requested_scope_lanes=(
        ["CONSOLIDATED","PARENT_COMPANY"] if requested_scope=="BOTH"
        else [requested_scope]
    )
    families = backend.research_definition_service.families() if hasattr(backend, "research_definition_service") else []
    knowledge_map = {"（无知识包，纯通用发现）": None} | {
        f"{family['display_name']} · {family['definition_version']}": family["family_id"]
        for family in families
    }
    knowledge_label = st.selectbox(
        "可选 Registry 知识包", list(knowledge_map), key="v68_knowledge_package",
        disabled=selected_definition is not None,
        help="知识包只从 Registry 提供不可变词表；选择 Research Definition 时由定义直接固定发现策略。",
    )
    selected_family_id = knowledge_map[knowledge_label]
    if st.button("① 发现主报表 occurrence 与附注候选", key="v65_discover", disabled=not selected_pdfs or not display_name.strip()):
        # A new discovery invalidates every downstream UI artifact from the
        # previous run.  Keeping an old Stage-B occurrence is what previously
        # caused UNSELECTED_ANCHOR_NEVER_MATERIALIZES.
        for key in (
            "v66_resolved_occurrences","v651_certified_occurrence_ids",
            "v66_certified_plans","v66_research_batch_id",
        ):
            st.session_state.pop(key,None)
        raw: list[dict[str, Any]] = []
        direct_occurrences = []
        for pdf in selected_pdfs:
            dim = infer_dimensions(pdf)
            backend.child_discovery_repository.save_scope(StatementScopeSelection.new(
                str(pdf),requested_scope,
                research_definition_id=str((selected_definition or {}).get("definition_id") or ""),
                selection_source="USER_SELECTED",selected_by="USER",
                evidence={"ui":"Research-Guided Capture"},
            ))
            if selected_definition:
                result = backend.generic_discovery_service.discover(pdf_path=pdf, definition_id=selected_definition["definition_id"], company=dim["company"], report_year=dim["year"])
                raw.extend(result["candidates"])
                for candidate in result["candidates"]:
                    backend.discovery_registry.save_machine(dict(candidate) | {"pdf_id": str(pdf)})
                for occurrence in result["occurrences"]:
                    direct_occurrences.append(backend.discovery_service.build_occurrence(context=dict(occurrence) | {"pdf_id": str(pdf)}, parent_text=occurrence["parent_text"], child_rows=occurrence["child_rows"], source_table_title=occurrence["source_table_title"], scope=occurrence.get("scope", "UNKNOWN")))
            else:
                discovery_context = (
                    backend.research_definition_service.family_discovery_context(selected_family_id)
                    if selected_family_id else {}
                )
                raw.extend(backend.discovery_service.preview(
                    pdf, display_name=display_name.strip(), company=dim["company"],
                    report_year=dim["year"], discovery_context=discovery_context,
                ))
        st.session_state["v65_raw_discovery"] = raw
        st.session_state["v65_clusters"] = backend.discovery_service.cluster(raw)
        st.session_state["v65_occurrences"] = direct_occurrences or backend.discovery_service.proposed_occurrences(raw)
    clusters = st.session_state.get("v65_clusters", [])
    occurrences = st.session_state.get("v65_occurrences", [])
    if not clusters and not occurrences:
        return
    st.markdown("#### 阶段 A：审核抓什么（已先按证据聚类）")
    if clusters:
        table = pd.DataFrame(clusters)
        cols = [c for c in ["candidate_cluster_id", "company", "report_year", "display_name", "statement_type", "scope", "member_table", "statement_pdf_page_index", "candidate_note_pdf_page_index", "note_reference_normalized", "confidence", "evidence_count"] if c in table]
        st.dataframe(table[cols], use_container_width=True, hide_index=True)
    else:
        table = pd.DataFrame()
    if occurrences:
        st.caption("发现、推荐、预选与认证严格分离；每份 PDF、每个口径最多推荐一个 Anchor，只有点击确认后才认证。")
        definition_scope=requested_scope_lanes[0] if len(requested_scope_lanes)==1 else ""
        ranked=backend.discovery_service.rank_anchor_candidates(
            occurrences,scope_preference=definition_scope or None,
            required_scopes=requested_scope_lanes,
        )
        ranked_by_id={row["occurrence_id"]:row for row in ranked["candidates"]}
        groups:dict[tuple[str,str],list[dict[str,Any]]]={}
        for row in ranked["candidates"]:
            key=(str(row.get("pdf_id") or ""),str(row.get("scope") or "UNKNOWN"))
            groups.setdefault(key,[]).append(row)
        selected_occurrence_ids=[]
        for group_index,((pdf_id,scope),rows) in enumerate(groups.items()):
            first=rows[0]
            st.markdown(
                f"**{first.get('company') or Path(pdf_id).stem}｜{first.get('report_year') or '-'}｜"
                f"{scope}**"
            )
            label_map={candidate_label(row):row["occurrence_id"] for row in rows}
            options=["不选择（需要人工判断）"]+list(label_map)
            recommended=next((row["occurrence_id"] for row in rows
                              if row["occurrence_id"] in ranked["preselected_ids"]),None)
            recommended_label=next((label for label,oid in label_map.items() if oid==recommended),None)
            choice=st.radio(
                "选择本口径主报表 Anchor",options,
                index=options.index(recommended_label) if recommended_label else 0,
                key=f"v69_anchor_choice_{group_index}_{abs(hash((pdf_id,scope)))}",
            )
            if choice!="不选择（需要人工判断）":
                selected_occurrence_ids.append(label_map[choice])
                selected=ranked_by_id[label_map[choice]]
                st.markdown("##### 人工判断依据")
                evidence_cols=st.columns([1.15,1])
                pdf=_resolve_pdf_path(selected,backend)
                page=_safe_pdf_page(selected.get("statement_pdf_page_index"))
                if pdf and page:
                    from pdf_evidence import page_preview
                    preview=page_preview(
                        pdf,page-1,
                        [str(selected.get("display_name") or "")]+[
                            str(x.get("item") or x.get("member_table") or "")
                            for x in selected.get("child_rows") or []
                        ],
                    )
                    _show_pdf_preview(evidence_cols[0],preview,"候选主报表原页")
                else:
                    evidence_cols[0].warning("没有可显示的主报表原页；请勿仅凭评分认证。")
                with evidence_cols[1]:
                    st.write(
                        f"**{selected.get('source_table_title') or '未知主表'}**  "
                        f"PDF {page or '未识别'} 页 · {selected.get('scope') or 'UNKNOWN'}"
                    )
                    child_rows=_anchor_children(selected)
                    if child_rows:
                        st.dataframe(pd.DataFrame(child_rows),use_container_width=True,hide_index=True)
                    else:
                        st.warning("未识别父行下的连续子项。")
                    st.dataframe(
                        pd.DataFrame(_human_anchor_evidence(selected)),
                        use_container_width=True,hide_index=True,
                    )
                with st.expander("高级信息：机器评分、门禁和算法版本",expanded=False):
                    st.write(
                        f"总分：{selected['total_score']:.2f}；门禁："
                        f"{'全部通过' if selected['hard_gates_passed'] else '未通过'}；"
                        f"排序版本：{selected['ranking_version']}"
                    )
                    st.dataframe(pd.DataFrame([
                        {"机器特征":name,"权重":value}
                        for name,value in selected["score_components"].items() if value
                    ]),use_container_width=True,hide_index=True)
                    failed=[name for name,passed in selected["hard_gate_results"].items() if not passed]
                    if failed: st.error("未通过硬门禁："+"、".join(failed))
            elif ranked["scope_decisions"].get(f"{pdf_id}::{scope}",{}).get("status")=="ANCHOR_SELECTION_REQUIRED":
                st.warning("候选分数不足、差距过小或证据冲突：需要人工选择，不会自动认证。")
        override_reason=st.text_input(
            "选择非推荐 Anchor 时的原因（可选）",
            key="v69_anchor_override_reason",
            placeholder="例如：研究任务要求母公司口径；推荐页为摘要表。",
        )
    else:
        ranked={"candidates":[],"preselected_ids":[]}
        ranked_by_id={}
        override_reason=""
        selected_occurrence_ids = []
    if st.button("② 认证所选 Anchor 并解析附注目标", key="v66_certify_anchors", disabled=not selected_occurrence_ids):
        chosen_occurrences = [o for o in occurrences if o["occurrence_id"] in selected_occurrence_ids]
        certified_occurrences = []
        for occurrence_id in selected_occurrence_ids:
            candidate=ranked_by_id[occurrence_id]
            recommended=occurrence_id in ranked["preselected_ids"]
            alternatives=[{
                "occurrence_id":x["occurrence_id"],"score":x["total_score"],
                "scope":x.get("scope"),"page":x.get("statement_pdf_page_index"),
            } for x in ranked["candidates"] if x["occurrence_id"]!=occurrence_id]
            backend.discovery_service.adjudicate_anchor(
                occurrence_id,label="ACCEPTED",chosen_scope=str(candidate.get("scope") or ""),
                reason="确认系统推荐" if recommended else override_reason.strip(),
                override={
                    "selection_method":"HUMAN_CONFIRMED_RECOMMENDATION" if recommended else "HUMAN_OVERRIDE",
                    "recommended_candidate_id":occurrence_id if recommended else next(iter(ranked["preselected_ids"]),None),
                    "selected_candidate_id":occurrence_id,
                    "candidate_score":candidate["total_score"],
                    "score_evidence_snapshot":{
                        "score_components":candidate["score_components"],
                        "hard_gate_results":candidate["hard_gate_results"],
                        "ranking_version":candidate["ranking_version"],
                    },
                    "alternative_candidates":alternatives,
                    "override_reason":"" if recommended else override_reason.strip(),
                },
            )
            certified=backend.discovery_registry.get_occurrence(occurrence_id)
            if certified and (
                certified.get("status")=="ANCHOR_CERTIFIED"
                or backend.discovery_registry.is_anchor_certified(occurrence_id)
            ):
                certified_occurrences.append(certified)
        # Persist only the anchor decision here.  Note candidates remain
        # non-executable until the user confirms a concrete target below.
        chosen_by_id={x["occurrence_id"]:x for x in chosen_occurrences}
        st.session_state["v66_resolved_occurrences"] = [
            backend.discovery_service.resolve_note_targets({
                **row,
                "pdf_id":chosen_by_id.get(row["occurrence_id"],{}).get("pdf_id") or row.get("pdf_id"),
                "child_rows":chosen_by_id.get(row["occurrence_id"],{}).get("child_rows") or row.get("child_rows") or [],
            })
            for row in certified_occurrences
        ]
        st.session_state["v651_certified_occurrence_ids"] = [
            x["occurrence_id"] for x in certified_occurrences
        ]
        st.session_state.pop("v66_certified_plans",None)
        v610_mappings=[]
        for row in certified_occurrences:
            source=Path(str(row.get("pdf_id") or ""))
            if not source.is_file():continue
            chosen=chosen_by_id.get(row["occurrence_id"],{})
            anchor={**row,"child_rows":chosen.get("child_rows") or row.get("child_rows") or []}
            anchor_scope=str(anchor.get("scope") or "")
            if anchor_scope not in requested_scope_lanes:
                if len(requested_scope_lanes)!=1:
                    st.error("认证 Anchor 的口径无法映射到所选双口径 lane；请返回阶段 A 重新认证。")
                    continue
                anchor_scope=requested_scope_lanes[0]
                anchor["scope"]=anchor_scope
            concepts=backend.child_discovery_repository.create_anchor_children(
                anchor,
                research_definition_id=str((selected_definition or {}).get("definition_id") or ""),
                definition_version=str((selected_definition or {}).get("definition_version") or ""),
            )
            links_by_child={}
            for concept in concepts:
                contract={
                    "member_table_id":concept["canonical_concept_id"] or concept["raw_label"],
                    "canonical_title":concept["raw_label"],
                    "exact_aliases":concept.get("concept_aliases") or [],
                    "certified_company_aliases":[],
                }
                found=backend.hierarchical_child_discovery_service.discover(
                    source,anchor,concept,contract,anchor_scope,
                )
                enriched=backend.hierarchical_child_discovery_service.enrich_top_k(
                    source,concept,found["candidates"],contract,
                )
                links=backend.hierarchical_child_discovery_service.link_candidates(
                    anchor,concept,enriched,contract,
                )
                links_by_child[concept["anchor_child_id"]]=links
                v610_mappings.append({
                    "anchor":anchor,"child":concept,"contract":contract,
                    "run":found["run"],"links":links,"pdf_path":str(source),
                })
            backend.hierarchical_child_discovery_service.assign_global(
                anchor["occurrence_id"],anchor_scope,
                links_by_child,
            )
        st.session_state["v610_child_mappings"]=v610_mappings
    resolved_occurrences = st.session_state.get("v66_resolved_occurrences", [])
    if not resolved_occurrences:
        return
    mappings=st.session_state.get("v610_child_mappings",[])
    if mappings:
        st.markdown("#### 阶段 B：审核子表映射（严格分级召回）")
        st.caption("显式附注引用优先；不足时才查询正式附注标题。只有人工认证的关系可以启动完整抓取。")
        selected_links=[]
        for item in mappings:
            child=item["child"];links=item["links"]
            with st.expander(
                f"{child['raw_label']}｜{child['statement_scope']}｜"
                f"主表金额 {child.get('statement_amount_raw')}",
                expanded=bool(links and links[0].get("is_preselected")),
            ):
                run=item["run"]
                st.caption(
                    f"执行层级：{', '.join(run['tiers_executed']) or '-'}；"
                    f"跳过：{', '.join(run['tiers_skipped']) or '-'}；"
                    f"早停：{run.get('early_stop_reason') or '无'}"
                )
                if not links:
                    st.warning("未找到候选；不会自动抓取。")
                    continue
                primary_links=[x for x in links if x.get("proposed_subtable_role")=="PRIMARY_AMOUNT_DETAIL"]
                supplementary_links=[x for x in links if x.get("proposed_subtable_role")!="PRIMARY_AMOUNT_DETAIL"]
                if not primary_links:
                    st.error("没有可认证的主金额明细候选；补充披露不能代替主表子项。")
                    continue
                labels={
                    f"{'推荐｜' if x['is_recommended'] else ''}{x['certification_score']:.2f}｜"
                    f"PDF {x['candidate']['start_page']}｜{x['candidate']['raw_heading']}｜"
                    f"{x['candidate']['retrieval_method']}":x for x in primary_links
                }
                default=next((i for i,x in enumerate(labels.values()) if x.get("is_preselected")),0)
                label=st.radio(
                    "主金额明细（默认选择推荐项）",list(labels),
                    index=default,
                    key=f"v610_mapping_{child['anchor_child_id']}",
                )
                selected_links.append((item,labels[label]))
                st.dataframe(pd.DataFrame([{
                    "召回":labels[label]["candidate"]["retrieval_method"],
                    "关系":labels[label]["reconciliation_relation"],
                    "勾稽":labels[label]["reconciliation_status"],
                    "正向证据":"、".join(labels[label].get("positive_evidence") or []),
                    "阻断":"、".join(labels[label]["blocking_warnings"]),
                }]),use_container_width=True,hide_index=True)
                if supplementary_links:
                    st.caption("可选补充披露：不占用主金额明细的唯一认证位。")
                    for supplemental in supplementary_links:
                        if st.checkbox(
                            f"补充｜{supplemental['proposed_subtable_role']}｜PDF {supplemental['candidate']['start_page']}｜{supplemental['candidate']['raw_heading']}",
                            value=bool(supplemental.get("is_supplementary_recommended")),
                            key=f"v610_guided_supp_{supplemental['link_candidate_id']}",
                        ):
                            selected_links.append((item,supplemental))
        mapping_reason=st.text_input(
            "选择非推荐子表时的覆盖原因（可选）",key="v610_mapping_override_reason",
        )
        if st.button("③ 认证所选子表关系",disabled=not selected_links,key="v610_certify_links"):
            certified=[]
            for item,link in selected_links:
                payload={
                    **link,"table_family_id":display_name.strip(),
                    "member_table_id":link["proposed_member_table_id"],
                    "subtable_role":link["proposed_subtable_role"],
                    "relation_type":link["proposed_relation_type"],
                    "selected_candidate_id":link["candidate_id"],
                    "recommended_candidate_id":next((x["candidate_id"] for x in item["links"] if x["is_recommended"]),None),
                    "alternative_candidates":[x["candidate_id"] for x in item["links"] if x["candidate_id"]!=link["candidate_id"]],
                    "score_snapshot":{"certification_score":link["certification_score"],
                                      "breakdown":link["score_breakdown"]},
                    "evidence_snapshot":{"hard_gates":link["hard_gate_results"],
                                         "retrieval_method":link["candidate"]["retrieval_method"],
                                         "anchor_note_reference":link.get("anchor_note_reference") or ""},
                    "reconciliation_result":{"relation":link["reconciliation_relation"],
                                             "status":link["reconciliation_status"]},
                    "research_definition_id":str((selected_definition or {}).get("definition_id") or ""),
                    "definition_version":str((selected_definition or {}).get("definition_version") or ""),
                }
                method="HUMAN_CONFIRMED_RECOMMENDATION" if link["is_recommended"] else "HUMAN_OVERRIDE"
                certified.append(backend.child_discovery_repository.certify(
                    payload,reviewer="USER",method=method,reason=mapping_reason,
                )|{"pdf_path":item["pdf_path"]})
            st.session_state["v610_certified_child_links"]=certified
            st.success(f"已认证 {len(certified)} 个子表关系。")
        certified_links=st.session_state.get("v610_certified_child_links",[])
        # v6.10: unified certified-child capture execution panel
        # replaces the old per-child synchronous orchestrator loop
        if certified_links:
            from components.child_capture_execution_panel import render_child_capture_execution_panel
            render_child_capture_execution_panel(
                st, backend,
                display_name=display_name,
                certified_links=certified_links,
                source_pdf_map={
                    str(link.get("pdf_id") or link.get("pdf_path", "")):
                    Path(link["pdf_path"]) for link in certified_links
                },
                research_definition=selected_definition,
                scope=requested_scope,
                key_prefix="v610_strict_child",
            )
        st.divider()
    st.markdown("#### 兼容流程：审核显式附注目标")
    st.caption("只有本阶段明确确认的附注目标会进入 Capture Plan；未选 Anchor 与未确认目标不会生成作业。")
    target_selections: dict[str, dict[str, Any]] = {}
    for occ in resolved_occurrences:
        pdf = _resolve_pdf_path(occ, backend)
        pdf_label = pdf.name if pdf else str(occ.get("pdf_id") or "PDF证据不可用")
        with st.expander(f"{pdf_label} · 已选主表：{occ.get('source_table_title')}", expanded=False):
            if pdf and occ.get("statement_pdf_page_index"):
                from pdf_evidence import page_preview
                preview = page_preview(pdf, int(occ["statement_pdf_page_index"]) - 1,
                                       [str(x.get("item") or "") for x in occ.get("child_rows") or []])
                _show_pdf_preview(st, preview, "主表")
            for child in occ.get("child_rows") or []:
                member = str(child.get("member_table") or child.get("item") or "")
                candidates = child.get("note_target_candidates") or []
                st.markdown(f"**{member}** · {child.get('note_reference_normalized') or child.get('note_reference') or '无附注引用'}")
                if not candidates:
                    st.warning("未找到可认证附注目标：不会自动抓取。")
                    continue
                labels = [f"PDF {x['pdf_page_index']} · {x.get('heading','')[:70]} · {x.get('locator_method')} · {x.get('score',0):.2f}" for x in candidates]
                selected_label = st.selectbox("确认附注目标", labels, key=f"v66_target_{occ['occurrence_id']}_{member}")
                candidate = candidates[labels.index(selected_label)]
                target_selections[f"{occ['occurrence_id']}::{member}"] = backend.discovery_service.note_resolver.certify(candidate)
    if st.button("③ 认证附注目标并生成 Capture Plan", key="v66_certify_targets"):
        plans = []
        for occ in resolved_occurrences:
            persisted=backend.discovery_registry.get_occurrence(occ["occurrence_id"])
            if not persisted or (
                persisted.get("status")!="ANCHOR_CERTIFIED"
                and not backend.discovery_registry.is_anchor_certified(occ["occurrence_id"])
            ):
                st.error(
                    "该主报表只是历史会话中的候选，尚未完成 Anchor 认证。"
                    "请返回阶段 A 重新选择并点击“认证所选 Anchor”。"
                )
                continue
            target_map = {key.split("::", 1)[1]: value for key, value in target_selections.items() if key.startswith(occ["occurrence_id"] + "::")}
            plans.append(backend.discovery_service.certified_capture_plan(occ, certified_ids=[], certified_targets=target_map))
        if not plans:
            st.session_state.pop("v66_certified_plans",None)
            return
        research = backend.research_batch_service.create(
            display_name=f"{display_name.strip()}_研究引导抓取",
            table_family=display_name.strip(),
            payload={"source_pdf_count": len(plans), "plan_ids": [p["plan_id"] for p in plans], "stage": "CERTIFIED_CAPTURE_PLAN"},
            research_definition_id=selected_definition["definition_id"] if selected_definition else None,
            definition_version=selected_definition["definition_version"] if selected_definition else None,
        )
        for plan in plans:
            backend.research_batch_service.attach(research["research_batch_id"], plan_id=plan["plan_id"], role="PLAN")
        st.session_state["v66_certified_plans"] = plans
        st.session_state["v66_research_batch_id"] = research["research_batch_id"]
    plans = st.session_state.get("v66_certified_plans", [])
    if not plans:
        return
    st.success(f"已生成 {len(plans)} 份独立 Capture Plan：共 {sum(len(p['items']) for p in plans)} 个表资产。")
    for plan in plans:
        with st.expander(f"计划 {plan['plan_id']}：1 个主报表构成 + {len(plan['items']) - 1} 个附注明细", expanded=False):
            plan_rows = []
            for item in plan["items"]:
                if item.get("member_table_role") == "NOTE_DETAIL":
                    target = item.get("certified_note_target") or {}
                    plan_rows.append({"成员": item.get("member_table"), "附注": item.get("note_reference"), "认证目标页": item.get("confirmed_note_pdf_page_index"), "认证标题": target.get("target_heading"), "定位方式": target.get("locator_method"), "状态": item.get("status")})
            st.dataframe(pd.DataFrame(plan_rows), use_container_width=True, hide_index=True)
    # v6.10: unified certified-child capture execution panel
    # replaces the old per-plan guided capture + progress + redirect block
    if plans:
        from components.child_capture_execution_panel import render_child_capture_execution_panel
        render_child_capture_execution_panel(
            st, backend,
            display_name=display_name,
            plans=plans,
            research_definition=selected_definition,
            scope=requested_scope,
            key_prefix="v610_compat_child",
        )


def render_review_center(st, backend) -> None:
    st.title("研究任务审核中心")
    batches = backend.research_batch_service.list()
    if batches:
        st.subheader("研究任务 / Research Batch")
        labels = {f"{b['display_name']} · {b['research_batch_id']} · {b['status']}": b for b in batches}
        chosen = labels[st.selectbox("选择研究任务", list(labels), key="v66_review_research_batch")]
        impact = backend.research_batch_service.impact(chosen['research_batch_id'])
        st.json({k: impact[k] for k in ['research_batch_id','plans','source_batches','jobs','captures']})
        st.caption("以下审核将优先围绕该研究任务的来源计划、主报表 Anchor、成员与附注目标展开；内部 DISC ID 仅在审计详情显示。")
        if st.button("修复本研究批次缺失的定义身份", key="v610_backfill_batch_definition_identity"):
            repair = backend.research_batch_service.backfill_missing_definition_identity(chosen['research_batch_id'])
            if repair.get("reason"):
                st.warning("该研究批次没有固定的研究定义版本，不能安全回填。")
            else:
                st.success(f"已安全回填 {repair.get('updated', 0)} 个逻辑资产的缺失定义身份；既有身份未被覆盖。")
                st.rerun()
        plan_view = backend.research_batch_service.plan_view(chosen['research_batch_id'])
        if plan_view:
            st.markdown("#### 已选主报表与子表（唯一执行范围）")
            for plan in plan_view:
                payload = plan.get('payload', {})
                anchor = payload.get('anchor', {})
                pdf = _resolve_pdf_path(
                    {"pdf_id": plan.get("pdf_id"), "source_pdf": payload.get("source_pdf")},
                    backend,
                )
                pdf_label = pdf.name if pdf else str(plan.get("pdf_id") or "PDF证据不可用")
                st.markdown(f"**{pdf_label}** · 已选 Anchor：{anchor.get('source_table_title','主报表')} · {anchor.get('scope','-')}")
                rows = []
                for item in plan['items']:
                    if item.get('member_table_role') == 'NOTE_DETAIL':
                        item_payload = json.loads(item.get('payload_json') or '{}')
                        target = item_payload.get('certified_note_target') or {}
                        rows.append({'成员':item.get('member_table'),'附注':item.get('note_reference'),'认证页':item.get('confirmed_note_pdf_page_index'),'目标标题':target.get('target_heading'),'状态':item.get('status')})
                st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)
                with st.expander("查看已认证主报表与附注证据", expanded=False):
                    statement_page = _safe_pdf_page(anchor.get('statement_pdf_page_index'))
                    if pdf and statement_page:
                        from pdf_evidence import page_preview
                        terms = [str(anchor.get('display_name') or '')] + [str(row['成员']) for row in rows]
                        preview = page_preview(pdf, statement_page - 1, terms)
                        _show_pdf_preview(st, preview, "主报表")
                    else:
                        st.warning("主报表证据页不可用；该计划不应据此自动扩大抓取范围。")
                    for row in rows:
                        target_page = _safe_pdf_page(row['认证页'])
                        if pdf and target_page:
                            from pdf_evidence import page_preview
                            detail = page_preview(pdf, target_page - 1, [str(row['目标标题'] or row['成员'])])
                            _show_pdf_preview(st, detail, str(row["成员"]))
                        else:
                            st.warning(f"{row['成员']} 缺少已认证附注页，不能进入自动抓取。")
            left, right = st.columns(2)
            if left.button("移入研究任务回收站", key="v66_trash_research_batch"):
                st.success(str(backend.research_batch_service.trash(chosen['research_batch_id'])))
                st.rerun()
            if right.button("恢复研究任务", key="v66_restore_research_batch"):
                st.success(str(backend.research_batch_service.restore(chosen['research_batch_id'])))
                st.rerun()
            st.markdown("#### Capture Result Review（执行、目标、质量分层）")
            result_rows = backend.research_batch_service.result_review(chosen['research_batch_id'])
            st.dataframe(pd.DataFrame(result_rows), use_container_width=True, hide_index=True)
            st.caption("execution_status 是不可变的历史作业结果；capture_quality 是最新非替代 Capture 的当前质量，重跑与合表以当前质量为准。")
            rerun_mode = st.selectbox("重跑范围", ["REVIEW_REQUIRED", "ALL"], key="v66_research_rerun_mode")
            rerun_candidates = backend.research_batch_service.rerun_candidates(chosen['research_batch_id'], rerun_mode)
            st.caption(f"可重跑的认证目标：{len(rerun_candidates)}；未认证或未选 Anchor 不会列入。")
            if st.button("按所选范围创建并启动认证重跑", key="v66_research_rerun_certified", disabled=not rerun_candidates):
                rerun_plans = backend.research_batch_service.build_rerun_plans(chosen['research_batch_id'], rerun_mode)
                results = []
                for rerun_plan in rerun_plans:
                    pdf = _resolve_pdf_path(rerun_plan, backend)
                    if pdf:
                        results.append(backend.guided_capture_service.execute(rerun_plan, pdf_path=pdf, research_batch_id=chosen['research_batch_id']))
                jobs = sum(len(result.get('jobs', [])) for result in results)
                st.success(f"已按 {rerun_mode} 新建 {len(rerun_plans)} 份版本化重跑计划并提交 {jobs} 个作业；不会复用旧作业状态。")
                st.rerun()
            st.markdown("#### 在此直接审核 Capture 结构")
            capture_choices = {}
            for row in result_rows:
                for capture_id in row.get('capture_ids') or []:
                    capture_choices[f"{row['member_table']} · {capture_id}"] = {
                        "capture_id": capture_id,
                        "review_row": row,
                    }
            if not capture_choices:
                st.caption("尚无完成的 Capture 可审核；完成作业后无需前往数据资产管理，可直接在此审核。")
            else:
                selected_capture_label = st.selectbox("选择本研究任务的 Capture", list(capture_choices), key="v66_review_capture_direct")
                selected_capture = capture_choices[selected_capture_label]
                capture = backend.capture_service.get(selected_capture["capture_id"])
                selected_review_row = selected_capture["review_row"]
                run_dir = Path(str((capture or {}).get('run_path') or ''))
                if capture and run_dir.exists():
                    wide_path = run_dir / 'table_raw_wide.csv'
                    long_path = run_dir / 'table_raw_long.csv'
                    machine_wide_path = run_dir / 'machine_capture_full_wide.csv'
                    machine_long_path = run_dir / 'machine_capture_full_long.csv'
                    official_tab, machine_tab = st.tabs(["正式输出", "机器完整证据"])
                    official_tab.dataframe(
                        pd.read_csv(wide_path) if wide_path.exists() else pd.DataFrame(),
                        use_container_width=True,
                        hide_index=True,
                    )
                    machine_tab.dataframe(
                        pd.read_csv(machine_wide_path) if machine_wide_path.exists() else pd.DataFrame(),
                        use_container_width=True,
                        hide_index=True,
                    )
                    result_path = run_dir / 'table_capture_result.json'
                    if result_path.exists():
                        try:
                            capture_result = json.loads(result_path.read_text(encoding='utf-8'))
                        except (OSError, json.JSONDecodeError):
                            capture_result = {}
                        capture_stats = capture_result.get("stats") or {}
                        boundary_evidence = capture_stats.get("boundary_evidence") or {}
                        boundary_method = str(boundary_evidence.get("method") or "")
                        boundary_target_page = _safe_pdf_page(
                            boundary_evidence.get("next_note_pdf_page_index")
                        )
                        has_terminating_boundary = bool(
                            boundary_target_page
                            and boundary_method in {"NEXT_NOTE_ORDINAL", "NEXT_PEER_HEADING"}
                        )
                        st.markdown("##### Table Boundary Evidence")
                        st.json({
                            "start": (
                                f"{capture_result.get('note_number') or capture_result.get('located_title')}"
                                f" · PDF {capture_result.get('start_page') or '?'}"
                            ),
                            "end": (
                                (
                                    f"{boundary_evidence.get('next_note_ordinal') or '未认证'}"
                                    f" · {boundary_evidence.get('next_note_title') or '需人工确认'}"
                                    f" · PDF {boundary_target_page or '?'}"
                                )
                                if has_terminating_boundary
                                else (
                                    f"未发现独立终止边界；搜索截止于 PDF "
                                    f"{capture_result.get('end_page') or '?'}"
                                )
                            ),
                            "evidence": boundary_method or "NO_BOUNDARY_EVIDENCE",
                            "boundary_confidence": capture_stats.get("boundary_confidence") or "LOW",
                            "boundary_status": capture_result.get("boundary_status") or "REVIEW_REQUIRED",
                        })
                        source_pdf_candidates = [
                            capture_stats.get("source_pdf_path"),
                            selected_review_row.get("source_pdf"),
                        ]
                        source_pdf = next(
                            (
                                Path(str(candidate))
                                for candidate in source_pdf_candidates
                                if candidate and Path(str(candidate)).is_file()
                            ),
                            None,
                        )
                        if source_pdf:
                            with st.expander("PDF 边界证据预览", expanded=True):
                                from pdf_evidence import page_preview
                                start_page = _safe_pdf_page(capture_result.get("start_page"))
                                end_page = _safe_pdf_page(
                                    boundary_target_page
                                    if has_terminating_boundary
                                    else capture_result.get("end_page")
                                )
                                left_preview, right_preview = st.columns(2)
                                if start_page:
                                    start_evidence = page_preview(
                                        source_pdf,
                                        start_page - 1,
                                        [
                                            str(capture_result.get("located_title") or ""),
                                            str(capture_result.get("table_query") or ""),
                                        ],
                                    )
                                    _show_pdf_preview(left_preview, start_evidence, "开始")
                                else:
                                    left_preview.warning("缺少可用的表格起始页。")
                                if end_page:
                                    end_evidence = page_preview(
                                        source_pdf,
                                        end_page - 1,
                                        (
                                            [
                                                str(boundary_evidence.get("next_note_title") or ""),
                                                str(boundary_evidence.get("next_note_heading_raw") or ""),
                                            ]
                                            if has_terminating_boundary
                                            else []
                                        ),
                                    )
                                    _show_pdf_preview(
                                        right_preview,
                                        end_evidence,
                                        "终止证据"
                                        if has_terminating_boundary
                                        else "搜索截止页（非边界证据）",
                                    )
                                    if not has_terminating_boundary:
                                        right_preview.info(
                                            "该页仅表示搜索窗口截止位置，不能作为下一附注边界的认证证据。"
                                        )
                                else:
                                    right_preview.warning("缺少可用的终止边界页；必须人工审核。")
                        else:
                            st.warning("未能解析此 Capture 的源 PDF 路径，暂时无法显示页面预览。")
                        machine_columns = list(capture_result.get('columns') or [])
                        if machine_columns:
                            st.caption("列维度审核也可在此完成；机器表头不会被覆盖，人工确认另存为审核记录。")
                            editable_columns = pd.DataFrame(machine_columns)
                            for column, default in (("year", ""), ("scope", ""), ("restated", False)):
                                if column not in editable_columns:
                                    editable_columns[column] = default
                            editable_columns["year"] = editable_columns["year"].where(editable_columns["year"].notna(), "")
                            editable_columns["scope"] = editable_columns["scope"].where(editable_columns["scope"].notna(), "")
                            editable_columns["restated"] = editable_columns["restated"].fillna(False).astype(bool)
                            editable_columns = editable_columns[[
                                column for column in ("ordinal", "header_raw", "year", "scope", "restated")
                                if column in editable_columns
                            ]]
                            with st.expander("审核列维度（期间 / 口径 / 重述）", expanded=False):
                                reviewed_columns = st.data_editor(
                                    editable_columns,
                                    hide_index=True,
                                    use_container_width=True,
                                    disabled=[column for column in ("ordinal", "header_raw") if column in editable_columns],
                                    key=f"v66_direct_header_editor_{capture['capture_id']}",
                                )
                                header_note = st.text_input("列维度审核说明", key=f"v66_direct_header_note_{capture['capture_id']}")
                                capture_detail=backend.capture_version_service.detail(capture["capture_id"])
                                if capture_detail:
                                    from inspection_route import InspectionRoute,set_inspection_route
                                    st.button(
                                        "在逻辑资产工作区审核表头",
                                        key=f"v69_route_header_{capture['capture_id']}",
                                        on_click=set_inspection_route,
                                        args=(st,InspectionRoute(
                                            logical_asset_id=capture_detail["logical_asset_id"],
                                            capture_version_id=capture["capture_id"],
                                            initial_tab="表头拓扑",return_route="发现结果审核",
                                        )),
                                        kwargs={"open_workspace":True},
                                    )
                    # Boundary adjudication must always use immutable machine
                    # evidence. Using an already-truncated official table makes
                    # it impossible to widen a previous human cutoff.
                    boundary_source = machine_long_path if machine_long_path.exists() else long_path
                    long = pd.read_csv(boundary_source) if boundary_source.exists() else pd.DataFrame()
                    if not long.empty and 'row_order' in long:
                        orders = sorted({int(x) for x in pd.to_numeric(long['row_order'], errors='coerce').dropna().tolist()})
                        cutoff = st.selectbox("确认边界：最后有效 row_order", orders, index=len(orders)-1, key=f"v66_direct_cutoff_{capture['capture_id']}")
                        capture_detail=backend.capture_version_service.detail(capture["capture_id"])
                        if capture_detail:
                            from inspection_route import InspectionRoute,set_inspection_route
                            st.button(
                                "在逻辑资产工作区审核边界",
                                key=f"v69_route_boundary_{capture['capture_id']}",
                                on_click=set_inspection_route,
                                args=(st,InspectionRoute(
                                    logical_asset_id=capture_detail["logical_asset_id"],
                                    capture_version_id=capture["capture_id"],
                                    initial_tab="附注容器与表块",return_route="发现结果审核",
                                )),
                                kwargs={"open_workspace":True},
                            )
                    else:
                        st.warning("此 Capture 缺少可审核的长表输出。")
            st.info("备选 Anchor 和原始机器候选已隔离至审计记录，不会显示为本研究任务的待审核子表，也不会进入 Capture Plan。")
            capture_ids = backend.research_batch_service.capture_ids(chosen['research_batch_id'])
            st.caption(f"可进入 Family Merge 的活动 Capture：{len(capture_ids)}")
            if capture_ids and st.button("将本研究任务的已认证 Capture 创建 Family Merge", key="v66_guided_family_merge"):
                merged = backend.merge_service.create(capture_ids=capture_ids, table_id=chosen['table_family'])
                st.success(f"已创建 Family Merge：{merged['merge_id']}")
            return
    rows = backend.discovery_registry.list_review_queue(limit=500)
    if not rows:
        st.info("暂无候选。请先运行“研究引导抓取”。")
        return
    table = pd.DataFrame(rows)
    st.caption("按 公司 → 年份 → 主报表 分级审核。一个主报表下同时展示其全部子表与附注证据；归档数据永不进入批量动作。")
    pending_statuses = ["NEEDS_REVIEW", "REVIEW_REQUIRED", "UNRESOLVED"]
    actionable = table[table["review_status"].isin(pending_statuses)].copy()
    archived = table[~table["review_status"].isin(pending_statuses)].copy()

    if actionable.empty:
        st.info("当前没有待审核候选。已处理记录可在下方归档区查看。")
        with st.expander(f"已处理归档（{len(archived)} 条，仅查看）", expanded=False):
            st.dataframe(archived, use_container_width=True, hide_index=True)
        return

    def text(value: Any) -> str:
        return "-" if value is None or pd.isna(value) or str(value).strip() == "" else str(value)

    companies = sorted(actionable["company"].dropna().astype(str).unique().tolist())
    company = st.selectbox("① 公司", companies, key="v651_review_company")
    by_company = actionable[actionable["company"].astype(str) == company].copy()
    years = sorted(by_company["report_year"].fillna("-").astype(str).unique().tolist(), reverse=True)
    year = st.selectbox("② 年份", years, key="v651_review_year")
    by_year = by_company[by_company["report_year"].fillna("-").astype(str) == year].copy()

    def anchor_key(r):
        return "\u241f".join([text(r.get(x)) for x in ("pdf_id", "scope", "source_table_title", "display_name", "statement_pdf_page_index", "statement_printed_page")])

    def anchor_label(r):
        page = _safe_pdf_page(r.get("statement_pdf_page_index")) or _safe_pdf_page(r.get("statement_page"))
        return " | ".join([text(r.get("scope")), text(r.get("source_table_title")), text(r.get("display_name")), f"PDF {page or '?'}（印刷页 {text(r.get('statement_printed_page'))}）"])

    by_year["_anchor_key"] = by_year.apply(anchor_key, axis=1)
    anchor_records = by_year.drop_duplicates("_anchor_key")
    anchor_options = {anchor_label(row): row["_anchor_key"] for _, row in anchor_records.iterrows()}
    chosen_anchor_label = st.selectbox("③ 主报表 / 表族", list(anchor_options), key="v651_review_anchor")
    chosen_anchor = anchor_options[chosen_anchor_label]
    children = by_year[by_year["_anchor_key"] == chosen_anchor].copy()

    def business_label(r):
        page = _safe_pdf_page(r.get("statement_pdf_page_index")) or _safe_pdf_page(r.get("statement_page"))
        return " | ".join([text(r.get("member_table") or r.get("statement_item")), text(r.get("note_reference_normalized")), f"附注 PDF {page or '?'}"])

    source = children.iloc[0].to_dict()
    pdf = _resolve_pdf_path(source, backend)
    statement_page = _safe_pdf_page(source.get("statement_pdf_page_index")) or _safe_pdf_page(source.get("statement_page"))
    st.markdown("#### 主报表证据")
    st.caption(chosen_anchor_label)
    if pdf and statement_page:
        from pdf_evidence import page_preview
        source_preview = page_preview(pdf, statement_page - 1, [text(source.get("display_name")), *(text(x) for x in children["member_table"].tolist())])
        _show_pdf_preview(st, source_preview, "主报表证据")
    else:
        st.warning("EVIDENCE_PAGE_UNRESOLVED：此主报表缺少可打开的 PDF 或有效页码。")

    children["子表审核对象"] = children.apply(business_label, axis=1)
    cols = [c for c in ["子表审核对象", "candidate_note_printed_page", "locator_method", "confidence", "review_status"] if c in children]
    st.markdown("#### 本主报表下的全部子表")
    st.dataframe(children[cols], use_container_width=True, hide_index=True)
    st.caption("下方同时提供每个子表的附注页预览；若没有 bbox/页码，会明确标记而不是伪造证据。")
    preview_columns = st.columns(2)
    for index, (_, child) in enumerate(children.iterrows()):
        with preview_columns[index % 2]:
            st.markdown(f"**{text(child.get('member_table') or child.get('statement_item'))}** · {text(child.get('note_reference_normalized'))}")
            note_page = _safe_pdf_page(child.get("candidate_note_pdf_page_index"))
            if pdf and note_page:
                from pdf_evidence import page_preview
                note_preview = page_preview(pdf, note_page - 1, [text(child.get("member_table") or child.get("statement_item"))])
                _show_pdf_preview(st, note_preview, "附注")
            else:
                st.info("未定位附注页：可标记 REVIEW_REQUIRED / UNRESOLVED。")

    # Only children from this specific source statement appear in the action UI.
    labels = dict(zip(children["子表审核对象"], children["discovery_id"]))
    chosen_labels = st.multiselect("④ 选择本主报表下要批量处理的子表", list(labels), default=list(labels), key="v651_anchor_child_select")
    ids = [labels[x] for x in chosen_labels]
    action = st.radio("⑤ 批量动作", ["ACCEPTED", "REJECTED", "REVIEW_REQUIRED", "UNRESOLVED"], horizontal=True)
    reason = st.text_input("审核理由", key="v65_review_reason")
    if st.button("保存批量审核", disabled=not ids, type="primary", key="v65_bulk_review"):
        backend.discovery_service.bulk_adjudicate(ids, label=action, reason=reason, scope="COMPANY_STATEMENT")
        st.success(f"已对 {len(ids)} 条候选逐条写入审计、认证知识和训练样本。")
    archived_for_anchor = archived.copy()
    if not archived_for_anchor.empty:
        archived_for_anchor["_anchor_key"] = archived_for_anchor.apply(anchor_key, axis=1)
        archived_for_anchor = archived_for_anchor[archived_for_anchor["_anchor_key"] == chosen_anchor]
    with st.expander(f"本主报表已处理归档（{len(archived_for_anchor)} 条，仅查看）", expanded=False):
        if archived_for_anchor.empty:
            st.caption("本主报表暂无已处理归档。")
        else:
            archived_for_anchor["子表审核对象"] = archived_for_anchor.apply(business_label, axis=1)
            archive_cols = [c for c in cols if c in archived_for_anchor]
            st.dataframe(archived_for_anchor[archive_cols], use_container_width=True, hide_index=True)
