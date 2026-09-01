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
import os
import re
import time
import uuid
from contextlib import contextmanager, nullcontext
from dataclasses import dataclass, asdict, field
from pathlib import Path
from typing import Any, Callable, Optional

from document_index_profile import CERTIFIED_DOCUMENT_INDEX_PROFILE

try:
    import pymupdf as fitz
except ImportError:
    import fitz  # type: ignore


INDEX_SCHEMA_VERSION = "v6.12-fast-index-v4"
OCR_PAGE_CACHE_SCHEMA_VERSION = "v6.12-ocr-page-cache-v1"
OCR_PAGE_CACHE_PIPELINE_VERSION = "FAST_INDEX_TESSERACT_WIDE_BAND_SAFE_RED_MASK_V2"


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
    # Historical index records may not carry this field.  Conditional Stage-A
    # Hybrid evidence refuses such cached geometry and refreshes only the
    # requested page through the existing shared OCR cache.
    ocr_geometry_metadata: dict[str, Any] = field(default_factory=dict)

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


def cache_key(
    ocr_mode: str,
    language: str,
    dpi: int,
    ocr_quality_threshold: float,
    force_ocr_pages: set[int],
    *,
    min_native_chars: int | None = None,
    page_subset: set[int] | None = None,
    ocr_psm: int = 4,
) -> str:
    native_threshold = "na" if min_native_chars is None else str(int(min_native_chars))
    subset_key = "all" if page_subset is None else "-".join(str(x) for x in sorted(page_subset))
    raw = (
        f"{ocr_mode}_{language}_{dpi}_fq{ocr_quality_threshold}"
        f"_mn{native_threshold}_{'-'.join(str(x) for x in sorted(force_ocr_pages))}"
        f"_psm{int(ocr_psm)}_ps{subset_key}"
    ).encode("utf-8")
    return hashlib.sha1(raw).hexdigest()[:12]


def ocr_page_cache_execution_key(*, language: str, dpi: int, ocr_psm: int = 4) -> str:
    """Stable OCR-content identity, independent of caller mode/page set."""
    effective_dpi = max(400, int(dpi))
    return "|".join([
        OCR_PAGE_CACHE_PIPELINE_VERSION,
        f"schema={OCR_PAGE_CACHE_SCHEMA_VERSION}",
        f"profile={CERTIFIED_DOCUMENT_INDEX_PROFILE['profile_version']}",
        f"language={language}",
        f"effective_dpi={effective_dpi}",
        "render=full_page",
        "preprocess=wide_band_safe_red_stamp_mask_v2",
        f"psm={int(ocr_psm)}",
        "fallback=pymupdf_full_page",
    ])


def shared_ocr_page_cache_path(
    pdf_path: Path,
    cache_root: Path,
    *,
    execution_key: str,
    language: str,
    dpi: int,
    min_native_chars: int = 40,
    force_ocr_pages: set[int] | None = None,
    pdf_sha256: str | None = None,
) -> Path:
    """Return the Fast Index-owned cache path for conditional page OCR.

    Conditional statement OCR and batch Fast Index deliberately share the
    document SHA directory and the same versioned key primitive.  The
    ``ocr_page_cache_`` filename distinguishes page-text evidence from a full
    index without creating an independent cache namespace.
    """
    pdf_sha = str(pdf_sha256 or sha256_file(pdf_path))
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
    _atomic_json_write(path, payload, sort_keys=True)


def _atomic_json_write(path: Path, payload: dict[str, Any], *, sort_keys: bool = False) -> None:
    """Write cache JSON atomically so readers never observe a partial file."""
    temporary = path.with_name(
        f".{path.name}.{os.getpid()}.{uuid.uuid4().hex}.tmp"
    )
    try:
        temporary.write_text(
            json.dumps(payload, ensure_ascii=False, sort_keys=sort_keys),
            encoding="utf-8",
        )
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


@contextmanager
def _exclusive_page_cache_lock(
    cache_path: Path,
    *,
    timeout_seconds: float = 600.0,
    stale_seconds: float = 3600.0,
):
    """Serialize read/merge/write for one document OCR cache.

    Atomic lock-file creation works across threads and processes on Windows.
    A stale lock is recoverable after one hour; normal page OCR has a much
    shorter timeout.  The lock protects both same-page de-duplication and
    merging different candidate sets into the aggregate page cache.
    """
    lock_path = cache_path.with_suffix(cache_path.suffix + ".lock")
    started = time.monotonic()
    while True:
        try:
            descriptor = os.open(
                str(lock_path),
                os.O_CREAT | os.O_EXCL | os.O_WRONLY,
            )
        except FileExistsError:
            try:
                if time.time() - lock_path.stat().st_mtime > stale_seconds:
                    lock_path.unlink(missing_ok=True)
                    continue
            except OSError:
                pass
            if time.monotonic() - started >= timeout_seconds:
                raise TimeoutError(f"OCR page cache lock timeout: {lock_path}")
            time.sleep(0.05)
            continue
        else:
            try:
                os.write(
                    descriptor,
                    f"pid={os.getpid()} created={time.time()}".encode("ascii"),
                )
            finally:
                os.close(descriptor)
            break
    try:
        yield
    finally:
        lock_path.unlink(missing_ok=True)


