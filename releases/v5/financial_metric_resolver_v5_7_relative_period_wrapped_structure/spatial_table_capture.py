#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Spatial ROI table capture for v5.1.

Core contract:
1. Named-note title creates a HARD table-context reset.
2. Exact ROI runs from target title bottom to next note title top (same-page supported).
3. Logical numeric columns are defined by period-header x anchors, not by how many
   numeric fragments happen to be extracted from a data row.
4. Numeric fragments are reconstructed inside each logical column anchor.
5. Raw labels and source coordinates remain auditable.
"""

from __future__ import annotations

import dataclasses
import re
from pathlib import Path
from typing import Any, Optional

import fitz  # PyMuPDF

from financial_metric_pdf_resolver import (
    clean_cell,
    file_sha256,
    normalize_text,
    parse_number,
)

_NOTE_LINE_RE = re.compile(r"^\s*(\d{1,3})\s*(?:[\.．、]\s*)?(.+?)\s*$")
_YEAR_RE = re.compile(r"(20\d{2})")
_RELATIVE_PERIOD_PATTERNS = [
    (re.compile(r"^(?:本年累计数|本期累计数|本期数|本年数|本期|本年|当期累计数|当期)$"), "CURRENT"),
    (re.compile(r"^(?:上年累计数|上期累计数|上期数|上年数|上期|上年|去年同期|上年同期)$"), "PRIOR"),
    (re.compile(r"^(?:期末|年末|本期期末|本年末)$"), "CURRENT_END"),
    (re.compile(r"^(?:期初|年初|本期期初|本年初)$"), "CURRENT_BEGIN"),
]
_UNIT_RE = re.compile(
    r"(?:单位\s*[:：]?\s*)?(?:人民币\s*)?(亿元|百万元|万元|千元|元)"
)


def _word_dict(word_tuple) -> dict[str, Any]:
    x0, y0, x1, y1, text, block_no, line_no, word_no = word_tuple[:8]
    return {
        "x0": float(x0), "y0": float(y0), "x1": float(x1), "y1": float(y1),
        "xc": (float(x0) + float(x1)) / 2,
        "yc": (float(y0) + float(y1)) / 2,
        "text": str(text),
        "block": int(block_no), "line": int(line_no), "word": int(word_no),
    }


def _group_lines(words: list[dict[str, Any]], y_tol: float = 3.8) -> list[dict[str, Any]]:
    if not words:
        return []
    words = sorted(words, key=lambda w: (w["yc"], w["x0"]))
    groups: list[list[dict[str, Any]]] = []
    centers: list[float] = []

    for w in words:
        best_i = None
        best_d = None
        for i in range(max(0, len(groups) - 4), len(groups)):
            d = abs(w["yc"] - centers[i])
            if d <= y_tol and (best_d is None or d < best_d):
                best_i, best_d = i, d
        if best_i is None:
            groups.append([w])
            centers.append(w["yc"])
        else:
            groups[best_i].append(w)
            centers[best_i] = sum(x["yc"] for x in groups[best_i]) / len(groups[best_i])

    lines = []
    for ws in groups:
        ws = sorted(ws, key=lambda x: x["x0"])
        # Preserve spaces only when physically separated enough; Chinese text usually
        # reconstructs correctly after normalize_item_label removes spaces.
        parts = []
        prev_x1 = None
        for w in ws:
            if prev_x1 is not None and w["x0"] - prev_x1 > 5:
                parts.append(" ")
            parts.append(w["text"])
            prev_x1 = w["x1"]
        text = "".join(parts).strip()
        lines.append({
            "words": ws,
            "text": text,
            "x0": min(w["x0"] for w in ws),
            "x1": max(w["x1"] for w in ws),
            "y0": min(w["y0"] for w in ws),
            "y1": max(w["y1"] for w in ws),
            "yc": sum(w["yc"] for w in ws) / len(ws),
        })
    return sorted(lines, key=lambda x: (x["y0"], x["x0"]))


def _page_lines(doc: fitz.Document, page_no: int) -> list[dict[str, Any]]:
    page = doc[page_no - 1]
    words = [_word_dict(w) for w in page.get_text("words", sort=True)]
    return _group_lines(words)


def _line_compact(text: str) -> str:
    return re.sub(r"\s+", "", clean_cell(text))


def _match_note_heading(text: str, expected_no: Optional[str] = None) -> Optional[tuple[str, str]]:
    """
    Accept common annual-report note headings:
      34. 业务及管理费
      34、业务及管理费
      34．业务及管理费
      34 业务及管理费

    Reject pure numeric/data lines by requiring non-numeric title content.
    """
    compact = _line_compact(text)
    m = _NOTE_LINE_RE.match(compact)
    if not m:
        return None
    no, title = m.group(1), m.group(2)
    if expected_no is not None and no != str(expected_no):
        return None
    if not re.search(r"[A-Za-z\u4e00-\u9fff]", title):
        return None
    return no, title


def _title_query_compatible(title_text: str, table_query: str) -> bool:
    """
    Allow common cross-company title variation while staying conservative.

    Example:
      query  = 业务及管理费和其他业务成本
      title  = 业务及管理费

    A numbered heading with a substantial containment relationship is accepted;
    nearby table-header evidence still decides body-vs-TOC location.
    """
    title = _line_compact(title_text)
    query = _line_compact(table_query)
    if not title or not query:
        return False
    if query in title:
        return True
    if title in query and len(title) >= 4:
        return True
    return False


def infer_note_number_from_located_title(
    located_title: str,
    table_query: str,
) -> Optional[str]:
    matched = _match_note_heading(located_title)
    if not matched:
        return None
    no, title = matched
    if not _title_query_compatible(title, table_query):
        return None
    return no


def _parse_period_token(text: str) -> Optional[dict[str, str]]:
    raw = clean_cell(text)
    compact = _line_compact(raw)
    if not compact:
        return None

    m = _YEAR_RE.search(compact)
    if m:
        year = m.group(1)
        return {
            "year": year,
            "period_label": year,
            "period_kind": "ABSOLUTE_YEAR",
            "token": raw,
        }

    period_core = re.sub(
        r"[（(]?(?:已重述|经重述|重述后|重述)[）)]?",
        "",
        compact,
    )
    period_core = re.sub(
        r"(?:人民币)?(?:亿元|百万元|万元|千元|元)$",
        "",
        period_core,
    )

    for pattern, kind in _RELATIVE_PERIOD_PATTERNS:
        if pattern.match(period_core):
            return {
                "year": period_core,
                "period_label": period_core,
                "period_kind": kind,
                "token": raw,
            }
    return None


def _period_words(line: dict[str, Any]) -> list[dict[str, Any]]:
    """
    Detect both absolute-year and relative-period leaf headers.

    Supports:
      2025年度 / 2024年度
      本年累计数 / 上年累计数
      本期 / 上期
      期末 / 期初

    Adjacent words are also joined to handle PDFs that split
    “本年”“累计数” into separate word objects.
    """
    words = line.get("words") or []
    candidates: list[dict[str, Any]] = []

    # Prefer longer 3/2-word spans, then single words.
    for span_len in (3, 2, 1):
        for i in range(0, len(words) - span_len + 1):
            span = words[i:i + span_len]
            if span_len > 1:
                gaps = [
                    span[j + 1]["x0"] - span[j]["x1"]
                    for j in range(len(span) - 1)
                ]
                if any(g > 16 for g in gaps):
                    continue
            joined = "".join(str(w["text"]) for w in span)
            parsed = _parse_period_token(joined)
            if not parsed:
                continue
            hit = {
                "x0": min(w["x0"] for w in span),
                "x1": max(w["x1"] for w in span),
                "y0": min(w["y0"] for w in span),
                "y1": max(w["y1"] for w in span),
                "xc": (
                    min(w["x0"] for w in span)
                    + max(w["x1"] for w in span)
                ) / 2,
                "yc": sum(w["yc"] for w in span) / len(span),
                **parsed,
                "_span_len": span_len,
            }
            candidates.append(hit)

    # De-duplicate overlapping detections, keeping the longer textual span.
    candidates.sort(key=lambda h: (-h["_span_len"], h["xc"]))
    selected: list[dict[str, Any]] = []
    for hit in candidates:
        if any(
            abs(hit["xc"] - old["xc"]) <= 8
            and abs(hit["yc"] - old["yc"]) <= 5
            for old in selected
        ):
            continue
        hit.pop("_span_len", None)
        selected.append(hit)
    return sorted(selected, key=lambda h: h["xc"])


def _contains_period_header(text: str) -> bool:
    compact = _line_compact(text)
    if _parse_period_token(compact):
        return True
    # Combined line such as "本年累计数 上年累计数".
    return any(
        token in compact
        for token in [
            "本年累计数", "上年累计数", "本期累计数", "上期累计数",
            "本期数", "上期数", "本年数", "上年数",
        ]
    )


def _is_unit_only_header(text: str) -> bool:
    compact = _line_compact(text)
    if not compact:
        return False
    cleaned = re.sub(r"(?:人民币)?(?:亿元|百万元|万元|千元|元)", "", compact)
    return cleaned == ""


def _title_score(line_text: str, table_query: str, note_number: Optional[str]) -> int:
    compact = _line_compact(line_text)
    q = _line_compact(table_query)
    score = 0
    if q and q in compact:
        score += 20

    matched = (
        _match_note_heading(line_text, note_number)
        if note_number else
        _match_note_heading(line_text)
    )
    if note_number and matched:
        score += 15
        if _title_query_compatible(matched[1], table_query):
            score += 15
    elif not note_number and matched and _title_query_compatible(matched[1], table_query):
        # A numbered heading compatible with the requested table is much stronger
        # than prose. Nearby period/header evidence then separates body from TOC.
        score += 25
    return score


def locate_table_roi(
    pdf_path: Path,
    table_query: str,
    note_number: Optional[str] = None,
    start_page_override: Optional[int] = None,
    max_pages: int = 8,
) -> dict[str, Any]:
    doc = fitz.open(str(pdf_path))
    note_number = str(note_number).strip() if note_number else None

    best = None
    if start_page_override:
        p = int(start_page_override)
        if p < 1 or p > doc.page_count:
            doc.close()
            raise ValueError(f"起始页超出PDF范围：{p}")
        lines = _page_lines(doc, p)
        # Prefer an actual matching title line on the override page; otherwise top.
        candidates = [
            (_title_score(l["text"], table_query, note_number), l)
            for l in lines
        ]
        candidates = [x for x in candidates if x[0] > 0]
        title_line = max(candidates, key=lambda x: x[0])[1] if candidates else {
            "text": table_query, "y0": 0.0, "y1": 0.0,
        }
        best = (999, p, title_line)
    else:
        for p in range(1, doc.page_count + 1):
            lines = _page_lines(doc, p)
            for i, line in enumerate(lines):
                candidates = [line]

                # Only merge a following line when the current line does NOT
                # already contain the requested table name. Otherwise a genuine
                # title like “34. 业务及管理费” can accidentally swallow the next
                # parent header line “本集团 / 本公司”, moving ROI start_y below it
                # and destroying scope extraction.
                current_heading = _match_note_heading(line["text"])
                current_has_query = (
                    _line_compact(table_query)
                    and (
                        _line_compact(table_query) in _line_compact(line["text"])
                        or (
                            current_heading is not None
                            and _title_query_compatible(current_heading[1], table_query)
                        )
                    )
                )
                if i + 1 < len(lines) and not current_has_query:
                    merged = dict(line)
                    merged["text"] = line["text"] + lines[i + 1]["text"]
                    merged["y1"] = lines[i + 1]["y1"]
                    candidates.append(merged)
                for candidate in candidates:
                    score = _title_score(candidate["text"], table_query, note_number)
                    if score:
                        # Prefer the real note body over a table-of-contents hit:
                        # nearby period headers / tabular numeric lines are strong evidence.
                        nearby = [
                            x for x in lines[i + 1:i + 24]
                            if x["y0"] - candidate["y1"] <= 320
                        ]
                        if any(_year_words(x) for x in nearby):
                            score += 25
                        numeric_like_lines = 0
                        for x in nearby:
                            digit_words = sum(
                                1 for w in x["words"]
                                if any(ch.isdigit() for ch in w["text"])
                            )
                            if digit_words >= 2:
                                numeric_like_lines += 1
                        score += min(15, numeric_like_lines * 3)

                    if score and (best is None or score > best[0]):
                        best = (score, p, candidate)

    if best is None:
        doc.close()
        raise ValueError(
            f"未定位到目标附注/表：{table_query!r}"
            + (f"；附注号={note_number}" if note_number else "")
        )

    _, start_page, title_line = best
    start_y = float(title_line["y1"]) + 2.0
    located_title = clean_cell(title_line["text"])

    resolved_note_number = note_number
    note_number_source = "USER_PROVIDED" if note_number else None
    if not resolved_note_number:
        resolved_note_number = infer_note_number_from_located_title(
            located_title,
            table_query,
        )
        if resolved_note_number:
            note_number_source = "INFERRED_FROM_LOCATED_TITLE"

    hard_end_page = min(doc.page_count, start_page + max(1, int(max_pages)) - 1)
    end_page = hard_end_page
    end_y = float(doc[end_page - 1].rect.height)
    boundary_reason = "max_pages"

    # Strongest boundary: exact next numbered note, including same-page position.
    next_no = str(int(resolved_note_number) + 1) if resolved_note_number and resolved_note_number.isdigit() else None
    if next_no:
        for p in range(start_page, hard_end_page + 1):
            for line in _page_lines(doc, p):
                if p == start_page and line["y0"] <= start_y:
                    continue
                matched_next = _match_note_heading(line["text"], next_no)
                # A note heading should be near the left/title alignment; avoid
                # treating table data such as "35 万元..." as a next-note boundary.
                title_x0 = float(title_line.get("x0", 0.0))
                spatially_heading_like = float(line.get("x0", 0.0)) <= title_x0 + 90.0
                if matched_next and spatially_heading_like:
                    end_page = p
                    end_y = max(0.0, float(line["y0"]) - 2.0)
                    boundary_reason = f"next_note_{next_no}"
                    break
            if boundary_reason.startswith("next_note_"):
                break

    page_heights = {p: float(doc[p - 1].rect.height) for p in range(start_page, end_page + 1)}
    page_widths = {p: float(doc[p - 1].rect.width) for p in range(start_page, end_page + 1)}
    doc.close()

    return {
        "start_page": start_page,
        "start_y": start_y,
        "end_page": end_page,
        "end_y": end_y,
        "located_title": located_title,
        "resolved_note_number": resolved_note_number,
        "note_number_source": note_number_source,
        "boundary_reason": boundary_reason,
        "page_heights": page_heights,
        "page_widths": page_widths,
    }


def _lines_in_roi(
    doc: fitz.Document,
    roi: dict[str, Any],
    page_no: int,
) -> list[dict[str, Any]]:
    lines = _page_lines(doc, page_no)
    height = float(doc[page_no - 1].rect.height)
    y0 = roi["start_y"] if page_no == roi["start_page"] else 0.0
    y1 = roi["end_y"] if page_no == roi["end_page"] else height
    return [l for l in lines if l["y1"] >= y0 and l["y0"] <= y1]


def _year_words(line: dict[str, Any]) -> list[dict[str, Any]]:
    # Backward-compatible name: now returns all recognized period leaf headers.
    return _period_words(line)


def _detect_header(
    lines: list[dict[str, Any]],
    page_width: float,
) -> Optional[dict[str, Any]]:
    candidates = []
    for i, line in enumerate(lines[:100]):
        hits = _period_words(line)
        if not hits:
            continue
        # Financial detail tables generally have 1-8 logical period/scope columns.
        if 1 <= len(hits) <= 8:
            spread = (
                max(h["xc"] for h in hits) - min(h["xc"] for h in hits)
                if len(hits) > 1 else 0
            )
            duplicate_period_bonus = 4 if len({h["period_label"] for h in hits}) < len(hits) else 0
            score = (
                len(hits) * 12
                + spread / max(page_width, 1) * 10
                + duplicate_period_bonus
            )
            candidates.append((score, i, line, hits))
    if not candidates:
        return None

    _, idx, line, hits = max(candidates, key=lambda x: x[0])
    hits = sorted(hits, key=lambda x: x["xc"])
    return {
        "line_index": idx,
        "line": line,
        "anchors": [h["xc"] for h in hits],
        # `years` remains for backward compatibility. Relative periods use their
        # label here and are resolved to absolute years later using document_year.
        "years": [h["year"] for h in hits],
        "period_labels": [h["period_label"] for h in hits],
        "period_kinds": [h["period_kind"] for h in hits],
        "header_y0": line["y0"],
        "header_y1": line["y1"],
    }


def _column_half_widths(anchors: list[float], page_width: float) -> list[float]:
    if len(anchors) == 1:
        return [page_width * 0.18]
    widths = []
    for i, a in enumerate(anchors):
        left_gap = a - anchors[i - 1] if i > 0 else anchors[1] - a
        right_gap = anchors[i + 1] - a if i < len(anchors) - 1 else a - anchors[i - 1]
        widths.append(max(20.0, min(left_gap, right_gap) * 0.48))
    return widths


def _nearest_anchor_index(x: float, anchors: list[float]) -> int:
    return min(range(len(anchors)), key=lambda i: abs(x - anchors[i]))


def _is_numeric_punct(text: str) -> bool:
    s = re.sub(r"\s+", "", str(text))
    return bool(s) and all(ch in "()（）-—–" for ch in s)


def _is_numeric_fragment(text: str) -> bool:
    s = re.sub(r"\s+", "", str(text))
    if not s:
        return False
    allowed = set("0123456789,.-—–()（）%％")
    return all(ch in allowed for ch in s) and any(ch.isdigit() for ch in s)


def _join_numeric_fragments(words: list[dict[str, Any]]) -> str:
    if not words:
        return ""
    parts = [w["text"].strip() for w in sorted(words, key=lambda x: x["x0"])]
    s = "".join(parts)
    s = s.replace("％", "%").replace("，", ",").replace("．", ".")
    return re.sub(r"\s+", "", s)


def _extract_unit(lines: list[dict[str, Any]]) -> Optional[str]:
    for line in lines:
        text = clean_cell(line["text"])
        m = _UNIT_RE.search(text)
        if m:
            return m.group(1)
    return None


def _scope_value(text: str) -> Optional[str]:
    n = normalize_text(clean_cell(text))
    if not n:
        return None
    if normalize_text("本集团") in n or n == normalize_text("集团"):
        return "本集团"
    if normalize_text("本公司") in n or n == normalize_text("公司"):
        return "本公司"
    return None


def _anchor_local_gap(anchors: list[float], idx: int, page_width: float) -> float:
    if len(anchors) <= 1:
        return page_width * 0.25
    gaps = []
    if idx > 0:
        gaps.append(anchors[idx] - anchors[idx - 1])
    if idx < len(anchors) - 1:
        gaps.append(anchors[idx + 1] - anchors[idx])
    return min(gaps) if gaps else page_width * 0.25


def _assign_parent_header_hits(
    anchors: list[float],
    hits: list[dict[str, Any]],
    page_width: float,
) -> dict[int, dict[str, Any]]:
    """
    Bind parent-level header labels to all child leaf columns in their span.

    Example:
            本集团                 本公司
         2022   2021          2022   2021

    The old nearest-single-anchor logic assigned 本集团/本公司 to only one year
    column each. This routine propagates each parent label across its spatially
    plausible child anchors.
    """
    if not hits:
        return {}

    hits = sorted(hits, key=lambda x: x["xc"])
    assigned: dict[int, dict[str, Any]] = {}

    for i, anchor in enumerate(anchors):
        nearest = min(hits, key=lambda h: abs(anchor - h["xc"]))
        distance = abs(anchor - nearest["xc"])
        local_gap = _anchor_local_gap(anchors, i, page_width)
        threshold = max(28.0, local_gap * 0.85)
        if distance <= threshold:
            assigned[i] = nearest

    return assigned


def _header_metadata(
    lines: list[dict[str, Any]],
    header: dict[str, Any],
    page_width: float,
) -> tuple[list[dict[str, Any]], float]:
    anchors = header["anchors"]
    years = header["years"]
    period_labels = header.get("period_labels", years)
    period_kinds = header.get("period_kinds", ["ABSOLUTE_YEAR"] * len(anchors))
    half = _column_half_widths(anchors, page_width)
    metadata = [
        {
            "year": years[i],
            "period_label": period_labels[i],
            "period_kind": period_kinds[i],
            "scope": None,
            "restated": False,
            "tokens": [period_labels[i]],
        }
        for i in range(len(anchors))
    ]

    header_bottom = header["header_y1"]

    # Parent/group headers may be ABOVE the year row. Scan both sides.
    lo = max(0, header["line_index"] - 10)
    hi = min(len(lines), header["line_index"] + 12)
    nearby = lines[lo:hi]

    for line in nearby:
        if line["y1"] < header["header_y0"] - 120:
            continue
        if line["y0"] > header["header_y1"] + 100:
            continue

        scope_hits = []
        restated_hits = []
        for w in line["words"]:
            t = clean_cell(w["text"])
            if not t:
                continue
            scope = _scope_value(t)
            if scope:
                scope_hits.append({**w, "scope": scope, "token": t})
            nt = normalize_text(t)
            if any(normalize_text(x) in nt for x in ["已重述", "经重述", "重述"]):
                restated_hits.append({**w, "token": t})

        if scope_hits:
            assignments = _assign_parent_header_hits(anchors, scope_hits, page_width)
            for idx, hit in assignments.items():
                metadata[idx]["scope"] = hit["scope"]
                if hit["token"] not in metadata[idx]["tokens"]:
                    metadata[idx]["tokens"].insert(0, hit["token"])
            header_bottom = max(header_bottom, line["y1"])

        if restated_hits:
            assignments = _assign_parent_header_hits(anchors, restated_hits, page_width)
            for idx, hit in assignments.items():
                metadata[idx]["restated"] = True
                if hit["token"] not in metadata[idx]["tokens"]:
                    metadata[idx]["tokens"].append(hit["token"])
            header_bottom = max(header_bottom, line["y1"])

    # Extend the header band through repeated period/unit rows below the leaf
    # header. This prevents “人民币元” from being materialized as a data row.
    for line in lines[header["line_index"]:header["line_index"] + 12]:
        numeric_words = [w for w in line["words"] if _is_numeric_fragment(w["text"])]
        if len(numeric_words) >= max(1, len(anchors) // 2):
            break
        if (
            _period_words(line)
            or any(_scope_value(w["text"]) for w in line["words"])
            or _is_unit_only_header(line["text"])
        ):
            header_bottom = max(header_bottom, line["y1"])

    # Explicit per-column labels below the period row remain supported.
    for line in lines[header["line_index"] + 1:header["line_index"] + 12]:
        if line["y0"] - header["header_y1"] > 90:
            break
        numeric_words = [w for w in line["words"] if _is_numeric_fragment(w["text"])]
        if numeric_words:
            break

        used = False
        for w in line["words"]:
            t = clean_cell(w["text"])
            nt = normalize_text(t)
            if not t:
                continue
            idx = _nearest_anchor_index(w["xc"], anchors)
            if abs(w["xc"] - anchors[idx]) > half[idx] * 1.35:
                continue

            scope = _scope_value(t)
            if scope:
                metadata[idx]["scope"] = scope
                if t not in metadata[idx]["tokens"]:
                    metadata[idx]["tokens"].append(t)
                used = True

            if any(normalize_text(x) in nt for x in ["已重述", "经重述", "重述"]):
                metadata[idx]["restated"] = True
                if t not in metadata[idx]["tokens"]:
                    metadata[idx]["tokens"].append(t)
                used = True

        if used:
            header_bottom = max(header_bottom, line["y1"])

    return metadata, header_bottom


def _line_to_spatial_cells(
    line: dict[str, Any],
    anchors: list[float],
    page_width: float,
) -> dict[str, Any]:
    half = _column_half_widths(anchors, page_width)
    numeric_groups: list[list[dict[str, Any]]] = [[] for _ in anchors]
    assigned_ids = set()

    # Numeric region begins well to the left of the first anchor, but not inside labels.
    if len(anchors) > 1:
        first_gap = anchors[1] - anchors[0]
    else:
        first_gap = page_width * 0.25
    numeric_left = anchors[0] - first_gap * 0.55

    for wi, w in enumerate(line["words"]):
        if w["xc"] < numeric_left:
            continue
        if not (_is_numeric_fragment(w["text"]) or _is_numeric_punct(w["text"])):
            continue
        idx = _nearest_anchor_index(w["xc"], anchors)
        if abs(w["xc"] - anchors[idx]) <= half[idx] * 1.5:
            numeric_groups[idx].append(w)
            assigned_ids.add(wi)

    values = []
    for group in numeric_groups:
        raw = _join_numeric_fragments(group)
        if raw:
            num, cell_unit, ok = parse_number(raw)
            if ok:
                values.append((raw, num, cell_unit))
            else:
                values.append((raw, None, None))
        else:
            values.append(("", None, None))

    label_words = [
        w for wi, w in enumerate(line["words"])
        if wi not in assigned_ids and w["xc"] < numeric_left
    ]
    label = "".join(w["text"] for w in label_words).strip()
    return {
        "label": label,
        "label_x0": min((w["x0"] for w in label_words), default=line["x0"]),
        "values": values,
        "has_numeric": any(raw for raw, _, _ in values),
    }


def _is_explicit_section_label(text: str) -> bool:
    raw = clean_cell(text)
    compact = _line_compact(raw).rstrip("：:")
    if not compact:
        return False
    if raw.rstrip().endswith(("：", ":")):
        return True
    exact = {
        "按费用项目", "减", "加", "其中",
        "可归属于保险合同组合的费用",
        "不可归属于保险合同组合的费用",
    }
    return compact in exact


def _append_text_only_row(
    rows: list,
    *,
    row_order: int,
    page: int,
    text: str,
    parent_section: Optional[str],
    header_source_page: Optional[int],
    as_section: bool,
):
    from table_capture import TableRow, normalize_item_label

    norm = normalize_item_label(text)
    rows.append(TableRow(
        row_order=row_order,
        page=page,
        block_id=f"spatial_p{page}",
        source_method=(
            "spatial_roi+section_header"
            if as_section else
            "spatial_roi+text_only_detail"
        ),
        raw_item=text,
        normalized_item=norm,
        canonical_item=None,
        mapping_status="UNMAPPED",
        row_type="SECTION_HEADER" if as_section else "DETAIL",
        row_level=0 if as_section else (1 if parent_section else 0),
        parent_section=None if as_section else parent_section,
        cells=[],
        header_source_page=header_source_page,
    ))
    return norm


def capture_named_table_spatial(
    pdf_path: Path,
    table_query: str,
    note_number: Optional[str] = None,
    start_page_override: Optional[int] = None,
    max_pages: int = 8,
    progress_callback=None,
):
    # Lazy import avoids circular import: table_capture calls this function only
    # after its dataclasses are fully defined.
    from table_capture import (
        TableColumn, TableCell, TableRow, TableCaptureResult,
        normalize_item_label, classify_row_type,
    )

    roi = locate_table_roi(
        pdf_path=pdf_path,
        table_query=table_query,
        note_number=note_number,
        start_page_override=start_page_override,
        max_pages=max_pages,
    )
    doc = fitz.open(str(pdf_path))

    if progress_callback:
        progress_callback({"event": "open_done", "message": "已定位目标附注ROI"})

    start_lines = _lines_in_roi(doc, roi, roi["start_page"])
    header = _detect_header(start_lines, roi["page_widths"][roi["start_page"]])
    if header is None:
        doc.close()
        raise ValueError("目标附注区域已定位，但未识别到年份/期间表头列锚点。")

    metadata, header_bottom = _header_metadata(
        start_lines, header, roi["page_widths"][roi["start_page"]]
    )
    root_width = roi["page_widths"][roi["start_page"]]
    anchor_ratios = [a / root_width for a in header["anchors"]]

    columns = []
    for i, meta in enumerate(metadata):
        tokens = meta["tokens"]
        columns.append(TableColumn(
            ordinal=i,
            source_column_index=i + 1,
            header_raw=" | ".join(tokens),
            year=meta["year"],
            scope=meta["scope"],
            restated=bool(meta["restated"]),
            period_label=meta.get("period_label") or meta["year"],
        ))

    # Unit search includes the whole start page to catch "单位：" above the ROI title.
    all_start_lines = _page_lines(doc, roi["start_page"])
    unit = _extract_unit(all_start_lines)

    rows: list[Any] = []
    row_order = 0
    parent_section = None
    pending: Optional[dict[str, Any]] = None
    source_pages = []

    for page_no in range(roi["start_page"], roi["end_page"] + 1):
        lines = _lines_in_roi(doc, roi, page_no)
        page_width = roi["page_widths"][page_no]

        # HARD context reset on root page. Continuation pages may repeat headers;
        # if so, use their own anchors. Otherwise inherit normalized root anchors.
        current_header = _detect_header(lines, page_width)
        if page_no == roi["start_page"]:
            anchors = header["anchors"]
            data_y_min = header_bottom + 2
            header_source_page = None
        elif current_header and len(current_header["anchors"]) == len(columns):
            anchors = current_header["anchors"]
            _, current_bottom = _header_metadata(lines, current_header, page_width)
            data_y_min = current_bottom + 2
            header_source_page = None
        else:
            anchors = [r * page_width for r in anchor_ratios]
            data_y_min = 0.0
            header_source_page = roi["start_page"]

        page_rows_before = len(rows)

        for line in lines:
            if line["y1"] < data_y_min:
                continue

            parsed = _line_to_spatial_cells(line, anchors, page_width)
            label = clean_cell(parsed["label"])
            compact = _line_compact(label)

            # Ignore title/header/prose rows.
            if not label and not parsed["has_numeric"]:
                continue
            if label and (
                _contains_period_header(label)
                or _is_unit_only_header(label)
                or compact in {"本集团", "本公司", "项目", "费用项目"}
            ):
                continue
            if label and len(label) > 55 and not parsed["has_numeric"]:
                # Introductory prose sentence.
                continue

            if parsed["has_numeric"]:
                # Resolve pending text-only line: wrapped label vs section header.
                if pending:
                    pending_text = pending["text"]
                    pending_page = pending["page"]
                    pending_header_source = (
                        roi["start_page"]
                        if pending_page > roi["start_page"] else None
                    )

                    if _is_explicit_section_label(pending_text):
                        # True structural marker, e.g. “减：” or “按费用项目：”.
                        row_order += 1
                        section_norm = _append_text_only_row(
                            rows,
                            row_order=row_order,
                            page=pending_page,
                            text=pending_text,
                            parent_section=parent_section,
                            header_source_page=pending_header_source,
                            as_section=True,
                        )
                        parent_section = section_norm
                    elif parsed["label_x0"] > pending["x0"] + 7:
                        # Wrapped accounting label:
                        #   当期发生的保费获取
                        #       现金流        594,788,447 ...
                        # The indented second line is a continuation, not a child section.
                        label = pending_text + label
                    else:
                        # Same-indent text-only line followed by a new numeric row is
                        # usually a genuine detail with blank values, e.g. “租赁费”.
                        # Preserve it as DETAIL instead of turning it into a section
                        # or concatenating it with the next item.
                        row_order += 1
                        _append_text_only_row(
                            rows,
                            row_order=row_order,
                            page=pending_page,
                            text=pending_text,
                            parent_section=parent_section,
                            header_source_page=pending_header_source,
                            as_section=False,
                        )
                    pending = None

                if not label:
                    continue

                cells = []
                for i, (raw, number, cell_unit) in enumerate(parsed["values"]):
                    if not raw:
                        continue
                    if cell_unit == "%":
                        original_unit = "%"
                        value_yuan = None
                    else:
                        original_unit = cell_unit or unit
                        mult = {
                            "元": 1.0, "千元": 1_000.0, "万元": 10_000.0,
                            "百万元": 1_000_000.0, "亿元": 100_000_000.0,
                        }.get(original_unit or "")
                        value_yuan = number * mult if number is not None and mult is not None else None
                    cells.append(TableCell(
                        column_ordinal=i,
                        source_column_index=i + 1,
                        raw=raw,
                        parsed_number=number,
                        unit_original=original_unit,
                        value_yuan=value_yuan,
                    ))

                if not cells:
                    continue
                norm = normalize_item_label(label)
                row_type = classify_row_type(norm, True)

                output_parent = parent_section
                output_level = 1 if parent_section else 0
                # A final TOTAL after an explicit “减:”/“加:” block is a peer of
                # the preceding subtotal, not a child of the modifier marker.
                if (
                    row_type == "TOTAL"
                    and normalize_text(parent_section or "") in {
                        normalize_text("减"),
                        normalize_text("加"),
                    }
                ):
                    output_parent = None
                    output_level = 0

                row_order += 1
                rows.append(TableRow(
                    row_order=row_order,
                    page=page_no,
                    block_id=f"spatial_p{page_no}",
                    source_method="spatial_roi+column_anchors",
                    raw_item=label,
                    normalized_item=norm,
                    canonical_item=None,
                    mapping_status="UNMAPPED",
                    row_type=row_type,
                    row_level=output_level,
                    parent_section=output_parent,
                    cells=cells,
                    header_source_page=header_source_page,
                ))
            else:
                if not label:
                    continue
                if pending:
                    prev_text = pending["text"]
                    prev_page = pending["page"]
                    prev_header_source = (
                        roi["start_page"]
                        if prev_page > roi["start_page"] else None
                    )

                    if _is_explicit_section_label(prev_text):
                        row_order += 1
                        prev_norm = _append_text_only_row(
                            rows,
                            row_order=row_order,
                            page=prev_page,
                            text=prev_text,
                            parent_section=parent_section,
                            header_source_page=prev_header_source,
                            as_section=True,
                        )
                        parent_section = prev_norm
                        pending = {
                            "text": label,
                            "x0": parsed["label_x0"],
                            "page": page_no,
                        }
                    elif parsed["label_x0"] > pending["x0"] + 7:
                        # Multi-line wrapped label without numeric values yet.
                        pending = {
                            "text": prev_text + label,
                            "x0": pending["x0"],
                            "page": prev_page,
                        }
                    else:
                        row_order += 1
                        _append_text_only_row(
                            rows,
                            row_order=row_order,
                            page=prev_page,
                            text=prev_text,
                            parent_section=parent_section,
                            header_source_page=prev_header_source,
                            as_section=False,
                        )
                        pending = {
                            "text": label,
                            "x0": parsed["label_x0"],
                            "page": page_no,
                        }
                else:
                    pending = {
                        "text": label,
                        "x0": parsed["label_x0"],
                        "page": page_no,
                    }

        if len(rows) > page_rows_before:
            source_pages.append(page_no)

        if progress_callback:
            total = roi["end_page"] - roi["start_page"] + 1
            progress_callback({
                "event": "page_start",
                "selected_index": page_no - roi["start_page"] + 1,
                "total_pages": total,
                "message": f"空间重建 PDF p.{page_no}",
            })

    if pending:
        pending_text = pending["text"]
        pending_page = pending["page"]
        row_order += 1
        _append_text_only_row(
            rows,
            row_order=row_order,
            page=pending_page,
            text=pending_text,
            parent_section=parent_section,
            header_source_page=(
                roi["start_page"] if pending_page > roi["start_page"] else None
            ),
            as_section=_is_explicit_section_label(pending_text),
        )

    doc.close()

    if not rows or not any(r.cells for r in rows):
        raise ValueError("空间ROI已定位并识别表头，但未重建出有效数值明细行。")

    warnings = []
    if unit is None:
        warnings.append("未在目标附注首页识别到明确单位；原始单位保持UNKNOWN，不做金额单位推断。")
    if roi["boundary_reason"] == "max_pages":
        warnings.append("未发现下一附注编号作为硬结束边界，当前使用max_pages边界，请人工核对末尾。")

    if progress_callback:
        progress_callback({"event": "done", "message": "空间整表重建完成"})

    return TableCaptureResult(
        pdf_name=Path(pdf_path).name,
        pdf_sha256=file_sha256(Path(pdf_path)),
        table_query=table_query,
        note_number=str(roi.get("resolved_note_number") or note_number) if (roi.get("resolved_note_number") or note_number) else None,
        located_title=roi["located_title"],
        start_page=roi["start_page"],
        end_page=roi["end_page"],
        pages=sorted(set(source_pages or [roi["start_page"]])),
        unit=unit,
        columns=columns,
        rows=rows,
        warnings=warnings,
        stats={
            "engine": "SPATIAL_ROI_V1",
            "boundary_reason": roi["boundary_reason"],
            "note_number_source": roi.get("note_number_source"),
            "resolved_note_number": roi.get("resolved_note_number"),
            "roi": {
                "start_page": roi["start_page"], "start_y": roi["start_y"],
                "end_page": roi["end_page"], "end_y": roi["end_y"],
            },
            "logical_columns": len(columns),
            "rows": len(rows),
            "numeric_rows": sum(bool(r.cells) for r in rows),
        },
    )
