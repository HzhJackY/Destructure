"""Stable session route shared by Inbox, Workspace, Merge and version history."""
from __future__ import annotations

from dataclasses import asdict, dataclass


REASON_TAB = {
    "BOUNDARY_REVIEW_REQUIRED": "附注容器与表块",
    "BOUNDARY_LOW_CONFIDENCE": "附注容器与表块",
    "HEADER_REVIEW_REQUIRED": "表头拓扑",
    "HEADER_AMBIGUOUS": "表头拓扑",
    "STRUCTURE_REVIEW_REQUIRED": "行结构",
    "ROW_STRUCTURE_AMBIGUOUS": "行结构",
    "RECONCILIATION_WARNING": "勾稽与质量",
    "UNIT_REVIEW_REQUIRED": "Canonical 数据",
    "UNIT_UNCERTAIN": "Canonical 数据",
}


@dataclass
class InspectionRoute:
    logical_asset_id: str
    capture_version_id: str
    table_block_id: str = ""
    initial_tab: str = "概览"
    return_route: str = ""
    review_queue_item_id: str = ""


def set_inspection_route(
    st, route: InspectionRoute, *, open_workspace: bool = False,
    update_selection: bool = True,
) -> None:
    payload=asdict(route)
    st.session_state["inspection_route"]=payload
    if update_selection:
        st.session_state["selected_logical_asset_id"]=route.logical_asset_id
        st.session_state["selected_capture_version_id"]=route.capture_version_id
    st.session_state["selected_table_block_id"]=route.table_block_id
    st.session_state["selected_inspection_tab"]=route.initial_tab
    st.session_state[f"inspection_tab_{route.logical_asset_id}"]=route.initial_tab
    if open_workspace:
        st.session_state["_pending_main_page"]="逻辑资产工作区"


def get_inspection_route(st) -> InspectionRoute | None:
    raw=st.session_state.get("inspection_route")
    if not raw: return None
    return InspectionRoute(**{field: str(raw.get(field) or "") for field in InspectionRoute.__dataclass_fields__})


def route_from_review(row: dict) -> InspectionRoute:
    reason=str(row.get("primary_review_reason") or "")
    return InspectionRoute(
        logical_asset_id=str(row["logical_asset_id"]),
        capture_version_id=str(row["capture_id"]),
        initial_tab=REASON_TAB.get(reason,"审核"),
        return_route="审核收件箱",
        review_queue_item_id=str(row.get("review_item_id") or ""),
    )
