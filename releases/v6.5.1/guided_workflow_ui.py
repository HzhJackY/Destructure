"""Streamlit adapter for the v6.5 guided path.

The adapter intentionally keeps planning separate from manual capture.  It only
submits a capture plan after an explicit two-stage review.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

import pandas as pd


def _safe_pdf_page(value: Any) -> int | None:
    """Accept legacy SQLite NULL/NaN values without pretending they are pages."""
    if value is None or pd.isna(value):
        return None
    try:
        page = int(float(value))
    except (TypeError, ValueError):
        return None
    return page if page > 0 else None


def render_guided_capture(st, backend, selected_pdfs: list[Path], infer_dimensions) -> None:
    st.subheader("研究引导抓取：发现 → 审核 → 认证计划 → 一键抓取")
    st.caption("该路径只输入一次研究目标；认证后不再重复选择目标表或表族。手工抓取在下方高级区独立保留。")
    display_name = st.text_input("研究目标 / display_name", placeholder="例如：金融投资、保险合同负债、投资收益", key="v65_display_name")
    presets = ["（无预设，纯通用发现）"] + list(__import__("generic_discovery").PRESETS)
    preset = st.selectbox("可选知识包", presets, key="v65_preset", help="预设只补充词表；任何 display_name 都可以发现。")
    if st.button("① 发现主报表 occurrence 与附注候选", key="v65_discover", disabled=not selected_pdfs or not display_name.strip()):
        raw: list[dict[str, Any]] = []
        direct_occurrences = []
        for pdf in selected_pdfs:
            dim = infer_dimensions(pdf)
            raw.extend(backend.discovery_service.preview(pdf, display_name=display_name.strip(), company=dim["company"], report_year=dim["year"], preset_name=None if preset.startswith("（") else preset))
            if display_name.strip() == "金融投资":
                from pdf_evidence import extract_statement_anchor
                found = extract_statement_anchor(pdf)
                if found.get("status") == "FOUND":
                    context = {"pdf_id": str(pdf), "company": dim["company"], "normalized_company": dim["company"], "report_year": dim["year"],
                               "display_name": "金融投资", "table_family": "金融投资", "statement_type": "BALANCE_SHEET",
                               "statement_pdf_page_index": found["statement_pdf_page_index"], "statement_printed_page": found["statement_printed_page"],
                               "source_table_title": found["source_table_title"], "evidence": {"real_pdf": True, "parent_bbox": found["parent_bbox"]}}
                    direct_occurrences.append(backend.discovery_service.build_occurrence(context=context, parent_text="金融投资", child_rows=found["children"], source_table_title=found["source_table_title"], scope="CONSOLIDATED"))
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
        st.caption("每份 PDF 都保留独立 Anchor Decision；批量确认只减少点击次数，不会把不同年份混成一个主报表。")
        def occurrence_label(o):
            return " | ".join(str(x or "-") for x in [o.get("company"), o.get("report_year"), o.get("scope"), o.get("source_table_title"), o.get("display_name"), f"PDF {o.get('statement_pdf_page_index') or '?'}（印刷页 {o.get('statement_printed_page') or '?'}）"])
        occurrence_labels = {occurrence_label(o): o["occurrence_id"] for o in occurrences}
        selected_occurrence_labels = st.multiselect(
            "选择要认证的主报表 Anchor（可多选）", list(occurrence_labels),
            default=list(occurrence_labels), key="v651_occurrence_select",
        )
        selected_occurrence_ids = [occurrence_labels[x] for x in selected_occurrence_labels]
    else:
        selected_occurrence_ids = []
    if st.button("② 认证所选 Anchor 并生成每份报告的 Capture Plan", key="v651_certify_plans", disabled=not selected_occurrence_ids):
        chosen_occurrences = [o for o in occurrences if o["occurrence_id"] in selected_occurrence_ids]
        backend.discovery_service.bulk_adjudicate_anchors(
            selected_occurrence_ids, label="ACCEPTED", chosen_scope="", reason="阶段A：批量认证；每份来源 PDF 独立 Anchor Decision",
        )
        plans = [backend.discovery_service.certified_capture_plan(o, certified_ids=[]) for o in chosen_occurrences]
        # Do not reuse a widget key here: Streamlit forbids mutating a widget's
        # session-state key after it has been instantiated in this run.
        st.session_state["v651_certified_plans"] = plans
        st.session_state["v651_certified_occurrence_ids"] = selected_occurrence_ids
    plans = st.session_state.get("v651_certified_plans", [])
    if not plans:
        return
    st.markdown("#### 阶段 B：审核在哪里（主表页与附注页）")
    st.success(f"已生成 {len(plans)} 份独立 Capture Plan：共 {sum(len(p['items']) for p in plans)} 个表资产。")
    for plan in plans:
        pdf = Path(str(plan.get("pdf_id") or ""))
        anchor = plan.get("anchor") or {}
        with st.expander(f"{pdf.name or plan.get('anchor_occurrence_id')}：1 个主报表构成 + {len(plan['items']) - 1} 个附注明细", expanded=False):
            st.dataframe(pd.DataFrame(plan["items"]), use_container_width=True, hide_index=True)
            if pdf.exists() and anchor.get("statement_pdf_page_index"):
                from pdf_evidence import page_preview
                preview = page_preview(pdf, int(anchor["statement_pdf_page_index"]) - 1,
                                       [str(x.get("item") or "") for x in anchor.get("rows", [])])
                st.caption(f"主报表：PDF {preview['pdf_page_index']}（印刷页 {preview['printed_page'] or '未识别'}）· {preview['evidence_level']}")
                st.image(preview["png"])
    if st.button("③ 确认并抓取全部已认证表", type="primary", key="v651_capture_all"):
        results = []
        for plan in plans:
            pdf = Path(str(plan.get("pdf_id") or ""))
            if pdf.exists():
                results.append(backend.guided_capture_service.execute(plan, pdf_path=pdf))
        jobs = sum(len(x.get("jobs", [])) for x in results)
        blocked = sum(len(x.get("blocked_items", [])) for x in results)
        st.session_state["v651_guided_batch_ids"] = [x["batch_id"] for x in results if x.get("batch_id")]
        st.success(f"已按来源 PDF 分别提交 {jobs} 个附注明细抓取作业；{len(results)} 个主报表锚点已保存。")
        if blocked:
            st.warning(f"{blocked} 个无确认页的成员保留 REVIEW_REQUIRED，未自动抓取。")
    guided_batches = st.session_state.get("v651_guided_batch_ids", [])
    if guided_batches:
        st.markdown("#### 本次引导抓取作业监控")
        st.caption("作业监控属于本工作台；无需前往“系统与迁移”。每个来源 PDF 保持独立批次。")
        monitor_rows = []
        for guided_batch in guided_batches:
            summary = backend.table_capture_runner.monitor(guided_batch)
            monitor_rows.extend([{
                "批次": guided_batch, "总作业": summary["total"], "已完成": summary["complete"],
                "运行中": summary["counts"].get("RUNNING", 0), "失败": summary["counts"].get("FAILED", 0),
                "进度": f"{summary['progress']:.0%}",
            }])
        st.dataframe(pd.DataFrame(monitor_rows), use_container_width=True, hide_index=True)
        if st.button("刷新本次引导抓取进度", key="v651_refresh_guided_jobs"):
            st.rerun()
        failed_guided_batches = [row["批次"] for row in monitor_rows if row["失败"]]
        if failed_guided_batches:
            retry_batch = st.selectbox("选择需重试的引导批次", failed_guided_batches, key="v651_retry_guided_batch")
            if st.button("重试该批失败作业", key="v651_retry_guided_jobs"):
                retries = backend.table_capture_runner.retry_failed(batch_id=retry_batch, max_workers=3)
                st.success(f"已创建 {len(retries)} 个重试作业；请刷新本工作台中的进度。")


def render_review_center(st, backend) -> None:
    st.title("发现结果审核中心")
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
    pdf = Path(str(source.get("pdf_id") or ""))
    statement_page = _safe_pdf_page(source.get("statement_pdf_page_index")) or _safe_pdf_page(source.get("statement_page"))
    st.markdown("#### 主报表证据")
    st.caption(chosen_anchor_label)
    if pdf.exists() and statement_page:
        from pdf_evidence import page_preview
        source_preview = page_preview(pdf, statement_page - 1, [text(source.get("display_name")), *(text(x) for x in children["member_table"].tolist())])
        st.caption(f"PDF {source_preview['pdf_page_index']}（印刷页 {source_preview['printed_page'] or '未识别'}）· {source_preview['evidence_level']}")
        st.image(source_preview["png"])
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
            if pdf.exists() and note_page:
                from pdf_evidence import page_preview
                note_preview = page_preview(pdf, note_page - 1, [text(child.get("member_table") or child.get("statement_item"))])
                st.caption(f"附注：PDF {note_preview['pdf_page_index']}（印刷页 {note_preview['printed_page'] or '未识别'}）· {note_preview['evidence_level']}")
                st.image(note_preview["png"])
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
