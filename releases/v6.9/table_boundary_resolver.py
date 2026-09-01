"""Note-aware table boundary resolution for certified financial-note targets.

The resolver is deliberately independent from extraction.  It converts a
certified note reference into an ordinal, finds the next peer note heading,
and returns an auditable region boundary.  A low-confidence fallback is never
treated as capture success.
"""
from __future__ import annotations

import re
from typing import Any, Callable


_CN_DIGITS = {
    "零": 0, "〇": 0, "一": 1, "二": 2, "三": 3, "四": 4,
    "五": 5, "六": 6, "七": 7, "八": 8, "九": 9,
}
_HEADING_RE = re.compile(
    r"^\s*[（(]?\s*(\d{1,3}|[零〇一二三四五六七八九十百]{1,5})\s*[）)]?"
    r"\s*(?:[.．、:：]\s*)?(.+?)\s*$"
)


def _cn_to_int(token: str) -> int | None:
    token = str(token or "").strip()
    if not token:
        return None
    if token.isdigit():
        return int(token)
    if token == "十":
        return 10
    if "百" in token:
        left, right = token.split("百", 1)
        hundreds = _CN_DIGITS.get(left, 1)
        tail = _cn_to_int(right) if right else 0
        return hundreds * 100 + (tail or 0)
    if "十" in token:
        left, right = token.split("十", 1)
        tens = _CN_DIGITS.get(left, 1) if left else 1
        ones = _CN_DIGITS.get(right, 0) if right else 0
        return tens * 10 + ones
    if all(ch in _CN_DIGITS for ch in token):
        value = 0
        for ch in token:
            value = value * 10 + _CN_DIGITS[ch]
        return value
    return None


def parse_note_ordinal(note_reference: Any) -> int | None:
    """Parse ``9``, ``附注八-9``, ``（十）`` and similar forms."""
    raw = str(note_reference or "").strip()
    if not raw:
        return None
    tail = re.split(r"[-—–/]", raw)[-1]
    matches = re.findall(r"\d{1,3}|[零〇一二三四五六七八九十百]{1,5}", tail)
    if not matches:
        return None
    return _cn_to_int(matches[-1])


def match_peer_note_heading(text: str) -> tuple[int, str] | None:
    compact = re.sub(r"\s+", "", str(text or ""))
    match = _HEADING_RE.match(compact)
    if not match:
        return None
    ordinal = _cn_to_int(match.group(1))
    title = match.group(2).strip()
    if ordinal is None or not re.search(r"[A-Za-z\u4e00-\u9fff]", title):
        return None
    return ordinal, title


def resolve_table_boundary(
    *,
    note_reference: Any,
    title: str,
    start_page: int,
    start_y: float,
    title_x0: float,
    page_count: int,
    page_height: Callable[[int], float],
    page_lines: Callable[[int], list[dict[str, Any]]],
    max_pages: int = 8,
) -> dict[str, Any]:
    """Resolve the end coordinate immediately before the next peer note."""
    current = parse_note_ordinal(note_reference)
    hard_end = min(int(page_count), int(start_page) + max(1, int(max_pages)) - 1)
    candidates: list[dict[str, Any]] = []

    for page in range(int(start_page), hard_end + 1):
        for line in page_lines(page):
            if page == int(start_page) and float(line.get("y0", 0.0)) <= float(start_y):
                continue
            matched = match_peer_note_heading(str(line.get("text") or ""))
            if not matched:
                continue
            numeric_word_count = sum(
                1
                for word in (line.get("words") or [])
                if re.search(r"\d", str(word.get("text") or ""))
            )
            # A peer heading normally contains only its ordinal as a numeric
            # token. Rows with multiple amounts must never terminate a table.
            if numeric_word_count > 1:
                continue
            ordinal, heading_title = matched
            if current is not None and ordinal <= current:
                continue
            # Note headings are peers of the current title and therefore remain
            # near its left alignment.  This rejects numeric table rows.
            if float(line.get("x0", 0.0)) > float(title_x0) + 90.0:
                continue
            candidates.append({
                "page": page,
                "y0": float(line.get("y0", 0.0)),
                "ordinal": ordinal,
                "title": heading_title,
                "text": str(line.get("text") or ""),
            })

    selected = None
    method = None
    if current is not None:
        exact = [item for item in candidates if item["ordinal"] == current + 1]
        if exact:
            selected = min(exact, key=lambda item: (item["page"], item["y0"]))
            method = "NEXT_NOTE_ORDINAL"
    if selected is None and candidates:
        selected = min(candidates, key=lambda item: (item["page"], item["y0"]))
        method = "NEXT_PEER_HEADING"

    if selected:
        return {
            "start_page": int(start_page),
            "start_y": float(start_y),
            "end_page": int(selected["page"]),
            "end_y": max(0.0, float(selected["y0"]) - 2.0),
            "boundary_confidence": "HIGH" if method == "NEXT_NOTE_ORDINAL" else "MEDIUM",
            "boundary_reason": (
                f"next_note_{selected['ordinal']}"
                if method == "NEXT_NOTE_ORDINAL"
                else f"next_peer_heading_{selected['ordinal']}"
            ),
            "boundary_evidence": {
                "method": method,
                "current_note_reference": str(note_reference or ""),
                "current_note_ordinal": current,
                "current_title": title,
                "next_note_ordinal": selected["ordinal"],
                "next_note_title": selected["title"],
                "next_note_heading_raw": selected["text"],
                "next_note_pdf_page_index": selected["page"],
                "next_note_y0": selected["y0"],
            },
        }

    return {
        "start_page": int(start_page),
        "start_y": float(start_y),
        "end_page": hard_end,
        "end_y": float(page_height(hard_end)),
        "boundary_confidence": "LOW",
        "boundary_reason": "boundary_unresolved",
        "boundary_evidence": {
            "method": "NO_PEER_HEADING_FOUND",
            "current_note_reference": str(note_reference or ""),
            "current_note_ordinal": current,
            "current_title": title,
            "searched_through_pdf_page_index": hard_end,
        },
    }
