"""Reusable merge-source picker over current certified active Capture records."""
from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Any, Iterable, Mapping


UNKNOWN_COMPANY = "未识别公司"
UNKNOWN_YEAR = "未识别年份"
UNKNOWN_MEMBER_TABLE = "未识别附注表名"
MERGE_PICKER_MODES = ("全部", "按公司", "按年份", "按附注表名", "按研究批次")


def _text(value: Any, fallback: str) -> str:
    text = str(value or "").strip()
    return text or fallback


def base_member_table_id(value: Any) -> str:
    """Collapse physical block identities to their certified member table."""
    return str(value or "").strip().split("::BLOCK_", 1)[0]


def enrich_merge_filter_identity(
    record: Mapping[str, Any],
    identity: Mapping[str, Any] | None = None,
    member_display_map: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    """Overlay read-only Logical Asset dimensions onto a Capture projection."""
    identity = identity or {}
    member_display_map = member_display_map or {}
    member_table_id = base_member_table_id(identity.get("member_table_id"))
    return dict(
        record,
        company=identity.get("company_id") or record.get("company"),
        document_year=identity.get("report_year") or record.get("document_year"),
        member_table_id=member_table_id,
        member_table_display=(
            member_display_map.get(member_table_id)
            or member_table_id
            or record.get("table_query")
        ),
    )


def capture_filter_dimensions(record: Mapping[str, Any]) -> dict[str, str]:
    """Read filter dimensions from Registry projections without re-deriving identity."""
    return {
        "company": _text(record.get("company") or record.get("company_id"), UNKNOWN_COMPANY),
        "year": _text(record.get("document_year") or record.get("report_year"), UNKNOWN_YEAR),
        "member_table": _text(
            record.get("member_table_display")
            or record.get("member_table")
            or base_member_table_id(record.get("member_table_id"))
            or record.get("table_query"),
            UNKNOWN_MEMBER_TABLE,
        ),
    }


def capture_record_id(record: Mapping[str, Any]) -> str:
    return _text(record.get("capture_id") or record.get("run_id"), "")


def capture_research_batch_ids(record: Mapping[str, Any]) -> tuple[str, ...]:
    value = record.get("research_batch_ids") or record.get("research_batch_id") or ()
    if isinstance(value, str):
        values = value.replace("，", ",").split(",")
    elif isinstance(value, Iterable):
        values = value
    else:
        values = (value,)
    return tuple(dict.fromkeys(
        str(item).strip() for item in values if str(item or "").strip()
    ))


def merge_filter_options(records: Iterable[Mapping[str, Any]]) -> dict[str, list[str]]:
    records = list(records)
    dimensions = [capture_filter_dimensions(record) for record in records]
    return {
        "companies": sorted({item["company"] for item in dimensions}),
        "years": sorted({item["year"] for item in dimensions}, reverse=True),
        "member_tables": sorted({item["member_table"] for item in dimensions}),
        "research_batch_ids": sorted({
            batch_id
            for record in records
            for batch_id in capture_research_batch_ids(record)
        }),
    }


def filter_merge_records(
    records: Iterable[Mapping[str, Any]],
    *,
    companies: set[str] | None = None,
    years: set[str] | None = None,
    member_tables: set[str] | None = None,
    research_batch_ids: set[str] | None = None,
) -> list[Mapping[str, Any]]:
    """Filter while preserving the Registry query order."""
    matched: list[Mapping[str, Any]] = []
    for record in records:
        dimensions = capture_filter_dimensions(record)
        if companies and dimensions["company"] not in companies:
            continue
        if years and dimensions["year"] not in years:
            continue
        if member_tables and dimensions["member_table"] not in member_tables:
            continue
        if research_batch_ids and not (
            set(capture_research_batch_ids(record)) & research_batch_ids
        ):
            continue
        matched.append(record)
    return matched


def reconcile_merge_selection(
    selected_ids: Iterable[str],
    visible_ids: Iterable[str],
    chosen_visible_ids: Iterable[str],
    valid_ids: Iterable[str],
) -> set[str]:
    """Replace the visible portion only, retaining selections hidden by filters."""
    valid = {str(value) for value in valid_ids}
    visible = {str(value) for value in visible_ids} & valid
    hidden = ({str(value) for value in selected_ids} & valid) - visible
    chosen = {str(value) for value in chosen_visible_ids} & visible
    return hidden | chosen


def normalize_merge_picker_state(
    state: Mapping[str, Any] | None,
    *,
    valid_ids: Iterable[str],
    options: Mapping[str, Iterable[str]],
) -> dict[str, Any]:
    """Normalize durable picker state independently from widget lifecycles."""
    state = state or {}
    mode = str(state.get("mode") or "全部")
    if mode not in MERGE_PICKER_MODES:
        mode = "全部"

    normalized: dict[str, Any] = {"mode": mode}
    for field in ("companies", "years", "member_tables", "research_batch_ids"):
        allowed = {str(value) for value in options.get(field, ())}
        normalized[field] = [
            str(value)
            for value in state.get(field, ())
            if str(value) in allowed
        ]
    valid = {str(value) for value in valid_ids}
    normalized["selected_ids"] = [
        str(value) for value in state.get("selected_ids", ()) if str(value) in valid
    ]
    return normalized


def _persist_picker_widget(session_state, state_key: str, field: str, widget_key: str) -> None:
    state = dict(session_state.get(state_key, {}))
    value = session_state.get(widget_key, [])
    state[field] = value if field == "mode" else list(value)
    session_state[state_key] = state


def _persist_picker_selection(
    session_state,
    state_key: str,
    selected_key: str,
    widget_key: str,
    visible_ids: Iterable[str],
    valid_ids: Iterable[str],
) -> None:
    state = dict(session_state.get(state_key, {}))
    selected = reconcile_merge_selection(
        state.get("selected_ids", ()),
        visible_ids,
        session_state.get(widget_key, ()),
        valid_ids,
    )
    state["selected_ids"] = sorted(selected)
    session_state[state_key] = state
    session_state[selected_key] = selected


def _set_picker_selection(
    session_state,
    state_key: str,
    selected_key: str,
    widget_key: str,
    visible_ids: Iterable[str],
    *,
    clear: bool = False,
) -> None:
    state = dict(session_state.get(state_key, {}))
    selected = set() if clear else {
        str(value) for value in state.get("selected_ids", ())
    } | {str(value) for value in visible_ids}
    state["selected_ids"] = sorted(selected)
    session_state[state_key] = state
    session_state[selected_key] = selected
    session_state[widget_key] = [] if clear else list(visible_ids)


@dataclass(frozen=True)
class MergeSelectionSummary:
    capture_count: int
    company_count: int
    year_range: str
    member_table_count: int
    research_batch_count: int


def merge_selection_summary(records: Iterable[Mapping[str, Any]]) -> MergeSelectionSummary:
    records = list(records)
    dimensions = [capture_filter_dimensions(record) for record in records]
    known_years = sorted({
        item["year"] for item in dimensions if item["year"] != UNKNOWN_YEAR
    })
    year_range = (
        f"{known_years[0]}-{known_years[-1]}"
        if len(known_years) > 1
        else (known_years[0] if known_years else "未识别")
    )
    return MergeSelectionSummary(
        capture_count=len(dimensions),
        company_count=len({item["company"] for item in dimensions}),
        year_range=year_range,
        member_table_count=len({item["member_table"] for item in dimensions}),
        research_batch_count=len({
            batch_id
            for record in records
            for batch_id in capture_research_batch_ids(record)
        }),
    )


def merge_asset_label(record: Mapping[str, Any]) -> str:
    dimensions = capture_filter_dimensions(record)
    parts = [dimensions["company"], dimensions["year"], dimensions["member_table"]]
    display_name = str(record.get("display_name") or "").strip()
    if display_name and display_name not in parts:
        parts.append(display_name)
    capture_id = capture_record_id(record)
    if capture_id:
        parts.append(capture_id)
    return " | ".join(parts)


def render_merge_asset_picker(
    st,
    records_or_backend,
    *,
    key: str = "v611_merge_assets",
) -> list[str]:
    """Render a filterable picker without changing eligibility or Capture state."""
    if hasattr(records_or_backend, "merge_eligibility_service"):
        records = list(records_or_backend.merge_eligibility_service.eligible_assets())
    else:
        records = list(records_or_backend)

    records_by_id = {
        capture_record_id(record): record
        for record in records
        if capture_record_id(record)
    }
    records = [records_by_id[capture_id] for capture_id in records_by_id]
    valid_ids = set(records_by_id)
    selected_key = f"{key}_selected_ids"
    state_key = f"{key}_state"
    options = merge_filter_options(records)
    raw_state = st.session_state.get(state_key)
    if not isinstance(raw_state, Mapping):
        raw_state = {
            "mode": st.session_state.get(f"{key}_mode", "全部"),
            "companies": st.session_state.get(f"{key}_companies", ()),
            "years": st.session_state.get(f"{key}_years", ()),
            "member_tables": st.session_state.get(f"{key}_member_tables", ()),
            "research_batch_ids": st.session_state.get(f"{key}_research_batch_ids", ()),
            "selected_ids": st.session_state.get(selected_key, ()),
        }
    state = normalize_merge_picker_state(raw_state, valid_ids=valid_ids, options=options)
    st.session_state[state_key] = state
    selected_ids = set(state["selected_ids"])

    mode_key = f"{key}_mode"
    if mode_key not in st.session_state:
        st.session_state[mode_key] = state["mode"]
    mode = st.radio(
        "整表来源",
        MERGE_PICKER_MODES,
        horizontal=True,
        key=mode_key,
        on_change=_persist_picker_widget,
        args=(st.session_state, state_key, "mode", mode_key),
    )
    state["mode"] = mode

    filter_specs = {
        "按公司": ("公司", "companies"),
        "按年份": ("年份", "years"),
        "按附注表名": ("member_table（附注表名）", "member_tables"),
        "按研究批次": ("research_batch_ids（研究批次）", "research_batch_ids"),
    }
    active_filters = {field: set() for _, field in filter_specs.values()}
    if mode in filter_specs:
        label, field = filter_specs[mode]
        widget_key = f"{key}_{field}"
        if widget_key not in st.session_state:
            st.session_state[widget_key] = state[field]
        values = st.multiselect(
            label,
            options[field],
            key=widget_key,
            on_change=_persist_picker_widget,
            args=(st.session_state, state_key, field, widget_key),
        )
        state[field] = list(values)
        active_filters[field] = set(values)
    st.session_state[state_key] = state

    matched_records = filter_merge_records(
        records,
        companies=active_filters["companies"],
        years=active_filters["years"],
        member_tables=active_filters["member_tables"],
        research_batch_ids=active_filters["research_batch_ids"],
    )
    matched_ids = [capture_record_id(record) for record in matched_records]
    view_signature = "\0".join([mode, *matched_ids])
    view_token = hashlib.sha1(view_signature.encode("utf-8")).hexdigest()[:12]
    visible_key = f"{key}_visible_{view_token}"
    if visible_key not in st.session_state:
        st.session_state[visible_key] = [
            capture_id for capture_id in matched_ids if capture_id in selected_ids
        ]
    chosen_ids = st.multiselect(
        "选择要合并的整表抓取运行",
        matched_ids,
        format_func=lambda capture_id: merge_asset_label(records_by_id[capture_id]),
        help="仅显示已通过正式合表资格门禁的抓取。",
        key=visible_key,
        on_change=_persist_picker_selection,
        args=(st.session_state, state_key, selected_key, visible_key, matched_ids, valid_ids),
    )
    selected_ids = reconcile_merge_selection(
        selected_ids,
        matched_ids,
        chosen_ids,
        valid_ids,
    )

    metric_col, select_col, clear_col = st.columns(3)
    metric_col.metric("匹配整表", len(matched_records))
    select_col.button(
        "全选当前筛选结果",
        key=f"{key}_all",
        on_click=_set_picker_selection,
        args=(st.session_state, state_key, selected_key, visible_key, matched_ids),
    )
    clear_col.button(
        "清空选择",
        key=f"{key}_clear",
        on_click=_set_picker_selection,
        args=(st.session_state, state_key, selected_key, visible_key, matched_ids),
        kwargs={"clear": True},
    )
    state["selected_ids"] = sorted(selected_ids)
    st.session_state[state_key] = state
    st.session_state[selected_key] = selected_ids

    selected_records = [
        record for record in records if capture_record_id(record) in selected_ids
    ]
    summary = merge_selection_summary(selected_records)
    st.caption(
        f"已选 {summary.capture_count} 个整表抓取 | {summary.company_count} 家公司 | "
        f"年份 {summary.year_range} | {summary.member_table_count} 个附注表名 | "
        f"{summary.research_batch_count} 个研究批次"
    )
    return [capture_record_id(record) for record in selected_records]
