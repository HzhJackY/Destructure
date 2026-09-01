#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations

import dataclasses
import hashlib
import json
import os
import re
import time
from concurrent.futures import ProcessPoolExecutor, wait, FIRST_COMPLETED
from multiprocessing import Manager
from pathlib import Path
from typing import Any, Callable, Optional

import pandas as pd

from fast_index import (
    PageIndexRecord,
    build_fast_index,
    retrieve_candidate_pages,
)
from financial_metric_pdf_resolver import (
    PDFBlock,
    RuleBook,
    extract_pdf_blocks,
    apply_cross_page_table_context,
    resolve_metric,
)
from llm_providers import build_llm_provider


PARSER_CACHE_VERSION = "v4.3-deep-1"


def infer_company_year(pdf_path: Path, first_text: str = "") -> tuple[str, str]:
    """
    Infer document-level company/year.

    Uploaded files are stored as:
        <12hex>_<original_filename>.pdf
    The storage SHA prefix is internal identity and must NEVER enter company name.
    """
    stem = pdf_path.stem
    clean_stem = re.sub(r"^[0-9a-fA-F]{12}_", "", stem)

    # Prefer explicit year in original filename; otherwise use early document text.
    year_match = (
        re.search(r"(20\d{2})", clean_stem)
        or re.search(r"(20\d{2})", first_text[:8000])
    )
    year = year_match.group(1) if year_match else ""

    company = re.sub(r"20\d{2}", "", clean_stem)
    company = re.sub(
        r"(年度信息披露报告|年度报告|年报|年度财务报告|信息披露报告|报告|财务报表|偿付能力报告)",
        "",
        company,
        flags=re.I,
    )
    company = re.sub(r"[_\-\s]+", " ", company).strip(" _-")
    return company or clean_stem, year


def display_pdf_name(pdf_name: str) -> str:
    """Remove internal 12-char storage hash from user-facing PDF names."""
    return re.sub(r"^[0-9a-fA-F]{12}_", "", str(pdf_name or ""))


def _block_to_dict(b: PDFBlock) -> dict[str, Any]:
    return dataclasses.asdict(b)


def _block_from_dict(d: dict[str, Any]) -> PDFBlock:
    return PDFBlock(**d)


def _page_cache_path(cache_root: Path, pdf_sha: str, page: int) -> Path:
    return cache_root / pdf_sha / "deep_pages" / f"{PARSER_CACHE_VERSION}_p{page:05d}.json"


def _ocr_block_from_record(rec: PageIndexRecord) -> Optional[PDFBlock]:
    if not rec.ocr_used or not rec.ocr_rows:
        return None
    return PDFBlock(
        block_id=f"p{rec.page}_ocr",
        page=rec.page,
        source_method="pymupdf_ocr_words",
        table_type="未知表",
        unit_hint=None,
        rows=rec.ocr_rows,
        page_text_preview=rec.text[:500],
    )


