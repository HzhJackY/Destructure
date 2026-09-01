from __future__ import annotations

import json


READONLY={"SUPERSEDED","INVALIDATED","TRASHED","ARCHIVED"}
TASK_TAB={
    "SOURCE_IDENTITY_REVIEW":"概览",
    # 边界的可裁决控件（最后有效行）在附注容器与表块，不是只读 PDF 预览。
    "PDF_BOUNDARY_REVIEW":"附注容器与表块",
    "TABLE_BLOCK_REVIEW":"附注容器与表块",
    "HEADER_TOPOLOGY_REVIEW":"表头拓扑",
    "ROW_STRUCTURE_REVIEW":"行结构",
    "FINAL_DATA_COLUMN_REVIEW":"最终数据复核",
    "UNIT_SCOPE_PERIOD_REVIEW":"Canonical 数据",
    "RECONCILIATION_REVIEW":"勾稽与质量",
    "FINAL_CERTIFICATION":"审核",
}
TASK_LABEL={
    "SOURCE_IDENTITY_REVIEW":"来源身份",
    "PDF_BOUNDARY_REVIEW":"PDF 边界",
    "TABLE_BLOCK_REVIEW":"表块分割",
    "HEADER_TOPOLOGY_REVIEW":"表头拓扑",
    "ROW_STRUCTURE_REVIEW":"行结构",
    "FINAL_DATA_COLUMN_REVIEW":"最终数据列",
    "UNIT_SCOPE_PERIOD_REVIEW":"单位、口径与期间",
    "RECONCILIATION_REVIEW":"勾稽关系",
    "FINAL_CERTIFICATION":"最终认证",
}


def _go_tab(st,logical_asset_id:str,tab:str)->None:
    st.session_state[f"inspection_tab_{logical_asset_id}"]=tab
    st.session_state["selected_inspection_tab"]=tab


