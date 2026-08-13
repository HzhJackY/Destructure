"""Unified Stage B certified-child capture execution panel.

Both the strict-child-mapping flow and the explicit-note-target compat flow
render through this single component.  It provides:

- Fixed primary-table selection plus optional certified supplementary tables
- Real-time batch progress display (QUEUED / RUNNING / SUCCESS / FAILED)
- Retry controls for failed batches
- Completion redirect to the Logical Asset Workspace with a filtered review queue
"""
from __future__ import annotations

from typing import Any

import pandas as pd
import streamlit as st

from capture_models import CAPTURE_SCOPE_CONTRACT_VERSION, CaptureScopePolicy
from presentation_labels import CLASSIFICATION_LABELS


_CAPTURE_SCOPE_HELP = {
    CaptureScopePolicy.PRIMARY_ONLY.value:
        "抓取主逻辑表及其全部已认证物理片段。",
    CaptureScopePolicy.SELECTED_NOTE_TABLES.value:
        "抓取主逻辑表及勾选的补充逻辑表；每张逻辑表自动包含其全部已认证片段。",
}

_PRIMARY_LABEL = CLASSIFICATION_LABELS["PRIMARY_TABLE"]
_SUPPLEMENTARY_LABEL = CLASSIFICATION_LABELS["SUPPLEMENTARY_TABLE"]


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
    svc = backend.child_capture_execution_service
    base_session_key = svc.execution_session_key(
        display_name=display_name,
        research_definition=research_definition,
        scope=scope,
    )
    active_session_state_key = f"{key_prefix}_active_session_key"
    session_key = str(
        st_obj.session_state.get(active_session_state_key)
        or svc.latest_execution_session_key(base_session_key)
        or base_session_key
    )
    state = svc.restore_execution(session_key)
    if certified_links or plans:
        entry_origin = (
            "UNIFIED" if certified_links and plans
            else "STRICT" if certified_links else "COMPAT"
        )
        state = svc.preview_capture_plans(
            display_name=display_name,
            certified_links=certified_links,
            source_pdf_map=source_pdf_map,
            plans=plans,
            research_definition=research_definition,
            scope=scope,
            session_key=session_key,
            entry_origin=entry_origin,
        )
        session_key = str(state.get("session_key") or session_key)
        st_obj.session_state[active_session_state_key] = session_key
    widget_prefix = f"{key_prefix}_{session_key[-12:]}"
    persisted_plans = list(state.get("plans") or [])
    executed = bool(state.get("executed"))
    batch_ids = list(state.get("batch_ids") or [])
    research_batch_id = str(state.get("research_batch_id") or "")
    can_execute = bool(persisted_plans)
    persisted_scope = dict(state.get("capture_scope") or {})
    persisted_contract_version = int(
        persisted_scope.get("capture_scope_contract_version") or 1
    )
    persisted_policy = str(
        persisted_scope.get("capture_scope_policy")
        or CaptureScopePolicy.PRIMARY_ONLY.value
    )
    selection_disabled = False
    logical_targets: dict[str,dict[str,Any]] = {}
    for plan in persisted_plans:
        for item in plan.get("items") or []:
            if item.get("member_table_role") != "NOTE_DETAIL":
                continue
            target = dict(item.get("certified_note_target") or {})
            if str(target.get("status") or "") != "CERTIFIED_NOTE_TARGET":
                continue
            classification = str(
                target.get("table_classification") or ""
            ).upper()
            if classification not in {"PRIMARY_TABLE","SUPPLEMENTARY_TABLE"}:
                continue
            if persisted_contract_version == CAPTURE_SCOPE_CONTRACT_VERSION and (
                str(target.get("segment_manifest_status") or "").upper()
                != "CERTIFIED_SEGMENT_MANIFEST"
                or not target.get("certified_segments")
            ):
                continue
            if (
                classification == "SUPPLEMENTARY_TABLE"
                and str(
                    target.get("note_table_inventory_status") or ""
                ).upper() != "COMPLETE"
            ):
                continue
            logical_table_id = str(
                target.get("logical_table_id")
                or target.get("member_table_id")
                or ""
            ).strip()
            if not logical_table_id:
                continue
            logical_targets.setdefault(logical_table_id,{
                "logical_table_id":logical_table_id,
                "classification":classification,
                "title":str(
                    target.get("target_heading")
                    or item.get("member_table")
                    or logical_table_id
                ),
                "segment_count":len(target.get("certified_segments") or []),
            })
    can_execute = bool(
        can_execute
        and any(
            target["classification"] == "PRIMARY_TABLE"
            for target in logical_targets.values()
        )
    )
    persisted_logical_ids = set(
        persisted_scope.get("selected_logical_table_ids") or []
    )
    if (
        persisted_contract_version == 1
        and persisted_policy == CaptureScopePolicy.ALL_NOTE_TABLES.value
    ):
        persisted_logical_ids = {
            logical_table_id
            for logical_table_id,target in logical_targets.items()
            if target["classification"] == "SUPPLEMENTARY_TABLE"
        }

    st_obj.markdown("#### 抓取逻辑表")
    for logical_table_id,target in logical_targets.items():
        if target["classification"] != "PRIMARY_TABLE":
            continue
        st_obj.checkbox(
            f"{_PRIMARY_LABEL}｜{target['title']}｜{target['segment_count']} 个认证片段",
            value=True,
            disabled=True,
            key=f"{widget_prefix}_primary_{logical_table_id}",
        )
    selected_logical_table_ids: list[str] = []
    for logical_table_id,target in logical_targets.items():
        if target["classification"] != "SUPPLEMENTARY_TABLE":
            continue
        selected = st_obj.checkbox(
            f"{_SUPPLEMENTARY_LABEL}｜{target['title']}｜{target['segment_count']} 个认证片段",
            value=logical_table_id in persisted_logical_ids,
            disabled=selection_disabled,
            key=f"{widget_prefix}_supplementary_{logical_table_id}",
        )
        if selected:
            selected_logical_table_ids.append(logical_table_id)
    selected_policy = (
        CaptureScopePolicy.SELECTED_NOTE_TABLES.value
        if selected_logical_table_ids
        else CaptureScopePolicy.PRIMARY_ONLY.value
    )
    st_obj.caption(_CAPTURE_SCOPE_HELP[selected_policy])
    if persisted_contract_version == 1 and selection_disabled:
        st_obj.warning(
            "该会话按历史 scope v1 重放，已冻结原物理片段选择；"
            "不会静默改写为 logical-table v2。"
        )

    # Capture Plan is explicit and comes back from the database for both
    # strict and compat entry adapters.
    st_obj.markdown("#### Capture Plan（数据库真源）")
    if persisted_plans:
        st_obj.caption(
            f"执行会话 {session_key}｜"
            f"{len(persisted_plans)} 份已持久化计划｜"
            f"统一回调 {state['callback_key']}"
        )
        for plan in persisted_plans:
            details = [
                {
                    "成员":item.get("member_table"),
                    "角色":item.get("member_table_role"),
                    "逻辑表ID":(
                        item.get("certified_note_target") or {}
                    ).get("logical_table_id"),
                    "逻辑表分类":(
                        item.get("certified_note_target") or {}
                    ).get("table_classification"),
                    "认证片段数":len((
                        item.get("certified_note_target") or {}
                    ).get("certified_segments") or []),
                    "附注":item.get("note_reference"),
                    "认证目标页":item.get("confirmed_note_pdf_page_index"),
                    "状态":item.get("status"),
                }
                for item in plan.get("items") or []
                if item.get("member_table_role")=="NOTE_DETAIL"
            ]
            with st_obj.expander(
                f"计划 {plan['plan_id']}｜{plan.get('table_family') or ''}",
                expanded=False,
            ):
                if details:
                    st_obj.dataframe(
                        pd.DataFrame(details),
                        use_container_width=True,
                        hide_index=True,
                    )
    else:
        st_obj.info("尚无已认证 Capture Plan；未认证目标不会进入执行。")

    # ---- execute button ----
    all_submitted = False
    if st_obj.button(
        "确认逻辑表并抓取",
        type="primary",
        disabled=not can_execute or all_submitted,
        key=f"{widget_prefix}_execute_btn",
    ):
        # The same certified inventory/plan shown in the read-only preview must
        # be forwarded to the execution service so an explicit first-time
        # submission atomically persists plans + session + scope (the offline
        # pipeline contract).  Restored sessions still submit by session key.
        result = backend.child_capture_execution_service.create_execution_batch(
            display_name=display_name,
            certified_links=certified_links,
            source_pdf_map=source_pdf_map,
            plans=plans,
            research_definition=research_definition,
            scope=scope,
            session_key=session_key,
            entry_origin=str(state.get("entry_origin") or "UNIFIED"),
            capture_scope_contract_version=CAPTURE_SCOPE_CONTRACT_VERSION,
            capture_scope_policy=selected_policy,
            selected_logical_table_ids=selected_logical_table_ids,
            selected_block_roles=[],
            selected_block_ids=[],
        )
        st_obj.session_state[active_session_state_key] = str(
            result.get("session_key") or session_key
        )
        st_obj.success(
            f"研究批次 {result.get('research_batch_id') or '未新建（幂等恢复）'} "
            f"已处理：{result['job_count']} 个认证子表抓取作业。"
        )
        if result.get("blocked_count"):
            st_obj.warning(
                f"{result['blocked_count']} 个无确认目标的项目保留 REVIEW_REQUIRED，未自动抓取。"
            )
        st_obj.rerun()

    # ---- progress display ----
    if executed and batch_ids:
        st_obj.markdown("#### 本次抓取作业监控")
        st_obj.caption(
            "进度来自持久 Job Registry；刷新页面或重启应用后可继续监控。"
        )
        monitor_rows = list(state.get("progress") or svc.monitor_all(batch_ids))

        if monitor_rows:
            st_obj.dataframe(
                pd.DataFrame(monitor_rows),
                use_container_width=True,
                hide_index=True,
            )

        if st_obj.button("刷新进度", key=f"{widget_prefix}_refresh"):
            st_obj.rerun()

        all_done = bool(state.get("all_terminal"))

        # ---- completion redirect: READY and REVIEW_REQUIRED always enter the
        # same research-batch-filtered Logical Asset Workspace. ----
        if research_batch_id and all_done:
            review_queue = list(state.get("review_queue") or [])

            if review_queue:
                st_obj.warning(
                    f"作业执行已结束，但有 {len(review_queue)} 张表仍需结构审核；"
                    "「抓取成功」不等于「已认证可合表」。"
                )
                display_cols = [
                    "company_id", "report_year", "member_table_id",
                    "capture_quality", "quality_blockers",
                ]
                review_frame = pd.DataFrame(review_queue)
                st_obj.dataframe(
                    review_frame[
                        [c for c in display_cols if c in review_frame.columns]
                    ],
                    use_container_width=True,
                    hide_index=True,
                )
            else:
                st_obj.success("本批次全部 Capture 已达到可用状态，无待审核表。")
            if st_obj.button(
                "进入统一逻辑资产工作区",
                type="primary",
                key=f"{widget_prefix}_open_workspace",
            ):
                st_obj.session_state["asset_workspace_review_queue"] = review_queue
                st_obj.session_state[
                    "asset_workspace_filter"
                ] = dict(state["workspace_filter"])
                st_obj.session_state[
                    "asset_workspace_stage_b_session_key"
                ] = session_key
                st_obj.session_state.pop("selected_logical_asset_id",None)
                st_obj.session_state.pop("selected_capture_version_id",None)
                st_obj.session_state.pop(
                    "asset_workspace_review_queue_capture",None
                )
                if review_queue:
                    first = review_queue[0]
                    st_obj.session_state["inspection_route"] = {
                        "logical_asset_id":first["logical_asset_id"],
                        "capture_version_id":first["capture_id"],
                        "table_block_id":"",
                        "initial_tab":"审核",
                        "return_route":"整表批量工作台",
                        "review_queue_item_id":first.get(
                            "review_item_id",""
                        ),
                    }
                else:
                    st_obj.session_state.pop("inspection_route",None)
                st_obj.session_state["_pending_main_page"] = state[
                    "workspace_route"
                ]
                st_obj.rerun()

        # ---- retry failed ----
        failed = svc.failed_batch_ids(batch_ids)
        if failed:
            retry_batch = st_obj.selectbox(
                "选择需重试的批次",
                failed,
                key=f"{widget_prefix}_retry_select",
            )
            if st_obj.button(
                "重试该批失败作业",key=f"{widget_prefix}_retry_btn"
            ):
                retries = svc.retry_failed(batch_id=retry_batch, max_workers=3)
                st_obj.success(f"已创建 {len(retries)} 个重试作业；请刷新进度。")

    return state
