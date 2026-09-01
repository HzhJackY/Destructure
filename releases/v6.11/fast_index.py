#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
fast_index.py

Fast first-pass PDF index with optional OCR.

Modes:
- off: native text only (except explicitly forced pages)
- selected: OCR only explicitly forced pages
- auto: OCR only low-text pages plus explicitly forced pages
- force: OCR every page (slow; scanned PDFs only)

PyMuPDF OCR requires Tesseract installed separately.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, asdict, field
from pathlib import Path
from typing import Any, Callable, Optional

from document_index_profile import CERTIFIED_DOCUMENT_INDEX_PROFILE

try:
    import pymupdf as fitz
except ImportError:
    import fitz  # type: ignore


INDEX_SCHEMA_VERSION = "v6.11-fast-index-v3"


@dataclass
class PageIndexRecord:
    page: int
    text: str
    text_chars: int
    source: str
    ocr_used: bool
    ocr_error: Optional[str]
    ocr_rows: list[list[str]]
    # OCR rows are adequate for search, but statement-family reconstruction
    # also needs the original TSV geometry to repair split labels and bind
    # note ordinals to their real column.  Keep it as immutable page evidence.
    ocr_words: list[tuple] = field(default_factory=list)
    page_number: int = 0

    def __post_init__(self):
        if not self.page_number and self.page:
            self.page_number = self.page


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
    vertical_count = 0
    valid_count = 0
    for w in words:
        if len(w) < 5:
            continue
        x0, y0, x1, y1, text = w[:5]
        text = str(text).strip()
        if text:
            items.append((float(x0), float(y0), float(x1), float(y1), text))
            if (x1 - x0) < (y1 - y0):
                vertical_count += 1
            valid_count += 1
            
    if not items:
        return []
        
    mapped_items = []
    for x0, y0, x1, y1, text in items:
        mapped_items.append((x0, y0, x1, y1, text))
            
    mapped_items.sort(key=lambda x: (x[1], x[0]))
    items = mapped_items

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


def cache_key(ocr_mode: str, language: str, dpi: int, ocr_quality_threshold: float, force_ocr_pages: set[int]) -> str:
    raw = f"{ocr_mode}_{language}_{dpi}_fq{ocr_quality_threshold}_{'-'.join(str(x) for x in sorted(force_ocr_pages))}".encode("utf-8")
    return hashlib.sha1(raw).hexdigest()[:12]


def shared_ocr_page_cache_path(
    pdf_path: Path,
    cache_root: Path,
    *,
    execution_key: str,
    language: str,
    dpi: int,
    min_native_chars: int = 40,
    force_ocr_pages: set[int] | None = None,
) -> Path:
    """Return the Fast Index-owned cache path for conditional page OCR.

    Conditional statement OCR and batch Fast Index deliberately share the
    document SHA directory and the same versioned key primitive.  The
    ``ocr_page_cache_`` filename distinguishes page-text evidence from a full
    index without creating an independent cache namespace.
    """
    pdf_sha = sha256_file(pdf_path)
    cfg_key = cache_key(execution_key, language, int(dpi), float(min_native_chars), force_ocr_pages or set())
    cache_dir = Path(cache_root) / pdf_sha
    cache_dir.mkdir(parents=True, exist_ok=True)
    return cache_dir / f"ocr_page_cache_{cfg_key}.json"


def load_shared_ocr_page_cache(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"pages": {}}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return {"pages": {}}
    if not isinstance(payload, dict) or not isinstance(payload.get("pages"), dict):
        return {"pages": {}}
    return payload