def _red_stamp_mask_preserving_wide_bands(rgb_array):
    """Remove compact red ink while preserving coloured table-header bands.

    The former per-pixel mask erased PICC's gold/brown header background and
    therefore also erased its white period labels.  Auditor stamps are compact
    components; a coloured header spans a large fraction of the page width.
    Rows with more than 35% red-like pixels are retained as structural bands.
    """
    import numpy as np

    arr = np.array(rgb_array, copy=True)
    r, g, b = arr[:, :, 0], arr[:, :, 1], arr[:, :, 2]
    red_mask = (
        (r > 120)
        & (r > g.astype(int) + 30)
        & (r > b.astype(int) + 30)
    )
    red_mask[red_mask.mean(axis=1) > 0.35, :] = False
    arr[red_mask] = [255, 255, 255]
    return arr


def _ocr_words_with_fallback(
    page: fitz.Page,
    ocr_language: str,
    ocr_dpi: int,
    ocr_psm: int = 4,
) -> tuple[list[tuple], dict[str, Any]]:
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
            arr = _red_stamp_mask_preserving_wide_bands(np.array(img))
            clean_img = Image.fromarray(arr)

            with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tmp:
                tmp_path = tmp.name
            clean_img.save(tmp_path, dpi=(effective_dpi, effective_dpi))

            try:
                cmd = [
                    tesseract_path,
                    tmp_path,
                    "stdout",
                    "-l",
                    ocr_language,
                    "--psm",
                    str(int(ocr_psm)),
                    "tsv",
                ]
                res = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
                words = []
                if res.returncode == 0:
                    for line in res.stdout.splitlines()[1:]:
                        parts = line.split("\t")
                        if len(parts) >= 12 and parts[11].strip():
                            left, top, w, h = int(parts[6]), int(parts[7]), int(parts[8]), int(parts[9])
                            words.append((left, top, left + w, top + h, parts[11].strip()))
                    if words:
                        return words, {
                            "geometry_schema_version": "FAST_INDEX_OCR_GEOMETRY_V2",
                            "coordinate_space": "RASTER_PIXELS",
                            "engine": "TESSERACT_CLI",
                            "psm": int(ocr_psm),
                            "effective_dpi": effective_dpi,
                            "render_width": int(pix.width), "render_height": int(pix.height),
                            "page_width_points": float(page.rect.width),
                            "page_height_points": float(page.rect.height),
                            "scale_x": float(pix.width) / float(page.rect.width),
                            "scale_y": float(pix.height) / float(page.rect.height),
                        }
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
    return page.get_text("words", textpage=tp, sort=True) or [], {
        "geometry_schema_version": "FAST_INDEX_OCR_GEOMETRY_V2",
        "coordinate_space": "PDF_POINTS",
        "engine": "PYMUPDF_TEXTPAGE_OCR",
        "effective_dpi": int(ocr_dpi),
        "render_width": None, "render_height": None,
        "page_width_points": float(page.rect.width),
        "page_height_points": float(page.rect.height),
        "scale_x": 1.0, "scale_y": 1.0,
    }


