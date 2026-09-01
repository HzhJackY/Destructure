"""Authoritative, section-first note target resolver for guided capture.

Candidate generation is intentionally broad, but it never returns a capture
permission.  A candidate becomes executable only after an explicit
``CERTIFIED_NOTE_TARGET`` decision is attached to the statement child.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Any


_CN_NUM = {"零": 0, "一": 1, "二": 2, "三": 3, "四": 4, "五": 5, "六": 6, "七": 7, "八": 8, "九": 9, "十": 10}


def chinese_ordinal(value: str) -> int | None:
    value = re.sub(r"[（）()、.．\s]", "", str(value or ""))
    if value.isdigit():
        return int(value)
    if value == "十": return 10
    if len(value) == 2 and value[0] == "十" and value[1] in _CN_NUM: return 10 + _CN_NUM[value[1]]
    if len(value) == 2 and value[1] == "十" and value[0] in _CN_NUM: return _CN_NUM[value[0]] * 10
    if len(value) == 3 and value[1] == "十" and value[0] in _CN_NUM and value[2] in _CN_NUM: return _CN_NUM[value[0]] * 10 + _CN_NUM[value[2]]
    return _CN_NUM.get(value)


def parse_note_reference(value: str) -> tuple[str, int | None]:
    compact = re.sub(r"\s+", "", str(value or ""))
    body = re.sub(r"^(?:附注|注)", "", compact)
    # Sectioned references use an explicit separator: 附注八-11 / 附注八、11.
    sectioned = re.fullmatch(r"([一二三四五六七八九十\d]+)[-、.．]([一二三四五六七八九十\d]+)", body)
    if sectioned:
        return sectioned.group(1), chinese_ordinal(sectioned.group(2))
    # A generic statement column headed merely “附注” exposes the note ordinal
    # directly.  It has no section context, but it is still a valid candidate
    # for ordinal + semantic resolution, not an absent reference.
    if re.fullmatch(r"[一二三四五六七八九十\d]+", body):
        return "", chinese_ordinal(body)
    return "", None


def normalize_title(value: str) -> str:
    return re.sub(r"[\s：:、.．（）()\-—]", "", str(value or "")).lower()


def _ordinal_pattern(ordinal: int) -> str:
    cn = "十" if ordinal == 10 else str(ordinal)
    return rf"(?:{ordinal}|{cn}|（{ordinal}）|\({ordinal}\)|（{cn}）|\({cn}\))[、.．\s]*"


@dataclass(frozen=True)
class NoteTargetCandidate:
    pdf_page_index: int
    heading: str
    heading_block: str
    section: str
    ordinal: int | None
    locator_method: str
    score: float
    following_table_signature: bool
    evidence: dict[str, Any]


class NoteReferenceResolver:
    """Resolve by Section -> ordinal -> semantic heading, never bare text first."""

    def candidates_from_pages(self, pages: list[str], *, note_reference: str, member_table: str) -> list[dict[str, Any]]:
        section, ordinal = parse_note_reference(note_reference)
        target = normalize_title(member_table)
        active_section = ""
        out: list[NoteTargetCandidate] = []
        for index, page in enumerate(pages, 1):
            text = page or ""
            if re.search(rf"(?:^|\n)\s*{re.escape(section)}[、.．].{{0,40}}(?:注释|附注|主要项目)", text) if section else False:
                active_section = section
            # A heading block can span adjacent lines.  This covers ``10.\n债权\n投资``.
            lines = [x.strip() for x in text.splitlines()]
            for pos in range(len(lines)):
                block = " ".join(x for x in lines[pos:pos + 3] if x)[:180]
                ordinal_match = re.match(_ordinal_pattern(ordinal), block) if ordinal is not None else None
                # Semantic fallback must look like a heading start, not a
                # paragraph that merely happens to mention the account name.
                semantic_line = bool(target and normalize_title(lines[pos]).startswith(target))
                semantic = bool(target and (semantic_line or (ordinal_match and target in normalize_title(block))))
                # An ordinal alone is commonly a table row number.  It is not
                # a note-heading candidate without the requested semantic.
                if not semantic:
                    continue
                heading_like = len(block) <= 100 and not block.endswith("。")
                following = "\n".join(lines[pos + 1:pos + 25])
                numeric_density = len(re.findall(r"\d[\d,，.]*", following)) >= 5
                period_headers = bool(re.search(r"20\d{2}年|20\d{2}[./-]\d{1,2}", following))
                table_signature = numeric_density and period_headers
                page_section_match = bool(section and (active_section == section or re.search(rf"{re.escape(section)}[、.．].{{0,40}}(?:注释|附注|主要项目)", text)))
                ordinal_exact = bool(ordinal_match)
                score = (0.34 if page_section_match else 0) + (0.30 if ordinal_exact else 0) + (0.20 if semantic else 0) + (0.08 if heading_like else 0) + (0.08 if table_signature else 0)
                # Paragraph mentions are a weak fallback, never automatic.
                if re.search(r"信用风险|减值测试|相关风险", block) and not table_signature:
                    score -= 0.35
                method = (
                    "SECTION_ORDINAL_SEMANTIC" if page_section_match and ordinal_exact and semantic
                    else "ORDINAL_SEMANTIC" if ordinal_exact and semantic
                    else "SECTION_SEMANTIC" if page_section_match and semantic
                    else "SEMANTIC_FALLBACK"
                )
                out.append(NoteTargetCandidate(index, block, block, section, ordinal, method, round(max(0.0, score), 4), table_signature,
                    {"section_match": page_section_match, "ordinal_exact": ordinal_exact, "semantic_match": bool(semantic), "heading_like": heading_like, "following_table_signature": table_signature}))
        # one logical target per page/heading: retain strongest evidence
        best: dict[tuple[int, str], NoteTargetCandidate] = {}
        for candidate in out:
            key = (candidate.pdf_page_index, normalize_title(candidate.heading))
            if key not in best or candidate.score > best[key].score:
                best[key] = candidate
        return [asdict(x) for x in sorted(best.values(), key=lambda x: (-x.score, x.pdf_page_index))]

    def candidates_from_pdf(self, pdf_path: Path, *, note_reference: str, member_table: str) -> list[dict[str, Any]]:
        import fitz
        doc = fitz.open(pdf_path)
        try:
            pages = [page.get_text("text") for page in doc]
        finally:
            doc.close()
        return self.candidates_from_pages(pages, note_reference=note_reference, member_table=member_table)

    def certify(self, candidate: dict[str, Any], *, actor: str = "USER") -> dict[str, Any]:
        if not candidate.get("pdf_page_index"):
            raise ValueError("note target requires a page")
        return {"status": "CERTIFIED_NOTE_TARGET", "confirmed_note_pdf_page_index": candidate["pdf_page_index"],
                "target_heading": candidate.get("heading"), "capture_query_title": candidate.get("capture_query_title") or candidate.get("heading"), "locator_method": candidate.get("locator_method"),
                "confidence": candidate.get("score"), "evidence": candidate.get("evidence") or {}, "actor": actor}
