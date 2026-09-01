"""v6.3 PDF Selection Workspace.

Selection state is an explicit set of absolute paths.  Filters only change the
candidate view; they never silently remove a user's earlier selections.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable


def infer_pdf_dimensions(path: Path) -> dict[str, str]:
    # Uploaded files are stored as ``<short_sha>_<original_name>.pdf``.  The
    # storage identity must never become a user-facing company dimension.
    text = re.sub(r"^[0-9a-fA-F]{12,64}_", "", path.stem)
    years = re.findall(r"(?<!\d)(20\d{2})(?!\d)", text)
    company = re.sub(r"(?<!\d)20\d{2}(?!\d)", "", text)
    company = re.sub(r"[_\-\s（）()【】\[\]]+", " ", company).strip()
    # The year can be followed by the Chinese linker ``年`` before an
    # ``年度报告`` suffix (for example ``中国人寿2023年年度报告``).  Removing the
    # four-digit year first leaves ``中国人寿年年度报告``; the former suffix rule
    # removed only ``年度报告`` and leaked the extra ``年`` into the canonical
    # company identity, which in turn disabled Golden Corpus lookup.
    company = re.sub(r"(?:年)?(?:年度报告|年报|财务报告|报告)$", "", company).strip()
    company = company or "未识别公司"
    return {"company": company, "year": years[0] if years else "未识别年份"}


def company_options(paths: Iterable[Path]) -> list[tuple[str, str]]:
    """One label per normalized company, never per PDF asset/hash."""
    grouped: dict[str, list[str]] = {}
    for path in paths:
        dim = infer_pdf_dimensions(path)
        grouped.setdefault(dim["company"], []).append(dim["year"])
    out=[]
    for company, years in grouped.items():
        known=sorted({x for x in years if x != "未识别年份"})
        span=f"{known[0]}–{known[-1]}" if len(known)>1 else (known[0] if known else "年份待识别")
        out.append((company, f"{company}（{len(years)}份，{span}）"))
    return sorted(out, key=lambda x:x[0])


def filter_pdfs(paths: Iterable[Path], *, companies: set[str] | None = None,
                years: set[str] | None = None, include: str = "", exclude: str = "") -> list[Path]:
    out: list[Path] = []
    excluded = [x.strip().lower() for x in exclude.replace("，", ",").split(",") if x.strip()]
    needle = include.strip().lower()
    for path in paths:
        d = infer_pdf_dimensions(path)
        name = path.name.lower()
        if companies and d["company"] not in companies:
            continue
        if years and d["year"] not in years:
            continue
        if needle and needle not in name:
            continue
        if any(token in name for token in excluded):
            continue
        out.append(path)
    return out


@dataclass(frozen=True)
class SelectionSummary:
    pdf_count: int
    company_count: int
    year_range: str


def selection_summary(paths: Iterable[Path]) -> SelectionSummary:
    dims = [infer_pdf_dimensions(p) for p in paths]
    years = sorted({d["year"] for d in dims if d["year"] != "未识别年份"})
    return SelectionSummary(len(dims), len({d["company"] for d in dims}),
                            f"{years[0]}–{years[-1]}" if len(years) > 1 else (years[0] if years else "未识别"))


def render_pdf_selection_workspace(paths: list[Path], *, key_prefix: str) -> list[Path]:
    """Streamlit adapter kept thin; selection semantics are testable above."""
    import streamlit as st
    selected_key = f"{key_prefix}_selected_paths"
    st.session_state.setdefault(selected_key, set())
    mode = st.radio("PDF 来源", ["全部", "按公司", "按年份", "手工选择"], horizontal=True, key=f"{key_prefix}_mode")
    dims = {str(p): infer_pdf_dimensions(p) for p in paths}
    company_labels = dict(company_options(paths))
    companies = list(company_labels)
    years = sorted({d["year"] for d in dims.values()}, reverse=True)
    chosen_companies = set(st.multiselect("公司", companies, format_func=lambda x: company_labels[x], key=f"{key_prefix}_companies")) if mode == "按公司" else set()
    chosen_years = set(st.multiselect("年份", years, key=f"{key_prefix}_years")) if mode == "按年份" else set()
    include = st.text_input("文件名包含", key=f"{key_prefix}_include")
    exclude = st.text_input("排除关键词（逗号分隔）", placeholder="摘要, 英文版", key=f"{key_prefix}_exclude")
    matched = filter_pdfs(paths, companies=chosen_companies, years=chosen_years, include=include, exclude=exclude)
    if mode == "手工选择":
        manual = st.multiselect("手工选择 PDF", paths, format_func=lambda p: p.name, key=f"{key_prefix}_manual")
        st.session_state[selected_key].update(map(str, manual))
    c1, c2, c3 = st.columns(3)
    c1.metric("匹配 PDF", len(matched))
    if c2.button("全选当前筛选结果", key=f"{key_prefix}_all"):
        st.session_state[selected_key].update(map(str, matched))
    if c3.button("清空选择", key=f"{key_prefix}_clear"):
        st.session_state[selected_key] = set()
    valid = {str(p) for p in paths}
    st.session_state[selected_key].intersection_update(valid)
    selected = [p for p in paths if str(p) in st.session_state[selected_key]]
    summary = selection_summary(selected)
    st.caption(f"已选 {summary.pdf_count} 份 PDF · {summary.company_count} 家公司 · 年份 {summary.year_range}；筛选变更不会清除已选集合。")
    return selected
