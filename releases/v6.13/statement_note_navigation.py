"""Statement-guided navigation for long annual-report PDFs.

The index is deliberately text-only.  It narrows candidate pages before the
existing spatial capture engine is called; it never replaces source capture.
"""
from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Iterable


STATEMENT_PATTERNS = {
    "BALANCE_SHEET": ("合并资产负债表", "资产负债表"),
    "INCOME_STATEMENT": ("合并利润表", "利润表"),
    "CASH_FLOW": ("合并现金流量表", "现金流量表"),
}
FINANCIAL_INVESTMENT_ITEMS = {"交易性金融资产", "债权投资", "其他债权投资", "其他权益工具投资", "长期股权投资"}

# Multi-signal scoring for balance sheet structure fallback (OCR title missing)
_BS_STRONG_SIGNALS = [
    "资产总计", "负债合计", "负债和所有者权益总计",
    "负债及股东权益合计", "负债和权益总计",
]
_BS_AUX_SIGNALS = [
    "货币资金", "交易性金融资产", "长期股权投资",
    "应付债券", "实收资本", "未分配利润",
    "定期存款", "应收利息", "固定资产",
]
_BS_CONSOLIDATED_TOKENS = ["合并", "本集团"]
_BS_PARENT_TOKENS = ["母公司", "本公司资产负债表"]
_BS_DATE_PATTERN = re.compile(r"\d{4}年\d{1,2}月\d{1,2}日")
# Minimum score to treat page as balance sheet candidate via structure fallback
_BS_STRUCTURE_MIN_SCORE = 5

# v6.10: disclosure section identification for investment portfolio discovery.
# These sections sit outside the financial-statement-note region and contain
# management discussion, business analysis, and narrative portfolio disclosures.
DISCLOSURE_SECTION_PATTERNS = {
    "MANAGEMENT_DISCUSSION": (
        "管理层讨论与分析", "管理层讨论", "经营情况讨论与分析",
    ),
    "INVESTMENT_BUSINESS_ANALYSIS": (
        "投资业务分析", "投资组合分析", "投资资产情况", "投资组合情况",
        "保险资金投资组合",
    ),
    "BUSINESS_REVIEW": (
        "业务回顾", "经营回顾", "业务概要",
    ),
}

# Absence classification for portfolio table discovery.
ABSENCE_CLASSIFICATIONS = {
    "FOUND_CANONICAL_TABLE",
    "FOUND_DISCLOSURE_VARIANT",
    "NARRATIVE_ONLY",
    "LEGITIMATELY_ABSENT",
    "DISCOVERY_FAILED",
    "UNRESOLVED",
}


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


def _note_numbers(text: str) -> tuple[str, ...]:
    return tuple(sorted(set(re.findall(r"(?:附注\s*)?(?:[一二三四五六七八九十]+[、.．-])?\s*(\d{1,2})(?=\s*[.．、]?(?:债权投资|投资|金融资产|其他权益))", text or ""))))


def fast_index_to_text_index(fast_records: Iterable[Any]) -> list[TextIndexRecord]:
    """Explicit adapter mapping physical PageIndexRecords to semantic TextIndexRecords.

    Preserves all physical OCR metadata (ocr_rows, ocr_used, ocr_error, _bs_fallback_meta)
    while explicitly deriving semantics (heading, section, note_numbers, page_number)
    without mutating the input record schema or injecting ad-hoc properties.
    """
    adapted: list[TextIndexRecord] = []
    for r in fast_records:
        pg_num = getattr(r, "page_number", getattr(r, "page", 0))
        raw_text = getattr(r, "text", "") or ""
        head = _heading(raw_text)
        sec = _section(raw_text)
        notes = _note_numbers(raw_text)
        rec = TextIndexRecord(
            page_number=pg_num,
            text=raw_text,
            heading=head,
            section=sec,
            note_numbers=notes,
        )
        # Preserve physical OCR attributes and fallback meta on adapted record
        for attr in ("ocr_rows", "ocr_words", "ocr_used", "ocr_error", "_bs_fallback_meta", "page"):
            if hasattr(r, attr):
                try:
                    object.__setattr__(rec, attr, getattr(r, attr))
                except (AttributeError, TypeError):
                    pass
        adapted.append(rec)
    return adapted