def load_or_build_deep_blocks(
    pdf_path: Path,
    pdf_sha: str,
    selected_pages: set[int],
    index_records: list[PageIndexRecord],
    cache_root: Path,
    progress_callback: Optional[Callable[[dict[str, Any]], None]] = None,
) -> tuple[list[PDFBlock], dict[str, Any]]:
    blocks: list[PDFBlock] = []
    missing: set[int] = set()
    cache_hits = 0

    for page in sorted(selected_pages):
        cp = _page_cache_path(cache_root, pdf_sha, page)
        if cp.exists():
            payload = json.loads(cp.read_text(encoding="utf-8"))
            blocks.extend(_block_from_dict(x) for x in payload.get("blocks", []))
            cache_hits += 1
        else:
            missing.add(page)

    parse_stats: dict[str, Any] = {
        "selected_pages": len(selected_pages),
        "deep_cache_hits": cache_hits,
        "deep_pages_parsed": len(missing),
    }

    if missing:
        new_blocks, raw_stats = extract_pdf_blocks(
            pdf_path,
            progress_callback=progress_callback,
            page_numbers=missing,
        )
        by_page: dict[int, list[PDFBlock]] = {p: [] for p in missing}
        for b in new_blocks:
            by_page.setdefault(b.page, []).append(b)
        for page in missing:
            cp = _page_cache_path(cache_root, pdf_sha, page)
            cp.parent.mkdir(parents=True, exist_ok=True)
            cp.write_text(
                json.dumps(
                    {"page": page, "blocks": [_block_to_dict(x) for x in by_page.get(page, [])]},
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
        blocks.extend(new_blocks)
        parse_stats["raw_deep_stats"] = raw_stats

    # Add OCR word-row blocks for scanned pages. These are independently marked.
    rec_map = {r.page: r for r in index_records}
    ocr_added = 0
    for page in sorted(selected_pages):
        rec = rec_map.get(page)
        if rec:
            ob = _ocr_block_from_record(rec)
            if ob is not None:
                blocks.append(ob)
                ocr_added += 1
    parse_stats["ocr_blocks_added"] = ocr_added

    # Critical for cache compatibility: cached page N and newly parsed page N+1
    # must still be evaluated together as a possible cross-page continued table.
    blocks = apply_cross_page_table_context(blocks)
    parse_stats["cross_page_context_blocks"] = sum(
        1 for b in blocks if b.header_source_page is not None
    )

    return blocks, parse_stats


def prepare_fast_blocks(
    pdf_path: Path,
    metrics: list[str],
    rules_path: Path,
    cache_root: Path,
    ocr_mode: str = "off",
    ocr_language: str = "chi_sim+eng",
    ocr_dpi: int = 150,
    min_native_chars: int = 40,
    top_pages_per_metric: int = 8,
    neighbor_radius: int = 1,
    index_progress_callback: Optional[Callable[[dict[str, Any]], None]] = None,
    deep_progress_callback: Optional[Callable[[dict[str, Any]], None]] = None,
) -> tuple[list[PDFBlock], dict[str, Any], dict[str, Any]]:
    rb = RuleBook(rules_path)
    records, index_meta = build_fast_index(
        pdf_path=pdf_path,
        cache_root=cache_root,
        ocr_mode=ocr_mode,
        ocr_language=ocr_language,
        ocr_dpi=ocr_dpi,
        min_native_chars=min_native_chars,
        progress_callback=index_progress_callback,
    )

    metric_terms: dict[str, dict[str, list[str]]] = {}
    for metric in metrics:
        standard, cfg, _ = rb.normalize_metric(metric)
        if standard and cfg:
            metric_terms[metric] = {
                "exact": [standard, metric],
                "aliases": cfg.get("aliases", []) + cfg.get("soft_aliases", []),
                "keywords": cfg.get("keywords", []),
            }
        else:
            metric_terms[metric] = {
                "exact": [metric],
                "aliases": [],
                "keywords": [x for x in re.split(r"[\s/]+", metric) if x],
            }

    selected_pages, retrieval = retrieve_candidate_pages(
        records,
        metric_terms,
        top_pages_per_metric=top_pages_per_metric,
        neighbor_radius=neighbor_radius,
    )

    # Cross-page table context requires the immediately preceding page even when
    # GUI neighbor_radius=0. These are context-only deep pages, not extra metric hits.
    candidate_pages = set(selected_pages)
    context_pages = {
        p - 1
        for p in candidate_pages
        if p > 1
    }
    selected_pages = candidate_pages | context_pages

    # Guardrail: if nothing was recalled, do not silently deep-parse all pages.
    # Return no blocks and let the resolver surface UNRESOLVED/RULE GAP.
    pdf_sha = index_meta["pdf_sha256"]
    blocks, deep_meta = load_or_build_deep_blocks(
        pdf_path=pdf_path,
        pdf_sha=pdf_sha,
        selected_pages=selected_pages,
        index_records=records,
        cache_root=cache_root,
        progress_callback=deep_progress_callback,
    )
    meta = {
        "index": index_meta,
        "retrieval": retrieval,
        "candidate_pages": sorted(candidate_pages),
        "context_pages": sorted(context_pages - candidate_pages),
        "selected_pages": sorted(selected_pages),
        "deep": deep_meta,
    }
    return blocks, meta, {"records": records}


def _parse_value_year(header_context: str) -> Optional[str]:
    years = re.findall(r"(20\d{2})", header_context or "")
    return str(max(map(int, years))) if years else None


def _parse_value_year(header_context: str) -> Optional[str]:
    years = re.findall(r"(20\d{2})", header_context or "")
    return str(max(map(int, years))) if years else None


def _value_fields(result) -> dict[str, Any]:
    pv = result.primary_value
    selected = result.selected
    parsed = pv.parsed_number if pv else None
    yuan = pv.value_yuan if pv else None
    raw = pv.raw if pv else None
    original_unit = pv.unit_original if pv else None

    # `value` is the normalized analysis value:
    # - monetary values with reliable unit => yuan
    # - percentage => percent points, e.g. 124.61
    # - otherwise parsed raw number
    display = yuan if yuan is not None else parsed if parsed is not None else raw
    output_unit = "元" if yuan is not None else original_unit

    period_raw = pv.header_context if pv else None
    return {
        "value": display,
        "value_raw": raw,
        "value_parsed": parsed,
        "value_yuan": yuan,
        "unit": output_unit,
        "original_unit": original_unit,
        "value_period_raw": period_raw,
        "value_year": _parse_value_year(period_raw or ""),
        "value_period_confidence": result.primary_value_confidence,
        "page": selected.page if selected else None,
        "matched_label": selected.label if selected else None,
        "source_method": selected.source_method if selected else None,
    }


def process_pdf_job(job: dict[str, Any]) -> dict[str, Any]:
    started = time.perf_counter()
    pdf_path = Path(job["pdf_path"])
    rules_path = Path(job["rules_path"])
    cache_root = Path(job["cache_root"])
    metrics = list(job["metrics"])
    progress_queue = job.get("_progress_queue")

    def emit(event: str, **payload: Any) -> None:
        if progress_queue is None:
            return
        try:
            progress_queue.put({
                "event": event,
                "pdf_name": pdf_path.name,
                "pdf_path": str(pdf_path),
                **payload,
            })
        except Exception:
            pass

    def index_cb(evt: dict[str, Any]) -> None:
        emit("worker_index", payload=evt)

    def deep_cb(evt: dict[str, Any]) -> None:
        emit("worker_deep", payload=evt)

    emit("worker_start", message="任务开始")

    blocks, fast_meta, holder = prepare_fast_blocks(
        pdf_path=pdf_path,
        metrics=metrics,
        rules_path=rules_path,
        cache_root=cache_root,
        ocr_mode=job.get("ocr_mode", "off"),
        ocr_language=job.get("ocr_language", "chi_sim+eng"),
        ocr_dpi=int(job.get("ocr_dpi", 150)),
        min_native_chars=int(job.get("min_native_chars", 40)),
        top_pages_per_metric=int(job.get("top_pages_per_metric", 8)),
        neighbor_radius=int(job.get("neighbor_radius", 1)),
        index_progress_callback=index_cb,
        deep_progress_callback=deep_cb,
    )

    records = holder["records"]
    first_text = "\n".join(r.text for r in records[:3])
    inferred_company, inferred_year = infer_company_year(pdf_path, first_text)
    company = job.get("company") or inferred_company
    document_year = str(job.get("year") or inferred_year)
    target_year = int(document_year) if document_year.isdigit() and len(document_year) == 4 else None

    llm = None
    if job.get("llm_enabled"):
        llm = build_llm_provider(
            job.get("llm_provider", "deepseek"),
            model=(job.get("llm_model") or None),
        )

    rb = RuleBook(rules_path)
    sha = fast_meta["index"]["pdf_sha256"]
    rows = []
    details = []

    for metric_idx, metric in enumerate(metrics, start=1):
        emit(
            "worker_metric_start",
            metric=metric,
            metric_index=metric_idx,
            metric_total=len(metrics),
            message=f"处理指标 {metric_idx}/{len(metrics)}：{metric}",
        )
        res = resolve_metric(
            pdf_path=pdf_path,
            sha=sha,
            blocks=blocks,
            rulebook=rb,
            metric_input=metric,
            user_aliases=[],
            llm=llm,
            top_k=int(job.get("top_k", 12)),
            high_threshold=float(job.get("high_threshold", 0.88)),
            medium_threshold=float(job.get("medium_threshold", 0.76)),
            margin_threshold=float(job.get("margin_threshold", 0.10)),
            target_year=target_year,
        )

        if res.status == "RESOLVED" and res.primary_value is None:
            raise RuntimeError(
                f"Invariant violation: {metric} is RESOLVED but primary_value is None"
            )

        row = {
            "metric": metric,
            "standard_metric": res.standard_metric,
            "status": res.status,
            "layer": res.layer,
            "confidence": res.confidence,
            "reason": res.reason,
            "warnings": " | ".join(res.warnings),
            **_value_fields(res),
        }
        rows.append(row)
        details.append(res.to_dict())
        emit(
            "worker_metric_done",
            metric=metric,
            metric_index=metric_idx,
            metric_total=len(metrics),
            status=res.status,
            layer=res.layer,
            confidence=res.confidence,
            page=(res.selected.page if res.selected else None),
            message=f"{metric}: {res.status} / {res.layer}",
        )

    emit("worker_done", elapsed_seconds=round(time.perf_counter() - started, 3), message="任务完成")

    return {
        "pdf_path": str(pdf_path),
        "pdf_name": pdf_path.name,
        "pdf_sha256": sha,
        "company": company,
        "document_year": document_year,
        "year": document_year,
        "results": rows,
        "resolution_details": details,
        "llm_enabled": bool(job.get("llm_enabled")),
        "llm_provider": job.get("llm_provider") if job.get("llm_enabled") else None,
        "llm_model": job.get("llm_model") if job.get("llm_enabled") else None,
        "fast_meta": {
            "selected_pages": fast_meta["selected_pages"],
            "index": fast_meta["index"],
            "deep": fast_meta["deep"],
        },
        "elapsed_seconds": round(time.perf_counter() - started, 3),
    }


def _is_missing(value: Any) -> bool:
    if value is None:
        return True
    try:
        if pd.isna(value):
            return True
    except Exception:
        pass
    s = str(value).strip()
    return s == "" or s.lower() in {"nan", "none", "nat"}


def _clean_year(value: Any) -> Optional[str]:
    if _is_missing(value):
        return None
    s = str(value).strip()
    m = re.search(r"(20\d{2})", s)
    return m.group(1) if m else s


def _clean_company_name(value: Any) -> str:
    s = str(value or "").strip()
    # Repair old v4.3-v4.5 outputs where storage SHA leaked into company.
    s = re.sub(r"^[0-9a-fA-F]{12}[ _-]+", "", s)
    return s.strip()


def _document_key_series(df: pd.DataFrame) -> pd.Series:
    return df.apply(
        lambda row: " ".join(
            x for x in [
                str(row.get("company") or "").strip(),
                str(row.get("effective_year") or "").strip(),
            ]
            if x and str(x).lower() not in {"nan", "none"}
        ),
        axis=1,
    )


def _metric_unit_value(series: pd.Series) -> str:
    units = []
    for value in series.tolist():
        if _is_missing(value):
            continue
        s = str(value).strip()
        if s and s not in units:
            units.append(s)

    if not units:
        return ""
    if len(units) == 1:
        return units[0]

    # Mixed dimensions in one metric row are unsafe for comparative analysis.
    return "REVIEW_REQUIRED[" + "|".join(units) + "]"


def build_wide_with_unit_column(
    long_df: pd.DataFrame,
    value_col: str,
    unit_col: str,
) -> pd.DataFrame:
    """
    Wide layout:
        metric | unit | Company 2024 | Company 2025 | ...

    One row per metric. Unit is a dedicated column, not a synthetic data row.
    """
    if long_df.empty:
        return pd.DataFrame()

    pivot = long_df.copy()
    pivot["document"] = _document_key_series(pivot)
    blank_doc = pivot["document"].astype(str).str.strip().eq("")
    if blank_doc.any():
        pivot.loc[blank_doc, "document"] = (
            pivot.loc[blank_doc, "pdf_name"].astype(str)
        )

    value_wide = pivot.pivot_table(
        index="metric",
        columns="document",
        values=value_col,
        aggfunc="first",
        dropna=False,
    ).reset_index()
    value_wide.columns.name = None

    units = (
        pivot.groupby("metric", sort=False)[unit_col]
        .apply(_metric_unit_value)
        .rename("unit")
        .reset_index()
    )

    result = units.merge(value_wide, on="metric", how="outer")

    # Preserve original metric order.
    metric_order = []
    for metric in long_df["metric"].tolist():
        if metric not in metric_order:
            metric_order.append(metric)
    result["_order"] = result["metric"].map(
        {metric: i for i, metric in enumerate(metric_order)}
    )
    result = result.sort_values("_order").drop(columns=["_order"]).reset_index(drop=True)

    # Contract: first two columns are always metric, unit.
    ordered_cols = ["metric", "unit"] + [
        c for c in result.columns
        if c not in {"metric", "unit"}
    ]
    return result[ordered_cols]


def aggregate_batch_results(doc_results: list[dict[str, Any]]) -> tuple[pd.DataFrame, pd.DataFrame]:
    long_rows = []
    for doc in doc_results:
        document_year = _clean_year(doc.get("document_year", doc.get("year", "")))
        company = _clean_company_name(doc.get("company", ""))
        pdf_name = display_pdf_name(doc.get("pdf_name", ""))

        for r in doc.get("results", []):
            value_year = _clean_year(r.get("value_year"))
            effective_year = value_year or document_year

            long_rows.append({
                "company": company,
                "document_year": document_year,
                "value_year": value_year,
                "effective_year": effective_year,
                "year_source": "table_header" if value_year else "document_fallback",
                "pdf_name": pdf_name,
                "metric": r.get("metric"),
                "standard_metric": r.get("standard_metric"),
                "value": r.get("value"),
                "value_raw": r.get("value_raw"),
                "value_yuan": r.get("value_yuan"),
                "unit": r.get("unit"),
                "original_unit": r.get("original_unit"),
                "value_period_raw": r.get("value_period_raw"),
                "value_period_confidence": r.get("value_period_confidence"),
                "status": r.get("status"),
                "layer": r.get("layer"),
                "confidence": r.get("confidence"),
                "page": r.get("page"),
                "matched_label": r.get("matched_label"),
                "source_method": r.get("source_method"),
                "warnings": r.get("warnings"),
                "pdf_sha256": doc.get("pdf_sha256"),
            })

    long_df = pd.DataFrame(long_rows)
    if long_df.empty:
        return long_df, pd.DataFrame()

    wide_df = build_wide_with_unit_column(
        long_df,
        value_col="value",
        unit_col="unit",
    )
    return long_df, wide_df


def _batch_report_markdown(doc_results: list[dict[str, Any]], long_df: pd.DataFrame) -> str:
    lines = [
        "# Batch Financial Metric Extraction Report",
        "",
        f"- Documents: {len(doc_results)}",
        f"- Rows: {len(long_df)}",
        "",
        "## Summary",
        "",
    ]
    if not long_df.empty:
        cols = [
            "company", "document_year", "value_year", "metric", "value_raw", "unit",
            "status", "layer", "confidence", "page", "matched_label", "source_method",
        ]
        view = long_df[[c for c in cols if c in long_df.columns]].fillna("")
        lines.append(view.to_markdown(index=False))
    lines += ["", "## Document details", ""]
    for doc in doc_results:
        lines.append(f"### {doc.get('company','')} {doc.get('document_year','')} — {doc.get('pdf_name','')}")
        lines.append("")
        for detail in doc.get("resolution_details", []):
            sel = detail.get("selected") or {}
            pv = detail.get("primary_value") or {}
            lines.append(
                f"- **{detail.get('metric_input')}**: {detail.get('status')} / {detail.get('layer')} "
                f"/ conf={detail.get('confidence')} / p.{sel.get('page','-')} / "
                f"`{sel.get('label','-')}` / value=`{pv.get('raw','-')}`"
            )
        lines.append("")
    return "\n".join(lines)


def _batch_report_html(doc_results: list[dict[str, Any]], long_df: pd.DataFrame) -> str:
    table_html = long_df.to_html(index=False, escape=True) if not long_df.empty else "<p>No results.</p>"
    detail_parts = []
    for doc in doc_results:
        rows = []
        for d in doc.get("resolution_details", []):
            sel = d.get("selected") or {}
            pv = d.get("primary_value") or {}
            warnings = "<br>".join(d.get("warnings") or [])
            rows.append(
                "<tr>"
                f"<td>{d.get('metric_input','')}</td>"
                f"<td>{d.get('status','')}</td>"
                f"<td>{d.get('layer','')}</td>"
                f"<td>{d.get('confidence','')}</td>"
                f"<td>{sel.get('page','')}</td>"
                f"<td>{sel.get('label','')}</td>"
                f"<td>{pv.get('raw','')}</td>"
                f"<td>{pv.get('header_context','')}</td>"
                f"<td>{warnings}</td>"
                "</tr>"
            )
        detail_parts.append(
            f"<h2>{doc.get('company','')} {doc.get('document_year','')} — {doc.get('pdf_name','')}</h2>"
            "<table><thead><tr><th>Metric</th><th>Status</th><th>Layer</th><th>Confidence</th>"
            "<th>Page</th><th>Matched label</th><th>Value</th><th>Period</th><th>Warnings</th></tr></thead>"
            f"<tbody>{''.join(rows)}</tbody></table>"
        )
    return f"""<!doctype html><html><head><meta charset="utf-8">
<style>
body{{font-family:Arial,'Microsoft YaHei',sans-serif;margin:24px;color:#172033}}
table{{border-collapse:collapse;width:100%;margin:14px 0 28px}}
th,td{{border:1px solid #d8dee9;padding:7px;vertical-align:top;font-size:13px}}
th{{background:#f4f7fb;position:sticky;top:0}}
h1,h2{{color:#102a43}}
</style></head><body>
<h1>Batch Financial Metric Extraction Report</h1>
<h2>Aggregate table</h2>{table_html}
{''.join(detail_parts)}
</body></html>"""


def write_batch_artifacts(
    output_dir: Path,
    doc_results: list[dict[str, Any]],
) -> tuple[pd.DataFrame, pd.DataFrame]:
    output_dir.mkdir(parents=True, exist_ok=True)

    (output_dir / "batch_results.json").write_text(
        json.dumps(doc_results, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    audit_path = output_dir / "audit.jsonl"
    with audit_path.open("w", encoding="utf-8") as f:
        for doc in doc_results:
            for detail in doc.get("resolution_details", []):
                record = {
                    "company": doc.get("company"),
                    "document_year": doc.get("document_year"),
                    "pdf_name": doc.get("pdf_name"),
                    "pdf_sha256": doc.get("pdf_sha256"),
                    **detail,
                }
                f.write(json.dumps(record, ensure_ascii=False) + "\n")

    # Initial final view: only machine RESOLVED values materialize.
    adjudicated_long, adjudicated_wide = write_adjudicated_artifacts(
        output_dir, doc_results, reviews=[]
    )

    (output_dir / "batch_report.md").write_text(
        _batch_report_markdown(doc_results, adjudicated_long), encoding="utf-8"
    )
    (output_dir / "batch_report.html").write_text(
        _batch_report_html(doc_results, adjudicated_long), encoding="utf-8"
    )
    return adjudicated_long, adjudicated_wide


def load_human_reviews(review_path: Path) -> list[dict[str, Any]]:
    if not review_path.exists():
        return []
    rows: list[dict[str, Any]] = []
    for line in review_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            rows.append(json.loads(line))
        except Exception:
            continue
    return rows


def _review_key(record: dict[str, Any]) -> tuple[str, str]:
    doc_key = (
        str(record.get("pdf_sha256") or "")
        or str(record.get("pdf_name") or "")
    )
    metric = str(record.get("metric_input") or record.get("metric") or "")
    return doc_key, metric


def _latest_review_map(reviews: list[dict[str, Any]]) -> dict[tuple[str, str], dict[str, Any]]:
    out: dict[tuple[str, str], dict[str, Any]] = {}
    for r in reviews:
        out[_review_key(r)] = r
    return out


def _machine_row_lookup(doc_results: list[dict[str, Any]]) -> dict[tuple[str, str], dict[str, Any]]:
    lookup: dict[tuple[str, str], dict[str, Any]] = {}
    for doc in doc_results:
        doc_key = str(doc.get("pdf_sha256") or doc.get("pdf_name") or "")
        for row in doc.get("results", []):
            lookup[(doc_key, str(row.get("metric") or ""))] = {
                "doc": doc,
                "row": row,
            }
    return lookup


def materialize_adjudicated_results(
    doc_results: list[dict[str, Any]],
    reviews: list[dict[str, Any]],
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """
    Returns:
      machine_long, machine_wide, adjudicated_long, adjudicated_wide

    Safety:
    - machine outputs are immutable evidence.
    - unreviewed machine values enter final only if machine status == RESOLVED.
    - REVIEW_REQUIRED / UNRESOLVED stay blank until human confirmation.
    - human override uses the frozen chosen_primary_value snapshot stored in review log.
    """
    machine_long, machine_wide = aggregate_batch_results(doc_results)
    latest = _latest_review_map(reviews)

    final_rows: list[dict[str, Any]] = []
    for _, m in machine_long.iterrows():
        doc_key = str(m.get("pdf_sha256") or m.get("pdf_name") or "")
        metric = str(m.get("metric") or "")
        review = latest.get((doc_key, metric))

        machine_status = str(m.get("status") or "")
        machine_value = m.get("value")
        machine_year = _clean_year(m.get("value_year"))
        machine_period = m.get("value_period_raw")
        machine_label = m.get("matched_label")
        machine_page = m.get("page")
        machine_source = m.get("source_method")

        final_value = machine_value if machine_status == "RESOLVED" else None
        final_value_raw = m.get("value_raw") if machine_status == "RESOLVED" else None
        final_value_yuan = m.get("value_yuan") if machine_status == "RESOLVED" else None
        final_unit = m.get("unit") if machine_status == "RESOLVED" else None
        final_original_unit = m.get("original_unit") if machine_status == "RESOLVED" else None
        final_year = machine_year if machine_status == "RESOLVED" else None
        final_period = machine_period if machine_status == "RESOLVED" else None
        final_label = machine_label if machine_status == "RESOLVED" else None
        final_page = machine_page if machine_status == "RESOLVED" else None
        final_source_method = machine_source if machine_status == "RESOLVED" else None
        resolution_source = "MACHINE" if machine_status == "RESOLVED" else "UNRESOLVED"
        review_status = "NOT_REVIEWED"

        if review:
            review_status = str(review.get("review_status") or review.get("verdict") or "")
            if review_status in {"CONFIRMED_AUTO", "确认自动结果"}:
                final_value = machine_value
                final_value_raw = m.get("value_raw")
                final_value_yuan = m.get("value_yuan")
                final_unit = m.get("unit")
                final_original_unit = m.get("original_unit")
                final_year = machine_year
                final_period = machine_period
                final_label = machine_label
                final_page = machine_page
                final_source_method = machine_source
                resolution_source = "HUMAN_REVIEW"
                review_status = "CONFIRMED_AUTO"

            elif review_status in {"CONFIRMED_OVERRIDE", "改选候选"}:
                pv = review.get("chosen_primary_value") or {}
                cand = review.get("chosen_candidate") or {}
                parsed = pv.get("parsed_number")
                yuan = pv.get("value_yuan")
                raw = pv.get("raw")
                final_value = yuan if yuan is not None else parsed if parsed is not None else raw
                final_value_raw = raw
                final_value_yuan = yuan
                final_original_unit = pv.get("unit_original")
                final_unit = "元" if yuan is not None else final_original_unit
                final_period = pv.get("header_context")
                years = re.findall(r"(20\d{2})", str(final_period or ""))
                final_year = str(max(map(int, years))) if years else review.get("chosen_value_year")
                final_label = cand.get("label")
                final_page = cand.get("page")
                final_source_method = cand.get("source_method")
                resolution_source = "HUMAN_REVIEW"
                review_status = "CONFIRMED_OVERRIDE"

            elif review_status in {"REJECTED", "驳回/未找到"}:
                final_value = None
                final_value_raw = None
                final_value_yuan = None
                final_unit = None
                final_original_unit = None
                final_year = None
                final_period = None
                final_label = None
                final_page = None
                final_source_method = None
                resolution_source = "HUMAN_REVIEW"
                review_status = "REJECTED"

            else:
                final_value = None
                final_value_raw = None
                final_value_yuan = None
                final_unit = None
                final_original_unit = None
                final_year = None
                final_period = None
                final_label = None
                final_page = None
                final_source_method = None
                resolution_source = "HUMAN_REVIEW"
                review_status = "UNRESOLVED"

        final_year = _clean_year(final_year)
        document_year_clean = _clean_year(m.get("document_year"))
        effective_year = final_year or document_year_clean

        final_rows.append({
            "company": m.get("company"),
            "document_year": document_year_clean,
            "value_year": final_year,
            "effective_year": effective_year,
            "year_source": "table_header" if final_year else "document_fallback",
            "pdf_name": m.get("pdf_name"),
            "pdf_sha256": m.get("pdf_sha256"),
            "metric": metric,
            "standard_metric": m.get("standard_metric"),

            "machine_value": machine_value,
            "machine_value_raw": m.get("value_raw"),
            "machine_value_yuan": m.get("value_yuan"),
            "machine_unit": m.get("unit"),
            "machine_original_unit": m.get("original_unit"),
            "machine_status": machine_status,
            "machine_layer": m.get("layer"),
            "machine_confidence": m.get("confidence"),
            "machine_page": machine_page,
            "machine_label": machine_label,
            "machine_period_raw": machine_period,
            "machine_source_method": machine_source,

            "final_value": final_value,
            "final_value_raw": final_value_raw,
            "final_value_yuan": final_value_yuan,
            "final_unit": final_unit,
            "final_original_unit": final_original_unit,
            "final_page": final_page,
            "final_label": final_label,
            "final_period_raw": final_period,
            "final_source_method": final_source_method,

            # Backward-compatible final-view aliases. batch_long.csv is the
            # adjudicated research table, so generic fields point to FINAL values.
            "value": final_value,
            "value_raw": final_value_raw,
            "value_yuan": final_value_yuan,
            "unit": final_unit,
            "original_unit": final_original_unit,
            "page": final_page,
            "matched_label": final_label,
            "source_method": final_source_method,
            "status": "RESOLVED" if final_value is not None else (
                "REJECTED" if review_status == "REJECTED" else "UNRESOLVED"
            ),
            "layer": "HUMAN" if resolution_source == "HUMAN_REVIEW" else m.get("layer"),
            "confidence": 1.0 if resolution_source == "HUMAN_REVIEW" and final_value is not None else m.get("confidence"),

            "resolution_source": resolution_source,
            "review_status": review_status,
            "reviewed_at": review.get("timestamp") if review else None,
            "review_note": review.get("note") if review else None,
        })

    adjudicated_long = pd.DataFrame(final_rows)
    if adjudicated_long.empty:
        return machine_long, machine_wide, adjudicated_long, pd.DataFrame()

    adjudicated_wide = build_wide_with_unit_column(
        adjudicated_long,
        value_col="final_value",
        unit_col="final_unit",
    )

    return machine_long, machine_wide, adjudicated_long, adjudicated_wide


def write_adjudicated_artifacts(
    output_dir: Path,
    doc_results: list[dict[str, Any]],
    reviews: Optional[list[dict[str, Any]]] = None,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    reviews = reviews or []
    machine_long, machine_wide, adjudicated_long, adjudicated_wide = materialize_adjudicated_results(
        doc_results, reviews
    )

    machine_long.to_csv(output_dir / "machine_long.csv", index=False, encoding="utf-8-sig")
    machine_wide.to_csv(output_dir / "machine_wide.csv", index=False, encoding="utf-8-sig")

    adjudicated_long.to_csv(output_dir / "adjudicated_long.csv", index=False, encoding="utf-8-sig")
    adjudicated_wide.to_csv(output_dir / "adjudicated_wide.csv", index=False, encoding="utf-8-sig")

    # Backward-compatible "batch_*" files represent FINAL adjudicated views.
    adjudicated_long.to_csv(output_dir / "batch_long.csv", index=False, encoding="utf-8-sig")
    adjudicated_wide.to_csv(output_dir / "batch_wide.csv", index=False, encoding="utf-8-sig")

    # Remove obsolete v4.8 values-only artifacts if refreshing an older run directory.
    for obsolete in [
        "machine_wide_values_only.csv",
        "adjudicated_wide_values_only.csv",
    ]:
        (output_dir / obsolete).unlink(missing_ok=True)

    review_df = pd.DataFrame(reviews)
    with pd.ExcelWriter(output_dir / "batch_results.xlsx", engine="openpyxl") as writer:
        machine_long.to_excel(writer, sheet_name="machine_long", index=False)
        machine_wide.to_excel(writer, sheet_name="machine_wide", index=False)
        adjudicated_long.to_excel(writer, sheet_name="adjudicated_long", index=False)
        adjudicated_wide.to_excel(writer, sheet_name="adjudicated_wide", index=False)
        review_df.to_excel(writer, sheet_name="review_log", index=False)

    return adjudicated_long, adjudicated_wide



def refresh_adjudicated_artifacts(output_dir: Path) -> tuple[pd.DataFrame, pd.DataFrame]:
    doc_results = json.loads((output_dir / "batch_results.json").read_text(encoding="utf-8"))
    reviews = load_human_reviews(output_dir / "human_review.jsonl")
    adjudicated_long, adjudicated_wide = write_adjudicated_artifacts(
        output_dir, doc_results, reviews
    )

    # Refresh human-facing reports so they reflect the latest adjudicated final table.
    (output_dir / "batch_report.md").write_text(
        _batch_report_markdown(doc_results, adjudicated_long),
        encoding="utf-8",
    )
    (output_dir / "batch_report.html").write_text(
        _batch_report_html(doc_results, adjudicated_long),
        encoding="utf-8",
    )
    return adjudicated_long, adjudicated_wide



def run_batch_jobs(
    jobs: list[dict[str, Any]],
    max_workers: int = 2,
    progress_callback: Optional[Callable[[dict[str, Any]], None]] = None,
) -> list[dict[str, Any]]:
    if not jobs:
        return []

    if max_workers <= 1 or len(jobs) <= 1:
        out = []
        for i, job in enumerate(jobs, start=1):
            if progress_callback:
                progress_callback({
                    "event": "job_start",
                    "index": i,
                    "total": len(jobs),
                    "pdf": job["pdf_path"],
                })

            class DirectQueue:
                def put(self, evt):
                    if progress_callback:
                        progress_callback({
                            **evt,
                            "job_index": i,
                            "job_total": len(jobs),
                        })

            local_job = dict(job)
            local_job["_progress_queue"] = DirectQueue()
            result = process_pdf_job(local_job)
            out.append(result)

            if progress_callback:
                progress_callback({
                    "event": "job_done",
                    "index": i,
                    "total": len(jobs),
                    "result": result,
                })
        return out

    out: list[dict[str, Any]] = []

    with Manager() as manager:
        queue = manager.Queue()

        def drain_queue(completed_count: int) -> None:
            while True:
                try:
                    evt = queue.get_nowait()
                except Exception:
                    break
                if progress_callback:
                    progress_callback({
                        **evt,
                        "completed_jobs": completed_count,
                        "total_jobs": len(jobs),
                    })

        submitted_jobs = []
        for job in jobs:
            j = dict(job)
            j["_progress_queue"] = queue
            submitted_jobs.append(j)

        with ProcessPoolExecutor(max_workers=max_workers) as ex:
            future_map = {
                ex.submit(process_pdf_job, job): job
                for job in submitted_jobs
            }
            pending = set(future_map)
            completed = 0

            while pending:
                drain_queue(completed)

                done, pending = wait(
                    pending,
                    timeout=0.20,
                    return_when=FIRST_COMPLETED,
                )

                for fut in done:
                    job = future_map[fut]
                    try:
                        result = fut.result()
                    except Exception as exc:
                        result = {
                            "pdf_path": job["pdf_path"],
                            "pdf_name": Path(job["pdf_path"]).name,
                            "company": job.get("company", ""),
                            "document_year": str(job.get("year", "")),
                            "year": str(job.get("year", "")),
                            "error": f"{type(exc).__name__}: {exc}",
                            "results": [],
                            "resolution_details": [],
                        }

                    # Worker emits worker_done before returning. Give Manager.Queue a
                    # brief opportunity to flush those final progress messages, then
                    # drain them BEFORE publishing terminal job_done.
                    time.sleep(0.03)
                    drain_queue(completed)

                    completed += 1
                    out.append(result)
                    if progress_callback:
                        progress_callback({
                            "event": "job_done",
                            "index": completed,
                            "total": len(jobs),
                            "result": result,
                        })

            time.sleep(0.03)
            drain_queue(completed)

    return out

