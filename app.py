#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
app.py — Financial Metric Resolver v6.6 transitional Streamlit UI

Local Streamlit workbench:
1. L0 dictionary management
2. PDF project import
3. Extraction run (L0/L1/L2 DeepSeek/Gemini)
4. Human review and rule feedback
5. Reports and audit inspection

Run:
    streamlit run app.py
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import os
import re
import shutil
import sys
import traceback
import time
from pathlib import Path
from typing import Any, Optional

import streamlit as st
import pandas as pd

# Ensure local imports work when launched from elsewhere.
APP_DIR = Path(__file__).resolve().parent
if str(APP_DIR) not in sys.path:
    sys.path.insert(0, str(APP_DIR))

from financial_metric_pdf_resolver import (  # noqa: E402
    RuleBook,
    extract_pdf_blocks,
    file_sha256,
    resolve_metric,
    generate_markdown,
    generate_html,
)
from llm_providers import build_llm_provider  # noqa: E402
from rulebook_admin import persist_verified_alias  # noqa: E402
from table_capture import (  # noqa: E402
    capture_to_long_df,
    capture_to_wide_df,
    item_dictionary_df,
)
from table_merge import (  # noqa: E402
    infer_capture_metadata,
    create_merge_project,
    refresh_merge_project,
    normalize_table_id,
)
from capture_center_ui import render_capture_center  # noqa: E402
from review_inbox_ui import render_review_inbox  # noqa: E402
from asset_workspace_ui import render_asset_workspace  # noqa: E402
from inspection_route import InspectionRoute, set_inspection_route  # noqa: E402
from capture_models import CaptureMode, CaptureRequest  # noqa: E402
from export_utils import save_csv_as  # noqa: E402
from capture_library import (  # noqa: E402
    MERGE_READY_STATUSES,
    initialize_capture_library_run,
    ensure_capture_metadata,
    update_capture_metadata,
    apply_boundary_review,
    reset_boundary_review,
    capture_record,
    list_capture_records,
    soft_delete_capture,
    restore_capture,
    permanent_delete_capture,
    render_pdf_page_png,
    capture_merge_ready,
)
from merge_library import (  # noqa: E402
    ensure_merge_metadata,
    update_merge_metadata,
    list_merge_records,
    research_wide_download_name,
    soft_delete_merge,
    restore_merge,
    permanent_delete_merge,
)
from header_review import (  # noqa: E402
    derive_header_dimension_status,
    effective_columns,
    apply_header_dimension_review,
    reset_header_dimension_review,
)
from column_topology_review import (  # noqa: E402
    apply_column_topology_review,
    reset_column_topology_review,
)
from data_home import (  # noqa: E402
    resolve_data_home,
    save_data_home_config,
    ensure_data_home,
)
from backend_context import build_backend_services  # noqa: E402
from migration_center import (  # noqa: E402
    scan_old_version,
    migrate_old_version,
)
from asset_management import (  # noqa: E402
    INVALIDATION_REASON_CODES,
    new_batch_id,
)
from services.table_family_service import BUILTIN_TABLE_FAMILIES, build_family  # noqa: E402
from pdf_selection_workspace import render_pdf_selection_workspace  # noqa: E402
from merge_asset_picker_ui import (  # noqa: E402
    enrich_merge_filter_identity,
    merge_asset_label,
    merge_project_label,
    render_merge_asset_picker,
)
from merge_order_controls_ui import render_merge_order_controls  # noqa: E402
from version import APP_VERSION  # noqa: E402
from visible_header_policy import adaptive_wide_interactive_frame, adaptive_wide_preview_html  # noqa: E402
from batch_pipeline import (
    aggregate_batch_results,
    infer_company_year,
    display_pdf_name,
    prepare_fast_blocks,
    run_batch_jobs,
    write_batch_artifacts,
    refresh_adjudicated_artifacts,
)  # noqa: E402


# -----------------------------------------------------------------------------
# Paths / state
# -----------------------------------------------------------------------------

BUNDLED_RULES = APP_DIR / "metric_aliases.json"
DATA_HOME = resolve_data_home(APP_DIR)
DATA_PATHS = ensure_data_home(DATA_HOME, BUNDLED_RULES)

DEFAULT_RULES = DATA_PATHS["rules"]
WORKSPACE = DATA_HOME
UPLOAD_DIR = DATA_PATHS["uploads"]
RUNS_DIR = DATA_PATHS["runs"]
BACKUP_DIR = DATA_PATHS["rule_backups"]
REVIEW_DIR = DATA_PATHS["reviews"]
CACHE_DIR = DATA_PATHS["cache"]
BATCH_DIR = DATA_PATHS["batch_runs"]
TABLE_CAPTURE_DIR = DATA_PATHS["table_captures"]
TABLE_CAPTURE_TRASH_DIR = DATA_PATHS["table_capture_trash"]
MERGE_DIR = DATA_PATHS["table_merges"]
MERGE_TRASH_DIR = DATA_PATHS["merge_trash"]
TABLE_TAXONOMY_PATH = DATA_PATHS["taxonomy"]
ARCHIVE_DIR = DATA_PATHS["archive"]
MIGRATION_REPORT_DIR = DATA_PATHS["migration_reports"]
RUNTIME_DIR = DATA_PATHS["runtime"]
ASSET_REPORT_DIR = DATA_PATHS["asset_reports"]
METADATA_DB = DATA_PATHS["metadata_db"]

st.set_page_config(
    page_title="财报指标提取工作台",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="expanded",
)


def _member_display_map() -> dict[str, str]:
    """Registry member_id -> Chinese display name for research-wide exports."""
    try:
        with BACKEND.registry.connect() as conn:
            rows = conn.execute(
                """SELECT member_id, display_name
                   FROM family_members
                   WHERE display_name IS NOT NULL
                     AND TRIM(display_name) <> ''"""
            ).fetchall()
        return {
            str(row["member_id"]): str(row["display_name"])
            for row in rows
        }
    except Exception:
        return {}


@st.cache_resource(show_spinner=False)
def _backend_services_for_data_home(data_home_key: str):
    # DATA_PATHS is stable for this Streamlit process; the key invalidates the
    # cache if the configured DATA_HOME changes between launches.
    return build_backend_services(DATA_PATHS)


BACKEND = _backend_services_for_data_home(str(DATA_HOME))


def init_state() -> None:
    defaults = {
        "rules_path": str(DEFAULT_RULES),
        "active_pdf": None,
        "active_run_dir": None,
        "active_batch_run_dir": None,
        "active_table_capture_dir": None,
        "active_merge_dir": None,
        "last_results": None,
        "last_stats": None,
        "last_sha": None,
        "dictionary_dirty": False,
        "table_capture_batch_id": "",
    }
    for k, v in defaults.items():
        st.session_state.setdefault(k, v)


init_state()

if not st.session_state.get("_v61_registry_bootstrap_checked"):
    try:
        st.session_state["_v61_registry_bootstrap_result"] = BACKEND.registry_service.bootstrap_if_needed()
    except Exception as _registry_exc:
        st.session_state["_v61_registry_bootstrap_result"] = {
            "error": f"{type(_registry_exc).__name__}: {_registry_exc}"
        }
    st.session_state["_v61_registry_bootstrap_checked"] = True


# -----------------------------------------------------------------------------
# Utility
# -----------------------------------------------------------------------------

def _default_export_dir() -> str:
    downloads = Path.home() / "Downloads"
    return str(downloads if downloads.exists() else Path.home())


def custom_csv_export_widget(
    source_path: Path,
    default_name: str,
    key: str,
    label: str = "自定义保存 CSV",
) -> None:
    """
    Local Streamlit export: write a CSV directly to a user-specified filesystem
    directory and filename. This is separate from browser download.
    """
    source_path = Path(source_path)
    if not source_path.exists():
        return

    with st.expander(label, expanded=False):
        c1, c2 = st.columns([2, 1])
        export_dir = c1.text_input(
            "保存目录",
            value=_default_export_dir(),
            key=f"export_dir_{key}",
            help=r"本地运行时可填写 Windows 路径，例如 D:\finance\data；目录不存在时会自动创建。",
        )
        export_name = c2.text_input(
            "文件名",
            value=default_name,
            key=f"export_name_{key}",
        )
        overwrite = st.checkbox(
            "允许覆盖同名文件",
            value=False,
            key=f"export_overwrite_{key}",
        )

        if st.button("保存到指定位置", key=f"export_save_{key}"):
            try:
                name = str(export_name or "").strip()
                if not name:
                    raise ValueError("文件名不能为空。")
                if not name.lower().endswith(".csv"):
                    name += ".csv"
                # Disallow path separators inside filename; location belongs in directory field.
                if any(sep in name for sep in ["/", "\\"]):
                    raise ValueError("文件名中不要包含路径；请把路径填写在“保存目录”。")

                target = save_csv_as(
                    source_path=source_path,
                    directory=export_dir,
                    filename=name,
                    overwrite=overwrite,
                )
                st.success(f"已保存：{target}")
            except Exception as exc:
                st.error(f"自定义保存失败：{type(exc).__name__}: {exc}")


def _resolve_capture_source_pdf(result: dict[str, Any]) -> Optional[Path]:
    stats=result.get("stats") or {}
    source=str(stats.get("source_pdf_path") or "").strip()
    if source:
        p=Path(source)
        if p.exists():
            return p
    pdf_name=str(result.get("pdf_name") or "")
    exact=UPLOAD_DIR/pdf_name
    if exact.exists():
        return exact
    for p in UPLOAD_DIR.glob("*.pdf"):
        if display_pdf_name(p.name)==pdf_name or p.name==pdf_name:
            return p
    return None


def header_parser_arbitration_widget(run_dir: Path, key_prefix: str) -> None:
    run_dir=Path(run_dir)
    result_path=run_dir/"table_capture_result.json"
    if not result_path.exists():
        st.error("缺少 table_capture_result.json。")
        return
    result=json.loads(result_path.read_text(encoding="utf-8"))
    arbitration=(result.get("stats") or {}).get("header_arbitration") or {}
    candidates=arbitration.get("candidates") or {}

    if not candidates:
        st.info("该历史 Capture 来自旧版本，没有双算法表头候选记录。")
        return

    st.write(
        f"**自动推荐**：`{arbitration.get('auto_selected_parser')}`  · "
        f"**实际使用**：`{arbitration.get('selected_parser')}`  · "
        f"**原因**：`{arbitration.get('selection_reason')}`"
    )

    rows=[]
    for name,c in candidates.items():
        rows.append({
            "parser":name,
            "status":c.get("status"),
            "score":c.get("score"),
            "leaf_columns":c.get("leaf_count"),
            "numeric_clusters":c.get("numeric_cluster_count"),
            "scope_coverage":f"{c.get('scope_coverage')}/{c.get('leaf_count')}",
            "duplicate_dimensions":c.get("duplicate_dimension_count"),
            "alignment_ratio":c.get("alignment_ratio"),
            "hard_failures":" | ".join(c.get("hard_failures") or []),
        })
    st.dataframe(pd.DataFrame(rows),use_container_width=True,hide_index=True)

    c1,c2=st.columns(2)
    for name,col in zip(["ABSOLUTE_YEAR_CLASSIC","GENERALIZED_PERIOD_V57"],[c1,c2]):
        candidate=candidates.get(name)
        with col:
            st.markdown(f"**{name}**")
            if not candidate:
                st.caption("未产生候选。")
                continue
            preview=pd.DataFrame(candidate.get("columns_preview") or [])
            st.dataframe(preview,use_container_width=True,hide_index=True)

    st.caption(
        "裁判优先使用硬规则：数值列聚类数量、父级 scope 基数、维度唯一性；"
        "评分只在多个候选都通过硬规则时用于排序。不会把两个算法的部分列拼接成一个结果。"
    )

    options=list(candidates.keys())
    selected=st.selectbox(
        "人工选择表头算法",
        options,
        index=options.index(arbitration.get("selected_parser")) if arbitration.get("selected_parser") in options else 0,
        key=f"{key_prefix}_parser_choice",
    )
    source_pdf=_resolve_capture_source_pdf(result)
    if source_pdf is None:
        st.warning("未找到原 PDF，当前只能查看候选，不能创建人工指定算法的新 Capture。")
        return

    if st.button(
        "用所选算法创建新的 Capture（保留当前机器证据）",
        type="primary",
        use_container_width=True,
        key=f"{key_prefix}_parser_rerun",
    ):
        try:
            stamp=dt.datetime.now().strftime("%Y%m%dT%H%M%S")
            parser_tag="classic" if selected=="ABSOLUTE_YEAR_CLASSIC" else "generalized"
            safe_base=re.sub(r'[\\\\/:*?"<>|]+',"_",run_dir.name)[:110]
            new_dir=TABLE_CAPTURE_DIR/f"{safe_base}__parser_{parser_tag}__{stamp}"
            submitted=BACKEND.capture_service.create(
                pdf_path=source_pdf,
                table_query=str(result.get("table_query") or ""),
                note_number=result.get("note_number"),
                start_page_override=int(result.get("start_page") or 1),
                max_pages=max(
                    1,
                    int(result.get("end_page") or 1)-int(result.get("start_page") or 1)+2,
                ),
                header_parser_mode=selected,
                output_dir=new_dir,
            )
            created_dir=Path(submitted["run_path"])
            st.session_state.active_table_capture_dir=str(created_dir)
            st.success(
                f"已通过统一抓取编排器创建新 Capture：{created_dir.name}。"
                "原 Capture 未被覆盖。"
            )
            st.rerun()
        except Exception as exc:
            st.exception(exc)


def column_topology_review_widget(run_dir: Path, key_prefix: str) -> None:
    run_dir=Path(run_dir)
    result_path=run_dir/"table_capture_result.json"
    if not result_path.exists():
        st.error("缺少 table_capture_result.json。")
        return
    result=json.loads(result_path.read_text(encoding="utf-8"))
    machine_cols=result.get("columns") or []
    if not machine_cols:
        st.info("没有机器逻辑列。")
        return

    review=result.get("column_topology_review") or {}
    active=set(int(x) for x in (review.get("active_ordinals") or []))
    has_review=str(review.get("status") or "")=="HUMAN_CONFIRMED"

    df=pd.DataFrame(machine_cols)
    df["action"]=df["ordinal"].map(
        lambda x:"KEEP" if (not has_review or int(x) in active) else "DROP_DUPLICATE"
    )
    show=[c for c in [
        "ordinal","source_column_index","header_raw","year","scope","restated","action"
    ] if c in df.columns]

    st.caption(
        "这是自动裁判仍不理想时的安全兜底。当前支持 KEEP / DROP_DUPLICATE；"
        "删除只影响正式输出，机器原始列永久保留。真正需要拼接数值碎片的 MERGE_COLUMNS 不会自动猜测。"
    )
    edited=st.data_editor(
        df[show],
        use_container_width=True,
        hide_index=True,
        disabled=[c for c in show if c!="action"],
        column_config={
            "action":st.column_config.SelectboxColumn(
                "action",
                options=["KEEP","DROP_DUPLICATE"],
                required=True,
            )
        },
        key=f"{key_prefix}_topology_editor",
    )
    note=st.text_input(
        "列拓扑复核备注（可选）",
        value=str(review.get("reviewer_note") or ""),
        key=f"{key_prefix}_topology_note",
    )
    c1,c2=st.columns(2)
    if c1.button(
        "确认列拓扑并重新物化正式输出",
        type="primary",
        use_container_width=True,
        key=f"{key_prefix}_topology_apply",
    ):
        try:
            out=apply_column_topology_review(
                run_dir,
                edited[["ordinal","action"]].to_dict("records"),
                reviewer_note=note,
            )
            st.success(
                f"列拓扑已确认：保留 {len(out.get('active_ordinals') or [])} 列，"
                f"排除 {len(out.get('dropped_ordinals') or [])} 列。"
            )
            st.rerun()
        except Exception as exc:
            st.exception(exc)
    if c2.button(
        "恢复全部机器列",
        use_container_width=True,
        key=f"{key_prefix}_topology_reset",
    ):
        try:
            check=reset_column_topology_review(run_dir)
            st.warning(f"已恢复全部机器列；表头状态={check['status']}。")
            st.rerun()
        except Exception as exc:
            st.exception(exc)


def header_dimension_review_widget(run_dir: Path, key_prefix: str) -> None:
    run_dir = Path(run_dir)
    result_path = run_dir / "table_capture_result.json"
    if not result_path.exists():
        st.error("缺少 table_capture_result.json。")
        return

    result = json.loads(result_path.read_text(encoding="utf-8"))
    status = derive_header_dimension_status(result)
    machine_cols = result.get("columns") or []
    current_cols = effective_columns(result)

    st.write(f"**当前表头维度状态**：`{status}`")
    if status == "REVIEW_REQUIRED":
        st.error(
            "检测到重复期间列无法由 year/scope/restated/measure 唯一区分。"
            "在完成表头维度复核前，该整表禁止进入正式合表。"
        )
    else:
        st.success("当前逻辑列维度唯一，可区分各数据窗口。")

    machine_df = pd.DataFrame(machine_cols)
    if not machine_df.empty:
        show_cols = [c for c in [
            "ordinal","source_column_index","header_raw","year","period_label",
            "scope","measure","restated"
        ] if c in machine_df.columns]
        st.caption("机器识别表头（审计证据，不会被人工覆盖）：")
        st.dataframe(machine_df[show_cols], use_container_width=True, hide_index=True)

    edit_df = pd.DataFrame(current_cols)
    if edit_df.empty:
        st.warning("没有逻辑列可复核。")
        return

    for col in ["year","period_label","scope","measure","header_raw"]:
        if col in edit_df:
            edit_df[col]=edit_df[col].fillna("").astype(str)
    if "restated" in edit_df:
        edit_df["restated"]=edit_df["restated"].fillna(False).astype(bool)

    edit_cols=[c for c in [
        "ordinal","source_column_index","year","period_label","scope","measure",
        "restated","header_raw"
    ] if c in edit_df.columns]
    edited=st.data_editor(
        edit_df[edit_cols],
        use_container_width=True,
        hide_index=True,
        disabled=["ordinal","source_column_index","header_raw"],
        key=f"{key_prefix}_header_editor",
        column_config={
            "restated": st.column_config.CheckboxColumn("restated"),
        },
    )

    st.caption(
        "典型例：2022/2021/2022/2021 应分别标为 "
        "本集团/本集团/本公司/本公司；同年多列可用 measure 区分摊余成本/公允价值。"
        "修改只影响正式输出维度，机器原始抓取保持不变。"
    )
    note=st.text_input(
        "表头维度复核备注（可选）",
        value=str((result.get("header_review") or {}).get("reviewer_note") or ""),
        key=f"{key_prefix}_header_note",
    )

    c1,c2=st.columns(2)
    if c1.button(
        "确认表头维度并重新生成正式输出",
        type="primary",
        use_container_width=True,
        key=f"{key_prefix}_header_confirm",
    ):
        try:
            review=apply_header_dimension_review(
                run_dir,
                edited_columns=edited.to_dict("records"),
                reviewer_note=note,
            )
            st.success(
                f"表头维度已确认：{len(review.get('columns') or [])} 个逻辑列。"
                "正式 CSV/Excel 已重新物化。"
            )
            st.rerun()
        except Exception as exc:
            st.exception(exc)

    if c2.button(
        "恢复机器识别表头并重新判定",
        use_container_width=True,
        key=f"{key_prefix}_header_reset",
    ):
        try:
            check=reset_header_dimension_review(run_dir)
            st.warning(f"已恢复机器表头；当前状态={check['status']}。")
            st.rerun()
        except Exception as exc:
            st.exception(exc)