def build_text_index(pdf_path: Path, cache_root: Path, *, text_provider=None,
                     force_rebuild: bool = False, ocr_mode: str = "auto") -> list[TextIndexRecord]:
    """Compatibility semantic view over the unified Fast Index.

    Production callers retain the historical ``TextIndexRecord`` contract but
    never rebuild a competing native-text cache.  Synthetic ``text_provider``
    input remains a test seam only.
    """
    pdf_path = Path(pdf_path)
    if text_provider is not None:
        provided = list(text_provider(pdf_path))
        if provided and hasattr(provided[0], "page") and hasattr(provided[0], "text"):
            records = fast_index_to_text_index(provided)
        else:
            records = []
            for number, text in enumerate(provided, 1):
                text_str = str(text or "")
                nums = _note_numbers(text_str)
                records.append(TextIndexRecord(number, text_str, _heading(text_str), _section(text_str), nums))
        return records

    # Local import avoids a module-level dependency cycle for legacy callers.
    from fast_index import build_fast_index
    from document_index_profile import fast_index_profile_kwargs
    fast_records, _ = build_fast_index(
        pdf_path, Path(cache_root),
        **fast_index_profile_kwargs(ocr_mode=ocr_mode),
        force_rebuild=force_rebuild,
    )
    return fast_index_to_text_index(fast_records)


def _score_balance_sheet_structure(text: str) -> dict[str, Any]:
    """Score a page's body text against multi-signal balance sheet evidence.

    Returns a dict with:
      structure_score     – int, sum of signal weights
      strong_signals      – list[str] strong signals found
      aux_signals         – list[str] auxiliary signals found
      has_date            – bool, reporting date pattern detected

    Strong signals score 3 pts each; auxiliary signals 1 pt; date 1 pt.
    A score >= _BS_STRUCTURE_MIN_SCORE triggers BODY_STRUCTURE_FALLBACK.
    """
    clean = text.replace(" ", "")
    strong_found = [s for s in _BS_STRONG_SIGNALS if s in clean]
    aux_found = [s for s in _BS_AUX_SIGNALS if s in clean]
    has_date = bool(_BS_DATE_PATTERN.search(text))
    score = len(strong_found) * 3 + len(aux_found) * 1 + (1 if has_date else 0)
    return {
        "structure_score": score,
        "strong_signals": strong_found,
        "aux_signals": aux_found,
        "has_date": has_date,
    }


def _infer_consolidated_scope(
    rec: Any,
    index: list[Any],
    page_num: int,
) -> dict[str, Any]:
    """Infer whether a structurally-detected balance sheet is consolidated.

    Returns a dict with:
      scope               – 'CONSOLIDATED' | 'PARENT_ONLY' | 'UNKNOWN'
      scope_source        – method used to infer scope
      scope_confidence    – float 0-1
      requires_scope_review – bool
    """
    clean = rec.text.replace(" ", "")

    # Check title/header tokens in OCR text (even if partially garbled)
    if any(t in clean for t in _BS_CONSOLIDATED_TOKENS):
        return {
            "scope": "CONSOLIDATED",
            "scope_source": "BODY_TOKEN",
            "scope_confidence": 0.75,
            "requires_scope_review": False,
        }

    # Check if a sibling page explicitly named 'parent' exists nearby
    nearby_pages = [
        r for r in index
        if abs(getattr(r, "page_number", getattr(r, "page", 0)) - page_num) <= 5
        and r is not rec
    ]
    for nearby in nearby_pages:
        nearby_clean = (nearby.text or "").replace(" ", "")
        if any(t in nearby_clean for t in _BS_PARENT_TOKENS):
            return {
                "scope": "CONSOLIDATED",
                "scope_source": "SIBLING_PAGE_HAS_PARENT",
                "scope_confidence": 0.85,
                "requires_scope_review": False,
            }

    # Cannot determine — flag for review
    return {
        "scope": "UNKNOWN",
        "scope_source": "NONE",
        "scope_confidence": 0.0,
        "requires_scope_review": True,
    }


