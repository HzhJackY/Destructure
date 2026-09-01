"""Bounded OCR fallback for image-based primary-statement page discovery.

This module deliberately discovers pages only.  It never emits a financial
value and it never invokes the structural capture pipeline.
"""
from __future__ import annotations

import hashlib
import re
import shutil
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Any, Callable

try:
    import pymupdf as fitz
except ImportError:  # pragma: no cover - compatibility for older PyMuPDF
    import fitz  # type: ignore

from fast_index import (
    build_fast_index,
    load_shared_ocr_page_cache,
    save_shared_ocr_page_cache,
    shared_ocr_page_cache_path,
)
from document_index_profile import CERTIFIED_DOCUMENT_INDEX_PROFILE, fast_index_profile_kwargs


OCR_FALLBACK_CONFIG = {
    "enable_ocr_fallback": True,
    "ocr_trigger_score_threshold": 0.85,
    "ocr_text_min_chars": 40,
    "ocr_image_area_threshold": 0.55,
    "ocr_neighbor_page_radius": 2,
    "ocr_max_pages_per_document": 12,
    "ocr_language": CERTIFIED_DOCUMENT_INDEX_PROFILE["ocr_language"],
    "ocr_dpi": CERTIFIED_DOCUMENT_INDEX_PROFILE["ocr_dpi"],
    "ocr_psm": 4,
    "ocr_candidate_review_threshold": 0.60,
    "ocr_high_confidence_threshold": 0.85,
    "full_document_ocr_enabled": False,
    "engine_version": "PYMUPDF_TESSERACT_V1",
}

STATEMENT_ANCHORS = {
    "BALANCE_SHEET": ("合并资产负债表", "资产负债表"),
    "INCOME_STATEMENT": ("合并利润表", "利润表"),
    "CASH_FLOW": ("合并现金流量表", "现金流量表"),
}
STRUCTURE_ANCHORS = ("资产", "负债", "所有者权益", "资产总计", "负债合计", "营业收入", "净利润")


def _compact(value: str) -> str:
    return re.sub(r"\s+", "", str(value or ""))


def classify_page(*, text: str, image_count: int, largest_image_area_ratio: float,
                  total_image_area_ratio: float, config: dict[str, Any]) -> dict[str, Any]:
    chars = len(_compact(text))
    if chars < int(config["ocr_text_min_chars"]) and largest_image_area_ratio >= float(config["ocr_image_area_threshold"]):
        modality = "IMAGE_DOMINANT"
    elif chars < int(config["ocr_text_min_chars"]) and image_count == 0:
        modality = "EMPTY_OR_UNKNOWN"
    elif image_count and largest_image_area_ratio >= float(config["ocr_image_area_threshold"]):
        modality = "HYBRID"
    else:
        modality = "TEXT_DOMINANT"
    return {
        "text_char_count": chars, "image_count": image_count,
        "largest_image_area_ratio": round(largest_image_area_ratio, 4),
        "total_image_area_ratio": round(total_image_area_ratio, 4),
        "page_has_large_raster": largest_image_area_ratio >= float(config["ocr_image_area_threshold"]),
        "page_modality": modality,
    }


def statement_score(text: str, statement_type: str) -> float:
    compact = _compact(text)
    title_hits = sum(anchor in compact for anchor in STATEMENT_ANCHORS.get(statement_type, ()))
    structure_hits = sum(anchor in compact for anchor in STRUCTURE_ANCHORS)
    date_hits = bool(re.search(r"20\d{2}年|年\d{1,2}月\d{1,2}日|期末|期初", compact))
    unit_hits = bool(re.search(r"人民币[元万千]|单位[:：]?(?:元|万元|千元|百万元)", compact))
    if not title_hits:
        return 0.0
    return min(0.99, 0.58 + min(0.22, structure_hits * 0.04) + (0.08 if date_hits else 0) + (0.06 if unit_hits else 0))


