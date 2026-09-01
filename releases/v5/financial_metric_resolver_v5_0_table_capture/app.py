#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
app.py — Financial Metric Resolver v4 GUI

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
    capture_named_table,
    write_capture_artifacts,
    capture_to_long_df,
    capture_to_wide_df,
    item_dictionary_df,
)
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

DEFAULT_RULES = APP_DIR / "metric_aliases.json"
WORKSPACE = APP_DIR / "workspace"
UPLOAD_DIR = WORKSPACE / "uploads"
RUNS_DIR = WORKSPACE / "runs"
BACKUP_DIR = WORKSPACE / "rule_backups"
REVIEW_DIR = WORKSPACE / "reviews"
CACHE_DIR = WORKSPACE / "cache"
BATCH_DIR = WORKSPACE / "batch_runs"
TABLE_CAPTURE_DIR = WORKSPACE / "table_captures"

for p in [
    WORKSPACE, UPLOAD_DIR, RUNS_DIR, BACKUP_DIR, REVIEW_DIR,
    CACHE_DIR, BATCH_DIR, TABLE_CAPTURE_DIR,
]:
    p.mkdir(parents=True, exist_ok=True)

st.set_page_config(
    page_title="财报指标提取工作台",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="expanded",
)


def init_state() -> None:
    defaults = {
        "rules_path": str(DEFAULT_RULES),
        "active_pdf": None,
        "active_run_dir": None,
        "active_batch_run_dir": None,
        "active_table_capture_dir": None,
        "last_results": None,
        "last_stats": None,
        "last_sha": None,
        "dictionary_dirty": False,
    }
    for k, v in defaults.items():
        st.session_state.setdefault(k, v)


init_state()


# -----------------------------------------------------------------------------
# Utility
# -----------------------------------------------------------------------------

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


# -----------------------------------------------------------------------------
# Sidebar
# -----------------------------------------------------------------------------

st.sidebar.title("📊 财报指标提取工作台")
page = st.sidebar.radio(
    "工作区",
    [
        "总览", "L0 指标字典", "PDF 项目", "运行提取",
        "批量项目", "整表抓取", "人工复核", "报告与审计",
    ],
)

st.sidebar.divider()
st.sidebar.caption("当前规则库")
st.sidebar.code(Path(st.session_state.rules_path).name)
if st.session_state.active_pdf:
    st.sidebar.caption("当前 PDF")
    st.sidebar.code(Path(st.session_state.active_pdf).name)
if st.session_state.active_run_dir:
    st.sidebar.caption("当前运行")
    st.sidebar.code(Path(st.session_state.active_run_dir).name)
if st.session_state.active_table_capture_dir:
    st.sidebar.caption("当前整表抓取")
    st.sidebar.code(Path(st.session_state.active_table_capture_dir).name)


# -----------------------------------------------------------------------------
# Dashboard
# -----------------------------------------------------------------------------

if page == "总览":
    st.title("财报 PDF 指标提取工作台")
    st.caption("L0 规则管理 → PDF 导入 → 单指标/批量指标/整表抓取 → 人工复核 → 报告与审计。")

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

