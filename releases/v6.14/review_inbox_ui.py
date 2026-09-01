"""Queue-only Review Inbox; all complex detail routes to the canonical Workspace."""
from __future__ import annotations

from inspection_route import route_from_review,set_inspection_route
from presentation_labels import classification_label


def _open_anchor_review(st,backend,row:dict)->None:
    st.session_state["v65_occurrences"]=backend.discovery_registry.occurrences(row["candidate_ids"])
    st.session_state["v65_clusters"]=[]
    st.session_state["v65_display_name"]=row["display_name"]
    st.session_state["_pending_main_page"]="整表批量工作台"


def _open_child_mapping_review(st,row:dict)->None:
    st.session_state["v610_review_anchor_id"]=row["anchor_id"]
    st.session_state["v610_review_anchor_child_id"]=row["anchor_child_id"]
    if row.get("logical_asset_id"):
        st.session_state["selected_logical_asset_id"]=row["logical_asset_id"]
        st.session_state["inspection_initial_tab"]="子表映射"
        st.session_state["_pending_main_page"]="逻辑资产工作区"
    else:
        st.session_state["_pending_main_page"]="整表批量工作台"


def render_review_inbox(st, backend) -> None:
    st.title("审核收件箱")
    st.caption("这里只管理待办、筛选、严重度和路由；单条 PDF/结构/勾稽审核统一在逻辑资产工作区完成。")
    anchor_rows=backend.discovery_registry.list_anchor_review_queue("PENDING")
    if anchor_rows:
        with st.expander(f"财务主报表锚点选择（{len(anchor_rows)}）",expanded=True):
            anchor_display=[{
                "严重度":row["severity"],"研究目标":row["display_name"],
                "口径":row["statement_scope"],"候选数":len(row["candidate_ids"]),
                "原因":"主报表候选存在歧义，需要人工单选",
                "来源 PDF":row["source_pdf_id"],
            } for row in anchor_rows]
            anchor_event=st.dataframe(
                anchor_display,use_container_width=True,hide_index=True,
                selection_mode="single-row",on_select="rerun",key="anchor_review_inbox_grid",
            )
            anchor_selected=list(anchor_event.selection.rows if anchor_event else [])
            if len(anchor_selected)==1:
                row=anchor_rows[anchor_selected[0]]
                st.button(
                    "打开财务主报表锚点选择",
                    type="primary",key="open_anchor_selection",
                    on_click=_open_anchor_review,args=(st,backend,row),
                )
    child_rows=backend.child_discovery_repository.child_review_queue("PENDING")
    if child_rows:
        with st.expander(f"附注逻辑表映射选择（{len(child_rows)}）",expanded=True):
            child_display=[{
                "锚点行项目":row["raw_label"],"口径":row["statement_scope"],
                "候选身份":classification_label(
                    row.get("classification") or row.get("member_role")
                ),
                "候选数":len(row["candidate_ids"]),
                "原因":"没有唯一高置信附注表候选，需要人工映射",
                "来源 PDF":row["source_pdf_id"],
            } for row in child_rows]
            child_event=st.dataframe(
                child_display,use_container_width=True,hide_index=True,
                selection_mode="single-row",on_select="rerun",
                key="child_mapping_review_inbox_grid",
            )
            child_selected=list(child_event.selection.rows if child_event else [])
            if len(child_selected)==1:
                row=child_rows[child_selected[0]]
                st.button(
                    "打开附注逻辑表映射",
                    type="primary",key="open_child_mapping_review",
                    on_click=_open_child_mapping_review,args=(st,row),
                )
    saved_views=backend.review_inbox_service.list_views()
    options=["不使用保存视图"]+[row["display_name"] for row in saved_views]
    selected_view=st.selectbox("保存视图",options,key="review_saved_view")
    active_view=next((row for row in saved_views if row["display_name"]==selected_view),None)
    cols=st.columns(4)
    status=cols[0].selectbox("状态",["PENDING","全部","CONFIRMED_HUMAN","REJECTED","UNRESOLVED"],key="review_status_filter")
    severity=cols[1].selectbox("严重性",["全部","CRITICAL","HIGH","MEDIUM","LOW"],key="review_severity_filter")
    reason=cols[2].text_input("审核原因",key="review_reason_filter")
    company=cols[3].text_input("公司",key="review_company_filter")
    cols2=st.columns(4)
    family=cols2[0].text_input("表族",key="review_family_filter")
    member=cols2[1].text_input("子表",key="review_member_filter")
    keyword=cols2[2].text_input("搜索 PDF/资产",key="review_search")
    sort_by=cols2[3].selectbox("排序",["severity","updated_at","created_at","company_id","report_year"],key="review_sort")
    filters=dict((active_view or {}).get("filters") or {})
    if status!="全部":filters["status"]=status
    if status!="PENDING":filters["include_completed"]=True
    if severity!="全部":filters["severity"]=severity
    if reason:filters["primary_review_reason"]=reason
    if company:filters["company_id"]=company
    if family:filters["table_family_id"]=family
    if member:filters["member_table_id"]=member
    if keyword:filters["search"]=keyword
    filters.update({"sort_by":sort_by,"page_size":200})
    rows=backend.review_inbox_service.list(**filters)
    if not rows:
        st.success("当前筛选下没有 Capture Version 待审核项目。")
        return
    display=[{
        "严重度":row.get("severity"),"公司":row.get("company_id"),"年度":row.get("report_year"),
        "表族":row.get("table_family_id"),"子表":row.get("member_table_id"),
        "Capture Version":row.get("capture_version"),"原因":row.get("primary_review_reason"),
        "质量":row.get("quality_status"),"生命周期":row.get("asset_status"),
        "Capture":row.get("capture_id"),
    } for row in rows]
    event=st.dataframe(display,use_container_width=True,hide_index=True,selection_mode="multi-row",on_select="rerun",key="review_inbox_grid")
    selected=list(event.selection.rows if event else [])
    selected_rows=[rows[i] for i in selected if i<len(rows)]
    ids=[str(row["capture_id"]) for row in selected_rows]
    left,middle,right=st.columns(3)
    if len(selected_rows)==1:
        route=route_from_review(selected_rows[0])
        left.button(
            "打开资产并审核",type="primary",key="open_asset_from_review",
            on_click=set_inspection_route,args=(st,route),kwargs={"open_workspace":True},
        )
    else:
        left.button("打开资产并审核",disabled=True,key="open_asset_from_review_disabled")
    gate=backend.review_inbox_service.validate_bulk_action(ids,"CONFIRMED") if ids else {"allowed":False}
    if middle.button("安全批量确认",disabled=not ids or not gate.get("allowed"),key="bulk_confirm_review"):
        backend.review_inbox_service.bulk_resolve(ids,"CONFIRMED")
        st.rerun()
    if right.button("批量拒绝",disabled=not ids,key="bulk_reject_review"):
        backend.review_inbox_service.bulk_resolve(ids,"REJECTED")
        st.rerun()
    if ids and not gate.get("allowed"):
        st.caption("批量确认仅允许同一原因、证据完整且无硬冲突的待办；复杂审核请打开资产。")
    with st.expander("保存当前队列视图"):
        view_name=st.text_input("视图名称",key="review_view_name")
        if st.button("保存视图",disabled=not view_name.strip(),key="save_review_view"):
            backend.review_inbox_service.save_view(view_name.strip(),filters)
            st.rerun()
