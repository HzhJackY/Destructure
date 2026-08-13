"""Human child-table mapping review inside the unified workspace."""
from __future__ import annotations

from typing import Any

import pandas as pd

from presentation_labels import (
    CLASSIFICATION_LABELS,
    LOGICAL_TABLE_ROLE_OPTIONS,
    classification_key,
    classification_label,
)


def _amount_text(row: dict[str, Any]) -> str:
    """Render persisted source amounts without treating an empty list as missing evidence."""
    value = row.get("statement_amount_normalized") or row.get("statement_amount_raw")
    if value in (None, "", "[]"):
        return "缺失（阻断认证）"
    if isinstance(value, str):
        return value
    return "；".join(str(item) for item in value) if isinstance(value, list) else str(value)


def render_inventory_resolution_case(
    st,backend,case:dict[str,Any],*,key_prefix:str,
)->dict[str,Any]|None:
    snapshot=dict(case.get("machine_snapshot") or {})
    logical_tables=list(snapshot.get("logical_tables") or [])
    if not logical_tables:
        st.error("该未决 case 没有已持久化 logical candidate；需修复自动发现，不能人工补页。")
        return None
    st.caption(
        f"Case {case['resolution_case_id']}｜Candidate {case['candidate_id']}｜"
        f"机器证据 {case['machine_snapshot_sha256'][:12]}"
    )
    st.dataframe(pd.DataFrame([
        {
            "logical_candidate_id":logical.get("logical_table_candidate_id"),
            "机器分类":classification_label(
                logical.get("classification")
                or logical.get("proposed_classification")
            ),
            "标题":logical.get("title"),
            "页范围":f"{logical.get('start_page')}–{logical.get('end_page')}",
            "segment 数":len(logical.get("segments") or []),
        }
        for logical in logical_tables
    ]),use_container_width=True,hide_index=True)
    logical_ids=[
        str(logical["logical_table_candidate_id"])
        for logical in logical_tables
    ]
    logical_roles={};has_unresolved=False
    for position,logical in enumerate(logical_tables):
        logical_id=str(logical["logical_table_candidate_id"])
        machine_role=str(
            logical.get("classification")
            or logical.get("proposed_classification") or "UNRESOLVED"
        ).upper()
        options=list(LOGICAL_TABLE_ROLE_OPTIONS)
        default=(
            options.index(machine_role) if machine_role in options else 0
        )
        displayed_options=[CLASSIFICATION_LABELS[option] for option in options]
        selected_label=st.selectbox(
            f"{logical.get('title') or logical_id} 的逻辑表身份",
            displayed_options,index=default,
            key=f"{key_prefix}_logical_{position}_{logical_id}",
        )
        logical_roles[logical_id]=classification_key(selected_label)
        has_unresolved|=logical_roles[logical_id]=="UNRESOLVED"
    flattened=[]
    for logical in logical_tables:
        logical_id=str(logical["logical_table_candidate_id"])
        for segment in logical.get("segments") or []:
            flattened.append((logical_id,dict(segment)))
    target_by_segment={}
    for position,(source_logical_id,segment) in enumerate(flattened):
        segment_id=str(segment["segment_candidate_id"])
        default=logical_ids.index(source_logical_id)
        target_by_segment[segment_id]=st.selectbox(
            f"Segment {segment_id} 的所属 logical candidate",
            logical_ids,index=default,
            key=f"{key_prefix}_segment_target_{position}_{segment_id}",
        )
        st.caption(
            f"只读机器位置：PDF {segment.get('start_page')}–"
            f"{segment.get('end_page')}；机器分类 "
            f"{classification_label(segment.get('classification') or segment.get('proposed_classification'))}"
        )
    decisions={"logical_tables":[],"segments":[]}
    for logical_id,classification in logical_roles.items():
        decisions["logical_tables"].append({
            "logical_table_candidate_id":logical_id,
            "classification":classification,
        })
    grouped={logical_id:[] for logical_id in logical_ids}
    for source_order,(_,segment) in enumerate(flattened):
        grouped[target_by_segment[str(segment["segment_candidate_id"])]].append(
            (source_order,segment)
        )
    for logical_id in logical_ids:
        previous_segment_id=None
        for order,(_,segment) in enumerate(sorted(grouped[logical_id])):
            segment_id=str(segment["segment_candidate_id"])
            decisions["segments"].append({
                "segment_candidate_id":segment_id,
                "logical_table_candidate_id":logical_id,
                "classification":logical_roles[logical_id]
                    if order==0 else "CONTINUATION_SEGMENT",
                "continuation_of_segment_candidate_id":previous_segment_id,
            })
            previous_segment_id=segment_id
    reason=st.text_input(
        "人工校正依据（必填）",key=f"{key_prefix}_reason",
    )
    if st.button(
        "保存语义校正并认证 inventory",
        disabled=has_unresolved or not reason.strip(),
        key=f"{key_prefix}_submit",
    ):
        try:
            adjudication=backend.child_discovery_repository.adjudicate_inventory_case(
                case["resolution_case_id"],decisions=decisions,
                reviewer="USER",reason=reason.strip(),
            )
            certified_inventory=(
                backend.child_discovery_repository.certify_note_table_inventory(
                    case["note_table_inventory_candidate_id"],
                    reviewer="USER",
                    method="HUMAN_INVENTORY_ADJUDICATION_V1",
                    reason=reason.strip(),
                    source_adjudication_id=adjudication["adjudication_id"],
                )
            )
        except (PermissionError,ValueError,TypeError) as exc:
            st.error(f"校正未保存：{exc}")
            return None
        st.success("语义 overlay 已保存；机器 candidate 与物理证据未修改。")
        return {
            "adjudication":adjudication,
            "certified_inventory":certified_inventory,
        }
    return None


def render_child_mapping_review(st,backend,detail:dict[str,Any])->None:
    logical_asset_id=str(detail.get("logical_asset_id") or "")
    anchor_id=str(
        detail.get("statement_anchor_id") or detail.get("anchor_id") or ""
    )
    rows=backend.child_discovery_repository.mapping_workspace(
        logical_asset_id=logical_asset_id,anchor_id=anchor_id,
    )
    st.subheader("子表候选异常审核")
    st.caption(
        "仅 OPEN/UNRESOLVED inventory case 可人工校正；人工只能调整已发现候选的语义归属。"
    )
    if not rows:
        st.info("当前资产没有可审核的子表候选。")
        return
    by_child={}
    for row in rows:
        by_child.setdefault(row["anchor_child_id"],[]).append(row)
    displayed=0
    for child_id,candidates in by_child.items():
        cases=backend.child_discovery_repository.unresolved_inventory_cases(
            anchor_child_id=child_id,
        )
        if not cases:
            continue
        base=candidates[0]
        with st.expander(
            f"{base['raw_label']}｜附注主明细表金额 {_amount_text(base)}｜"
            f"{base.get('statement_scope') or 'UNKNOWN'}",
            expanded=True,
        ):
            for case in cases:
                render_inventory_resolution_case(
                    st,backend,case,
                    key_prefix=f"v611_inventory_case_{case['resolution_case_id']}",
                )
                displayed+=1
    if not displayed:
        st.info("没有 OPEN/UNRESOLVED inventory case；此处不提供人工映射入口。")