def render_review_action_panel(st, backend, detail: dict) -> None:
    capture_id=str(detail["capture_id"])
    summary=backend.review_task_service.summary(capture_id)
    readonly=str(detail.get("asset_status")) in READONLY
    certified=str(detail.get("asset_status"))=="CERTIFIED_ACTIVE"
    st.subheader("审核总览")
    st.progress(summary["completed"]/summary["total"] if summary["total"] else 1.0)
    st.caption(f"审核进度：{summary['completed']} / {summary['total']} 已完成")
    task_by_type={row["task_type"]:row for row in summary["tasks"]}
    checklist=[]
    for task_type in TASK_LABEL:
        task=task_by_type.get(task_type,{})
        checklist.append({
            "审核任务":TASK_LABEL[task_type],
            "状态":task.get("status","未生成"),
            "必需":"是" if task.get("required") else "否",
            "严重度":task.get("severity","-"),
            "阻断合表":"是" if task.get("blocking") else "否",
        })
    st.dataframe(checklist,use_container_width=True,hide_index=True)

    # 批量引导入口与数据资产管理必须进入同一审核面板。此前首屏只有
    # 状态表，而具体证据/处理页和裁决控件位于页面下方，导致用户误以为
    # 无法审核。这里把下一项必需任务提升到清单后，先引导至其专属证据页。
    quick_tasks=[
        x for x in summary["tasks"]
        if x["task_type"]!="FINAL_CERTIFICATION"
        and x["status"] in {"PENDING","IN_PROGRESS","UNRESOLVED"}
        and x.get("required")
    ]
    if quick_tasks:
        quick_map={
            f"{TASK_LABEL.get(x['task_type'],x['task_type'])}｜{x['status']}":x
            for x in quick_tasks
        }
        st.markdown("#### 下一项必需审核")
        quick_label=st.selectbox(
            "选择要处理的审核任务",list(quick_map),
            key=f"quick_review_task_{capture_id}",
        )
        quick_task=quick_map[quick_label]
        st.info(
            "先查看该任务的 PDF 证据或结构编辑器，再回到“审核”作出裁决；"
            "不会因打开此页而自动确认机器结果。"
        )
        st.button(
            "查看证据并处理此任务",
            type="primary",
            key=f"quick_review_goto_{capture_id}",
            on_click=_go_tab,
            args=(st,str(detail["logical_asset_id"]),TASK_TAB.get(quick_task["task_type"],"审核")),
        )

    if summary["issues"]:
        st.markdown("#### 待处理问题")
    for issue in summary["issues"]:
        severity=str(issue["severity"])
        with st.container(border=True):
            st.markdown(f"**{severity}｜{issue['human_title']}**")
            st.write(issue["human_description"])
            st.caption(
                f"影响：{issue.get('affected_object_type') or 'Capture'} / "
                f"{issue.get('affected_object_id') or capture_id}；"
                f"阻断合表：{'是' if issue.get('blocking') else '否'}"
            )
            st.info("建议："+issue["recommended_action"])
            with st.expander("系统证据",expanded=False):
                st.json(issue.get("evidence") or {})
            st.button(
                "前往处理",
                key=f"goto_issue_{issue['review_issue_id']}",
                on_click=_go_tab,
                args=(st,str(detail["logical_asset_id"]),TASK_TAB.get(issue["review_task_type"],"审核")),
            )

    if readonly:
        st.warning("历史、失效或归档版本只读，不能执行审核。")
    elif certified:
        st.info("该版本已认证；需要修改时必须创建新的 Capture Version。")

    st.markdown("#### 任务裁决")
    actionable=[x for x in summary["tasks"] if x["task_type"]!="FINAL_CERTIFICATION" and x["status"] in {"PENDING","IN_PROGRESS","UNRESOLVED"}]
    if actionable:
        option_map={f"{TASK_LABEL.get(x['task_type'],x['task_type'])}｜{x['status']}":x for x in actionable}
        label=st.selectbox("选择审核任务",list(option_map),key=f"review_task_select_{capture_id}")
        task=option_map[label]
        reason=st.text_area("人工判断依据",key=f"review_task_reason_{capture_id}")
        cols=st.columns(3)
        if cols[0].button("确认此任务",disabled=readonly or certified,key=f"confirm_task_{capture_id}"):
            backend.review_service.decide_task(
                capture_id=capture_id,task_type=task["task_type"],decision="CONFIRMED",
                reason=reason,evidence={"source":"CAPTURE_INSPECTION_PANEL"},
            )
            st.rerun()
        if cols[1].button("覆盖后解决",disabled=readonly or certified or not reason.strip(),key=f"override_task_{capture_id}"):
            backend.review_service.decide_task(
                capture_id=capture_id,task_type=task["task_type"],decision="OVERRIDDEN",
                reason=reason,evidence={"source":"CAPTURE_INSPECTION_PANEL"},
            )
            st.rerun()
        if cols[2].button("标记尚未解决",disabled=readonly or certified,key=f"unresolved_task_{capture_id}"):
            backend.review_service.decide_task(
                capture_id=capture_id,task_type=task["task_type"],decision="UNRESOLVED",
                reason=reason,evidence={"source":"CAPTURE_INSPECTION_PANEL"},
            )
            st.rerun()
    else:
        st.success("除最终认证外，没有未完成的必需审核任务。")

    st.markdown("#### 最终认证")
    blocking_names=[TASK_LABEL.get(x["task_type"],x["task_type"]) for x in summary["blocking_tasks"]]
    if blocking_names:
        st.error("最终确认已锁定；请先完成："+"、".join(blocking_names))
    final_reason=st.text_area("最终认证说明",key=f"final_review_reason_{capture_id}")
    structured=st.columns(3)
    scope=structured[0].selectbox(
        "确认口径",["保持机器结果","CONSOLIDATED","PARENT_COMPANY","COMPANY","OTHER"],
        key=f"structured_scope_{capture_id}",
    )
    unit=structured[1].selectbox(
        "确认单位",["保持机器结果","CNY","CNY_THOUSAND","CNY_MILLION"],
        key=f"structured_unit_{capture_id}",
    )
    restated=structured[2].selectbox(
        "重述状态",["保持机器结果","未重述","已重述"],
        key=f"structured_restated_{capture_id}",
    )
    structured_override={"statement_scope":scope,"currency_unit":unit,"restated":restated}
    with st.expander("高级模式：原始 JSON Override",expanded=False):
        raw_override=st.text_area("仅供开发者/审计使用",key=f"raw_override_{capture_id}")
        if raw_override.strip():
            try:structured_override.update(json.loads(raw_override))
            except json.JSONDecodeError:st.error("高级 Override 不是有效 JSON。")
    cols=st.columns(4)
    locked=readonly or certified or not summary["can_final_confirm"]
    if cols[0].button("最终确认",disabled=locked,key=f"final_confirm_{capture_id}"):
        backend.review_service.adjudicate_capture(
            capture_id=capture_id,action="CONFIRMED",reason=final_reason,
            override=structured_override,
        )
        st.rerun()
    if cols[1].button("覆盖后确认",disabled=locked or not final_reason.strip(),key=f"final_override_{capture_id}"):
        backend.review_service.adjudicate_capture(
            capture_id=capture_id,action="CONFIRMED_OVERRIDE",reason=final_reason,
            override=structured_override,
        )
        st.rerun()
    if cols[2].button("拒绝该版本",disabled=readonly or certified,key=f"final_reject_{capture_id}"):
        backend.review_service.adjudicate_capture(capture_id=capture_id,action="REJECTED",reason=final_reason)
        st.rerun()
    if cols[3].button("标记为尚未解决",disabled=readonly or certified,key=f"final_unresolved_{capture_id}"):
        backend.review_service.adjudicate_capture(capture_id=capture_id,action="UNRESOLVED",reason=final_reason)
        st.rerun()

    with st.expander("版本操作与审核历史",expanded=False):
        more=st.columns(4)
        if more[0].button("重新抓取",disabled=readonly,key=f"rerun_{capture_id}"):
            backend.capture_service.rerun(detail["logical_asset_id"],requested_by="INSPECTION_PANEL")
            st.rerun()
        if more[1].button("使该版本失效",disabled=readonly or certified,key=f"invalidate_{capture_id}"):
            backend.review_service.adjudicate_capture(
                capture_id=capture_id,action="REJECTED",reason=final_reason or "INVALIDATED_FROM_INSPECTION",
            )
            st.rerun()
        if more[2].button("归档",disabled=str(detail.get("asset_status"))=="ARCHIVED",key=f"archive_version_{capture_id}"):
            backend.archive_service.archive_versions([capture_id],reason="CAPTURE_INSPECTION_PANEL")
            st.rerun()
        if more[3].button("恢复",disabled=str(detail.get("asset_status"))!="ARCHIVED",key=f"restore_version_{capture_id}"):
            backend.archive_service.restore_versions([capture_id],reason="CAPTURE_INSPECTION_PANEL")
            st.rerun()
        history=backend.capture_version_service.review_history(capture_id)
        if history:st.dataframe(history,use_container_width=True,hide_index=True)