def _directory_statement_hints(native_pages: list[str], statement_type: str,
                               preferred_scope: str | None = None) -> dict[int, dict[str, str]]:
    hints: dict[int, dict[str, str]] = {}
    wanted_anchors = STATEMENT_ANCHORS.get(statement_type, ())
    for toc_pdf_page, text in enumerate(native_pages, start=1):
        # A financial-statement TOC uses printed statement page numbers, not
        # PDF indices.  Its own PDF position is the offset because printed
        # page 1 (audit report) starts on the following PDF page.
        compact_page = _compact(text)
        # Real annual reports vary between “已审财务报表”, “经审计财务报表”,
        # and a bare financial-statement contents page.  Require a contents
        # signal plus a statement and note signal, rather than one publisher's
        # exact wording.  This deliberately remains narrower than searching
        # the whole report for a statement title.
        is_contents = ("目录" in compact_page or "页次" in compact_page or "目次" in compact_page)
        financial_signal = any(marker in compact_page for marker in (
            "财务报表附注", "财务报表", "审计报告", "经审计", "已审",
        ))
        has_statement_anchor = any(_compact(anchor) in compact_page for anchor in wanted_anchors)
        if not (is_contents and financial_signal and has_statement_anchor):
            continue
        lines = [line.strip() for line in text.splitlines() if line.strip()]
        for line_index, line in enumerate(lines):
            compact_line = _compact(line)
            matched_title = next(
                (anchor for anchor in wanted_anchors if _compact(anchor) in compact_line),
                None,
            )
            if not matched_title:
                continue
            scope = "CONSOLIDATED" if "合并" in compact_line else "PARENT_COMPANY"
            if preferred_scope and preferred_scope not in {"BOTH", "UNKNOWN", scope}:
                continue
            # PDF extraction often separates a TOC title and its page range
            # into adjacent lines.
            # Prefer page numbers on the same TOC line.  Fall back only to
            # the following two short lines, because a broader window can
            # accidentally pick a report year or the next entry's number.
            title_at = line.find(matched_title)
            tail = line[title_at + len(matched_title):] if title_at >= 0 else ""
            numbers = re.findall(r"(?<!\d)(\d{1,4})(?!\d)", tail)
            if not numbers:
                window = " ".join(lines[line_index + 1:line_index + 3])
                numbers = re.findall(r"(?<!\d)(\d{1,4})(?!\d)", window)
            if numbers:
                # Use the first number for ranges such as "6 - 7".
                target_page = toc_pdf_page + int(numbers[0])
                if not 1 <= target_page <= len(native_pages):
                    continue
                hints[target_page] = {
                    "statement_type": statement_type,
                    "statement_title": matched_title,
                    "scope": scope,
                    "toc_pdf_page": str(toc_pdf_page),
                    "printed_page": numbers[0],
                }
    return hints


def _directory_hints(native_pages: list[str], statement_type: str) -> set[int]:
    return set(_directory_statement_hints(native_pages, statement_type))


def _candidate_pages(features: list[dict[str, Any]], native_pages: list[str],
                     statement_type: str, config: dict[str, Any]) -> tuple[list[int], dict[int, list[str]]]:
    radius = int(config["ocr_neighbor_page_radius"])
    total = len(features)
    reasons: dict[int, list[str]] = {}

    def add(page: int, reason: str) -> None:
        if 1 <= page <= total:
            reasons.setdefault(page, []).append(reason)

    directory_hints = _directory_statement_hints(
        native_pages, statement_type, config.get("preferred_scope")
    )
    for page in directory_hints:
        add(page, "DIRECTORY_REFERENCED_PAGE")
        for near in range(page - radius, page + radius + 1): add(near, "DIRECTORY_NEIGHBOR")
    for feature in features:
        page = feature["page"]
        text = native_pages[page - 1]
        if "财务报表" in text or "审计报告" in text:
            for near in range(page - radius, page + radius + 1): add(near, "FINANCIAL_SECTION_NEIGHBOR")
        if feature["page_modality"] == "IMAGE_DOMINANT": add(page, "IMAGE_DOMINANT")
        elif feature["page_modality"] == "HYBRID" and feature["text_char_count"] < int(config["ocr_text_min_chars"]) * 4:
            add(page, "LOW_TEXT_HYBRID")
    priority = {
        "DIRECTORY_REFERENCED_PAGE": 0, "DIRECTORY_NEIGHBOR": 1,
        "FINANCIAL_SECTION_NEIGHBOR": 2, "LOW_TEXT_HYBRID": 3, "IMAGE_DOMINANT": 4,
    }
    pages = sorted(reasons, key=lambda p: (min(priority[x] for x in reasons[p]), p))
    return pages[:int(config["ocr_max_pages_per_document"])], reasons


