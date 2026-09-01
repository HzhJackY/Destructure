"""Statement-guided navigation for long annual-report PDFs.

The index is deliberately text-only.  It narrows candidate pages before the
existing spatial capture engine is called; it never replaces source capture.
"""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Iterable


STATEMENT_PATTERNS = {
    "BALANCE_SHEET": ("合并资产负债表", "资产负债表"),
    "INCOME_STATEMENT": ("合并利润表", "利润表"),
    "CASH_FLOW": ("合并现金流量表", "现金流量表"),
}
FINANCIAL_INVESTMENT_ITEMS = {"交易性金融资产", "债权投资", "其他债权投资", "其他权益工具投资", "长期股权投资"}


@dataclass(frozen=True)
class TextIndexRecord:
    page_number: int
    text: str
    heading: str
    section: str
    note_numbers: tuple[str, ...]


@dataclass(frozen=True)
class StatementNoteEdge:
    statement_type: str
    statement_item: str
    note_reference: str
    member_table: str
    statement_page: int
    note_page: int | None
    locator_method: str
    confidence: float


def _heading(text: str) -> str:
    for line in text.splitlines()[:12]:
        line = re.sub(r"\s+", " ", line).strip()
        if 2 <= len(line) <= 80:
            return line
    return ""


def _section(text: str) -> str:
    match = re.search(r"(?:附注|财务报表项目注释)\s*([一二三四五六七八九十]+|\d+)", text[:1200])
    return match.group(1) if match else ""


def build_text_index(pdf_path: Path, cache_root: Path, *, text_provider=None) -> list[TextIndexRecord]:
    """Create/reuse a cache keyed by file content; supports an injected reader for tests."""
    digest = hashlib.sha256(Path(pdf_path).read_bytes()).hexdigest()[:24]
    cache = Path(cache_root) / f"{digest}.statement_text_index.json"
    if cache.exists():
        return [TextIndexRecord(**{**x, "note_numbers": tuple(x.get("note_numbers", []))}) for x in json.loads(cache.read_text(encoding="utf-8"))]
    if text_provider is None:
        import fitz
        doc = fitz.open(pdf_path)
        pages = [page.get_text("text") for page in doc]
        doc.close()
    else:
        pages = list(text_provider(pdf_path))
    records = []
    for number, text in enumerate(pages, 1):
        nums = tuple(sorted(set(re.findall(r"(?:附注\s*)?(?:[一二三四五六七八九十]+[、.．-])?\s*(\d{1,2})(?=\s*[.．、]?(?:债权投资|投资|金融资产|其他权益))", text))))
        records.append(TextIndexRecord(number, text, _heading(text), _section(text), nums))
    cache.parent.mkdir(parents=True, exist_ok=True)
    cache.write_text(json.dumps([asdict(x) for x in records], ensure_ascii=False), encoding="utf-8")
    return records


def locate_primary_statements(index: Iterable[TextIndexRecord]) -> dict[str, list[int]]:
    found: dict[str, list[int]] = {key: [] for key in STATEMENT_PATTERNS}
    for rec in index:
        for kind, patterns in STATEMENT_PATTERNS.items():
            if any(token in rec.text[:2500] for token in patterns):
                found[kind].append(rec.page_number)
    return found


def extract_statement_references(index: Iterable[TextIndexRecord], *, statement_type: str = "BALANCE_SHEET") -> list[dict[str, Any]]:
    """Extract item + cross-reference without treating the reference as a value.

    This conservative line parser returns no edge when a note number cannot be
    established.  The original table remains authoritative for actual values.
    """
    pages = set(locate_primary_statements(index).get(statement_type, []))
    refs: list[dict[str, Any]] = []
    for rec in index:
        if rec.page_number not in pages:
            continue
        for line in rec.text.splitlines():
            normalized = re.sub(r"\s+", " ", line).strip()
            # Longest label first prevents “债权投资” from also matching the
            # more specific “其他债权投资” row.
            for item in sorted(FINANCIAL_INVESTMENT_ITEMS, key=len, reverse=True):
                if item not in normalized:
                    continue
                tail = normalized.split(item, 1)[1]
                number = re.search(r"(?:附注\s*)?(\d{1,2})(?:\D|$)", tail)
                if number:
                    refs.append({"statement_type": statement_type, "statement_item": item,
                                 "note_reference": number.group(1), "statement_page": rec.page_number,
                                 "raw_line": normalized})
                    break
    return refs


def locate_note(index: Iterable[TextIndexRecord], *, note_reference: str, item: str, section_context: str = "") -> tuple[int | None, str, float]:
    """Apply safe ordered navigation; never search a bare note number alone."""
    candidates = []
    number_pattern = re.compile(rf"(?:^|\n)\s*(?:{re.escape(section_context)}[、.．-]\s*)?{re.escape(str(note_reference))}[、.．.\s]+[^\n]*{re.escape(item)}")
    for rec in index:
        if number_pattern.search(rec.text):
            return rec.page_number, "EXACT_HEADING", .98
        if item in rec.text and str(note_reference) in rec.note_numbers:
            candidates.append(rec)
    if candidates:
        return candidates[0].page_number, "NOTE_REF_ITEM_SECTION", .78
    for rec in index:
        if item in rec.text:
            return rec.page_number, "DIRECT_SEARCH_FALLBACK", .45
    return None, "NOT_FOUND", 0.0


def build_statement_note_graph(index: Iterable[TextIndexRecord], *, family: str = "金融投资") -> list[StatementNoteEdge]:
    edges = []
    for ref in extract_statement_references(index):
        page, method, confidence = locate_note(index, note_reference=ref["note_reference"], item=ref["statement_item"])
        edges.append(StatementNoteEdge(ref["statement_type"], ref["statement_item"], ref["note_reference"],
                                       ref["statement_item"], ref["statement_page"], page, method, confidence))
    return edges


def reconcile_statement_note(statement_value: float | None, note_value: float | None, *, unit: str = "元") -> dict[str, Any]:
    if statement_value is None or note_value is None:
        return {"status": "NOT_TESTABLE", "difference": None, "tolerance": None}
    factor = {"元": 1.0, "千元": 1000.0, "万元": 10000.0, "百万元": 1_000_000.0, "亿元": 100_000_000.0}.get(unit, 1.0)
    tolerance = max(factor, abs(float(statement_value)) * 1e-8)
    diff = abs(float(statement_value) - float(note_value))
    return {"status": "PASS_EXACT" if diff == 0 else ("PASS_WITH_ROUNDING" if diff <= tolerance else "WARNING_STATEMENT_NOTE_MISMATCH"),
            "difference": diff, "tolerance": tolerance}
