"""Conditional Streamlit controls for merge ordering at project creation."""
from __future__ import annotations

from collections.abc import Iterable, Mapping, MutableMapping
from dataclasses import dataclass
from typing import Any

from merge_asset_picker_ui import capture_record_id, merge_asset_label


NOTE_ORDINAL_ORDER_POLICY = "NOTE_ORDINAL_REFERENCE_YEAR"


@dataclass(frozen=True)
class MergeOrderSelection:
    reference_capture_run_id: str
    order_policy: str | None
    reference_report_year: str


def _reference_options(
    selected_records: Iterable[Mapping[str, Any]],
) -> dict[str, str]:
    options = {
        merge_asset_label(record): str(
            record.get("run_id") or capture_record_id(record)
        ).strip()
        for record in selected_records
        if record.get("run_id") or capture_record_id(record)
    }
    if not options:
        raise ValueError("MERGE_ORDER_REFERENCE_CAPTURE_REQUIRED")
    return options


def _year_options(document_years: Iterable[Any]) -> list[str]:
    years = {
        str(value).strip()
        for value in document_years
        if value is not None
        and str(value).strip()
        and str(value).strip().lower() != "nan"
    }
    return sorted(years, reverse=True)


def render_merge_order_controls(
    st,
    selected_records: Iterable[Mapping[str, Any]],
    document_years: Iterable[Any],
) -> MergeOrderSelection:
    """Render only the controls required by the selected ordering strategy."""
    reference_options = _reference_options(selected_records)
    default_reference_label = next(iter(reference_options))
    reference_capture_run_id = reference_options[default_reference_label]

    order_policy_label = st.radio(
        "合表排序策略",
        ["排序基准表（默认）", "按年份附注号排序"],
        horizontal=True,
        key="merge_order_policy_selector",
        help=(
            "排序基准表：以所选 Capture 的行序为骨架（旧逻辑）。"
            "按年份附注号排序：以所选年份年报的附注号顺序排列成员表。"
        ),
    )
    order_policy = (
        NOTE_ORDINAL_ORDER_POLICY
        if str(order_policy_label).startswith("按年份")
        else None
    )
    reference_report_year = ""

    if order_policy:
        order_years = _year_options(document_years)
        if not order_years:
            st.warning(
                "所选来源缺少 document_year，无法按年份附注号排序；"
                "将回退为排序基准表。"
            )
            order_policy = None
        else:
            reference_report_year = str(st.selectbox(
                "基准年份（按该年附注号排序）",
                order_years,
                key="merge_order_reference_year",
            ))
    else:
        reference_key = "merge_reference_capture"
        session_state = getattr(st, "session_state", None)
        if (
            isinstance(session_state, MutableMapping)
            and reference_key in session_state
            and session_state.get(reference_key) not in reference_options
        ):
            session_state[reference_key] = default_reference_label
        reference_label = st.selectbox(
            "排序基准表（非常重要）",
            list(reference_options),
            index=0,
            key=reference_key,
            help=(
                "最终 canonical 行顺序严格以该表的 row_order 为骨架。"
                "其他来源独有细项只会按其原表上下文插入，"
                "不会重排基准表已有的小计/明细/合计顺序。"
            ),
        )
        reference_capture_run_id = reference_options[reference_label]
        st.caption(
            "排序策略：基准表顺序不可被 groupby/pivot/字母排序改变；"
            "其他来源若与基准表共同项目顺序冲突，将生成 ORDER_CONFLICT。"
        )

    return MergeOrderSelection(
        reference_capture_run_id=reference_capture_run_id,
        order_policy=order_policy,
        reference_report_year=reference_report_year,
    )
