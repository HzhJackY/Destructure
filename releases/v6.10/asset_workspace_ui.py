"""Canonical Logical Asset master-detail workspace for v6.9."""
from __future__ import annotations

from components.capture_inspection_panel import render_capture_inspection_panel
from inspection_route import InspectionRoute,get_inspection_route,set_inspection_route


def _human_label(row: dict) -> str:
    return "｜".join(filter(None,[
        str(row.get("company_id") or "未知公司"),
        f"{row.get('report_year')}年报" if row.get("report_year") else "",
        str(row.get("table_family_id") or ""),
        str(row.get("member_table_id") or row.get("table_query") or ""),
    ]))


def render_asset_workspace(st, backend) -> None:
    st.title("逻辑资产工作区")
    st.caption("唯一的单条资产详情、PDF证据、结构审核、版本治理和影响分析中心。")
    pending=st.session_state.pop("pending_inspection_route",None)
    if pending:
        # Revision buttons run after widgets exist. Consume the pending route on
        # the next rerun, before selection widgets are instantiated.
        st.session_state.pop("selected_logical_asset_id",None)
        st.session_state.pop("selected_capture_version_id",None)
        st.session_state["inspection_route"]=pending
    route=get_inspection_route(st)
    review_queue=list(st.session_state.get("asset_workspace_review_queue") or [])
    if review_queue:
        st.subheader("本批次待审核 Capture")
        st.caption(
            "这里列出的是跨多个逻辑资产的审核队列；下方 Capture Version "
            "只表示当前逻辑资产自己的历史版本。"
        )
        queue_map={str(row["capture_id"]):row for row in review_queue if row.get("capture_id")}
        queue_ids=list(queue_map)
        queue_preferred=(
            route.capture_version_id if route and route.capture_version_id in queue_map
            else queue_ids[0]
        )
        queue_capture=st.selectbox(
            "待审核 Capture",queue_ids,index=queue_ids.index(queue_preferred),
            format_func=lambda capture_id:(
                f"{queue_map[capture_id].get('company_id') or '未知公司'}｜"
                f"{queue_map[capture_id].get('report_year') or ''}｜"
                f"{queue_map[capture_id].get('member_table_id') or queue_map[capture_id].get('member_table') or ''}"
                f" · {capture_id}"
            ),
            key="asset_workspace_review_queue_capture",
        )
        queue_index=queue_ids.index(queue_capture)
        nav_prev,nav_progress,nav_next,nav_return=st.columns([1,1.4,1,1.4])
        def _move_queue(target_capture: str) -> None:
            st.session_state["asset_workspace_review_queue_capture"]=target_capture
            st.session_state.pop("selected_logical_asset_id",None)
            st.session_state.pop("selected_capture_version_id",None)
            st.session_state.pop("inspection_route",None)
        nav_prev.button(
            "上一张",disabled=queue_index==0,key="asset_queue_previous",
            on_click=_move_queue,args=(queue_ids[max(0,queue_index-1)],),
        )
        nav_progress.caption(f"第 {queue_index+1}/{len(queue_ids)} 张")
        nav_next.button(
            "下一张",disabled=queue_index>=len(queue_ids)-1,key="asset_queue_next",
            on_click=_move_queue,args=(queue_ids[min(len(queue_ids)-1,queue_index+1)],),
        )
        def _return_to_batch() -> None:
            st.session_state["_pending_main_page"]="整表批量工作台"
        nav_return.button(
            "返回批次监控",key="asset_queue_return_batch",
            on_click=_return_to_batch,
        )
        queued=queue_map[queue_capture]
        if (
            not route
            or route.capture_version_id != queue_capture
            or route.logical_asset_id != str(queued.get("logical_asset_id") or "")
        ):
            route=InspectionRoute(
                logical_asset_id=str(queued.get("logical_asset_id") or ""),
                capture_version_id=queue_capture,
                initial_tab=str(queued.get("initial_tab") or "审核"),
                return_route=str(queued.get("return_route") or "整表批量工作台"),
            )
    saved_views=backend.asset_query_service.list_views()
    view_labels=["不使用保存视图"]+[row["display_name"] for row in saved_views]
    selected_view_label=st.selectbox("资产保存视图",view_labels,key="asset_saved_view")
    selected_view=next((row for row in saved_views if row["display_name"]==selected_view_label),None)
    include_archived=st.toggle("显示历史/归档资产",value=False,key="asset_include_archived")
    keyword=st.text_input("搜索公司、表族、子表、PDF 或逻辑资产",key="asset_search")
    fcols=st.columns(7)
    filter_fields=[
        ("company_id","公司"),("report_year","报告年度"),("research_batch_id","研究批次"),
        ("table_family_id","表族"),
        ("member_table_id","子表"),("quality_status","质量"),("review_status","审核"),
    ]
    base_rows=backend.asset_query_service.search(
        include_archived=True,search=keyword,pagination={"page_size":2000},
    )
    facets=backend.asset_query_service.facets(base_rows)
    filters=dict((selected_view or {}).get("filters") or {})
    for col,(field,label) in zip(fcols,filter_fields):
        choice=col.selectbox(label,["全部"]+facets.get(field,[]),key=f"asset_filter_{field}")
        if choice!="全部":filters[field]=choice
    page_col,size_col,sort_col=st.columns(3)
    page=int(page_col.number_input("页码",min_value=1,value=1,key="asset_page"))
    page_size=int(size_col.selectbox("每页",[25,50,100,200],index=1,key="asset_page_size"))
    sort_field=sort_col.selectbox("排序",["company_id","updated_at","report_year","table_family_id"],key="asset_sort")
    rows=backend.asset_query_service.search(
        filters=filters,include_archived=include_archived,search=keyword,
        pagination={"page":page,"page_size":page_size},
        sort={"field":sort_field,"direction":"DESC" if sort_field in {"updated_at","report_year"} else "ASC"},
    )
    if not rows:
        st.info("没有匹配的逻辑资产。")
        return

    # One master row per logical asset; version selection belongs in detail.
    masters={}
    for row in rows:
        asset_id=str(row["logical_asset_id"])
        current=masters.get(asset_id)
        if current is None or bool(row.get("is_current")) or int(row.get("capture_version") or 0)>int(current.get("capture_version") or 0):
            masters[asset_id]=row
    master_rows=list(masters.values())
    options=[str(row["logical_asset_id"]) for row in master_rows]
    preferred=(route.logical_asset_id if route and route.logical_asset_id in options else st.session_state.get("selected_logical_asset_id"))
    if preferred not in options:preferred=options[0]
    selected_asset=st.selectbox(
        "Logical Asset（公司/年度/表族/子表的稳定身份）",options,index=options.index(preferred),
        format_func=lambda x:_human_label(masters[x]),key="selected_logical_asset_id",
    )
    master=masters[selected_asset]
    st.dataframe([{
        "资产":_human_label(row),"当前版本":row.get("capture_version"),
        "生命周期":row.get("asset_status"),"审核":row.get("review_status"),
        "质量":row.get("quality_status"),"口径":row.get("statement_scope"),
        "生产版本":row.get("producer_version"),
    } for row in master_rows],use_container_width=True,hide_index=True)

    versions=backend.capture_version_service.versions(selected_asset)
    if not include_archived:
        versions=[
            row for row in versions
            if str(row.get("asset_status") or "") not in {
                "ARCHIVED","TRASHED","SUPERSEDED","INVALIDATED",
            }
        ]
    if not versions:
        st.info("该逻辑资产在当前生命周期筛选下没有可显示的 Capture Version。")
        return
    version_ids=[str(row["capture_id"]) for row in versions]
    preferred_version=(
        route.capture_version_id if route and route.logical_asset_id==selected_asset and route.capture_version_id in version_ids
        else st.session_state.get("selected_capture_version_id")
    )
    if preferred_version not in version_ids:
        preferred_version=next((str(row["capture_id"]) for row in versions if row.get("is_current")),version_ids[0])
    selected_version=st.selectbox(
        "Capture Version（仅当前 Logical Asset 的历史抓取版本）",version_ids,index=version_ids.index(preferred_version),
        format_func=lambda x:next(
            f"v{row['capture_version']} · {row['asset_status']} · {x}"
            for row in versions if str(row["capture_id"])==x
        ),key="selected_capture_version_id",
    )
    initial_tab=(route.initial_tab if route and route.logical_asset_id==selected_asset and route.capture_version_id==selected_version else st.session_state.get("selected_inspection_tab") or "概览")
    active_route=InspectionRoute(
        logical_asset_id=selected_asset,capture_version_id=selected_version,
        table_block_id=st.session_state.get("selected_table_block_id",""),
        initial_tab=initial_tab,return_route=(route.return_route if route else ""),
        review_queue_item_id=(route.review_queue_item_id if route else ""),
    )
    st.session_state["inspection_route"]=active_route.__dict__
    chosen=next(row for row in versions if str(row["capture_id"])==selected_version)
    readonly=str(chosen.get("asset_status")) in {"SUPERSEDED","INVALIDATED","TRASHED","ARCHIVED"}
    render_capture_inspection_panel(
        st,backend,logical_asset_id=selected_asset,capture_version_id=selected_version,
        initial_tab=initial_tab,readonly_mode=readonly,
    )

    with st.expander("资产级操作与保存视图"):
        a,b=st.columns(2)
        if a.button("归档当前逻辑资产",key="archive_selected_asset"):
            backend.archive_service.archive([selected_asset],reason="LOGICAL_ASSET_WORKSPACE")
            st.rerun()
        if b.button("恢复当前逻辑资产",key="restore_selected_asset"):
            backend.archive_service.restore([selected_asset],reason="LOGICAL_ASSET_WORKSPACE")
            st.rerun()
        view_name=st.text_input("保存视图名称",key="asset_view_name")
        if st.button("保存当前筛选",disabled=not view_name.strip(),key="save_asset_view"):
            backend.asset_query_service.save_view(view_name.strip(),filters,{"field":sort_field})
            st.rerun()
