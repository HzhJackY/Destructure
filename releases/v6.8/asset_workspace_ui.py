"""Logical asset/version workspace and archive operations."""
from __future__ import annotations


def render_asset_workspace(st, backend) -> None:
    st.title("逻辑资产工作区")
    saved_views = backend.asset_query_service.list_views()
    view_labels = ["不使用保存视图"] + [row["display_name"] for row in saved_views]
    selected_view_label = st.selectbox("资产保存视图", view_labels)
    selected_view = next(
        (row for row in saved_views if row["display_name"] == selected_view_label), None
    )
    include_archived = st.toggle("显示已归档资产", value=False)
    keyword = st.text_input("搜索公司、表族、子表、PDF 或逻辑资产")
    page_col, size_col, sort_col = st.columns(3)
    page = page_col.number_input("页码", min_value=1, value=1)
    page_size = size_col.selectbox("每页", [25, 50, 100, 200], index=1)
    sort_field = sort_col.selectbox("排序", ["company_id", "updated_at", "report_year", "table_family_id"])
    rows = backend.asset_query_service.search(
        include_archived=include_archived, search=keyword,
        pagination={"page": page, "page_size": page_size},
        sort={"field": sort_field, "direction": "DESC" if sort_field in {"updated_at", "report_year"} else "ASC"},
    )
    facets = backend.asset_query_service.facets(rows)
    cols = st.columns(4)
    filters = dict((selected_view or {}).get("filters") or {})
    for col, field, label in zip(
        cols,
        ("company_id", "report_year", "table_family_id", "quality_status"),
        ("公司", "报告年度", "表族", "质量状态"),
    ):
        choice = col.selectbox(label, ["全部"] + facets.get(field, []), key=f"asset_{field}")
        if choice != "全部": filters[field] = choice
    if filters:
        rows = backend.asset_query_service.search(
            filters=filters, include_archived=include_archived, search=keyword,
            pagination={"page": page, "page_size": page_size},
            sort={"field": sort_field, "direction": "DESC" if sort_field in {"updated_at", "report_year"} else "ASC"},
        )
    event = st.dataframe(rows, use_container_width=True, hide_index=True,
                         selection_mode="multi-row", on_select="rerun", key="v68_asset_grid")
    selected = event.selection.rows if event else []
    logical_ids = sorted({rows[i]["logical_asset_id"] for i in selected if i < len(rows)})
    a, b = st.columns(2)
    if a.button("归档所选逻辑资产", disabled=not logical_ids):
        backend.archive_service.archive(logical_ids, reason="ASSET_WORKSPACE")
        st.rerun()
    if b.button("恢复所选逻辑资产", disabled=not logical_ids):
        backend.archive_service.restore(logical_ids, reason="ASSET_WORKSPACE")
        st.rerun()
    with st.expander("保存与管理当前资产视图"):
        view_name = st.text_input("资产视图名称")
        if st.button("保存资产视图", disabled=not view_name.strip()):
            backend.asset_query_service.save_view(
                view_name.strip(), filters,
                {"field": sort_field, "direction": "DESC" if sort_field in {"updated_at", "report_year"} else "ASC"},
            )
            st.rerun()
        if selected_view:
            renamed = st.text_input("重命名资产视图", value=selected_view["display_name"])
            rename_col, delete_col = st.columns(2)
            if rename_col.button("重命名资产视图", disabled=not renamed.strip()):
                backend.asset_query_service.rename_view(selected_view["view_id"], renamed.strip())
                st.rerun()
            if delete_col.button("删除资产视图"):
                backend.asset_query_service.delete_view(selected_view["view_id"])
                st.rerun()
    st.subheader("可进入合表的当前认证版本")
    st.dataframe(backend.merge_eligibility_service.eligible_assets(filters),
                 use_container_width=True, hide_index=True)
