"""Streamlit adapter for the v6.5 guided path.

The adapter intentionally keeps planning separate from manual capture.  It only
submits a capture plan after an explicit two-stage review.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

import pandas as pd


def render_guided_capture(st, backend, selected_pdfs: list[Path], infer_dimensions) -> None:
    st.subheader("研究引导抓取：发现 → 审核 → 认证计划 → 一键抓取")
    st.caption("该路径只输入一次研究目标；认证后不再重复选择目标表或表族。手工抓取在下方高级区独立保留。")
    display_name = st.text_input("研究目标 / display_name", placeholder="例如：金融投资、保险合同负债、投资收益", key="v65_display_name")
    presets = ["（无预设，纯通用发现）"] + list(__import__("generic_discovery").PRESETS)
    preset = st.selectbox("可选知识包", presets, key="v65_preset", help="预设只补充词表；任何 display_name 都可以发现。")
    if st.button("① 发现主报表 occurrence 与附注候选", key="v65_discover", disabled=not selected_pdfs or not display_name.strip()):
        raw: list[dict[str, Any]] = []
        for pdf in selected_pdfs:
            dim = infer_dimensions(pdf)
            raw.extend(backend.discovery_service.preview(pdf, display_name=display_name.strip(), company=dim["company"], report_year=dim["year"], preset_name=None if preset.startswith("（") else preset))
        st.session_state["v65_raw_discovery"] = raw
        st.session_state["v65_clusters"] = backend.discovery_service.cluster(raw)
        st.session_state["v65_occurrences"] = backend.discovery_service.proposed_occurrences(raw)
    clusters = st.session_state.get("v65_clusters", [])
    if not clusters:
        return
    table = pd.DataFrame(clusters)
    st.markdown("#### 阶段 A：审核抓什么（已先按证据聚类）")
    cols = [c for c in ["candidate_cluster_id", "company", "report_year", "display_name", "statement_type", "scope", "member_table", "statement_pdf_page_index", "candidate_note_pdf_page_index", "note_reference_normalized", "confidence", "evidence_count"] if c in table]
    st.dataframe(table[cols], use_container_width=True, hide_index=True)
    occurrences = st.session_state.get("v65_occurrences", [])
    selected_occurrence = None
    if occurrences:
        arbitration = backend.discovery_service.arbitrate(occurrences)
        st.caption(f"自动发现 {len(occurrences)} 个主报表 occurrence；Anchor Arbitration：{arbitration['status']}。")
        ids = [x["occurrence_id"] for x in occurrences]
        selected_occurrence_id = st.selectbox("选择主报表 Anchor occurrence", ids, format_func=lambda x: next(f"{o.get('source_table_title')} · {o.get('scope')} · PDF {o.get('statement_pdf_page_index')}" for o in occurrences if o['occurrence_id'] == x), key="v65_occurrence_choice")
        selected_occurrence = next(o for o in occurrences if o["occurrence_id"] == selected_occurrence_id)
    selected_clusters = st.multiselect("选择属于本表族的成员候选", table["candidate_cluster_id"].tolist(), default=table["candidate_cluster_id"].tolist(), key="v65_cluster_select")
    scope = st.selectbox("主报表口径", ["CONSOLIDATED", "COMPANY", "UNKNOWN"], key="v65_scope")
    parent = st.text_input("主报表父行", value=display_name, key="v65_parent")
    if st.button("② 生成可审核 Statement Anchor", key="v65_anchor", disabled=not selected_clusters):
        chosen = [x for x in clusters if x["candidate_cluster_id"] in selected_clusters]
        certified = backend.discovery_service.bulk_adjudicate(
            [x["discovery_id"] for x in chosen if x.get("discovery_id")],
            label="ACCEPTED", reason="阶段A：纳入 Statement Anchor", scope="COMPANY_STATEMENT",
        )
        first = chosen[0]
        child_rows = [{"item": x.get("statement_item") or x.get("member_table"), "member_table": x.get("member_table"),
                       "note_reference_normalized": x.get("note_reference_normalized") or x.get("note_reference") or "",
                       "candidate_note_pdf_page_index": x.get("candidate_note_pdf_page_index") or x.get("note_page"),
                       "value": x.get("statement_value"), "locator_method": x.get("locator_method"), "confidence": x.get("confidence")} for x in chosen]
        if selected_occurrence:
            # Keep the machine-discovered parent/children but permit review to
            # remove candidates not included in Stage A.
            accepted_names = {str(x.get("member_table")) for x in chosen}
            selected_occurrence["child_rows"] = [x for x in selected_occurrence.get("child_rows", []) if str(x.get("member_table")) in accepted_names]
            selected_occurrence["scope"] = scope
            occ = selected_occurrence
            backend.discovery_service.adjudicate_anchor(occ["occurrence_id"], label="ACCEPTED", chosen_scope=scope,
                                                        reason="阶段A：确认 Statement Anchor")
        else:
            occ = backend.discovery_service.build_occurrence(context={**first, "display_name": display_name, "table_family": display_name}, parent_text=parent, child_rows=child_rows, source_table_title=first.get("source_table_title") or first.get("statement_type"), scope=scope)
        st.session_state["v65_occurrence"] = occ
        st.session_state["v65_certified_ids"] = [x["discovery_id"] for x in certified]
    occurrence = st.session_state.get("v65_occurrence")
    if not occurrence:
        return
    st.markdown("#### 阶段 B：审核在哪里（主表页与附注页）")
    st.json({"source_statement": occurrence.get("source_table_title"), "scope": occurrence.get("scope"),
             "statement_pdf_page_index": occurrence.get("statement_pdf_page_index"), "statement_printed_page": occurrence.get("statement_printed_page"),
             "child_rows": occurrence.get("child_rows")})
    st.info("PDF 页预览使用上游 Capture/Review 的 bbox 证据；若本次发现尚未提供 bbox，界面会保留页码并标记人工复核，而不是伪造高亮。")
    if st.button("③ 认证并生成 Capture Plan", key="v65_plan"):
        st.session_state["v65_plan"] = backend.discovery_service.certified_capture_plan(
            occurrence, certified_ids=st.session_state.get("v65_certified_ids", [])
        )
    plan = st.session_state.get("v65_plan")
    if not plan:
        return
    st.success(f"已生成计划：1 个主报表构成 + {len(plan['items']) - 1} 个附注明细；状态 {plan['status']}。")
    st.dataframe(pd.DataFrame(plan["items"]), use_container_width=True, hide_index=True)
    current_pdf = selected_pdfs[0] if len(selected_pdfs) == 1 else None
    if current_pdf is None:
        st.warning("一键抓取需要先在本次引导流程中选择单个 PDF；多 PDF 可分别认证，避免跨报告混用锚点。")
    elif st.button("④ 确认并抓取全部已认证表", type="primary", key="v65_capture"):
        result = backend.guided_capture_service.execute(plan, pdf_path=current_pdf)
        st.success(f"已提交 {len(result['jobs'])} 个附注明细抓取作业；主报表锚点已保存为 {result['anchor_artifact']}。")
        if result["blocked_items"]:
            st.warning(f"{len(result['blocked_items'])} 个无确认页的成员保留 REVIEW_REQUIRED，未自动抓取。")


def render_review_center(st, backend) -> None:
    st.title("发现结果审核中心")
    rows = backend.discovery_registry.list_machine(limit=500)
    if not rows:
        st.info("暂无候选。请先运行“研究引导抓取”。")
        return
    table = pd.DataFrame(rows)
    st.caption("按成员、页码和证据聚类后批量审核；每个选择仍分别写入审计和训练样本。")
    filtered = table.copy()
    status = st.multiselect("状态", sorted(filtered["status"].dropna().unique()), default=["NEEDS_REVIEW", "REVIEW_REQUIRED"])
    if status:
        filtered = filtered[filtered["status"].isin(status)]
    cols = [c for c in ["discovery_id", "company", "report_year", "display_name", "statement_type", "scope", "member_table", "statement_pdf_page_index", "statement_printed_page", "candidate_note_pdf_page_index", "candidate_note_printed_page", "note_reference_normalized", "locator_method", "confidence", "status"] if c in filtered]
    st.dataframe(filtered[cols], use_container_width=True, hide_index=True)
    ids = st.multiselect("批量选择候选", filtered["discovery_id"].tolist(), key="v65_review_ids")
    action = st.radio("批量动作", ["ACCEPTED", "REJECTED", "REVIEW_REQUIRED", "UNRESOLVED"], horizontal=True)
    reason = st.text_input("审核理由", key="v65_review_reason")
    if st.button("保存批量审核", disabled=not ids, type="primary", key="v65_bulk_review"):
        backend.discovery_service.bulk_adjudicate(ids, label=action, reason=reason, scope="COMPANY_STATEMENT")
        st.success(f"已对 {len(ids)} 条候选逐条写入审计、认证知识和训练样本。")