def _ocr_page_default(page, cfg: dict[str, Any]) -> str:
    """OCR a bounded page with reading-order-oriented preprocessing.

    PyMuPDF's full-page OCR text layer can interleave table columns.  Prefer a
    grayscale crop plus Tesseract single-block layout; retain PyMuPDF as the
    compatibility fallback.
    """
    executable = shutil.which("tesseract")
    if executable:
        rect = page.rect
        clip = fitz.Rect(
            rect.x0 + rect.width * .04,
            rect.y0 + rect.height * .06,
            rect.x1 - rect.width * .04,
            rect.y1 - rect.height * .08,
        )
        dpi = max(200, int(cfg.get("ocr_dpi") or 300))
        matrix = fitz.Matrix(dpi / 72.0, dpi / 72.0)
        pix = page.get_pixmap(matrix=matrix, clip=clip, alpha=False, colorspace=fitz.csGRAY)
        with tempfile.TemporaryDirectory(prefix="axa_ocr_") as tmp:
            image_path = Path(tmp) / "page.png"
            pix.save(str(image_path))
            completed = subprocess.run(
                [
                    executable, str(image_path), "stdout",
                    "-l", str(cfg["ocr_language"]),
                    "--psm", str(cfg.get("ocr_psm") or 6),
                ],
                stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                check=True, timeout=90,
            )
            return completed.stdout.decode("utf-8", errors="replace")
    textpage = page.get_textpage_ocr(
        language=cfg["ocr_language"], dpi=int(cfg["ocr_dpi"]), full=True
    )
    return page.get_text("text", textpage=textpage, sort=True) or ""