elif page == "整表抓取":
    st.title("整表抓取")
    st.caption(
        "按附注/表名定位整张表，保留原始明细、多层表头、跨页续表和行层级。"
        "v5.0 不强制统一细项语义：raw_item 永久保留，canonical_item 默认留待后续taxonomy/人工裁决。"
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
        value="34",
        help="例如 34。提供后定位更稳，并会尝试以下一个附注编号作为结束边界。",
    )

    c3, c4 = st.columns(2)
    start_override_text = c3.text_input(
        "起始 PDF 页（可选）",
        value="",
        help="留空则自动搜索表名/附注号。PDF页码从1开始。",
    )
    max_pages = c4.number_input(
        "最多连续抓取页数",
        min_value=1,
        max_value=30,
        value=6,
        step=1,
    )

    with st.expander("v5.0 整表抓取输出契约", expanded=False):
        st.code(
            """table_raw_long.csv
- 一行 = 一个原始明细 × 一个表头列
- 保留 raw_item / normalized_item / row_type / parent_section
- 保留 year / scope / restated / page / header_source_page

table_raw_wide.csv
- 一行 = 一个原始明细
- 列 = 多层表头扁平化后的期间/口径
- 保留 unit

table_item_dictionary.csv
- normalized_item 去重清单
- canonical_item/category 默认空白
- 供后续跨公司taxonomy和人工映射使用""",
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
            start_override = (
                int(start_override_text.strip())
                if start_override_text.strip()
                else None
            )
        except ValueError:
            st.error("起始 PDF 页必须是整数。")
            st.stop()

        stamp = dt.datetime.now().strftime("%Y%m%dT%H%M%S")
        safe_title = re.sub(r'[\\/:*?"<>|\\s]+', "_", table_query.strip())[:60]
        run_dir = TABLE_CAPTURE_DIR / f"{stamp}_{safe_title}"
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
                progress.progress(min(0.85, 0.10 + 0.70 * idx / total))
            elif ev == "done":
                progress.progress(0.90)

        try:
            result = capture_named_table(
                pdf_path=chosen_pdf,
                table_query=table_query.strip(),
                note_number=note_number.strip() or None,
                start_page_override=start_override,
                max_pages=int(max_pages),
                progress_callback=capture_progress,
            )
            artifacts = write_capture_artifacts(run_dir, result)
            progress.progress(1.0)
            status.update(
                label=(
                    f"整表抓取完成：PDF p.{result.start_page}–{result.end_page} · "
                    f"{len(result.rows)} 行 · {len(result.columns)} 个数值列"
                ),
                state="complete",
                expanded=False,
            )
            st.session_state.active_table_capture_dir = str(run_dir)

            st.success(
                f"定位：{result.located_title}；实际表格页："
                + ", ".join(map(str, result.pages))
            )

            if result.warnings:
                for w in result.warnings:
                    st.warning(w)

            tabs = st.tabs([
                "宽表预览", "长表预览", "细项字典",
                "列结构", "机器JSON", "下载",
            ])

            with tabs[0]:
                wide_df = capture_to_wide_df(result)
                st.dataframe(wide_df, use_container_width=True, hide_index=True)

            with tabs[1]:
                long_df = capture_to_long_df(result)
                st.dataframe(long_df, use_container_width=True, hide_index=True)

            with tabs[2]:
                dict_df = item_dictionary_df(result)
                st.caption(
                    "v5.0 仅做确定性文本规范化，不把“业务宣传费/营销培训费”等近义但不一定等价的细项强行合并。"
                )
                st.dataframe(dict_df, use_container_width=True, hide_index=True)

            with tabs[3]:
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

            with tabs[4]:
                st.json(result.to_dict())

            with tabs[5]:
                for label, key, filename, mime in [
                    ("下载原始长表 CSV", "raw_long", "table_raw_long.csv", "text/csv"),
                    ("下载原始宽表 CSV", "raw_wide", "table_raw_wide.csv", "text/csv"),
                    ("下载细项字典 CSV", "item_dictionary", "table_item_dictionary.csv", "text/csv"),
                    ("下载 Excel", "xlsx", "table_capture.xlsx", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"),
                    ("下载 JSON", "result_json", "table_capture_result.json", "application/json"),
                    ("下载 HTML 报告", "report_html", "table_report.html", "text/html"),
                ]:
                    path = Path(artifacts[key])
                    st.download_button(
                        label,
                        path.read_bytes(),
                        file_name=filename,
                        mime=mime,
                        key=f"download_{key}_{run_dir.name}",
                    )
        except Exception as exc:
            status.update(label="整表抓取失败", state="error", expanded=True)
            st.exception(exc)

    st.divider()
    st.subheader("历史整表抓取")
    capture_runs = sorted(
        [
            p for p in TABLE_CAPTURE_DIR.iterdir()
            if p.is_dir() and (p / "table_capture_result.json").exists()
        ],
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    if not capture_runs:
        st.caption("暂无历史整表抓取。")
    else:
        hist_name = st.selectbox(
            "选择历史抓取",
            [p.name for p in capture_runs],
            key="table_capture_history",
        )
        hist = next(p for p in capture_runs if p.name == hist_name)
        hc1, hc2, hc3 = st.columns(3)
        hc1.download_button(
            "下载历史宽表",
            (hist / "table_raw_wide.csv").read_bytes(),
            file_name="table_raw_wide.csv",
            mime="text/csv",
        )
        hc2.download_button(
            "下载历史长表",
            (hist / "table_raw_long.csv").read_bytes(),
            file_name="table_raw_long.csv",
            mime="text/csv",
        )
        if (hist / "table_capture.xlsx").exists():
            hc3.download_button(
                "下载历史 Excel",
                (hist / "table_capture.xlsx").read_bytes(),
                file_name="table_capture.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            )


elif page == "人工复核":
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
            "分数": c.get("score"),
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

        with tabs[3]:
            path = run_dir / "adjudicated_long.csv"
            if not path.exists():
                path = run_dir / "batch_long.csv"
            if path.exists():
                df = pd.read_csv(path)
                st.dataframe(df, use_container_width=True, hide_index=True)
                st.download_button("下载最终长表", path.read_bytes(), file_name="adjudicated_long.csv", mime="text/csv")
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

        with tabs[5]:
            path = run_dir / "machine_long.csv"
            if path.exists():
                df = pd.read_csv(path)
                st.dataframe(df, use_container_width=True, hide_index=True)

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

