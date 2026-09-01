"""Unified Stage B certified-child capture execution panel.

Both the strict-child-mapping flow and the explicit-note-target compat flow
render through this single component.  It provides:

- A "确认并抓取全部已认证子表" button
- Real-time batch progress display (QUEUED / RUNNING / SUCCESS / FAILED)
- Retry controls for failed batches
- Completion redirect to the Logical Asset Workspace with a filtered review queue
"""
from __future__ import annotations

from typing import Any

import pandas as pd
import streamlit as st


def render_child_capture_execution_panel(
    st_obj: Any,
    backend: Any,
    *,
    display_name: str,
    certified_links: list[dict[str, Any]] | None = None,
    plans: list[dict[str, Any]] | None = None,
    source_pdf_map: dict[str, Any] | None = None,
    research_definition: dict[str, Any] | None = None,
    scope: str = "",
    key_prefix: str = "v610_child_capture",
) -> dict[str, Any]:
    """Render the unified certified-child capture execution panel.

    Parameters
    ----------
    certified_links:
        From the strict flow — list of CertifiedChildTableLink dicts.
    plans:
        From the compat flow — list of Capture Plan dicts.
    source_pdf_map:
        Mapping from pdf_id to Path for the strict flow.
    key_prefix:
        Unique prefix for Streamlit widget keys so the two flows don't collide.

    Returns
    -------
    A dict describing the current execution state:
        ``{"executed": bool, "batch_ids": list[str], "research_batch_id": str, "review_queue": list}``
    """
    # ---- state keys ----
    exec_key = f"{key_prefix}_executed"
    batch_ids_key = f"{key_prefix}_batch_ids"
    research_batch_key = f"{key_prefix}_research_batch_id"
    plans_key = f"{key_prefix}_plans"

    executed = bool(st_obj.session_state.get(exec_key, False))
    batch_ids: list[str] = st_obj.session_state.get(batch_ids_key, [])
    research_batch_id: str = st_obj.session_state.get(research_batch_key, "")
    saved_plans: list[dict[str, Any]] = st_obj.session_state.get(plans_key, [])

    can_execute = bool(certified_links or (plans or saved_plans))

    # ---- execute button ----
    if st_obj.button(
        "确认并抓取全部已认证子表",
        type="primary",
        disabled=not can_execute or executed,
        key=f"{key_prefix}_execute_btn",
    ):
        _plans = plans or saved_plans
        result = backend.child_capture_execution_service.create_execution_batch(
            display_name=display_name,
            certified_links=certified_links,
            source_pdf_map=source_pdf_map,
            plans=_plans,
            research_definition=research_definition,
            scope=scope,
        )
        st_obj.session_state[exec_key] = True
        st_obj.session_state[batch_ids_key] = result["batch_ids"]
        st_obj.session_state[research_batch_key] = result["research_batch_id"]
        batch_ids = result["batch_ids"]
        research_batch_id = result["research_batch_id"]

        job_word = "附注明细" if plans else "认证子表"
        st_obj.success(
            f"研究批次 {research_batch_id} 已提交："
            f"{result['job_count']} 个{job_word}抓取作业。"
        )
        if result.get("blocked_count"):
            st_obj.warning(
                f"{result['blocked_count']} 个无确认目标的项目保留 REVIEW_REQUIRED，未自动抓取。"
            )
        st_obj.rerun()

    # ---- progress display ----
    if executed and batch_ids:
        st_obj.markdown("#### 本次抓取作业监控")
        st_obj.caption("作业监控属于本工作台；无需前往“系统与迁移”。")

        svc = backend.child_capture_execution_service
        monitor_rows = svc.monitor_all(batch_ids)

        if monitor_rows:
            st_obj.dataframe(
                pd.DataFrame(monitor_rows),
                use_container_width=True,
                hide_index=True,
            )

        if st_obj.button("刷新进度", key=f"{key_prefix}_refresh"):
            st_obj.rerun()

        all_done = svc.all_terminal(batch_ids)

        # ---- completion redirect ----
        if research_batch_id and all_done:
            review_queue = svc.build_review_queue(research_batch_id)

            if review_queue:
                st_obj.warning(
                    f"作业执行已结束，但有 {len(review_queue)} 张表仍需结构审核；"
                    "「抓取成功」不等于「已认证可合表」。"
                )
                candidate_map = {row["capture_id"]: row for row in review_queue}
                selected_ids = st_obj.multiselect(
                    "选择要送入逻辑资产工作区的待审核 Capture",
                    list(candidate_map),
                    default=list(candidate_map),
                    format_func=lambda cid: (
                        f"{candidate_map[cid].get('company_id') or '未知公司'}｜"
                        f"{candidate_map[cid].get('report_year') or ''}｜"
                        f"{candidate_map[cid].get('member_table_id') or ''}"
                    ),
                    key=f"{key_prefix}_review_selection",
                )
                display_cols = [
                    "company_id", "report_year", "member_table_id",
                    "capture_quality", "quality_blockers",
                ]
                st_obj.dataframe(
                    pd.DataFrame([candidate_map[x] for x in selected_ids])[
                        [c for c in display_cols if c in pd.DataFrame([candidate_map[x] for x in selected_ids]).columns]
                    ],
                    use_container_width=True,
                    hide_index=True,
                )
                if st_obj.button(
                    "审核所选 Capture（进入逻辑资产工作区）",
                    type="primary",
                    disabled=not selected_ids,
                    key=f"{key_prefix}_open_review",
                ):
                    queue = [candidate_map[x] for x in selected_ids]
                    first = queue[0]
                    st_obj.session_state["asset_workspace_review_queue"] = queue
                    st_obj.session_state.pop("selected_logical_asset_id", None)
                    st_obj.session_state.pop("selected_capture_version_id", None)
                    st_obj.session_state.pop("asset_workspace_review_queue_capture", None)
                    st_obj.session_state["inspection_route"] = {
                        "logical_asset_id": first["logical_asset_id"],
                        "capture_version_id": first["capture_id"],
                        "table_block_id": "",
                        "initial_tab": "审核",
                        "return_route": "整表批量工作台",
                        "review_queue_item_id": "",
                    }
                    st_obj.session_state["_pending_main_page"] = "逻辑资产工作区"
                    st_obj.rerun()
            else:
                st_obj.success("本批次全部 Capture 已达到可用状态，无待审核表。")
                if st_obj.button("进入合表", type="primary", key=f"{key_prefix}_go_merge"):
                    st_obj.session_state["merge_research_batch_id"] = research_batch_id
                    st_obj.session_state["_pending_main_page"] = "合表"
                    st_obj.rerun()

        # ---- retry failed ----
        failed = svc.failed_batch_ids(batch_ids)
        if failed:
            retry_batch = st_obj.selectbox(
                "选择需重试的批次",
                failed,
                key=f"{key_prefix}_retry_select",
            )
            if st_obj.button("重试该批失败作业", key=f"{key_prefix}_retry_btn"):
                retries = svc.retry_failed(batch_id=retry_batch, max_workers=3)
                st_obj.success(f"已创建 {len(retries)} 个重试作业；请刷新进度。")

    state = {
        "executed": executed,
        "batch_ids": batch_ids,
        "research_batch_id": research_batch_id,
    }
    return state