def locate_primary_statements(
    index: Iterable[TextIndexRecord],
    retain_broad_candidates: bool = False,
) -> dict[str, list[int]]:
    """Locate primary financial statements.

    Annual-report notes frequently refer to a balance sheet in prose.  A broad
    substring scan promotes those pages into the statement candidate set and
    makes later OCR both slow and misleading.  Prefer a title-like line in the
    page heading region; retain the former broad scan only as a compatibility
    fallback when an unusual PDF exposes no formal title at all, unless
    retain_broad_candidates is explicitly requested.

    For OCR pages where the title is missing or garbled, a multi-signal body
    structure scorer (_score_balance_sheet_structure) is used as fallback.
    The fallback records detection_method=BODY_STRUCTURE_FALLBACK,
    title_status=OCR_TITLE_MISSING, and scope inference metadata on the rec
    object if it supports attribute assignment.
    """
    index_list = list(index)
    found: dict[str, list[int]] = {key: [] for key in STATEMENT_PATTERNS}
    broad: dict[str, list[int]] = {key: [] for key in STATEMENT_PATTERNS}
    # Metadata about pages detected via structure fallback
    structure_fallback_meta: dict[int, dict[str, Any]] = {}

    for rec in index_list:
        page_num = getattr(rec, "page_number", getattr(rec, "page", 0))
        title_lines = [re.sub(r"\s+", "", line) for line in rec.text.splitlines()[:32] if line.strip() and "。" not in line]
        for kind, patterns in STATEMENT_PATTERNS.items():
            if any(token in rec.text[:2500] for token in patterns):
                broad[kind].append(page_num)
            if any(
                (clean := re.sub(r"[(（].*?[)）]$", "", line.replace("（续）", "").replace("(续)", "").replace("续表", "")).strip("：:")) in patterns
                or any(clean.endswith(pattern) for pattern in patterns)
                for line in title_lines
            ) or (hasattr(rec, "ocr_rows") and rec.ocr_rows and any(token in rec.text[:2500] for token in patterns)):
                found[kind].append(page_num)

        # Multi-signal structural fallback for OCR pages with garbled/missing titles
        if hasattr(rec, "ocr_rows") and rec.ocr_rows and page_num not in found["BALANCE_SHEET"]:
            score_result = _score_balance_sheet_structure(rec.text)
            if score_result["structure_score"] >= _BS_STRUCTURE_MIN_SCORE:
                found["BALANCE_SHEET"].append(page_num)
                scope_meta = _infer_consolidated_scope(rec, index_list, page_num)
                meta: dict[str, Any] = {
                    "pdf_page_index": page_num - 1,   # 0-based
                    "statement_pdf_page": page_num,    # 1-based display
                    "detection_method": "BODY_STRUCTURE_FALLBACK",
                    "title_status": "OCR_TITLE_MISSING",
                    "ocr_title_raw": (rec.text.splitlines()[0] if rec.text.splitlines() else ""),
                    "requires_review": score_result["structure_score"] < 8 or scope_meta["requires_scope_review"],
                    **score_result,
                    **scope_meta,
                }
                structure_fallback_meta[page_num] = meta
                # Attach to record object if mutable (PageIndexRecord supports setattr)
                try:
                    object.__setattr__(rec, "_bs_fallback_meta", meta)
                except (AttributeError, TypeError, Exception):
                    pass

    for kind in found:
        if retain_broad_candidates:
            found[kind] = sorted(set(found[kind] + broad[kind]))
        elif not found[kind]:
            found[kind] = broad[kind]
    return found


def locate_disclosure_sections(
    index: Iterable[TextIndexRecord],
) -> dict[str, list[int]]:
    """Locate disclosure/narrative sections outside formal financial statements.

    Returns a dict mapping section type keys (``MANAGEMENT_DISCUSSION``,
    ``INVESTMENT_BUSINESS_ANALYSIS``, ``BUSINESS_REVIEW``) to lists of
    page numbers.

    Used by ``DIRECT_DISCLOSURE_SEARCH`` to scope portfolio discovery to
    the right parts of the annual report.
    """
    found: dict[str, list[int]] = {key: [] for key in DISCLOSURE_SECTION_PATTERNS}
    for rec in index:
        head = rec.heading or ""
        text_head = (rec.text or "")[:2500]
        for kind, patterns in DISCLOSURE_SECTION_PATTERNS.items():
            if any(p in head for p in patterns):
                found[kind].append(getattr(rec, "page_number", getattr(rec, "page", 0)))
            elif any(p in text_head for p in patterns):
                found[kind].append(getattr(rec, "page_number", getattr(rec, "page", 0)))
    return found


def classify_absence(
    *,
    candidates_found: int,
    exact_title_match: bool,
    certified_alias_match: bool,
    section_searched: bool,
    table_evidence: bool,
    narrative_only: bool,
    human_reviewed: bool = False,
) -> str:
    """Classify why a portfolio table was or was not discovered.

    Returns one of:
      - ``FOUND_CANONICAL_TABLE`` — exact title match with table evidence
      - ``FOUND_DISCLOSURE_VARIANT`` — certified alias match with table evidence
      - ``NARRATIVE_ONLY`` — text found but no tabular structure
      - ``LEGITIMATELY_ABSENT`` — exhaustive search found nothing; human confirmed
      - ``DISCOVERY_FAILED`` — search could not complete
      - ``UNRESOLVED`` — default, pending further investigation
    """
    if candidates_found:
        if exact_title_match and table_evidence:
            return "FOUND_CANONICAL_TABLE"
        if certified_alias_match and table_evidence:
            return "FOUND_DISCLOSURE_VARIANT"
        if narrative_only:
            return "NARRATIVE_ONLY"
        return "FOUND_DISCLOSURE_VARIANT"
    if human_reviewed and section_searched:
        return "LEGITIMATELY_ABSENT"
    if not section_searched:
        return "DISCOVERY_FAILED"
    return "UNRESOLVED"


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