def conditional_ocr_primary_statements(pdf_path: Path, *, native_pages: list[str],
                                       preferred_statement_type: str | None,
                                       cache_root: Path, config: dict[str, Any] | None = None,
                                       ocr_provider: Callable[[Any, int, dict[str, Any]], str] | None = None) -> tuple[dict[str, str], dict[str, Any]]:
    """Return OCR page text plus a compact audit; never OCRs an entire PDF by default."""
    cfg = {**OCR_FALLBACK_CONFIG, **dict(config or {})}
    statement_type = preferred_statement_type or "BALANCE_SHEET"
    text_score = max((statement_score(text, statement_type) for text in native_pages), default=0.0)
    audit: dict[str, Any] = {
        "text_scan_completed": True, "max_text_candidate_score": text_score,
        "high_confidence_threshold": cfg["ocr_trigger_score_threshold"],
        "ocr_triggered": False, "ocr_trigger_reason": "HIGH_CONFIDENCE_TEXT_CANDIDATE" if text_score >= cfg["ocr_trigger_score_threshold"] else "",
        "ocr_page_count": 0, "total_pages": len(native_pages), "ocr_pages": [],
        "page_modalities": [], "ocr_extra_ms": 0.0, "ocr_unavailable_reason": "",
        "full_document_ocr_count": 0, "ocr_engine": cfg["engine_version"],
        "ocr_cache_namespace": "FAST_INDEX_SHARED_OCR_PAGE_CACHE",
        "ocr_cache_hits": 0, "ocr_cache_misses": 0, "ocr_cache_path": "",
        "ocr_page_text_evidence": [],
    }
    force_for_target = bool(cfg.get("force_ocr_due_unqualified_target"))
    if text_score >= float(cfg["ocr_trigger_score_threshold"]) and not force_for_target:
        audit["final_status"] = "FOUND_HIGH_CONFIDENCE_TEXT"
        return {}, audit
    if not cfg["enable_ocr_fallback"]:
        audit["final_status"] = "NO_HIGH_CONFIDENCE_TEXT_OCR_NOT_TRIGGERED_BY_POLICY"
        audit["ocr_trigger_reason"] = "POLICY_DISABLED"
        return {}, audit
    started = time.perf_counter()
    try:
        doc = fitz.open(str(pdf_path))
    except Exception as exc:
        audit["final_status"] = "NO_HIGH_CONFIDENCE_TEXT_OCR_NOT_AVAILABLE"
        audit["ocr_unavailable_reason"] = f"PDF_OPEN_FAILED:{type(exc).__name__}"
        return {}, audit
    features: list[dict[str, Any]] = []
    for index, page in enumerate(doc):
        area = max(1.0, float(page.rect.width * page.rect.height))
        image_areas = []
        for image in page.get_images(full=True):
            try:
                image_areas.extend(float(rect.width * rect.height) for rect in page.get_image_rects(image[0]))
            except Exception:
                continue
        feature = classify_page(
            text=native_pages[index] if index < len(native_pages) else "", image_count=len(image_areas),
            largest_image_area_ratio=(max(image_areas) / area if image_areas else 0.0),
            total_image_area_ratio=(sum(image_areas) / area if image_areas else 0.0), config=cfg,
        ) | {"page": index + 1}
        features.append(feature)
    selected, reasons = _candidate_pages(features, native_pages, statement_type, cfg)
    if force_for_target:
        # A readable primary statement is not the same thing as a qualified
        # occurrence of the requested research target.  When the target gate
        # fails, OCR the bounded formal-statement candidates as a second view.
        formal_pages = [
            index + 1 for index, text in enumerate(native_pages)
            if statement_score(text, statement_type) >= float(cfg["ocr_candidate_review_threshold"])
        ]
        for page_number in formal_pages:
            reasons.setdefault(page_number, []).append("UNQUALIFIED_TARGET_ON_FORMAL_STATEMENT")
        # TOC-derived image pages are stronger than already-readable formal
        # statement pages; keep the latter only as trailing corroboration.
        selected = list(dict.fromkeys([*selected, *formal_pages]))[:int(cfg["ocr_max_pages_per_document"])]
    # A fallback may inspect a bounded *subset* only.  In a short image-only
    # document the candidate heuristics can otherwise nominate every page;
    # trim the lowest-priority tail so the default path never degenerates into
    # whole-document OCR.  A one-page document is intentionally abstained
    # from here rather than silently treating full OCR as a fallback.
    audit["ocr_scope_truncated_to_avoid_full_document"] = False
    if len(native_pages) <= 1 and selected:
        selected = []
        audit["ocr_scope_truncated_to_avoid_full_document"] = True
    elif len(selected) >= len(native_pages) and len(native_pages) > 1:
        selected = selected[:len(native_pages) - 1]
        audit["ocr_scope_truncated_to_avoid_full_document"] = True
    audit["page_modalities"] = features
    audit["directory_statement_hints"] = {
        str(page): payload for page, payload in _directory_statement_hints(
            native_pages, statement_type, cfg.get("preferred_scope")
        ).items()
    }
    audit["ocr_pages"] = selected
    audit["ocr_page_count"] = len(selected)
    if not selected:
        doc.close(); audit["final_status"] = "NO_HIGH_CONFIDENCE_TEXT_OCR_NOT_TRIGGERED_BY_POLICY"; audit["ocr_trigger_reason"] = "NO_BOUNDED_CANDIDATE_PAGES"; return {}, audit
    audit["ocr_triggered"] = True
    audit["ocr_trigger_reason"] = (
        "FORMAL_STATEMENT_FOUND_BUT_RESEARCH_TARGET_UNQUALIFIED"
        if force_for_target
        else "NO_HIGH_CONFIDENCE_TEXT_AND_BOUNDED_IMAGE_OR_SECTION_CANDIDATES"
    )
    # Production OCR is executed only by Fast Index.  This function owns the
    # bounded-page policy and audit contract; it no longer owns a second OCR
    # implementation or page-cache path.  The injectable provider below is
    # retained solely as a deterministic test seam for historical tests.
    if ocr_provider is None:
        doc.close()
        try:
            fast_records, fast_meta = build_fast_index(
                Path(pdf_path),
                Path(cache_root),
                **fast_index_profile_kwargs(
                    ocr_mode="selected", force_ocr_pages=set(selected)
                ),
            )
        except Exception as exc:
            audit["ocr_errors"] = [f"FAST_INDEX:{type(exc).__name__}"]
            audit["final_status"] = "NO_HIGH_CONFIDENCE_TEXT_OCR_NOT_AVAILABLE"
            audit["ocr_unavailable_reason"] = f"FAST_INDEX:{type(exc).__name__}:{exc}"
            return {}, audit
        output: dict[str, str] = {}
        evidence: list[dict[str, Any]] = []
        for record in fast_records:
            page_number = int(getattr(record, "page", getattr(record, "page_number", 0)) or 0)
            if page_number not in selected:
                continue
            text = str(getattr(record, "text", "") or "")
            if text:
                output[str(page_number)] = text
            evidence.append({
                "page": page_number,
                "source": "FAST_INDEX_OCR" if getattr(record, "ocr_used", False) else "FAST_INDEX_NATIVE",
                "cache_hit": bool(fast_meta.get("cache_hit")),
                "engine": cfg["engine_version"],
                "text_sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
                "text_chars": len(_compact(text)),
                "line_count": len(text.splitlines()),
                "native_geometry_present": False,
                "usable_as_amount": False,
            })
        audit["ocr_cache_namespace"] = "FAST_INDEX"
        audit["ocr_cache_hits"] = len(selected) if fast_meta.get("cache_hit") else 0
        audit["ocr_cache_misses"] = 0 if fast_meta.get("cache_hit") else len(selected)
        audit["ocr_page_text_evidence"] = evidence
        audit["ocr_errors"] = []
        audit["ocr_extra_ms"] = round((time.perf_counter() - started) * 1000, 2)
        audit["ocr_average_page_ms"] = round(audit["ocr_extra_ms"] / max(1, len(selected)), 2)
        audit["ocr_page_reasons"] = {str(p): reasons[p] for p in selected}
        if not output:
            audit["final_status"] = "OCR_COMPLETED_NO_QUALIFIED_CANDIDATE"
        else:
            high = max((statement_score(text, statement_type) for text in output.values()), default=0.0)
            audit["max_ocr_candidate_score"] = high
            audit["final_status"] = (
                "FOUND_HIGH_CONFIDENCE_OCR" if high >= float(cfg["ocr_high_confidence_threshold"])
                else "OCR_CANDIDATE_REQUIRES_REVIEW" if high >= float(cfg["ocr_candidate_review_threshold"])
                else "OCR_COMPLETED_NO_QUALIFIED_CANDIDATE"
            )
        return output, audit
    execution_key = "|".join([
        "conditional_statement_ocr",
        str(cfg.get("engine_version") or "UNKNOWN_ENGINE"),
        f"psm={int(cfg.get('ocr_psm') or 4)}",
        "preprocess=gray_crop_v1",
    ])
    cache_path = shared_ocr_page_cache_path(
        Path(pdf_path),
        Path(cache_root),
        execution_key=execution_key,
        language=str(cfg["ocr_language"]),
        dpi=int(cfg["ocr_dpi"]),
        min_native_chars=int(cfg["ocr_text_min_chars"]),
    )
    cache_payload = load_shared_ocr_page_cache(cache_path)
    cache_payload.setdefault("cache_namespace", "FAST_INDEX_SHARED_OCR_PAGE_CACHE")
    cache_payload.setdefault("execution_key", execution_key)
    cache_payload.setdefault("pages", {})
    audit["ocr_cache_path"] = str(cache_path)
    output: dict[str, str] = {}
    errors: list[str] = []
    cache_changed = False
    for page_number in selected:
        cache_entry = cache_payload["pages"].get(str(page_number))
        if isinstance(cache_entry, dict) and isinstance(cache_entry.get("text"), str):
            text = cache_entry["text"]
            audit["ocr_cache_hits"] += 1
            if text:
                output[str(page_number)] = text
            audit["ocr_page_text_evidence"].append({
                "page": page_number,
                "source": "SHARED_OCR_CACHE",
                "cache_hit": True,
                "engine": cache_entry.get("engine") or cfg["engine_version"],
                "text_sha256": cache_entry.get("text_sha256")
                or hashlib.sha256(text.encode("utf-8")).hexdigest(),
                "text_chars": len(_compact(text)),
                "line_count": len(text.splitlines()),
                "native_geometry_present": False,
                "usable_as_amount": False,
            })
            continue
        audit["ocr_cache_misses"] += 1
        try:
            page = doc[page_number - 1]
            if ocr_provider:
                text = ocr_provider(page, page_number, cfg)
            else:
                text = _ocr_page_default(page, cfg)
            text = str(text or "")
            cache_payload["pages"][str(page_number)] = {
                "text": text,
                "engine": cfg["engine_version"],
                "text_sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
                "native_geometry_present": False,
                "usable_as_amount": False,
            }
            cache_changed = True
            if text:
                output[str(page_number)] = text
            audit["ocr_page_text_evidence"].append({
                "page": page_number,
                "source": "OCR_ENGINE",
                "cache_hit": False,
                "engine": cfg["engine_version"],
                "text_sha256": cache_payload["pages"][str(page_number)]["text_sha256"],
                "text_chars": len(_compact(text)),
                "line_count": len(text.splitlines()),
                "native_geometry_present": False,
                "usable_as_amount": False,
            })
        except Exception as exc:
            errors.append(f"p{page_number}:{type(exc).__name__}")
    if cache_changed:
        save_shared_ocr_page_cache(cache_path, cache_payload)
    doc.close()
    audit["ocr_extra_ms"] = round((time.perf_counter() - started) * 1000, 2)
    audit["ocr_average_page_ms"] = round(audit["ocr_extra_ms"] / max(1, len(selected)), 2)
    audit["ocr_page_reasons"] = {str(p): reasons[p] for p in selected}
    audit["ocr_errors"] = errors
    if not output:
        audit["final_status"] = "NO_HIGH_CONFIDENCE_TEXT_OCR_NOT_AVAILABLE" if errors else "OCR_COMPLETED_NO_QUALIFIED_CANDIDATE"
    else:
        high = max((statement_score(text, statement_type) for text in output.values()), default=0.0)
        audit["max_ocr_candidate_score"] = high
        audit["final_status"] = (
            "FOUND_HIGH_CONFIDENCE_OCR" if high >= float(cfg["ocr_high_confidence_threshold"])
            else "OCR_CANDIDATE_REQUIRES_REVIEW" if high >= float(cfg["ocr_candidate_review_threshold"])
            else "OCR_COMPLETED_NO_QUALIFIED_CANDIDATE"
        )
    return output, audit
