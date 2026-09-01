"""The only production implementation of single Capture inspection."""
from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from components.compound_container_panel import render_compound_container_panel
from components.pdf_evidence_panel import render_pdf_evidence_panel
from components.review_action_panel import render_review_action_panel
from components.child_mapping_review import render_child_mapping_review
from financial_structure_resolver import project_certified_row_hierarchy


TABS=["概览","子表映射","PDF 证据","附注容器与表块","表头拓扑","行结构","最终数据复核","Canonical 数据","勾稽与质量","审核","版本对比","使用情况"]

STATUS_LABEL={
    "REVIEW_REQUIRED":"需要复核","READY":"就绪","PENDING":"待处理",
    "ACTIVE":"活动","CERTIFIED_ACTIVE":"已认证","COMPLETED":"已完成",
    "REGISTERED":"已注册","SUPERSEDED":"已被替代","INVALIDATED":"已失效",
    "UNKNOWN":"未知",
}


def _status(value):
    raw=str(value or "UNKNOWN")
    return f"{STATUS_LABEL.get(raw,raw)}（{raw}）"


def _load_result(run_path: str) -> dict:
    path=Path(str(run_path or ""))/"table_capture_result.json"
    if not path.is_file(): return {}
    try: return json.loads(path.read_text(encoding="utf-8"))
    except (OSError,json.JSONDecodeError): return {}


def _load_frame(run_path: str, names: list[str]) -> pd.DataFrame:
    root=Path(str(run_path or ""))
    for name in names:
        path=root/name
        if path.is_file():
            try:
                return pd.read_parquet(path) if path.suffix==".parquet" else pd.read_csv(path)
            except Exception:
                continue
    return pd.DataFrame()


def _certified_row_structure_frame(rows: list[dict]) -> pd.DataFrame:
    """Return the UI projection of the certified source-row graph."""
    frame = pd.DataFrame(rows)
    if frame.empty:
        return frame
    return project_certified_row_hierarchy(
        frame,
        allow_legacy_compatibility=True,
    )


def _create_revision(st,backend,detail,revision_type,payload,block_id=None):
    out=backend.capture_version_service.create_structure_revision(
        capture_id=detail["capture_id"],revision_type=revision_type,
        payload=payload,table_block_id=block_id,
    )
    st.session_state["pending_inspection_route"]={
        "logical_asset_id":out["logical_asset_id"],
        "capture_version_id":out["new_capture_id"],
        "table_block_id":str(block_id or ""),
        "initial_tab":"审核",
        "return_route":"逻辑资产工作区",
        "review_queue_item_id":"",
    }
    st.success(f"已生成不可变新版本：{out['new_capture_id']}")
    st.rerun()