def locate_note(
    index: Iterable[TextIndexRecord], *, note_reference: str, item: str,
    section_context: str = "", authoritative_main_statement_page: int | None = None,
) -> tuple[int | None, str, float]:
    """Locate a note-detail page without promoting a contents page to evidence.

    A note ordinal is only an address, not proof that the page contains the
    underlying detail table.  In particular, annual-report contents pages often
    contain the same ``ordinal + item`` pair as a real note heading.  This
    locator therefore certifies a page only when a non-contents record contains
    a heading-shaped match *and* either the declared section or additional
    detail context. A target on or before the authoritative main statement is
    excluded before exact and fallback retrieval. We intentionally return a
    review status (rather than a guessed page) for weaker retrieval evidence.
    """
    records = list(index)
    if authoritative_main_statement_page is None:
        statement_pages = locate_primary_statements(records)
        resolved_statement_pages = [
            page
            for pages in statement_pages.values()
            for page in pages
        ]
        authoritative_main_statement_page = max(
            resolved_statement_pages, default=None,
        )
    eligible_records = [
        rec for rec in records
        if authoritative_main_statement_page is None
        or rec.page_number > authoritative_main_statement_page
    ]
    rejected_main_statement_item = bool(
        authoritative_main_statement_page is not None
        and any(
            rec.page_number <= authoritative_main_statement_page
            and item in rec.text
            for rec in records
        )
    )
    candidates = []
    expected_section, ordinal = _parse_note_reference(note_reference, section_context)
    if not ordinal:
        return None, "NO_NOTE_ORDINAL", 0.0

    # A reference such as “附注七-10” carries more information than a bare
    # “10”.  First collect line-level exact hits, then prefer a hit whose page
    # also carries the declared note section.  This is deliberately not tied to
    # a particular insurer's note numbering or PDF page layout.
    exact_hits: list[tuple[TextIndexRecord, bool, bool]] = []
    for rec in eligible_records:
        lines = rec.text.splitlines()
        for position, raw_line in enumerate(lines):
            # In text layers, a narrow note-number column and its item label
            # are frequently emitted as two adjacent lines (``12`` then
            # ``债权投资``).  Recombine only immediate non-empty neighbours;
            # never turn arbitrary page-wide token co-occurrence into a title.
            candidates = [raw_line]
            if position + 1 < len(lines) and lines[position + 1].strip():
                candidates.append(f"{raw_line} {lines[position + 1]}")
            if any(_is_exact_note_heading(candidate, ordinal, item, expected_section) for candidate in candidates):
                exact_hits.append((
                    rec,
                    _page_has_note_section(rec, expected_section),
                    _has_detail_heading_context(rec, raw_line, item),
                ))
                break

    if exact_hits:
        verified = [hit for hit in exact_hits if not _is_contents_record(hit[0]) and (hit[1] or hit[2])]
        sectioned = [hit for hit in verified if hit[1]]
        if sectioned:
            return sectioned[0][0].page_number, "SECTION_ORDINAL_EXACT_HEADING", .98
        if verified:
            # A note can start immediately after a section-title page, or the
            # text layer can omit the section title.  The additional detail
            # context makes this a reviewable heading match, not a TOC hit.
            return verified[0][0].page_number, "ORDINAL_EXACT_HEADING_WITH_CONTEXT", .90
        if any(_is_contents_record(hit[0]) for hit in exact_hits):
            return None, "TOC_ONLY_MATCH_REVIEW_REQUIRED", .0
        return None, "UNVERIFIED_NOTE_HEADING_REVIEW_REQUIRED", .0

    for rec in eligible_records:
        note_nums = getattr(rec, "note_numbers", ())
        if not _is_contents_record(rec) and item in rec.text and ordinal in note_nums:
            candidates.append(rec)
    if candidates:
        # This retrieval signal is useful for the review queue but cannot
        # certify a detail table: the index only knows that tokens co-occur.
        return None, "NOTE_REF_ITEM_UNVERIFIED_REVIEW_REQUIRED", .0
    for rec in eligible_records:
        if not _is_contents_record(rec) and item in rec.text:
            return None, "DIRECT_SEARCH_UNVERIFIED_REVIEW_REQUIRED", .0
    if rejected_main_statement_item:
        return None, "NOTE_TARGET_NOT_AFTER_MAIN_STATEMENT_REVIEW_REQUIRED", .0
    return None, "NOT_FOUND", 0.0


