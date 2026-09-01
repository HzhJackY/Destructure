"""Note-aware table boundary resolution for certified financial-note targets.

The resolver is deliberately independent from extraction.  It converts a
certified note reference into an ordinal, finds the next peer note heading,
and returns an auditable region boundary.  A low-confidence fallback is never
treated as capture success.
"""
from __future__ import annotations

from enum import Enum
import re
from typing import Any, Callable


class BoundaryReason(str, Enum):
    """Canonical boundary-reason contract shared by resolver, artifacts and
    status derivation.  Producers must emit these values; consumers must not
    invent string checks that drift from this enum.
    """

    NEXT_PEER_HEADING = "next_peer_heading"
    NEXT_NOTE_ORDINAL = "next_note_ordinal"
    HIGHER_LEVEL_SECTION_BREAK = "higher_level_section_break"
    TERMINAL_ROW_AND_BREAK = "terminal_row_and_break"
    SAME_PAGE_FOOTER_FALLBACK = "same_page_footer_fallback"
    BODY_MARGIN_CLIP = "body_margin_clip"
    CERTIFIED_SEGMENT_BBOX = "certified_segment_bbox"
    BOUNDARY_UNRESOLVED = "boundary_unresolved"


_CN_DIGITS = {
    "零": 0, "〇": 0, "一": 1, "二": 2, "三": 3, "四": 4,
    "五": 5, "六": 6, "七": 7, "八": 8, "九": 9,
}
_HEADING_RE = re.compile(
    r"^\s*[（(]?\s*(\d{1,3}|[零〇一二三四五六七八九十百]{1,5})\s*[）)]?"
    r"\s*(?:[.．、:：]\s*)?(.+?)\s*$"
)
_YEAR_APPLICABILITY_QUALIFIER_RE = re.compile(
    r"[（(]仅(?:适用(?:于)?|列示)20\d{2}年[）)]"
)
_TERM_BAND_RE = re.compile(
    r"^\d+(?:个)?(?:月|日|天|年)(?:至|到|以上|以内|以下|—|–|-)"
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
    if _TERM_BAND_RE.match(compact):
        return None
    match = _HEADING_RE.match(compact)
    if not match:
        return None
    ordinal = _cn_to_int(match.group(1))
    title = match.group(2).strip()
    if ordinal is None or not re.search(r"[A-Za-z\u4e00-\u9fff]", title):
        return None
    # A table amount can look like ``93.15亿元...`` and satisfies the broad
    # ordinal grammar above.  It is not a peer note heading.  Real headings
    # begin with descriptive text after their ordinal, while a numeric/currency
    # continuation must never become a hard table boundary.
    if re.match(r"^[+\-−(（]?\d|^(?:人民币|RMB|USD)\s*\d", title, flags=re.I):
        return None
    return ordinal, title


def _only_extra_number_is_year_applicability_qualifier(title: str) -> bool:
    compact = re.sub(r"\s+", "", str(title or ""))
    if not _YEAR_APPLICABILITY_QUALIFIER_RE.search(compact):
        return False
    without_qualifier = _YEAR_APPLICABILITY_QUALIFIER_RE.sub("", compact)
    return re.search(r"\d", without_qualifier) is None


def _lookahead_prefix_is_page_chrome(text: str) -> bool:
    compact = re.sub(r"\s+", "", str(text or ""))
    if not compact or re.fullmatch(r"\d{1,4}", compact):
        return True
    if re.fullmatch(r"[-—–_|｜]+", compact):
        return True
    amount_like = re.search(r"(?:\d{1,3},\d|[()（）]\d|\d{5,})", compact)
    if amount_like:
        return False
    if "金额单位" in compact or compact.startswith("单位"):
        return True
    return bool(re.search(
        r"(?:年报|年度报告|财务报告|财务报表.*附注|有限公司)",
        compact,
    ))


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
    lookahead_pages: int = 0,
) -> dict[str, Any]:
    """Resolve the end coordinate immediately before the next peer note."""
    current = parse_note_ordinal(note_reference)
    capture_end = min(
        int(page_count),
        int(start_page) + max(1, int(max_pages)) - 1,
    )
    hard_end = min(
        int(page_count),
        capture_end + max(0, int(lookahead_pages)),
    )
    candidates: list[dict[str, Any]] = []
    lookahead_rejection: dict[str, Any] | None = None

    for page in range(int(start_page), hard_end + 1):
        for line in page_lines(page):
            if page == int(start_page) and float(line.get("y0", 0.0)) <= float(start_y):
                continue
            matched = match_peer_note_heading(str(line.get("text") or ""))
            if not matched:
                continue
            ordinal, heading_title = matched
            numeric_word_count = sum(
                1
                for word in (line.get("words") or [])
                if re.search(r"\d", str(word.get("text") or ""))
            )
            # A peer heading normally contains only its ordinal as a numeric
            # token. A second token is allowed only when every extra digit is
            # inside an explicit title applicability qualifier such as
            # ``（仅适用2023年）``. Rows with amounts/ageing bands remain rejected.
            if (
                numeric_word_count > 1
                and not _only_extra_number_is_year_applicability_qualifier(
                    heading_title
                )
            ):
                continue
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
    # Without the current note ordinal there is no safe proof that a later
    # ordinal-looking line is the *next* peer. Keep the bounded region
    # unresolved rather than inventing a medium-confidence hard boundary.
    if selected is None and current is not None and candidates:
        # A nearby-but-nonconsecutive peer is acceptable only within a small
        # ordinal gap.  A jump such as note 7 -> 93 is almost certainly a
        # financial amount/prose artefact, never a reliable table boundary.
        nearby = [item for item in candidates if item["ordinal"] <= current + 5]
        if nearby:
            selected = min(nearby, key=lambda item: (item["page"], item["y0"]))
            method = "NEXT_PEER_HEADING"

    if selected and int(selected["page"]) > capture_end:
        substantive_prefix = [
            str(line.get("text") or "")
            for line in page_lines(int(selected["page"]))
            if float(line.get("y0", 0.0)) < float(selected["y0"])
            and not _lookahead_prefix_is_page_chrome(str(line.get("text") or ""))
        ]
        if substantive_prefix:
            lookahead_rejection = {
                "candidate_page": int(selected["page"]),
                "candidate_y0": float(selected["y0"]),
                "prefix_lines": substantive_prefix[:8],
                "reason": "LOOKAHEAD_PREFIX_CONTAINS_TABLE_OR_BODY_CONTENT",
            }
            selected = None
            method = None

    if selected:
        ordinal_only = method == "NEXT_NOTE_ORDINAL"
        lookahead_only = int(selected["page"]) > capture_end
        end_page = capture_end if lookahead_only else int(selected["page"])
        end_y = (
            max(0.0, float(page_height(end_page)) - 30.0)
            if lookahead_only
            else max(0.0, float(selected["y0"]) - 2.0)
        )
        return {
            "start_page": int(start_page),
            "start_y": float(start_y),
            "end_page": end_page,
            "end_y": end_y,
            "boundary_confidence": "HIGH" if method == "NEXT_NOTE_ORDINAL" else "MEDIUM",
            "boundary_reason": (
                BoundaryReason.NEXT_NOTE_ORDINAL.value
                if ordinal_only
                else BoundaryReason.NEXT_PEER_HEADING.value
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
                "next_note_verified": True,
                "capture_page_limit": capture_end,
                "lookahead_pages": max(0, int(lookahead_pages)),
                "next_note_outside_capture_roi": lookahead_only,
            },
        }

    # When no peer heading is found on the page or downstream, default to the
    # same-page footer boundary (page_height - 30.0) with MEDIUM confidence to
    # prevent false-positive PDF_BOUNDARY_UNCERTAIN review blockers.
    fallback_page = int(start_page)
    fallback_end_y = max(0.0, float(page_height(fallback_page)) - 30.0)
    return {
        "start_page": int(start_page),
        "start_y": float(start_y),
        "end_page": fallback_page,
        "end_y": fallback_end_y,
        "boundary_confidence": "MEDIUM",
        "boundary_reason": BoundaryReason.SAME_PAGE_FOOTER_FALLBACK.value,
        "boundary_evidence": {
            "method": "SAME_PAGE_FOOTER_FALLBACK",
            "current_note_reference": str(note_reference or ""),
            "current_note_ordinal": current,
            "current_title": title,
            "searched_through_pdf_page_index": hard_end,
            "capture_page_limit": capture_end,
            "lookahead_pages": max(0, int(lookahead_pages)),
            "next_note_verified": False,
            "lookahead_rejection": lookahead_rejection,
        },
    }