def build_fast_index(
    pdf_path: Path,
    cache_root: Path,
    *,
    ocr_mode: str = "auto",
    ocr_language: str = CERTIFIED_DOCUMENT_INDEX_PROFILE["ocr_language"],
    ocr_dpi: int = CERTIFIED_DOCUMENT_INDEX_PROFILE["ocr_dpi"],
    ocr_psm: int = CERTIFIED_DOCUMENT_INDEX_PROFILE["ocr_psm"],
    ocr_quality_threshold: float = CERTIFIED_DOCUMENT_INDEX_PROFILE["ocr_quality_threshold"],
    min_native_chars: int = CERTIFIED_DOCUMENT_INDEX_PROFILE["min_native_chars"],
    force_ocr_pages: set[int] | None = None,
    page_subset: set[int] | None = None,
    require_ocr_geometry_metadata: bool = False,
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
    if page_subset is not None:
        page_subset = {int(page) for page in page_subset if int(page) > 0}

    pdf_sha = sha256_file(pdf_path)
    cfg_key = cache_key(
        ocr_mode,
        ocr_language,
        ocr_dpi,
        ocr_quality_threshold,
        force_ocr_pages,
        min_native_chars=min_native_chars,
        page_subset=page_subset,
        ocr_psm=ocr_psm,
    )
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
                required_pages = set(force_ocr_pages or set())
                geometry_ready = all(
                    record.ocr_geometry_metadata.get("geometry_schema_version") == "FAST_INDEX_OCR_GEOMETRY_V2"
                    for record in records if record.page in required_pages
                )
                if not require_ocr_geometry_metadata or geometry_ready:
                    meta["cache_hit"] = True
                    emit("index_cache_hit", total_pages=len(records), message="命中 Fast Index 缓存")
                    return records, meta
        except Exception:
            pass  # Corrupted cache — fallback to rebuild

    page_cache_path: Path | None = None
    page_cache_payload: dict[str, Any] = {"pages": {}}
    ocr_page_cache_hits = 0
    ocr_page_cache_misses = 0
    ocr_page_cache_hit_pages: list[int] = []
    ocr_page_cache_miss_pages: list[int] = []
    page_cache_execution_key = ocr_page_cache_execution_key(
        language=ocr_language, dpi=ocr_dpi, ocr_psm=ocr_psm
    )
    if ocr_mode != "off" or force_ocr_pages:
        page_cache_path = shared_ocr_page_cache_path(
            pdf_path,
            cache_root,
            execution_key=page_cache_execution_key,
            language=ocr_language,
            dpi=max(400, int(ocr_dpi)),
            min_native_chars=0,
            pdf_sha256=pdf_sha,
        )
        loaded_page_cache = load_shared_ocr_page_cache(page_cache_path)
        if (
            loaded_page_cache.get("page_cache_schema_version") == OCR_PAGE_CACHE_SCHEMA_VERSION
            and loaded_page_cache.get("execution_key") == page_cache_execution_key
        ):
            page_cache_payload = loaded_page_cache
        else:
            page_cache_payload = {
                "page_cache_schema_version": OCR_PAGE_CACHE_SCHEMA_VERSION,
                "execution_key": page_cache_execution_key,
                "cache_namespace": "FAST_INDEX_SHARED_OCR_PAGE_CACHE",
                "pdf_sha256": pdf_sha,
                "pages": {},
            }

    records: list[PageIndexRecord] = []
    ocr_pages = 0
    ocr_page_numbers: list[int] = []
    ocr_failures = 0

    doc = fitz.open(str(pdf_path))
    total = doc.page_count
    emit("index_start", total_pages=total, message=f"开始快速索引，共 {total} 页")

    for idx in range(total):
        page_no = idx + 1
        if page_subset is not None and page_no not in page_subset:
            continue
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
        ocr_geometry_metadata: dict[str, Any] = {}

        if need_ocr:
            lock_context = (
                _exclusive_page_cache_lock(page_cache_path)
                if page_cache_path is not None
                else nullcontext()
            )
            with lock_context:
                # Reload while holding the lock.  Another process may have
                # populated this or a different page after our initial read.
                if page_cache_path is not None:
                    latest_page_cache = load_shared_ocr_page_cache(page_cache_path)
                    if (
                        latest_page_cache.get("page_cache_schema_version")
                        == OCR_PAGE_CACHE_SCHEMA_VERSION
                        and latest_page_cache.get("execution_key")
                        == page_cache_execution_key
                    ):
                        page_cache_payload = latest_page_cache
                    else:
                        page_cache_payload = {
                            "page_cache_schema_version": OCR_PAGE_CACHE_SCHEMA_VERSION,
                            "execution_key": page_cache_execution_key,
                            "cache_namespace": "FAST_INDEX_SHARED_OCR_PAGE_CACHE",
                            "pdf_sha256": pdf_sha,
                            "pages": {},
                        }
                cache_entry = (
                    None
                    if force_rebuild
                    else page_cache_payload.get("pages", {}).get(str(page_no))
                )
                cache_entry_valid = bool(
                    isinstance(cache_entry, dict)
                    and isinstance(cache_entry.get("text"), str)
                    and isinstance(cache_entry.get("ocr_rows"), list)
                    and isinstance(cache_entry.get("ocr_words"), list)
                )
                if require_ocr_geometry_metadata:
                    cache_entry_valid = cache_entry_valid and bool(
                        isinstance(cache_entry.get("ocr_geometry_metadata"), dict)
                        and cache_entry.get("ocr_geometry_metadata", {}).get("geometry_schema_version")
                        == "FAST_INDEX_OCR_GEOMETRY_V2"
                    )
                if cache_entry_valid:
                    text = str(cache_entry["text"])
                    ocr_rows = [list(row) for row in cache_entry["ocr_rows"]]
                    ocr_words = [tuple(word) for word in cache_entry["ocr_words"]]
                    ocr_geometry_metadata = dict(cache_entry.get("ocr_geometry_metadata") or {})
                    source = "ocr"
                    ocr_pages += 1
                    ocr_page_numbers.append(page_no)
                    ocr_page_cache_hits += 1
                    ocr_page_cache_hit_pages.append(page_no)
                    emit(
                        "ocr_page_cache_hit", page=page_no, total_pages=total,
                        message=f"第 {page_no} 页：命中页级 OCR 缓存",
                    )
                else:
                    ocr_page_cache_misses += 1
                    ocr_page_cache_miss_pages.append(page_no)
                    emit("ocr_start", page=page_no, total_pages=total, message=f"第 {page_no} 页：OCR")
                    try:
                        # Compatibility for narrow callers/tests which inject the
                        # pre-V2 helper result (a words list only).  Such a result
                        # remains searchable and cacheable, but cannot satisfy a
                        # Hybrid geometry request because it has no coordinate
                        # provenance.
                        # Preserve compatibility with narrow tests/callers
                        # which monkeypatch the historical three-argument
                        # helper when the certified default is requested.
                        if int(ocr_psm) == 4:
                            ocr_result = _ocr_words_with_fallback(
                                page, ocr_language, ocr_dpi
                            )
                        else:
                            ocr_result = _ocr_words_with_fallback(
                                page, ocr_language, ocr_dpi, int(ocr_psm)
                            )
                        if (
                            isinstance(ocr_result, tuple)
                            and len(ocr_result) == 2
                            and isinstance(ocr_result[1], dict)
                        ):
                            ocr_words, ocr_geometry_metadata = ocr_result
                        else:
                            ocr_words = list(ocr_result)
                            ocr_geometry_metadata = {
                                "geometry_schema_version": "FAST_INDEX_OCR_GEOMETRY_LEGACY",
                                "coordinate_space": "UNSPECIFIED",
                                "geometry_eligible": False,
                            }
                        ocr_rows = words_to_rows(ocr_words)
                        text = "\n".join(" ".join(row) for row in ocr_rows)
                        source = "ocr"
                        ocr_pages += 1
                        ocr_page_numbers.append(page_no)
                        if page_cache_path is not None:
                            page_cache_payload.setdefault("pages", {})[str(page_no)] = {
                                "page": page_no,
                                "text": text,
                                "ocr_rows": ocr_rows,
                                "ocr_words": ocr_words,
                                "text_sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
                                "pipeline_version": OCR_PAGE_CACHE_PIPELINE_VERSION,
                                "effective_dpi": max(400, int(ocr_dpi)),
                                "language": ocr_language,
                                "ocr_geometry_metadata": ocr_geometry_metadata,
                                "usable_as_amount": False,
                            }
                            save_shared_ocr_page_cache(
                                page_cache_path,
                                page_cache_payload,
                            )
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
            ocr_geometry_metadata=ocr_geometry_metadata,
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
        "indexed_page_subset": sorted(page_subset) if page_subset is not None else None,
        "ocr_mode": ocr_mode,
        "ocr_language": ocr_language,
        "ocr_dpi": int(ocr_dpi),
        "ocr_psm": int(ocr_psm),
        "min_native_chars": int(min_native_chars),
        "ocr_pages": ocr_pages,
        "ocr_page_numbers": ocr_page_numbers,
        "ocr_failures": ocr_failures,
        "ocr_page_cache_namespace": "FAST_INDEX_SHARED_OCR_PAGE_CACHE",
        "ocr_page_cache_path": str(page_cache_path or ""),
        "ocr_page_cache_execution_key": page_cache_execution_key,
        "ocr_page_cache_hits": ocr_page_cache_hits,
        "ocr_page_cache_misses": ocr_page_cache_misses,
        "ocr_page_cache_hit_pages": ocr_page_cache_hit_pages,
        "ocr_page_cache_miss_pages": ocr_page_cache_miss_pages,
        "cache_hit": False,
    }
    _atomic_json_write(
        index_path,
        {"meta": meta, "pages": [asdict(x) for x in records]},
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
