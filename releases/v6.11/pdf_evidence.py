"""Real-PDF evidence extraction and preview fallbacks for v6.5.1."""
from __future__ import annotations
import io, re, hashlib
from functools import lru_cache
from pathlib import Path
from typing import Any

import fitz
from statement_anchored_family import compose_note_reference

FINANCIAL_INVESTMENT_CHILDREN = [
    "以公允价值计量且其变动计入当期损益的金融资产", "债权投资", "其他债权投资", "其他权益工具投资",
]

def printed_page(text: str) -> str | None:
    m = re.search(r"股份有限公司\s*(\d+)\s*$", text, re.M)
    return m.group(1) if m else None

@lru_cache(maxsize=96)
def _render_page_cached(pdf_text: str, page_index: int, terms: tuple[str, ...],
                        file_size: int, mtime_ns: int) -> tuple[bytes, str, tuple[tuple[float, float, float, float], ...]]:
    """Render a page lazily and draw deterministic evidence boxes into the preview."""
    doc = fitz.open(pdf_text)
    try:
        page = doc[page_index]
        bboxes: list[tuple[float, float, float, float]] = []
        for term in terms:
            if not term:
                continue
            for rect in page.search_for(term):
                bboxes.append(tuple(rect))
                page.draw_rect(rect, color=(0.84, 0.15, 0.10), width=1.35, overlay=True)
        pix = page.get_pixmap(matrix=fitz.Matrix(1.4, 1.4), alpha=False)
        return pix.tobytes("png"), page.get_text("text"), tuple(bboxes)
    finally:
        doc.close()

def page_preview(pdf_path: Path, page_index: int, terms: list[str] | None = None) -> dict[str, Any]:
    path = Path(pdf_path).resolve()
    base = {
        "png": None,
        "pdf_page_index": int(page_index) + 1,
        "printed_page": None,
        "bboxes": (),
        "evidence_level": "UNAVAILABLE",
    }
    if not path.exists() or not path.is_file():
        return base | {"status": "PDF_MISSING", "error": f"PDF不存在：{path}"}
    try:
        stat = path.stat()
        with fitz.open(str(path)) as doc:
            if page_index < 0 or page_index >= doc.page_count:
                return base | {
                    "status": "PAGE_OUT_OF_RANGE",
                    "error": f"页码越界：{page_index + 1}/{doc.page_count}",
                }
            if doc.needs_pass:
                return base | {"status": "PDF_ENCRYPTED", "error": "PDF需要密码。"}
    except Exception as exc:
        return base | {"status": "PDF_OPEN_FAILED", "error": f"{type(exc).__name__}: {exc}"}
    normalized_terms = tuple(dict.fromkeys(str(term).strip() for term in (terms or []) if str(term).strip()))
    try:
        png, text, bboxes = _render_page_cached(
            str(path), page_index, normalized_terms, int(stat.st_size), int(stat.st_mtime_ns)
        )
    except Exception as exc:
        return base | {"status": "RENDER_FAILED", "error": f"{type(exc).__name__}: {exc}"}
    if bboxes:
        level = "LEVEL_1_BBOX"
    elif text.strip():
        level = "LEVEL_3_PAGE_ONLY"
    else:
        level = "EMPTY_OR_SCANNED_PAGE"
    return {
        "status": "OK",
        "png": png,
        "pdf_page_index": page_index + 1,
        "printed_page": printed_page(text),
        "bboxes": bboxes,
        "evidence_level": level,
    }

def _note_target_pages(doc, refs: list[str], labels: list[str]) -> dict[str, int | None]:
    out = {ref: None for ref in refs}
    for ix, page in enumerate(doc):
        text = page.get_text("text")
        for ref, label in zip(refs, labels):
            # Both 附注八-11 and direct 附注11 are valid statement references.
            note_no = ref.rsplit("-", 1)[-1]
            if note_no == ref:
                note_no = re.sub(r"^(?:附注|注)", "", ref)
            if out[ref] is None and re.search(rf"(?:^|\n)\s*{re.escape(note_no)}\.\s*{re.escape(label)}", text):
                out[ref] = ix + 1
    return out

def extract_statement_anchor(pdf_path: Path, display_name: str = "金融投资") -> dict[str, Any]:
    """Extract the known statement block from a real PDF without fabricating values."""
    doc = fitz.open(pdf_path)
    candidates = []
    for ix, page in enumerate(doc):
        text = page.get_text("text")
        if "合并资产负债表" in text and f"{display_name}：" in text:
            candidates.append((ix, text))
    if not candidates:
        return {"status": "EVIDENCE_PAGE_UNRESOLVED", "children": []}
    ix, text = candidates[0]
    lines = [x.strip() for x in text.splitlines() if x.strip()]
    parent_at = lines.index(f"{display_name}：")
    # Do not hard-code “附注八”: some reports expose direct note ordinals under
    # a bare “附注” column.  Use the closest actual statement header instead.
    note_header = next(
        (
            line for line in reversed(lines[max(0, parent_at - 30):parent_at + 1])
            if re.fullmatch(r"(?:附注|注)(?:\s*[一二三四五六七八九十百\d]+)?", line)
        ),
        "附注",
    )
    children = []
    for label in FINANCIAL_INVESTMENT_CHILDREN:
        try:
            pos = lines.index(label, parent_at + 1)
            note = lines[pos + 1]
            if not re.fullmatch(r"\d{1,3}", note):
                continue
            reference = compose_note_reference(note_header, note)
            if not reference["note_reference_normalized"]:
                continue
            children.append({"item": label, "member_table": label,
                             **reference,
                             "statement_pdf_page_index": ix + 1,
                             "statement_printed_page": printed_page(text),
                             "bbox": [tuple(r) for r in doc[ix].search_for(label)]})
        except ValueError:
            continue
    refs = [x["note_reference_normalized"] for x in children]
    pages = _note_target_pages(doc, refs, [x["item"] for x in children])
    for child in children:
        child["candidate_note_pdf_page_index"] = pages[child["note_reference_normalized"]]
    return {"status": "FOUND", "pdf_path": str(pdf_path), "display_name": display_name,
            "statement_type": "BALANCE_SHEET", "scope": "CONSOLIDATED", "source_table_title": "合并资产负债表",
            "parent_text": display_name, "statement_pdf_page_index": ix + 1,
            "statement_printed_page": printed_page(text), "children": children,
            "parent_bbox": [tuple(r) for r in doc[ix].search_for(f"{display_name}：")]}
