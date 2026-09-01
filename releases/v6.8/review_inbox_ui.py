"""Faceted review inbox for logical Capture versions."""
from __future__ import annotations
import json
from pathlib import Path


def render_review_inbox(st, backend) -> None:
    st.title("审核收件箱")
    st.caption("只显示待处理版本；已确认、已拒绝和已归档记录与工作列表隔离。")
    saved_views = backend.review_inbox_service.list_views()
    view_options = ["不使用保存视图"] + [row["display_name"] for row in saved_views]
    chosen_view = st.selectbox("保存视图", view_options)
    active_view = next((row for row in saved_views if row["display_name"] == chosen_view), None)
    c1, c2, c3 = st.columns(3)
    status = c1.selectbox("状态", ["PENDING", "CONFIRMED", "REJECTED", "全部"])
    severity = c2.selectbox("严重性", ["全部", "CRITICAL", "HIGH", "MEDIUM", "LOW"])
    reason = c3.text_input("原因精确筛选")
    filters = dict((active_view or {}).get("filters") or {})
    if status != "全部": filters["status"] = status
    if status != "PENDING": filters["include_completed"] = True
    if severity != "全部": filters["severity"] = severity
    if reason: filters["primary_review_reason"] = reason
    c4, c5, c6 = st.columns(3)
    company = c4.text_input("公司")
    family = c5.text_input("表族")
    member = c6.text_input("子表")
    keyword = st.text_input("搜索 PDF、表名或资产")
    if company: filters["company_id"] = company
    if family: filters["table_family_id"] = family
    if member: filters["member_table_id"] = member
    if keyword: filters["search"] = keyword
    page_col, size_col, sort_col = st.columns(3)
    filters["page"] = page_col.number_input("页码", min_value=1, value=1)
    filters["page_size"] = size_col.selectbox("每页", [25, 50, 100, 200], index=1)
    filters["sort_by"] = sort_col.selectbox("排序", ["severity", "updated_at", "created_at", "company_id", "report_year"])
    rows = backend.review_inbox_service.list(**filters)
    event = st.dataframe(
        rows, use_container_width=True, hide_index=True,
        selection_mode="multi-row", on_select="rerun", key="v68_review_inbox",
    )
    selected = event.selection.rows if event else []
    ids = [rows[i]["capture_id"] for i in selected if i < len(rows)]
    confirm_gate = backend.review_inbox_service.validate_bulk_action(ids, "CONFIRMED") if ids else {"allowed": False}
    a, b = st.columns(2)
    if ids and not confirm_gate["allowed"]:
        st.warning("所选项目并非同一审核原因、证据不完整或含硬冲突，不能批量确认；可逐条审核或批量拒绝。")
    if a.button("批量确认", disabled=not ids or not confirm_gate["allowed"]):
        backend.review_inbox_service.bulk_resolve(ids, "CONFIRMED")
        st.rerun()
    if b.button("批量拒绝", disabled=not ids):
        backend.review_inbox_service.bulk_resolve(ids, "REJECTED")
        st.rerun()
    with st.expander("保存当前筛选"):
        view_name = st.text_input("视图名称")
        if st.button("保存视图", disabled=not view_name.strip()):
            backend.review_inbox_service.save_view(view_name.strip(), filters)
            st.rerun()
        if active_view:
            renamed = st.text_input("重命名当前视图", value=active_view["display_name"])
            rename_col, delete_col = st.columns(2)
            if rename_col.button("重命名", disabled=not renamed.strip()):
                backend.review_inbox_service.rename_view(active_view["view_id"], renamed.strip())
                st.rerun()
            if delete_col.button("删除当前视图"):
                backend.review_inbox_service.delete_view(active_view["view_id"])
                st.rerun()
    if len(selected) == 1:
        row = rows[selected[0]]
        st.subheader("所选审核项：证据与版本链")
        try:
            evidence = json.loads(row.get("evidence_summary_json") or "{}")
        except (TypeError, json.JSONDecodeError):
            evidence = {"raw": row.get("evidence_summary_json")}
        st.json({
            "审核原因": row.get("primary_review_reason"),
            "次要原因": row.get("secondary_review_reasons_json"),
            "证据": evidence,
            "来源PDF": row.get("pdf_name") or row.get("source_pdf_display"),
            "Capture": row.get("capture_id"),
        })
        lineage = backend.asset_query_service.get_asset_lineage(row["logical_asset_id"])
        with st.expander("Capture 版本链"):
            st.json(lineage)
        pdf_path = Path(str(row.get("pdf_path") or ""))
        page_candidates = [
            evidence.get("statement_pdf_page_index"),
            evidence.get("candidate_note_pdf_page_index"),
            evidence.get("confirmed_note_pdf_page_index"),
            evidence.get("start_page"),
            evidence.get("page"),
        ]
        page = next(
            (int(value) for value in page_candidates
             if value is not None and str(value).strip().isdigit() and int(value) > 0),
            None,
        )
        if pdf_path.is_file() and page:
            from pdf_evidence import page_preview
            preview = page_preview(
                pdf_path, page - 1,
                [str(row.get("member_table_id") or ""), str(row.get("table_family_id") or "")],
            )
            if preview.get("png"):
                st.image(
                    preview["png"],
                    caption=f"PDF {preview['pdf_page_index']}页（印刷页 {preview.get('printed_page') or '-'}）",
                    use_container_width=True,
                )
                st.caption(f"证据等级：{preview.get('evidence_level')} · 高亮框：{len(preview.get('bboxes') or [])}")
        elif pdf_path.is_file():
            st.info("源 PDF 可用，但审核原因未提供可验证页码；请通过版本链中的 Capture 证据查看。")
        action_cols = st.columns(6)
        if action_cols[0].button("确认", key="v68_single_confirm"):
            backend.review_inbox_service.resolve(row["capture_id"], "CONFIRMED")
            st.rerun()
        if action_cols[1].button("覆盖确认", key="v68_single_override"):
            backend.review_inbox_service.resolve(row["capture_id"], "CONFIRMED_OVERRIDE")
            st.rerun()
        if action_cols[2].button("拒绝", key="v68_single_reject"):
            backend.review_inbox_service.resolve(row["capture_id"], "REJECTED")
            st.rerun()
        if action_cols[3].button("标记未解决", key="v68_single_unresolved"):
            backend.review_inbox_service.resolve(row["capture_id"], "UNRESOLVED")
            st.rerun()
        if action_cols[4].button("重跑", key="v68_single_rerun"):
            backend.asset_service.rerun([row["capture_id"]])
            st.rerun()
        if action_cols[5].button("归档", key="v68_single_archive"):
            backend.archive_service.archive([row["logical_asset_id"]], reason="REVIEW_INBOX")
            st.rerun()