def save_shared_ocr_page_cache(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(
        json.dumps(payload, ensure_ascii=False, sort_keys=True),
        encoding="utf-8",
    )


def _ocr_words_with_fallback(page: fitz.Page, ocr_language: str, ocr_dpi: int) -> list[tuple]:
    """Perform OCR using system Tesseract CLI with rotation check, falling back to PyMuPDF OCR."""
    import shutil
    import subprocess
    import tempfile
    import io
    from PIL import Image

    tesseract_path = shutil.which("tesseract") or (
        r"C:\Program Files\Tesseract-OCR\tesseract.exe"
        if Path(r"C:\Program Files\Tesseract-OCR\tesseract.exe").exists()
        else None
    )

    if tesseract_path:
        try:
            # Render at high DPI and filter out red auditor stamp ink (Scheme A)
            effective_dpi = max(400, int(ocr_dpi))
            pix = page.get_pixmap(dpi=effective_dpi)

            import io
            import numpy as np
            from PIL import Image

            img_bytes = pix.tobytes("png")
            img = Image.open(io.BytesIO(img_bytes)).convert("RGB")
            arr = np.array(img)
            r, g, b = arr[:, :, 0], arr[:, :, 1], arr[:, :, 2]
            # Red ink mask: filter red pixels to white so auditor stamps don't obscure text
            red_mask = (r > 120) & (r > g.astype(int) + 30) & (r > b.astype(int) + 30)
            arr[red_mask] = [255, 255, 255]
            clean_img = Image.fromarray(arr)

            with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tmp:
                tmp_path = tmp.name
            clean_img.save(tmp_path, dpi=(effective_dpi, effective_dpi))

            try:
                cmd = [tesseract_path, tmp_path, "stdout", "-l", ocr_language, "--psm", "6", "tsv"]
                res = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
                words = []
                if res.returncode == 0:
                    for line in res.stdout.splitlines()[1:]:
                        parts = line.split("\t")
                        if len(parts) >= 12 and parts[11].strip():
                            left, top, w, h = int(parts[6]), int(parts[7]), int(parts[8]), int(parts[9])
                            words.append((left, top, left + w, top + h, parts[11].strip()))
                    if words:
                        return words
            finally:
                try:
                    Path(tmp_path).unlink(missing_ok=True)
                except Exception:
                    pass
        except Exception:
            pass

    # PyMuPDF fallback
    try:
        tp = page.get_textpage_ocr(language=ocr_language, dpi=int(ocr_dpi), full=True)
    except TypeError:
        tp = page.get_textpage_ocr(language=ocr_language, dpi=int(ocr_dpi))
    return page.get_text("words", textpage=tp, sort=True) or []


def build_fast_index(
    pdf_path: Path,
    cache_root: Path,
    *,
    ocr_mode: str = "auto",
    ocr_language: str = CERTIFIED_DOCUMENT_INDEX_PROFILE["ocr_language"],
    ocr_dpi: int = CERTIFIED_DOCUMENT_INDEX_PROFILE["ocr_dpi"],
    ocr_quality_threshold: float = CERTIFIED_DOCUMENT_INDEX_PROFILE["ocr_quality_threshold"],
    min_native_chars: int = CERTIFIED_DOCUMENT_INDEX_PROFILE["min_native_chars"],
    force_ocr_pages: set[int] | None = None,
    force_rebuild: bool = False,
    progress_callback: Any | None = None,
) -> tuple[list[PageIndexRecord], dict[str, Any]]:
    """Build or load the token-efficient Fast Index for an annual report PDF."""
    pdf_path = Path(pdf_path)
    cache_root = Path(cache_root)
    if ocr_mode not in {"off", "selected", "auto", "force"}:
        raise ValueError("ocr_mode must be off/selected/auto/force")

    if force_ocr_pages is None:
        force_ocr_pages = set()

    pdf_sha = sha256_file(pdf_path)
    cfg_key = cache_key(ocr_mode, ocr_language, ocr_dpi, ocr_quality_threshold, force_ocr_pages)
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
        try:
            payload = json.loads(index_path.read_text(encoding="utf-8"))
            meta = payload.get("meta", {})
            if meta.get("index_schema_version") == INDEX_SCHEMA_VERSION and meta.get("pdf_sha256") == pdf_sha:
                records = [PageIndexRecord(**x) for x in payload["pages"]]
                meta["cache_hit"] = True
                emit("index_cache_hit", total_pages=len(records), message="命中 Fast Index 缓存")
                return records, meta
        except Exception:
            pass  # Corrupted cache — fallback to rebuild

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
        
        # Calculate native text quality score if a threshold is given and there are native chars
        quality_score = 1.0
        if ocr_quality_threshold > 0 and native_chars > 0:
            raw_text = native.replace(" ", "").replace("\n", "")
            if raw_text:
                valid_chars = len(re.findall(r'[\u4e00-\u9fa50-9]', raw_text))
                quality_score = valid_chars / len(raw_text)

        need_ocr = (
            ocr_mode == "force" 
            or (ocr_mode == "auto" and native_chars < min_native_chars)
            or (page_no in force_ocr_pages)
            or (ocr_mode == "auto" and ocr_quality_threshold > 0 and native_chars > 0 and quality_score < ocr_quality_threshold)
        )
        text = native
        source = "native_text"
        ocr_error = None
        ocr_rows: list[list[str]] = []
        ocr_words: list[tuple] = []

        if need_ocr:
            emit("ocr_start", page=page_no, total_pages=total, message=f"第 {page_no} 页：OCR")
            try:
                ocr_words = _ocr_words_with_fallback(page, ocr_language, ocr_dpi)
                ocr_rows = words_to_rows(ocr_words)
                text = "\n".join(" ".join(row) for row in ocr_rows)
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
            ocr_words=ocr_words,
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
        "index_schema_version": INDEX_SCHEMA_VERSION,
        "document_index_profile_version": CERTIFIED_DOCUMENT_INDEX_PROFILE["profile_version"],
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
