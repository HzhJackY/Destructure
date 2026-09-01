#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
fast_index.py

Fast first-pass PDF index with optional OCR.

Modes:
- off: native text only
- auto: OCR only low-text pages
- force: OCR every page (slow; scanned PDFs only)

PyMuPDF OCR requires Tesseract installed separately.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Any, Callable, Optional

try:
    import pymupdf as fitz
except ImportError:
    import fitz  # type: ignore


@dataclass
class PageIndexRecord:
    page: int
    text: str
    text_chars: int
    source: str
    ocr_used: bool
    ocr_error: Optional[str]
    ocr_rows: list[list[str]]


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _norm(s: str) -> str:
    return re.sub(r"[\s\u3000:：,，;；。\.、_/\\\-—–·'\"“”‘’（）()【】\[\]{}<>《》]+", "", s).lower()


def words_to_rows(words: list[tuple], y_tolerance: float = 4.0, gap_tolerance: float = 12.0) -> list[list[str]]:
    if not words:
        return []
    items = []
    for w in words:
        if len(w) < 5:
            continue
        x0, y0, x1, y1, text = w[:5]
        text = str(text).strip()
        if text:
            items.append((float(x0), float(y0), float(x1), float(y1), text))
    items.sort(key=lambda x: (x[1], x[0]))

    groups: list[list[tuple]] = []
    for item in items:
        if not groups:
            groups.append([item])
            continue
        avg_y = sum(x[1] for x in groups[-1]) / len(groups[-1])
        if abs(item[1] - avg_y) <= y_tolerance:
            groups[-1].append(item)
        else:
            groups.append([item])

    rows: list[list[str]] = []
    for group in groups:
        group.sort(key=lambda x: x[0])
        cells: list[str] = []
        current = ""
        last_x1 = None
        for x0, y0, x1, y1, text in group:
            if last_x1 is None or x0 - last_x1 <= gap_tolerance:
                current += text
            else:
                if current:
                    cells.append(current)
                current = text
            last_x1 = x1
        if current:
            cells.append(current)
        if cells:
            rows.append(cells)
    return rows


def cache_key(ocr_mode: str, language: str, dpi: int, min_native_chars: int) -> str:
    raw = f"{ocr_mode}|{language}|{dpi}|{min_native_chars}".encode("utf-8")
    return hashlib.sha1(raw).hexdigest()[:12]


def build_fast_index(
    pdf_path: Path,
    cache_root: Path,
    ocr_mode: str = "off",
    ocr_language: str = "chi_sim+eng",
    ocr_dpi: int = 150,
    min_native_chars: int = 40,
    progress_callback: Optional[Callable[[dict[str, Any]], None]] = None,
    force_rebuild: bool = False,
) -> tuple[list[PageIndexRecord], dict[str, Any]]:
    if ocr_mode not in {"off", "auto", "force"}:
        raise ValueError("ocr_mode must be off/auto/force")

    pdf_sha = sha256_file(pdf_path)
    cfg_key = cache_key(ocr_mode, ocr_language, ocr_dpi, min_native_chars)
    cache_dir = cache_root / pdf_sha
    cache_dir.mkdir(parents=True, exist_ok=True)
    index_path = cache_dir / f"fast_index_{cfg_key}.json"

    def emit(event: str, **kw: Any) -> None:
        if progress_callback:
            try:
                progress_callback({"event": event, **kw})
            except Exception:
                pass

    if index_path.exists() and not force_rebuild:
        payload = json.loads(index_path.read_text(encoding="utf-8"))
        records = [PageIndexRecord(**x) for x in payload["pages"]]
        meta = payload["meta"]
        meta["cache_hit"] = True
        emit("index_cache_hit", total_pages=len(records), message="命中 Fast Index 缓存")
        return records, meta

    records: list[PageIndexRecord] = []
    ocr_pages = 0
    ocr_failures = 0

    doc = fitz.open(str(pdf_path))
    total = doc.page_count
    emit("index_start", total_pages=total, message=f"开始快速索引，共 {total} 页")

    for idx in range(total):
        page_no = idx + 1
        page = doc.load_page(idx)
        native = page.get_text("text", sort=True) or ""
        native_chars = len(_norm(native))
        need_ocr = ocr_mode == "force" or (ocr_mode == "auto" and native_chars < min_native_chars)
        text = native
        source = "native_text"
        ocr_error = None
        ocr_rows: list[list[str]] = []

        if need_ocr:
            emit("ocr_start", page=page_no, total_pages=total, message=f"第 {page_no} 页：OCR")
            try:
                try:
                    tp = page.get_textpage_ocr(
                        language=ocr_language,
                        dpi=int(ocr_dpi),
                        full=True,
                    )
                except TypeError:
                    tp = page.get_textpage_ocr(
                        language=ocr_language,
                        dpi=int(ocr_dpi),
                    )
                text = page.get_text("text", textpage=tp, sort=True) or ""
                words = page.get_text("words", textpage=tp, sort=True) or []
                ocr_rows = words_to_rows(words)
                source = "ocr"
                ocr_pages += 1
            except Exception as exc:
                ocr_error = f"{type(exc).__name__}: {exc}"
                ocr_failures += 1
                source = "native_text_ocr_failed"

        rec = PageIndexRecord(
            page=page_no,
            text=text,
            text_chars=len(_norm(text)),
            source=source,
            ocr_used=(source == "ocr"),
            ocr_error=ocr_error,
            ocr_rows=ocr_rows,
        )
        records.append(rec)
        emit(
            "index_page_done",
            page=page_no,
            total_pages=total,
            source=source,
            text_chars=rec.text_chars,
            message=f"快速索引 {page_no}/{total} · {source} · {rec.text_chars:,} chars",
        )

    doc.close()

    meta = {
        "pdf_sha256": pdf_sha,
        "source_file": str(pdf_path),
        "total_pages": total,
        "ocr_mode": ocr_mode,
        "ocr_language": ocr_language,
        "ocr_dpi": int(ocr_dpi),
        "min_native_chars": int(min_native_chars),
        "ocr_pages": ocr_pages,
        "ocr_failures": ocr_failures,
        "cache_hit": False,
    }
    index_path.write_text(
        json.dumps({"meta": meta, "pages": [asdict(x) for x in records]}, ensure_ascii=False),
        encoding="utf-8",
    )
    emit("index_done", total_pages=total, ocr_pages=ocr_pages, message="Fast Index 完成")
    return records, meta