def boundary_review_widget(run_dir: Path, key_prefix: str) -> None:
    """
    Review table end-boundary directly from extracted output.

    Reviewer selects the last valid row. Machine-full output is immutable;
    official table_raw_* artifacts are rematerialized from row 1..cutoff.
    """
    run_dir = Path(run_dir)
    result_path = run_dir / "table_capture_result.json"
    if not result_path.exists():
        st.error("缺少 table_capture_result.json。")
        return

    result_data = json.loads(result_path.read_text(encoding="utf-8"))
    boundary_status = str(result_data.get("boundary_status") or "REVIEW_REQUIRED")
    machine_wide_path = run_dir / "machine_capture_full_wide.csv"
    if not machine_wide_path.exists():
        machine_wide_path = run_dir / "table_raw_wide.csv"

    if not machine_wide_path.exists():
        st.error("缺少可复核的整表宽表。")
        return

    machine_wide = pd.read_csv(machine_wide_path)
    st.write(f"**当前边界状态**：`{boundary_status}`")

    if boundary_status == "REVIEW_REQUIRED":
        st.warning(
            "自动解析未获得可靠硬结束边界。请直接查看下面的完整机器抓取结果，"
            "选择最后一条仍属于目标表的记录。其后的记录会从正式输出中排除，但仍保留在机器审计文件中。"
        )
    else:
        st.info(
            "当前边界已确认。仍可重新指定最后有效记录；修改不会删除机器原始抓取证据。"
        )

    st.dataframe(machine_wide, use_container_width=True, hide_index=True, height=430)

    if machine_wide.empty or "row_order" not in machine_wide.columns:
        st.error("当前宽表没有 row_order，无法做行级边界复核。")
        return

    choices = []
    label_to_order = {}
    for _, row in machine_wide.iterrows():
        try:
            order = int(row["row_order"])
        except Exception:
            continue
        item = str(row.get("raw_item") or row.get("normalized_item") or "").strip()
        label = f"{order} · {item}"
        # Ensure uniqueness.
        if label in label_to_order:
            label += f" · #{len(choices)+1}"
        choices.append(label)
        label_to_order[label] = order

    if not choices:
        st.error("没有可选择的有效 row_order。")
        return

    existing_review = result_data.get("boundary_review") or {}
    existing_cutoff = existing_review.get("last_included_row_order")
    default_idx = len(choices) - 1
    if existing_cutoff is not None:
        for i, label in enumerate(choices):
            if label_to_order[label] == int(existing_cutoff):
                default_idx = i
                break

    selected_label = st.selectbox(
        "最后一条属于目标表的记录",
        choices,
        index=default_idx,
        key=f"{key_prefix}_boundary_cutoff",
        help="选择后，该记录及之前的行进入正式 table_raw_*；后续行标记为边界排除并仅保留在审计层。",
    )
    cutoff = label_to_order[selected_label]

    # Context preview around the cutoff.
    numeric_order = pd.to_numeric(machine_wide["row_order"], errors="coerce")
    context = machine_wide[
        (numeric_order >= max(1, cutoff - 3))
        & (numeric_order <= cutoff + 5)
    ].copy()
    st.caption("截断点上下文：蓝本中选择的记录应是目标表最后一条有效记录。")
    st.dataframe(context, use_container_width=True, hide_index=True)

    note = st.text_input(
        "边界复核备注（可选）",
        value=str(existing_review.get("reviewer_note") or ""),
        key=f"{key_prefix}_boundary_note",
    )

    c1, c2 = st.columns(2)
    if c1.button(
        "确认到此结束并重新生成正式输出",
        type="primary",
        use_container_width=True,
        key=f"{key_prefix}_boundary_confirm",
    ):
        try:
            review = apply_boundary_review(
                run_dir,
                last_included_row_order=cutoff,
                reviewer_note=note,
            )
            st.success(
                f"边界已人工确认：保留至 row {review['last_included_row_order']} · "
                f"{review['last_included_raw_item']}。正式 CSV/Excel 已重新生成。"
            )
            st.rerun()
        except Exception as exc:
            st.exception(exc)

    if c2.button(
        "恢复完整机器抓取并重新待审",
        use_container_width=True,
        key=f"{key_prefix}_boundary_reset",
    ):
        try:
            reset_boundary_review(run_dir)
            st.warning("已恢复完整机器抓取；边界状态重新进入待复核。")
            st.rerun()
        except Exception as exc:
            st.exception(exc)


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json_atomic(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    json.loads(tmp.read_text(encoding="utf-8"))  # syntax validation
    tmp.replace(path)


def backup_rules(path: Path) -> Path:
    stamp = dt.datetime.now().strftime("%Y%m%d_%H%M%S")
    backup = BACKUP_DIR / f"{path.stem}_{stamp}{path.suffix}"
    shutil.copy2(path, backup)
    return backup


def normalize_list_text(text: str) -> list[str]:
    parts = []
    for raw in text.replace("；", "\n").replace(";", "\n").replace("|", "\n").splitlines():
        s = raw.strip()
        if s and s not in parts:
            parts.append(s)
    return parts


def list_text(items: list[str]) -> str:
    return "\n".join(items or [])


def validate_rule_dict(raw: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    if not isinstance(raw, dict):
        return ["规则库顶层必须是 JSON object。"]

    required = ["aliases", "soft_aliases", "keywords", "exclude", "table_hint", "position_hint"]
    alias_owner: dict[str, str] = {}

    def norm(s: str) -> str:
        return re.sub(r"[\s:：,，;；。\.、_/\\\-—–·'\"“”‘’（）()【】\[\]{}<>《》]+", "", str(s)).lower()

    for metric, cfg in raw.items():
        if not isinstance(cfg, dict):
            errors.append(f"{metric}: 配置必须是 object")
            continue
        for key in required:
            if key not in cfg:
                errors.append(f"{metric}: 缺少字段 {key}")
        for key in ["aliases", "soft_aliases", "keywords", "exclude", "table_hint"]:
            if key in cfg and not isinstance(cfg[key], list):
                errors.append(f"{metric}.{key}: 必须是 list")
        if cfg.get("position_hint") not in {"top", "middle", "bottom", "any"}:
            errors.append(f"{metric}.position_hint: 必须是 top/middle/bottom/any")

        names = [metric] + cfg.get("aliases", []) + cfg.get("soft_aliases", [])
        for name in names:
            n = norm(name)
            if not n:
                continue
            owner = alias_owner.get(n)
            if owner and owner != metric:
                errors.append(f"跨指标别名冲突：{name!r} 同时属于 {owner} 和 {metric}")
            else:
                alias_owner[n] = metric

    return errors


def load_rules() -> dict[str, Any]:
    path = Path(st.session_state.rules_path)
    return read_json(path)


def save_rules(data: dict[str, Any]) -> tuple[bool, str]:
    errors = validate_rule_dict(data)
    if errors:
        return False, "\n".join(errors[:30])
    path = Path(st.session_state.rules_path)
    backup = backup_rules(path)
    write_json_atomic(path, data)
    # Validate through production RuleBook as final gate.
    RuleBook(path)
    st.session_state.dictionary_dirty = False
    return True, f"已保存；备份：{backup.name}"


def safe_filename(name: str) -> str:
    keep = "".join(c if c.isalnum() or c in "._-" else "_" for c in name)
    return keep[:180] or "uploaded.pdf"


def inspect_pdf_bytes(raw: bytes) -> dict[str, Any]:
    """
    Lightweight preflight before pdfplumber/pdfminer.

    This does not prove the PDF is semantically healthy, but catches:
    - empty/truncated uploads
    - HTML/error pages renamed to .pdf
    - arbitrary non-PDF files
    - leading wrapper/junk before %PDF-
    """
    info: dict[str, Any] = {
        "size_bytes": len(raw),
        "is_pdf_header": False,
        "pdf_header_offset": None,
        "has_eof_marker": False,
        "looks_html": False,
        "errors": [],
        "warnings": [],
    }

    if len(raw) == 0:
        info["errors"].append("文件大小为 0 字节。")
        return info

    stripped = raw[:4096].lstrip()
    lowered = stripped[:512].lower()
    if lowered.startswith(b"<!doctype html") or lowered.startswith(b"<html") or b"<body" in lowered:
        info["looks_html"] = True
        info["errors"].append("文件内容看起来是 HTML 网页，而不是 PDF。常见原因是保存了下载页/登录页/错误页。")

    offset = raw[:1024 * 1024].find(b"%PDF-")
    if offset == 0:
        info["is_pdf_header"] = True
        info["pdf_header_offset"] = 0
    elif offset > 0:
        info["pdf_header_offset"] = offset
        info["warnings"].append(
            f"在文件开头之后 {offset} 字节才发现 %PDF- 头，文件前存在额外数据；部分解析器可能失败。"
        )
    else:
        info["errors"].append("未发现 PDF 文件头 %PDF-。该文件很可能不是 PDF，或已严重损坏。")

    tail = raw[-8192:] if len(raw) > 8192 else raw
    if b"%%EOF" in tail:
        info["has_eof_marker"] = True
    else:
        info["warnings"].append("文件尾部未发现 %%EOF 标记，文件可能被截断或非标准生成。")

    if len(raw) < 1024:
        info["warnings"].append("文件小于 1 KB，几乎不可能是正常财报 PDF。")

    return info


def inspect_pdf_file(path: Path) -> dict[str, Any]:
    try:
        return inspect_pdf_bytes(path.read_bytes())
    except Exception as exc:
        return {
            "size_bytes": 0,
            "is_pdf_header": False,
            "pdf_header_offset": None,
            "has_eof_marker": False,
            "looks_html": False,
            "errors": [f"无法读取文件：{type(exc).__name__}: {exc}"],
            "warnings": [],
        }


def try_normalize_leading_junk_pdf(path: Path) -> tuple[Optional[Path], str]:
    """
    Safe-ish normalization for one specific case only:
    bytes before a valid %PDF- header.

    We never attempt to fabricate/reconstruct missing PDF objects.
    """
    raw = path.read_bytes()
    offset = raw[:1024 * 1024].find(b"%PDF-")
    if offset <= 0:
        return None, "没有检测到可安全剥离的 PDF 前置数据。"
    repaired = path.with_name(path.stem + "_normalized.pdf")
    repaired.write_bytes(raw[offset:])
    check = inspect_pdf_file(repaired)
    if check["errors"]:
        repaired.unlink(missing_ok=True)
        return None, "剥离前置数据后仍未通过 PDF 头检查。"
    return repaired, f"已剥离 PDF 头之前的 {offset} 字节，生成 {repaired.name}"


def save_uploaded_pdf(uploaded) -> Path:
    raw = uploaded.getvalue()
    check = inspect_pdf_bytes(raw)
    if check["errors"]:
        raise ValueError("；".join(check["errors"]))
    sha = hashlib.sha256(raw).hexdigest()[:12]
    path = UPLOAD_DIR / f"{sha}_{safe_filename(uploaded.name)}"
    path.write_bytes(raw)
    try:
        company, year = infer_company_year(Path(display_pdf_name(path.name)), "")
        BACKEND.registry.upsert_pdf({
            "pdf_id": "PDF::" + str(path.resolve()).lower(),
            "filename": path.name,
            "display_name": display_pdf_name(path.name),
            "company": company,
            "document_year": year,
            "size_bytes": path.stat().st_size,
            "path": str(path.resolve()),
            "modified_at": dt.datetime.fromtimestamp(path.stat().st_mtime).astimezone().isoformat(timespec="seconds"),
        })
    except Exception:
        pass
    return path


def run_dir_for(pdf_path: Path) -> Path:
    stamp = dt.datetime.now().strftime("%Y%m%d_%H%M%S")
    return RUNS_DIR / f"{pdf_path.stem}_{stamp}"


def load_run_results(run_dir: Path) -> Optional[dict[str, Any]]:
    p = run_dir / "results.json"
    if not p.exists():
        return None
    return read_json(p)


def result_summary_df(payload: dict[str, Any]) -> pd.DataFrame:
    rows = []
    for r in payload.get("results", []):
        s = r.get("selected") or {}
        pv = r.get("primary_value") or {}
        value = pv.get("value_yuan")
        if value is None:
            value = pv.get("raw")
        rows.append({
            "查询指标": r.get("metric_input"),
            "标准科目": r.get("standard_metric"),
            "状态": r.get("status"),
            "层级": r.get("layer"),
            "置信度": r.get("confidence"),
            "页码": s.get("page"),
            "匹配原文": s.get("label"),
            "主值": value,
            "主值置信度": r.get("primary_value_confidence"),
        })
    return pd.DataFrame(rows)


def append_human_review(run_dir: Path, record: dict[str, Any]) -> None:
    path = run_dir / "human_review.jsonl"
    payload = {
        "timestamp": dt.datetime.now().astimezone().isoformat(timespec="seconds"),
        **record,
    }
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(payload, ensure_ascii=False) + "\n")


def runtime_instance() -> dict[str, Any]:
    path = RUNTIME_DIR / "active_instance.json"
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def request_runtime_action(action: str) -> tuple[bool, str]:
    active = runtime_instance()
    token = str(active.get("instance_token") or os.environ.get("FIN_METRIC_INSTANCE_TOKEN") or "")
    if not token:
        return False, "当前程序不是通过 v6.1 single-instance launcher 启动，无法安全远程控制进程。"
    payload = {
        "action": str(action),
        "instance_token": token,
        "requested_at": dt.datetime.now().astimezone().isoformat(timespec="seconds"),
        "requested_from": "streamlit_ui",
    }
    (RUNTIME_DIR / "control.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return True, f"已提交 {action} 请求。"


# -----------------------------------------------------------------------------
# Sidebar
# -----------------------------------------------------------------------------

st.sidebar.title("📊 财报指标提取工作台")
active_instance = runtime_instance()
st.sidebar.caption(
    f"当前版本：{APP_VERSION} · 端口：{active_instance.get('port', 'direct')} · "
    f"模式：{'Single Instance' if active_instance else 'Direct Streamlit'}"
)
pending_main_page = st.session_state.pop("_pending_main_page", None)
if pending_main_page:
    # Streamlit 禁止在同一轮中于 radio 创建后回写其 key；页面跳转
    # 统一先写入 pending key，再在下一轮、控件实例化前应用。
    st.session_state["main_page"] = pending_main_page
if st.session_state.get("main_page") in {"附注多表检查","人工复核"}:
    st.session_state["main_page"]="逻辑资产工作区"
page = st.sidebar.radio(
    "工作区",
    [
        "总览", "L0 指标字典", "PDF 项目", "运行提取",
        "批量项目", "抓取中心", "审核收件箱", "逻辑资产工作区",
        "整表批量工作台", "发现结果审核", "发现规则与学习库", "研究定义与表族", "整表抓取", "合表", "报告与审计", "数据资产管理", "系统与迁移",
    ],
    key="main_page",
)

st.sidebar.divider()
st.sidebar.caption("共享 DATA_HOME")
st.sidebar.code(str(DATA_HOME))
st.sidebar.caption("当前规则库")
st.sidebar.code(str(Path(st.session_state.rules_path)))
if st.session_state.active_pdf:
    st.sidebar.caption("当前 PDF")
    st.sidebar.code(Path(st.session_state.active_pdf).name)
if st.session_state.active_run_dir:
    st.sidebar.caption("当前运行")
    st.sidebar.code(Path(st.session_state.active_run_dir).name)
if st.session_state.active_table_capture_dir:
    st.sidebar.caption("当前整表抓取")
    st.sidebar.code(Path(st.session_state.active_table_capture_dir).name)
if st.session_state.active_merge_dir:
    st.sidebar.caption("当前合表项目")
    st.sidebar.code(Path(st.session_state.active_merge_dir).name)

st.sidebar.divider()
with st.sidebar.expander("系统控制", expanded=False):
    c1, c2 = st.columns(2)
    if c1.button("重启程序", use_container_width=True, key="runtime_restart_button"):
        ok, msg = request_runtime_action("restart")
        (st.success if ok else st.warning)(msg)
        if ok:
            time.sleep(0.8)
    exit_confirm = st.checkbox("确认退出", key="runtime_exit_confirm")
    if c2.button("退出程序", use_container_width=True, disabled=not exit_confirm, key="runtime_exit_button"):
        ok, msg = request_runtime_action("shutdown")
        (st.success if ok else st.warning)(msg)
        if ok:
            time.sleep(0.8)


# -----------------------------------------------------------------------------
# Dashboard
# -----------------------------------------------------------------------------

if page == "总览":
    st.title("财报 PDF 指标提取工作台")
    st.caption("共享 DATA_HOME → PDF/历史资产 → 提取/整表 → 结构复核 → 合表/Taxonomy → 审计；升级版本不再复制 workspace。")

    rules = load_rules()
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("L0 标准指标", len(rules))
    c2.metric("已导入 PDF", len(list(UPLOAD_DIR.glob("*.pdf"))))
    c3.metric("历史运行", len([p for p in RUNS_DIR.iterdir() if p.is_dir()]))
    c4.metric("规则备份", len(list(BACKUP_DIR.glob("*.json"))))

    st.subheader("工作流")
    st.markdown(
        """
        **1. L0 指标字典**：新增、编辑、删除标准指标；管理 aliases / soft aliases / exclude / table hints；保存前自动校验冲突并备份。  
        **2. PDF 项目**：拖入年报/季报/偿付能力报告，建立当前项目。  
        **3. 运行提取**：从 L0 选择指标，必要时启用 DeepSeek / Gemini；LLM 只做候选选择，不生成金额。  
        **4. 人工复核**：逐项查看页码、原始科目、数值列、Top 候选；记录确认/驳回；可将确认别名回写 L0。  
        **5. 批量项目**：多 PDF 并行 Fast Index、候选页深度解析、缓存复用并输出公司×年份指标表。  
**6. 报告与审计**：在界面直接查看 HTML 报告、Markdown、results.json、audit.jsonl 和人工复核记录。
        """
    )

    st.info(
        "设计原则：字典负责提高精度，但不应成为未来 PDF 搜索的永久硬门槛；"
        "GUI 会把 RULE GAP / REVIEW_REQUIRED 暴露出来，便于持续扩充 L0。"
    )


# -----------------------------------------------------------------------------
# L0 dictionary manager
# -----------------------------------------------------------------------------

elif page == "L0 指标字典":
    st.title("L0 指标字典管理")
    rules = load_rules()

    top1, top2, top3 = st.columns([2, 1, 1])
    search = top1.text_input("搜索标准指标 / 别名", placeholder="例如：偿付能力、总保费、权益")
    category = top2.selectbox(
        "指标类型筛选",
        ["全部", "financial_statement", "regulatory_metric", "operating_metric",
         "investment_metric", "value_metric", "quality_metric", "未分类"],
    )
    mode = top3.radio("操作", ["编辑现有", "新增指标"], horizontal=True)

    def metric_matches(metric: str, cfg: dict[str, Any]) -> bool:
        blob = " ".join(
            [metric]
            + cfg.get("aliases", [])
            + cfg.get("soft_aliases", [])
            + cfg.get("keywords", [])
        ).lower()
        if search and search.lower() not in blob:
            return False
        mt = cfg.get("metric_type")
        if category == "未分类" and mt:
            return False
        if category not in {"全部", "未分类"} and mt != category:
            return False
        return True

    filtered = [m for m, cfg in rules.items() if metric_matches(m, cfg)]
    st.caption(f"当前显示 {len(filtered)} / {len(rules)} 个标准指标")

    if mode == "编辑现有":
        if not filtered:
            st.warning("没有匹配指标。")
            st.stop()
        selected_metric = st.selectbox("标准指标", filtered)
        cfg = json.loads(json.dumps(rules[selected_metric], ensure_ascii=False))
        metric_name = selected_metric
    else:
        metric_name = st.text_input("新标准指标名称", placeholder="例如：核心偿付能力充足率")
        cfg = {
            "aliases": [],
            "soft_aliases": [],
            "keywords": [],
            "exclude": [],
            "table_hint": [],
            "position_hint": "any",
            "metric_type": "regulatory_metric",
            "value_type": "percentage",
        }

    st.subheader("规则配置")
    left, right = st.columns(2)
    aliases_txt = left.text_area(
        "强别名 aliases（每行一个）",
        value=list_text(cfg.get("aliases", [])),
        height=140,
        help="语义高度确定的别名。避免把“收入”“权益”这种过宽词放进强别名。",
    )
    soft_txt = right.text_area(
        "软别名 soft_aliases（每行一个）",
        value=list_text(cfg.get("soft_aliases", [])),
        height=140,
    )
    kw_txt = left.text_area("关键词 keywords", value=list_text(cfg.get("keywords", [])), height=120)
    exc_txt = right.text_area("排除词 exclude", value=list_text(cfg.get("exclude", [])), height=120)
    hint_txt = left.text_area(
        "表类型提示 table_hint",
        value=list_text(cfg.get("table_hint", [])),
        height=110,
        placeholder="偿付能力表\n监管指标表",
    )
    position = right.selectbox(
        "位置提示 position_hint",
        ["any", "top", "middle", "bottom"],
        index=["any", "top", "middle", "bottom"].index(cfg.get("position_hint", "any")),
    )
    metric_type = left.selectbox(
        "metric_type",
        ["financial_statement", "regulatory_metric", "operating_metric",
         "investment_metric", "value_metric", "quality_metric", "other"],
        index=(
            ["financial_statement", "regulatory_metric", "operating_metric",
             "investment_metric", "value_metric", "quality_metric", "other"]
            .index(cfg.get("metric_type", "other"))
            if cfg.get("metric_type", "other") in
            ["financial_statement", "regulatory_metric", "operating_metric",
             "investment_metric", "value_metric", "quality_metric", "other"]
            else 6
        ),
    )
    value_type = right.selectbox(
        "value_type",
        ["monetary", "percentage", "ratio", "text", "count", "other"],
        index=(
            ["monetary", "percentage", "ratio", "text", "count", "other"]
            .index(cfg.get("value_type", "other"))
            if cfg.get("value_type", "other") in
            ["monetary", "percentage", "ratio", "text", "count", "other"]
            else 5
        ),
    )

    new_cfg = {
        "aliases": normalize_list_text(aliases_txt),
        "soft_aliases": normalize_list_text(soft_txt),
        "keywords": normalize_list_text(kw_txt),
        "exclude": normalize_list_text(exc_txt),
        "table_hint": normalize_list_text(hint_txt),
        "position_hint": position,
        "metric_type": metric_type,
        "value_type": value_type,
    }

    b1, b2, b3 = st.columns([1, 1, 2])
    if b1.button("校验当前规则", type="secondary", use_container_width=True):
        test = dict(rules)
        if metric_name:
            test[metric_name] = new_cfg
        errs = validate_rule_dict(test)
        if errs:
            st.error("\n".join(errs[:30]))
        else:
            st.success("规则结构、JSON语义和跨指标别名冲突检查通过。")

    if b2.button("保存规则", type="primary", use_container_width=True):
        if not metric_name.strip():
            st.error("标准指标名称不能为空。")
        elif mode == "新增指标" and metric_name in rules:
            st.error("该标准指标已存在，请切换到“编辑现有”。")
        else:
            updated = dict(rules)
            updated[metric_name.strip()] = new_cfg
            ok, msg = save_rules(updated)
            if ok:
                st.success(msg)
                st.rerun()
            else:
                st.error(msg)

    if mode == "编辑现有":
        with b3:
            if st.button("删除当前指标", type="secondary"):
                st.session_state[f"confirm_delete_{selected_metric}"] = True
        if st.session_state.get(f"confirm_delete_{selected_metric}"):
            st.warning(f"确认删除标准指标：{selected_metric}？")
            c1, c2 = st.columns(2)
            if c1.button("确认删除", type="primary"):
                updated = dict(rules)
                updated.pop(selected_metric, None)
                ok, msg = save_rules(updated)
                if ok:
                    st.success(msg)
                    st.session_state.pop(f"confirm_delete_{selected_metric}", None)
                    st.rerun()
                else:
                    st.error(msg)
            if c2.button("取消"):
                st.session_state.pop(f"confirm_delete_{selected_metric}", None)
                st.rerun()

    st.divider()
    st.subheader("规则库整体校验 / 导出")
    errs = validate_rule_dict(rules)
    if errs:
        st.error(f"发现 {len(errs)} 个问题")
        st.code("\n".join(errs[:100]))
    else:
        st.success("当前规则库通过结构与别名冲突校验。")

    st.download_button(
        "下载当前 metric_aliases.json",
        data=json.dumps(rules, ensure_ascii=False, indent=2),
        file_name="metric_aliases.json",
        mime="application/json",
    )


# -----------------------------------------------------------------------------
# PDF project
# -----------------------------------------------------------------------------

elif page == "研究定义与表族":
    st.title("研究定义与表族 Registry")
    st.caption("指标语义、采集表族和研究版本分层维护；保存后无需为新研究目标改写解析器。")
    service = BACKEND.research_definition_service
    tabs = st.tabs(["Research Definitions", "Table Families", "Metric ↔ Family", "Discovery Strategies", "Knowledge Library", "导入/导出"])
    with tabs[0]:
        definitions = service.definitions()
        st.dataframe(pd.DataFrame([{k: row.get(k) for k in ("definition_id", "display_name", "definition_version", "status", "created_at")} for row in definitions]), use_container_width=True, hide_index=True)
        template = {"definition_id": "CUSTOM_PORTFOLIO_V1", "display_name": "投资组合", "definition_version": "CUSTOM_PORTFOLIO_V1", "table_families": ["investment_portfolio"], "research_scope": {"core_members": ["portfolio_by_category", "portfolio_by_measurement"], "optional_members": [], "excluded_members": []}}
        raw = st.text_area("新增 Research Definition（JSON）", value=json.dumps(template, ensure_ascii=False, indent=2), key="v67_definition_json", height=220)
        if st.button("保存为新 Definition Version", key="v67_save_definition"):
            try:
                created = service.create_definition(json.loads(raw), actor="STREAMLIT")
                st.success(f"已保存：{created['definition_id']}")
            except Exception as exc: st.exception(exc)
        if definitions:
            selected = st.selectbox("复制已有版本", [x["definition_id"] for x in definitions], key="v67_clone_source")
            new_version = st.text_input("新版本 ID", key="v67_clone_version")
            if st.button("复制为新版本", key="v67_clone_definition", disabled=not new_version.strip()):
                try: st.success(f"已复制：{service.clone_definition(selected, new_version.strip())['definition_id']}")
                except Exception as exc: st.exception(exc)
            if st.button("归档选中的 Definition（不影响历史批次）", key="v67_archive_definition"):
                try:
                    service.archive_definition(selected, actor="STREAMLIT")
                    st.success(f"已归档：{selected}")
                    st.rerun()
                except Exception as exc: st.exception(exc)
    with tabs[1]:
        families = service.families()
        st.dataframe(pd.DataFrame([{**{k: row.get(k) for k in ("family_id", "display_name", "definition_version", "discovery_strategy")}, "members": len(service.members(row["family_id"]))} for row in families]), use_container_width=True, hide_index=True)
        if families:
            family_id = st.selectbox("查看 Family Members", [x["family_id"] for x in families], key="v67_family_view")
            st.dataframe(pd.DataFrame([{**{k: row.get(k) for k in ("member_id", "display_name", "member_role", "required", "canonical_order")}, "aliases": "；".join(row["payload"].get("aliases", []))} for row in service.members(family_id)]), use_container_width=True, hide_index=True)
            if st.button("归档当前 Family（不影响历史证据）", key="v67_archive_family"):
                try:
                    service.archive_family(family_id, actor="STREAMLIT")
                    st.success(f"已归档：{family_id}")
                    st.rerun()
                except Exception as exc: st.exception(exc)
        with st.expander("新增/更新 Family 或 Member", expanded=False):
            family_payload = st.text_area("Family JSON", value=json.dumps({"family_id":"custom_family","display_name":"自定义表族","definition_version":"CUSTOM_FAMILY_V1","discovery_strategy":"DIRECT_NOTE_TABLE_FAMILY","core_members":[],"optional_members":[],"excluded_members":[]}, ensure_ascii=False, indent=2), key="v67_family_json", height=160)
            if st.button("保存 Family", key="v67_save_family"):
                try: st.success(f"已保存：{service.save_family(json.loads(family_payload), actor='STREAMLIT')['family_id']}")
                except Exception as exc: st.exception(exc)
            member_payload = st.text_area("Member JSON", value=json.dumps({"member_id":"custom_member","display_name":"自定义明细表","member_role":"DIRECT_DISCLOSURE_TABLE","required":True,"canonical_order":1,"aliases":[],"row_signatures":[],"column_signatures":[]}, ensure_ascii=False, indent=2), key="v67_member_json", height=160)
            target_family = st.selectbox("Member 所属 Family", [x["family_id"] for x in service.families()], key="v67_member_family")
            if st.button("保存 Member", key="v67_save_member"):
                try: st.success(f"已保存：{service.save_member(target_family, json.loads(member_payload), actor='STREAMLIT')['member_id']}")
                except Exception as exc: st.exception(exc)
    with tabs[2]:
        with BACKEND.registry.connect() as conn:
            mappings=[dict(row) for row in conn.execute("SELECT metric_id,family_id,member_id,row_path_hint,priority FROM metric_family_mappings WHERE archived=0 ORDER BY priority").fetchall()]
        st.dataframe(pd.DataFrame(mappings), use_container_width=True, hide_index=True)
        st.caption("Metric Registry 负责指标语义；Table Family Registry 负责结构化采集；Mapping 仅说明优先数据来源。")
    with tabs[3]:
        with BACKEND.registry.connect() as conn:
            strategies=[dict(row) for row in conn.execute("SELECT strategy_id,display_name,plugin_key,archived FROM discovery_strategies ORDER BY strategy_id").fetchall()]
        st.dataframe(pd.DataFrame(strategies), use_container_width=True, hide_index=True)
    with tabs[4]:
        stats=service.template_stats()
        st.dataframe(pd.DataFrame(stats), use_container_width=True, hide_index=True)
        st.caption("历史模板仅提供定位/结构候选；页码、附注号和金额均必须重新验证。")
    with tabs[5]:
        definitions=service.definitions()
        if definitions:
            export_id=st.selectbox("导出 Definition", [x["definition_id"] for x in definitions], key="v67_export_definition")
            st.download_button("下载 JSON", json.dumps(service.export_definition(export_id), ensure_ascii=False, indent=2), file_name=f"{export_id}.json", mime="application/json")

elif page == "PDF 项目":
    st.title("PDF 项目")
    uploaded = st.file_uploader(
        "导入财报 PDF",
        type=["pdf"],
        help="支持年报、季报、偿付能力报告等文本型 PDF。扫描页会在报告中标记风险。",
    )

    if uploaded is not None:
        try:
            pdf_path = save_uploaded_pdf(uploaded)
            st.session_state.active_pdf = str(pdf_path)
            st.success(f"已导入并通过基础 PDF 预检：{pdf_path.name}")
            preflight = inspect_pdf_file(pdf_path)
            for w in preflight.get("warnings", []):
                st.warning(w)
        except Exception as exc:
            st.error(f"导入失败：{exc}")
            st.info(
                "请重新从原始来源下载 PDF。不要把浏览器中的登录页、预览页或错误页直接“另存为 .pdf”。"
            )

    existing = sorted(UPLOAD_DIR.glob("*.pdf"), key=lambda p: p.stat().st_mtime, reverse=True)
    if existing:
        current_names = [p.name for p in existing]
        default_idx = 0
        if st.session_state.active_pdf:
            active_name = Path(st.session_state.active_pdf).name
            if active_name in current_names:
                default_idx = current_names.index(active_name)
        chosen = st.selectbox("已导入 PDF", current_names, index=default_idx)
        chosen_path = next(p for p in existing if p.name == chosen)
        if st.button("设为当前 PDF", type="primary"):
            st.session_state.active_pdf = str(chosen_path)
            st.success(f"当前 PDF：{chosen_path.name}")

        c1, c2, c3 = st.columns(3)
        c1.metric("文件大小", f"{chosen_path.stat().st_size / 1024 / 1024:.2f} MB")
        c2.metric("SHA256前12位", file_sha256(chosen_path)[:12])
        c3.metric("导入时间", dt.datetime.fromtimestamp(chosen_path.stat().st_mtime).strftime("%Y-%m-%d %H:%M"))

        preflight = inspect_pdf_file(chosen_path)
        if preflight["errors"]:
            st.error("PDF 预检失败：\n- " + "\n- ".join(preflight["errors"]))
        else:
            st.success("PDF 文件头基础预检通过。")
        for w in preflight.get("warnings", []):
            st.warning(w)

        if preflight.get("pdf_header_offset", 0) and preflight["pdf_header_offset"] > 0:
            if st.button("尝试剥离 PDF 头之前的额外数据"):
                repaired, msg = try_normalize_leading_junk_pdf(chosen_path)
                if repaired:
                    st.session_state.active_pdf = str(repaired)
                    st.success(msg)
                    st.rerun()
                else:
                    st.error(msg)
        with chosen_path.open("rb") as f:
            st.download_button("下载当前 PDF", f.read(), file_name=chosen_path.name, mime="application/pdf")
    else:
        st.info("尚未导入 PDF。")


# -----------------------------------------------------------------------------
# Run extraction
# -----------------------------------------------------------------------------

elif page == "运行提取":
    st.title("运行提取")

    if not st.session_state.active_pdf:
        st.warning("请先在“PDF 项目”导入并选择当前 PDF。")
        st.stop()

    pdf_path = Path(st.session_state.active_pdf)
    rules = load_rules()

    c1, c2 = st.columns([2, 1])
    selected_metrics = c1.multiselect(
        "从 L0 字典选择指标",
        options=list(rules.keys()),
        default=[
            x for x in ["营业收入", "净利润", "归母净利润", "保险合同负债"]
            if x in rules
        ],
    )
    extra_metrics_txt = c1.text_area(
        "额外自由输入指标（每行一个）",
        placeholder="核心偿付能力\n总保费\n风险综合评级",
        help="用于测试字典盲区。未映射项会显示 UNRESOLVED/RULE GAP，供后续加入 L0。",
    )
    llm_enabled = c2.checkbox("启用 L2 LLM 兜底", value=False)
    provider = c2.selectbox("LLM Provider", ["deepseek", "gemini"])
    model = c2.text_input(
        "模型名（可留空用环境默认）",
        value="",
        placeholder="例如 deepseek-v4-flash / Gemini model",
    )
    api_key = c2.text_input(
        "API Key（仅本次会话）",
        type="password",
        value="",
        help="不会写入规则库或报告。也可提前设置环境变量。",
    )

    parse_mode = c2.selectbox(
        "PDF解析模式",
        ["Fast Index（推荐）", "全页深度解析（兼容模式）"],
        help="Fast Index先快速扫描全文，只深度解析候选页；批量年报建议使用。",
    )
    ocr_label = c2.selectbox(
        "OCR",
        ["关闭", "自动（仅低文本页）", "强制（全部页，慢）"],
        index=0,
        help="自动模式只对低文本/疑似扫描页执行OCR；强制模式适合纯扫描PDF，会明显变慢。",
    )
    ocr_mode = {"关闭": "off", "自动（仅低文本页）": "auto", "强制（全部页，慢）": "force"}[ocr_label]

    extra_metrics = normalize_list_text(extra_metrics_txt)
    metrics = []
    for x in selected_metrics + extra_metrics:
        if x and x not in metrics:
            metrics.append(x)

    st.caption(f"当前 PDF：{pdf_path.name} · 共选择 {len(metrics)} 个指标")

    with st.expander("高级阈值"):
        a, b, c, d = st.columns(4)
        top_k = a.number_input("Top-K候选", min_value=3, max_value=50, value=12)
        high_th = b.number_input("高置信阈值", min_value=0.5, max_value=1.0, value=0.88, step=0.01)
        medium_th = c.number_input("中置信阈值", min_value=0.3, max_value=1.0, value=0.76, step=0.01)
        margin_th = d.number_input("候选margin阈值", min_value=0.0, max_value=0.5, value=0.10, step=0.01)

        e, f, g, h = st.columns(4)
        top_pages_per_metric = e.number_input("每指标候选页", min_value=2, max_value=30, value=8)
        neighbor_radius = f.number_input("候选页邻域 ±", min_value=0, max_value=3, value=1)
        ocr_dpi = g.number_input("OCR DPI", min_value=100, max_value=300, value=150, step=25)
        min_native_chars = h.number_input("自动OCR文本阈值", min_value=0, max_value=500, value=40)
        ocr_language = st.text_input("OCR语言", value="chi_sim+eng", help="需要本机Tesseract安装对应语言包。")

    if st.button("▶ 开始提取", type="primary", use_container_width=True):
        if not metrics:
            st.error("至少选择一个指标。")
            st.stop()

        if llm_enabled and api_key:
            if provider == "deepseek":
                os.environ["DEEPSEEK_API_KEY"] = api_key
            else:
                os.environ["GEMINI_API_KEY"] = api_key

        llm = None
        if llm_enabled:
            try:
                llm = build_llm_provider(provider, model=model.strip() or None)
            except Exception as exc:
                st.error(f"LLM 初始化失败：{exc}")
                st.stop()

        # Hard preflight before invoking pdfplumber/pdfminer.
        preflight = inspect_pdf_file(pdf_path)
        if preflight["errors"]:
            st.error("当前文件未通过 PDF 预检，已停止运行：\n- " + "\n- ".join(preflight["errors"]))
            st.info(
                "处理建议：重新下载原始 PDF；确认文件不是 HTML/登录页；"
                "若文件在浏览器可正常打开，也可用“打印 → 另存为 PDF”生成新的标准 PDF 后再导入。"
            )
            st.stop()

        run_dir = run_dir_for(pdf_path)
        run_dir.mkdir(parents=True, exist_ok=True)

        st.subheader("实时工作状态")
        overall_progress = st.progress(0, text="准备开始…")
        current_work = st.empty()

        pc1, pc2, pc3, pc4 = st.columns(4)
        page_metric = pc1.empty()
        table_metric = pc2.empty()
        fallback_metric = pc3.empty()
        time_metric = pc4.empty()
        page_metric.metric("当前页", "准备中")
        table_metric.metric("表格块", "0")
        fallback_metric.metric("坐标重建块", "0")
        time_metric.metric("运行时间", "0.0s")

        st.caption("实时日志（用于判断程序是在工作、慢页处理，还是已经中止）")
        log_placeholder = st.empty()
        live_logs: list[str] = []
        run_started = time.perf_counter()

        def add_log(message: str) -> None:
            now = dt.datetime.now().strftime("%H:%M:%S")
            live_logs.append(f"[{now}] {message}")
            log_placeholder.code("\n".join(live_logs[-80:]), language="text")

        def fast_index_progress(evt: dict[str, Any]) -> None:
            event = str(evt.get("event", ""))
            message = str(evt.get("message", event))
            elapsed = time.perf_counter() - run_started
            time_metric.metric("运行时间", f"{elapsed:.1f}s")
            total = int(evt.get("total_pages") or 0)
            page_no = int(evt.get("page") or 0)
            if total:
                page_metric.metric("快速索引", f"{page_no}/{total}" if page_no else f"0/{total}")
            if event == "index_cache_hit":
                overall_progress.progress(35, text="命中 Fast Index 缓存")
            elif event == "index_start":
                overall_progress.progress(2, text="开始 Fast Index")
            elif event == "index_page_done" and total:
                pct = 2 + int(33 * page_no / total)
                overall_progress.progress(min(pct, 35), text=f"快速索引 {page_no}/{total}")
            elif event == "ocr_start":
                current_work.warning(message)
            elif event == "index_done":
                overall_progress.progress(35, text="Fast Index 完成，召回候选页")
            current_work.info(message)
            if event in {"index_cache_hit", "index_start", "index_page_done", "ocr_start", "index_done"}:
                add_log(message)

        def pdf_progress(evt: dict[str, Any]) -> None:
            event = str(evt.get("event", ""))
            message = str(evt.get("message", event))
            elapsed = time.perf_counter() - run_started
            time_metric.metric("运行时间", f"{elapsed:.1f}s")

            total = int(evt.get("total_pages") or 0)
            page_no = int(evt.get("page") or 0)
            tables = int(evt.get("table_blocks") or 0)
            fallback = int(evt.get("fallback_row_blocks") or 0)

            if total:
                page_metric.metric("当前页", f"{page_no}/{total}" if page_no else f"0/{total}")
            table_metric.metric("表格块", str(tables))
            fallback_metric.metric("坐标重建块", str(fallback))

            if event == "open_start":
                overall_progress.progress(1, text="打开 PDF 文档结构")
            elif event == "open_done":
                overall_progress.progress(3, text=f"PDF 已打开，共 {total} 页")
            elif event == "page_start" and total:
                pct = 3 + int(64 * max(page_no - 1, 0) / total)
                overall_progress.progress(min(pct, 67), text=f"解析第 {page_no}/{total} 页")
            elif event == "page_done" and total:
                pct = 3 + int(64 * page_no / total)
                overall_progress.progress(min(pct, 67), text=f"第 {page_no}/{total} 页完成")
                sec = float(evt.get("page_seconds") or 0)
                if sec >= 15:
                    message += f" ⚠ 本页耗时较长（{sec:.1f}s）"
            elif event == "done":
                overall_progress.progress(70, text="PDF 解析完成，准备解析指标")

            current_work.info(message)

            if event in {
                "open_start", "open_done", "page_start", "page_text_done",
                "page_tables_done", "fallback_start", "page_done", "done",
            }:
                add_log(message)

        try:
            add_log(f"开始处理文件：{pdf_path.name}")
            fast_meta = None
            if parse_mode.startswith("Fast Index"):
                add_log("阶段 1/4：Fast Index → 候选页召回 → 候选页深度解析")
                blocks, fast_meta, holder = prepare_fast_blocks(
                    pdf_path=pdf_path,
                    metrics=metrics,
                    rules_path=Path(st.session_state.rules_path),
                    cache_root=CACHE_DIR,
                    ocr_mode=ocr_mode,
                    ocr_language=ocr_language,
                    ocr_dpi=int(ocr_dpi),
                    min_native_chars=int(min_native_chars),
                    top_pages_per_metric=int(top_pages_per_metric),
                    neighbor_radius=int(neighbor_radius),
                    index_progress_callback=fast_index_progress,
                    deep_progress_callback=pdf_progress,
                )
                sha = fast_meta["index"]["pdf_sha256"]
                raw_deep = fast_meta["deep"].get("raw_deep_stats") or {}
                stats = {
                    "pages": int(fast_meta["index"]["total_pages"]),
                    "pages_with_text": None,
                    "pages_with_tables": raw_deep.get("pages_with_tables", 0),
                    "table_blocks": sum(1 for b in blocks if b.source_method == "pdfplumber_table"),
                    "fallback_row_blocks": sum(1 for b in blocks if b.source_method in {"coordinate_rows", "pymupdf_ocr_words"}),
                    "likely_scanned_pages": [
                        r.page for r in holder["records"]
                        if r.source in {"ocr", "native_text_ocr_failed"}
                    ],
                    "fast_index": fast_meta,
                }
                add_log(
                    f"Fast Index完成：全文 {stats['pages']}页；候选深度页 "
                    f"{len(fast_meta['selected_pages'])}；索引缓存={fast_meta['index'].get('cache_hit')}; "
                    f"深度缓存命中={fast_meta['deep'].get('deep_cache_hits',0)}"
                )
            else:
                add_log("阶段 1/4：全页深度解析（兼容模式）")
                blocks, stats = extract_pdf_blocks(pdf_path, progress_callback=pdf_progress)
                sha = file_sha256(pdf_path)
                add_log(
                    f"全页解析完成：{stats['pages']}页；结构化表格块={stats['table_blocks']}；"
                    f"坐标重建块={stats['fallback_row_blocks']}"
                )
            add_log("阶段 2/4：逐指标执行 L0/L1/L2 解析")
            overall_progress.progress(70, text="开始逐指标解析")

            results = []
            for i, metric in enumerate(metrics, start=1):
                current_work.info(f"正在处理指标：{metric} ({i}/{len(metrics)})")
                add_log(f"指标 {i}/{len(metrics)}：{metric} — 开始")
                res = resolve_metric(
                    pdf_path=pdf_path,
                    sha=sha,
                    blocks=blocks,
                    rulebook=RuleBook(Path(st.session_state.rules_path)),
                    metric_input=metric,
                    user_aliases=[],
                    llm=llm,
                    top_k=int(top_k),
                    high_threshold=float(high_th),
                    medium_threshold=float(medium_th),
                    margin_threshold=float(margin_th),
                )
                results.append(res)
                overall_progress.progress(
                    min(90, 70 + int(20 * i / len(metrics))),
                    text=f"{metric}: {res.status}",
                )
                selected_label = res.selected.label if res.selected else "-"
                selected_page = res.selected.page if res.selected else "-"
                add_log(
                    f"指标 {metric} — {res.status} · {res.layer} · "
                    f"conf={res.confidence:.3f} · p.{selected_page} · {selected_label}"
                )

            add_log("阶段 3/4：写入 results.json 与 audit.jsonl")
            overall_progress.progress(92, text="写入机器结果与审计日志")

            payload = {
                "source_file": str(pdf_path),
                "file_sha256": sha,
                "extraction_stats": stats,
                "results": [r.to_dict() for r in results],
                "run_config": {
                    "metrics": metrics,
                    "llm_enabled": llm_enabled,
                    "provider": provider if llm_enabled else None,
                    "model": model if llm_enabled else None,
                    "parse_mode": parse_mode,
                    "ocr_mode": ocr_mode,
                    "ocr_language": ocr_language if ocr_mode != "off" else None,
                },
            }
            (run_dir / "results.json").write_text(
                json.dumps(payload, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )

            audit_path = run_dir / "audit.jsonl"
            with audit_path.open("w", encoding="utf-8") as f:
                for r in results:
                    f.write(json.dumps({
                        "timestamp": dt.datetime.now().astimezone().isoformat(timespec="seconds"),
                        **r.to_dict(),
                    }, ensure_ascii=False) + "\n")

            add_log("阶段 4/4：生成人工 HTML / Markdown 报告")
            overall_progress.progress(96, text="生成人工报告")
            (run_dir / "report.md").write_text(
                generate_markdown(pdf_path, stats, results), encoding="utf-8"
            )
            (run_dir / "report.html").write_text(
                generate_html(pdf_path, stats, results), encoding="utf-8"
            )

            elapsed_total = time.perf_counter() - run_started
            add_log(f"全部完成，总耗时 {elapsed_total:.1f}s")
            (run_dir / "activity.log").write_text(
                "\n".join(live_logs) + "\n", encoding="utf-8"
            )

            st.session_state.active_run_dir = str(run_dir)
            st.session_state.last_results = payload
            st.session_state.last_stats = stats
            st.session_state.last_sha = sha
            overall_progress.progress(100, text=f"完成 · 总耗时 {elapsed_total:.1f}s")
            current_work.success(f"提取完成：{run_dir.name}")
            st.success(
                f"运行完成：{stats['pages']} 页 · {len(metrics)} 个指标 · "
                f"总耗时 {elapsed_total:.1f}s"
            )
            st.dataframe(result_summary_df(payload), use_container_width=True, hide_index=True)
        except Exception as exc:
            elapsed_total = time.perf_counter() - run_started
            add_log(f"ERROR：{type(exc).__name__}: {exc}")
            try:
                (run_dir / "activity.log").write_text(
                    "\n".join(live_logs) + "\n", encoding="utf-8"
                )
            except Exception:
                pass
            overall_progress.progress(100, text=f"运行中止 · 已运行 {elapsed_total:.1f}s")
            current_work.error("任务已中止，请查看下方错误与 activity.log。")
            message = str(exc)
            if "No /Root object" in message or "Is this really a PDF" in message:
                st.error(
                    "PDF 解析器无法读取文档结构（缺少 /Root）。这通常表示文件损坏、下载不完整，"
                    "或实际内容不是 PDF。"
                )
                st.info(
                    "优先重新下载原始文件。若浏览器/Adobe 能打开但程序不能，可尝试“打印 → 另存为 PDF”"
                    "重新生成标准 PDF，再导入工作台。"
                )
            else:
                st.error(f"运行失败：{exc}")
            with st.expander("错误详情"):
                st.code(traceback.format_exc())


# -----------------------------------------------------------------------------
# Batch project
# -----------------------------------------------------------------------------

elif page == "批量项目":
    st.title("多 PDF 批量项目")
    st.caption(
        "Fast Index → 候选页深度解析 → 页级缓存 → 多进程并行 → 长表/宽表/Excel。"
        "第二次处理相同PDF会复用索引与已解析候选页。"
    )

    uploaded_batch = st.file_uploader(
        "一次选择多份 PDF",
        type=["pdf"],
        accept_multiple_files=True,
        key="batch_uploader",
    )

    batch_paths: list[Path] = []
    if uploaded_batch:
        for up in uploaded_batch:
            try:
                p = save_uploaded_pdf(up)
                batch_paths.append(p)
            except Exception as exc:
                st.error(f"{up.name}: {exc}")

    existing = sorted(UPLOAD_DIR.glob("*.pdf"), key=lambda p: p.name)
    existing_names = [p.name for p in existing]
    selected_existing = st.multiselect(
        "也可从已导入 PDF 选择",
        existing_names,
        default=[],
    )
    for name in selected_existing:
        p = next(x for x in existing if x.name == name)
        if p not in batch_paths:
            batch_paths.append(p)

    if not batch_paths:
        st.info("请上传或选择至少一份 PDF。")
    else:
        st.subheader("文档元数据")
        meta_rows = []
        for p in batch_paths:
            company, year = infer_company_year(p, "")
            meta_rows.append({"pdf_name": display_pdf_name(p.name), "storage_name": p.name, "company": company, "year": year})
        meta_df = pd.DataFrame(meta_rows)
        edited_meta = st.data_editor(
            meta_df,
            use_container_width=True,
            hide_index=True,
            disabled=["pdf_name", "storage_name"],
            key="batch_meta_editor",
        )

        rules = load_rules()
        default_metrics = [
            x for x in [
                "总保费", "净利润", "归母净利润",
                "核心偿付能力充足率", "综合偿付能力充足率",
                "新业务价值", "权益类投资资产占比",
            ] if x in rules
        ]
        metrics = st.multiselect(
            "批量提取指标",
            options=list(rules.keys()),
            default=default_metrics,
            key="batch_metrics",
        )

        c1, c2, c3, c4 = st.columns(4)
        workers = c1.number_input(
            "并行进程数",
            min_value=1,
            max_value=max(1, min(8, os.cpu_count() or 4)),
            value=min(2, max(1, os.cpu_count() or 2)),
        )
        ocr_label_b = c2.selectbox(
            "OCR",
            ["关闭", "自动（仅低文本页）", "强制（全部页，慢）"],
            index=0,
            key="batch_ocr",
        )
        ocr_mode_b = {"关闭": "off", "自动（仅低文本页）": "auto", "强制（全部页，慢）": "force"}[ocr_label_b]
        top_pages_b = c3.number_input("每指标候选页", 2, 30, 8, key="batch_top_pages")
        neighbor_b = c4.number_input("候选页邻域 ±", 0, 3, 1, key="batch_neighbor")

        d1, d2, d3 = st.columns(3)
        ocr_language_b = d1.text_input("OCR语言", "chi_sim+eng", key="batch_ocr_lang")
        ocr_dpi_b = d2.number_input("OCR DPI", 100, 300, 150, 25, key="batch_ocr_dpi")
        min_chars_b = d3.number_input("自动OCR文本阈值", 0, 500, 40, key="batch_min_chars")

        st.markdown("#### L2 语义裁决（可选）")
        l21, l22, l23 = st.columns(3)
        batch_llm_enabled = l21.checkbox(
            "启用批量 L2",
            value=False,
            help="仅在L1无法唯一确定候选时调用。LLM只能在预提取候选ID中选择或放弃，不能生成财务金额。",
            key="batch_llm_enabled",
        )
        batch_llm_provider = l22.selectbox(
            "Provider",
            ["deepseek", "gemini"],
            key="batch_llm_provider",
            disabled=not batch_llm_enabled,
        )
        batch_llm_model = l23.text_input(
            "模型名（可留空）",
            value="",
            key="batch_llm_model",
            disabled=not batch_llm_enabled,
        )
        batch_api_key = st.text_input(
            "批量 L2 API Key（仅当前会话）",
            type="password",
            value="",
            key="batch_llm_key",
            disabled=not batch_llm_enabled,
        )

        if batch_llm_enabled:
            st.info(
                "批量 L2 会在各PDF工作进程内对模糊候选进行 bounded-choice 裁决。"
                "为避免API限流/成本突增，建议并行进程数先设为 1–2。"
            )

        if ocr_mode_b == "force":
            st.warning("强制 OCR 会显著降低速度，只建议用于纯扫描 PDF。")

        if st.button("▶ 开始批量提取", type="primary", use_container_width=True):
            if not metrics:
                st.error("请选择至少一个指标。")
                st.stop()

            if batch_llm_enabled and batch_api_key:
                if batch_llm_provider == "deepseek":
                    os.environ["DEEPSEEK_API_KEY"] = batch_api_key
                else:
                    os.environ["GEMINI_API_KEY"] = batch_api_key

            stamp = dt.datetime.now().strftime("%Y%m%d_%H%M%S")
            batch_run = BATCH_DIR / f"batch_{stamp}"
            batch_run.mkdir(parents=True, exist_ok=True)

            meta_map = {
                str(row.get("storage_name") or row.get("pdf_name")): {
                    "company": row["company"],
                    "year": row["year"],
                }
                for _, row in edited_meta.iterrows()
            }
            jobs = []
            for p in batch_paths:
                meta = meta_map.get(p.name, {})
                jobs.append({
                    "pdf_path": str(p),
                    "rules_path": str(Path(st.session_state.rules_path)),
                    "cache_root": str(CACHE_DIR),
                    "metrics": metrics,
                    "company": meta.get("company", ""),
                    "year": str(meta.get("year", "")),
                    "ocr_mode": ocr_mode_b,
                    "ocr_language": ocr_language_b,
                    "ocr_dpi": int(ocr_dpi_b),
                    "min_native_chars": int(min_chars_b),
                    "top_pages_per_metric": int(top_pages_b),
                    "neighbor_radius": int(neighbor_b),
                    "llm_enabled": bool(batch_llm_enabled),
                    "llm_provider": batch_llm_provider if batch_llm_enabled else None,
                    "llm_model": batch_llm_model.strip() if batch_llm_enabled else None,
                })

            progress = st.progress(0, text="批量任务准备中")
            status = st.empty()
            st.markdown("#### 各 PDF 实时进度")
            progress_table = st.empty()
            log = st.empty()
            logs: list[str] = []
            started = time.perf_counter()

            doc_state: dict[str, dict[str, Any]] = {
                p.name: {
                    "PDF": display_pdf_name(p.name),
                    "阶段": "等待",
                    "进度": 0,
                    "当前工作": "",
                    "已完成指标": f"0/{len(metrics)}",
                    "状态": "PENDING",
                }
                for p in batch_paths
            }

            def render_batch_state() -> None:
                rows = list(doc_state.values())
                progress_table.dataframe(
                    pd.DataFrame(rows),
                    use_container_width=True,
                    hide_index=True,
                )
                overall = (
                    sum(float(r.get("进度", 0)) for r in rows) / len(rows)
                    if rows else 0
                )
                progress.progress(
                    min(100, int(overall)),
                    text=f"批量总体进度 {overall:.1f}%"
                )

            def push_log(msg: str) -> None:
                now = dt.datetime.now().strftime("%H:%M:%S")
                logs.append(f"[{now}] {msg}")
                log.code("\n".join(logs[-120:]), language="text")

            render_batch_state()

            def batch_progress(evt: dict[str, Any]) -> None:
                event = str(evt.get("event", ""))
                name = str(evt.get("pdf_name") or "")
                if event == "job_done":
                    result = evt["result"]
                    name = str(result.get("pdf_name", name or "-"))
                    err = result.get("error")
                    elapsed_doc = result.get("elapsed_seconds", "-")
                    s = doc_state.setdefault(name, {"PDF": name})
                    s.update({
                        "阶段": "完成" if not err else "失败",
                        "进度": 100,
                        "当前工作": f"{elapsed_doc}s" if not err else str(err),
                        "已完成指标": f"{len(metrics)}/{len(metrics)}" if not err else s.get("已完成指标", "-"),
                        "状态": "DONE" if not err else "ERROR",
                    })
                    push_log(
                        f"{name} · {'DONE' if not err else 'ERROR'} · "
                        f"{elapsed_doc}s" + (f" · {err}" if err else "")
                    )
                    render_batch_state()
                    return

                if not name:
                    return

                s = doc_state.setdefault(name, {
                    "PDF": display_pdf_name(name), "阶段": "", "进度": 0,
                    "当前工作": "", "已完成指标": f"0/{len(metrics)}", "状态": "RUNNING",
                })
                if s.get("状态") in {"DONE", "ERROR"}:
                    return
                s["状态"] = "RUNNING"

                if event == "worker_start":
                    s.update({"阶段": "启动", "进度": 1, "当前工作": evt.get("message", "任务开始")})

                elif event == "worker_index":
                    p = evt.get("payload") or {}
                    pe = str(p.get("event", ""))
                    page_no = int(p.get("page") or 0)
                    total_pages = int(p.get("total_pages") or 0)
                    if pe == "index_cache_hit":
                        s.update({"阶段": "Fast Index缓存", "进度": 35, "当前工作": "命中索引缓存"})
                    elif pe == "ocr_start":
                        s.update({"阶段": "OCR", "当前工作": str(p.get("message", "OCR"))})
                    elif pe == "index_page_done" and total_pages:
                        pct = 3 + 32 * page_no / total_pages
                        s.update({
                            "阶段": "Fast Index",
                            "进度": round(pct, 1),
                            "当前工作": f"{page_no}/{total_pages} · {p.get('source','')}",
                        })
                    elif pe == "index_done":
                        s.update({"阶段": "候选页召回", "进度": 35, "当前工作": "Fast Index完成"})

                elif event == "worker_deep":
                    p = evt.get("payload") or {}
                    pe = str(p.get("event", ""))
                    selected_idx = int(p.get("selected_index") or 0)
                    requested = int(p.get("total_pages") or p.get("requested_pages") or 0)
                    pdf_page = int(p.get("page") or 0)
                    if pe == "open_done":
                        requested = int(p.get("requested_pages") or requested or 0)
                        s.update({
                            "阶段": "候选页深度解析",
                            "进度": 38,
                            "当前工作": f"需深度解析 {requested} 页",
                        })
                    elif pe in {"page_start", "page_done"} and requested:
                        idx = selected_idx or min(requested, max(1, selected_idx))
                        pct = 38 + 37 * idx / requested
                        s.update({
                            "阶段": "候选页深度解析",
                            "进度": round(min(75, pct), 1),
                            "当前工作": f"PDF第 {pdf_page} 页 · {idx}/{requested}",
                        })
                    elif pe == "done":
                        s.update({"阶段": "指标解析", "进度": 75, "当前工作": "候选页解析完成"})

                elif event == "worker_metric_start":
                    mi = int(evt.get("metric_index") or 0)
                    mt = int(evt.get("metric_total") or len(metrics))
                    metric_name = str(evt.get("metric") or "")
                    pct = 75 + 20 * max(0, mi - 1) / max(1, mt)
                    s.update({
                        "阶段": "L0/L1/L2",
                        "进度": round(pct, 1),
                        "当前工作": f"{mi}/{mt} · {metric_name}",
                        "已完成指标": f"{max(0, mi-1)}/{mt}",
                    })

                elif event == "worker_metric_done":
                    mi = int(evt.get("metric_index") or 0)
                    mt = int(evt.get("metric_total") or len(metrics))
                    pct = 75 + 20 * mi / max(1, mt)
                    s.update({
                        "阶段": "L0/L1/L2",
                        "进度": round(pct, 1),
                        "当前工作": (
                            f"{evt.get('metric','')} · {evt.get('status','')} / "
                            f"{evt.get('layer','')} · p.{evt.get('page','-')}"
                        ),
                        "已完成指标": f"{mi}/{mt}",
                    })
                    push_log(f"{name} · {s['当前工作']}")

                elif event == "worker_done":
                    s.update({"阶段": "写入结果", "进度": 98, "当前工作": "Worker完成，等待汇总"})

                render_batch_state()
                status.info(f"{name}：{s.get('阶段')} · {s.get('当前工作')}")

            results = run_batch_jobs(
                jobs,
                max_workers=int(workers),
                progress_callback=batch_progress,
            )
            (batch_run / "batch_activity.log").write_text(
                "\n".join(logs) + "\n",
                encoding="utf-8",
            )
            try:
                long_df, wide_df = write_batch_artifacts(batch_run, results)
            except Exception as exc:
                st.error(f"批量报告/审计输出失败：{exc}")
                long_df, wide_df = aggregate_batch_results(results)

            st.session_state.active_batch_run_dir = str(batch_run)
            elapsed = time.perf_counter() - started
            st.success(f"批量任务完成：{len(batch_paths)}份PDF · {len(metrics)}个指标 · {elapsed:.1f}s")
            st.subheader("最终裁决宽表预览")
            st.dataframe(wide_df, use_container_width=True, hide_index=True)
            st.subheader("最终裁决长表预览")
            st.dataframe(long_df, use_container_width=True, hide_index=True)

            if (batch_run / "batch_results.xlsx").exists():
                st.download_button(
                    "下载 Excel 汇总",
                    data=(batch_run / "batch_results.xlsx").read_bytes(),
                    file_name="batch_results.xlsx",
                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                )
            st.download_button(
                "下载宽表 CSV",
                data=(batch_run / "batch_wide.csv").read_bytes(),
                file_name="batch_wide.csv",
                mime="text/csv",
            )
            st.download_button(
                "下载长表 CSV",
                data=(batch_run / "batch_long.csv").read_bytes(),
                file_name="batch_long.csv",
                mime="text/csv",
            )
            if (batch_run / "batch_report.html").exists():
                st.download_button(
                    "下载批量 HTML 报告",
                    data=(batch_run / "batch_report.html").read_bytes(),
                    file_name="batch_report.html",
                    mime="text/html",
                )
            if (batch_run / "audit.jsonl").exists():
                st.download_button(
                    "下载批量审计日志",
                    data=(batch_run / "audit.jsonl").read_bytes(),
                    file_name="audit.jsonl",
                    mime="application/jsonl",
                )


# -----------------------------------------------------------------------------
# Human review
# -----------------------------------------------------------------------------

elif page == "抓取中心":
    render_capture_center(
        st, BACKEND,
        sorted(UPLOAD_DIR.glob("*.pdf"), key=lambda p: p.stat().st_mtime, reverse=True),
    )

elif page == "审核收件箱":
    render_review_inbox(st, BACKEND)

elif page == "逻辑资产工作区":
    render_asset_workspace(st, BACKEND)

elif page == "整表批量工作台":
    st.title("整表批量工作台")
    st.caption(f"{APP_VERSION}：批量抓取、通用主表引导发现、审核认证和持久化作业。每个 PDF × 目标表都是独立审计作业。")
    pdfs = sorted(UPLOAD_DIR.glob("*.pdf"), key=lambda p: p.stat().st_mtime, reverse=True)
    if not pdfs:
        st.info("请先在“PDF 项目”导入至少一份 PDF。")
        st.stop()
    selected_pdfs = render_pdf_selection_workspace(pdfs, key_prefix="v63_batch")
    from guided_workflow_ui import render_guided_capture
    render_guided_capture(st, BACKEND, selected_pdfs, __import__("pdf_selection_workspace").infer_pdf_dimensions)
    st.divider()
    st.subheader("手工 / 高级抓取（与研究引导流程独立）")
    st.caption("仅在已知目标表名、页码或需要旧版表族工作流时使用；不要在完成认证计划后回到这里重复选择目标。")
    mode = st.radio("抓取目标", ["内置表族", "自定义多表"], horizontal=True, key="v62_family_mode")
    if mode == "内置表族":
        family_id = st.selectbox("表族", list(BUILTIN_TABLE_FAMILIES), format_func=lambda x: BUILTIN_TABLE_FAMILIES[x].display_name)
        family = BUILTIN_TABLE_FAMILIES[family_id]
        st.caption("目标表：" + "、".join(f"{x.name}（{x.role}）" for x in family.targets))
    else:
        family_name = st.text_input("表族名称", value="自定义表族", key="v62_family_name")
        targets_text = st.text_area("目标表名（每行一个；可加 |角色，例如：投资收益|INVESTMENT_COMPONENT）", value="", key="v62_targets")
        raw_targets = []
        for line in targets_text.splitlines():
            name, _, role = line.partition("|")
            if name.strip(): raw_targets.append({"name": name.strip(), "role": role.strip() or "COMPONENT"})
        family = build_family("CUSTOM_" + re.sub(r"\\W+", "_", family_name).upper(), family_name, raw_targets) if raw_targets else None
    c1, c2, c3 = st.columns(3)
    batch_id = c1.text_input("批次 ID", value=st.session_state.get("v62_batch_id", new_batch_id()), key="v62_batch_id")
    workers = c2.number_input("并发 Worker", min_value=1, max_value=8, value=3, step=1, help="默认 3；PDF 解析与写盘较重，避免无限并发。")
    max_pages = c3.number_input("最大保护页数", min_value=1, max_value=30, value=8, step=1)
    parser = st.selectbox("表头算法", ["AUTO", "ABSOLUTE_YEAR_CLASSIC", "GENERALIZED_PERIOD_V57"], key="v62_parser")
    note_number = st.text_input("附注编号（可选，所有任务共用）", key="v62_note")
    _v63_summary = __import__("pdf_selection_workspace").selection_summary(selected_pdfs)
    st.info(f"提交摘要：{_v63_summary.pdf_count} 份 PDF · {_v63_summary.company_count} 家公司 · 年份 {_v63_summary.year_range} · 目标 {family.display_name if family else '-'} · 并发 {int(workers)}")
    if st.button("创建并启动批量抓取", type="primary", disabled=not selected_pdfs or family is None, use_container_width=True):
        effective_batch=batch_id.strip() or new_batch_id()
        requests=[
            CaptureRequest.new(
                capture_mode=CaptureMode.DIRECT_DISCLOSURE,
                source_pdf_path=str(Path(pdf).resolve()),
                table_family_id=family.display_name,
                member_table_id=target.name,
                request_metadata={
                    "table_query":target.name,"note_number":note_number.strip() or None,
                    "max_pages":int(max_pages),"header_parser_mode":parser,
                    "batch_id":effective_batch,"member_table_role":target.role,
                },
            )
            for pdf in selected_pdfs for target in family.targets
        ]
        jobs = BACKEND.capture_service.submit_batch(
            requests,batch_id=effective_batch,max_workers=int(workers),asynchronous=True
        )
        st.success(f"已创建 {len(jobs)} 个独立作业，正在后台以 {int(workers)} 个 Worker 执行。")
    st.divider()
    monitorable_batches = BACKEND.batch_service.list_monitorable_batches(limit=1000)
    batch_options = [str(row["batch_id"]) for row in monitorable_batches]
    if st.session_state.get("v62_monitor_batch") not in batch_options:
        st.session_state.pop("v62_monitor_batch", None)
    monitor_batch = st.selectbox(
        "监控批次", batch_options,
        index=(batch_options.index(batch_id) if batch_id in batch_options else 0)
        if batch_options else None,
        key="v62_monitor_batch",
    ) if batch_options else None
    if monitor_batch:
        summary = BACKEND.table_capture_runner.monitor(monitor_batch)
        readiness = BACKEND.batch_service.execution_readiness(monitor_batch)
        a, b, c, d, e = st.columns(5)
        a.metric("总作业", readiness["total_jobs"])
        b.metric("执行终止", readiness["terminal_jobs"])
        c.metric("作业需审核", readiness["status_counts"].get("REVIEW_REQUIRED", 0))
        d.metric("有效当前 Capture", readiness["active_current_capture_count"])
        e.metric("失败", readiness["status_counts"].get("FAILED", 0))
        st.progress(summary["progress"])
        if st.button("刷新进度", key="v62_refresh_monitor"): st.rerun()
        if readiness["all_terminal"]:
            review_queue = readiness["review_queue"]
            if review_queue:
                st.warning(
                    f"本批次作业已执行完成，但 {len(review_queue)} 张 Capture 仍需审核后才能合表。"
                )
                batch_review_map={row["capture_id"]:row for row in review_queue}
                batch_review_ids=st.multiselect(
                    "本批次待审核 Capture",list(batch_review_map),
                    default=list(batch_review_map),
                    format_func=lambda capture_id:(
                        f"{batch_review_map[capture_id].get('company_id') or '未知公司'}｜"
                        f"{batch_review_map[capture_id].get('report_year') or ''}｜"
                        f"{batch_review_map[capture_id].get('member_table_id') or ''}"
                    ),
                    key=f"v610_batch_review_ids_{monitor_batch}",
                )
                if st.button(
                    "审核所选 Capture（进入逻辑资产工作区）",
                    type="primary",disabled=not batch_review_ids,
                    key=f"v610_open_batch_review_{monitor_batch}",
                ):
                    queue=[batch_review_map[x] for x in batch_review_ids]
                    first=queue[0]
                    st.session_state["asset_workspace_review_queue"]=queue
                    for key in (
                        "selected_logical_asset_id","selected_capture_version_id",
                        "asset_workspace_review_queue_capture",
                    ):
                        st.session_state.pop(key,None)
                    st.session_state["inspection_route"]={
                        "logical_asset_id":first["logical_asset_id"],
                        "capture_version_id":first["capture_id"],
                        "table_block_id":"","initial_tab":"审核",
                        "return_route":"整表批量工作台","review_queue_item_id":"",
                    }
                    st.session_state["_pending_main_page"]="逻辑资产工作区"
                    st.rerun()
            elif readiness["can_enter_merge"]:
                st.success(
                    "本批次作业已执行终止，且全部有效当前 Capture 已通过正式合表资格门禁。"
                )
                if readiness["non_blocking_warning_count"]:
                    st.warning(
                        f"保留 {readiness['non_blocking_warning_count']} 条非阻断 warning；"
                        "这些证据不会阻断合表。"
                    )
                if st.button("进入合表",key=f"v610_batch_go_merge_{monitor_batch}"):
                    st.session_state["_pending_main_page"]="合表"
                    st.rerun()
            else:
                gate_labels = {
                    "NO_JOBS":"批次没有作业",
                    "JOBS_NOT_TERMINAL":"仍有作业未终止",
                    "FAILED_JOBS":"存在失败作业",
                    "CANCELLED_JOBS":"存在取消作业",
                    "SKIPPED_JOBS":"存在跳过作业",
                    "MISSING_CAPTURE_OUTPUT":"作业缺少已注册 Capture 产物",
                    "DUPLICATE_JOB_CAPTURE_OUTPUT":"多个作业指向同一 Capture 产物",
                    "INACTIVE_OR_HISTORICAL_CAPTURE_OUTPUT":"产物已回收、失效或不是 current version",
                    "NO_ACTIVE_CURRENT_CAPTURE":"没有有效的 current Capture",
                    "BUNDLE_ROOT_NOT_READY":"CaptureBundle 根身份或状态未就绪",
                    "CAPTURE_REVIEW_REQUIRED":"仍有阻断性 Capture 审核任务",
                    "MERGE_ELIGIBILITY_SERVICE_UNAVAILABLE":"正式合表资格服务不可用",
                    "CAPTURE_NOT_MERGE_ELIGIBLE":"至少一个当前根未通过正式合表资格",
                }
                reasons = [
                    gate_labels.get(code, code)
                    for code in readiness["gate_reasons"]
                ]
                st.error("本批次不能进入合表：" + "；".join(reasons))
        if summary["counts"].get("FAILED", 0) and st.button("重试失败作业", key="v62_retry_failed"):
            retries = BACKEND.table_capture_runner.retry_failed(batch_id=monitor_batch, max_workers=int(workers))
            st.success(f"已创建 {len(retries)} 个重试作业。")
        view = [{"job_id": j["job_id"], "状态": j["status"], "进度": j["progress"], "PDF": Path((j.get("payload") or {}).get("pdf_path", "")).name, "目标表": (j.get("payload") or {}).get("table_query"), "角色": (j.get("payload") or {}).get("target_role"), "错误": j.get("error_message", "")} for j in summary["jobs"]]
        st.dataframe(pd.DataFrame(view), use_container_width=True, hide_index=True)

elif page == "发现结果审核":
    from guided_workflow_ui import render_review_center
    render_review_center(st, BACKEND)

elif page == "发现规则与学习库":
    st.title("发现规则与学习库")
    knowledge = BACKEND.discovery_registry.knowledge_summary(limit=300)
    if knowledge:
        st.dataframe(pd.DataFrame(knowledge), use_container_width=True, hide_index=True)
    else:
        st.info("尚无已认证结构。审核 ACCEPTED/OVERRIDDEN 的发现会在这里形成同公司、同报表类型的快速入口和训练样本。")

elif page == "整表抓取":
    st.title("整表抓取")
    st.caption(
        "v6.1 保留 v5.9 双表头专家与 v6.0 生命周期，并新增 SQLite Metadata Registry + Service/Repository Layer。"
        "独立数值列裁判自动择优，机器完整抓取永久保留。"
    )

    pdfs = sorted(UPLOAD_DIR.glob("*.pdf"), key=lambda p: p.stat().st_mtime, reverse=True)
    if not pdfs:
        st.info("请先在“PDF 项目”导入至少一份 PDF。")
        st.stop()

    pdf_names = [display_pdf_name(p.name) for p in pdfs]
    default_idx = 0
    if st.session_state.active_pdf:
        active = Path(st.session_state.active_pdf)
        for i, p in enumerate(pdfs):
            if p.resolve() == active.resolve():
                default_idx = i
                break

    chosen_display = st.selectbox(
        "选择 PDF",
        pdf_names,
        index=default_idx,
        key="table_capture_pdf",
    )
    chosen_pdf = pdfs[pdf_names.index(chosen_display)]

    c1, c2 = st.columns([2, 1])
    table_query = c1.text_input(
        "目标表 / 附注名称",
        value="业务及管理费和其他业务成本",
        help="例如：业务及管理费和其他业务成本、投资资产分类及收益、保险合同负债变动。",
    )
    note_number = c2.text_input(
        "附注编号（可选）",
        value="",
        help=(
            "通常无需填写。系统会从实际定位标题（如“34. 业务及管理费”）自动反推编号，"
            "再寻找下一附注建立硬结束边界；仅在自动识别失败时手工指定。"
        ),
    )

    c3, c4 = st.columns(2)
    start_override_text = c3.text_input(
        "起始 PDF 页（可选）",
        value="",
        help="留空则自动搜索；PDF页码从1开始。",
    )
    max_pages = c4.number_input(
        "最大保护页数",
        min_value=1,
        max_value=30,
        value=8,
        step=1,
        help="只有找不到下一附注硬边界时才作为保护上限；这类结果会进入边界待复核。",
    )

    parser_mode_label = st.selectbox(
        "表头算法模式",
        [
            "AUTO — 双算法并行 + 独立裁判（推荐）",
            "ABSOLUTE_YEAR_CLASSIC — 传统绝对年份专家",
            "GENERALIZED_PERIOD_V57 — 本年/去年/复杂期间专家",
        ],
        index=0,
        help=(
            "AUTO 会同时运行 Classic 与 v5.7 Generalized，使用数值列聚类、scope基数和维度唯一性裁判。"
            "人工指定模式用于复核/对照，不会混拼两个算法的部分结果。"
        ),
        key="table_header_parser_mode",
    )
    parser_mode = (
        "AUTO"
        if parser_mode_label.startswith("AUTO")
        else parser_mode_label.split(" — ", 1)[0]
    )

    def _generate_table_capture_batch_id() -> None:
        # Streamlit forbids mutating a widget-bound Session State key after that
        # widget has been instantiated in the same script run. A button callback
        # runs before the next top-to-bottom rerun, so updating the text_input key
        # here is safe and immediately reflected on the rerun.
        st.session_state["table_capture_batch_id"] = new_batch_id()

    b1, b2 = st.columns([4, 1])
    batch_label = b1.text_input(
        "整表抓取批次ID/标签（可选）",
        key="table_capture_batch_id",
        placeholder="例如：2024年报_业务及管理费_第一批；留空则本次作为独立批次",
        help="连续抓取同一批PDF时使用相同批次ID，之后可在数据资产管理中整批废除/重跑。",
    )
    b2.button(
        "生成新批次ID",
        use_container_width=True,
        key="new_table_capture_batch",
        on_click=_generate_table_capture_batch_id,
    )

    with st.expander("v6.1 双表头算法与资产批次契约", expanded=False):
        st.code(
            """表头算法层
ABSOLUTE_YEAR_CLASSIC     = 2025/2024/已重述等传统年份表
GENERALIZED_PERIOD_V57   = 本年/去年/本期等复杂期间表
AUTO                     = 双算法并行 + 独立数值列/层级裁判

机器审计层（永不被人工裁决覆盖）
machine_capture_full_long.csv
machine_capture_full_wide.csv

正式输出层（供研究/合表）
table_raw_long.csv
table_raw_wide.csv
table_item_dictionary.csv

边界状态
HARD_BOUNDARY_CONFIRMED = 自动找到可靠下一附注硬边界
HUMAN_CONFIRMED        = 人工在输出结果中确认最后有效记录
REVIEW_REQUIRED        = 必须人工确认边界后再进入正式合表

人工复核不会删除机器完整抓取；
被截断的后续数据保存在 boundary_excluded_rows.csv。""",
            language="text",
        )

    run_capture = st.button(
        "开始整表抓取",
        type="primary",
        use_container_width=True,
        disabled=not bool(table_query.strip()),
    )

    if run_capture:
        try:
            start_override = int(start_override_text.strip()) if start_override_text.strip() else None
        except ValueError:
            st.error("起始 PDF 页必须是整数。")
            st.stop()

        stamp = dt.datetime.now().strftime("%Y%m%dT%H%M%S")
        effective_batch_id = batch_label.strip() or f"SINGLE_CAPTURE_{stamp}"
        source_stem = Path(display_pdf_name(chosen_pdf.name)).stem
        safe_source = re.sub(r'[\\/:*?"<>|]+', "_", source_stem).strip()[:65]
        safe_title = re.sub(r'[\\/:*?"<>|]+', "_", table_query.strip()).strip()[:55]
        note_prefix = f"{note_number.strip()}_" if note_number.strip() else ""
        run_dir = TABLE_CAPTURE_DIR / f"{safe_source}__{note_prefix}{safe_title}__{stamp}"
        run_dir.mkdir(parents=True, exist_ok=True)

        status = st.status("正在定位并解析整表…", expanded=True)
        progress = st.progress(0.0)
        live = st.empty()

        def capture_progress(event: dict[str, Any]) -> None:
            ev = event.get("event", "")
            msg = event.get("message", ev)
            live.write(msg)
            if ev == "open_done":
                progress.progress(0.10)
            elif ev == "page_start":
                total = max(1, int(event.get("total_pages") or 1))
                idx = int(event.get("selected_index") or 1)
                progress.progress(min(0.90, 0.10 + 0.75 * idx / total))
            elif ev == "done":
                progress.progress(0.94)

        try:
            submitted = BACKEND.capture_service.create(
                pdf_path=chosen_pdf,
                table_query=table_query.strip(),
                note_number=note_number.strip() or None,
                start_page_override=start_override,
                max_pages=int(max_pages),
                progress_callback=capture_progress,
                header_parser_mode=parser_mode,
                batch_id=effective_batch_id,
                output_dir=run_dir,
            )
            artifacts = submitted.get("artifacts") or {}
            metadata = submitted.get("metadata") or {}
            result_data = submitted.get("result") or {}
            run_dir = Path(submitted["run_path"])
            progress.progress(1.0)

            boundary_status = result_data.get("boundary_status", "REVIEW_REQUIRED")
            header_status = result_data.get("header_dimension_status", "REVIEW_REQUIRED")
            status.update(
                label=(
                    f"整表抓取完成：PDF p.{result_data.get('start_page')}–{result_data.get('end_page')} · "
                    f"{len(result_data.get('rows') or [])} 行 · 边界={boundary_status} · 表头={header_status} · "
                    f"算法={(result_data.get('stats') or {}).get('header_parser','legacy')}"
                ),
                state="complete",
                expanded=False,
            )
            st.session_state.active_table_capture_dir = str(run_dir)

            st.success(
                f"{metadata.get('display_name')} · 实际表格页："
                + ", ".join(map(str, result_data.get("pages") or []))
            )

            if boundary_status == "REVIEW_REQUIRED":
                st.warning(
                    "该抓取未获得可靠硬结束边界。请在“边界复核”Tab直接查看完整输出并选择最后一条有效记录。"
                )
            if header_status == "REVIEW_REQUIRED":
                st.error(
                    "该抓取存在重复期间/列维度碰撞。请在“表头维度复核”中确认 year / scope / restated；"
                    "完成前不会进入正式合表。"
                )
            for w in result_data.get("warnings") or []:
                st.warning(w)

            tabs = st.tabs([
                "正式宽表",
                "正式长表",
                "边界复核",
                "表头算法裁决",
                "列拓扑复核",
                "表头维度复核",
                "合计/小计复核",
                "细项字典",
                "列结构",
                "机器JSON",
                "下载",
            ])

            with tabs[0]:
                path = run_dir / "table_raw_wide.csv"
                df = pd.read_csv(path) if path.exists() else pd.DataFrame()
                st.dataframe(df, use_container_width=True, hide_index=True)

            with tabs[1]:
                path = run_dir / "table_raw_long.csv"
                df = pd.read_csv(path) if path.exists() else pd.DataFrame()
                st.dataframe(df, use_container_width=True, hide_index=True)

            with tabs[2]:
                boundary_review_widget(run_dir, key_prefix=f"new_{run_dir.name}")

            with tabs[3]:
                header_parser_arbitration_widget(run_dir, key_prefix=f"new_{run_dir.name}")

            with tabs[4]:
                column_topology_review_widget(run_dir, key_prefix=f"new_{run_dir.name}")

            with tabs[5]:
                header_dimension_review_widget(run_dir, key_prefix=f"new_{run_dir.name}")

            with tabs[6]:
                path = run_dir / "table_reconciliation_audit.csv"
                audit = pd.read_csv(path) if path.exists() else pd.DataFrame()
                st.caption(
                    "仅用于结构/算术 Warning：先按 row_type/row_level/parent_section 推断候选子项，"
                    "再验证求和；不会用“凑数”反推成员，也不会自动修改任何金额。"
                )
                if audit.empty:
                    st.info("没有可测试的合计/小计结构。")
                else:
                    warnings = audit[
                        audit["status"].astype(str).str.startswith("WARNING")
                        | audit["status"].astype(str).str.startswith("NOT_TESTABLE")
                    ]
                    if warnings.empty:
                        st.success("当前可测试的合计/小计算术检查未发现 Warning。")
                    else:
                        st.warning(f"发现 {len(warnings)} 条 Warning/不可测试项，请人工核对结构成员。")
                    st.dataframe(audit, use_container_width=True, hide_index=True)

            with tabs[7]:
                path = run_dir / "table_item_dictionary.csv"
                df = pd.read_csv(path) if path.exists() else pd.DataFrame()
                st.caption("跨公司同义细项统一请进入“合表 / Taxonomy”工作区。")
                st.dataframe(df, use_container_width=True, hide_index=True)

            with tabs[8]:
                col_rows = [
                    {
                        "序号": c.ordinal,
                        "原始列索引": c.source_column_index,
                        "年份": c.year,
                        "口径": c.scope,
                        "已重述": c.restated,
                        "原始表头": c.header_raw,
                    }
                    for c in result.columns
                ]
                st.dataframe(pd.DataFrame(col_rows), use_container_width=True, hide_index=True)

            with tabs[9]:
                st.json(json.loads((run_dir / "table_capture_result.json").read_text(encoding="utf-8")))

            with tabs[10]:
                downloads = [
                    ("正式长表 CSV", "table_raw_long.csv", "text/csv"),
                    ("正式宽表 CSV", "table_raw_wide.csv", "text/csv"),
                    ("细项字典 CSV", "table_item_dictionary.csv", "text/csv"),
                    ("合计小计复核 CSV", "table_reconciliation_audit.csv", "text/csv"),
                    ("表头算法候选 CSV", "header_parser_candidates.csv", "text/csv"),
                    ("表头裁决 JSON", "machine_header_arbitration.json", "application/json"),
                    ("机器完整长表 CSV", "machine_capture_full_long.csv", "text/csv"),
                    ("机器完整宽表 CSV", "machine_capture_full_wide.csv", "text/csv"),
                    ("Excel", "table_capture.xlsx", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"),
                    ("JSON", "table_capture_result.json", "application/json"),
                    ("HTML报告", "table_report.html", "text/html"),
                ]
                for label, filename, mime in downloads:
                    path = run_dir / filename
                    if path.exists():
                        st.download_button(
                            f"下载{label}",
                            path.read_bytes(),
                            file_name=filename,
                            mime=mime,
                            key=f"capture_dl_{run_dir.name}_{filename}",
                        )

                csv_files = {
                    "正式长表": run_dir / "table_raw_long.csv",
                    "正式宽表": run_dir / "table_raw_wide.csv",
                    "细项字典": run_dir / "table_item_dictionary.csv",
                    "合计小计复核": run_dir / "table_reconciliation_audit.csv",
                    "机器完整长表": run_dir / "machine_capture_full_long.csv",
                    "机器完整宽表": run_dir / "machine_capture_full_wide.csv",
                }
                csv_choice = st.selectbox(
                    "选择要自定义保存的 CSV",
                    list(csv_files),
                    key=f"capture_custom_choice_{run_dir.name}",
                )
                custom_csv_export_widget(
                    csv_files[csv_choice],
                    default_name=csv_files[csv_choice].name,
                    key=f"capture_custom_{run_dir.name}_{csv_choice}",
                    label="自定义保存整表 CSV",
                )

        except Exception as exc:
            status.update(label="整表抓取失败", state="error", expanded=True)
            st.exception(exc)

    st.divider()
    st.info(
        "历史 Capture、批量废除/恢复、整批重跑、回收站与依赖管理已移至一级菜单「数据资产管理」。"
    )


elif page == "合表":
    st.title("整表合表 / Taxonomy")
    st.caption(
        "将多份整表抓取结果合并为同一数据项目。Raw evidence 永久保留；"
        "完全相同的规范化细项可自动对齐，名称不同的细项只提供建议，必须人工确认后才进入共同 canonical key。"
    )

    # SQLite is the active-asset authority.  The old filesystem scan included
    # abandoned legacy folders, which produced "待认证" rows that did not exist
    # in 数据资产管理 → Captures.  Never present an unregistered folder as a
    # live merge candidate.
    merge_research_batch_id=st.session_state.get("merge_research_batch_id")
    if merge_research_batch_id:
        batch_scope_col,batch_clear_col=st.columns([4,1])
        batch_scope_col.info(f"当前仅显示研究批次：{merge_research_batch_id}")
        if batch_clear_col.button("清除批次范围",key="clear_merge_research_batch"):
            st.session_state.pop("merge_research_batch_id",None)
            st.rerun()
    all_capture_records = BACKEND.asset_service.list_captures(
        lifecycle_status="ACTIVE",
        research_batch_id=merge_research_batch_id,
        limit=100000,
    )
    missing_run_records = [r for r in all_capture_records if not Path(str(r.get("run_dir") or "")).exists()]
    all_capture_records = [r for r in all_capture_records if Path(str(r.get("run_dir") or "")).exists()]
    if missing_run_records:
        st.warning(f"已隔离 {len(missing_run_records)} 条缺少实际目录的旧 Capture 索引；它们不会显示为待认证或合表候选。")
    with st.expander("旧版整表目录 / SQLite 索引对账", expanded=False):
        filesystem_count = len(list_capture_records(TABLE_CAPTURE_DIR))
        st.caption(f"活动 SQLite Capture：{len(all_capture_records)}；旧目录扫描结果：{filesystem_count}。合表只使用前者。")
        if st.button("执行一次安全索引同步", key="v66_merge_registry_sync"):
            result = BACKEND.registry_service.full_sync(reason="MERGE_LEGACY_RECONCILIATION")
            st.success(f"已完成索引同步：{result}")
            st.rerun()
    merge_ready_records = [r for r in all_capture_records if r.get("merge_ready")]
    blocked_records = [r for r in all_capture_records if not r.get("merge_ready")]

    # Filter labels come from the Logical Asset identity. Capture.table_query
    # may be a physical block title such as "按资产类型", so it is only a
    # legacy fallback when no logical member identity exists.
    merge_asset_identities = {
        str(row.get("capture_id") or ""): row
        for row in BACKEND.asset_query_service.search(
            pagination={"page_size": 2000},
        )
        if row.get("capture_id")
    }
    member_display_map = _member_display_map()
    enriched_merge_ready_records = []
    for record in merge_ready_records:
        capture_id = str(record.get("capture_id") or record.get("run_id") or "")
        identity = merge_asset_identities.get(capture_id) or {}
        enriched_merge_ready_records.append(enrich_merge_filter_identity(
            record,
            identity,
            member_display_map,
        ))
    merge_ready_records = enriched_merge_ready_records

    def _merge_inspection_route(record: dict, *, initial_tab: str) -> InspectionRoute | None:
        capture_id = str(record.get("capture_id") or record.get("run_id") or "")
        if not capture_id:
            return None
        detail = BACKEND.capture_version_service.detail(capture_id) or {}
        logical_asset_id = str(
            detail.get("logical_asset_id")
            or record.get("logical_asset_id")
            or ""
        )
        if not logical_asset_id:
            return None
        return InspectionRoute(
            logical_asset_id=logical_asset_id,
            capture_version_id=capture_id,
            initial_tab=initial_tab,
            return_route="合表",
        )

    if blocked_records:
        with st.expander(f"有 {len(blocked_records)} 个整表抓取尚未通过结构认证，暂不可合表", expanded=False):
            st.dataframe(
                pd.DataFrame([
                    {
                        "名称": r.get("display_name"),
                        "边界状态": r.get("boundary_status"),
                        "表头维度": r.get("header_dimension_status"),
                        "阻断原因": " | ".join(r.get("merge_blockers") or []),
                        "来源PDF": r.get("source_pdf_display"),
                        "表": r.get("table_query"),
                    }
                    for r in blocked_records
                ]),
                use_container_width=True,
                hide_index=True,
            )
            st.caption(
                "阻断来源可直接进入逻辑资产工作区完成结构、证据与审核检查。"
            )
            blocked_option_map = {
                merge_asset_label(r): r
                for r in blocked_records
            }
            blocked_label = st.selectbox(
                "检查一个阻断来源",
                list(blocked_option_map),
                key="merge_blocked_inspection_source",
            )
            blocked_route = _merge_inspection_route(
                blocked_option_map[blocked_label],
                initial_tab="勾稽与质量",
            )
            if blocked_route is None:
                st.caption("该旧记录尚未关联逻辑资产；请先执行上方安全索引同步。")
            else:
                st.button(
                    "在逻辑资产工作区检查此来源",
                    key="open_merge_blocked_in_workspace",
                    on_click=set_inspection_route,
                    args=(st, blocked_route),
                    kwargs={"open_workspace": True},
                )

    if not merge_ready_records:
        st.info("当前没有边界已确认、可用于正式合表的整表抓取结果。")
        st.stop()

    merge_record_map = {
        str(r.get("capture_id") or r.get("run_id")): r
        for r in merge_ready_records
        if r.get("capture_id") or r.get("run_id")
    }
    selected_capture_ids = render_merge_asset_picker(
        st,
        merge_ready_records,
        key="v611_merge_assets",
    )
    selected_records = [
        merge_record_map[capture_id]
        for capture_id in selected_capture_ids
        if capture_id in merge_record_map
    ]
    merge_option_map = {
        merge_asset_label(record): record
        for record in selected_records
    }
    selected_labels = list(merge_option_map)
    selected_dirs = [Path(r["run_dir"]) for r in selected_records]

    if selected_dirs:
        inspect_label = st.selectbox(
            "检查已选合表来源",
            selected_labels,
            key="merge_ready_inspection_source",
        )
        inspect_route = _merge_inspection_route(
            merge_option_map[inspect_label],
            initial_tab="Canonical 数据",
        )
        if inspect_route is not None:
            st.button(
                "在逻辑资产工作区检查已选来源",
                key="open_merge_ready_in_workspace",
                on_click=set_inspection_route,
                args=(st, inspect_route),
                kwargs={"open_workspace": True},
            )
        inferred = [infer_capture_metadata(p) for p in selected_dirs]
        first_table = inferred[0].get("table_query") or "TABLE"
        table_id_input = st.text_input(
            "Canonical Table ID",
            value=normalize_table_id(first_table),
            help="同一经济含义的不同公司表名应使用同一个 Table ID；这是合表的表级主键。",
        )

        meta_df = pd.DataFrame([
            {
                "capture_run_id": m["capture_run_id"],
                "pdf_name": m["pdf_name"],
                "company": m["company"],
                "document_year": m["document_year"],
                "table_query": m["table_query"],
                "note_number": m["note_number"],
            }
            for m in inferred
        ])
        st.subheader("来源元数据")
        st.caption(
            "document_year 必须是年报实际年份（四位数）。"
            "当整表列名为“本年/本年累计数/本期”时，系统会转换为 document_year；"
            "“去年/上年/上年累计数/上期”会转换为 document_year-1。"
            "原始相对期间文字保留在 source_period_label 中。"
        )
        edited_meta = st.data_editor(
            meta_df,
            use_container_width=True,
            hide_index=True,
            disabled=["capture_run_id", "pdf_name", "table_query", "note_number"],
            key="merge_source_metadata",
        )

        order_selection = render_merge_order_controls(
            st,
            selected_records,
            edited_meta["document_year"].tolist(),
        )
        reference_capture_run_id = order_selection.reference_capture_run_id
        order_policy = order_selection.order_policy
        reference_report_year = order_selection.reference_report_year

        if st.button("创建合表项目", type="primary", use_container_width=True):
            stamp = dt.datetime.now().strftime("%Y%m%dT%H%M%S")
            safe_id = re.sub(r'[\\/:*?"<>|\\s]+', "_", table_id_input)[:70]
            merge_dir = MERGE_DIR / f"{stamp}_{safe_id}"
            merge_dir.mkdir(parents=True, exist_ok=True)

            metadata_rows = edited_meta.to_dict("records")
            try:
                create_merge_project(
                    capture_dirs=selected_dirs,
                    metadata_rows=metadata_rows,
                    output_dir=merge_dir,
                    table_id=table_id_input,
                    taxonomy_path=TABLE_TAXONOMY_PATH,
                    reference_capture_run_id=reference_capture_run_id,
                    order_policy=order_policy,
                    reference_report_year=reference_report_year or None,
                    member_display_map=_member_display_map(),
                )
                ensure_merge_metadata(merge_dir)
                st.session_state.active_merge_dir = str(merge_dir)
                st.success(
                    "合表项目已创建。Raw数据未修改；请在下方“映射审核”中处理不同名称的细项。"
                )
            except Exception as exc:
                st.exception(exc)

    st.divider()
    st.subheader("合表项目")

    merge_records = list_merge_records(MERGE_DIR)
    if not merge_records:
        st.caption("暂无合表项目。")
        st.stop()

    st.dataframe(
        pd.DataFrame([
            {
                "名称": r.get("display_name"),
                "Table ID": r.get("table_id"),
                "来源数": r.get("source_count"),
                "排序基准": r.get("reference_capture_run_id"),
                "顺序冲突": r.get("order_conflict_count"),
                "数值/单位冲突": r.get("value_conflict_count"),
                "备注": r.get("note"),
            }
            for r in merge_records
        ]),
        use_container_width=True,
        hide_index=True,
    )

    merge_option_map = {
        merge_project_label(r): r
        for r in merge_records
    }
    merge_labels = list(merge_option_map)

    default_merge = 0
    if st.session_state.active_merge_dir:
        active_name = Path(st.session_state.active_merge_dir).name
        for i, label in enumerate(merge_labels):
            if merge_option_map[label]["run_id"] == active_name:
                default_merge = i
                break

    merge_label = st.selectbox(
        "选择合表项目",
        merge_labels,
        index=default_merge,
        key="merge_project_selector",
    )
    merge_rec = merge_option_map[merge_label]
    merge_dir = Path(merge_rec["run_dir"])
    merge_name = merge_rec["run_id"]
    merge_display_name = str(merge_rec.get("display_name") or merge_name)
    research_wide_xlsx_download_name = research_wide_download_name(
        merge_display_name, "xlsx"
    )
    research_wide_csv_download_name = research_wide_download_name(
        merge_display_name, "csv"
    )
    st.session_state.active_merge_dir = str(merge_dir)

    manifest = json.loads((merge_dir / "merge_manifest.json").read_text(encoding="utf-8"))
    st.caption(
        f"Table ID: `{manifest.get('table_id')}` · "
        f"来源数量: {len(manifest.get('sources', []))} · "
        f"排序基准: `{manifest.get('reference_capture_run_id')}` · "
        f"Taxonomy: `{Path(manifest.get('taxonomy_path','')).name}`"
    )
    if manifest.get("period_resolution_policy"):
        st.caption(
            "期间口径：正式 canonical Merge 使用实际年份；"
            "本年/去年/上年/本期等相对标签仅作为 source_period_label 保留审计。"
        )

    tabs = st.tabs([
        "Canonical宽表",
        "结构顺序",
        "Resolved Long",
        "映射审核",
        "冲突",
        "合计/小计复核",
        "覆盖率",
        "Raw Long",
        "管理",
        "下载",
    ])

    with tabs[0]:
        path = merge_dir / "merge_canonical_wide.csv"
        df = pd.read_csv(path) if path.exists() else pd.DataFrame()
        metadata_path = merge_dir / "research_wide_metadata.json"
        dimensions_path = merge_dir / "column_dimensions.csv"
        wide_metadata = json.loads(metadata_path.read_text(encoding="utf-8")) if metadata_path.exists() else {}
        dimensions = pd.read_csv(dimensions_path) if dimensions_path.exists() else pd.DataFrame()
        value_columns = [str(column) for column in df.columns if str(column).startswith("COL_")]
        current_observation_schema = (
            bool(value_columns)
            and not dimensions.empty
            and "column_id" in dimensions.columns
            and set(value_columns).issubset(set(dimensions["column_id"].dropna().astype(str)))
        )
        if not current_observation_schema:
            st.warning(
                "此合表项目仍是旧版派生产物，尚未具备 v6.7 自适应多层表头契约。"
                "升级仅会重建派生 Long/Wide/Excel 输出，不会修改原始 Capture、机器证据或人工审核。"
            )
            st.caption(
                "旧版复合列头会被替换为稳定 COL_xxxxx + column_dimensions.csv。"
                "注意：若源 Capture 在旧版已把百万元错误写为元，必须重抓原 PDF；"
                "重新合表不会猜测或修正历史金额。"
            )
            if st.button("升级旧合表为 v6.7 自适应宽表", key=f"upgrade_v67_adaptive_wide_{merge_name}"):
                try:
                    refresh_merge_project(merge_dir)
                    ensure_merge_metadata(merge_dir)
                    st.success("已按 v6.7 自适应宽表契约重建派生产物。")
                    st.rerun()
                except Exception as exc:
                    st.exception(exc)
            # Do not render the stale wide frame as if it were canonical.
            # Other merge tabs remain available for diagnosis and recovery.
            df = pd.DataFrame()
        if current_observation_schema:
            presentation_export_current = int(wide_metadata.get("presentation_export_version") or 0) >= 2
            st.markdown("#### 自适应多层表头预览")
            interactive_preview, runtime_policy = adaptive_wide_interactive_frame(df, dimensions, max_rows=1000)
            html_preview, _ = adaptive_wide_preview_html(df, dimensions, max_rows=1000)
            st.markdown("#### Research Wide 元数据")
            st.json(runtime_policy.metadata_values)
            st.caption("可见列头维度：" + " → ".join(runtime_policy.visible_header_dimensions))
            preview_tabs = st.tabs(["交互式预览", "严格多层表头"])
            with preview_tabs[0]:
                st.caption(
                    "此视图复用数据资产管理的原生表格组件，因此具有相同的悬浮工具栏、搜索、全屏与下载入口。"
                    "原生组件不支持多层列头，故只在这里将各层显示标签压缩为单个可读列名。"
                )
                st.dataframe(interactive_preview, use_container_width=True, hide_index=True)
            with preview_tabs[1]:
                st.caption("此视图是展示版 Excel 的表头基准：保留真正的多层/合并表头。")
                st.markdown(html_preview, unsafe_allow_html=True)
            st.caption(
                "Excel 是展示版导出，保留预览所示的多行/合并表头；"
                "CSV 是机器交换格式，保留 COL_xxxxx，并通过列维度映射恢复完整观察维度。"
            )
            if not presentation_export_current:
                st.warning("此合表的 Excel 由旧展示版导出器生成，仍可能出现 COL_xxxxx。请先重新生成展示版导出。")
                if st.button("重新生成展示版 Excel 与宽表派生产物", key=f"refresh_presentation_export_{merge_name}"):
                    try:
                        refresh_merge_project(
                            merge_dir,
                            member_display_map=_member_display_map(),
                        )
                        ensure_merge_metadata(merge_dir)
                        st.success("已重新生成展示版 Excel；现在可以下载与预览一致的多层表头。")
                        st.rerun()
                    except Exception as exc:
                        st.exception(exc)
            download_columns = st.columns(5)
            excel_path = merge_dir / "merge_project.xlsx"
            research_wide_path = merge_dir / "research_wide.xlsx"
            with download_columns[0]:
                if excel_path.exists() and presentation_export_current:
                    st.download_button(
                        "下载 Excel 多层表头",
                        excel_path.read_bytes(),
                        file_name=excel_path.name,
                        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                        key=f"adaptive_wide_excel_{merge_name}",
                    )
                else:
                    st.caption("请先生成当前展示版 Excel。")
            with download_columns[1]:
                st.download_button(
                    "下载当前预览 HTML",
                    html_preview,
                    file_name="research_wide_preview.html",
                    mime="text/html",
                    key=f"adaptive_wide_html_{merge_name}",
                )
            with download_columns[2]:
                st.download_button(
                    "下载机器宽表 CSV",
                    path.read_bytes(),
                    file_name=path.name,
                    mime="text/csv",
                    key=f"adaptive_wide_csv_{merge_name}",
                )
            with download_columns[3]:
                st.download_button(
                    "下载列维度映射 CSV",
                    dimensions_path.read_bytes(),
                    file_name=dimensions_path.name,
                    mime="text/csv",
                    key=f"adaptive_wide_dimensions_{merge_name}",
                )
            with download_columns[4]:
                if research_wide_path.exists() and presentation_export_current:
                    st.download_button(
                        "下载研究用宽表 Excel",
                        research_wide_path.read_bytes(),
                        file_name=research_wide_xlsx_download_name,
                        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                        key=f"adaptive_research_wide_excel_{merge_name}",
                        help="仅保留 member_table / canonical_item / unit 与实际数据列，多层表头架构不变。",
                    )
                elif research_wide_path.exists():
                    st.caption("请先重新生成展示版导出。")
                else:
                    st.caption("研究宽表尚未生成。")
                    if st.button(
                        "生成研究宽表（重新物化合表）",
                        key=f"generate_research_wide_{merge_name}",
                    ):
                        try:
                            refresh_merge_project(
                                merge_dir,
                                member_display_map=_member_display_map(),
                            )
                            ensure_merge_metadata(merge_dir)
                            st.success(
                                "已生成研究宽表与展示版导出；"
                                "现在可以下载研究用宽表 Excel/CSV。"
                            )
                            st.rerun()
                        except Exception as exc:
                            st.exception(exc)
        else:
            st.info("请先升级此旧合表，升级完成后将在这里显示自适应多层表头。")

    with tabs[1]:
        st.markdown("#### 合表顺序策略")
        order_manifest_path = merge_dir / "merge_manifest.json"
        order_manifest = (
            json.loads(order_manifest_path.read_text(encoding="utf-8"))
            if order_manifest_path.exists() else {}
        )
        current_order_policy = str(
            order_manifest.get("order_policy")
            or "REFERENCE_CAPTURE_PRESERVE_WITH_CONTEXTUAL_INSERTION"
        )
        current_reference_year = str(
            order_manifest.get("reference_report_year") or ""
        )
        st.caption(
            f"当前策略：{current_order_policy}"
            + (
                f"｜基准年份：{current_reference_year}"
                if current_reference_year else ""
            )
        )
        order_years = sorted({
            str(source.get("document_year") or source.get("report_year") or "")
            for source in (order_manifest.get("sources") or [])
            if source.get("document_year") or source.get("report_year")
        }, reverse=True)
        if order_years:
            year_col, apply_col = st.columns([1, 2])
            selected_order_year = year_col.selectbox(
                "基准年份（按该年附注号排序）",
                order_years,
                key=f"note_order_year_{merge_name}",
            )
            if apply_col.button(
                "应用基准年份并重新物化合表",
                key=f"apply_note_order_{merge_name}",
            ):
                try:
                    # NOTE_ORDINAL_ORDER_POLICY value kept literal here so a
                    # running process with a cached older table_merge module
                    # cannot break app.py startup on symbol import.
                    note_ordinal_policy = "NOTE_ORDINAL_REFERENCE_YEAR"
                    refresh_merge_project(
                        output_dir=merge_dir,
                        order_policy=note_ordinal_policy,
                        reference_report_year=str(selected_order_year),
                        member_display_map=_member_display_map(),
                    )
                    ensure_merge_metadata(merge_dir)
                    st.success(
                        f"已按 {selected_order_year} 年附注号重新排序合表。"
                    )
                except Exception as exc:
                    st.exception(exc)
        else:
            st.caption("合表来源缺少年份信息，无法按附注号排序。")
        st.divider()
        order_path = merge_dir / "merge_structural_order.csv"
        order_df = pd.read_csv(order_path) if order_path.exists() else pd.DataFrame()
        st.caption(
            "canonical_order 是最终研究表的唯一权威行序。"
            "REFERENCE 表示来自排序基准表；INSERTED_FROM 表示其他来源独有项目按上下文插入。"
        )
        st.dataframe(order_df, use_container_width=True, hide_index=True)

        conflict_path = merge_dir / "merge_order_conflicts.csv"
        order_conflicts = (
            pd.read_csv(conflict_path)
            if conflict_path.exists() and conflict_path.stat().st_size > 0
            else pd.DataFrame()
        )
        if order_conflicts.empty:
            st.success("未发现跨来源共同项目顺序冲突。")
        else:
            st.warning(
                "发现 ORDER_CONFLICT / DUPLICATE_CANONICAL_KEY_IN_SOURCE。"
                "最终输出仍严格保留排序基准表顺序，不会自动重排。"
            )
            st.dataframe(order_conflicts, use_container_width=True, hide_index=True)

    with tabs[2]:
        path = merge_dir / "merge_resolved_long.csv"
        df = pd.read_csv(path) if path.exists() else pd.DataFrame()
        st.dataframe(df, use_container_width=True, hide_index=True)

    with tabs[3]:
        queue_path = merge_dir / "merge_mapping_queue.csv"
        queue = pd.read_csv(queue_path) if queue_path.exists() else pd.DataFrame()
        if not queue.empty:
            for col in [
                "suggested_canonical_section", "suggested_canonical_item",
                "canonical_section", "canonical_item", "category",
                "mapping_status", "mapping_note",
            ]:
                if col in queue.columns:
                    queue[col] = queue[col].fillna("").astype(str)
        if queue.empty:
            st.info("当前没有可审核的细项映射。")
        else:
            st.caption(
                "AUTO_EXACT_IDENTITY：同名项目在各自原表中均唯一时，parent_section 仅作上下文，不再阻止自动对齐。"
                "只有同一来源内部出现同名多次时，才启用 parent_section / row_type / occurrence 消歧。"
                "UNMAPPED_PRESERVED：仍以 RAW key 保留；不同名称需人工 CONFIRMED。"
            )
            edited = st.data_editor(
                queue,
                use_container_width=True,
                hide_index=True,
                disabled=[
                    "source_key", "parent_section", "normalized_item",
                    "occurrences", "capture_count", "companies",
                    "example_raw_items", "suggested_canonical_section",
                    "suggested_canonical_item", "suggestion_score",
                ],
                column_config={
                    "mapping_status": st.column_config.SelectboxColumn(
                        "mapping_status",
                        options=[
                            "AUTO_EXACT_IDENTITY",
                            "AUTO_TAXONOMY",
                            "UNMAPPED_PRESERVED",
                            "CONFIRMED",
                            "CONFIRMED_OVERRIDE",
                            "REJECTED",
                        ],
                    )
                },
                key=f"mapping_editor_{merge_name}",
            )
            persist_tax = st.checkbox(
                "将 CONFIRMED 映射写入持久化 Table Taxonomy",
                value=True,
                help="下一次合并同类表时，这些映射会自动以 AUTO_TAXONOMY 生效。",
                key=f"persist_tax_{merge_name}",
            )
            if st.button(
                "保存映射并重新物化合表",
                type="primary",
                key=f"save_mapping_{merge_name}",
            ):
                try:
                    refresh_merge_project(
                        output_dir=merge_dir,
                        mapping_queue=edited,
                        persist_taxonomy=persist_tax,
                        member_display_map=_member_display_map(),
                    )
                    st.success("映射已保存；canonical long/wide、冲突表和覆盖率已重新生成。")
                    st.rerun()
                except Exception as exc:
                    st.exception(exc)

    with tabs[4]:
        path = merge_dir / "merge_conflicts.csv"
        conflicts = pd.read_csv(path) if path.exists() and path.stat().st_size > 0 else pd.DataFrame()
        if conflicts.empty:
            st.success("当前没有 canonical key 数值/单位冲突。")
        else:
            st.warning(
                "这些键存在 VALUE_CONFLICT 或 UNIT_CONFLICT，已阻止进入 canonical wide。"
            )
            st.dataframe(conflicts, use_container_width=True, hide_index=True)

    with tabs[5]:
        path = merge_dir / "merge_reconciliation_audit.csv"
        audit = pd.read_csv(path) if path.exists() else pd.DataFrame()
        st.caption(
            "Warning-only 汇总：成员集合先由来源整表结构推断，再做算术验证。"
            "WARNING 不会自动修改金额，也不会单独阻断 canonical wide。"
        )
        if audit.empty:
            st.info("当前来源没有可用的合计/小计算术复核记录。")
        else:
            warnings = audit[
                audit["status"].astype(str).str.startswith("WARNING")
                | audit["status"].astype(str).str.startswith("NOT_TESTABLE")
            ]
            if warnings.empty:
                st.success("当前可测试的来源合计/小计检查未发现 Warning。")
            else:
                st.warning(f"发现 {len(warnings)} 条 Warning/不可测试项，请结合 child_items / child_row_orders 人工核对。")
            st.dataframe(audit, use_container_width=True, hide_index=True)

    with tabs[6]:
        path = merge_dir / "merge_coverage.csv"
        cov = pd.read_csv(path) if path.exists() else pd.DataFrame()
        st.dataframe(cov, use_container_width=True, hide_index=True)

    with tabs[7]:
        path = merge_dir / "merge_raw_long.csv"
        raw = pd.read_csv(path) if path.exists() else pd.DataFrame()
        st.caption("不可变来源证据层。映射/合表不会覆盖这里的 raw_item、原始值和页码。")
        st.dataframe(raw, use_container_width=True, hide_index=True)

    with tabs[8]:
        merge_meta = ensure_merge_metadata(merge_dir)
        st.write(f"**稳定 Run ID**：`{merge_name}`")
        new_merge_name = st.text_input(
            "显示名称",
            value=str(merge_meta.get("display_name") or merge_name),
            key=f"merge_display_name_{merge_name}",
        )
        new_merge_note = st.text_area(
            "备注",
            value=str(merge_meta.get("note") or ""),
            key=f"merge_note_{merge_name}",
        )
        if st.button("保存名称/备注", key=f"merge_meta_save_{merge_name}"):
            update_merge_metadata(
                merge_dir,
                display_name=new_merge_name,
                note=new_merge_note,
            )
            st.success("合表项目元数据已保存。")
            st.rerun()

        st.divider()
        st.warning("删除仅将整个合表项目移动到回收站，不会删除来源整表抓取或原始 PDF。")
        confirm_merge_delete = st.checkbox(
            "确认将该合表项目移到回收站",
            key=f"merge_delete_confirm_{merge_name}",
        )
        if st.button(
            "移到回收站",
            disabled=not confirm_merge_delete,
            key=f"merge_soft_delete_{merge_name}",
        ):
            soft_delete_merge(merge_dir, MERGE_TRASH_DIR)
            st.session_state.active_merge_dir = None
            st.success("合表项目已移动到回收站。")
            st.rerun()

    with tabs[9]:
        downloads = [
            ("Raw Long", "merge_raw_long.csv", "text/csv"),
            ("Mapping Queue", "merge_mapping_queue.csv", "text/csv"),
            ("Canonical Long", "merge_canonical_long.csv", "text/csv"),
            ("Resolved Long", "merge_resolved_long.csv", "text/csv"),
            ("Canonical Wide", "merge_canonical_wide.csv", "text/csv"),
            ("Conflicts", "merge_conflicts.csv", "text/csv"),
            ("Coverage", "merge_coverage.csv", "text/csv"),
            ("Structural Order", "merge_structural_order.csv", "text/csv"),
            ("Order Conflicts", "merge_order_conflicts.csv", "text/csv"),
            ("Reconciliation Audit", "merge_reconciliation_audit.csv", "text/csv"),
            ("研究用宽表 Excel", "research_wide.xlsx", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"),
            ("研究用宽表 CSV", "research_wide.csv", "text/csv"),
            ("Excel", "merge_project.xlsx", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"),
            ("Manifest", "merge_manifest.json", "application/json"),
        ]
        for label, filename, mime in downloads:
            path = merge_dir / filename
            if path.exists():
                download_name = {
                    "research_wide.xlsx": research_wide_xlsx_download_name,
                    "research_wide.csv": research_wide_csv_download_name,
                }.get(filename, filename)
                st.download_button(
                    f"下载 {label}",
                    path.read_bytes(),
                    file_name=download_name,
                    mime=mime,
                    key=f"merge_dl_{merge_name}_{filename}",
                )


        csv_files = {
            "Raw Long": merge_dir / "merge_raw_long.csv",
            "Mapping Queue": merge_dir / "merge_mapping_queue.csv",
            "Canonical Long": merge_dir / "merge_canonical_long.csv",
            "Resolved Long": merge_dir / "merge_resolved_long.csv",
            "Canonical Wide": merge_dir / "merge_canonical_wide.csv",
            "Conflicts": merge_dir / "merge_conflicts.csv",
            "Coverage": merge_dir / "merge_coverage.csv",
            "Structural Order": merge_dir / "merge_structural_order.csv",
            "Order Conflicts": merge_dir / "merge_order_conflicts.csv",
            "Reconciliation Audit": merge_dir / "merge_reconciliation_audit.csv",
        }
        existing_csv = {k: v for k, v in csv_files.items() if v.exists()}
        if existing_csv:
            st.divider()
            custom_choice = st.selectbox(
                "选择要自定义保存的 CSV",
                list(existing_csv),
                key=f"merge_custom_choice_{merge_name}",
            )
            custom_csv_export_widget(
                existing_csv[custom_choice],
                default_name=existing_csv[custom_choice].name,
                key=f"merge_custom_{merge_name}_{custom_choice}",
                label="自定义保存合表 CSV",
            )


    with st.expander("合表项目回收站", expanded=False):
        trashed_merges = sorted(
            [
                p for p in MERGE_TRASH_DIR.iterdir()
                if p.is_dir() and (p / "merge_manifest.json").exists()
            ],
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )
        if not trashed_merges:
            st.caption("合表回收站为空。")
        else:
            trash_map = {}
            for p in trashed_merges:
                try:
                    meta = ensure_merge_metadata(p)
                    label = merge_project_label({**meta, "run_id": p.name})
                except Exception:
                    label = p.name
                trash_map[label] = p

            trash_label = st.selectbox(
                "回收站合表项目",
                list(trash_map),
                key="merge_trash_selector",
            )
            trash_dir = trash_map[trash_label]
            c1, c2 = st.columns(2)
            if c1.button(
                "恢复合表项目",
                use_container_width=True,
                key=f"merge_restore_{trash_dir.name}",
            ):
                restore_merge(trash_dir, MERGE_DIR)
                st.success("合表项目已恢复。")
                st.rerun()

            permanent_confirm = st.checkbox(
                "确认永久删除该合表项目（不可恢复）",
                key=f"merge_perm_confirm_{trash_dir.name}",
            )
            if c2.button(
                "永久删除",
                disabled=not permanent_confirm,
                use_container_width=True,
                key=f"merge_perm_delete_{trash_dir.name}",
            ):
                permanent_delete_merge(trash_dir)
                st.success("合表项目已永久删除。")
                st.rerun()


elif page == "人工复核":
    # DEPRECATED thin compatibility route.  This value is no longer present in
    # production navigation; bookmarked legacy sessions land in the one
    # canonical inspection implementation.
    st.warning("旧“人工复核”入口已迁移至逻辑资产工作区。")
    render_asset_workspace(st, BACKEND)
    st.stop()
    st.title("人工复核")
    review_mode = st.radio(
        "复核对象",
        ["单 PDF 运行", "批量运行"],
        horizontal=True,
        key="review_mode",
    )

    if review_mode == "单 PDF 运行":
        runs = sorted(
            [p for p in RUNS_DIR.iterdir() if p.is_dir() and (p / "results.json").exists()],
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )
        if not runs:
            st.info("还没有单 PDF 运行结果。")
            st.stop()

        run_names = [p.name for p in runs]
        default = 0
        if st.session_state.active_run_dir:
            active_name = Path(st.session_state.active_run_dir).name
            if active_name in run_names:
                default = run_names.index(active_name)
        run_name = st.selectbox("选择运行", run_names, index=default, key="single_review_run")
        run_dir = next(p for p in runs if p.name == run_name)
        st.session_state.active_run_dir = str(run_dir)
        payload = load_run_results(run_dir)
        if payload is None:
            st.error("results.json 不存在。")
            st.stop()

        summary = result_summary_df(payload)
        st.dataframe(summary, use_container_width=True, hide_index=True)
        result_map = {r["metric_input"]: r for r in payload.get("results", [])}
        metric = st.selectbox("选择要复核的指标", list(result_map.keys()), key="single_review_metric")
        r = result_map[metric]
        review_dir = run_dir
        review_context = {"run_type": "single"}
    else:
        batch_runs = sorted(
            [p for p in BATCH_DIR.iterdir() if p.is_dir() and (p / "batch_results.json").exists()],
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )
        if not batch_runs:
            st.info("还没有批量运行结果。")
            st.stop()

        batch_name = st.selectbox(
            "选择批量运行",
            [p.name for p in batch_runs],
            key="batch_review_run",
        )
        review_dir = next(p for p in batch_runs if p.name == batch_name)
        docs = json.loads((review_dir / "batch_results.json").read_text(encoding="utf-8"))

        doc_labels = [
            f"{re.sub(r'^[0-9a-fA-F]{12}[ _-]+', '', str(d.get('company','')))} "
            f"{d.get('document_year', d.get('year',''))} — "
            f"{display_pdf_name(d.get('pdf_name',''))} · {str(d.get('pdf_sha256',''))[:8]}"
            for d in docs
        ]
        doc_label = st.selectbox("选择文档", doc_labels, key="batch_review_doc")
        doc = docs[doc_labels.index(doc_label)]

        summary_rows = doc.get("results", [])
        if summary_rows:
            st.dataframe(pd.DataFrame(summary_rows), use_container_width=True, hide_index=True)

        detail_map = {
            d.get("metric_input"): d
            for d in doc.get("resolution_details", [])
            if d.get("metric_input")
        }

        # Backward/self-healing fallback: recover detailed resolutions from audit.jsonl.
        if not detail_map:
            audit_path = review_dir / "audit.jsonl"
            if audit_path.exists():
                recovered = {}
                for line in audit_path.read_text(encoding="utf-8").splitlines():
                    try:
                        rec = json.loads(line)
                    except Exception:
                        continue
                    same_sha = (
                        str(rec.get("pdf_sha256") or "") == str(doc.get("pdf_sha256") or "")
                    )
                    same_name = (
                        display_pdf_name(rec.get("pdf_name", "")) ==
                        display_pdf_name(doc.get("pdf_name", ""))
                    )
                    if (same_sha or same_name) and rec.get("metric_input"):
                        recovered[rec["metric_input"]] = rec
                detail_map = recovered

        if not detail_map:
            st.warning(
                "该批量运行没有保存候选级详细信息，无法做候选改选。"
                "机器汇总结果仍可在“报告与审计 → 批量运行”查看；"
                "重新用 v4.6 运行后会完整保留候选证据。"
            )
            st.stop()

        metric = st.selectbox(
            "选择要复核的指标",
            list(detail_map.keys()),
            key="batch_review_metric",
        )
        r = detail_map[metric]
        review_context = {
            "run_type": "batch",
            "company": doc.get("company"),
            "document_year": doc.get("document_year", doc.get("year")),
            "pdf_name": doc.get("pdf_name"),
            "pdf_sha256": doc.get("pdf_sha256"),
        }

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("状态", r.get("status", "-"))
    c2.metric("决策层", r.get("layer", "-"))
    c3.metric("置信度", f"{float(r.get('confidence') or 0):.3f}")
    c4.metric("标准科目", r.get("standard_metric") or "未映射")

    selected = r.get("selected")
    if selected:
        st.subheader("自动选择结果")
        s1, s2, s3 = st.columns(3)
        s1.write(f"**PDF页码**：{selected.get('page')}")
        s2.write(f"**匹配原文**：{selected.get('label')}")
        s3.write(f"**解析来源**：{selected.get('source_method')}")
        if selected.get("header_source_page"):
            st.info(
                f"该候选位于 PDF 第 {selected.get('page')} 页，"
                f"期间/单位表头继承自 PDF 第 {selected.get('header_source_page')} 页。"
            )

        vals = selected.get("values") or []
        if vals:
            st.dataframe(pd.DataFrame([{
                "列": v.get("column_index", 0) + 1,
                "原始值": v.get("raw"),
                "期间/表头": v.get("header_context"),
                "原始单位": v.get("unit_original"),
                "换算为元": (
                    "不适用"
                    if v.get("unit_original") == "%"
                    else v.get("value_yuan")
                ),
            } for v in vals]), use_container_width=True, hide_index=True)

        snippet = selected.get("snippet_rows") or []
        if snippet:
            st.markdown("**原始表格上下文**")
            width = max(len(x) for x in snippet)
            st.dataframe(
                pd.DataFrame([x + [""] * (width - len(x)) for x in snippet]),
                use_container_width=True,
                hide_index=True,
            )
    else:
        st.warning("系统未自动确定唯一候选。")

    st.subheader("Top 候选")
    candidates = r.get("top_candidates") or []
    if candidates:
        cand_df = pd.DataFrame([{
            "candidate_id": c.get("candidate_id"),
            "页码": c.get("page"),
            "原始科目": c.get("label"),
            "表类型": c.get("table_type"),
            "来源": c.get("source_method"),
            "表头来源页": c.get("header_source_page"),
            "语义分": c.get("score"),
            "证据质量": c.get("evidence_quality"),
            "综合裁决分": c.get("arbitration_score"),
            "单位完整": bool(
                c.get("values")
                and any((v.get("unit_original") or "") for v in (c.get("values") or []))
            ),
            "期间/表头完整": bool(
                c.get("values")
                and any((v.get("header_context") or "") for v in (c.get("values") or []))
            ),
            "是否有数值": bool(c.get("values")),
            "匹配类型": next(
                (k for k in [
                    "exact_standard", "exact_alias", "exact_user_alias", "exact_soft_alias",
                    "contains_name", "string_similarity"
                ] if k in (c.get("score_detail") or {})),
                "-"
            ),
        } for c in candidates])
        st.dataframe(cand_df, use_container_width=True, hide_index=True)

        candidate_ids = [c.get("candidate_id") for c in candidates]
        auto_id = selected.get("candidate_id") if selected else None
        review_choice = st.selectbox(
            "人工确认候选",
            ["不选择"] + candidate_ids,
            index=(candidate_ids.index(auto_id) + 1 if auto_id in candidate_ids else 0),
            key=f"review_choice_{review_mode}_{metric}",
        )

        chosen_candidate = next(
            (c for c in candidates if c.get("candidate_id") == review_choice),
            None,
        )
        chosen_review_value = None
        if chosen_candidate:
            st.markdown("**人工所选候选证据**")
            st.write(
                f"p.{chosen_candidate.get('page')} · "
                f"{chosen_candidate.get('label')} · "
                f"{chosen_candidate.get('source_method')}"
            )
            candidate_values = chosen_candidate.get("values") or []
            if candidate_values:
                st.dataframe(
                    pd.DataFrame(candidate_values),
                    use_container_width=True,
                    hide_index=True,
                )

                target_review_year = str(review_context.get("document_year") or "")
                value_labels = []
                default_value_idx = 0
                for idx_v, v in enumerate(candidate_values):
                    ctx = str(v.get("header_context") or "")
                    label_v = f"{ctx or '期间未知'} | {v.get('raw')} | col={v.get('column_index')}"
                    value_labels.append(label_v)
                    if target_review_year and target_review_year in ctx:
                        default_value_idx = idx_v

                chosen_value_label = st.selectbox(
                    "人工确认该候选的数值列",
                    value_labels,
                    index=default_value_idx,
                    key=f"review_value_{review_mode}_{metric}_{review_choice}",
                )
                chosen_review_value = candidate_values[value_labels.index(chosen_value_label)]
    else:
        review_choice = "不选择"
        chosen_candidate = None
        chosen_review_value = None
        st.info("没有候选行。该项更可能属于 RULE GAP / PDF召回不足。")

    verdict = st.radio(
        "人工结论",
        ["确认自动结果", "改选候选", "驳回/未找到", "暂不判断"],
        horizontal=True,
        key=f"review_verdict_{review_mode}_{metric}",
    )
    note = st.text_area(
        "复核备注",
        placeholder="例如：精确科目“净利润”在利润表中明确出现；拒绝“本公司净利润”等限定口径。",
        key=f"review_note_{review_mode}_{metric}",
    )

    promote_alias = st.checkbox(
        "将本次查询名加入标准科目的 L0 强别名",
        value=False,
        disabled=not bool(r.get("standard_metric")),
        help="仅在语义确实等价时使用；“权益”“收入”等过宽词不要直接提升为强别名。",
        key=f"promote_alias_{review_mode}_{metric}",
    )
    if promote_alias and r.get("standard_metric"):
        st.caption(
            "保存时将执行：写入实际 rules_path → 重载生产 RuleBook → "
            "normalize_metric(本次查询名) 即时验证。验证失败会自动回滚。"
        )

    if st.button("保存人工复核", type="primary", key=f"save_review_{review_mode}"):
        chosen = None if review_choice == "不选择" else review_choice
        review_status_map = {
            "确认自动结果": "CONFIRMED_AUTO",
            "改选候选": "CONFIRMED_OVERRIDE",
            "驳回/未找到": "REJECTED",
            "暂不判断": "UNRESOLVED",
        }
        canonical_review_status = review_status_map[verdict]

        if canonical_review_status == "CONFIRMED_OVERRIDE":
            if not chosen_candidate:
                st.error("“改选候选”必须先选择一个候选。")
                st.stop()
            if not chosen_review_value:
                st.error("“改选候选”必须确认该候选对应的数值列。")
                st.stop()

        chosen_primary_snapshot = None
        chosen_candidate_snapshot = None
        chosen_value_year = None

        if canonical_review_status == "CONFIRMED_AUTO":
            chosen_candidate_snapshot = r.get("selected")
            chosen_primary_snapshot = r.get("primary_value")
        elif canonical_review_status == "CONFIRMED_OVERRIDE":
            chosen_candidate_snapshot = chosen_candidate
            chosen_primary_snapshot = chosen_review_value

        if chosen_primary_snapshot:
            ctx = str(chosen_primary_snapshot.get("header_context") or "")
            years = re.findall(r"(20\d{2})", ctx)
            chosen_value_year = str(max(map(int, years))) if years else None

        append_human_review(review_dir, {
            **review_context,
            "metric_input": metric,
            "standard_metric": r.get("standard_metric"),
            "verdict": verdict,
            "review_status": canonical_review_status,
            "chosen_candidate_id": chosen,
            "chosen_candidate": chosen_candidate_snapshot,
            "chosen_primary_value": chosen_primary_snapshot,
            "chosen_value_year": chosen_value_year,
            "note": note,
        })

        adjudication_msg = ""
        if review_mode == "批量运行":
            try:
                final_long, final_wide = refresh_adjudicated_artifacts(review_dir)
                adjudication_msg = (
                    f"；最终裁决表已刷新（long={len(final_long)}行，"
                    f"wide={len(final_wide)}行）"
                )
            except Exception as exc:
                adjudication_msg = f"；最终裁决表刷新失败：{exc}"

        alias_msg = ""
        if promote_alias and r.get("standard_metric"):
            standard = str(r["standard_metric"])
            alias_name = str(metric)
            result = persist_verified_alias(
                Path(st.session_state.rules_path),
                standard_metric=standard,
                alias=alias_name,
            )
            if result.get("ok"):
                # Force the next UI render / resolver construction to read the
                # freshly verified on-disk rulebook.
                st.session_state.dictionary_dirty = False
                st.session_state["rules_reload_nonce"] = (
                    int(st.session_state.get("rules_reload_nonce", 0)) + 1
                )
                alias_msg = (
                    "；"
                    + result.get("message", "L0别名写入并验证成功")
                    + f"；规则文件：{Path(result.get('rules_path','')).name}"
                )
            else:
                alias_msg = (
                    "；L0_ALIAS_WRITEBACK_FAILED："
                    + str(result.get("error") or "未知错误")
                )
        st.success(f"人工复核已保存{alias_msg}{adjudication_msg}")

    review_file = review_dir / "human_review.jsonl"
    if review_file.exists():
        with st.expander("查看人工复核记录"):
            st.code(review_file.read_text(encoding="utf-8"))


# -----------------------------------------------------------------------------
# Reports / audit
# -----------------------------------------------------------------------------

elif page == "报告与审计":
    st.title("报告与审计")
    report_mode = st.radio(
        "报告类型",
        ["单 PDF 运行", "批量运行"],
        horizontal=True,
        key="report_mode",
    )

    if report_mode == "单 PDF 运行":
        runs = sorted(
            [p for p in RUNS_DIR.iterdir() if p.is_dir() and (p / "results.json").exists()],
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )
        if not runs:
            st.info("还没有单 PDF 运行结果。")
            st.stop()

        run_names = [p.name for p in runs]
        default = 0
        if st.session_state.active_run_dir:
            active_name = Path(st.session_state.active_run_dir).name
            if active_name in run_names:
                default = run_names.index(active_name)

        run_name = st.selectbox("选择单 PDF 运行", run_names, index=default, key="single_report_run")
        run_dir = next(p for p in runs if p.name == run_name)

        tabs = st.tabs([
            "HTML报告", "Markdown", "机器JSON",
            "审计日志", "运行日志", "人工复核记录",
        ])

        with tabs[0]:
            path = run_dir / "report.html"
            if path.exists():
                raw = path.read_text(encoding="utf-8")
                st.components.v1.html(raw, height=900, scrolling=True)
                st.download_button("下载 HTML 报告", raw, file_name="report.html", mime="text/html")
            else:
                st.info("report.html 不存在。")

        with tabs[1]:
            path = run_dir / "report.md"
            if path.exists():
                raw = path.read_text(encoding="utf-8")
                st.markdown(raw)
                st.download_button("下载 Markdown", raw, file_name="report.md", mime="text/markdown")

        with tabs[2]:
            path = run_dir / "results.json"
            if path.exists():
                raw = path.read_text(encoding="utf-8")
                st.json(json.loads(raw))
                st.download_button("下载 results.json", raw, file_name="results.json", mime="application/json")

        with tabs[3]:
            path = run_dir / "audit.jsonl"
            if path.exists():
                raw = path.read_text(encoding="utf-8")
                st.code(raw, language="json")
                st.download_button("下载 audit.jsonl", raw, file_name="audit.jsonl", mime="application/jsonl")

        with tabs[4]:
            path = run_dir / "activity.log"
            if path.exists():
                raw = path.read_text(encoding="utf-8")
                st.code(raw, language="text")
                st.download_button("下载 activity.log", raw, file_name="activity.log", mime="text/plain")
            else:
                st.info("没有 activity.log。")

        with tabs[5]:
            path = run_dir / "human_review.jsonl"
            if path.exists():
                raw = path.read_text(encoding="utf-8")
                st.code(raw, language="json")
            else:
                st.info("尚无人工复核记录。")

    else:
        batch_runs = sorted(
            [p for p in BATCH_DIR.iterdir() if p.is_dir() and (p / "batch_results.json").exists()],
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )
        if not batch_runs:
            st.info("还没有批量运行结果。")
            st.stop()

        batch_names = [p.name for p in batch_runs]
        default = 0
        if st.session_state.active_batch_run_dir:
            active_name = Path(st.session_state.active_batch_run_dir).name
            if active_name in batch_names:
                default = batch_names.index(active_name)

        batch_name = st.selectbox("选择批量运行", batch_names, index=default, key="batch_report_run")
        run_dir = next(p for p in batch_runs if p.name == batch_name)
        st.session_state.active_batch_run_dir = str(run_dir)

        # Self-heal final tables for runs that have batch_results.json but old/missing materialized views.
        try:
            if not (run_dir / "adjudicated_long.csv").exists():
                refresh_adjudicated_artifacts(run_dir)
        except Exception as exc:
            st.warning(f"最终裁决表自动重建失败：{exc}")

        tabs = st.tabs([
            "HTML总报告", "Markdown",
            "最终宽表", "最终长表",
            "机器宽表", "机器长表",
            "机器JSON", "审计日志",
            "并行运行日志", "人工复核记录",
        ])

        with tabs[0]:
            path = run_dir / "batch_report.html"
            if path.exists():
                raw = path.read_text(encoding="utf-8")
                st.components.v1.html(raw, height=900, scrolling=True)
                st.download_button("下载批量 HTML 报告", raw, file_name="batch_report.html", mime="text/html")
            else:
                st.info("batch_report.html 不存在。")

        with tabs[1]:
            path = run_dir / "batch_report.md"
            if path.exists():
                raw = path.read_text(encoding="utf-8")
                st.markdown(raw)
                st.download_button("下载 Markdown", raw, file_name="batch_report.md", mime="text/markdown")

        with tabs[2]:
            path = run_dir / "adjudicated_wide.csv"
            if not path.exists():
                path = run_dir / "batch_wide.csv"
            if path.exists():
                df = pd.read_csv(path)
                st.caption("最终研究使用视图：一行一个指标，第二列为统一单位；结构为 metric | unit | company-year...。")
                st.dataframe(df, use_container_width=True, hide_index=True)
                st.download_button("下载最终宽表", path.read_bytes(), file_name="adjudicated_wide.csv", mime="text/csv")
                custom_csv_export_widget(
                    path,
                    default_name="adjudicated_wide.csv",
                    key=f"batch_final_wide_{run_dir.name}",
                    label="自定义保存最终宽表 CSV",
                )

        with tabs[3]:
            path = run_dir / "adjudicated_long.csv"
            if not path.exists():
                path = run_dir / "batch_long.csv"
            if path.exists():
                df = pd.read_csv(path)
                st.dataframe(df, use_container_width=True, hide_index=True)
                st.download_button("下载最终长表", path.read_bytes(), file_name="adjudicated_long.csv", mime="text/csv")
                custom_csv_export_widget(
                    path,
                    default_name="adjudicated_long.csv",
                    key=f"batch_final_long_{run_dir.name}",
                    label="自定义保存最终长表 CSV",
                )
            xlsx = run_dir / "batch_results.xlsx"
            if xlsx.exists():
                st.download_button(
                    "下载 Excel（机器+最终+复核日志）",
                    xlsx.read_bytes(),
                    file_name="batch_results.xlsx",
                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                )

        with tabs[4]:
            path = run_dir / "machine_wide.csv"
            if path.exists():
                df = pd.read_csv(path)
                st.caption("原始机器结果，仅用于审计，不会被人工裁决覆盖。")
                st.dataframe(df, use_container_width=True, hide_index=True)
                custom_csv_export_widget(
                    path,
                    default_name="machine_wide.csv",
                    key=f"batch_machine_wide_{run_dir.name}",
                    label="自定义保存机器宽表 CSV",
                )

        with tabs[5]:
            path = run_dir / "machine_long.csv"
            if path.exists():
                df = pd.read_csv(path)
                st.dataframe(df, use_container_width=True, hide_index=True)
                custom_csv_export_widget(
                    path,
                    default_name="machine_long.csv",
                    key=f"batch_machine_long_{run_dir.name}",
                    label="自定义保存机器长表 CSV",
                )

        with tabs[6]:
            path = run_dir / "batch_results.json"
            if path.exists():
                raw = path.read_text(encoding="utf-8")
                st.json(json.loads(raw))
                st.download_button("下载 batch_results.json", raw, file_name="batch_results.json", mime="application/json")

        with tabs[7]:
            path = run_dir / "audit.jsonl"
            if path.exists():
                raw = path.read_text(encoding="utf-8")
                st.code(raw, language="json")
                st.download_button("下载 audit.jsonl", raw, file_name="audit.jsonl", mime="application/jsonl")
            else:
                st.info("audit.jsonl 不存在。")

        with tabs[8]:
            path = run_dir / "batch_activity.log"
            if path.exists():
                raw = path.read_text(encoding="utf-8")
                st.code(raw, language="text")
                st.download_button("下载 batch_activity.log", raw, file_name="batch_activity.log", mime="text/plain")
            else:
                st.info("该运行没有 batch_activity.log。")

        with tabs[9]:
            path = run_dir / "human_review.jsonl"
            if path.exists():
                raw = path.read_text(encoding="utf-8")
                st.code(raw, language="json")
                st.download_button("下载 human_review.jsonl", raw, file_name="human_review.jsonl", mime="application/jsonl")
            else:
                st.info("尚无人工复核记录。")



# -----------------------------------------------------------------------------
# Data Asset Management Center
# -----------------------------------------------------------------------------

elif page == "数据资产管理":
    st.title("数据资产管理中心")
    st.caption(
        "v6.1 起资产列表由 SQLite Metadata Registry 提供索引；PDF/CSV/JSON 仍是机器证据与数据文件。"
        "Capture / Batch / Merge 的生命周期操作通过 Service Layer 执行，不再要求 Streamlit 直接扫描整个 DATA_HOME。"
    )

    reg_stats = BACKEND.registry_service.stats()
    h1, h2, h3, h4 = st.columns([1.2, 1, 1, 2.2])
    h1.metric("Captures", reg_stats["counts"].get("captures", 0))
    h2.metric("Batches", reg_stats["counts"].get("capture_batches", 0))
    h3.metric("Merges", reg_stats["counts"].get("merge_projects", 0))
    h4.caption(f"Registry: {reg_stats['db_path']}\n\nLast sync: {reg_stats.get('last_full_sync_at') or 'not synced'}")
    if st.button("重新同步 DATA_HOME → SQLite Registry", key="v61_registry_full_sync"):
        with st.spinner("正在重建元数据索引；机器证据不会被修改…"):
            out = BACKEND.registry_service.full_sync("USER_REQUESTED_FROM_UI")
        st.success(
            f"Registry 已同步：PDF {out['pdf_assets']} · Capture {out['captures']} · Merge {out['merges']}。"
        )
        st.rerun()

    asset_tabs = st.tabs(["Captures", "Batches", "Merges", "PDF", "回收站"])

    # ------------------------------------------------------------------ Captures
    with asset_tabs[0]:
        st.subheader("Capture 资产")
        options = BACKEND.asset_service.filter_options()
        f1, f2, f3, f4, f5, f6 = st.columns(6)
        lifecycle_filter = f1.selectbox(
            "生命周期", ["全部"] + options.get("lifecycle_status", []), key="v61_cap_lifecycle"
        )
        table_filter = f2.text_input("表名包含", key="v61_cap_table")
        company_filter = f3.text_input("公司包含", key="v61_cap_company")
        year_filter = f4.selectbox(
            "报告年", ["全部"] + options.get("document_year", []), key="v61_cap_year"
        )
        version_filter = f5.selectbox(
            "Producer Version", ["全部"] + options.get("producer_version", []), key="v61_cap_version"
        )
        research_batch_filter = f6.selectbox(
            "研究批次", ["全部"] + options.get("research_batch_id", []), key="v610_cap_research_batch"
        )

        filters = {
            "lifecycle_status": None if lifecycle_filter == "全部" else lifecycle_filter,
            "table_query_contains": table_filter.strip() or None,
            "company_contains": company_filter.strip() or None,
            "document_year": None if year_filter == "全部" else year_filter,
            "producer_version": None if version_filter == "全部" else version_filter,
            "research_batch_id": None if research_batch_filter == "全部" else research_batch_filter,
            "include_trash": False,
        }
        total = BACKEND.asset_service.count_captures(**filters)
        p1, p2 = st.columns([1, 3])
        page_size = p1.selectbox("每页", [50, 100, 250, 500], index=1, key="v61_cap_page_size")
        max_page = max(1, (total + page_size - 1) // page_size)
        _filter_sig = hashlib.md5(repr(sorted((str(k), str(v)) for k, v in filters.items())).encode("utf-8")).hexdigest()[:8]
        page_no = p2.selectbox(
            "页码", list(range(1, max_page + 1)), index=0,
            key=f"v61_cap_page_no_{_filter_sig}_{page_size}_{max_page}",
        )
        records = BACKEND.asset_service.list_captures(
            **filters, limit=int(page_size), offset=(int(page_no) - 1) * int(page_size)
        )
        st.caption(f"SQLite 查询结果：{total} 条 · 当前第 {page_no}/{max_page} 页")

        if not records:
            st.info("当前筛选条件下没有 Capture。")
        else:
            df = pd.DataFrame(records)
            display_cols = [c for c in [
                "capture_id", "lifecycle_status", "company", "document_year", "source_pdf_display",
                "table_query", "research_batch_ids", "batch_id", "producer_version", "header_parser", "boundary_status",
                "header_dimension_status", "merge_ready", "created_at", "invalidation_reason_code",
            ] if c in df.columns]
            manage = df[display_cols].copy()
            manage.insert(0, "选择", False)
            edited = st.data_editor(
                manage, use_container_width=True, hide_index=True,
                disabled=[c for c in manage.columns if c != "选择"],
                key=f"v61_capture_editor_{_filter_sig}_{page_no}_{page_size}", height=430,
            )
            selected_ids = set(
                edited.loc[edited["选择"] == True, "capture_id"].astype(str).tolist()
            )
            s1, s2 = st.columns(2)
            select_page = s1.checkbox(
                f"选择当前页全部 {len(records)} 条", key=f"v61_select_page_{_filter_sig}_{page_no}_{page_size}"
            )
            select_all_filtered = s2.checkbox(
                f"选择全部 {total} 条筛选结果", key=f"v61_select_all_filtered_{_filter_sig}_{total}",
                help="只从 SQLite 查询匹配的 Capture ID，不需要把全部明细加载到浏览器。",
            )
            if select_all_filtered:
                selected_ids = set(BACKEND.asset_service.matching_capture_ids(**filters))
            elif select_page:
                selected_ids = {str(r["capture_id"]) for r in records}
            st.write(f"**已选择：{len(selected_ids)} 条**")

            if selected_ids:
                impact = BACKEND.asset_service.dependency_impact(selected_ids)
                if impact["dependent_merge_count"]:
                    st.warning(
                        f"所选 Capture 被 {impact['dependent_merge_count']} 个 Merge 引用；废除/回收后依赖 Merge 会变为 STALE。"
                    )
                    with st.expander("查看依赖 Merge"):
                        st.dataframe(pd.DataFrame(impact["dependent_merges"]), use_container_width=True, hide_index=True)

            op1, op2, op3, op4 = st.columns(4)
            with op1:
                reason = st.selectbox("废除原因", INVALIDATION_REASON_CODES, key="v61_inv_reason")
                note = st.text_input("废除备注", key="v61_inv_note")
                ok = st.checkbox("确认批量废除", key="v61_inv_ok")
                if st.button("批量废除 INVALIDATED", type="primary", use_container_width=True,
                             disabled=not selected_ids or not ok, key="v61_inv_btn"):
                    out = BACKEND.asset_service.invalidate(selected_ids, reason_code=reason, note=note)
                    st.success(f"已废除 {len(out['invalidated'])} 条；STALE Merge {len(out['stale_merges'])} 个。")
                    st.rerun()
            with op2:
                ok = st.checkbox("确认恢复 ACTIVE", key="v61_reactivate_ok")
                if st.button("批量恢复 ACTIVE", use_container_width=True, disabled=not selected_ids or not ok, key="v61_reactivate_btn"):
                    out = BACKEND.asset_service.reactivate(selected_ids)
                    st.success(f"已恢复 {len(out['reactivated'])} 条。")
                    st.rerun()
            with op3:
                ok = st.checkbox("确认移入回收站", key="v61_trash_ok")
                if st.button("批量移入回收站", use_container_width=True, disabled=not selected_ids or not ok, key="v61_trash_btn"):
                    out = BACKEND.asset_service.trash(selected_ids)
                    st.success(f"已回收 {len(out['trashed'])} 条。")
                    st.rerun()
            with op4:
                parser = st.selectbox("重新抓取 Parser", ["AUTO", "ABSOLUTE_YEAR_CLASSIC", "GENERALIZED_PERIOD_V57"], key="v61_rerun_parser")
                ok = st.checkbox("确认批量重抓", key="v61_rerun_ok")
                if st.button("批量重新抓取", use_container_width=True, disabled=not selected_ids or not ok, key="v61_rerun_btn"):
                    new_bid = new_batch_id("RERUN_BATCH")
                    out = BACKEND.asset_service.rerun(selected_ids, parser_mode=parser, batch_id=new_bid)
                    st.success(f"替代批次 {new_bid}：成功 {len(out['created'])}，失败 {len(out['failures'])}。")
                    st.rerun()

            st.divider()
            st.subheader("单条 Capture 预览 / 结构审核")
            detail_map = {
                f"{r.get('company') or ''} {r.get('document_year') or ''} · {r.get('table_query') or ''} · {r.get('capture_id')}": r
                for r in records
            }
            detail_label = st.selectbox("选择当前页 Capture", list(detail_map), key="v61_capture_detail")
            rec = detail_map[detail_label]
            hist = Path(rec["run_path"])
            if hist.exists():
                detail_tabs = st.tabs(["预览", "边界复核", "表头算法裁决", "列拓扑复核", "表头维度复核", "合计/小计复核"])
                with detail_tabs[0]:
                    wide = hist / "table_raw_wide.csv"
                    st.dataframe(pd.read_csv(wide) if wide.exists() else pd.DataFrame(), use_container_width=True, hide_index=True)
                    result_path = hist / "table_capture_result.json"
                    if result_path.exists():
                        result_data = json.loads(result_path.read_text(encoding="utf-8"))
                        pdf_name = result_data.get("pdf_name")
                        pdf_path = UPLOAD_DIR / str(pdf_name)
                        if pdf_path.exists():
                            with st.expander("PDF 起始页预览", expanded=False):
                                st.image(render_pdf_page_png(pdf_path, int(result_data.get("start_page") or 1)), use_container_width=True)
                with detail_tabs[1]: boundary_review_widget(hist, key_prefix=f"asset_{hist.name}")
                with detail_tabs[2]: header_parser_arbitration_widget(hist, key_prefix=f"asset_{hist.name}")
                with detail_tabs[3]: column_topology_review_widget(hist, key_prefix=f"asset_{hist.name}")
                with detail_tabs[4]: header_dimension_review_widget(hist, key_prefix=f"asset_{hist.name}")
                with detail_tabs[5]:
                    rp = hist / "table_reconciliation_audit.csv"
                    st.dataframe(pd.read_csv(rp) if rp.exists() else pd.DataFrame(), use_container_width=True, hide_index=True)

            if st.button("导出当前页 Capture 资产清单 CSV", key="v61_export_inventory"):
                path = BACKEND.asset_service.export_inventory(records)
                st.success(f"已生成：{path}")

    # ------------------------------------------------------------------ Batches
    with asset_tabs[1]:
        st.subheader("Capture Batches · 正常资产")
        st.caption("主表只显示仍有 ACTIVE / INVALIDATED Capture 的批次；完全进入 TRASHED 的批次移到“回收站 → Batch Trash”。")
        batches = BACKEND.batch_service.list_batches(include_fully_trashed=False)
        if not batches:
            st.info("暂无有效 Batch。")
        else:
            bdf = pd.DataFrame(batches)
            cols = [c for c in ["batch_id", "batch_status", "capture_count", "active_count", "invalidated_count", "trashed_count", "table_query", "producer_versions", "last_created_at"] if c in bdf.columns]
            manage = bdf[cols].copy(); manage.insert(0, "选择", False)
            bedit = st.data_editor(manage, use_container_width=True, hide_index=True,
                                   disabled=[c for c in manage.columns if c != "选择"], key="v61_batch_editor")
            selected_batches = bedit.loc[bedit["选择"] == True, "batch_id"].astype(str).tolist()
            selected_capture_ids = BACKEND.batch_service.selected_capture_ids(selected_batches)
            st.caption(f"已选择 {len(selected_batches)} 个批次 / {len(selected_capture_ids)} 个非回收 Capture")
            b1, b2, b3 = st.columns(3)
            with b1:
                reason = st.selectbox("整批废除原因", INVALIDATION_REASON_CODES, key="v61_batch_reason")
                note = st.text_input("整批废除备注", key="v61_batch_note")
                ok = st.checkbox("确认整批废除", key="v61_batch_inv_ok")
                if st.button("废除所选批次", disabled=not selected_capture_ids or not ok, use_container_width=True, key="v61_batch_inv_btn"):
                    out = BACKEND.batch_service.invalidate(selected_batches, reason_code=reason, note=note)
                    st.success(f"已废除 {len(out['invalidated'])} 个 Capture。")
                    st.rerun()
            with b2:
                ok = st.checkbox("确认整批重新抓取", key="v61_batch_rerun_ok")
                if st.button("重新运行所选批次", disabled=not selected_capture_ids or not ok, use_container_width=True, key="v61_batch_rerun_btn"):
                    replacement = new_batch_id("BATCH_REPLACEMENT")
                    out = BACKEND.batch_service.rerun(selected_batches, parser_mode="AUTO", batch_id=replacement)
                    st.success(f"替代批次 {replacement}：成功 {len(out['created'])}，失败 {len(out['failures'])}。")
                    st.rerun()
            with b3:
                ok = st.checkbox("确认整批回收", key="v61_batch_trash_ok")
                if st.button("所选批次移入回收站", disabled=not selected_capture_ids or not ok, use_container_width=True, key="v61_batch_trash_btn"):
                    out = BACKEND.batch_service.trash(selected_batches)
                    st.success(f"已回收 {len(out['trashed'])} 个 Capture。")
                    st.rerun()

    # ------------------------------------------------------------------ Merges
    with asset_tabs[2]:
        st.subheader("Merge Assets")
        if st.button("重新检查全部 Merge 依赖状态", key="v61_refresh_merge_deps"):
            out = BACKEND.merge_service.refresh_dependencies()
            st.success(f"已检查 {len(out['updated'])} 个 Merge。")
            st.rerun()
        merges = BACKEND.merge_service.list(include_trash=False)
        if not merges:
            st.info("暂无 Merge Project。")
        else:
            mdf = pd.DataFrame(merges)
            cols = [c for c in ["merge_id", "display_name", "table_id", "source_count", "dependency_status", "stale_capture_run_ids", "created_at"] if c in mdf.columns]
            manage = mdf[cols].copy(); manage.insert(0, "选择", False)
            medit = st.data_editor(manage, use_container_width=True, hide_index=True,
                                   disabled=[c for c in manage.columns if c != "选择"], key="v61_merge_editor")
            mids = medit.loc[medit["选择"] == True, "merge_id"].astype(str).tolist()
            ok = st.checkbox("确认将所选 Merge 移入回收站", key="v61_merge_trash_ok")
            if st.button("批量回收 Merge", disabled=not mids or not ok, use_container_width=True, key="v61_merge_trash_btn"):
                out = BACKEND.merge_service.trash(mids)
                st.success(f"已回收 {len(out['trashed'])} 个 Merge。")
                st.rerun()

    # ------------------------------------------------------------------ PDFs
    with asset_tabs[3]:
        st.subheader("PDF Source Assets")
        pdf_rows = BACKEND.pdf_service.list(limit=10000)
        if not pdf_rows:
            st.info("暂无 PDF。")
        else:
            st.dataframe(pd.DataFrame(pdf_rows), use_container_width=True, hide_index=True)
            st.caption("PDF 是源证据。SQLite 只保存索引，不承载 PDF 内容；被 Capture 引用的源 PDF 默认不提供批量硬删除。")

    # ------------------------------------------------------------------ Recycle bin
    with asset_tabs[4]:
        st.subheader("统一回收站")
        rt1, rt2, rt3 = st.tabs(["Capture Trash", "Batch Trash", "Merge Trash"])
        with rt1:
            trash_records = BACKEND.asset_service.list_captures(only_trash=True, include_trash=True, limit=5000)
            if not trash_records:
                st.caption("Capture 回收站为空。")
            else:
                tdf = pd.DataFrame(trash_records)
                cols = [c for c in ["capture_id", "batch_id", "source_pdf_display", "table_query", "company", "document_year", "lifecycle_status", "updated_at"] if c in tdf.columns]
                manage = tdf[cols].copy(); manage.insert(0, "选择", False)
                tedit = st.data_editor(manage, use_container_width=True, hide_index=True,
                                       disabled=[c for c in manage.columns if c != "选择"], key="v61_trash_capture_editor")
                ids = tedit.loc[tedit["选择"] == True, "capture_id"].astype(str).tolist()
                c1, c2 = st.columns(2)
                if c1.button("批量恢复 Capture", disabled=not ids, use_container_width=True, key="v61_trash_restore"):
                    out = BACKEND.asset_service.restore(ids)
                    st.success(f"已恢复 {len(out['restored'])} 条。")
                    st.rerun()
                ok = st.checkbox("确认永久删除所选 Capture（不可恢复）", key="v61_trash_purge_ok")
                if c2.button("永久删除所选 Capture", disabled=not ids or not ok, use_container_width=True, key="v61_trash_purge"):
                    out = BACKEND.asset_service.purge(ids)
                    st.success(f"已永久删除 {len(out['purged'])} 条。")
                    st.rerun()
        with rt2:
            trash_batches = BACKEND.batch_service.list_batches(include_fully_trashed=True, only_with_trash=True)
            if not trash_batches:
                st.caption("没有包含 TRASHED Capture 的 Batch。")
            else:
                tbdf = pd.DataFrame(trash_batches)
                cols = [c for c in ["batch_id", "batch_status", "capture_count", "active_count", "invalidated_count", "trashed_count", "table_query", "last_created_at"] if c in tbdf.columns]
                manage = tbdf[cols].copy(); manage.insert(0, "选择", False)
                edit = st.data_editor(manage, use_container_width=True, hide_index=True,
                                      disabled=[c for c in manage.columns if c != "选择"], key="v61_trash_batch_editor")
                bids = edit.loc[edit["选择"] == True, "batch_id"].astype(str).tolist()
                trash_ids = []
                for bid in bids:
                    trash_ids.extend(BACKEND.batch_service.trashed_capture_ids(bid))
                st.caption(f"选择 {len(bids)} 个批次，涉及 {len(trash_ids)} 个 TRASHED Capture。")
                c1, c2 = st.columns(2)
                if c1.button("恢复所选批次中的 TRASHED Capture", disabled=not trash_ids, use_container_width=True, key="v61_trash_batch_restore"):
                    out = BACKEND.asset_service.restore(trash_ids)
                    st.success(f"已恢复 {len(out['restored'])} 条。")
                    st.rerun()
                ok = st.checkbox("确认永久删除这些 TRASHED Capture", key="v61_trash_batch_purge_ok")
                if c2.button("永久删除所选批次回收数据", disabled=not trash_ids or not ok, use_container_width=True, key="v61_trash_batch_purge"):
                    out = BACKEND.asset_service.purge(trash_ids)
                    st.success(f"已永久删除 {len(out['purged'])} 条。")
                    st.rerun()
        with rt3:
            trash_merges = BACKEND.merge_service.list(include_trash=True, only_trash=True)
            if not trash_merges:
                st.caption("Merge 回收站为空。")
            else:
                tdf = pd.DataFrame(trash_merges)
                cols = [c for c in ["merge_id", "display_name", "table_id", "source_count", "created_at"] if c in tdf.columns]
                manage = tdf[cols].copy(); manage.insert(0, "选择", False)
                edit = st.data_editor(manage, use_container_width=True, hide_index=True,
                                      disabled=[c for c in manage.columns if c != "选择"], key="v61_trash_merge_editor")
                mids = edit.loc[edit["选择"] == True, "merge_id"].astype(str).tolist()
                c1, c2 = st.columns(2)
                if c1.button("批量恢复 Merge", disabled=not mids, use_container_width=True, key="v61_trash_merge_restore"):
                    out = BACKEND.merge_service.restore(mids)
                    st.success(f"已恢复 {len(out['restored'])} 个 Merge。")
                    st.rerun()
                ok = st.checkbox("确认永久删除所选 Merge", key="v61_trash_merge_purge_ok")
                if c2.button("永久删除所选 Merge", disabled=not mids or not ok, use_container_width=True, key="v61_trash_merge_purge"):
                    out = BACKEND.merge_service.purge(mids)
                    st.success(f"已永久删除 {len(out['purged'])} 个 Merge。")
                    st.rerun()

# -----------------------------------------------------------------------------
# Shared DATA_HOME / migration center
# -----------------------------------------------------------------------------

elif page == "系统与迁移":
    st.title("系统与迁移")
    st.caption(
        "v6.1 延续共享 DATA_HOME，并新增 SQLite Metadata Registry、Repository/Service Layer 与 Headless Service CLI；Single-Instance Launcher 继续保留。"
        "新版启动器会安全识别并关闭旧的 Financial Metric Resolver Streamlit 实例。"
    )

    st.subheader("运行实例")
    st.json(runtime_instance() or {"mode": "Direct Streamlit", "note": "建议以后使用 run_gui.bat / launcher.py 启动"})
    st.caption("Single-Instance 只会关闭经命令行验证属于 Financial Metric Resolver 的旧 Streamlit PID，不会执行 taskkill python.exe。")

    st.subheader("Backend / Metadata Registry")
    st.caption("SQLite 仅保存元数据索引、生命周期、依赖与 Job 状态；PDF/JSON/CSV/Parquet 仍保留在 DATA_HOME。")
    st.json({
        **BACKEND.registry_service.stats(),
        "bootstrap": st.session_state.get("_v61_registry_bootstrap_result"),
        "service_cli": "python service_cli.py registry-stats",
    })
    if st.button("在系统页执行 Registry Full Sync", key="system_registry_sync"):
        with st.spinner("正在同步 DATA_HOME 元数据…"):
            _sync = BACKEND.registry_service.full_sync("SYSTEM_PAGE_USER_REQUEST")
        st.success(f"同步完成：Capture {_sync['captures']} · Merge {_sync['merges']} · PDF {_sync['pdf_assets']}")
        st.rerun()

    st.subheader("Persistent Job Registry")
    _jobs = BACKEND.job_service.list(limit=100)
    if _jobs:
        _job_df = pd.DataFrame(_jobs)
        _job_cols = [c for c in ["job_id", "batch_id", "job_type", "status", "progress", "source_asset_id", "target_asset_id", "created_at", "updated_at", "error_message"] if c in _job_df.columns]
        st.dataframe(_job_df[_job_cols], use_container_width=True, hide_index=True)
    else:
        st.caption("暂无持久化 Job。v6.1 先建立 Registry/Service 契约；受控多 PDF Worker Pool 在下一工作流版本接入。")

    st.subheader("共享 DATA_HOME")
    st.code(str(DATA_HOME))
    manifest_path = DATA_PATHS["manifest"]
    if manifest_path.exists():
        st.json(json.loads(manifest_path.read_text(encoding="utf-8")))

    with st.expander("修改 DATA_HOME", expanded=False):
        new_home = st.text_input(
            "新的共享数据目录",
            value=str(DATA_HOME),
            help=r"例如 D:\FinancialMetricResolverData。保存后需要重启 Streamlit 才会切换。",
            key="new_data_home",
        )
        if st.button("保存 DATA_HOME 配置", key="save_data_home"):
            try:
                target = Path(new_home).expanduser()
                target.mkdir(parents=True, exist_ok=True)
                save_data_home_config(APP_DIR, target)
                st.success(f"已保存：{target}。请关闭并重新启动当前 Streamlit 程序。")
            except Exception as exc:
                st.exception(exc)

    st.divider()
    st.subheader("历史版本迁移中心")
    st.markdown(
        """
迁移策略：

- **PDF / Capture / 边界复核 / 表头复核 / Batch / Review**：迁移并保留。
- **Table Taxonomy**：与当前共享 Taxonomy 合并。
- **L0 metric_aliases**：只做保守合并，新版规则不会被旧文件整体覆盖。
- **旧 Merge Project**：作为派生资产移入 `archive/legacy_merges_*`，标记 **REBUILD_RECOMMENDED**。
- **Cache**：不迁移，新版本重新生成。
        """
    )

    old_path = st.text_input(
        "旧版本目录或旧 workspace 目录",
        value="",
        help=(
            r"可填写旧版程序根目录，例如 D:\FinancialResolver\v5.5，"
            r"也可直接填写 D:\FinancialResolver\v5.5\workspace。"
        ),
        key="migration_source_path",
    )

    c1, c2 = st.columns(2)
    if c1.button("扫描旧版本", use_container_width=True, key="scan_old_version"):
        try:
            scan = scan_old_version(Path(old_path))
            st.session_state["migration_scan"] = scan
        except Exception as exc:
            st.session_state["migration_scan"] = None
            st.exception(exc)

    scan = st.session_state.get("migration_scan")
    if scan:
        st.success("已识别旧版本数据。")
        st.dataframe(
            pd.DataFrame([
                {"资产": "PDF", "数量/状态": scan["pdf_count"]},
                {"资产": "Capture", "数量/状态": scan["capture_count"]},
                {"资产": "旧 Merge", "数量/状态": scan["merge_count"]},
                {"资产": "Batch", "数量/状态": scan["batch_count"]},
                {"资产": "单指标 Run", "数量/状态": scan["run_count"]},
                {"资产": "Review 文件", "数量/状态": scan["review_file_count"]},
                {"资产": "Taxonomy", "数量/状态": "YES" if scan["has_taxonomy"] else "NO"},
                {"资产": "metric_aliases", "数量/状态": "YES" if scan["has_metric_aliases"] else "NO"},
                {"资产": "Cache", "数量/状态": "SKIP" if scan["cache_present"] else "NONE"},
            ]),
            use_container_width=True,
            hide_index=True,
        )
        st.code(scan["workspace"])

        confirm_migrate = st.checkbox(
            "确认执行迁移；旧 Merge 仅归档，不作为当前正式 canonical 结果继续使用",
            key="migration_confirm",
        )
        if c2.button(
            "执行迁移",
            type="primary",
            use_container_width=True,
            disabled=not confirm_migrate,
            key="run_migration",
        ):
            try:
                with st.status("正在迁移历史资产…", expanded=True) as status:
                    report = migrate_old_version(
                        Path(scan["source_root"]),
                        DATA_PATHS,
                        archive_old_merges=True,
                    )
                    status.update(label="历史版本迁移完成", state="complete", expanded=False)
                st.session_state["last_migration_report"] = report
                st.success(
                    "迁移完成。Capture/PDF/人工裁决已进入共享 DATA_HOME；"
                    "旧 Merge 已归档，建议基于最新版 Capture 重新建立正式合表。"
                )
                st.rerun()
            except Exception as exc:
                st.exception(exc)

    st.divider()
    st.subheader("迁移报告")
    reports = sorted(
        MIGRATION_REPORT_DIR.glob("migration_*.json"),
        key=lambda x: x.stat().st_mtime,
        reverse=True,
    )
    if not reports:
        st.caption("暂无迁移报告。")
    else:
        selected_report = st.selectbox(
            "选择迁移报告",
            reports,
            format_func=lambda x: x.name,
            key="migration_report_selector",
        )
        report_data = json.loads(selected_report.read_text(encoding="utf-8"))
        st.json(report_data.get("summary", {}))
        with st.expander("完整迁移事件", expanded=False):
            st.dataframe(
                pd.DataFrame(report_data.get("events") or []),
                use_container_width=True,
                hide_index=True,
            )
        st.download_button(
            "下载 migration_report.json",
            selected_report.read_bytes(),
            file_name=selected_report.name,
            mime="application/json",
        )

    st.divider()
    st.subheader("数据资产原则")
    st.code(
        """永久资产：
PDF
Machine Capture
人工边界复核
人工表头维度复核
Taxonomy / 人工映射

可重建派生资产：
Canonical Merge

临时资产：
Cache

以后升级 v6.1 → v6.2 / React-FastAPI 迁移版本：
新版代码继续指向同一个 DATA_HOME，
通常无需再次搬历史数据。""",
        language="text",
    )

    st.divider()
    st.subheader("旧数据完全清除")
    st.caption(
        "危险操作：清空 Registry 业务数据与 DATA_HOME 派生产物。"
        "执行前会自动备份 metadata.db 与受影响目录；"
        "Schema、Research Definition、表族/成员、config/Taxonomy 与 Golden 语料保留。"
    )
    from services.data_cleanup_service import (
        CLEANUP_CONFIRMATION_TOKEN,
        SCOPE_ALL,
        SCOPE_CAPTURE,
        DataCleanupService,
    )

    cleanup_svc = DataCleanupService(
        BACKEND.registry,
        DATA_PATHS,
        app_version=APP_VERSION,
    )
    scope_label = st.radio(
        "清除范围",
        [
            "全部业务数据（认证＋抓取＋合并）",
            "仅抓取记录（保留认证）",
        ],
        horizontal=True,
        key="data_cleanup_scope",
        help=(
            "“仅抓取记录”保留 occurrence/Anchor/子表候选/认证清单/CertifiedChildTableLink，"
            "只清抓取、作业、执行会话、审核与合并产物。"
        ),
    )
    cleanup_scope = SCOPE_ALL if scope_label.startswith("全部") else SCOPE_CAPTURE
    include_pdfs = st.checkbox(
        "同时清除上传的 PDF 资产（uploads/ 与 pdf_assets）",
        value=False,
        key="data_cleanup_include_pdfs",
        help="默认保留 PDF；勾选后 PDF 会随备份归档并从当前 DATA_HOME 移除。",
    )
    if st.button("扫描待清除数据（只读）", key="data_cleanup_scan_btn"):
        st.session_state["data_cleanup_preview"] = cleanup_svc.preview(
            scope=cleanup_scope,
            include_pdfs=include_pdfs,
        )
    preview = st.session_state.get("data_cleanup_preview")
    if (
        preview
        and (
            preview.get("scope") != cleanup_scope
            or preview.get("include_pdfs") != include_pdfs
        )
    ):
        preview = None
        st.session_state.pop("data_cleanup_preview", None)
    if preview:
        table_rows = pd.DataFrame(
            [
                {"表": table, "行数": count}
                for table, count in (preview.get("registry_rows") or {}).items()
            ]
        )
        dir_rows = pd.DataFrame(
            [
                {"目录": key, "文件数": count}
                for key, count in (preview.get("dir_files") or {}).items()
            ]
        )
        if not table_rows.empty:
            st.markdown("**Registry 业务表（待清空）**")
            st.dataframe(table_rows, use_container_width=True, hide_index=True)
        if not dir_rows.empty:
            st.markdown("**DATA_HOME 目录（待归档）**")
            st.dataframe(dir_rows, use_container_width=True, hide_index=True)
        if table_rows.empty and dir_rows.empty:
            st.success("当前没有可清除的旧数据。")
    confirmation_token = st.text_input(
        f"输入确认口令 {CLEANUP_CONFIRMATION_TOKEN}",
        type="password",
        key="data_cleanup_token",
        help="清除不可逆，仅备份可回滚；确认后系统会先备份再清除。",
    )
    if st.button(
        "备份并清除旧数据",
        type="primary",
        disabled=(
            confirmation_token != CLEANUP_CONFIRMATION_TOKEN
            or not preview
        ),
        key="data_cleanup_run",
    ):
        with st.spinner("正在备份并清除旧数据…"):
            report = cleanup_svc.run_cleanup(
                confirmation=confirmation_token,
                scope=cleanup_scope,
                include_pdfs=include_pdfs,
            )
        st.success(
            "清除完成。备份与清除报告位于："
            f"`{report['backup']['database']}`"
        )
        st.json(report)
        st.session_state.pop("data_cleanup_preview", None)
        st.rerun()