def render_capture_inspection_panel(
    st, backend, *, logical_asset_id: str, capture_version_id: str,
    initial_tab: str="概览", readonly_mode: bool=False,
) -> None:
    detail=backend.capture_version_service.detail(capture_version_id)
    if not detail or str(detail["logical_asset_id"])!=str(logical_asset_id):
        st.error("选中的 Capture Version 不属于当前 Logical Asset，已停止审核。")
        return
    result=_load_result(detail.get("run_path"))
    bundle=backend.capture_version_service.bundle(capture_version_id)
    versions=backend.capture_version_service.versions(logical_asset_id)
    key=f"inspection_tab_{logical_asset_id}"
    if key not in st.session_state:
        st.session_state[key]=initial_tab if initial_tab in TABS else "概览"
    tab=st.radio("检查区域",TABS,horizontal=True,key=key)
    st.session_state["selected_inspection_tab"]=tab

    if tab=="概览":
        title="｜".join(filter(None,[
            str(detail.get("company_id") or "未知公司"),
            f"{detail.get('report_year')}年报" if detail.get("report_year") else "",
            str(detail.get("member_table_id") or detail.get("table_query") or "未命名表"),
        ]))
        st.subheader(title)
        st.caption(
            f"来源：{detail.get('pdf_name') or '未知 PDF'}；附注 {result.get('note_number') or detail.get('note_number') or '-'}；"
            f"PDF {result.get('start_page','?')}–{result.get('end_page','?')} 页"
        )
        top=st.columns(4)
        top[0].metric("Capture Version",f"v{detail.get('capture_version') or '?'}")
        top[1].metric("质量",_status(detail.get("quality_status")))
        top[2].metric("审核",_status(detail.get("review_status")))
        top[3].metric("生命周期",_status(detail.get("asset_status")))
        identity=[
            {"项目":"研究定义","当前值":detail.get("research_definition_id") or "缺失"},
            {"项目":"定义版本","当前值":detail.get("definition_version") or "缺失"},
            {"项目":"表族","当前值":detail.get("table_family_id") or "缺失"},
            {"项目":"子表","当前值":detail.get("member_table_id") or "缺失"},
            {"项目":"Subtable Role","当前值":detail.get("logical_source_role") or "未标注"},
            {"项目":"Statement Scope","当前值":detail.get("statement_scope") or "UNKNOWN"},
            {"项目":"单位","当前值":result.get("unit") or "未识别"},
            {"项目":"Current","当前值":"是" if detail.get("is_current") else "否"},
        ]
        st.dataframe(identity,use_container_width=True,hide_index=True)
        detected_scope=str((result.get("document_context") or {}).get("statement_scope") or "UNKNOWN").upper()
        if str(detail.get("statement_scope") or "UNKNOWN").upper()=="UNKNOWN" and detected_scope not in {"", "UNKNOWN"}:
            st.info(
                f"文档上下文已识别口径：{detected_scope}（来源 PDF 页 "
                f"{(result.get('document_context') or {}).get('statement_scope_source_page') or '?'}），"
                "但旧 Capture 注册时未写入逻辑资产身份。"
            )
            if st.button("从文档证据回填报表口径", disabled=readonly_mode, key=f"scope_backfill_{capture_version_id}"):
                outcome=backend.capture_version_service.backfill_scope_from_document_context(capture_version_id)
                if outcome.get("updated"):
                    st.success(f"已回填 {outcome['scope']}，来源 PDF 页 {outcome.get('source_page') or '?'}。")
                    st.rerun()
                else:
                    st.warning(f"未回填：{outcome.get('reason')}")
        missing_identity=(
            not detail.get("research_definition_id") or
            not detail.get("definition_version") or
            not detail.get("table_family_id") or
            str(detail.get("statement_scope") or "UNKNOWN").upper()=="UNKNOWN"
        )
        if missing_identity and not readonly_mode:
            with st.expander("修复研究身份（生成新版本）",expanded=True):
                definitions=backend.research_definition_service.definitions()
                definition_options=["暂不关联"]+[f"{x['definition_id']}｜{x['definition_version']}" for x in definitions]
                chosen_definition=st.selectbox("Research Definition / Version",definition_options,key=f"identity_definition_{capture_version_id}")
                families=backend.research_definition_service.families()
                family_options=["暂不关联"]+[str(x["family_id"]) for x in families]
                chosen_family=st.selectbox("Table Family",family_options,key=f"identity_family_{capture_version_id}")
                chosen_scope=st.selectbox("Statement Scope",["CONSOLIDATED","PARENT_COMPANY","COMPANY","OTHER"],key=f"identity_scope_{capture_version_id}")
                chosen_unit=st.selectbox("Currency Unit",["CNY","CNY_THOUSAND","CNY_MILLION"],key=f"identity_unit_{capture_version_id}")
                if st.button("保存身份修复为新 Capture Version",key=f"identity_revision_{capture_version_id}"):
                    definition=next((x for x in definitions if f"{x['definition_id']}｜{x['definition_version']}"==chosen_definition),{})
                    _create_revision(st,backend,detail,"IDENTITY_OVERRIDE",{
                        "research_definition_id":definition.get("definition_id"),
                        "definition_version":definition.get("definition_version"),
                        "table_family_id":None if chosen_family=="暂不关联" else chosen_family,
                        "statement_scope":chosen_scope,"currency_unit":chosen_unit,
                    })
        review_summary=backend.review_task_service.summary(capture_version_id)
        blockers=review_summary["blocking_tasks"]
        review_cols=st.columns(3)
        review_cols[0].metric("待处理问题",len(review_summary["issues"]))
        review_cols[1].metric("高严重度",sum(x["severity"]=="HIGH" for x in review_summary["issues"]))
        review_cols[2].metric("阻断认证任务",len(blockers))
        if blockers:
            st.warning("推荐下一步："+"；".join(filter(None,(x.get("recommended_action") for x in blockers)))[:500])
        else:
            st.success("必需审核任务已完成，可进入“审核”执行最终认证。")
        warnings=result.get("warnings") or []
        if warnings: st.warning("；".join(map(str,warnings)))
        with st.expander("高级信息 / 原始元数据",expanded=False):
            st.json({"detail":detail,"capture_result_metadata":{
                k:v for k,v in result.items() if k not in {"rows"}
            }})

    elif tab=="子表映射":
        render_child_mapping_review(st,backend,detail)

    elif tab=="PDF 证据":
        selected_block=None
        if bundle and st.session_state.get("selected_table_block_id"):
            selected_block=next((x for x in bundle["children"] if x["block_id"]==st.session_state["selected_table_block_id"]),None)
        render_pdf_evidence_panel(st,detail,result,selected_block)

    elif tab=="附注容器与表块":
        st.subheader("Capture 整表边界")
        from capture_library import derive_boundary_status
        stored_boundary_status=str(result.get("boundary_status") or detail.get("boundary_status") or "")
        boundary_status=derive_boundary_status(result)
        st.write(f"当前边界状态：**{_status(boundary_status)}**")
        if boundary_status != stored_boundary_status:
            st.info("已按当前表内结构、勾稽和页末证据重新判定历史边界；原始机器状态与警告仍保留在审计记录中。")
        with st.expander("边界机器证据",expanded=boundary_status=="REVIEW_REQUIRED"):
            st.json(
                (result.get("stats") or {}).get("boundary_evidence")
                or result.get("boundary_evidence")
                or {}
            )
        boundary_rows=list(result.get("rows") or [])
        if boundary_status in {"","REVIEW_REQUIRED","AMBIGUOUS"} and boundary_rows:
            row_options=[int(row.get("row_order") or index+1) for index,row in enumerate(boundary_rows)]
            numeric_rows=[
                int(row.get("row_order") or index+1)
                for index,row in enumerate(boundary_rows)
                if row.get("cells") or row.get("values") or row.get("value_cells")
            ]
            recommended=max(numeric_rows or row_options)
            cutoff=st.selectbox(
                "最后一条有效数据行",
                row_options,index=row_options.index(recommended),
                format_func=lambda order:next(
                    f"row {order}｜{row.get('raw_item') or row.get('row_item_normalized') or row.get('normalized_item') or '[空标签派生行]'}"
                    for row in boundary_rows
                    if int(row.get("row_order") or 0)==order
                ),
                key=f"boundary_cutoff_{capture_version_id}",
            )
            boundary_note=st.text_input(
                "边界确认说明",key=f"boundary_note_{capture_version_id}",
            )
            if st.button(
                "确认最后有效行并重建正式输出",
                disabled=readonly_mode,key=f"confirm_boundary_{capture_version_id}",
            ):
                backend.review_service.apply_boundary(
                    Path(detail["run_path"]),int(cutoff),boundary_note,
                )
                backend.review_service.decide_task(
                    capture_id=capture_version_id,task_type="PDF_BOUNDARY_REVIEW",
                    decision="CONFIRMED",reason=boundary_note,
                    evidence={"last_included_row_order":int(cutoff),"source":"BOUNDARY_REVIEW_PANEL"},
                )
                st.rerun()
        render_compound_container_panel(st,backend,detail,bundle)

    elif tab=="表头拓扑":
        st.subheader("表头拓扑复核")
        render_pdf_evidence_panel(st,detail,result,None)
        stats=result.get("stats") or {}
        selected=stats.get("v69_header_topology") or {}
        alternatives=stats.get("header_arbitration") or []
        columns=result.get("columns") or []
        with st.expander("Header bbox 与机器拓扑证据",expanded=False):
            st.json({
                "header_bbox":stats.get("header_bbox") or result.get("header_bbox"),
                "header_rows":stats.get("header_rows"),
                "merged_cells":stats.get("merged_cells"),
                "selected_topology":selected,
                "quality_warnings":stats.get("header_warnings") or result.get("warnings"),
            })
        if alternatives:
            labels=[f"候选 {i+1}｜得分 {float(x.get('score') or 0):.2f}｜{x.get('method') or x.get('name') or '拓扑'}" for i,x in enumerate(alternatives)]
            selected_label=st.selectbox("选择表头候选",["当前机器拓扑"]+labels,key=f"header_candidate_{capture_version_id}")
            chosen=selected if selected_label=="当前机器拓扑" else alternatives[labels.index(selected_label)]
            with st.expander("候选证据",expanded=False):st.json(chosen)
        table=[]
        for index,column in enumerate(columns):
            row=dict(column) if isinstance(column,dict) else {"raw_header_path":str(column)}
            table.append({
                "column_index":index,"raw_header_path":row.get("raw_header_path") or row.get("header_path") or row.get("label"),
                "data_year":row.get("data_year") or row.get("year"),
                "period_type":row.get("period_type") or "ANNUAL",
                "statement_scope":row.get("statement_scope") or detail.get("statement_scope") or "UNKNOWN",
                "unit":row.get("unit") or result.get("unit"),
                "measure":row.get("measure") or "VALUE",
                "merged_parent":row.get("merged_parent"),
            })
        edited=st.data_editor(pd.DataFrame(table),use_container_width=True,hide_index=True,
                              key=f"header_mapping_editor_{capture_version_id}")
        header_start,header_end=st.columns(2)
        start=header_start.number_input("Header 起始行",min_value=0,value=int(selected.get("header_start") or 0),key=f"header_start_{capture_version_id}")
        end=header_end.number_input("Header 结束行",min_value=0,value=int(selected.get("header_end") or 0),key=f"header_end_{capture_version_id}")
        actions=st.columns(3)
        if actions[0].button("确认当前拓扑",disabled=readonly_mode,key=f"confirm_header_{capture_version_id}"):
            backend.review_service.decide_task(capture_id=capture_version_id,task_type="HEADER_TOPOLOGY_REVIEW",decision="CONFIRMED")
            st.rerun()
        if actions[1].button("保存为新结构版本",disabled=readonly_mode,key=f"header_revision_btn_{capture_version_id}"):
            _create_revision(st,backend,detail,"HEADER_TOPOLOGY_OVERRIDE",{
                "header_start":int(start),"header_end":int(end),
                "columns":edited.to_dict("records"),"selected_candidate":selected_label,
            })
        if actions[2].button("标记未解决",disabled=readonly_mode,key=f"unresolved_header_{capture_version_id}"):
            backend.review_service.decide_task(capture_id=capture_version_id,task_type="HEADER_TOPOLOGY_REVIEW",decision="UNRESOLVED")
            st.rerun()

    elif tab=="行结构":
        rows=result.get("rows") or []
        row_projection=_certified_row_structure_frame(rows)
        display_columns=[column for column in (
            "source_row_id","parent_row_id","hierarchy_parent_label",
            "hierarchy_path","hierarchy_level","hierarchy_status","row_role",
            "raw_item","normalized_item","row_origin","hierarchy_evidence",
            "container_id","table_block_id","classification_axis",
            "derivation_method","label_derivation","derived_from_rows",
        ) if column in row_projection.columns]
        st.dataframe(
            row_projection[display_columns],
            use_container_width=True,
            hide_index=True,
        )
        editable_columns=[column for column in (
            "source_row_id","parent_row_id","hierarchy_path","hierarchy_level",
            "hierarchy_status","row_role","normalized_item",
        ) if column in row_projection.columns]
        editable=row_projection[editable_columns].copy()
        edited_rows=st.data_editor(
            editable,
            use_container_width=True,
            hide_index=True,
            disabled=[column for column in (
                "source_row_id","parent_row_id","hierarchy_path",
                "hierarchy_level","hierarchy_status",
            ) if column in editable.columns],
            key=f"row_editor_{capture_version_id}",
        )
        noise_candidates=[]
        for row in rows:
            if row.get("raw_item") or row.get("row_item_raw"):
                continue
            cells=list(row.get("cells") or [])
            token=" | ".join(str(cell.get("raw") or cell.get("raw_value") or "") for cell in cells).strip()
            noise_candidates.append({
                "row_order":row.get("row_order"),"token":token,
                "bbox":row.get("bbox") or row.get("source_bbox"),
                "role":row.get("row_role") or row.get("row_type"),
            })
        if noise_candidates and not readonly_mode:
            st.markdown("#### 版面噪声人工裁决")
            st.caption("仅适用于无项目标签的页码、脚注编号或版面残留。此操作保留机器原始行，创建新 Capture Version，并只从正式输出/合表中排除该行。")
            choice=st.selectbox(
                "选择无标签疑似噪声行",
                noise_candidates,
                format_func=lambda item: f"row {item['row_order']}｜token={item['token'] or '[空]'}｜机器角色={item['role'] or '未标注'}",
                key=f"layout_noise_row_{capture_version_id}",
            )
            noise_reason=st.text_input(
                "裁决说明（必填）",
                placeholder="例如：07 位于数值栏，系侧页码/脚注残留，不是经济项目。",
                key=f"layout_noise_reason_{capture_version_id}",
            )
            if st.button(
                "标记为版面噪声并生成新 Capture Version",
                disabled=not noise_reason.strip(),
                key=f"layout_noise_revision_{capture_version_id}",
            ):
                _create_revision(st,backend,detail,"ROW_LAYOUT_NOISE_EXCLUSION",{
                    "row_noise_decisions":[{
                        "row_order":choice["row_order"],"reason":noise_reason.strip(),
                        "machine_token":choice["token"],"machine_bbox":choice["bbox"],
                    }]
                })
        row_actions=st.columns(3)
        if row_actions[0].button("确认当前行结构",disabled=readonly_mode,key=f"confirm_rows_{capture_version_id}"):
            backend.review_service.decide_task(capture_id=capture_version_id,task_type="ROW_STRUCTURE_REVIEW",decision="CONFIRMED")
            st.rerun()
        if row_actions[1].button("保存为新结构版本",disabled=readonly_mode,key=f"row_revision_btn_{capture_version_id}"):
            _create_revision(st,backend,detail,"ROW_STRUCTURE_OVERRIDE",{"rows":edited_rows.to_dict("records")})
        if row_actions[2].button("标记未解决",disabled=readonly_mode,key=f"unresolved_rows_{capture_version_id}"):
            backend.review_service.decide_task(capture_id=capture_version_id,task_type="ROW_STRUCTURE_REVIEW",decision="UNRESOLVED")
            st.rerun()

    elif tab=="最终数据复核":
        st.subheader("最终数据列复核")
        final_summary=backend.review_task_service.summary(capture_version_id)
        final=final_summary["final_data_review"]
        final_task=next(
            (task for task in final_summary["tasks"]
             if task["task_type"]=="FINAL_DATA_COLUMN_REVIEW"),
            {},
        )
        final_task_status=str(final_task.get("status") or "PENDING")
        last=final["last_column_check"]
        renderer=st.success if last["status"]=="PASS" else st.info if last["status"]=="NOT_APPLICABLE" else st.error
        renderer(
            f"最后一列专项检查：{last['status']}；"
            f"{last['rows_with_last_token']}/{last['row_count']} 个适用行具有末列 token；"
            f"排除派生合计行 {last.get('excluded_derived_rows',0)} 个；"
            f"排除无数值行 {last.get('excluded_non_value_rows',0)} 个"
        )
        st.markdown("**Header → Canonical Column Mapping**")
        st.dataframe(final["column_mappings"],use_container_width=True,hide_index=True)
        st.markdown("**逐行观察值与来源**")
        st.dataframe(final["observations"],use_container_width=True,hide_index=True)
        if final["issues"]:
            st.error("检测到阻断问题："+"、".join(x["reason_code"] for x in final["issues"]))
            if final_task_status in {"CONFIRMED","OVERRIDDEN"}:
                st.success(f"机器警告已由人工裁决解决：{final_task_status}")
        review_reason=st.text_input(
            "人工裁决说明",
            help="机器仍报告警告时，必须说明核对了哪些 PDF 列、末列 token 或来源证据。",
            key=f"final_data_review_reason_{capture_version_id}",
        )
        final_actions=st.columns(3)
        if final_actions[0].button(
            "确认无异常",disabled=readonly_mode or bool(final["issues"]),
            key=f"confirm_final_data_{capture_version_id}",
        ):
            backend.review_service.decide_task(capture_id=capture_version_id,task_type="FINAL_DATA_COLUMN_REVIEW",decision="CONFIRMED")
            st.rerun()
        if final_actions[1].button(
            "人工覆盖确认警告",
            disabled=readonly_mode or not bool(final["issues"]) or not review_reason.strip(),
            key=f"override_final_data_{capture_version_id}",
        ):
            backend.review_service.decide_task(
                capture_id=capture_version_id,
                task_type="FINAL_DATA_COLUMN_REVIEW",decision="OVERRIDDEN",
                reason=review_reason,
                evidence={
                    "source":"FINAL_DATA_REVIEW_PANEL",
                    "machine_issues":[issue["reason_code"] for issue in final["issues"]],
                    "last_column_check":last,
                },
            )
            st.rerun()
        if final_actions[2].button("标记未解决",disabled=readonly_mode,key=f"unresolved_final_data_{capture_version_id}"):
            backend.review_service.decide_task(capture_id=capture_version_id,task_type="FINAL_DATA_COLUMN_REVIEW",decision="UNRESOLVED")
            st.rerun()

    elif tab=="Canonical 数据":
        long_df=_load_frame(detail.get("run_path"),["canonical_research_long.parquet","canonical_research_long.csv","table_raw_long.csv"])
        if long_df.empty: st.info("该版本没有可显示的 Canonical Long。")
        else: st.dataframe(long_df,use_container_width=True,hide_index=True)
        wide=_load_frame(detail.get("run_path"),["research_wide.parquet","research_wide.csv","table_raw_wide.csv"])
        if not wide.empty:
            with st.expander("Wide Preview"):st.dataframe(wide,use_container_width=True,hide_index=True)

    elif tab=="勾稽与质量":
        st.json({
            "intra_table":(result.get("stats") or {}).get("v69_reconciliation"),
            "boundary":(result.get("stats") or {}).get("boundary_evidence"),
            "quality_status":detail.get("quality_status"),
            "merge_eligible":any(x.get("capture_id")==capture_version_id for x in backend.merge_eligibility_service.eligible_assets()),
        })
        if bundle:
            st.subheader("跨子表 / Bundle")
            st.json({"bundle_status":bundle["bundle"].get("status"),
                     "children":[{"capture_id":x.get("capture_id"),"reconciliation":json.loads(x.get("reconciliation_json") or "{}")} for x in bundle["children"]]})

    elif tab=="审核":
        render_review_action_panel(st,backend,detail)

    elif tab=="版本对比":
        st.dataframe(versions,use_container_width=True,hide_index=True)
        compare=st.selectbox("比较版本",[x["capture_id"] for x in versions if x["capture_id"]!=capture_version_id],key=f"compare_{capture_version_id}") if len(versions)>1 else None
        if compare:
            other=backend.capture_version_service.detail(compare)
            other_result=_load_result(other.get("run_path"))
            st.json({
                "当前":{"capture_id":capture_version_id,"status":detail.get("asset_status"),"rows":len(result.get("rows") or []),"unit":result.get("unit"),"columns":result.get("columns")},
                "对比":{"capture_id":compare,"status":other.get("asset_status"),"rows":len(other_result.get("rows") or []),"unit":other_result.get("unit"),"columns":other_result.get("columns")},
            })

    elif tab=="使用情况":
        usage=backend.capture_version_service.usage(capture_version_id)
        st.json(usage)
        if any(usage.values()):
            st.warning("Invalidate / Archive / Supersede 前请确认这些下游资产的 stale 影响。")
