"""Real-PDF evidence extraction and preview fallbacks for v6.5.1."""
from __future__ import annotations
import io, re
from pathlib import Path
from typing import Any

import fitz

FINANCIAL_INVESTMENT_CHILDREN = [
    "以公允价值计量且其变动计入当期损益的金融资产", "债权投资", "其他债权投资", "其他权益工具投资",
]

def printed_page(text: str) -> str | None:
    m = re.search(r"股份有限公司\s*(\d+)\s*$", text, re.M)
    return m.group(1) if m else None

def page_preview(pdf_path: Path, page_index: int, terms: list[str] | None = None) -> dict[str, Any]:
    doc = fitz.open(pdf_path); page = doc[page_index]
    pix = page.get_pixmap(matrix=fitz.Matrix(1.4, 1.4), alpha=False)
    bboxes = []
    for term in terms or []:
        bboxes.extend([tuple(r) for r in page.search_for(term)])
    # Preview remains usable at Level 3 even if no text bbox exists.
    return {"png": pix.tobytes("png"), "pdf_page_index": page_index + 1,
            "printed_page": printed_page(page.get_text("text")), "bboxes": bboxes,
            "evidence_level": "LEVEL_1_BBOX" if bboxes else "LEVEL_3_PAGE_KEYWORDS"}

def _note_target_pages(doc, refs: list[str], labels: list[str]) -> dict[str, int | None]:
    out = {ref: None for ref in refs}
    for ix, page in enumerate(doc):
        text = page.get_text("text")
        for ref, label in zip(refs, labels):
            note_no = ref.rsplit("-", 1)[-1]
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
    children = []
    for label in FINANCIAL_INVESTMENT_CHILDREN:
        try:
            pos = lines.index(label, parent_at + 1)
            note = lines[pos + 1]
            if not re.fullmatch(r"\d{1,3}", note):
                continue
            children.append({"item": label, "member_table": label,
                             "note_reference_normalized": f"附注八-{note}",
                             "note_reference_section": "八", "note_reference_item": note,
                             "note_reference_status": "COMPOSED_FROM_HEADER_AND_ROW",
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
