from __future__ import annotations

import json


def render_compound_container_panel(st, backend, detail: dict, bundle: dict | None) -> dict | None:
    if not bundle:
        st.info("该 Capture 不属于多表附注 Bundle。")
        return None
    header=bundle["bundle"]
    st.metric("Bundle 状态",header.get("status"))
    children=bundle.get("children") or []
    st.dataframe([{
        "顺序":row.get("child_order"),"Block":row.get("block_title"),
        "角色":row.get("block_role"),"分类轴":row.get("classification_axis"),
        "终止类型":row.get("block_terminal_type"),
        "页码":f"{row.get('start_pdf_page')}–{row.get('end_pdf_page')}",
        "Capture":row.get("capture_id"),"质量":row.get("quality_status") or row.get("block_quality_status"),
        "审核":row.get("review_status"),"生命周期":row.get("asset_status"),
        "勾稽":json.loads(row.get("reconciliation_json") or "{}").get("status"),
    } for row in children],use_container_width=True,hide_index=True)
    options={str(row["block_id"]):row for row in children}
    selected_id=st.selectbox("表块",list(options),format_func=lambda x:f"{options[x].get('child_order')}. {options[x].get('block_title')}",key=f"inspection_block_{detail['capture_id']}")
    selected=options[selected_id]
    st.session_state["selected_table_block_id"]=selected_id
    if selected.get("capture_id") and selected.get("logical_asset_id"):
        from inspection_route import InspectionRoute,set_inspection_route
        st.button(
            "打开此子 Capture 的完整审核",
            key=f"open_child_{detail['capture_id']}_{selected_id}",
            on_click=set_inspection_route,
            args=(st,InspectionRoute(
                logical_asset_id=str(selected["logical_asset_id"]),
                capture_version_id=str(selected["capture_id"]),
                table_block_id=selected_id,initial_tab="概览",
                return_route="逻辑资产工作区",
            )),
            kwargs={"open_workspace":True},
        )
    left,right=st.columns(2)
    with left:
        st.caption("表头拓扑")
        st.json(json.loads(selected.get("header_topology_json") or "{}"))
    with right:
        st.caption("勾稽")
        st.json(json.loads(selected.get("reconciliation_json") or "{}"))
    st.caption("结构调整会生成新 Capture Version，不改写机器证据。")
    edit_type=st.selectbox("受控结构调整",["不调整","SPLIT_BLOCK","MERGE_BLOCK","MOVE_BOUNDARY","CHANGE_BLOCK_TYPE","CHANGE_SUBTABLE_ROLE"],key=f"block_edit_{detail['capture_id']}")
    payload=st.text_area("调整说明/参数（JSON 或文字）",key=f"block_edit_payload_{detail['capture_id']}")
    if st.button("创建结构修订版本",disabled=edit_type=="不调整",key=f"create_revision_{detail['capture_id']}"):
        try:
            parsed=json.loads(payload) if payload.strip().startswith(("{","[")) else {"note":payload}
            out=backend.capture_version_service.create_structure_revision(
                capture_id=detail["capture_id"],revision_type=edit_type,payload=parsed,
                table_block_id=selected_id,
            )
            st.session_state["pending_inspection_route"]={
                "logical_asset_id":out["logical_asset_id"],
                "capture_version_id":out["new_capture_id"],
                "table_block_id":selected_id,
                "initial_tab":"审核",
                "return_route":"逻辑资产工作区",
                "review_queue_item_id":"",
            }
            st.success(f"已生成新版本：{out['new_capture_id']}")
            st.rerun()
        except Exception as exc:
            st.error(str(exc))
    return selected