def _normalize_locator_text(value: Any) -> str:
    """Normalize spacing/punctuation only for locator comparison.

    PDF text layers frequently mix normal spaces, ideographic spaces (U+3000),
    narrow no-break spaces and full-width punctuation.  The raw source text is
    never changed or persisted through this helper.
    """
    text = unicodedata.normalize("NFKC", str(value or ""))
    text = re.sub(r"[\s\u2000-\u200B\u202F\u205F\u3000]+", "", text)
    return text.replace("：", ":").replace("．", ".").replace("，", ",")


def _parse_note_reference(note_reference: str, section_context: str = "") -> tuple[str, str]:
    """Return declared note section (when unambiguous) and note ordinal.

    ``附注11`` means ordinal 11, whereas ``附注七-11`` means section 七,
    ordinal 11.  Treating the former as section 1/item 1 is a common source of
    false note targets, so section extraction requires an explicit separator.
    """
    raw = _normalize_locator_text(note_reference)
    context = _normalize_locator_text(section_context)
    match = re.search(r"(?:附注)?([一二三四五六七八九十百千万]+|\d+)[、,._\-—]+(\d{1,3})(?:\D|$)", raw)
    if match:
        return match.group(1), match.group(2)
    ordinals = re.findall(r"\d{1,3}", raw)
    return context, ordinals[-1] if ordinals else ""


def _page_has_note_section(rec: TextIndexRecord, section: str) -> bool:
    if not section:
        return False
    compact = _normalize_locator_text(rec.text)
    escaped = re.escape(section)
    return bool(
        re.search(rf"附注{escaped}(?:[、,.:\-—]|$)", compact)
        or re.search(rf"(?:^|\n){escaped}[、,.]", rec.text)
    )


def _is_exact_note_heading(raw_line: str, ordinal: str, item: str, section: str) -> bool:
    line = _normalize_locator_text(raw_line)
    normalized_item = _normalize_locator_text(item)
    if normalized_item not in line:
        return False
    prefix = rf"(?:(?:附注)?{re.escape(section)}[、,._\-—])?{re.escape(ordinal)}[、,._\-—:]*"
    return bool(re.match(prefix, line))


def _is_contents_record(rec: TextIndexRecord) -> bool:
    """Return whether a text page looks like a table of contents/index page."""
    lead = "\n".join(rec.text.splitlines()[:36])
    compact = _normalize_locator_text(lead).lower()
    if "目录" in compact or "contents" in compact:
        return True
    # Dot leaders plus a dense run of page-like terminal numbers is a robust
    # secondary signal when OCR drops the literal title “目录”.
    leader_lines = sum(1 for line in lead.splitlines() if re.search(r"[.．·…]{3,}", line))
    numbered_lines = sum(1 for line in lead.splitlines() if re.search(r"\d{1,4}\s*$", line.strip()))
    return leader_lines >= 2 and numbered_lines >= 3


def _has_detail_heading_context(rec: TextIndexRecord, raw_line: str, item: str) -> bool:
    """Require evidence that an ordinal/item line belongs to a detail page.

    This intentionally avoids trusting a lone line such as ``11 债权投资``.
    A real note page normally provides either a note-section marker, a table
    heading/measurement context, or substantive text following the heading.
    """
    if _is_contents_record(rec):
        return False
    lines = [line.strip() for line in rec.text.splitlines() if line.strip()]
    try:
        position = next(i for i, line in enumerate(lines) if _normalize_locator_text(line) == _normalize_locator_text(raw_line))
    except StopIteration:
        position = 0
    surrounding = " ".join(lines[max(0, position - 1): position + 7])
    compact = _normalize_locator_text(surrounding)
    markers = ("金额单位", "单位", "年", "余额", "账面", "成本", "公允价值", "减值", "本集团", "本公司", "人民币")
    if any(marker in compact for marker in markers):
        return True
    # A non-trivial line after the heading is also contextual evidence.  This
    # supports text-layer notes whose table headers are rendered as separate
    # vector objects and therefore absent from extraction.
    following = [line for line in lines[position + 1: position + 4] if _normalize_locator_text(line) != _normalize_locator_text(item)]
    return any(len(_normalize_locator_text(line)) >= 4 for line in following)


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