def expand_metric_terms(metric: str, cfg: Optional[dict[str, Any]]) -> dict[str, list[str]]:
    exact = [metric]
    aliases: list[str] = []
    keywords: list[str] = []
    if cfg:
        aliases.extend(cfg.get("aliases", []))
        aliases.extend(cfg.get("soft_aliases", []))
        keywords.extend(cfg.get("keywords", []))
    def dedup(xs: list[str]) -> list[str]:
        out = []
        for x in xs:
            x = str(x).strip()
            if x and x not in out:
                out.append(x)
        return out
    return {"exact": dedup(exact), "aliases": dedup(aliases), "keywords": dedup(keywords)}


def retrieve_candidate_pages(
    records: list[PageIndexRecord],
    metric_terms: dict[str, dict[str, list[str]]],
    top_pages_per_metric: int = 8,
    neighbor_radius: int = 1,
    min_score: float = 0.5,
) -> tuple[set[int], dict[str, list[dict[str, Any]]]]:
    selected: set[int] = set()
    evidence: dict[str, list[dict[str, Any]]] = {}
    total_pages = len(records)

    for metric, terms in metric_terms.items():
        scored = []
        exact_norm = [_norm(x) for x in terms.get("exact", []) if _norm(x)]
        alias_norm = [_norm(x) for x in terms.get("aliases", []) if _norm(x)]
        kw_norm = [_norm(x) for x in terms.get("keywords", []) if _norm(x)]

        for rec in records:
            nt = _norm(rec.text)
            score = 0.0
            hits = []
            for term in exact_norm:
                if term in nt:
                    score += 8.0
                    hits.append(term)
            for term in alias_norm:
                if term in nt:
                    score += 5.0
                    hits.append(term)
            for term in kw_norm:
                if term in nt:
                    score += 1.0
                    hits.append(term)
            if score > 0:
                scored.append({
                    "page": rec.page,
                    "score": score,
                    "hits": hits[:10],
                    "source": rec.source,
                })

        scored.sort(key=lambda x: (-x["score"], x["page"]))
        chosen = [x for x in scored if x["score"] >= min_score][:top_pages_per_metric]
        evidence[metric] = chosen
        for x in chosen:
            p = x["page"]
            for q in range(max(1, p - neighbor_radius), min(total_pages, p + neighbor_radius) + 1):
                selected.add(q)

    return selected, evidence
