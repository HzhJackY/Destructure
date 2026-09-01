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

from dataclasses import dataclass, field
import dataclasses
import hashlib
import itertools
import json
import re
from pathlib import Path
from typing import Any, Optional, Sequence

import fitz  # PyMuPDF

from certified_roi_membership import (
    CERTIFIED_ROI_ROW_MEMBERSHIP_SEMANTICS,
    belongs_to_certified_roi,
)
from financial_metric_pdf_resolver import (
    clean_cell,
    file_sha256,
    normalize_text,
    parse_number,
)
from period_identity import normalize_period_fields, normalize_period_token


@dataclasses.dataclass
class NumericToken:
    """v6.10: formal amount token reconstruction evidence.

    Captures the raw fragments, bbox positions, normalization steps, and
    final parsed value so the reconstruction is fully auditable.
    """
    raw_numeric_tokens: list[str] = dataclasses.field(default_factory=list)
    normalized_numeric_text: str = ""
    parsed_decimal_value: float | None = None
    numeric_token_bboxes: list[list[float]] = dataclasses.field(default_factory=list)
    numeric_source_mode: str = ""  # SINGLE_FRAGMENT, BBOX_CONTIGUOUS_JOIN, SAME_LINE_JOIN
    normalization_method: str = ""  # COMMA_STRIP, PARENTHESIS_NEGATIVE, DIRECT
    parsing_confidence: float = 0.0


def reconstruct_numeric_token(
    fragments: list[dict[str, Any]],
) -> NumericToken:
    """Reconstruct a single numeric value from spatially ordered fragments.

    Fragments must already be sorted left-to-right within their logical
    column.  This is a pure function that does not mutate the source data.
    """
    if not fragments:
        return NumericToken()

    raw_tokens = [str(f.get("text", "")).strip() for f in fragments]
    bboxes = [
        [float(f.get("x0", 0)), float(f.get("y0", 0)),
         float(f.get("x1", 0)), float(f.get("y1", 0))]
        for f in fragments
    ]

    # Join by reading order (already sorted by caller)
    joined = "".join(raw_tokens)
    joined = joined.replace("％", "%").replace("，", ",").replace("．", ".")
    joined = re.sub(r"\s+", "", joined)

    source_mode = "SINGLE_FRAGMENT" if len(fragments) == 1 else "BBOX_CONTIGUOUS_JOIN"
    norm_method = "DIRECT"
    confidence = 0.95

    # Normalize: strip commas, handle parentheses for negatives
    cleaned = joined.replace(",", "").replace("，", "")
    if cleaned.startswith("(") and ")" in cleaned:
        cleaned = "-" + cleaned.replace("(", "").replace(")", "")
        norm_method = "PARENTHESIS_NEGATIVE"
    elif joined != cleaned:
        norm_method = "COMMA_STRIP"

    # Parse
    parsed = None
    try:
        parsed = float(cleaned)
    except ValueError:
        confidence = 0.0

    return NumericToken(
        raw_numeric_tokens=raw_tokens,
        normalized_numeric_text=cleaned,
        parsed_decimal_value=parsed,
        numeric_token_bboxes=bboxes,
        numeric_source_mode=source_mode,
        normalization_method=norm_method,
        parsing_confidence=confidence,
    )

_NOTE_LINE_RE = re.compile(r"^\s*[（(]?\s*(\d{1,3}|[零〇一二三四五六七八九十百]{1,5})\s*[）)]?\s*(?:[\.．、]\s*)?(.+?)\s*$")
_YEAR_RE = re.compile(r"(20\d{2})")
_EXPLICIT_MEASURE_TOKENS = (
    "摊余成本",
    "公允价值",
    "账面价值",
    "账面余额",
    "账面值",
    "成本",
    "减值准备",
    "比例",
    "收益率",
    "金额",
)
_REPORT_FOOTER_RE = re.compile(
    r"^\d{1,4}(?:(?:[二〇零一二三四五六七八九]{4})年年报|"
    r"20\d{2}年(?:年报|年度报告))[|｜]?财务报告$"
)
_REPORT_PAGE_CHROME_MARKER_RE = re.compile(
    r"(?:20\d{2}年?(?:年报|年度[报報]告)|"
    r"[二〇零一二三四五六七八九]{4}年年报)"
)
_REPORT_NAVIGATION_CHROME_TOKENS = (
    "关于公司",
    "致股东函",
    "经营情况",
    "企业管治",
    "其他信息",
    "财务报告",
)
_RELATIVE_PERIOD_PATTERNS = [
    (
        re.compile(
            r"^(?:本年累计数|本年度累计数|本期累计数|本期数|本年数|"
            r"本期|本年|本年度|当期累计数|当期)$"
        ),
        "CURRENT",
    ),
    (
        re.compile(
            r"^(?:上年累计数|上年度累计数|上期累计数|上期数|上年数|"
            r"上期|上年|上年度|去年|去年累计数|去年数|去年同期|"
            r"上年同期|上年度同期)$"
        ),
        "PRIOR",
    ),
    (re.compile(r"^(?:期末|年末|本期期末|本年末|本年度末)$"), "CURRENT_END"),
    (re.compile(r"^(?:期初|年初|本期期初|本年初|本年度初)$"), "CURRENT_BEGIN"),
]
_UNIT_RE = re.compile(
    r"(?:单位\s*[:：]?\s*)?(?:人民币\s*)?(亿元|百万元|万元|千元|元)"
)
_UNIT_DECL_RE = re.compile(
    r"(?:金额单位\s*(?:为|：|:)|金额\s*(?:为|以)|除特别注明外.{0,30}?金额单位)\s*(?:人民币\s*)?(百万元|亿元|万元|千元|元)"
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
        raw_text = "".join(parts)
        leading_ws = 0
        for ch in raw_text:
            if ch == "\u3000":
                leading_ws += 1
            elif ch in (" ", "\t"):
                continue
            else:
                break
        if leading_ws == 0 and ws:
            first_w = str(ws[0].get("text", ""))
            for ch in first_w:
                if ch == "\u3000":
                    leading_ws += 1
                elif ch in (" ", "\t"):
                    continue
                else:
                    break
        text = raw_text.strip()
        lines.append({
            "words": ws,
            "text": text,
            "raw_text": raw_text,
            "leading_ws_indent": leading_ws,
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
    from table_boundary_resolver import parse_note_ordinal
    raw_no, title = m.group(1), m.group(2)
    ordinal = parse_note_ordinal(raw_no)
    expected_ordinal = parse_note_ordinal(expected_no)
    if expected_no is not None and ordinal != expected_ordinal:
        return None
    if not re.search(r"[A-Za-z\u4e00-\u9fff]", title):
        return None
    return str(ordinal), title


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


def _parse_period_token(text: str) -> Optional[dict[str, Any]]:
    return normalize_period_token(clean_cell(text))


def _period_words_generalized(line: dict[str, Any]) -> list[dict[str, Any]]:
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

    # Full Chinese dates are commonly split as ``2024`` / ``年12`` /
    # ``月31`` / ``日``.  Prefer maximal 5/4-word spans before shorter forms.
    for span_len in (5, 4, 3, 2, 1):
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
            if len(_YEAR_RE.findall(_line_compact(joined))) > 1:
                continue
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
                "word_indices": list(range(i, i + span_len)),
            }
            candidates.append(hit)

    # De-duplicate overlapping detections, keeping maximal semantic spans.
    # This prevents 2024 + 2024年度 (or 本年 + 本年累计数) from becoming
    # duplicate physical leaf columns.
    candidates.sort(key=lambda h: (-h["_span_len"], -(h["x1"]-h["x0"]), h["xc"]))
    selected: list[dict[str, Any]] = []
    for hit in candidates:
        duplicate=False
        for old in selected:
            hit_indices = set(hit.get("word_indices") or [])
            old_indices = set(old.get("word_indices") or [])
            same_year = hit.get("year") == old.get("year")
            # A complete date and its year/month prefixes have different
            # period_kind values.  They are still the same physical header
            # when the shorter candidate is wholly contained in the maximal
            # span selected first.
            contained_fragment = (
                same_year
                and bool(hit_indices)
                and hit_indices < old_indices
            )
            same_semantic=(
                same_year
                and hit.get("period_kind")==old.get("period_kind")
            )
            same_baseline=abs(hit["yc"]-old["yc"])<=7
            overlap=max(0.0,min(hit["x1"],old["x1"])-max(hit["x0"],old["x0"]))
            denom=max(1.0,min(hit["x1"]-hit["x0"],old["x1"]-old["x0"]))
            overlap_ratio=overlap/denom
            if same_baseline and (
                contained_fragment
                or (
                    same_semantic
                    and (overlap_ratio>=0.55 or abs(hit["xc"]-old["xc"])<=10)
                )
            ):
                duplicate=True
                break
        if duplicate:
            continue
        hit.pop("_span_len", None)
        selected.append(hit)
    return sorted(selected, key=lambda h: h["xc"])



def _bbox_overlap_ratio(a: dict[str, Any], b: dict[str, Any]) -> float:
    overlap=max(0.0, min(float(a["x1"]),float(b["x1"]))-max(float(a["x0"]),float(b["x0"])))
    denom=max(1.0, min(float(a["x1"])-float(a["x0"]), float(b["x1"])-float(b["x0"])))
    return overlap/denom


def _period_words(line: dict[str, Any]) -> list[dict[str, Any]]:
    """Compatibility wrapper: v5.7 generalized parser."""
    return _period_words_generalized(line)


def _classic_absolute_year_words(line: dict[str, Any]) -> list[dict[str, Any]]:
    """
    Conservative classic parser for explicit absolute-year headers.

    It intentionally does NOT parse relative periods. It generates candidates
    from 1-3 adjacent PDF words, then performs maximal-span dominance using
    source-word overlap + semantic year equality. Thus:
        2024
        2024 + 年度
    becomes one physical header anchor, not two.
    """
    words=line.get("words") or []
    candidates=[]
    for span_len in (3,2,1):
        for i in range(0,len(words)-span_len+1):
            span=words[i:i+span_len]
            if span_len>1:
                gaps=[span[j+1]["x0"]-span[j]["x1"] for j in range(len(span)-1)]
                if any(g>18 for g in gaps):
                    continue
            joined="".join(str(w["text"]) for w in span)
            years=re.findall(r"20\d{2}", joined)
            if len(years)!=1:
                continue
            year=years[0]
            # Avoid treating numeric data cells as year headers.
            compact=_line_compact(joined)
            if not (
                compact==year
                or compact.startswith(year+"年")
                or compact.startswith(year+"年度")
                or "重述" in compact
            ):
                continue
            candidates.append({
                "x0":min(w["x0"] for w in span),
                "x1":max(w["x1"] for w in span),
                "y0":min(w["y0"] for w in span),
                "y1":max(w["y1"] for w in span),
                "xc":(min(w["x0"] for w in span)+max(w["x1"] for w in span))/2,
                "yc":sum(w["yc"] for w in span)/len(span),
                "year":year,
                "period_label":year,
                "period_kind":"ABSOLUTE_YEAR",
                "token":joined,
                "_span_len":span_len,
                "_word_ids":set(range(i,i+span_len)),
                "_restated_hint":("重述" in compact),
            })

    # Maximal-span semantic dedup. Same physical text region + same year -> keep
    # the widest/longest candidate. Distinct 2024 columns under 集团/公司 remain.
    candidates.sort(
        key=lambda h:(-h["_span_len"], -(h["x1"]-h["x0"]), h["xc"])
    )
    selected=[]
    for hit in candidates:
        duplicate=False
        for old in selected:
            same_year=hit["year"]==old["year"]
            same_baseline=abs(hit["yc"]-old["yc"])<=7
            shared_words=bool(hit["_word_ids"] & old["_word_ids"])
            strong_overlap=_bbox_overlap_ratio(hit,old)>=0.55
            if same_year and same_baseline and (shared_words or strong_overlap):
                duplicate=True
                # preserve restated evidence on the retained maximal span
                old["_restated_hint"]=old.get("_restated_hint") or hit.get("_restated_hint")
                break
        if not duplicate:
            selected.append(hit)

    for hit in selected:
        hit.pop("_span_len",None)
        hit.pop("_word_ids",None)
    return sorted(selected,key=lambda h:h["xc"])


def _detect_header_classic(
    lines:list[dict[str,Any]],
    page_width:float,
)->Optional[dict[str,Any]]:
    candidates=[]
    for i,line in enumerate(lines[:100]):
        hits=_classic_absolute_year_words(line)
        if not hits:
            continue
        if 1<=len(hits)<=8:
            spread=(max(h["xc"] for h in hits)-min(h["xc"] for h in hits)) if len(hits)>1 else 0
            score=len(hits)*14+spread/max(page_width,1)*10
            candidates.append((score,i,line,hits))
    if not candidates:
        return None
    _,idx,line,hits=max(candidates,key=lambda x:x[0])
    hits=sorted(hits,key=lambda x:x["xc"])
    return {
        "parser":"ABSOLUTE_YEAR_CLASSIC",
        "line_index":idx,
        "line":line,
        "anchors":[h["xc"] for h in hits],
        "years":[h["year"] for h in hits],
        "period_labels":[h["period_label"] for h in hits],
        "period_kinds":[h["period_kind"] for h in hits],
        "restated_hints":[bool(h.get("_restated_hint")) for h in hits],
        "header_y0":line["y0"],
        "header_y1":line["y1"],
    }


def _detect_header_generalized_wrapped(
    lines:list[dict[str,Any]],
    page_width:float,
)->Optional[dict[str,Any]]:
    header=_detect_header_generalized(lines,page_width)
    if header:
        header=dict(header)
        header["parser"]="GENERALIZED_PERIOD_V57"
    return header


def _numeric_column_clusters(
    lines:list[dict[str,Any]],
    *,
    header_y1:float,
    page_width:float,
    max_lines:int=40,
    body_end_y:float|None=None,
)->dict[str,Any]:
    """
    Independent referee using only numeric x-centers in body rows.
    """
    observations=[]
    used_lines=0
    for li,line in enumerate(lines):
        if line["y0"]<=header_y1+8:
            continue
        if body_end_y is not None and line["y0"] > body_end_y:
            break
        hits=[]
        for w in line.get("words") or []:
            if w["xc"]<page_width*0.25:
                continue
            compact=_line_compact(w["text"])
            if not (
                _is_numeric_fragment(w["text"])
                or re.fullmatch(r"[-—–－]+", compact)
            ):
                continue
            # exclude bare 4-digit years in possible repeated headers
            if re.fullmatch(r"20\d{2}",compact):
                continue
            hits.append(float(w["xc"]))
        if len(hits)>=2:
            used_lines+=1
            observations.extend((x,li) for x in hits)
        if used_lines>=max_lines:
            break

    if not observations:
        return {"count":0,"centers":[],"supports":[],"lines":0}

    clusters=[]
    tolerance=max(16.0,min(32.0,page_width*0.028))
    for x,li in sorted(observations,key=lambda z:z[0]):
        best=None
        best_dist=None
        for c in clusters:
            dist=abs(x-c["center"])
            if dist<=tolerance and (best_dist is None or dist<best_dist):
                best=c;best_dist=dist
        if best is None:
            clusters.append({"xs":[x],"lines":{li},"center":x})
        else:
            best["xs"].append(x);best["lines"].add(li)
            best["center"]=sum(best["xs"])/len(best["xs"])

    min_support=max(2,int(max(1,used_lines)*0.20))
    kept=[c for c in clusters if len(c["lines"])>=min_support]
    return {
        "count":len(kept),
        "centers":[round(c["center"],3) for c in kept],
        "supports":[len(c["lines"]) for c in kept],
        "lines":used_lines,
        "body_end_y": (
            float(body_end_y) if body_end_y is not None else None
        ),
        "body_bounded": body_end_y is not None,
    }


def _validated_numeric_assignment_anchors(
    anchors: list[float],
    numeric_clusters: dict[str, Any] | None,
    *,
    page_width: float,
    require_body_bounded: bool = False,
) -> list[float] | None:
    """Return body-value lanes only when topology independently agrees.

    PDF table headers are often centered text while amounts are right-aligned
    inside the same columns.  The two x-centers can therefore differ by a
    meaningful amount.  Header anchors remain the source of column identity;
    these optional anchors are used only for assigning numeric words to that
    already-certified column order.

    The referee must observe exactly one supported numeric lane per header
    column.  Any cardinality or support ambiguity disables the adjustment and
    leaves the original conservative assignment path untouched.
    """
    header_anchors = [float(value) for value in anchors or []]
    if len(header_anchors) < 2 or not numeric_clusters:
        return None
    if require_body_bounded and not bool(
        numeric_clusters.get("body_bounded")
    ):
        return None
    centers = [float(value) for value in numeric_clusters.get("centers") or []]
    supports = [int(value) for value in numeric_clusters.get("supports") or []]
    if len(centers) != len(header_anchors):
        return None
    if len(supports) != len(centers) or any(value < 2 for value in supports):
        return None
    if any(value < page_width * 0.25 or value > page_width for value in centers):
        return None
    if any(right <= left for left, right in zip(centers, centers[1:])):
        return None
    return centers


def _primary_table_end_y(
    lines:list[dict[str,Any]], *, header_y1:float,
    amount_anchors:Sequence[float]=(), page_width:float|None=None,
)->float|None:
    """Find a safe end for the first numerical table inside one note section.

    A note may contain a principal balance table followed by a separate
    impairment roll-forward with a different column topology.  The latter is
    not a continuation of the first table and must not invalidate its header
    arbitration.  We only split after a witnessed total/subtotal and a
    subsequent prose introduction, so ordinary multi-line tables remain whole.
    """
    last_total_y:float|None=None
    last_data_y:float|None=None
    for line in lines:
        if line["y0"] <= header_y1 + 4:
            continue
        text=clean_cell(line.get("text") or "")
        compact=_line_compact(text)
        if not text:
            continue
        has_total=(compact.startswith("合计") or compact.startswith("小计"))
        numeric_words=[
            word for word in (line.get("words") or [])
            if _is_numeric_fragment(word.get("text", ""))
        ]
        has_number=bool(numeric_words)
        lane_tolerance=max(18.0,float(page_width or 0.0)*0.05)
        has_lane_number=(
            any(
                any(
                    abs(float(
                        word.get("xc",(
                            float(word.get("x0",0.0))
                            +float(word.get("x1",word.get("x0",0.0)))
                        )/2.0)
                    )-float(anchor))<=lane_tolerance
                    for anchor in amount_anchors
                )
                for word in numeric_words
            )
            if amount_anchors else has_number
        )
        # Test for prose before updating ``last_data_y``: footnote markers such
        # as “(1)” are numeric fragments but are not table values.
        if (
            last_total_y is not None
            and line["y0"] > last_total_y
            and len(text) >= 24
            and not has_lane_number
            and not compact.startswith(("其中", "注", "说明"))
        ):
            return last_data_y or last_total_y
        if has_total and has_number:
            last_total_y=float(line["y1"])
            last_data_y=last_total_y
            continue
        if last_total_y is not None and has_lane_number:
            last_data_y=float(line["y1"])
    return None


def _stable_physical_segment_id(
    note_identity: str,
    table_identity: str,
    page_number: int,
    y0: float,
    ordinal: int,
) -> str:
    material = "|".join((
        normalize_text(note_identity),
        normalize_text(table_identity),
        str(int(page_number)),
        f"{float(y0):.2f}",
        str(int(ordinal)),
    ))
    digest = hashlib.sha256(material.encode("utf-8")).hexdigest()[:18]
    return f"SEG_{digest}"


def _line_numeric_lane_centers(
    line: dict[str, Any],
    page_width: float,
) -> list[float]:
    centers = []
    for word in line.get("words") or []:
        if float(word.get("xc", 0.0)) < page_width * 0.25:
            continue
        text = _line_compact(word.get("text", ""))
        if re.fullmatch(r"20\d{2}", text):
            continue
        if (
            _is_numeric_fragment(word.get("text", ""))
            or re.fullmatch(
                r"[-—–－]+",
                _line_compact(word.get("text", "")),
            )
        ):
            centers.append(float(word["xc"]))
    return centers


def _first_body_line_y(
    lines: list[dict[str, Any]],
    *,
    start_y: float,
    centers: list[float],
    page_width: float,
) -> float | None:
    if len(centers) < 2:
        return None
    tolerance = max(18.0, page_width * 0.035)
    minimum_matches = max(2, (len(centers) + 1) // 2)
    for line in lines:
        if float(line["y0"]) <= float(start_y) + 2.0:
            continue
        hits = _line_numeric_lane_centers(line, page_width)
        matched = {
            index
            for hit in hits
            for index, center in enumerate(centers)
            if abs(hit - center) <= tolerance
        }
        if len(matched) >= minimum_matches:
            return float(line["y0"])
    return None


def _local_header_labels(
    lines: list[dict[str, Any]],
    *,
    start_y: float,
    body_y: float,
    centers: list[float],
    page_width: float,
) -> list[str]:
    labels: list[list[str]] = [[] for _ in centers]
    period_labels: list[list[str]] = [[] for _ in centers]
    tolerance = max(34.0, page_width * 0.055)
    page_height = max(
        (float(line.get("y1", 0.0)) for line in lines),
        default=0.0,
    )
    for line in lines:
        if not (float(start_y) < float(line["y0"]) < float(body_y)):
            continue
        if _report_page_chrome_role(line, page_height):
            continue
        header_hits = []
        for word in line.get("words") or []:
            text = clean_cell(word.get("text", ""))
            if not text or _is_unit_only_header(text):
                continue
            compact = _line_compact(text)
            if _is_numeric_fragment(text) and not re.search(r"[A-Za-z\u4e00-\u9fff]", compact):
                continue
            index = _nearest_anchor_index(float(word["xc"]), centers)
            distance = abs(float(word["xc"]) - centers[index])
            if distance > max(
                tolerance,
                _anchor_local_gap(centers, index, page_width) * 0.90,
            ):
                continue
            if _parse_period_token(text):
                if compact not in {
                    _line_compact(value) for value in period_labels[index]
                }:
                    period_labels[index].append(text)
                continue
            header_hits.append({**word, "token": text})
        if not header_hits:
            continue
        if len(header_hits) < len(centers):
            assignments = _assign_parent_header_hits(
                centers,
                header_hits,
                page_width,
            )
            for index, hit in assignments.items():
                text = str(hit["token"])
                if _line_compact(text) not in {
                    _line_compact(value) for value in labels[index]
                }:
                    labels[index].append(text)
            continue
        for hit in header_hits:
            index = _nearest_anchor_index(float(hit["xc"]), centers)
            if abs(float(hit["xc"]) - centers[index]) > tolerance:
                continue
            text = str(hit["token"])
            if _line_compact(text) not in {
                _line_compact(value) for value in labels[index]
            }:
                labels[index].append(text)
    return [
        " | ".join(values or period_labels[index])
        for index, values in enumerate(labels)
    ]


def _local_column_metadata(labels: list[str]) -> list[dict[str, Any]]:
    metadata = []
    for label in labels:
        year_match = _YEAR_RE.search(str(label or ""))
        year = year_match.group(1) if year_match else None
        metadata.append({
            "tokens": [label] if label else [],
            "year": year,
            "scope": None,
            "restated": False,
            "period_label": year,
            "period_kind": "ABSOLUTE_YEAR" if year else None,
            "measure": label or None,
        })
    return metadata


def _segment_period_labels(
    lines: list[dict[str, Any]],
    *,
    start_y: float,
    end_y: float,
) -> list[str]:
    periods = []
    for line in lines:
        if not (float(start_y) <= float(line["y0"]) <= float(end_y)):
            continue
        compact = _line_compact(line.get("text") or "")
        if _REPORT_FOOTER_RE.fullmatch(compact):
            continue
        for match in re.finditer(r"(?<!\d)(20\d{2})年", compact):
            year = match.group(1)
            if year not in periods:
                periods.append(year)
    return periods


def _period_axis_line_labels(line: dict[str, Any]) -> list[str]:
    compact = _line_compact(line.get("text") or "")
    if (
        not compact
        or len(compact) > 56
        or re.search(r"[，；。]", compact)
        or _REPORT_FOOTER_RE.fullmatch(compact)
    ):
        return []
    periods = []
    for hit in _period_words_generalized(line):
        if str(hit.get("period_kind") or "") != "ABSOLUTE_YEAR":
            continue
        period = str(hit.get("year") or "").strip()
        if period and period not in periods:
            periods.append(period)
    return periods


def _matched_lane_indexes(
    line: dict[str, Any],
    centers: list[float],
    page_width: float,
) -> set[int]:
    tolerance = max(18.0, page_width * 0.035)
    return {
        index
        for hit in _line_numeric_lane_centers(line, page_width)
        for index, center in enumerate(centers)
        if abs(float(hit) - float(center)) <= tolerance
    }


def _preceding_local_lane_header_y0(
    lines: list[dict[str, Any]],
    *,
    period_y0: float,
    lower_bound: float,
    centers: list[float],
    page_width: float,
) -> float:
    tolerance = max(34.0, page_width * 0.055)
    search_y0 = max(float(lower_bound), float(period_y0) - 90.0)
    candidates: list[tuple[float, float, set[int], bool]] = []
    for line in lines:
        line_y0 = float(line.get("y0", 0.0))
        if not (search_y0 <= line_y0 < float(period_y0)):
            continue
        compact_line = _line_compact(line.get("text") or "")
        sparse_header_eligible = bool(
            compact_line
            and len(compact_line) <= 56
            and not re.search(r"[，；。：]", compact_line)
        )
        matched = set()
        for word in line.get("words") or []:
            text = clean_cell(word.get("text", ""))
            compact = _line_compact(text)
            if (
                not compact
                or _is_numeric_fragment(text)
                or _parse_period_token(text)
                or _is_unit_only_header(text)
            ):
                continue
            index = _nearest_anchor_index(float(word["xc"]), centers)
            if abs(float(word["xc"]) - centers[index]) <= tolerance:
                matched.add(index)
        if matched:
            candidates.append((
                line_y0,
                float(line.get("y1", line_y0)),
                matched,
                sparse_header_eligible,
            ))

    minimum_lane_count = min(2, len(centers))
    dense_candidates = [
        candidate
        for candidate in candidates
        if len(candidate[2]) >= minimum_lane_count
    ]
    if not dense_candidates:
        return float(period_y0)

    earliest = min(candidate[0] for candidate in dense_candidates)
    adjacency_tolerance = max(18.0, page_width * 0.03)
    for line_y0, line_y1, _matched, sparse_header_eligible in reversed(candidates):
        if line_y0 >= earliest:
            continue
        if earliest - line_y1 > adjacency_tolerance:
            break
        if not sparse_header_eligible:
            break
        earliest = line_y0
    return earliest


def _bounded_period_axis_evidence(
    lines: list[dict[str, Any]],
    *,
    start_y: float,
    end_y: float,
    centers: list[float],
    page_width: float,
) -> dict[str, Any]:
    if len(centers) < 2:
        return {
            "period_labels": [],
            "header_y0": float(start_y),
            "data_y_min": None,
            "complete": False,
            "issue_codes": ["AMOUNT_LANE_SIGNATURE_REQUIRED"],
        }

    bounded = [
        line
        for line in lines
        if float(start_y) <= float(line.get("y0", 0.0)) <= float(end_y)
    ]
    page_height = max(
        (float(line.get("y1", 0.0)) for line in bounded),
        default=float(end_y),
    )
    axis_lines = []
    for index, line in enumerate(bounded):
        if _report_page_chrome_role(line, page_height):
            continue
        periods = _period_axis_line_labels(line)
        if periods:
            axis_lines.append((index, line, periods))

    supported = []
    unsupported = []
    for index, line, periods in axis_lines:
        body_y = None
        for candidate in bounded[index:]:
            if float(candidate.get("y0", 0.0)) - float(
                line.get("y1", 0.0)
            ) > 90.0:
                break
            if len(_matched_lane_indexes(
                candidate,
                centers,
                page_width,
            )) == len(centers):
                body_y = float(candidate["y0"])
                break
        record = {
            "line_y0": float(line["y0"]),
            "line_y1": float(line["y1"]),
            "period_labels": periods,
            "body_y": body_y,
        }
        if body_y is None:
            unsupported.append(record)
        else:
            supported.append(record)

    if not supported:
        return {
            "period_labels": [],
            "header_y0": float(start_y),
            "data_y_min": None,
            "complete": False,
            "issue_codes": ["PERIOD_AXIS_EVIDENCE_REQUIRED"],
        }

    supported.sort(key=lambda item: item["line_y0"])
    first_axis_y = float(supported[0]["line_y0"])
    unresolved = [
        item
        for item in unsupported
        if float(item["line_y0"]) >= first_axis_y
    ]
    periods = []
    for item in supported:
        for period in item["period_labels"]:
            if period not in periods:
                periods.append(period)
    header_y0 = _preceding_local_lane_header_y0(
        bounded,
        period_y0=first_axis_y,
        lower_bound=float(start_y),
        centers=centers,
        page_width=page_width,
    )
    issue_codes = []
    if unresolved:
        issue_codes.append("PERIOD_AXIS_BLOCK_INCOMPLETE")
    return {
        "period_labels": periods,
        "header_y0": header_y0,
        "data_y_min": float(supported[0]["body_y"]),
        "complete": not issue_codes,
        "issue_codes": issue_codes,
        "supported_blocks": supported,
        "unsupported_blocks": unresolved,
    }


def _lane_ratios_aligned(
    current: list[float],
    parent: list[float],
    *,
    tolerance: float = 0.04,
) -> bool:
    return len(current) == len(parent) and all(
        abs(value - parent[index]) <= tolerance
        for index, value in enumerate(current)
    )


def _header_labels_compatible(
    current: list[str],
    parent: list[str],
) -> bool | None:
    current_values = [_line_compact(value) for value in current]
    parent_values = [_line_compact(value) for value in parent]
    evidenced = [value for value in current_values if value]
    if len(evidenced) < 2:
        return None
    if len(current_values) != len(parent_values):
        return False
    return all(
        not current_value
        or not parent_value
        or current_value in parent_value
        or parent_value in current_value
        for current_value, parent_value in zip(current_values, parent_values)
    )


def _plan_physical_table_segments(
    lines_by_page: dict[int, list[dict[str, Any]]],
    page_widths: dict[int, float],
    *,
    start_page: int,
    end_page: int,
    root_header: dict[str, Any],
    root_metadata: list[dict[str, Any]],
    root_header_bottom: float,
    note_identity: str,
    table_identity: str,
    unit: str | None,
) -> tuple[list[dict[str, Any]], dict[int, list[dict[str, Any]]], list[dict[str, Any]]]:
    from table_segment_classifier import classify_table_segment

    plans: list[dict[str, Any]] = []
    by_page: dict[int, list[dict[str, Any]]] = {}
    additional_columns: list[dict[str, Any]] = []
    next_column_ordinal = len(root_metadata)

    def add_plan(
        *,
        page_number: int,
        segment_y0: float,
        segment_y1: float,
        data_y_min: float,
        anchors: list[float],
        metadata: list[dict[str, Any]],
        segment_period_labels: list[str],
        source_column_ordinals: list[int],
        segment_table_identity: str,
        text_lines: list[str],
        parent_plan: dict[str, Any] | None,
        independent_header: bool,
        narrative_separator: bool,
        local_total_before: bool,
        page_adjacent: bool | None,
        header_y0: float | None,
        header_y1: float | None,
        period_signature_complete: bool = True,
        structure_issue_codes: Sequence[str] = (),
    ) -> dict[str, Any]:
        page_width = float(page_widths[page_number])
        ratios = [float(anchor) / page_width for anchor in anchors]
        headers = [" | ".join(item.get("tokens") or []) for item in metadata]
        parent_segment = parent_plan["segment"] if parent_plan else None
        segment_id = _stable_physical_segment_id(
            note_identity,
            segment_table_identity,
            page_number,
            segment_y0,
            len(plans),
        )
        segment = classify_table_segment(
            segment_id,
            page_number,
            (0.0, segment_y0, page_width, segment_y1),
            note_identity,
            segment_table_identity,
            text_lines,
            headers,
            parent_segment,
            anchor_ratios=ratios,
            source_column_ordinals=source_column_ordinals,
            period_labels=segment_period_labels,
            measure_labels=[
                str(item.get("measure") or "").strip()
                for item in metadata
                if str(item.get("measure") or "").strip()
            ],
            unit=unit,
            independent_header=independent_header,
            narrative_separator=narrative_separator,
            local_total_before=local_total_before,
            page_adjacent=page_adjacent,
            header_y0=header_y0,
            header_y1=header_y1,
            data_y_min=data_y_min,
            data_y_max=segment_y1,
        )
        plan = {
            "segment": segment,
            "segment_id": segment.segment_id,
            "anchors": list(anchors),
            "anchor_ratios": ratios,
            "metadata": list(metadata),
            "source_column_ordinals": list(source_column_ordinals),
            "column_offset": min(source_column_ordinals, default=0),
            "column_count": len(source_column_ordinals),
            "segment_y0": float(segment_y0),
            "segment_y1": float(segment_y1),
            "data_y_min": float(data_y_min),
            "header_source_page": (
                parent_plan.get("header_source_page")
                or parent_segment.pdf_page_number
                if segment.classification.value == "CONTINUATION_SEGMENT"
                else None
            ),
        }
        plan["signature_coverage"] = {
            "page_bbox": bool(
                page_number >= 1
                and float(segment_y1) > float(segment_y0)
                and page_width > 0.0
            ),
            "period": bool(segment.period_labels) and bool(
                period_signature_complete
            ),
            "header": bool(
                segment.header_topology_fingerprint
                and len(headers) == len(ratios)
                and all(_line_compact(value) for value in headers)
            ),
            "amount_lanes": bool(
                ratios
                and len(ratios) == len(source_column_ordinals)
                and len(set(source_column_ordinals)) == len(source_column_ordinals)
                and all(0.0 < value < 1.0 for value in ratios)
                and all(
                    right > left
                    for left, right in zip(ratios, ratios[1:])
                )
            ),
            "source": "BOUNDED_NATIVE_TEXT",
        }
        plan["structure_issue_codes"] = list(dict.fromkeys(
            str(code) for code in structure_issue_codes if str(code)
        ))
        plans.append(plan)
        by_page.setdefault(page_number, []).append(plan)
        return plan

    start_lines = lines_by_page.get(start_page, [])
    start_width = float(page_widths[start_page])
    start_page_end = max((float(line["y1"]) for line in start_lines), default=root_header_bottom)
    primary_end = _primary_table_end_y(
        start_lines,
        header_y1=float(root_header["header_y1"]),
        amount_anchors=[float(value) for value in root_header.get("anchors") or []],
        page_width=start_width,
    )
    primary_segment_y1 = float(primary_end or start_page_end)
    root_ordinals = list(range(len(root_metadata)))
    primary_plan = add_plan(
        page_number=start_page,
        segment_y0=float(root_header.get("header_y0", 0.0)),
        segment_y1=primary_segment_y1,
        data_y_min=float(root_header_bottom) + 2.0,
        anchors=[float(value) for value in root_header.get("anchors") or []],
        metadata=root_metadata,
        segment_period_labels=[
            str(item.get("year") or item.get("period_label") or "")
            for item in root_metadata
            if item.get("period_label") or item.get("year")
        ],
        source_column_ordinals=root_ordinals,
        segment_table_identity=table_identity,
        text_lines=[table_identity],
        parent_plan=None,
        independent_header=False,
        narrative_separator=False,
        local_total_before=False,
        page_adjacent=None,
        header_y0=float(root_header.get("header_y0", 0.0)),
        header_y1=float(root_header.get("header_y1", root_header_bottom)),
    )
    active_plan = primary_plan

    if primary_end is not None:
        numeric = _numeric_column_clusters(
            start_lines,
            header_y1=float(primary_end),
            page_width=start_width,
        )
        centers = [float(value) for value in numeric.get("centers") or []]
        period_axis = _bounded_period_axis_evidence(
            start_lines,
            start_y=float(primary_end) + 0.01,
            end_y=start_page_end,
            centers=centers,
            page_width=start_width,
        )
        body_y = period_axis.get("data_y_min") or _first_body_line_y(
            start_lines,
            start_y=float(primary_end),
            centers=centers,
            page_width=start_width,
        )
        if len(centers) >= 2 and body_y is not None:
            local_header_y0 = float(
                period_axis.get("header_y0")
                if period_axis.get("period_labels")
                else float(primary_end) + 0.01
            )
            labels = _local_header_labels(
                start_lines,
                start_y=local_header_y0 - 0.01,
                body_y=body_y,
                centers=centers,
                page_width=start_width,
            )
            metadata = _local_column_metadata(labels)
            ordinals = list(range(
                next_column_ordinal,
                next_column_ordinal + len(metadata),
            ))
            for index, item in enumerate(metadata):
                additional_columns.append({
                    **item,
                    "ordinal": ordinals[index],
                    "source_column_index": ordinals[index] + 1,
                })
            next_column_ordinal += len(metadata)
            narrative = [
                clean_cell(line.get("text") or "")
                for line in start_lines
                if float(primary_end) < float(line["y0"]) < body_y
            ]
            identity_material = "|".join(labels) or f"LANES_{len(centers)}"
            supplementary_identity = (
                f"{table_identity}::SUPPLEMENTARY::"
                f"{hashlib.sha256(identity_material.encode('utf-8')).hexdigest()[:12]}"
            )
            segment_periods = list(
                period_axis.get("period_labels") or _segment_period_labels(
                    start_lines,
                    start_y=local_header_y0,
                    end_y=start_page_end,
                )
            )
            active_plan = add_plan(
                page_number=start_page,
                segment_y0=local_header_y0,
                segment_y1=start_page_end,
                data_y_min=body_y,
                anchors=centers,
                metadata=metadata,
                segment_period_labels=segment_periods,
                source_column_ordinals=ordinals,
                segment_table_identity=supplementary_identity,
                text_lines=narrative,
                parent_plan=primary_plan,
                independent_header=True,
                narrative_separator=bool(narrative),
                local_total_before=True,
                page_adjacent=False,
                header_y0=local_header_y0,
                header_y1=body_y - 0.01,
                period_signature_complete=bool(
                    period_axis.get("period_labels")
                    and period_axis.get("complete")
                ),
                structure_issue_codes=list(
                    period_axis.get("issue_codes") or []
                ),
            )

    for page_number in range(start_page + 1, end_page + 1):
        lines = lines_by_page.get(page_number, [])
        if not lines:
            continue
        page_width = float(page_widths[page_number])
        page_end = max(float(line["y1"]) for line in lines)
        numeric = _numeric_column_clusters(
            lines,
            header_y1=-10.0,
            page_width=page_width,
        )
        centers = [float(value) for value in numeric.get("centers") or []]
        if len(centers) < 2:
            continue
        period_axis = _bounded_period_axis_evidence(
            lines,
            start_y=0.0,
            end_y=page_end,
            centers=centers,
            page_width=page_width,
        )
        body_y = period_axis.get("data_y_min") or _first_body_line_y(
            lines,
            start_y=-10.0,
            centers=centers,
            page_width=page_width,
        )
        if body_y is None:
            continue
        local_header_y0 = float(
            period_axis.get("header_y0")
            if period_axis.get("period_labels")
            else 0.0
        )
        page_sections = [{
            "centers":centers,
            "labels":[],
            "body_y":body_y,
            "header_y0":local_header_y0,
            "header_y1":body_y - 0.01,
            "periods":list(period_axis.get("period_labels") or []),
            "period_signature_complete":bool(
                period_axis.get("period_labels")
                and period_axis.get("complete")
            ),
            "structure_issue_codes":list(
                period_axis.get("issue_codes") or []
            ),
            "segment_y0":local_header_y0,
            "segment_y1":page_end,
        }]
        for section_index,section in enumerate(page_sections):
            section_centers=[float(value) for value in section["centers"]]
            section_body_y=float(section["body_y"])
            section_y0=float(section["segment_y0"])
            section_y1=float(section["segment_y1"])
            ratios = [center / page_width for center in section_centers]
            parent_ratios = list(active_plan["anchor_ratios"])
            detected_header_labels = list(section.get("labels") or []) or (
                _local_header_labels(
                    lines,
                    start_y=section_y0 - 0.01,
                    body_y=section_body_y,
                    centers=section_centers,
                    page_width=page_width,
                )
            )
            parent_header_labels = [
                " | ".join(item.get("tokens") or [])
                for item in active_plan["metadata"]
            ]
            header_labels_match = _header_labels_compatible(
                detected_header_labels,
                parent_header_labels,
            )
            body_periods = list(section.get("periods") or []) or (
                _segment_period_labels(
                    lines,
                    start_y=section_body_y,
                    end_y=section_y1,
                )
            )
            parent_periods = list(active_plan["segment"].period_labels)
            header_periods = _segment_period_labels(
                lines,
                start_y=section_y0,
                end_y=section_body_y - 0.01,
            )
            detected_periods = (
                body_periods
                if body_periods
                else header_periods
                if header_periods == parent_periods
                else []
            )
            period_reset = bool(
                detected_periods
                and parent_periods
                and detected_periods != parent_periods
            )
            if (
                _lane_ratios_aligned(ratios, parent_ratios)
                and header_labels_match is not False
                and not period_reset
            ):
                metadata = list(active_plan["metadata"])
                ordinals = list(active_plan["source_column_ordinals"])
                segment_identity = active_plan["segment"].table_identity
                independent_header = False
                header_labels = parent_header_labels
                segment_periods = detected_periods
            else:
                header_labels = detected_header_labels
                metadata = _local_column_metadata(header_labels)
                ordinals = list(range(
                    next_column_ordinal,
                    next_column_ordinal + len(metadata),
                ))
                for index, item in enumerate(metadata):
                    additional_columns.append({
                        **item,
                        "ordinal": ordinals[index],
                        "source_column_index": ordinals[index] + 1,
                    })
                next_column_ordinal += len(metadata)
                identity_material = (
                    "|".join(header_labels)
                    or f"LANES_{len(section_centers)}"
                )
                segment_identity = (
                    f"{table_identity}::SUPPLEMENTARY::"
                    f"{hashlib.sha256((identity_material + '|' + '|'.join(detected_periods)).encode('utf-8')).hexdigest()[:12]}"
                )
                independent_header = True
                segment_periods = detected_periods
            header_text = [
                clean_cell(line.get("text") or "")
                for line in lines
                if section_y0 <= float(line["y0"]) < section_body_y
            ]
            active_plan = add_plan(
                page_number=page_number,
                segment_y0=section_y0,
                segment_y1=section_y1,
                data_y_min=section_body_y,
                anchors=section_centers,
                metadata=metadata,
                segment_period_labels=segment_periods,
                source_column_ordinals=ordinals,
                segment_table_identity=segment_identity,
                text_lines=header_text or header_labels,
                parent_plan=active_plan,
                independent_header=independent_header,
                narrative_separator=independent_header and bool(header_text),
                local_total_before=(
                    independent_header and section_index == 0
                ),
                page_adjacent=(section_index == 0),
                header_y0=float(section["header_y0"]),
                header_y1=float(section["header_y1"]),
                period_signature_complete=bool(
                    section.get("period_signature_complete")
                ),
                structure_issue_codes=list(
                    section.get("structure_issue_codes") or []
                ),
            )

    return plans, by_page, additional_columns


_CANDIDATE_STRUCTURE_PLANNER_VERSION = "NATIVE_LINES_STRUCTURE_V2"


def _candidate_structure_id(prefix: str, *parts: Any) -> str:
    material = json.dumps(
        parts,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )
    return f"{prefix}_{hashlib.sha256(material.encode('utf-8')).hexdigest()[:24]}"


def _candidate_title_bbox(value: Any) -> dict[str, float]:
    if isinstance(value, dict):
        source = value
        return {
            "x0": float(source.get("x0", source.get("left", 0.0)) or 0.0),
            "y0": float(source.get("y0", source.get("top", 0.0)) or 0.0),
            "x1": float(source.get("x1", source.get("right", 0.0)) or 0.0),
            "y1": float(source.get("y1", source.get("bottom", 0.0)) or 0.0),
        }
    if isinstance(value, (list, tuple)) and len(value) == 4:
        return {
            "x0": float(value[0]),
            "y0": float(value[1]),
            "x1": float(value[2]),
            "y1": float(value[3]),
        }
    return {"x0": 0.0, "y0": 0.0, "x1": 0.0, "y1": 0.0}


def _certified_segment_page_bboxes(
    certified_segments: Sequence[dict[str, Any]] | None,
) -> dict[int, dict[str, float]]:
    """Return the authenticated physical-segment ROI by PDF page.

    A target may contain several physical segments (for example a real page
    continuation).  The capture ROI is the union of only those certified
    segment boxes, never the whole page.  Missing boxes are left to the
    existing strict title identity gate; malformed boxes fail closed.
    """
    page_bboxes: dict[int, dict[str, float]] = {}
    for segment in list(certified_segments or []):
        if not isinstance(segment, dict) or "bbox" not in segment:
            continue
        certification_status = str(
            segment.get("certification_status")
            or segment.get("status")
            or ""
        ).strip().upper()
        if certification_status != "CERTIFIED":
            continue
        raw_bbox = segment.get("bbox")
        entries = (
            raw_bbox.get("pages")
            if isinstance(raw_bbox, dict)
            and isinstance(raw_bbox.get("pages"), list)
            else [raw_bbox]
        )
        for entry in entries:
            if not isinstance(entry, dict):
                entry = {"bbox": entry}
            source = entry.get("bbox") if "bbox" in entry else entry
            box = _candidate_title_bbox(source)
            page_value = (
                entry.get("page")
                or (source.get("page") if isinstance(source, dict) else None)
                or segment.get("pdf_page_number")
                or segment.get("start_page")
            )
            try:
                page = int(page_value)
            except (TypeError, ValueError) as exc:
                raise ValueError("CERTIFIED_SEGMENT_BBOX_PAGE_REQUIRED") from exc
            if (
                page < 1
                or box["x1"] <= box["x0"]
                or box["y1"] <= box["y0"]
            ):
                raise ValueError("CERTIFIED_SEGMENT_BBOX_INVALID")
            current = page_bboxes.get(page)
            if current is None:
                page_bboxes[page] = box
            else:
                page_bboxes[page] = {
                    "x0": min(current["x0"], box["x0"]),
                    "y0": min(current["y0"], box["y0"]),
                    "x1": max(current["x1"], box["x1"]),
                    "y1": max(current["y1"], box["y1"]),
                }
    return page_bboxes


def _certified_column_context(
    certified_segments: Sequence[dict[str, Any]] | None,
    *,
    page_number: int,
    lines: list[dict[str, Any]],
    page_width: float,
) -> dict[str, Any] | None:
    certified_values = list(certified_segments or [])
    if len(certified_values) != 1:
        return None
    matching = []
    for segment in certified_values:
        if not isinstance(segment, dict):
            continue
        status = str(
            segment.get("certification_status")
            or segment.get("status")
            or ""
        ).strip().upper()
        try:
            segment_page = int(
                segment.get("pdf_page_number")
                or segment.get("start_page")
                or (segment.get("bbox") or {}).get("page")
            )
        except (TypeError, ValueError):
            continue
        if status == "CERTIFIED" and segment_page == int(page_number):
            matching.append(segment)
    if not matching:
        return None
    if len(matching) != 1:
        raise ValueError("CERTIFIED_COLUMN_CONTEXT_AMBIGUOUS")

    segment = matching[0]
    lane_signature = dict(segment.get("amount_lane_signature") or {})
    header_signature = dict(segment.get("header_signature") or {})
    period_signature = dict(segment.get("period_signature") or {})
    geometry_versions = {
        int(value)
        for value in (
            lane_signature.get("contract_version"),
            header_signature.get("contract_version"),
        )
        if value is not None
    }
    if len(geometry_versions) > 1:
        raise ValueError("CERTIFIED_COLUMN_CONTEXT_CONTRACT_VERSION_MISMATCH")
    geometry_version = next(iter(geometry_versions), 1)
    period_version = int(
        period_signature.get("contract_version") or geometry_version
    )
    # V4 upgrades only the period signature.  Physical leaf/header geometry
    # intentionally remains on its independent V3 contract.
    if period_version not in {geometry_version, 4} or (
        period_version == 4 and geometry_version < 3
    ):
        raise ValueError("CERTIFIED_COLUMN_CONTEXT_CONTRACT_VERSION_MISMATCH")
    contract_version = max(geometry_version, period_version)
    lane_count = int(lane_signature.get("lane_count") or 0)
    anchor_ratios = [
        float(value) for value in lane_signature.get("anchor_ratios") or []
    ]
    source_ordinals = [
        int(value)
        for value in lane_signature.get("source_column_ordinals") or []
    ]
    measure_labels = [
        str(value).strip()
        for value in header_signature.get("labels") or []
    ]
    if not measure_labels:
        return None
    period_labels = [
        str(value).strip()
        for value in (
            period_signature.get("period_labels")
            or period_signature.get("periods")
            or []
        )
        if str(value).strip()
    ]
    period_kinds = [
        str(value).strip()
        for value in period_signature.get("period_kinds") or []
    ]
    year_labels = list(period_signature.get("year_labels") or [])
    measure_kinds = [
        str(value).strip()
        for value in header_signature.get("measure_kinds") or []
    ]
    lane_group_ids = list(period_signature.get("lane_group_ids") or [])
    period_groups = list(period_signature.get("column_groups") or [])
    leaf_bboxes = list(header_signature.get("leaf_bboxes") or [])
    header_bbox = dict(header_signature.get("header_bbox") or {})
    leaf_count = int(header_signature.get("leaf_count") or lane_count or 0)
    if (
        lane_count < 1
        or len(anchor_ratios) != lane_count
        or leaf_count != lane_count
        or (measure_labels and len(measure_labels) != lane_count)
        or len(source_ordinals) != lane_count
        or len(set(source_ordinals)) != len(source_ordinals)
        or any(value <= 0.0 or value >= 1.0 for value in anchor_ratios)
        or any(
            right <= left
            for left, right in zip(anchor_ratios, anchor_ratios[1:])
        )
    ):
        raise ValueError("CERTIFIED_COLUMN_CONTEXT_INVALID")
    if contract_version >= 2:
        if (
            len(period_labels) != lane_count
            or len(period_kinds) != lane_count
            or len(year_labels) != lane_count
            or len(measure_kinds) != lane_count
            or len(leaf_bboxes) != lane_count
            or not all(
                isinstance(value, dict)
                and all(key in value for key in ("x0", "y0", "x1", "y1"))
                and float(value["x1"]) > float(value["x0"])
                and float(value["y1"]) > float(value["y0"])
                for value in leaf_bboxes
            )
            or not all(key in header_bbox for key in ("x0", "y0", "x1", "y1"))
            or float(header_bbox["x1"]) <= float(header_bbox["x0"])
            or float(header_bbox["y1"]) <= float(header_bbox["y0"])
        ):
            raise ValueError("CERTIFIED_COLUMN_CONTEXT_V2_PHYSICAL_EVIDENCE_REQUIRED")
    if contract_version >= 3:
        group_ids = {
            str(group.get("column_group_id") or "")
            for group in period_groups
            if isinstance(group, dict)
        }
        valid_groups = bool(period_groups) and all(
            isinstance(group, dict)
            and str(group.get("period") or "").strip()
            and str(group.get("column_group_id") or "").strip()
            and isinstance(group.get("period_anchor_bbox"), dict)
            and isinstance(group.get("period_group_bbox"), dict)
            and isinstance(group.get("period_header_row_band"), dict)
            and isinstance(group.get("child_header_row_band"), dict)
            and bool(group.get("consumed_spans"))
            and isinstance(group.get("evidence"), dict)
            for group in period_groups
        )
        valid_lane_groups = (
            len(lane_group_ids) == lane_count
            and all(
                (
                    str(group_id) in group_ids
                    if measure_kinds[index] != "CHANGE_RATE"
                    else str(group_id) == "PERIOD_CHANGE_GROUP"
                )
                for index, group_id in enumerate(lane_group_ids)
            )
        )
        if not valid_groups or not valid_lane_groups:
            raise ValueError("CERTIFIED_COLUMN_CONTEXT_V3_PERIOD_GROUP_REQUIRED")

    evidence = dict(segment.get("evidence") or {})
    raw_bbox = segment.get("bbox") or {}
    bbox = _candidate_title_bbox(raw_bbox)
    header_y0 = float(evidence.get("header_y0", bbox["y0"]) or bbox["y0"])
    data_y_min = float(
        evidence.get("data_y_min")
        or evidence.get("header_y1")
        or bbox["y0"]
    )
    header_y1 = float(evidence.get("header_y1", data_y_min) or data_y_min)
    numeric_clusters = _numeric_column_clusters(
        lines,
        header_y1=max(header_y1, data_y_min) - 0.01,
        page_width=float(page_width),
        body_end_y=float(bbox["y1"]),
    )
    certified_anchors = [value * float(page_width) for value in anchor_ratios]
    numeric_assignment_anchors = _validated_numeric_assignment_anchors(
        certified_anchors,
        numeric_clusters,
        page_width=float(page_width),
        require_body_bounded=True,
    )
    if numeric_assignment_anchors is None:
        raise ValueError("CERTIFIED_COLUMN_CONTEXT_BODY_LANES_MISMATCH")

    classification = str(segment.get("classification") or "").strip().upper()
    if classification not in {
        "PRIMARY_TABLE",
        "CONTINUATION_SEGMENT",
        "SUPPLEMENTARY_TABLE",
    }:
        raise ValueError("CERTIFIED_COLUMN_CONTEXT_CLASSIFICATION_INVALID")
    header_fingerprint = str(header_signature.get("fingerprint") or "").strip()
    return {
        "segment": segment,
        "classification": classification,
        "lane_count": lane_count,
        "anchors": certified_anchors,
        "anchor_ratios": anchor_ratios,
        "numeric_assignment_anchors": numeric_assignment_anchors,
        "numeric_clusters": numeric_clusters,
        "source_column_ordinals": source_ordinals,
        "measure_labels": measure_labels,
        "measure_kinds": measure_kinds,
        "period_labels": period_labels,
        "period_kinds": period_kinds,
        "year_labels": year_labels,
        "lane_group_ids": lane_group_ids,
        "period_groups": period_groups,
        "header_fingerprint": header_fingerprint,
        "leaf_bboxes": leaf_bboxes,
        "header_bbox": header_bbox,
        "column_topology_contract_version": contract_version,
        "bbox": bbox,
        "header_y0": header_y0,
        "header_y1": header_y1,
        "data_y_min": data_y_min,
    }


def _direct_portfolio_column_context(
    certified_segments: Sequence[dict[str, Any]] | None,
    *,
    page_number: int,
    lines: list[dict[str, Any]],
    page_width: float,
) -> dict[str, Any] | None:
    """Recover a legacy Direct segment through generic N-lane physical evidence.

    New Direct certifications persist the same complete signatures consumed by
    ``_certified_column_context``.  This adapter remains for old records whose
    signatures are empty.  It derives no business value and never writes back:
    every lane must be independently present in the bounded body and have a
    physical leaf header before the context can participate in arbitration.
    """
    values = [row for row in (certified_segments or []) if isinstance(row, dict)]
    if len(values) != 1:
        return None
    segment = values[0]
    evidence = dict(segment.get("evidence") or {})
    if str(evidence.get("strategy") or "") != "DIRECT_PORTFOLIO_TABLES":
        return None
    status = str(
        segment.get("certification_status")
        or segment.get("status")
        or ""
    ).strip().upper()
    if status != "CERTIFIED":
        return None
    try:
        segment_page = int(
            segment.get("pdf_page_number")
            or segment.get("start_page")
            or (segment.get("bbox") or {}).get("page")
        )
    except (TypeError, ValueError):
        return None
    if segment_page != int(page_number):
        return None
    certified_period_labels = [
        str(value).strip()
        for value in evidence.get("period_labels") or []
        if str(value).strip()
    ]
    if not certified_period_labels:
        return None
    bbox = _candidate_title_bbox(segment.get("bbox") or {})
    topology = _validated_physical_column_topology(
        lines,
        bbox=bbox,
        page_width=float(page_width),
        certified_period_labels=certified_period_labels,
    )
    if topology is None:
        return None
    return {
        "segment": segment,
        "classification": str(segment.get("classification") or "PRIMARY_TABLE"),
        "lane_count": int(topology["lane_count"]),
        "anchors": list(topology["anchors"]),
        "anchor_ratios": list(topology["anchor_ratios"]),
        "numeric_assignment_anchors": list(topology["anchors"]),
        "numeric_clusters": dict(topology["numeric_clusters"]),
        "source_column_ordinals": list(topology["source_column_ordinals"]),
        "measure_labels": list(topology["measure_labels"]),
        "measure_kinds": list(topology["measure_kinds"]),
        "period_labels": list(topology["period_labels"]),
        "period_kinds": list(topology["period_kinds"]),
        "year_labels": list(topology["year_labels"]),
        "header_fingerprint": str(topology["header_fingerprint"]),
        "bbox": bbox,
        "header_y0": float(topology["header_y0"]),
        "header_y1": float(topology["header_y1"]),
        "data_y_min": float(topology["data_y_min"]),
        "header_line_index": int(topology["header_line_index"]),
        "header_line": dict(topology["header_line"]),
        "period_groups": list(topology["period_groups"]),
        "lane_group_ids": list(topology["lane_group_ids"]),
        "period_mapping_evidence": dict(topology["period_mapping_evidence"]),
        "period_label_resolution_evidence": dict(
            topology["period_label_resolution_evidence"]
        ),
        "period_details": list(topology["period_details"]),
        "header_geometry_source": "DIRECT_PORTFOLIO_PHYSICAL_COLUMN_TOPOLOGY_V4",
        "column_topology_contract_version": 4,
        "context_source": "LEGACY_RUNTIME_VALIDATED",
    }


def _direct_portfolio_measure_kind(text: str) -> str | None:
    """Map a physical Direct leaf label to an open column-measure kind."""
    compact = _line_compact(text)
    if not compact:
        return None
    if any(token in compact for token in ("增减变动", "变动率", "增长率", "同比")):
        return "CHANGE_RATE"
    if (
        "占比" in compact
        or "比例" in compact
        or compact in {"%", "％"}
    ):
        return "PERCENTAGE"
    if any(token in compact for token in ("金额", "账面值", "账面价值")):
        return "AMOUNT"
    if re.search(r"[A-Za-z\u4e00-\u9fff]", compact):
        return "OTHER"
    return None


def _is_period_fragment(text: str) -> bool:
    """Return whether a token is a date remainder, not a column measure.

    Complete periods are consumed through ``_period_words_generalized``.  This
    guard catches only remnants that can be left when a PDF splits one date
    across several physical words.  Such a remnant is never valid measure
    evidence on its own.
    """
    compact = _line_compact(text)
    if not compact:
        return False
    return bool(re.fullmatch(
        r"(?:年)?(?:1[0-2]|0?[1-9])月(?:3[01]|[12]\d|0?[1-9])日?"
        r"|(?:年)?(?:1[0-2]|0?[1-9])月"
        r"|年(?:1[0-2]|0?[1-9])"
        r"|月(?:3[01]|[12]\d|0?[1-9])"
        r"|(?:3[01]|[12]\d|0?[1-9])日"
        r"|日",
        compact,
    ))


def _period_word_is_consumed(
    *,
    line_index: int,
    word_index: int,
    word: dict[str, Any],
    period_line_index: int,
    period_hits: Sequence[dict[str, Any]],
) -> bool:
    if int(line_index) != int(period_line_index):
        return False
    if any(
        int(word_index) in {
            int(value) for value in hit.get("word_indices") or []
        }
        for hit in period_hits
    ):
        return True
    xc = float(word.get("xc", 0.0))
    yc = float(word.get("yc", 0.0))
    return any(
        float(hit["x0"]) - 0.5 <= xc <= float(hit["x1"]) + 0.5
        and float(hit["y0"]) - 0.5 <= yc <= float(hit["y1"]) + 0.5
        for hit in period_hits
    )


def _resolve_physical_period_labels(
    period_hits: Sequence[dict[str, Any]],
    certified_period_labels: Sequence[str],
) -> tuple[list[str], dict[str, Any]] | None:
    """Use bounded native headers as period identity and keep Stage A as evidence."""
    certified = [
        str(value).strip()
        for value in certified_period_labels
        if str(value).strip()
    ]
    physical = [
        str(hit.get("period_label") or hit.get("year") or "").strip()
        for hit in period_hits
    ]
    if (
        not certified
        or len(certified) != len(period_hits)
        or not all(physical)
    ):
        return None

    comparisons: list[dict[str, Any]] = []
    for index, (certified_label, physical_label, hit) in enumerate(
        zip(certified, physical, period_hits)
    ):
        certified_parsed = _parse_period_token(certified_label) or {}
        certified_year = str(certified_parsed.get("year") or "").strip()
        certified_semantic_label = str(
            certified_parsed.get("period_label") or certified_label
        ).strip()
        physical_year = str(hit.get("year") or "").strip()
        exact = (
            _line_compact(certified_semantic_label)
            == _line_compact(physical_label)
        )
        same_year = bool(
            certified_year
            and physical_year
            and certified_year == physical_year
        )
        comparisons.append({
            "ordinal": index,
            "certified_label": certified_label,
            "physical_label": physical_label,
            "certified_year": certified_year or None,
            "physical_year": physical_year or None,
            "resolution": (
                "EXACT"
                if exact
                else "PHYSICAL_LABEL_MORE_SPECIFIC"
                if same_year
                else "PHYSICAL_LABEL_OVERRIDES_CERTIFIED_HINT"
            ),
        })
    return physical, {
        "period_label_source": "BOUNDED_NATIVE_PHYSICAL_HEADER",
        "certified_period_labels": certified,
        "physical_period_labels": physical,
        "comparisons": comparisons,
        "physical_override_count": sum(
            item["resolution"] == "PHYSICAL_LABEL_OVERRIDES_CERTIFIED_HINT"
            for item in comparisons
        ),
    }


def _lane_horizontal_bounds(
    anchors: Sequence[float],
    *,
    bbox: dict[str, float],
) -> list[tuple[float, float]]:
    values = [float(value) for value in anchors]
    bounds: list[tuple[float, float]] = []
    for index, anchor in enumerate(values):
        left = (
            (values[index - 1] + anchor) / 2.0
            if index > 0
            else float(bbox["x0"])
        )
        right = (
            (anchor + values[index + 1]) / 2.0
            if index + 1 < len(values)
            else float(bbox["x1"])
        )
        bounds.append((left, right))
    return bounds


def _stacked_period_lane_partition(
    period_hits: Sequence[dict[str, Any]],
    anchors: Sequence[float],
    lane_indices: Sequence[int],
    *,
    bbox: dict[str, float],
    page_width: float,
    measure_kinds: Sequence[str] | None = None,
) -> tuple[dict[int, int], dict[str, Any]]:
    """Partition lower header lanes into monotonic parent-period groups."""
    ordered_lanes = list(lane_indices)
    period_count = len(period_hits)
    if period_count < 1 or len(ordered_lanes) < period_count:
        raise ValueError("CERTIFIED_COLUMN_CONTEXT_PERIOD_MAPPING_AMBIGUOUS")

    lane_bounds = _lane_horizontal_bounds(anchors, bbox=bbox)
    candidates: list[tuple[float, tuple[int, ...], list[list[int]]]] = []
    for cuts in itertools.combinations(
        range(1, len(ordered_lanes)),
        period_count - 1,
    ):
        offsets = (0, *cuts, len(ordered_lanes))
        groups = [
            ordered_lanes[offsets[index]:offsets[index + 1]]
            for index in range(period_count)
        ]
        score = 0.0
        for hit, group in zip(period_hits, groups):
            left = lane_bounds[group[0]][0]
            right = lane_bounds[group[-1]][1]
            child_center = (
                float(anchors[group[0]]) + float(anchors[group[-1]])
            ) / 2.0
            parent_center = float(hit["xc"])
            score += abs(parent_center - child_center)
            if parent_center < left:
                score += (left - parent_center) * 2.0
            elif parent_center > right:
                score += (parent_center - right) * 2.0
        candidates.append((score, cuts, groups))

    candidates.sort(key=lambda item: (item[0], item[1]))
    best_score, best_cuts, best_groups = candidates[0]
    ambiguity_margin = max(3.0, float(page_width) * 0.008)
    kinds = [str(value) for value in (measure_kinds or [])]
    repeated_groups: list[list[int]] = []
    repeated_schema: tuple[str, ...] = ()
    if (
        kinds
        and len(ordered_lanes) % period_count == 0
        and all(index < len(kinds) for index in ordered_lanes)
    ):
        group_size = len(ordered_lanes) // period_count
        repeated_groups = [
            ordered_lanes[index * group_size:(index + 1) * group_size]
            for index in range(period_count)
        ]
        schemas = [
            tuple(kinds[lane_index] for lane_index in group)
            for group in repeated_groups
        ]
        if (
            schemas[0]
            and all(schema == schemas[0] for schema in schemas[1:])
            and "AMOUNT" in schemas[0]
        ):
            repeated_schema = schemas[0]
            repeated_cuts = tuple(
                group_size * index for index in range(1, period_count)
            )
            # The repeated leaf schema is physical header evidence.  A parent
            # text box centred off-axis must not assign one period to one lane
            # and the next period to three lanes when the leaf schema visibly
            # repeats as equal groups.
            if best_cuts != repeated_cuts:
                best_groups = repeated_groups
                best_cuts = repeated_cuts
                best_score = next(
                    (score for score, cuts, _ in candidates if cuts == best_cuts),
                    best_score,
                )
                return {
                    lane_index: group_index
                    for group_index, group in enumerate(best_groups)
                    for lane_index in group
                }, {
                    "mapping_mode": "REPEATED_MEASURE_SCHEMA_CONSTRAINT",
                    "partition_score": best_score,
                    "partition_cuts": list(best_cuts),
                    "ambiguity_margin": ambiguity_margin,
                    "repeated_measure_schema": list(repeated_schema),
                }
    if (
        len(candidates) > 1
        and candidates[1][0] - best_score <= ambiguity_margin
        and candidates[1][1] != best_cuts
    ):
        # A repeated leaf schema (for example 金额/占比 | 金额/占比) is
        # independent physical evidence for equal contiguous period groups.
        # Use it only as an ambiguity tiebreak: every period must expose the
        # same non-empty measure sequence and contain an amount lane.
        if (
            repeated_groups
            and repeated_schema
        ):
            group_size = len(ordered_lanes) // period_count
            best_groups = repeated_groups
            best_cuts = tuple(group_size * index for index in range(1, period_count))
            best_score = next(
                (score for score, cuts, _ in candidates if cuts == best_cuts),
                best_score,
            )
            return {
                lane_index: group_index
                for group_index, group in enumerate(best_groups)
                for lane_index in group
            }, {
                "mapping_mode": "REPEATED_MEASURE_SCHEMA_TIEBREAK",
                "partition_score": best_score,
                "partition_cuts": list(best_cuts),
                "ambiguity_margin": ambiguity_margin,
                "repeated_measure_schema": list(repeated_schema),
            }
        raise ValueError(
            "PERIOD_PARENT_AMBIGUOUS:"
            f"period_count={period_count}:lanes={ordered_lanes}:"
            f"measure_kinds={[str(value) for value in (measure_kinds or [])]}"
        )

    assignment = {
        lane_index: group_index
        for group_index, group in enumerate(best_groups)
        for lane_index in group
    }
    return assignment, {
        "mapping_mode": "MULTIROW_CONTIGUOUS_COLUMN_GROUP",
        "partition_score": best_score,
        "partition_cuts": list(best_cuts),
        "ambiguity_margin": ambiguity_margin,
    }


def _single_row_period_lane_assignment(
    period_hits: Sequence[dict[str, Any]],
    anchors: Sequence[float],
    leaf_bboxes: Sequence[dict[str, float]],
    lane_indices: Sequence[int],
    *,
    page_width: float,
) -> tuple[dict[int, int], dict[str, Any]]:
    """Resolve same-row parents with a left preference and right fallback."""
    assignment: dict[int, int] = {}
    direction_by_lane: dict[int, str] = {}
    right_penalty = max(48.0, float(page_width) * 0.20)
    ambiguity_margin = max(3.0, float(page_width) * 0.008)
    for lane_index in lane_indices:
        leaf = leaf_bboxes[lane_index]
        scored: list[tuple[float, int, str]] = []
        for period_index, hit in enumerate(period_hits):
            if float(hit["x1"]) <= float(leaf["x0"]) + 2.0:
                score = max(0.0, float(leaf["x0"]) - float(hit["x1"]))
                direction = "LEFT"
            elif float(hit["x0"]) >= float(leaf["x1"]) - 2.0:
                score = (
                    max(0.0, float(hit["x0"]) - float(leaf["x1"]))
                    + right_penalty
                )
                direction = "RIGHT_PENALISED"
            else:
                score = abs(float(hit["xc"]) - float(anchors[lane_index]))
                direction = "OVERLAP"
            scored.append((score, period_index, direction))
        scored.sort(key=lambda item: (item[0], item[1]))
        if (
            len(scored) > 1
            and scored[1][0] - scored[0][0] <= ambiguity_margin
            and scored[1][1] != scored[0][1]
        ):
            raise ValueError("PERIOD_PARENT_AMBIGUOUS")
        assignment[lane_index] = scored[0][1]
        direction_by_lane[lane_index] = scored[0][2]

    assigned_groups = [assignment[index] for index in lane_indices]
    if assigned_groups != sorted(assigned_groups):
        raise ValueError("PERIOD_PARENT_DIRECTION_CONFLICT")
    if set(assigned_groups) != set(range(len(period_hits))):
        raise ValueError("CERTIFIED_COLUMN_CONTEXT_PERIOD_MAPPING_AMBIGUOUS")
    return assignment, {
        "mapping_mode": "SAME_ROW_LEFT_PREFERRED_RIGHT_PENALISED",
        "right_penalty": right_penalty,
        "ambiguity_margin": ambiguity_margin,
        "direction_by_lane": {
            str(index): direction_by_lane[index] for index in lane_indices
        },
    }


def _certified_period_column_groups(
    *,
    period_hits: Sequence[dict[str, Any]],
    period_line_index: int,
    period_labels: Sequence[str],
    anchors: Sequence[float],
    leaf_bboxes: Sequence[dict[str, float]],
    measure_kinds: Sequence[str],
    measure_line_indices: Sequence[int],
    bbox: dict[str, float],
    page_width: float,
) -> tuple[list[int | None], list[dict[str, Any]], dict[str, Any]]:
    ordinary_lanes = [
        index
        for index, kind in enumerate(measure_kinds)
        if str(kind) != "CHANGE_RATE"
    ]
    same_row = int(period_line_index) in {
        int(value) for value in measure_line_indices
    }
    if same_row:
        assignment, mapping_evidence = _single_row_period_lane_assignment(
            period_hits,
            anchors,
            leaf_bboxes,
            ordinary_lanes,
            page_width=page_width,
        )
    else:
        assignment, mapping_evidence = _stacked_period_lane_partition(
            period_hits,
            anchors,
            ordinary_lanes,
            bbox=bbox,
            page_width=page_width,
            measure_kinds=measure_kinds,
        )

    lane_bounds = _lane_horizontal_bounds(anchors, bbox=bbox)
    lane_group_indices: list[int | None] = [None] * len(anchors)
    groups: list[dict[str, Any]] = []
    for group_index, (hit, period_label) in enumerate(
        zip(period_hits, period_labels)
    ):
        group_lanes = sorted(
            lane_index
            for lane_index, assigned_group in assignment.items()
            if assigned_group == group_index
        )
        if not group_lanes:
            raise ValueError("CERTIFIED_COLUMN_CONTEXT_PERIOD_MAPPING_AMBIGUOUS")
        for lane_index in group_lanes:
            lane_group_indices[lane_index] = group_index
        child_boxes = [leaf_bboxes[index] for index in group_lanes]
        consumed_span = {
            "line_index": int(period_line_index),
            "word_indices": [
                int(value) for value in hit.get("word_indices") or []
            ],
            "text": str(hit.get("token") or ""),
            "bbox": {
                key: float(hit[key]) for key in ("x0", "y0", "x1", "y1")
            },
            "method": "MAXIMAL_CONTIGUOUS_PERIOD_SPAN",
        }
        left = lane_bounds[group_lanes[0]][0]
        right = lane_bounds[group_lanes[-1]][1]
        group_id = f"PERIOD_GROUP_{group_index + 1}"
        groups.append({
            "period": str(period_label),
            "period_anchor_bbox": {
                key: float(hit[key]) for key in ("x0", "y0", "x1", "y1")
            },
            "period_group_bbox": {
                "x0": float(left),
                "y0": min(float(hit["y0"]), *(float(box["y0"]) for box in child_boxes)),
                "x1": float(right),
                "y1": max(float(hit["y1"]), *(float(box["y1"]) for box in child_boxes)),
            },
            "period_header_row_band": {
                "y0": float(hit["y0"]),
                "y1": float(hit["y1"]),
            },
            "child_header_row_band": {
                "y0": min(float(box["y0"]) for box in child_boxes),
                "y1": max(float(box["y1"]) for box in child_boxes),
            },
            "consumed_spans": [consumed_span],
            "column_group_id": group_id,
            "confidence": 1.0,
            "evidence": {
                **mapping_evidence,
                "lane_ordinals": group_lanes,
            },
        })
    return lane_group_indices, groups, mapping_evidence


def _resolve_observation_unit(
    *,
    raw_cell_unit: str | None,
    measure: str | None,
    number: float | None,
    certified_amount_unit: str | None,
    page_context_unit: str | None,
    page_context_source_page: int | None = None,
    certified_amount_unit_code: str | None = None,
) -> tuple[str | None, float | None, str, dict[str, Any]]:
    """Resolve one numeric observation's effective unit and provenance."""
    cell_unit = str(raw_cell_unit or "").strip() or None
    measure_text = str(measure or "").strip()
    percent_measure = measure_text in {
        "占比", "金额增减变动", "比例", "百分比",
    }
    if cell_unit == "%" or percent_measure:
        return (
            "%",
            None,
            "EXPLICIT_CELL_PERCENT" if cell_unit == "%" else "CERTIFIED_COLUMN_MEASURE",
            {"measure": measure_text},
        )

    resolved_unit = (
        cell_unit
        or str(certified_amount_unit or "").strip()
        or str(page_context_unit or "").strip()
        or None
    )
    multiplier = {
        "元": 1.0,
        "千元": 1_000.0,
        "万元": 10_000.0,
        "百万元": 1_000_000.0,
        "亿元": 100_000_000.0,
    }.get(resolved_unit or "")
    value_yuan = (
        number * multiplier
        if number is not None and multiplier is not None
        else None
    )
    if cell_unit:
        source = "EXPLICIT_CELL_UNIT"
    elif certified_amount_unit:
        source = "CERTIFIED_DIRECT_AMOUNT_UNIT"
    elif page_context_unit:
        source = "NATIVE_PAGE_CONTEXT"
    else:
        source = "UNIT_UNRESOLVED_AMOUNT_OBSERVATION"
    return resolved_unit, value_yuan, source, {
        "measure": measure_text,
        "certified_amount_unit": certified_amount_unit_code or None,
        "resolved_unit": resolved_unit,
        "source_page": page_context_source_page,
    }


def _validated_physical_column_topology(
    lines: list[dict[str, Any]],
    *,
    bbox: dict[str, float],
    page_width: float,
    certified_period_labels: list[str],
) -> dict[str, Any] | None:
    """Build an N-lane topology from one bounded physical table.

    Period groups, leaf headers, body lanes and their bboxes must all agree.
    A cross-period change column remains a distinct ``PERIOD_CHANGE`` lane; it
    is never silently assigned to the current or comparative period.
    """
    numeric = _numeric_column_clusters(
        lines,
        header_y1=float(bbox["y0"]),
        page_width=float(page_width),
        body_end_y=float(bbox["y1"]),
    )
    anchors = [float(value) for value in numeric.get("centers") or []]
    if not anchors:
        return None
    body_y = _first_body_line_y(
        lines,
        start_y=float(bbox["y0"]),
        centers=anchors,
        page_width=float(page_width),
    )
    if body_y is None:
        return None

    header_lines = [
        (index, line)
        for index, line in enumerate(lines)
        if float(line["y1"]) >= float(bbox["y0"]) - 2.0
        and float(line["y0"]) < float(body_y)
    ]
    period_candidates: list[tuple[int, dict[str, Any], list[dict[str, Any]]]] = []
    for index, line in header_lines:
        period_hits = _period_words(line)
        if period_hits:
            period_candidates.append((index, line, period_hits))
    if not period_candidates:
        return None
    period_index, period_line, period_hits = max(
        period_candidates,
        key=lambda item: (len(item[2]), float(item[1]["y1"])),
    )
    period_hits = sorted(period_hits, key=lambda hit: float(hit["xc"]))
    period_resolution = _resolve_physical_period_labels(
        period_hits,
        certified_period_labels,
    )
    if period_resolution is None:
        return None
    resolved_periods, period_label_resolution_evidence = period_resolution
    half_widths = _column_half_widths(anchors, float(page_width))
    period_top = min(float(hit["y0"]) for hit in period_hits)
    matched: dict[int, list[tuple[int, dict[str, Any]]]] = {}
    for index, line in header_lines:
        if float(line["y1"]) < period_top - 2.0:
            continue
        for word_index, word in enumerate(line.get("words") or []):
            if _period_word_is_consumed(
                line_index=index,
                word_index=word_index,
                word=word,
                period_line_index=period_index,
                period_hits=period_hits,
            ):
                continue
            text = clean_cell(word.get("text", ""))
            if not text or _is_unit_only_header(text) or "单位" in text:
                continue
            if _parse_period_token(text):
                continue
            if _is_period_fragment(text):
                raise ValueError("PERIOD_FRAGMENT_IN_MEASURE_LABEL")
            kind = _direct_portfolio_measure_kind(word.get("text", ""))
            if kind is None:
                continue
            lane_index = _nearest_anchor_index(float(word["xc"]), anchors)
            if (
                abs(float(word["xc"]) - anchors[lane_index])
                > half_widths[lane_index] * 1.35
            ):
                continue
            matched.setdefault(lane_index, []).append((index, {**word, "text": text}))

    # Some Direct tables use the complete period itself as the amount-column
    # leaf and print only the adjacent percentage label.  Once the complete
    # period span has been consumed, certify the single remaining lane inside
    # each period region as AMOUNT only when that region already contains an
    # explicit percentage lane.  This is physical column-group evidence, not
    # a table-wide default-unit or alternating-column assumption.
    if set(matched) != set(range(len(anchors))):
        # In the CPIC native layout a parent date is printed over the amount
        # lane and the percentage leaf sits immediately to its right.  Using
        # the parent text midpoint as a region boundary splits that pair at
        # the wrong place.  Anchor each parent to its nearest physical lane,
        # then let the next parent define the start of the next contiguous
        # group.  This is only a local amount-lane recovery; the certified
        # period-group resolver below remains the authority for final period
        # assignment and ambiguity handling.
        parent_anchor_lanes = [
            _nearest_anchor_index(float(hit["xc"]), anchors)
            for hit in period_hits
        ]
        monotonic_parent_lanes = all(
            right > left
            for left, right in zip(parent_anchor_lanes, parent_anchor_lanes[1:])
        )
        if monotonic_parent_lanes:
            period_lane_ranges = [
                (
                    parent_anchor_lanes[hit_index],
                    (
                        parent_anchor_lanes[hit_index + 1] - 1
                        if hit_index + 1 < len(parent_anchor_lanes)
                        else len(anchors) - 1
                    ),
                )
                for hit_index in range(len(period_hits))
            ]
        else:
            period_lane_ranges = []
        for hit_index, hit in enumerate(period_hits):
            if period_lane_ranges:
                start_lane, end_lane = period_lane_ranges[hit_index]
                region_lanes = list(range(start_lane, end_lane + 1))
            else:
                region_lanes = []
            missing_lanes = [
                lane_index for lane_index in region_lanes
                if lane_index not in matched
            ]
            explicit_kinds = {
                _direct_portfolio_measure_kind(
                    "".join(str(word.get("text") or "") for _, word in matched[lane_index])
                )
                for lane_index in region_lanes
                if lane_index in matched
            }
            if len(missing_lanes) != 1 or "PERCENTAGE" not in explicit_kinds:
                continue
            lane_index = missing_lanes[0]
            matched[lane_index] = [(
                period_index,
                {
                    **hit,
                    "text": "金额",
                    "measure_inference": "PERIOD_SPAN_AMOUNT_LANE",
                    "period_hit_index": hit_index,
                },
            )]

    if set(matched) != set(range(len(anchors))):
        return None
    measure_labels: list[str] = []
    measure_kinds: list[str] = []
    leaf_bboxes: list[dict[str, float]] = []
    measure_line_indices: set[int] = set()
    for lane_index in range(len(anchors)):
        values = sorted(
            matched[lane_index],
            key=lambda item: (float(item[1]["y0"]), float(item[1]["x0"])),
        )
        tokens: list[str] = []
        for line_index, word in values:
            measure_line_indices.add(line_index)
            token = clean_cell(word.get("text", ""))
            if token and token not in tokens:
                tokens.append(token)
        label = "".join(tokens)
        if not label:
            return None
        kind = _direct_portfolio_measure_kind(label) or "UNRESOLVED"
        measure_labels.append(label)
        measure_kinds.append(kind)
        words = [item[1] for item in values]
        leaf_bboxes.append({
            "x0": min(float(word["x0"]) for word in words),
            "y0": min(float(word["y0"]) for word in words),
            "x1": max(float(word["x1"]) for word in words),
            "y1": max(float(word["y1"]) for word in words),
        })

    # OCR can corrupt one repeated leaf label while preserving its physical
    # lane. Complete only OTHER/UNRESOLVED positions from the same ordinal in
    # every equal-sized period group when all recognized peers agree. This is
    # a local repeated-header schema repair, not an alternating-column rule.
    measure_kind_recovery: list[dict[str, Any]] = []
    period_count = len(resolved_periods)
    if period_count > 1 and len(measure_kinds) % period_count == 0:
        group_size = len(measure_kinds) // period_count
        for offset in range(group_size):
            lane_indices = [group * group_size + offset for group in range(period_count)]
            known = {
                measure_kinds[index]
                for index in lane_indices
                if measure_kinds[index] not in {"OTHER", "UNRESOLVED"}
            }
            if len(known) != 1:
                continue
            recovered_kind = next(iter(known))
            for index in lane_indices:
                if measure_kinds[index] not in {"OTHER", "UNRESOLVED"}:
                    continue
                measure_kind_recovery.append({
                    "lane_index": index,
                    "raw_label": measure_labels[index],
                    "recovered_kind": recovered_kind,
                    "peer_lane_indices": [value for value in lane_indices if value != index],
                    "method": "REPEATED_PERIOD_LEAF_ORDINAL",
                })
                measure_kinds[index] = recovered_kind
                if recovered_kind == "PERCENTAGE":
                    measure_labels[index] = "占比"
                elif recovered_kind == "AMOUNT":
                    measure_labels[index] = "金额"

    measure_line_indices = sorted(measure_line_indices)
    lane_group_indices, period_groups, period_mapping_evidence = (
        _certified_period_column_groups(
            period_hits=period_hits,
            period_line_index=period_index,
            period_labels=resolved_periods,
            anchors=anchors,
            leaf_bboxes=leaf_bboxes,
            measure_kinds=measure_kinds,
            measure_line_indices=measure_line_indices,
            bbox=bbox,
            page_width=float(page_width),
        )
    )

    period_labels: list[str] = []
    period_kinds: list[str] = []
    year_labels: list[str | None] = []
    for lane_index, (anchor, kind) in enumerate(zip(anchors, measure_kinds)):
        if kind == "CHANGE_RATE":
            if len(resolved_periods) < 2:
                return None
            period_labels.append(f"{resolved_periods[0]}较{resolved_periods[1]}")
            period_kinds.append("PERIOD_CHANGE")
            year_labels.append(None)
            continue
        period_group = lane_group_indices[lane_index]
        if period_group is None:
            raise ValueError("CERTIFIED_COLUMN_CONTEXT_PERIOD_MAPPING_AMBIGUOUS")
        period_label = resolved_periods[period_group]
        period_labels.append(period_label)
        period_hit = period_hits[period_group]
        period_kinds.append(
            str(period_hit.get("period_kind") or "ABSOLUTE_YEAR")
        )
        year_labels.append(
            str(period_hit.get("year") or period_label).strip() or period_label
        )

    lane_group_ids = [
        (
            period_groups[group_index]["column_group_id"]
            if group_index is not None
            else "PERIOD_CHANGE_GROUP"
        )
        for group_index in lane_group_indices
    ]
    header_line_index = measure_line_indices[-1]
    header_line = lines[header_line_index]
    header_y0 = min(
        min(float(hit["y0"]) for hit in period_hits),
        min(float(value["y0"]) for value in leaf_bboxes),
    )
    header_y1 = max(
        max(float(hit["y1"]) for hit in period_hits),
        max(float(value["y1"]) for value in leaf_bboxes),
    )
    fingerprint_payload = {
        "labels": measure_labels,
        "period_labels": period_labels,
        "measure_kinds": measure_kinds,
        "lane_group_ids": lane_group_ids,
    }
    fingerprint = hashlib.sha256(
        json.dumps(
            fingerprint_payload,
            ensure_ascii=False,
            sort_keys=True,
        ).encode("utf-8")
    ).hexdigest()
    period_details = [
        normalize_period_fields(period_label=label, year=year)
        for label, year in zip(period_labels, year_labels)
    ]
    return {
        "contract_version": 4,
        "lane_count": len(anchors),
        "anchors": anchors,
        "anchor_ratios": [value / float(page_width) for value in anchors],
        "source_column_ordinals": list(range(len(anchors))),
        "numeric_clusters": numeric,
        "measure_labels": measure_labels,
        "measure_kinds": measure_kinds,
        "period_labels": period_labels,
        "period_kinds": period_kinds,
        "year_labels": year_labels,
        "period_details": period_details,
        "lane_group_ids": lane_group_ids,
        "period_groups": period_groups,
        "period_mapping_evidence": period_mapping_evidence,
        "period_label_resolution_evidence": period_label_resolution_evidence,
        "measure_kind_recovery": measure_kind_recovery,
        "leaf_bboxes": leaf_bboxes,
        "header_bbox": {
            "x0": min(float(hit["x0"]) for hit in period_hits + [
                {"x0": value["x0"]} for value in leaf_bboxes
            ]),
            "y0": header_y0,
            "x1": max(float(hit["x1"]) for hit in period_hits + [
                {"x1": value["x1"]} for value in leaf_bboxes
            ]),
            "y1": header_y1,
        },
        "header_y0": header_y0,
        "header_y1": header_y1,
        "data_y_min": header_y1,
        "period_line_index": int(period_index),
        "measure_line_indices": measure_line_indices,
        "header_line_index": int(header_line_index),
        "header_line": header_line,
        "header_fingerprint": fingerprint,
    }


def build_certified_column_topology_from_pdf(
    pdf_path: Path | str,
    *,
    page_number: int,
    bbox: dict[str, Any],
    period_labels: Sequence[str],
    ocr_cache_root: Path | str | None = None,
) -> dict[str, Any] | None:
    """Build persisted column signatures, with bounded Fast Index recovery.

    Native PDF words remain authoritative. When Stage A already identified a
    direct physical portfolio table but its image-backed header has no usable
    Native word geometry, Stage B may OCR that one certified page through the
    existing Conditional OCR/Fast Index owner. OCR must provide V2 coordinate
    metadata and is converted to PDF points before the same topology validator
    runs; no period or lane is inferred from the filing year.
    """
    path = Path(pdf_path)
    geometry_source = "NATIVE_PDF_WORDS"
    recovery_audit: dict[str, Any] = {}
    certified_ocr_words_pdf_points: list[list[Any]] = []
    with fitz.open(path) as doc:
        if int(page_number) < 1 or int(page_number) > len(doc):
            return None
        page = doc[int(page_number) - 1]
        normalized_bbox = {
            "x0": float(bbox["x0"]),
            "y0": float(bbox["y0"]),
            "x1": float(bbox["x1"]),
            "y1": float(bbox["y1"]),
        }
        roi = {
            "start_page": int(page_number),
            "end_page": int(page_number),
            "start_y": normalized_bbox["y0"],
            "end_y": normalized_bbox["y1"],
            "certified_page_bboxes": {int(page_number): normalized_bbox},
        }
        lines = _lines_in_roi(doc, roi, int(page_number))
        topology = _validated_physical_column_topology(
            lines,
            bbox=normalized_bbox,
            page_width=float(page.rect.width),
            certified_period_labels=list(period_labels),
        )
        if topology is None and ocr_cache_root is not None:
            from conditional_statement_ocr import ocr_statement_page_group
            from statement_anchor_evidence_v2 import _normalize_ocr_words_to_pdf_points

            payload, recovery_audit = ocr_statement_page_group(
                path,
                cache_root=Path(ocr_cache_root),
                page_numbers=[int(page_number)],
                recovery_stage="DIRECT_PORTFOLIO_CERTIFIED_COLUMN_TOPOLOGY_RECOVERY",
            )
            page_payload = dict(payload.get(int(page_number)) or {})
            normalized_words, _, normalized_metadata = _normalize_ocr_words_to_pdf_points(
                list(page_payload.get("ocr_words") or []),
                dict(page_payload.get("metadata") or {}),
                page_width=float(page.rect.width),
                page_height=float(page.rect.height),
            )
            if normalized_metadata is not None:
                ocr_word_dicts = [
                    {
                        "x0": float(word[0]), "y0": float(word[1]),
                        "x1": float(word[2]), "y1": float(word[3]),
                        "xc": (float(word[0]) + float(word[2])) / 2.0,
                        "yc": (float(word[1]) + float(word[3])) / 2.0,
                        "text": str(word[4]), "block": 0, "line": 0, "word": index,
                    }
                    for index, word in enumerate(normalized_words)
                ]
                # Tesseract may put YYYY/31日 and 年12月 on adjacent baselines.
                # Collapse only a complete, left-to-right date sequence in the
                # same visual band before line grouping. Consumed fragments are
                # removed so they cannot masquerade as measure labels.
                consumed: set[int] = set()
                reconstructed: list[dict[str, Any]] = []
                patterns = (
                    re.compile(r"年"), re.compile(r"(?:1[0-2]|[1-9])"),
                    re.compile(r"月"), re.compile(r"(?:3[01]|[12]\d|[1-9])"),
                    re.compile(r"日"),
                )
                for year_index, year_word in enumerate(ocr_word_dicts):
                    year = clean_cell(year_word.get("text", ""))
                    if not re.fullmatch(r"20\d{2}", year) or year_index in consumed:
                        continue
                    selected = [year_index]
                    cursor_x = float(year_word["xc"])
                    for pattern in patterns:
                        matches = [
                            (index, word) for index, word in enumerate(ocr_word_dicts)
                            if index not in consumed and index not in selected
                            and float(word["xc"]) > cursor_x
                            and float(word["xc"]) - float(year_word["xc"]) <= 100.0
                            and abs(float(word["yc"]) - float(year_word["yc"])) <= 10.0
                            and pattern.fullmatch(clean_cell(word.get("text", "")))
                        ]
                        if not matches:
                            selected = []
                            break
                        index, word = min(matches, key=lambda item: float(item[1]["xc"]))
                        selected.append(index)
                        cursor_x = float(word["xc"])
                    if len(selected) != 6:
                        continue
                    parts = [ocr_word_dicts[index] for index in selected]
                    month = int(clean_cell(parts[2]["text"]))
                    day = int(clean_cell(parts[4]["text"]))
                    synthetic = {
                        "x0": min(float(word["x0"]) for word in parts),
                        "y0": min(float(word["y0"]) for word in parts),
                        "x1": max(float(word["x1"]) for word in parts),
                        "y1": max(float(word["y1"]) for word in parts),
                        "text": f"{year}年{month}月{day}日",
                        "block": 0, "line": 0, "word": year_index,
                    }
                    synthetic["xc"] = (synthetic["x0"] + synthetic["x1"]) / 2.0
                    synthetic["yc"] = (synthetic["y0"] + synthetic["y1"]) / 2.0
                    reconstructed.append(synthetic)
                    consumed.update(selected)
                if reconstructed:
                    ocr_word_dicts = [
                        word for index, word in enumerate(ocr_word_dicts)
                        if index not in consumed
                    ] + reconstructed
                ocr_lines = [
                    line for line in _group_lines(ocr_word_dicts)
                    if belongs_to_certified_roi(line, normalized_bbox)
                ]
                topology = _validated_physical_column_topology(
                    ocr_lines,
                    bbox=normalized_bbox,
                    page_width=float(page.rect.width),
                    certified_period_labels=list(period_labels),
                )
                if topology is not None:
                    geometry_source = "FAST_INDEX_OCR_WORDS_PDF_POINTS"
                    certified_ocr_words_pdf_points = [
                        [
                            float(word["x0"]), float(word["y0"]),
                            float(word["x1"]), float(word["y1"]),
                            str(word["text"]),
                        ]
                        for line in ocr_lines
                        for word in line.get("words") or []
                    ]
    if topology is None:
        return None
    return {
        "period_signature": {
            "contract_version": 4,
            "period_labels": list(topology["period_labels"]),
            "period_kinds": list(topology["period_kinds"]),
            "year_labels": list(topology["year_labels"]),
            "periods": list(topology["period_details"]),
            "source_period_labels": [str(value) for value in period_labels],
            "period_label_resolution": dict(
                topology["period_label_resolution_evidence"]
            ),
            "lane_group_ids": list(topology["lane_group_ids"]),
            "column_groups": list(topology["period_groups"]),
        },
        "header_signature": {
            "contract_version": 3,
            "fingerprint": str(topology["header_fingerprint"]),
            "leaf_count": int(topology["lane_count"]),
            "labels": list(topology["measure_labels"]),
            "measure_kinds": list(topology["measure_kinds"]),
            "leaf_bboxes": list(topology["leaf_bboxes"]),
            "header_bbox": dict(topology["header_bbox"]),
        },
        "amount_lane_signature": {
            "contract_version": 3,
            "lane_count": int(topology["lane_count"]),
            "anchor_ratios": list(topology["anchor_ratios"]),
            "source_column_ordinals": list(topology["source_column_ordinals"]),
        },
        "evidence": {
            "column_topology_contract_version": 4,
            "column_topology_source": "CERTIFIED_PERIOD_GROUP_AND_BODY_LANES",
            "header_y0": float(topology["header_y0"]),
            "header_y1": float(topology["header_y1"]),
            "data_y_min": float(topology["data_y_min"]),
            "period_mapping_evidence": dict(topology["period_mapping_evidence"]),
            "period_label_resolution_evidence": dict(
                topology["period_label_resolution_evidence"]
            ),
            "measure_kind_recovery": list(topology.get("measure_kind_recovery") or []),
            "certified_column_geometry_source": geometry_source,
            "ocr_recovery_stage": (
                recovery_audit.get("recovery_stage") if recovery_audit else ""
            ),
            "ocr_recovery_pages": list(recovery_audit.get("ocr_pages") or []),
            "ocr_cache_hits": int(recovery_audit.get("ocr_cache_hits") or 0),
            "ocr_cache_misses": int(recovery_audit.get("ocr_cache_misses") or 0),
            "certified_ocr_geometry_contract_version": (
                1 if certified_ocr_words_pdf_points else 0
            ),
            "certified_ocr_words_pdf_points": certified_ocr_words_pdf_points,
        },
    }


def _certified_ocr_lines_for_page(
    certified_segments: Sequence[dict[str, Any]] | None,
    *,
    page_number: int,
    certified_bbox: dict[str, float],
) -> list[dict[str, Any]] | None:
    """Replay the exact OCR geometry frozen by Stage-B certification."""
    matches: list[dict[str, Any]] = []
    for segment in certified_segments or []:
        if not isinstance(segment, dict):
            continue
        status = str(segment.get("certification_status") or segment.get("status") or "").upper()
        try:
            page = int(segment.get("pdf_page_number") or segment.get("start_page"))
        except (TypeError, ValueError):
            continue
        evidence = dict(segment.get("evidence") or {})
        if (
            status == "CERTIFIED"
            and page == int(page_number)
            and evidence.get("certified_column_geometry_source")
            == "FAST_INDEX_OCR_WORDS_PDF_POINTS"
            and int(evidence.get("certified_ocr_geometry_contract_version") or 0) == 1
        ):
            matches.append(evidence)
    if not matches:
        return None
    if len(matches) != 1:
        raise ValueError("CERTIFIED_OCR_GEOMETRY_AMBIGUOUS")
    raw_words = list(matches[0].get("certified_ocr_words_pdf_points") or [])
    words: list[dict[str, Any]] = []
    for index, raw in enumerate(raw_words):
        if not isinstance(raw, (list, tuple)) or len(raw) < 5:
            raise ValueError("CERTIFIED_OCR_GEOMETRY_WORD_INVALID")
        x0, y0, x1, y1 = (float(raw[value]) for value in range(4))
        text = str(raw[4] or "").strip()
        if not text or x1 <= x0 or y1 <= y0:
            raise ValueError("CERTIFIED_OCR_GEOMETRY_WORD_INVALID")
        words.append({
            "x0": x0, "y0": y0, "x1": x1, "y1": y1,
            "xc": (x0 + x1) / 2.0, "yc": (y0 + y1) / 2.0,
            "text": text, "block": 0, "line": 0, "word": index,
        })
    lines = [
        line for line in _group_lines(words)
        if belongs_to_certified_roi(line, certified_bbox)
    ]
    if not lines:
        raise ValueError("CERTIFIED_OCR_GEOMETRY_LINES_REQUIRED")
    return lines


def _hybrid_native_label_ocr_value_lines(
    native_lines: list[dict[str, Any]],
    ocr_lines: list[dict[str, Any]],
    certified_segments: Sequence[dict[str, Any]] | None,
    *,
    page_number: int,
    page_width: float,
) -> list[dict[str, Any]]:
    """Keep Native label identity while replaying certified OCR value lanes."""
    matching = []
    for segment in certified_segments or []:
        if not isinstance(segment, dict):
            continue
        status = str(segment.get("certification_status") or segment.get("status") or "").upper()
        try:
            page = int(segment.get("pdf_page_number") or segment.get("start_page"))
        except (TypeError, ValueError):
            continue
        evidence = dict(segment.get("evidence") or {})
        if (
            status == "CERTIFIED"
            and page == int(page_number)
            and evidence.get("certified_column_geometry_source")
            == "FAST_INDEX_OCR_WORDS_PDF_POINTS"
        ):
            matching.append(segment)
    if len(matching) != 1:
        raise ValueError("CERTIFIED_OCR_HYBRID_SEGMENT_AMBIGUOUS")
    ratios = [
        float(value)
        for value in dict(matching[0].get("amount_lane_signature") or {}).get(
            "anchor_ratios"
        ) or []
    ]
    if not ratios:
        raise ValueError("CERTIFIED_OCR_HYBRID_LANES_REQUIRED")
    anchors = [ratio * float(page_width) for ratio in ratios]
    if len(anchors) > 1:
        first_gap = anchors[1] - anchors[0]
    else:
        first_gap = float(page_width) * 0.25
    numeric_left = max(float(page_width) * 0.25, anchors[0] - first_gap * 0.55)

    native_label_words = [
        word
        for line in native_lines
        for word in line.get("words") or []
        if float(word["xc"]) < numeric_left
    ]
    selected_words = list(native_label_words)
    selected_words.extend(
        word
        for line in ocr_lines
        for word in line.get("words") or []
        if float(word["xc"]) >= numeric_left
    )

    # Preserve OCR label text only for a row band where Native supplied no
    # label fragment.  This keeps pure scan pages viable while preventing OCR
    # spellings from replacing an available PDF text-layer identity.
    for ocr_line in ocr_lines:
        ocr_label_words = [
            word for word in ocr_line.get("words") or []
            if float(word["xc"]) < numeric_left
        ]
        if not ocr_label_words:
            continue
        ocr_y0 = float(ocr_line["y0"])
        ocr_y1 = float(ocr_line["y1"])
        has_native_band = any(
            min(ocr_y1, float(line["y1"])) - max(ocr_y0, float(line["y0"]))
            >= 0.35 * min(
                max(0.01, ocr_y1 - ocr_y0),
                max(0.01, float(line["y1"]) - float(line["y0"])),
            )
            for line in native_lines
            if any(
                float(word["xc"]) < numeric_left
                for word in line.get("words") or []
            )
        )
        if not has_native_band:
            selected_words.extend(ocr_label_words)
    hybrid = _group_lines(selected_words)
    if not hybrid:
        raise ValueError("CERTIFIED_OCR_HYBRID_LINES_REQUIRED")
    return hybrid


def _certified_header(
    context: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any]]:
    lane_count = int(context["lane_count"])
    periods = list(context.get("period_labels") or [])
    if len(periods) == 1:
        mapped_periods = periods * lane_count
    elif len(periods) == lane_count:
        mapped_periods = periods
    else:
        raise ValueError("CERTIFIED_COLUMN_CONTEXT_PERIOD_MAPPING_AMBIGUOUS")
    measures = list(context.get("measure_labels") or [])
    if len(measures) != lane_count:
        raise ValueError("CERTIFIED_COLUMN_CONTEXT_MEASURES_REQUIRED")
    contract_version = int(context.get("column_topology_contract_version") or 1)
    period_kinds = list(context.get("period_kinds") or [])
    year_labels = list(context.get("year_labels") or [])
    measure_kinds = list(context.get("measure_kinds") or [])
    if contract_version >= 2 and (
        len(period_kinds) != lane_count
        or len(year_labels) != lane_count
        or len(measure_kinds) != lane_count
    ):
        raise ValueError("CERTIFIED_COLUMN_CONTEXT_V2_MAPPING_REQUIRED")
    if not period_kinds:
        period_kinds = ["ABSOLUTE_YEAR"] * lane_count
    if not year_labels:
        year_labels = list(mapped_periods)
    header = {
        "parser": "CERTIFIED_COLUMN_CONTEXT",
        "line_index": int(context.get("header_line_index") or 0),
        "line": dict(context.get("header_line") or {}),
        "anchors": list(context["anchors"]),
        "years": year_labels,
        "period_labels": list(mapped_periods),
        "period_kinds": period_kinds,
        "restated_hints": [False] * lane_count,
        "measure_labels": measures,
        "measure_kinds": measure_kinds,
        "lane_group_ids": list(context.get("lane_group_ids") or []),
        "period_groups": list(context.get("period_groups") or []),
        "header_y0": float(context["header_y0"]),
        "header_y1": float(context["header_y1"]),
    }
    metrics = {
        "parser": "CERTIFIED_COLUMN_CONTEXT",
        "status": "VALID",
        "score": 100.0,
        "leaf_count": lane_count,
        "numeric_cluster_count": lane_count,
        "numeric_clusters": dict(context["numeric_clusters"]),
        "hard_failures": [],
    }
    arbitration = {
        "mode": "AUTO",
        "auto_selected_parser": "CERTIFIED_COLUMN_CONTEXT",
        "selected_parser": "CERTIFIED_COLUMN_CONTEXT",
        "selection_reason": "CERTIFIED_CONTEXT_VALIDATED_BY_BODY_LANES",
        "auto_abstain": False,
        "candidates": {"CERTIFIED_COLUMN_CONTEXT": metrics},
    }
    return header, arbitration


def _arbitrate_with_certified_context(
    header: dict[str, Any],
    arbitration: dict[str, Any],
    context: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Add a complete certified topology as a bounded AUTO candidate."""
    certified_header, certified_arbitration = _certified_header(context)
    certified_metrics = dict(
        certified_arbitration["candidates"]["CERTIFIED_COLUMN_CONTEXT"]
    )
    merged_arbitration = dict(arbitration)
    candidates = dict(merged_arbitration.get("candidates") or {})
    candidates["CERTIFIED_COLUMN_CONTEXT"] = certified_metrics
    merged_arbitration["candidates"] = candidates
    observed_lane_count = len(header.get("anchors") or [])
    certified_lane_count = int(context["lane_count"])
    merged_arbitration["certified_context_lane_count"] = certified_lane_count
    merged_arbitration["selected_candidate_lane_count"] = observed_lane_count
    if observed_lane_count == certified_lane_count:
        merged_arbitration["certified_context_status"] = "LANE_COUNT_MATCH"
        return header, merged_arbitration
    merged_arbitration.update({
        "auto_selected_parser": "CERTIFIED_COLUMN_CONTEXT",
        "selected_parser": "CERTIFIED_COLUMN_CONTEXT",
        "selection_reason": "CERTIFIED_CONTEXT_RESOLVES_LANE_COUNT_CONFLICT",
        "auto_abstain": False,
        "certified_context_status": "SELECTED_FOR_LANE_COUNT_CONFLICT",
    })
    return certified_header, merged_arbitration


def _certified_vertical_period_plan(
    context: dict[str, Any],
    lines_by_page: dict[int, list[dict[str, Any]]],
    page_widths: dict[int, float],
) -> tuple[list[dict[str, Any]], dict[int, list[dict[str, Any]]]]:
    periods = list(context.get("period_labels") or [])
    lane_count = int(context["lane_count"])
    measures = list(context.get("measure_labels") or [])
    if len(periods) < 2 or len(periods) == lane_count:
        return [], {}
    if len(measures) != lane_count:
        raise ValueError("CERTIFIED_COLUMN_CONTEXT_MEASURES_REQUIRED")

    occurrences = []
    for page_number in sorted(lines_by_page):
        page_width = float(page_widths[page_number])
        page_lines = list(lines_by_page[page_number])
        for line_index, line in enumerate(page_lines):
            compact = _line_compact(line.get("text") or "")
            matched_period = next(
                (
                    period for period in periods
                    if re.search(rf"(?<!\d){re.escape(period)}年", compact)
                ),
                None,
            )
            if not matched_period:
                continue
            body_candidates = [
                candidate
                for candidate in page_lines[line_index:line_index + 4]
                if float(candidate.get("y0", 0.0))
                <= float(line.get("y1", 0.0)) + 48.0
                and len(_line_numeric_lane_centers(candidate, page_width))
                == lane_count
            ]
            if not body_candidates:
                continue
            occurrences.append((
                page_number,
                float(line["y0"]),
                min(float(candidate["y0"]) for candidate in body_candidates),
                matched_period,
            ))

    selected = []
    position = (-1, -1.0)
    for period in periods:
        candidates = [
            item for item in occurrences
            if item[3] == period and (item[0], item[1]) > position
        ]
        if not candidates:
            raise ValueError("CERTIFIED_VERTICAL_PERIOD_EVIDENCE_REQUIRED")
        chosen = min(candidates, key=lambda item: (item[0], item[1]))
        selected.append(chosen)
        position = (chosen[0], chosen[1])

    groups = []
    occurrences_by_page: dict[int, list[dict[str, Any]]] = {}
    for section_index, (page_number, y0, body_y, period) in enumerate(selected):
        anchors = [
            float(ratio) * float(page_widths[page_number])
            for ratio in context["anchor_ratios"]
        ]
        metadata = [
            {
                "year": period,
                "period_label": period,
                "period_kind": "ABSOLUTE_YEAR",
                "scope": None,
                "restated": False,
                "measure": measures[index],
                "tokens": [period, measures[index]],
            }
            for index in range(lane_count)
        ]
        column_offset = section_index * lane_count
        block_id = f"spatial_p{page_number}_certified_period_{section_index + 1}"
        header = {
            "parser": "CERTIFIED_VERTICAL_PERIOD_CONTEXT",
            "line_index": 0,
            "line": {},
            "anchors": anchors,
            "years": [period] * lane_count,
            "period_labels": [period] * lane_count,
            "period_kinds": ["ABSOLUTE_YEAR"] * lane_count,
            "restated_hints": [False] * lane_count,
            "measure_labels": measures,
            "header_y0": y0,
            "header_y1": body_y,
        }
        group = {
            "section_index": section_index,
            "header": header,
            "anchors": anchors,
            "anchor_ratios": list(context["anchor_ratios"]),
            "data_y_min": body_y,
            "column_offset": column_offset,
            "column_count": lane_count,
            "block_id": block_id,
            "period_labels": [period] * lane_count,
            "measure_labels": measures,
            "metadata": metadata,
            "header_page": page_number,
            "header_y0": y0,
            "source_pages": [page_number],
        }
        groups.append(group)
        occurrences_by_page.setdefault(page_number, []).append({
            "section_index": section_index,
            "header": header,
            "anchors": anchors,
            "data_y_min": body_y,
            "column_offset": column_offset,
            "column_count": lane_count,
            "block_id": block_id,
            "period_labels": [period] * lane_count,
            "header_page": page_number,
            "header_source_page": None,
        })
    return groups, occurrences_by_page


def _apply_certified_context_to_metadata(
    metadata: list[dict[str, Any]],
    context: dict[str, Any] | None,
) -> None:
    if context is None:
        return
    lane_count = int(context["lane_count"])
    if len(metadata) != lane_count:
        raise ValueError("CERTIFIED_COLUMN_CONTEXT_COLUMN_COUNT_MISMATCH")
    periods = list(context.get("period_labels") or [])
    mapped = periods * lane_count if len(periods) == 1 else periods
    if len(mapped) != lane_count:
        return
    period_kinds = list(context.get("period_kinds") or [])
    if len(period_kinds) != lane_count:
        period_kinds = ["ABSOLUTE_YEAR"] * lane_count
    year_labels = list(context.get("year_labels") or [])
    if len(year_labels) != lane_count:
        year_labels = list(mapped)
    measures = list(context.get("measure_labels") or [])
    if len(measures) != lane_count:
        raise ValueError("CERTIFIED_COLUMN_CONTEXT_MEASURES_REQUIRED")
    contract_version = int(
        context.get("column_topology_contract_version") or 1
    )
    for index, item in enumerate(metadata):
        existing = str(item.get("period_label") or "")
        if existing and existing != mapped[index] and contract_version < 3:
            raise ValueError("CERTIFIED_COLUMN_CONTEXT_PERIOD_CONFLICT")
        if _is_period_fragment(str(measures[index])) or _parse_period_token(
            str(measures[index])
        ):
            raise ValueError("PERIOD_FRAGMENT_IN_MEASURE_LABEL")
        item["year"] = year_labels[index]
        item["period_label"] = mapped[index]
        item["period_kind"] = period_kinds[index]
        if contract_version >= 3:
            item["measure"] = measures[index]
            preserved = [
                token
                for token in list(item.get("tokens") or [])
                if _scope_value(str(token))
                or any(
                    marker in normalize_text(str(token))
                    for marker in ("已重述", "经重述", "重述")
                )
            ]
            item["tokens"] = list(dict.fromkeys([
                mapped[index], measures[index], *preserved,
            ]))
        else:
            tokens = list(item.get("tokens") or [])
            if mapped[index] not in tokens:
                tokens.insert(0, mapped[index])
            item["tokens"] = tokens


def _apply_certified_segment_identity(
    plans: list[dict[str, Any]],
    context: dict[str, Any] | None,
) -> None:
    if context is None:
        return
    if len(plans) != 1:
        raise ValueError("CERTIFIED_SEGMENT_COUNT_CONFLICT")
    from table_segment_classifier import SegmentClassification

    segment = plans[0]["segment"]
    certified_bbox = context["bbox"]
    plans[0]["segment"] = dataclasses.replace(
        segment,
        classification=SegmentClassification(context["classification"]),
        bbox=(
            float(certified_bbox["x0"]),
            float(certified_bbox["y0"]),
            float(certified_bbox["x1"]),
            float(certified_bbox["y1"]),
        ),
        header_topology_fingerprint=(
            str(context.get("header_fingerprint") or "")
            or segment.header_topology_fingerprint
        ),
        source_column_ordinals=tuple(context["source_column_ordinals"]),
        anchor_ratios=tuple(context["anchor_ratios"]),
        period_labels=tuple(context["period_labels"]),
        measure_labels=tuple(context["measure_labels"]),
        header_y0=float(context["header_y0"]),
        header_y1=float(context["header_y1"]),
        data_y_min=float(context["data_y_min"]),
        data_y_max=float(certified_bbox["y1"]),
        reason_codes=tuple(dict.fromkeys([
            *segment.reason_codes,
            "CERTIFIED_SEGMENT_IDENTITY",
        ])),
    )


def _candidate_boundary_summary(
    boundary: dict[str, Any] | None,
    *,
    start_page: int,
    end_page: int,
) -> dict[str, Any]:
    source = dict(boundary or {})
    evidence = dict(source.get("boundary_evidence") or {})
    reason = str(source.get("boundary_reason") or evidence.get("reason") or "")
    confidence = str(
        source.get("boundary_confidence") or evidence.get("confidence") or ""
    ).upper()
    method = str(evidence.get("method") or source.get("method") or "").upper()
    explicit_status = str(source.get("boundary_status") or "").upper()
    next_note_verified = bool(evidence.get("next_note_verified"))
    peer_boundary = bool(
        next_note_verified
        and (
            reason in {"next_note_ordinal", "next_peer_heading"}
            or method in {"NEXT_NOTE_ORDINAL", "NEXT_PEER_HEADING"}
        )
    )
    complete = bool(
        peer_boundary
        or explicit_status in {
            "HARD_BOUNDARY_CONFIRMED",
            "VERIFIED_PEER_BOUNDARY",
            "VERIFIED_DOCUMENT_END",
        }
        or source.get("inventory_boundary_complete") is True
    )
    status = (
        "VERIFIED_PEER_BOUNDARY"
        if peer_boundary
        else explicit_status
        if explicit_status
        else "UNRESOLVED"
    )
    next_note_bbox: dict[str, Any] = {}
    raw_next_note_bbox = evidence.get("next_note_bbox")
    next_note_page = evidence.get("next_note_pdf_page_index")
    next_note_y0 = evidence.get("next_note_y0")
    if next_note_page is not None:
        next_note_bbox["page"] = int(next_note_page)
    if isinstance(raw_next_note_bbox, dict):
        coordinate_aliases = {
            "x0": ("x0", "left"),
            "y0": ("y0", "top"),
            "x1": ("x1", "right"),
            "y1": ("y1", "bottom"),
        }
        for coordinate, aliases in coordinate_aliases.items():
            for alias in aliases:
                if raw_next_note_bbox.get(alias) is not None:
                    next_note_bbox[coordinate] = float(
                        raw_next_note_bbox[alias]
                    )
                    break
    elif isinstance(raw_next_note_bbox, (list, tuple)) and len(
        raw_next_note_bbox
    ) == 4:
        next_note_bbox.update({
            "x0": float(raw_next_note_bbox[0]),
            "y0": float(raw_next_note_bbox[1]),
            "x1": float(raw_next_note_bbox[2]),
            "y1": float(raw_next_note_bbox[3]),
        })
    if "y0" not in next_note_bbox and next_note_y0 is not None:
        next_note_bbox["y0"] = float(next_note_y0)
    if "y0" in next_note_bbox and "y1" not in next_note_bbox:
        next_note_bbox["y1"] = float(next_note_bbox["y0"])
    next_note_bbox_source = (
        "BOUNDARY_EVIDENCE_BBOX"
        if {"x0", "y0", "x1", "y1"}.issubset(next_note_bbox)
        else "BOUNDARY_EVIDENCE_Y_ONLY"
        if "y0" in next_note_bbox
        else "UNAVAILABLE"
    )
    return {
        "status": status,
        "complete": complete,
        "reason": reason,
        "confidence": confidence,
        "method": method,
        "peer_classification": "PEER_TABLE" if peer_boundary else "",
        "next_note_verified": next_note_verified,
        "next_note_reference": evidence.get("next_note_reference"),
        "next_note_ordinal": evidence.get("next_note_ordinal"),
        "next_note_title": evidence.get("next_note_title"),
        "next_note_heading_raw": evidence.get("next_note_heading_raw"),
        "next_note_pdf_page_index": next_note_page,
        "next_note_y0": next_note_y0,
        "next_note_bbox": next_note_bbox,
        "next_note_bbox_source": next_note_bbox_source,
        "bounded_start_page": int(start_page),
        "bounded_end_page": int(end_page),
    }


def _candidate_page_bbox(
    lines: list[dict[str, Any]],
    *,
    page_number: int,
    page_width: float,
) -> dict[str, Any]:
    return {
        "page": int(page_number),
        "x0": min((float(line.get("x0", 0.0)) for line in lines), default=0.0),
        "y0": min((float(line.get("y0", 0.0)) for line in lines), default=0.0),
        "x1": max(
            (float(line.get("x1", page_width)) for line in lines),
            default=float(page_width),
        ),
        "y1": max((float(line.get("y1", 0.0)) for line in lines), default=0.0),
    }


def _unresolved_candidate_structure(
    *,
    candidate_namespace: str,
    note_identity: str,
    table_identity: str,
    start_page: int,
    end_page: int,
    title_bbox: dict[str, float],
    bounded_lines_by_page: dict[int, list[dict[str, Any]]],
    page_widths: dict[int, float],
    boundary_summary: dict[str, Any],
    issue_codes: list[str],
) -> dict[str, Any]:
    page_boxes = [
        _candidate_page_bbox(
            bounded_lines_by_page.get(page_number, []),
            page_number=page_number,
            page_width=float(page_widths[page_number]),
        )
        for page_number in range(start_page, end_page + 1)
    ]
    logical_id = _candidate_structure_id(
        "LTCAND",
        candidate_namespace,
        note_identity,
        table_identity,
        start_page,
        end_page,
        title_bbox,
        "UNRESOLVED",
    )
    segment_id = _candidate_structure_id(
        "STCAND", logical_id, start_page, end_page, page_boxes
    )
    periods = []
    for page_number in range(start_page, end_page + 1):
        for period in _segment_period_labels(
            bounded_lines_by_page.get(page_number, []),
            start_y=0.0,
            end_y=max(
                (
                    float(line.get("y1", 0.0))
                    for line in bounded_lines_by_page.get(page_number, [])
                ),
                default=0.0,
            ),
        ):
            if period not in periods:
                periods.append(period)
    logical_candidate = {
        "logical_table_candidate_id": logical_id,
        "table_order": 0,
        "classification": "UNRESOLVED",
        "proposed_classification": "UNRESOLVED",
        "title": table_identity,
        "start_page": int(start_page),
        "end_page": int(end_page),
        "bbox": {"pages": page_boxes},
        "signature": {
            "header_fingerprints": [],
            "period_labels": periods,
            "amount_lane_counts": [],
        },
        "evidence": {
            "source": "NATIVE_PDF_LINES",
            "note_identity": note_identity,
            "issue_codes": list(issue_codes),
        },
        "confidence": 0.0,
        "status": "REVIEW_REQUIRED",
    }
    segment_candidate = {
        "segment_candidate_id": segment_id,
        "logical_table_candidate_id": logical_id,
        "segment_order": 0,
        "classification": "UNRESOLVED",
        "proposed_classification": "UNRESOLVED",
        "start_page": int(start_page),
        "end_page": int(end_page),
        "bbox": {"pages": page_boxes},
        "continuation_of_segment_candidate_id": None,
        "period_signature": {"period_labels": periods},
        "header_signature": {"fingerprint": "", "leaf_count": 0, "labels": []},
        "amount_lane_signature": {"lane_count": 0, "anchor_ratios": []},
        "evidence": {
            "source": "NATIVE_PDF_LINES",
            "issue_codes": list(issue_codes),
        },
        "confidence": 0.0,
        "status": "REVIEW_REQUIRED",
    }
    inventory_id = _candidate_structure_id(
        "NTINV", candidate_namespace, logical_candidate, boundary_summary
    )
    return {
        "planner_version": _CANDIDATE_STRUCTURE_PLANNER_VERSION,
        "inventory_id": inventory_id,
        "inventory_status": "INCOMPLETE",
        "boundary_status": boundary_summary["status"],
        "boundary_evidence": boundary_summary,
        "logical_table_candidates": [logical_candidate],
        "segment_candidates": [segment_candidate],
        "issue_codes": list(dict.fromkeys(issue_codes)),
    }


def plan_table_structure_candidates(
    lines_by_page: dict[int, list[dict[str, Any]]],
    page_widths: dict[int, float],
    *,
    start_page: int,
    end_page: int,
    title_bbox: Any,
    note_identity: str,
    table_identity: str,
    unit: str | None = None,
    boundary: dict[str, Any] | None = None,
    candidate_namespace: str = "",
    header_parser_mode: str = "AUTO",
) -> dict[str, Any]:
    """Plan logical-table and physical-segment candidates without amounts."""
    start_page = int(start_page)
    end_page = int(end_page)
    if start_page < 1 or end_page < start_page:
        raise ValueError("INVALID_CANDIDATE_STRUCTURE_PAGE_RANGE")
    missing_widths = [
        page_number
        for page_number in range(start_page, end_page + 1)
        if float(page_widths.get(page_number, 0.0) or 0.0) <= 0.0
    ]
    if missing_widths:
        raise ValueError(
            f"CANDIDATE_STRUCTURE_PAGE_WIDTH_REQUIRED:{missing_widths}"
        )

    normalized_title_bbox = _candidate_title_bbox(title_bbox)
    raw_boundary = dict(boundary or {})
    boundary_end_y = raw_boundary.get("end_y")
    bounded_lines_by_page: dict[int, list[dict[str, Any]]] = {}
    for page_number in range(start_page, end_page + 1):
        page_lines = [dict(line) for line in lines_by_page.get(page_number, [])]
        if page_number == start_page:
            page_lines = [
                line
                for line in page_lines
                if float(line.get("y1", 0.0)) >= normalized_title_bbox["y1"]
            ]
        if page_number == end_page and boundary_end_y is not None:
            page_lines = [
                line
                for line in page_lines
                if float(line.get("y0", 0.0)) <= float(boundary_end_y)
            ]
        bounded_lines_by_page[page_number] = page_lines

    boundary_summary = _candidate_boundary_summary(
        boundary,
        start_page=start_page,
        end_page=end_page,
    )
    start_lines = bounded_lines_by_page.get(start_page, [])
    if not start_lines:
        return _unresolved_candidate_structure(
            candidate_namespace=candidate_namespace,
            note_identity=note_identity,
            table_identity=table_identity,
            start_page=start_page,
            end_page=end_page,
            title_bbox=normalized_title_bbox,
            bounded_lines_by_page=bounded_lines_by_page,
            page_widths=page_widths,
            boundary_summary=boundary_summary,
            issue_codes=["CANDIDATE_STRUCTURE_LINES_REQUIRED"],
        )

    try:
        root_header, header_arbitration = _arbitrate_header_candidates(
            start_lines,
            float(page_widths[start_page]),
            parser_mode=header_parser_mode,
        )
        root_metadata, root_header_bottom = _header_metadata(
            start_lines,
            root_header,
            float(page_widths[start_page]),
        )
    except Exception as exc:
        return _unresolved_candidate_structure(
            candidate_namespace=candidate_namespace,
            note_identity=note_identity,
            table_identity=table_identity,
            start_page=start_page,
            end_page=end_page,
            title_bbox=normalized_title_bbox,
            bounded_lines_by_page=bounded_lines_by_page,
            page_widths=page_widths,
            boundary_summary=boundary_summary,
            issue_codes=[
                "HEADER_TOPOLOGY_UNRESOLVED",
                f"HEADER_PLANNER_ERROR:{type(exc).__name__}",
            ],
        )

    plans, _plans_by_page, _additional_columns = _plan_physical_table_segments(
        bounded_lines_by_page,
        page_widths,
        start_page=start_page,
        end_page=end_page,
        root_header=root_header,
        root_metadata=root_metadata,
        root_header_bottom=float(root_header_bottom),
        note_identity=str(note_identity or ""),
        table_identity=str(table_identity or ""),
        unit=unit,
    )
    ordered_segments = [
        {
            **plan["segment"].to_dict(),
            "plan_order": index,
            "signature_coverage": dict(
                plan.get("signature_coverage") or {}
            ),
            "structure_issue_codes": list(
                plan.get("structure_issue_codes") or []
            ),
        }
        for index, plan in enumerate(plans)
    ]
    if not ordered_segments:
        return _unresolved_candidate_structure(
            candidate_namespace=candidate_namespace,
            note_identity=note_identity,
            table_identity=table_identity,
            start_page=start_page,
            end_page=end_page,
            title_bbox=normalized_title_bbox,
            bounded_lines_by_page=bounded_lines_by_page,
            page_widths=page_widths,
            boundary_summary=boundary_summary,
            issue_codes=["PHYSICAL_TABLE_SEGMENT_REQUIRED"],
        )

    source_segments = {
        str(segment["segment_id"]): segment for segment in ordered_segments
    }
    invalid_relation_ids: set[str] = set()

    def root_segment_id(segment: dict[str, Any]) -> str:
        current = segment
        visited: set[str] = set()
        while str(current.get("classification") or "") == "CONTINUATION_SEGMENT":
            current_id = str(current.get("segment_id") or "")
            if current_id in visited:
                invalid_relation_ids.update(visited)
                return current_id
            visited.add(current_id)
            parent_id = str(current.get("continuation_of_segment_id") or "")
            if not parent_id or parent_id not in source_segments:
                invalid_relation_ids.add(current_id)
                return current_id
            current = source_segments[parent_id]
        return str(current.get("segment_id") or "")

    grouped_segments: dict[str, list[dict[str, Any]]] = {}
    root_order: list[str] = []
    for segment in ordered_segments:
        if str(segment.get("classification") or "") == "PEER_TABLE":
            continue
        root_id = root_segment_id(segment)
        if root_id not in grouped_segments:
            grouped_segments[root_id] = []
            root_order.append(root_id)
        grouped_segments[root_id].append(segment)

    confidence_scores = {"HIGH": 0.95, "MEDIUM": 0.75, "LOW": 0.4}
    logical_candidates: list[dict[str, Any]] = []
    segment_candidates: list[dict[str, Any]] = []
    issue_codes: list[str] = []

    for table_order, root_id in enumerate(root_order):
        members = sorted(
            grouped_segments[root_id],
            key=lambda item: int(item.get("plan_order") or 0),
        )
        root_segment = source_segments.get(root_id) or members[0]
        root_classification = str(root_segment.get("classification") or "UNRESOLVED")
        if root_id in invalid_relation_ids:
            root_classification = "UNRESOLVED"
        header_fingerprints = [
            str(member.get("header_topology_fingerprint") or "")
            for member in members
        ]
        period_labels = list(dict.fromkeys(
            str(period)
            for member in members
            for period in (member.get("period_labels") or [])
            if str(period)
        ))
        lane_counts = [len(member.get("anchor_ratios") or []) for member in members]
        logical_signature = {
            "header_fingerprints": header_fingerprints,
            "period_labels": period_labels,
            "amount_lane_counts": lane_counts,
            "segment_classifications": [
                str(member.get("classification") or "UNRESOLVED")
                for member in members
            ],
        }
        logical_id = _candidate_structure_id(
            "LTCAND",
            candidate_namespace,
            note_identity,
            root_segment.get("table_identity"),
            root_classification,
            logical_signature,
        )
        candidate_ids_by_source = {
            str(member["segment_id"]): _candidate_structure_id(
                "STCAND",
                logical_id,
                member["segment_id"],
                member.get("pdf_page_number"),
                member.get("bbox"),
                member.get("header_topology_fingerprint"),
            )
            for member in members
        }
        member_confidences = [
            confidence_scores.get(str(member.get("confidence") or "").upper(), 0.0)
            for member in members
        ]
        member_signature_complete = [
            bool(
                dict(member.get("signature_coverage") or {}).get("page_bbox")
                and dict(member.get("signature_coverage") or {}).get("period")
                and dict(member.get("signature_coverage") or {}).get("header")
                and dict(member.get("signature_coverage") or {}).get("amount_lanes")
                and str(
                    dict(member.get("signature_coverage") or {}).get("source")
                    or ""
                ).upper() == "BOUNDED_NATIVE_TEXT"
            )
            for member in members
        ]
        logical_review_required = bool(
            root_classification not in {"PRIMARY_TABLE", "SUPPLEMENTARY_TABLE"}
            or any(
                str(member.get("classification") or "") == "UNRESOLVED"
                for member in members
            )
            or any(str(member["segment_id"]) in invalid_relation_ids for member in members)
            or not all(member_signature_complete)
            or any(
                member.get("structure_issue_codes")
                for member in members
            )
        )
        if logical_review_required:
            issue_codes.append("TABLE_SEGMENT_RELATION_UNRESOLVED")
        if not all(member_signature_complete):
            issue_codes.append("TABLE_SEGMENT_SIGNATURE_INCOMPLETE")
        if any(member.get("structure_issue_codes") for member in members):
            issue_codes.extend(
                str(code)
                for member in members
                for code in (member.get("structure_issue_codes") or [])
            )
        page_boxes = [
            {
                "page": int(member["pdf_page_number"]),
                "bbox": {
                    "x0": float(member["bbox"][0]),
                    "y0": float(member["bbox"][1]),
                    "x1": float(member["bbox"][2]),
                    "y1": float(member["bbox"][3]),
                },
            }
            for member in members
        ]
        logical_candidates.append({
            "logical_table_candidate_id": logical_id,
            "table_order": table_order,
            "classification": root_classification,
            "proposed_classification": root_classification,
            "title": str(root_segment.get("table_identity") or table_identity),
            "start_page": min(int(member["pdf_page_number"]) for member in members),
            "end_page": max(int(member["pdf_page_number"]) for member in members),
            "bbox": {"pages": page_boxes},
            "signature": logical_signature,
            "evidence": {
                "source": "NATIVE_PDF_LINES",
                "note_identity": note_identity,
                "root_segment_id": root_id,
                "segment_count": len(members),
                "signature_coverage": {
                    "page_bbox": all(
                        dict(member.get("signature_coverage") or {}).get(
                            "page_bbox"
                        )
                        for member in members
                    ),
                    "period": all(
                        dict(member.get("signature_coverage") or {}).get(
                            "period"
                        )
                        for member in members
                    ),
                    "header": all(
                        dict(member.get("signature_coverage") or {}).get(
                            "header"
                        )
                        for member in members
                    ),
                    "amount_lanes": all(
                        dict(member.get("signature_coverage") or {}).get(
                            "amount_lanes"
                        )
                        for member in members
                    ),
                    "source": "BOUNDED_NATIVE_TEXT",
                },
            },
            "confidence": min(member_confidences, default=0.0),
            "status": "REVIEW_REQUIRED" if logical_review_required else "READY",
        })
        for segment_order, member in enumerate(members):
            source_id = str(member["segment_id"])
            source_parent_id = str(member.get("continuation_of_segment_id") or "")
            invalid_relation = source_id in invalid_relation_ids
            classification = str(member.get("classification") or "UNRESOLVED")
            confidence = confidence_scores.get(
                str(member.get("confidence") or "").upper(),
                0.0,
            )
            segment_candidates.append({
                "segment_candidate_id": candidate_ids_by_source[source_id],
                "logical_table_candidate_id": logical_id,
                "segment_order": segment_order,
                "classification": classification,
                "proposed_classification": classification,
                "start_page": int(member["pdf_page_number"]),
                "end_page": int(member["pdf_page_number"]),
                "bbox": {
                    "page": int(member["pdf_page_number"]),
                    "x0": float(member["bbox"][0]),
                    "y0": float(member["bbox"][1]),
                    "x1": float(member["bbox"][2]),
                    "y1": float(member["bbox"][3]),
                },
                "continuation_of_segment_candidate_id": (
                    candidate_ids_by_source.get(source_parent_id)
                    if source_parent_id and not invalid_relation
                    else None
                ),
                "period_signature": {
                    "period_labels": list(member.get("period_labels") or []),
                },
                "header_signature": {
                    "fingerprint": str(
                        member.get("header_topology_fingerprint") or ""
                    ),
                    "leaf_count": len(member.get("anchor_ratios") or []),
                    "labels": list(member.get("measure_labels") or []),
                },
                "amount_lane_signature": {
                    "lane_count": len(member.get("anchor_ratios") or []),
                    "anchor_ratios": list(member.get("anchor_ratios") or []),
                    "source_column_ordinals": list(
                        member.get("source_column_ordinals") or []
                    ),
                },
                "evidence": {
                    "source": "NATIVE_PDF_LINES",
                    "source_segment_id": source_id,
                    "candidate_relation": member.get("candidate_relation"),
                    "reason_codes": list(member.get("reason_codes") or []),
                    "consistency_audit": dict(
                        member.get("consistency_audit") or {}
                    ),
                    "unit": member.get("unit"),
                    "header_y0": member.get("header_y0"),
                    "header_y1": member.get("header_y1"),
                    "data_y_min": member.get("data_y_min"),
                    "data_y_max": member.get("data_y_max"),
                    "signature_coverage": dict(
                        member.get("signature_coverage") or {}
                    ),
                    "structure_issue_codes": list(
                        member.get("structure_issue_codes") or []
                    ),
                },
                "confidence": confidence,
                "status": (
                    "REVIEW_REQUIRED"
                    if (
                        invalid_relation
                        or classification == "UNRESOLVED"
                        or not member_signature_complete[segment_order]
                        or bool(member.get("structure_issue_codes"))
                    )
                    else "READY"
                ),
            })

    if not any(
        candidate["classification"] == "PRIMARY_TABLE"
        for candidate in logical_candidates
    ):
        issue_codes.append("PRIMARY_LOGICAL_TABLE_CANDIDATE_REQUIRED")
    if not boundary_summary["complete"]:
        issue_codes.append("TABLE_INVENTORY_BOUNDARY_UNRESOLVED")
    if any(
        candidate["classification"] == "UNRESOLVED"
        or candidate["status"] != "READY"
        for candidate in logical_candidates
    ):
        issue_codes.append("TABLE_INVENTORY_CLASSIFICATION_UNRESOLVED")
    issue_codes = list(dict.fromkeys(issue_codes))
    inventory_status = "COMPLETE" if not issue_codes else "INCOMPLETE"
    inventory_id = _candidate_structure_id(
        "NTINV",
        candidate_namespace,
        note_identity,
        table_identity,
        boundary_summary,
        [candidate["signature"] for candidate in logical_candidates],
    )
    return {
        "planner_version": _CANDIDATE_STRUCTURE_PLANNER_VERSION,
        "inventory_id": inventory_id,
        "inventory_status": inventory_status,
        "boundary_status": boundary_summary["status"],
        "boundary_evidence": boundary_summary,
        "header_arbitration": {
            "selected_parser": header_arbitration.get("selected_parser"),
            "selection_reason": header_arbitration.get("selection_reason"),
            "auto_abstain": bool(header_arbitration.get("auto_abstain")),
        },
        "logical_table_candidates": logical_candidates,
        "segment_candidates": segment_candidates,
        "issue_codes": issue_codes,
    }


def _active_physical_segment(
    segments: list[dict[str, Any]],
    line_y0: float,
) -> dict[str, Any] | None:
    matching = [
        segment
        for segment in segments
        if float(segment["segment_y0"]) <= float(line_y0) <= float(segment["segment_y1"])
    ]
    return matching[-1] if matching else None


def _scope_parent_count(
    lines:list[dict[str,Any]],
    header:dict[str,Any],
)->int:
    lo=max(0,int(header["line_index"])-8)
    hi=min(len(lines),int(header["line_index"])+6)
    scopes=[]
    for line in lines[lo:hi]:
        for w in line.get("words") or []:
            s=_scope_value(w["text"])
            if s and s not in scopes:
                scopes.append(s)
    return len(scopes)


def _candidate_arbitration_metrics(
    lines:list[dict[str,Any]],
    header:dict[str,Any],
    page_width:float,
)->dict[str,Any]:
    metadata,_=_header_metadata(lines,header,page_width)

    # Classic parser can carry restated hint inside the year-span itself.
    hints=header.get("restated_hints") or []
    for i,hint in enumerate(hints):
        if i<len(metadata) and hint:
            metadata[i]["restated"]=True
            token="已重述"
            if token not in metadata[i]["tokens"]:
                metadata[i]["tokens"].append(token)

    keys=[
        (
            str(m.get("year") or ""),
            str(m.get("scope") or ""),
            bool(m.get("restated")),
            str(m.get("measure") or ""),
        )
        for m in metadata
    ]
    duplicate_dimensions=len(keys)-len(set(keys))
    scope_coverage=sum(bool(m.get("scope")) for m in metadata)
    leaf_count=len(header.get("anchors") or [])

    primary_end_y=_primary_table_end_y(lines,header_y1=float(header["header_y1"]))
    numeric=_numeric_column_clusters(
        lines,
        header_y1=float(header["header_y1"]),
        page_width=page_width,
        body_end_y=primary_end_y,
    )
    numeric_count=int(numeric["count"])
    parent_scopes=_scope_parent_count(lines,header)

    hard_failures=[]
    if duplicate_dimensions>0:
        hard_failures.append("DUPLICATE_DIMENSION_KEYS")

    if numeric_count>=2:
        if leaf_count>numeric_count+1:
            hard_failures.append("HEADER_OVERSEGMENTATION_VS_NUMERIC_CLUSTERS")
        elif leaf_count<numeric_count:
            hard_failures.append("HEADER_UNDERSEGMENTATION_VS_NUMERIC_CLUSTERS")

    # With both 本集团 and 本公司, a 2-period table normally has leaf columns
    # divisible by 2. Odd/excessive cardinality is suspicious.
    if parent_scopes>=2 and leaf_count%parent_scopes!=0:
        hard_failures.append("HIERARCHICAL_CARDINALITY_MISMATCH")

    alignment=0
    if numeric_count and header.get("anchors"):
        tol=max(22.0,page_width*0.04)
        for a in header["anchors"]:
            if min(abs(float(a)-c) for c in numeric["centers"])<=tol:
                alignment+=1
    alignment_ratio=alignment/max(1,leaf_count)

    # Scoring is secondary to hard gates.
    score=50.0
    score+=20.0*alignment_ratio
    score+=10.0*(scope_coverage/max(1,leaf_count))
    if numeric_count==leaf_count and numeric_count>0:
        score+=20.0
    else:
        score-=8.0*abs(numeric_count-leaf_count) if numeric_count else 0
    score-=20.0*duplicate_dimensions
    score-=35.0*len(hard_failures)

    return {
        "parser":header.get("parser"),
        "leaf_count":leaf_count,
        "numeric_cluster_count":numeric_count,
        "numeric_clusters":numeric,
        "primary_table_end_y":primary_end_y,
        "parent_scope_count":parent_scopes,
        "scope_coverage":scope_coverage,
        "duplicate_dimension_count":duplicate_dimensions,
        "alignment_ratio":round(alignment_ratio,4),
        "hard_failures":hard_failures,
        "status":"REJECTED" if hard_failures else "VALID",
        "score":round(score,4),
        "columns_preview":[
            {
                "ordinal":i,
                "year":m.get("year"),
                "period_label":m.get("period_label"),
                "scope":m.get("scope"),
                "restated":bool(m.get("restated")),
                "header_raw":" | ".join(m.get("tokens") or []),
            }
            for i,m in enumerate(metadata)
        ],
    }


def _detect_header_candidates(
    lines:list[dict[str,Any]],
    page_width:float,
)->dict[str,dict[str,Any]]:
    out={}
    classic=_detect_header_classic(lines,page_width)
    generalized=_detect_header_generalized_wrapped(lines,page_width)
    if classic:
        out["ABSOLUTE_YEAR_CLASSIC"]=classic
    if generalized:
        out["GENERALIZED_PERIOD_V57"]=generalized
    return out


def _expand_repeated_measure_columns(lines: list[dict[str, Any]], header: dict[str, Any], page_width: float) -> dict[str, Any]:
    """Promote year-paired measures into leaf columns when geometry proves it.

    A management disclosure can have ``2023 / 2022`` on the first header row
    and ``账面值 / 占总额比例`` beneath each year.  Treating it as two columns
    loses two physical numeric axes, while merely disabling the referee would
    hide an ambiguity.  This bridge preserves all four axes and labels them.
    """
    numeric = _numeric_column_clusters(lines, header_y1=float(header["header_y1"]), page_width=page_width)
    original = list(header.get("anchors") or [])
    if len(original) < 1 or numeric["count"] < len(original):
        return header
    centers = [float(x) for x in numeric["centers"]]
    # Only accept a repeated-measure topology when nearby header text actually
    # names a measure at the discovered numeric centers.
    labels: list[str] = []
    label_bottoms: list[float] = []
    for center in centers:
        matches=[]
        for line in lines[max(0, int(header["line_index"]) - 1): min(len(lines), int(header["line_index"]) + 8)]:
            for word in line.get("words") or []:
                text=clean_cell(word.get("text", ""))
                norm=normalize_text(text)
                if (
                    any(normalize_text(token) in norm for token in _EXPLICIT_MEASURE_TOKENS)
                    and abs(float(word["xc"])-center) <= max(30.0, page_width*.045)
                ):
                    matches.append((text, float(word.get("y1", line.get("y1", 0.0)))))
        labels.append(matches[0][0] if matches else "")
        label_bottoms.append(matches[0][1] if matches else float(header["header_y1"]))
    # This promotion is deliberately narrow: it is for repeated *measures*
    # (e.g. 账面值 + 占比), not ordinary multi-year balance-sheet tables that
    # happen to mention a value/balance label once in their header.
    if not all(labels) or len({normalize_text(x) for x in labels}) < 2:
        return header
    # Map every physical axis back to the nearest period/header anchor.
    years=list(header.get("years") or [])
    periods=list(header.get("period_labels") or years)
    kinds=list(header.get("period_kinds") or ["ABSOLUTE_YEAR"]*len(original))
    restated=list(header.get("restated_hints") or [False]*len(original))
    expanded=dict(header)
    expanded.update({
        "anchors": centers,
        "years": [years[_nearest_anchor_index(x, original)] for x in centers],
        "period_labels": [periods[_nearest_anchor_index(x, original)] for x in centers],
        "period_kinds": [kinds[_nearest_anchor_index(x, original)] for x in centers],
        "restated_hints": [restated[_nearest_anchor_index(x, original)] for x in centers],
        "measure_labels": labels,
        "measure_expansion": "NUMERIC_AXIS_WITH_EXPLICIT_MEASURE_LABELS",
        "header_y1": max([float(header["header_y1"]), *label_bottoms]),
    })
    return expanded


def _period_measure_section_candidates(
    lines: list[dict[str, Any]],
    page_width: float,
) -> list[dict[str, Any]]:
    """Detect individual period bands with repeated measure columns."""
    sections: list[dict[str, Any]] = []
    for index, line in enumerate(lines[:120]):
        hits = _period_words_generalized(line)
        if len(hits) < 2:
            continue
        identities = {
            (
                str(hit.get("year") or ""),
                str(hit.get("period_label") or ""),
                str(hit.get("period_kind") or ""),
            )
            for hit in hits
        }
        if len(identities) != 1:
            continue
        header = {
            "parser": "STACKED_PERIOD_MEASURE",
            "line_index": index,
            "line": line,
            "anchors": [hit["xc"] for hit in hits],
            "years": [hit["year"] for hit in hits],
            "period_labels": [hit["period_label"] for hit in hits],
            "period_kinds": [hit["period_kind"] for hit in hits],
            "restated_hints": [False] * len(hits),
            "header_y0": line["y0"],
            "header_y1": line["y1"],
        }
        expanded = _expand_repeated_measure_columns(lines, header, page_width)
        labels = list(expanded.get("measure_labels") or [])
        if (
            len(labels) != len(expanded.get("anchors") or [])
            or len({normalize_text(label) for label in labels if label}) < 2
        ):
            continue
        sections.append(expanded)

    sections.sort(key=lambda item: float(item["header_y0"]))
    return sections


def _detect_stacked_period_measure_sections(
    lines: list[dict[str, Any]],
    page_width: float,
) -> list[dict[str, Any]]:
    """Detect vertically stacked period bands with repeated measure columns."""
    sections = _period_measure_section_candidates(lines, page_width)
    if len(sections) < 2:
        return []
    period_sequence = [
        str((section.get("period_labels") or [""])[0])
        for section in sections
    ]
    if len(set(period_sequence)) < 2:
        return []
    reference = [float(value) for value in sections[0]["anchors"]]
    tolerance = max(18.0, page_width * 0.035)
    aligned = all(
        len(section["anchors"]) == len(reference)
        and all(
            abs(float(anchor) - reference[position]) <= tolerance
            for position, anchor in enumerate(section["anchors"])
        )
        for section in sections[1:]
    )
    return sections if aligned else []


def _vertical_period_plan(
    lines_by_page: dict[int, list[dict[str, Any]]],
    page_widths: dict[int, float],
) -> tuple[list[dict[str, Any]], dict[int, list[dict[str, Any]]]]:
    occurrences: list[tuple[int, dict[str, Any], list[dict[str, Any]], float]] = []
    for page_no, lines in lines_by_page.items():
        page_width = float(page_widths[page_no])
        for header in _period_measure_section_candidates(lines, page_width):
            metadata, header_bottom = _header_metadata(lines, header, page_width)
            occurrences.append((page_no, header, metadata, header_bottom))

    period_identities = {
        tuple(
            (
                normalize_text(str(item.get("period_label") or item.get("year") or "")),
                str(item.get("period_kind") or ""),
            )
            for item in metadata
        )
        for _page_no, _header, metadata, _header_bottom in occurrences
    }
    if len(period_identities) < 2:
        return [], {}

    reference_page, reference_header, reference_metadata, _ = occurrences[0]
    reference_width = float(page_widths[reference_page])
    reference_ratios = [
        float(anchor) / reference_width
        for anchor in reference_header["anchors"]
    ]
    reference_measures = [
        normalize_text(str(item.get("measure") or ""))
        for item in reference_metadata
    ]
    tolerance_ratio = max(0.035, 18.0 / reference_width)
    for page_no, header, metadata, _header_bottom in occurrences[1:]:
        page_width = float(page_widths[page_no])
        ratios = [float(anchor) / page_width for anchor in header["anchors"]]
        measures = [
            normalize_text(str(item.get("measure") or ""))
            for item in metadata
        ]
        if (
            len(ratios) != len(reference_ratios)
            or measures != reference_measures
            or any(
                abs(ratio - reference_ratios[index]) > tolerance_ratio
                for index, ratio in enumerate(ratios)
            )
        ):
            return [], {}

    groups: list[dict[str, Any]] = []
    group_by_identity: dict[tuple[Any, ...], dict[str, Any]] = {}
    occurrences_by_page: dict[int, list[dict[str, Any]]] = {}
    for page_no, header, metadata, header_bottom in occurrences:
        period_identity = tuple(
            (
                normalize_text(str(item.get("period_label") or item.get("year") or "")),
                str(item.get("period_kind") or ""),
            )
            for item in metadata
        )
        measure_identity = tuple(
            normalize_text(str(item.get("measure") or ""))
            for item in metadata
        )
        identity = (period_identity, measure_identity)
        group = group_by_identity.get(identity)
        if group is None:
            section_index = len(groups)
            column_offset = sum(
                int(existing["column_count"])
                for existing in groups
            )
            group = {
                "section_index": section_index,
                "header": header,
                "anchors": list(header["anchors"]),
                "anchor_ratios": [
                    float(anchor) / float(page_widths[page_no])
                    for anchor in header["anchors"]
                ],
                "data_y_min": max(
                    float(header_bottom),
                    float(header["header_y1"]),
                ) + 2.0,
                "column_offset": column_offset,
                "column_count": len(metadata),
                "block_id": f"spatial_p{page_no}_period_{section_index + 1}",
                "period_labels": [
                    str(item.get("period_label") or item.get("year") or "")
                    for item in metadata
                ],
                "measure_labels": [str(item.get("measure") or "") for item in metadata],
                "metadata": metadata,
                "header_page": page_no,
                "header_y0": float(header["header_y0"]),
                "source_pages": [],
            }
            groups.append(group)
            group_by_identity[identity] = group
        if page_no not in group["source_pages"]:
            group["source_pages"].append(page_no)
        occurrences_by_page.setdefault(page_no, []).append({
            "section_index": int(group["section_index"]),
            "header": header,
            "anchors": list(header["anchors"]),
            "data_y_min": max(
                float(header_bottom),
                float(header["header_y1"]),
            ) + 2.0,
            "column_offset": int(group["column_offset"]),
            "column_count": int(group["column_count"]),
            "block_id": str(group["block_id"]),
            "period_labels": list(group["period_labels"]),
            "header_page": page_no,
            "header_source_page": None,
        })

    return groups, occurrences_by_page


def _vertical_sections_for_page(
    groups: list[dict[str, Any]],
    occurrences_by_page: dict[int, list[dict[str, Any]]],
    *,
    page_no: int,
    page_width: float,
    active_section_index: Optional[int],
) -> list[dict[str, Any]]:
    sections = list(occurrences_by_page.get(page_no, []))
    if groups and active_section_index is not None:
        active_group = groups[active_section_index]
        sections.insert(0, {
            "section_index": int(active_group["section_index"]),
            "header": {"header_y0": -1.0},
            "anchors": [
                float(ratio) * float(page_width)
                for ratio in active_group["anchor_ratios"]
            ],
            "data_y_min": 0.0,
            "column_offset": int(active_group["column_offset"]),
            "column_count": int(active_group["column_count"]),
            "block_id": str(active_group["block_id"]),
            "period_labels": list(active_group["period_labels"]),
            "header_page": int(active_group["header_page"]),
            "header_source_page": int(active_group["header_page"]),
        })
    return sections


def _plan_stacked_physical_table_segments(
    lines_by_page: dict[int, list[dict[str, Any]]],
    page_widths: dict[int, float],
    stacked_sections: list[dict[str, Any]],
    *,
    note_identity: str,
    table_identity: str,
    unit: str | None,
) -> tuple[list[dict[str, Any]], dict[int, list[dict[str, Any]]]]:
    """Expose one physical manifest segment for a vertically stacked table.

    Vertical period groups retain separate block IDs for value assignment, but
    they are one bounded physical disclosure when they share a page and amount
    axis.  Scope validation needs that physical evidence even though the row
    parser consumes each period group independently.
    """
    if not stacked_sections:
        return [], {}
    pages = {int(section.get("header_page") or 0) for section in stacked_sections}
    if len(pages) != 1 or 0 in pages:
        return [], {}

    from table_segment_classifier import classify_table_segment

    page_number = next(iter(pages))
    page_width = float(page_widths[page_number])
    ordered = sorted(
        stacked_sections,
        key=lambda section: float(section.get("header_y0") or 0.0),
    )
    first = ordered[0]
    first_header = dict(first.get("header") or {})
    anchors = [float(value) for value in first.get("anchors") or []]
    metadata = list(first.get("metadata") or [])
    source_ordinals = list(
        range(
            int(first.get("column_offset") or 0),
            int(first.get("column_offset") or 0)
            + int(first.get("column_count") or len(metadata)),
        )
    )
    if not anchors or not source_ordinals:
        return [], {}

    segment_y0 = min(
        float(section.get("header_y0") or 0.0) for section in ordered
    )
    body_bottoms: list[float] = []
    for index, section in enumerate(ordered):
        section_start = float(section.get("data_y_min") or 0.0)
        section_end = (
            float(ordered[index + 1].get("header_y0"))
            if index + 1 < len(ordered)
            else max(
                (float(line.get("y1", 0.0)) for line in lines_by_page[page_number]),
                default=section_start,
            )
        )
        section_anchors = [float(value) for value in section.get("anchors") or []]
        tolerance = max(18.0, page_width * 0.035)
        matched = []
        for line in lines_by_page[page_number]:
            line_y0 = float(line.get("y0", 0.0))
            if not (line_y0 >= section_start and line_y0 < section_end):
                continue
            if _report_page_chrome_role(line, max(
                (float(item.get("y1", 0.0)) for item in lines_by_page[page_number]),
                default=0.0,
            )):
                continue
            centers = _line_numeric_lane_centers(line, page_width)
            if any(
                abs(center - anchor) <= tolerance
                for center in centers
                for anchor in section_anchors
            ):
                matched.append(float(line.get("y1", line_y0)))
        if matched:
            body_bottoms.append(max(matched))

    segment_y1 = max(
        (float(line.get("y1", 0.0)) for line in lines_by_page[page_number]),
        default=max(body_bottoms or [segment_y0]),
    )
    headers = [" | ".join(item.get("tokens") or []) for item in metadata]
    period_labels = [
        str(item.get("period_label") or item.get("year") or "")
        for item in metadata
        if item.get("period_label") or item.get("year")
    ]
    measure_labels = [
        str(item.get("measure") or "")
        for item in metadata
        if str(item.get("measure") or "").strip()
    ]
    anchor_ratios = [value / page_width for value in anchors]
    segment_id = _stable_physical_segment_id(
        note_identity,
        table_identity,
        page_number,
        segment_y0,
        0,
    )
    segment = classify_table_segment(
        segment_id,
        page_number,
        (0.0, segment_y0, page_width, segment_y1),
        note_identity,
        table_identity,
        [table_identity],
        headers,
        anchor_ratios=anchor_ratios,
        source_column_ordinals=source_ordinals,
        period_labels=period_labels,
        measure_labels=measure_labels,
        unit=unit,
        independent_header=False,
        narrative_separator=False,
        local_total_before=False,
        page_adjacent=None,
        header_y0=float(first_header.get("header_y0") or segment_y0),
        header_y1=float(first_header.get("header_y1") or first.get("data_y_min") or segment_y0),
        data_y_min=float(first.get("data_y_min") or segment_y0),
        data_y_max=segment_y1,
    )
    plan = {
        "segment": segment,
        "segment_id": segment.segment_id,
        "anchors": anchors,
        "anchor_ratios": anchor_ratios,
        "metadata": metadata,
        "source_column_ordinals": source_ordinals,
        "column_offset": min(source_ordinals, default=0),
        "column_count": len(source_ordinals),
        "segment_y0": segment_y0,
        "segment_y1": segment_y1,
        "data_y_min": float(first.get("data_y_min") or segment_y0),
        "header_source_page": None,
    }
    return [plan], {page_number: [plan]}


def _active_vertical_section(
    sections: list[dict[str, Any]],
    line_y0: float,
) -> Optional[dict[str, Any]]:
    eligible = [
        section
        for section in sections
        if float(line_y0) >= float(section["header"]["header_y0"])
    ]
    return eligible[-1] if eligible else None


def _arbitrate_header_candidates(
    lines:list[dict[str,Any]],
    page_width:float,
    parser_mode:str="AUTO",
)->tuple[dict[str,Any],dict[str,Any]]:
    candidates={
        name: _expand_repeated_measure_columns(lines, header, page_width)
        for name, header in _detect_header_candidates(lines,page_width).items()
    }
    if not candidates:
        raise ValueError("未识别到任何可用表头候选。")

    metrics={
        name:_candidate_arbitration_metrics(lines,h,page_width)
        for name,h in candidates.items()
    }

    mode=str(parser_mode or "AUTO").upper()
    aliases={
        "CLASSIC":"ABSOLUTE_YEAR_CLASSIC",
        "ABSOLUTE":"ABSOLUTE_YEAR_CLASSIC",
        "GENERALIZED":"GENERALIZED_PERIOD_V57",
        "V57":"GENERALIZED_PERIOD_V57",
    }
    mode=aliases.get(mode,mode)

    auto_selected=None
    valid=[m for m in metrics.values() if m["status"]=="VALID"]
    if valid:
        # If explicit absolute years exist and Classic is valid, give a small
        # stability prior without overriding objective topology evidence.
        for m in valid:
            if m["parser"]=="ABSOLUTE_YEAR_CLASSIC":
                m["_selection_score"]=m["score"]+3.0
            else:
                m["_selection_score"]=m["score"]
        auto_selected=max(valid,key=lambda m:m["_selection_score"])["parser"]
    else:
        # Do not pretend confidence: choose best diagnostic candidate but mark abstain.
        auto_selected=max(metrics.values(),key=lambda m:m["score"])["parser"]

    if mode!="AUTO":
        if mode not in candidates:
            raise ValueError(
                f"HEADER_PARSER_OVERRIDE_UNAVAILABLE：指定 {mode}，但该算法没有产生可用表头候选。"
            )
        selected=mode
        selection_reason="HUMAN/USER_PARSER_OVERRIDE"
    else:
        selected=auto_selected
        selection_reason=(
            "AUTO_VALIDATED_SELECTION"
            if metrics[selected]["status"]=="VALID"
            else "AUTO_ABSTAIN_BEST_DIAGNOSTIC_CANDIDATE"
        )

    arbitration={
        "mode":mode,
        "auto_selected_parser":auto_selected,
        "selected_parser":selected,
        "selection_reason":selection_reason,
        "auto_abstain":not any(m["status"]=="VALID" for m in metrics.values()),
        "candidates":metrics,
    }

    if mode=="AUTO" and arbitration["auto_abstain"]:
        raise ValueError(
            "HEADER_TOPOLOGY_REVIEW_REQUIRED：Classic 与 Generalized 表头候选均未通过独立拓扑裁判。"
            f" 候选诊断={metrics}"
        )

    return candidates[selected],arbitration


def _detect_header(
    lines:list[dict[str,Any]],
    page_width:float,
    parser_mode:str="AUTO",
)->Optional[dict[str,Any]]:
    """Backward-compatible detector returning the arbitrated header only."""
    try:
        header,_=_arbitrate_header_candidates(lines,page_width,parser_mode=parser_mode)
        return header
    except Exception:
        return None


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
    strict_target_identity: bool = False,
    certified_target_heading: Optional[str] = None,
    certified_segments: Sequence[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    doc = fitz.open(str(pdf_path))
    note_reference_raw = str(note_number).strip() if note_number else None
    from table_boundary_resolver import (
        BoundaryReason,
        parse_note_ordinal,
        resolve_table_boundary,
    )
    parsed_note_ordinal = parse_note_ordinal(note_reference_raw)
    note_number = str(parsed_note_ordinal) if parsed_note_ordinal is not None else note_reference_raw
    certified_page_bboxes = _certified_segment_page_bboxes(certified_segments)
    certified_bbox_pages = sorted(certified_page_bboxes)
    if certified_bbox_pages:
        if start_page_override and int(start_page_override) not in certified_page_bboxes:
            doc.close()
            raise ValueError("CERTIFIED_SEGMENT_PAGE_MISMATCH")
        for page in certified_bbox_pages:
            if page > doc.page_count:
                doc.close()
                raise ValueError("CERTIFIED_SEGMENT_BBOX_PAGE_OUT_OF_RANGE")

    best = None
    identity_source = "TITLE"
    if start_page_override:
        p = int(start_page_override)
        if p < 1 or p > doc.page_count:
            doc.close()
            raise ValueError(f"起始页超出PDF范围：{p}")
        lines = _page_lines(doc, p)
        # Prefer an actual matching title line on the override page; otherwise top.
        candidates = []
        for index, line in enumerate(lines):
            variants = [line]
            # Do not merge an already complete note title with the period line.
            # In many Chinese notes the period header sits immediately below the
            # title.  Merging it makes ``start_y`` fall after the year columns,
            # so the ROI has values but no recoverable header (notably notes 11
            # and 12 in the Ping An 2023 financial-investment appendix).
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
            if index + 1 < len(lines) and not current_has_query:
                merged = dict(line)
                merged["text"] = str(line.get("text") or "") + str(lines[index + 1].get("text") or "")
                merged["y1"] = lines[index + 1]["y1"]
                variants.append(merged)
            for variant in variants:
                score = _title_score(variant["text"], table_query, note_number)
                if strict_target_identity:
                    matched = _match_note_heading(variant["text"], note_number)
                    if note_number:
                        if not matched or not _title_query_compatible(matched[1], table_query):
                            continue
                    else:
                        # Direct-disclosure tables often have no numeric note
                        # reference.  Their certified identity is therefore a
                        # concrete page plus a literal subtable query; do not
                        # require the unrelated "附注 n" grammar here.
                        if _line_compact(table_query) not in _line_compact(variant["text"]):
                            continue
                    if certified_target_heading:
                        certified_compact = _line_compact(certified_target_heading)
                        actual_compact = _line_compact(variant["text"])
                        query_compact = _line_compact(table_query)
                        if (
                            query_compact not in actual_compact
                            and actual_compact not in certified_compact
                            and certified_compact not in actual_compact
                        ):
                            continue
                candidates.append((score, variant))
        candidates = [x for x in candidates if x[0] > 0]
        if strict_target_identity and not candidates:
            if not certified_page_bboxes:
                doc.close()
                raise ValueError(
                    "CERTIFIED_TARGET_HEADING_MISMATCH：认证页中未找到匹配的"
                    f"附注标题（note={note_reference_raw}, table={table_query}）。"
                )
            bbox = certified_page_bboxes[p]
            title_line = {
                "text": certified_target_heading or table_query,
                "y0": bbox["y0"],
                "y1": bbox["y0"],
                "x0": bbox["x0"],
                "x1": bbox["x1"],
            }
            identity_source = "CERTIFIED_BBOX"
        else:
            title_line = max(candidates, key=lambda x: x[0])[1] if candidates else {
                "text": table_query, "y0": 0.0, "y1": 0.0, "x0": 0.0,
            }
        best = (999, p, title_line)
    else:
        search_pages = (
            certified_bbox_pages
            if certified_bbox_pages
            else range(1, doc.page_count + 1)
        )
        for p in search_pages:
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

    if best is None and strict_target_identity and certified_page_bboxes:
        first_page = certified_bbox_pages[0]
        bbox = certified_page_bboxes[first_page]
        best = (
            999,
            first_page,
            {
                "text": certified_target_heading or table_query,
                "y0": bbox["y0"],
                "y1": bbox["y0"],
                "x0": bbox["x0"],
                "x1": bbox["x1"],
            },
        )
        identity_source = "CERTIFIED_BBOX"
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

    boundary = resolve_table_boundary(
        note_reference=note_reference_raw or resolved_note_number,
        title=located_title,
        start_page=start_page,
        start_y=start_y,
        title_x0=float(title_line.get("x0", 0.0)),
        page_count=doc.page_count,
        page_height=lambda page: float(doc[page - 1].rect.height),
        page_lines=lambda page: _page_lines(doc, page),
        max_pages=max_pages,
        lookahead_pages=1 if strict_target_identity else 0,
    )
    end_page = int(boundary["end_page"])
    end_y = float(boundary["end_y"])
    boundary_reason = str(boundary["boundary_reason"])

    if certified_page_bboxes:
        start_page = certified_bbox_pages[0]
        end_page = certified_bbox_pages[-1]
        start_y = certified_page_bboxes[start_page]["y0"]
        end_y = certified_page_bboxes[end_page]["y1"]
        boundary_reason = BoundaryReason.CERTIFIED_SEGMENT_BBOX.value
        identity_source = "CERTIFIED_BBOX"

    page_heights = {p: float(doc[p - 1].rect.height) for p in range(start_page, end_page + 1)}
    page_widths = {p: float(doc[p - 1].rect.width) for p in range(start_page, end_page + 1)}
    printed_page_numbers: dict[int, list[int]] = {}
    for p in range(start_page, end_page + 1):
        numbers = []
        for line in _page_lines(doc, p):
            token = str(line.get("text") or "").strip()
            if token.isdigit() and len(token) <= 3:
                numbers.append(int(token))
        if numbers:
            printed_page_numbers[p] = numbers
    amount_column_x_centers = []
    for line in _page_lines(doc, start_page):
        text = str(line.get("text") or "").strip()
        if re.search(r"\d{4}\s*年", text):
            amount_column_x_centers.append(
                (float(line.get("x0", 0.0)) + float(line.get("x1", 0.0))) / 2.0
            )
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
        "boundary_confidence": boundary["boundary_confidence"],
        "boundary_evidence": boundary["boundary_evidence"],
        "page_heights": page_heights,
        "page_widths": page_widths,
        "printed_page_numbers": printed_page_numbers,
        "amount_column_x_centers": amount_column_x_centers,
        "certified_page_bboxes": certified_page_bboxes,
        "certified_roi_row_membership_semantics": (
            CERTIFIED_ROI_ROW_MEMBERSHIP_SEMANTICS
            if certified_page_bboxes else None
        ),
        "identity_source": identity_source,
    }


def _mark_tail_page_number_noise(
    rows: list[TableRow],
    roi: dict[str, Any],
) -> None:
    """Mark layout-noise rows after a confirmed terminal total as page numbers.

    Conditions are deliberately composite so real amounts / note ordinals /
    second subtables are never deleted: the row must sit after the last
    terminal row, carry no label, hold exactly one short integer token, lie in
    the bottom page region and match the page's printed page number.  The
    printed-page match is the decisive gate: real page numbers may sit directly
    under an amount column, so x-overlap alone must never veto a token that
    matches the printed page number.  The raw row is retained verbatim; it is
    only excluded from topology / terminal-row / merge logic.
    """
    page_heights = roi.get("page_heights") or {}
    printed = roi.get("printed_page_numbers") or {}

    terminal_idx: int | None = None
    for i in range(len(rows) - 1, -1, -1):
        row = rows[i]
        if getattr(row, "excluded_from_table_logic", False):
            continue
        role = str(row.row_role or row.row_type or "").upper()
        label = str(
            row.raw_item or row.row_item_raw or row.normalized_item or ""
        ).strip()
        if role == "TOTAL" or label in {"合计", "总计", "资产合计", "负债合计"}:
            terminal_idx = i
            break
    if terminal_idx is None:
        return

    for row in rows[terminal_idx + 1:]:
        if getattr(row, "excluded_from_table_logic", False):
            continue
        label = str(row.raw_item or row.row_item_raw or "").strip()
        if label:
            continue
        cells = list(row.cells or [])
        if len(cells) != 1:
            continue
        token = str(cells[0].raw or "").strip()
        if not token.isdigit() or not (1 <= len(token) <= 3):
            continue
        bbox = row.bbox or {}
        y0 = float(bbox.get("y0", bbox.get("top", 0.0)) or 0.0)
        height = float((page_heights or {}).get(int(row.page or 0), 0.0) or 0.0)
        if height <= 0 or y0 <= height * 0.9:
            continue  # 不在页面底部 footer 区域
        page_nums = {int(x) for x in (printed or {}).get(int(row.page or 0), [])}
        if not page_nums or int(token) not in page_nums:
            continue  # 必须有印刷页码匹配，否则保守不标
        row.row_role = "PAGE_NUMBER_NOISE"
        row.excluded_from_table_logic = True


def _mark_side_page_number_noise(
    rows: list[TableRow],
    roi: dict[str, Any],
) -> None:
    """Mark side-margin printed page numbers (e.g. 新华年报 “07”) as noise.

    These tokens sit at the left/right page margin (outside the table x-band),
    carry no label, hold exactly one short integer and match the page's
    printed page number.  Unlike tail page numbers they may appear mid-table,
    so this classifier does not require a terminal row.  The raw row is
    retained verbatim; it is only excluded from table logic.
    """
    page_widths = roi.get("page_widths") or {}
    printed = roi.get("printed_page_numbers") or {}
    active = [r for r in rows if not getattr(r, "excluded_from_table_logic", False)]
    data_rows = [
        r for r in active
        if str(r.raw_item or r.row_item_raw or "").strip()
        or len(list(r.cells or [])) > 1
    ]
    if not data_rows:
        return
    band_x0 = min(
        float((r.bbox or {}).get("x0", 0.0) or 0.0) for r in data_rows
    )
    band_x1 = max(
        float((r.bbox or {}).get("x1", 0.0) or 0.0) for r in data_rows
    )

    for row in rows:
        if getattr(row, "excluded_from_table_logic", False):
            continue
        label = str(row.raw_item or row.row_item_raw or "").strip()
        if label:
            continue
        cells = list(row.cells or [])
        if len(cells) != 1:
            continue
        token = str(cells[0].raw or "").strip()
        if not token.isdigit() or not (1 <= len(token) <= 3):
            continue
        bbox = row.bbox or {}
        x0 = float(bbox.get("x0", 0.0) or 0.0)
        x1 = float(bbox.get("x1", 0.0) or 0.0)
        width = float((page_widths or {}).get(int(row.page or 0), 0.0) or 0.0)
        if width <= 0:
            continue
        in_side_margin = x1 <= 40.0 or x0 >= width - 40.0
        if not in_side_margin:
            continue
        outside_band = x1 < band_x0 - 10.0 or x0 > band_x1 + 10.0
        if not outside_band:
            continue
        page_nums = {int(x) for x in (printed or {}).get(int(row.page or 0), [])}
        if not page_nums or int(token) not in page_nums:
            continue  # 必须有印刷页码匹配，否则保守不标
        row.row_role = "PAGE_NUMBER_NOISE"
        row.excluded_from_table_logic = True


def _mark_report_footer_noise(rows: list[TableRow]) -> None:
    """Exclude full annual-report footer labels while retaining raw evidence."""
    for row in rows:
        if getattr(row, "excluded_from_table_logic", False) or row.cells:
            continue
        label = _line_compact(
            str(row.raw_item or row.row_item_raw or row.normalized_item or "")
        )
        if not _REPORT_FOOTER_RE.fullmatch(label):
            continue
        row.row_role = "PAGE_FOOTER_NOISE"
        row.row_type = "PAGE_FOOTER_NOISE"
        row.excluded_from_table_logic = True


def _report_page_chrome_role(
    line: dict[str, Any],
    page_height: float,
) -> Optional[str]:
    """Classify annual-report running headers/footers before amount parsing.

    A running header can place the report year and printed page number inside
    the same amount-column band.  The semantic report marker plus a strict
    physical page-edge gate distinguishes it from table period/data rows.
    """
    compact = _line_compact(str(line.get("text") or ""))
    if page_height <= 0:
        return None
    edge_band = max(48.0, page_height * 0.08)
    marker_edge_band = max(edge_band, page_height * 0.12)
    navigation_hits = sum(
        token in compact for token in _REPORT_NAVIGATION_CHROME_TOKENS
    )
    if navigation_hits >= 3 and float(line.get("y1", 0.0) or 0.0) <= edge_band:
        return "PAGE_HEADER_NOISE"
    if not (
        _REPORT_PAGE_CHROME_MARKER_RE.search(compact)
        or _REPORT_FOOTER_RE.fullmatch(compact)
    ):
        return None
    if float(line.get("y1", 0.0) or 0.0) <= edge_band:
        return "PAGE_HEADER_NOISE"
    footer_band = marker_edge_band if _REPORT_PAGE_CHROME_MARKER_RE.search(compact) else edge_band
    if float(line.get("y0", 0.0) or 0.0) >= page_height - footer_band:
        return "PAGE_FOOTER_NOISE"
    return None


def _lines_in_roi(
    doc: fitz.Document,
    roi: dict[str, Any],
    page_no: int,
) -> list[dict[str, Any]]:
    lines = _page_lines(doc, page_no)
    height = float(doc[page_no - 1].rect.height)
    y0 = roi["start_y"] if page_no == roi["start_page"] else 0.0
    y1 = roi["end_y"] if page_no == roi["end_page"] else height
    page_bboxes = roi.get("certified_page_bboxes") or {}
    page_bbox = page_bboxes.get(page_no) or page_bboxes.get(str(page_no))
    x0 = 0.0
    x1 = float(doc[page_no - 1].rect.width)
    if isinstance(page_bbox, dict):
        y0 = max(y0, float(page_bbox.get("y0", y0)))
        y1 = min(y1, float(page_bbox.get("y1", y1)))
        x0 = max(x0, float(page_bbox.get("x0", x0)))
        x1 = min(x1, float(page_bbox.get("x1", x1)))
        certified_bbox = {"x0": x0, "y0": y0, "x1": x1, "y1": y1}
        return [
            line for line in lines
            if belongs_to_certified_roi(line, certified_bbox)
        ]
    return [
        line for line in lines
        if line["y1"] >= y0
        and line["y0"] <= y1
        and line["x1"] >= x0
        and line["x0"] <= x1
    ]


def _year_words(line: dict[str, Any]) -> list[dict[str, Any]]:
    # Backward-compatible name: now returns all recognized period leaf headers.
    return _period_words(line)


def _detect_header_generalized(
    lines: list[dict[str, Any]],
    page_width: float,
) -> Optional[dict[str, Any]]:
    candidates = []
    for i, line in enumerate(lines[:100]):
        hits = _period_words_generalized(line)
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
    return bool(s) and all(ch in "()（）-—–－" for ch in s)


def _is_explicit_amount_placeholder(text: str) -> bool:
    compact = re.sub(r"\s+", "", clean_cell(text))
    return compact in {"不适用", "不適用"} or compact.upper() in {"N/A", "N／A"}


def _joined_explicit_placeholder_words(
    words: list[dict[str, Any]],
) -> list[tuple[set[int], dict[str, Any]]]:
    """Join OCR-split placeholder glyphs without promoting arbitrary prose.

    Tesseract commonly emits ``不`` and ``适用`` as separate words.  A legal
    placeholder is reconstructed only from adjacent, vertically overlapping
    fragments whose complete joined text matches the closed placeholder
    vocabulary.  Partial prefixes never become cells on their own.
    """
    ordered = sorted(enumerate(words), key=lambda item: float(item[1]["x0"]))
    accepted: list[tuple[set[int], dict[str, Any]]] = []
    consumed: set[int] = set()
    valid_targets = {"不适用", "不適用", "N/A", "N／A"}
    for position, (source_index, first) in enumerate(ordered):
        if source_index in consumed:
            continue
        fragments: list[tuple[int, dict[str, Any]]] = []
        compact = ""
        previous: dict[str, Any] | None = None
        for next_index, word in ordered[position:position + 4]:
            if next_index in consumed:
                break
            token = re.sub(r"\s+", "", clean_cell(word.get("text", "")))
            candidate = compact + token
            if not candidate or not any(target.startswith(candidate) for target in valid_targets):
                break
            if previous is not None:
                overlap = min(float(previous["y1"]), float(word["y1"])) - max(
                    float(previous["y0"]), float(word["y0"])
                )
                shorter = min(
                    float(previous["y1"]) - float(previous["y0"]),
                    float(word["y1"]) - float(word["y0"]),
                )
                gap = float(word["x0"]) - float(previous["x1"])
                if overlap < shorter * 0.6 or gap > shorter * 1.25:
                    break
            fragments.append((next_index, word))
            compact = candidate
            previous = word
            if compact in valid_targets:
                indexes = {index for index, _ in fragments}
                composite = {
                    "text": compact,
                    "x0": min(float(item["x0"]) for _, item in fragments),
                    "y0": min(float(item["y0"]) for _, item in fragments),
                    "x1": max(float(item["x1"]) for _, item in fragments),
                    "y1": max(float(item["y1"]) for _, item in fragments),
                }
                composite["xc"] = (composite["x0"] + composite["x1"]) / 2.0
                composite["yc"] = (composite["y0"] + composite["y1"]) / 2.0
                accepted.append((indexes, composite))
                consumed.update(indexes)
                break
    return accepted


def _is_numeric_fragment(text: str) -> bool:
    s = re.sub(r"\s+", "", str(text))
    if not s:
        return False
    allowed = set("0123456789,.-—–－()（）%％")
    return all(ch in allowed for ch in s) and any(ch.isdigit() for ch in s)


def _is_strict_ocr_numeric_confusion(text: str) -> bool:
    compact = re.sub(r"\s+", "", str(text or ""))
    return bool(re.fullmatch(r"A\d{2}(?:,\d{3})+", compact))


def _join_numeric_fragments(words: list[dict[str, Any]]) -> str:
    if not words:
        return ""
    parts = [w["text"].strip() for w in sorted(words, key=lambda x: x["x0"])]
    s = "".join(parts)
    s = s.replace("％", "%").replace("，", ",").replace("．", ".")
    compact = re.sub(r"\s+", "", s)
    # Strict OCR glyph repair: a leading ``4`` in a thousands-grouped amount
    # is occasionally emitted as Latin ``A``.  The correction is accepted
    # only for a complete comma-grouped numeric token; arbitrary alphanumeric
    # strings remain unparseable and fail closed.
    if re.fullmatch(r"A\d{2}(?:,\d{3})+", compact):
        compact = "4" + compact[1:]
    return compact


def _extract_unit(lines: list[dict[str, Any]]) -> Optional[str]:
    for line in lines:
        text = clean_cell(line["text"])
        # A data/prose line may contain “人民币26百万元”; it is not a table
        # context declaration and must never override inherited document unit.
        m = _UNIT_DECL_RE.search(re.sub(r"\s+", "", text))
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
    Bind parent/group headers to child leaf columns.

    v5.9:
    - With >=2 distinct parent headers (e.g. 本集团 / 本公司), assign anchors by
      Voronoi/midpoint regions between parent centers. This is robust when a
      restated leaf label is visually wider and shifts its own center.
    - With one parent hit, retain conservative distance gating.
    """
    if not hits:
        return {}

    # Deduplicate same semantic parent hits.
    dedup=[]
    for h in sorted(hits,key=lambda x:x["xc"]):
        if any(
            h.get("scope")==old.get("scope")
            and abs(float(h["xc"])-float(old["xc"]))<=12
            for old in dedup
        ):
            continue
        dedup.append(h)
    hits=dedup

    assigned: dict[int, dict[str, Any]] = {}
    if len(hits)>=2:
        centers=[float(h["xc"]) for h in hits]
        boundaries=[
            (centers[i]+centers[i+1])/2
            for i in range(len(centers)-1)
        ]
        for i,anchor in enumerate(anchors):
            region=0
            while region<len(boundaries) and float(anchor)>boundaries[region]:
                region+=1
            region=min(region,len(hits)-1)
            hit=hits[region]
            distance=abs(float(anchor)-float(hit["xc"]))
            local_gap=_anchor_local_gap(anchors,i,page_width)
            threshold=max(28.0,local_gap*0.90)
            if distance<=threshold:
                assigned[i]=hit
        return assigned

    nearest=hits[0]
    nearest_index=_nearest_anchor_index(float(nearest["xc"]),anchors)
    nearest_distance=abs(float(anchors[nearest_index])-float(nearest["xc"]))
    nearest_gap=_anchor_local_gap(anchors,nearest_index,page_width)
    if nearest_distance<=max(12.0,nearest_gap*0.35):
        return {nearest_index:nearest}
    for i,anchor in enumerate(anchors):
        distance=abs(float(anchor)-float(nearest["xc"]))
        local_gap=_anchor_local_gap(anchors,i,page_width)
        threshold=max(28.0,local_gap*0.90)
        if distance<=threshold:
            assigned[i]=nearest
    return assigned


def _assign_leaf_header_hits(
    anchors:list[float],
    hits:list[dict[str,Any]],
    page_width:float,
)->dict[int,dict[str,Any]]:
    """One-to-one-ish binding for leaf annotations such as 已重述."""
    assigned={}
    if not hits:
        return assigned
    half=_column_half_widths(anchors,page_width)
    for hit in hits:
        idx=_nearest_anchor_index(float(hit["xc"]),anchors)
        if abs(float(hit["xc"])-float(anchors[idx]))<=half[idx]*1.45:
            # Prefer the hit closest to the anchor if multiple compete.
            old=assigned.get(idx)
            if old is None or abs(float(hit["xc"])-anchors[idx])<abs(float(old["xc"])-anchors[idx]):
                assigned[idx]=hit
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
    measure_labels = header.get("measure_labels", [""] * len(anchors))
    half = _column_half_widths(anchors, page_width)
    metadata = [
        {
            "year": years[i],
            "period_label": period_labels[i],
            "period_kind": period_kinds[i],
            "scope": None,
            "restated": False,
            "measure": measure_labels[i] if i < len(measure_labels) else "",
            "tokens": [x for x in [period_labels[i], measure_labels[i] if i < len(measure_labels) else ""] if x],
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
        # Parent scopes/restatement markers belong immediately around the
        # header.  A later footnote can say “本集团” as ordinary prose; letting
        # that reach this pass makes the footnote look like a header extension
        # and can discard every real data row before it.
        if line["y0"] > header["header_y1"] + 42:
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
            assignments = _assign_leaf_header_hits(anchors, restated_hits, page_width)
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


def _numeric_amount_clusters(
    fragments: list[dict[str, Any]],
    page_width: float,
) -> list[list[dict[str, Any]]]:
    if not fragments:
        return []
    ordered = sorted(
        fragments,
        key=lambda word: (float(word.get("x0", 0.0)), float(word.get("x1", 0.0))),
    )
    adjacency_tolerance = max(6.0, page_width * 0.008)
    clusters: list[list[dict[str, Any]]] = [[ordered[0]]]
    for word in ordered[1:]:
        previous = clusters[-1][-1]
        gap = float(word.get("x0", 0.0)) - float(previous.get("x1", 0.0))
        punctuation_bridge = (
            _is_numeric_punct(str(word.get("text", "")))
            or _is_numeric_punct(str(previous.get("text", "")))
        )
        if gap <= adjacency_tolerance * (2.0 if punctuation_bridge else 1.0):
            clusters[-1].append(word)
        else:
            clusters.append([word])
    return [cluster for cluster in clusters if any(
        clean_cell(word.get("text", "")) for word in cluster
    )]


def _line_to_spatial_cells(
    line: dict[str, Any],
    anchors: list[float],
    page_width: float,
    *,
    numeric_anchors: list[float] | None = None,
) -> dict[str, Any]:
    # Keep the certified/header anchors as the column identity and ordinal
    # source.  A separate, independently validated body lane may be used for
    # assigning right-aligned amount words whose centres do not coincide with
    # the wider year-label text boxes.
    assignment_anchors = (
        [float(value) for value in numeric_anchors]
        if numeric_anchors is not None
        and len(numeric_anchors) == len(anchors)
        else [float(value) for value in anchors]
    )
    half = _column_half_widths(assignment_anchors, page_width)
    numeric_groups: list[list[dict[str, Any]]] = [[] for _ in assignment_anchors]
    assigned_ids = set()

    # Numeric region begins well to the left of the first anchor, but not inside labels.
    if len(assignment_anchors) > 1:
        first_gap = assignment_anchors[1] - assignment_anchors[0]
    else:
        first_gap = page_width * 0.25
    assignment_left = assignment_anchors[0] - first_gap * 0.55
    if len(anchors) > 1:
        header_gap = float(anchors[1]) - float(anchors[0])
    else:
        header_gap = page_width * 0.25
    header_left = float(anchors[0]) - header_gap * 0.55
    # Keep the numeric region wide enough for a body lane that is shifted
    # relative to centred header text, while retaining a broad label-side
    # guard.  Chinese labels are not numeric fragments and remain excluded.
    numeric_left = max(page_width * 0.25, min(assignment_left, header_left))

    for source_indexes, placeholder in _joined_explicit_placeholder_words(
        list(line["words"])
    ):
        if float(placeholder["xc"]) < numeric_left:
            continue
        idx = _nearest_anchor_index(float(placeholder["xc"]), assignment_anchors)
        if abs(float(placeholder["xc"]) - assignment_anchors[idx]) <= half[idx] * 1.5:
            numeric_groups[idx].append(placeholder)
            assigned_ids.update(source_indexes)

    for wi, w in enumerate(line["words"]):
        if wi in assigned_ids:
            continue
        if w["xc"] < numeric_left:
            continue
        if not (
            _is_numeric_fragment(w["text"])
            or _is_strict_ocr_numeric_confusion(w["text"])
            or _is_numeric_punct(w["text"])
            or _is_explicit_amount_placeholder(w["text"])
        ):
            continue
        idx = _nearest_anchor_index(w["xc"], assignment_anchors)
        if abs(w["xc"] - assignment_anchors[idx]) <= half[idx] * 1.5:
            numeric_groups[idx].append(w)
            assigned_ids.add(wi)

    values = []
    for column_index, group in enumerate(numeric_groups):
        amount_clusters = _numeric_amount_clusters(group, page_width)
        if len(amount_clusters) > 1:
            cluster_texts = [
                _join_numeric_fragments(cluster)
                for cluster in amount_clusters
            ]
            raise ValueError(
                "MULTIPLE_NUMERIC_CLUSTERS_IN_ONE_CELL:"
                f"column={column_index};clusters={cluster_texts}"
            )
        raw = _join_numeric_fragments(amount_clusters[0] if amount_clusters else [])
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
    raw_label = "".join(w["text"] for w in label_words).strip(" \t\r\n")
    label = clean_cell(raw_label)
    return {
        "label": label,
        "raw_label": raw_label,
        "label_x0": min((w["x0"] for w in label_words), default=line["x0"]),
        "values": values,
        "has_numeric": any(raw for raw, _, _ in values),
        "leading_ws_indent": int(line.get("leading_ws_indent", 0)),
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
        # Generic accounting section labels.  They are only treated as a
        # section when the PDF emitted them as a standalone text-only line;
        # this preserves the explicit source row instead of concatenating it
        # with an indented numeric child.
        "债券", "债务工具", "权益工具",
        # Independently reviewed legacy available-for-sale hierarchy.  The
        # cost-measured branch can contain only one numeric descendant, so the
        # generic minimum-two-children geometry rule cannot promote it.
        "以公允价值计量的可供出售金融资产",
        "以成本计量的可供出售金融资产",
        "债权型投资", "股权型投资",
        "可归属于保险合同组合的费用",
        "不可归属于保险合同组合的费用",
    }
    return compact in exact


def _certified_nested_financial_section_level(text: str) -> int | None:
    """Return the audited structural level for legacy financial-asset sections.

    Some pre-IFRS-9 notes print the measurement basis and the investment type at
    the same x coordinate.  Geometry therefore cannot distinguish the outer
    measurement section from its inner debt/equity section.  Keep this contract
    deliberately narrow: only independently reviewed section labels participate;
    all other tables continue to use the generic geometry state machine.
    """
    compact = _line_compact(clean_cell(text)).rstrip("：:")
    if compact in {
        "以公允价值计量的可供出售金融资产",
        "以成本计量的可供出售金融资产",
    }:
        return 0
    if compact in {"债权型投资", "股权型投资"}:
        return 1
    return None


def _flush_pending_fragments(
    fragments: list[dict[str, Any]],
    target_rows: list[Any],
    current_row_order: int,
    current_parent_section: Optional[str],
    root_start_page: int,
    page_footnote_context: Optional[dict[int, dict[str, Any]]] = None,
    current_parent_section_x0: Optional[float] = None,
    *,
    lines: list[dict[str, Any]] | None = None,
    current_line_index: int | None = None,
    anchors: list[float] | None = None,
    page_width: float | None = None,
    numeric_anchors: list[float] | None = None,
) -> tuple[int, Optional[str], Optional[float]]:
    order = current_row_order
    parent = current_parent_section
    parent_x0 = current_parent_section_x0
    for frag in fragments:
        order += 1
        frag_text = str(frag.get("text") or "")
        frag_x0 = float(frag.get("x0", 0.0))
        is_sec = bool(frag.get("is_structural_parent")) or _is_explicit_section_label(frag_text)
        if not is_sec and lines and current_line_index is not None and anchors and page_width:
            next_child_x0 = float(lines[current_line_index].get("x0", frag_x0))
            if _is_indented_group_section(
                lines,
                current_line_index=current_line_index,
                parent_x0=frag_x0,
                first_child_x0=next_child_x0,
                anchors=anchors,
                page_width=page_width,
                numeric_anchors=numeric_anchors,
                minimum_children=2,
            ):
                is_sec = True
        frag_page = int(frag.get("page", root_start_page))
        header_src = root_start_page if frag_page > root_start_page else None
        norm_res_text = _append_text_only_row(
            target_rows,
            row_order=order,
            page=frag_page,
            text=frag_text,
            parent_section=parent,
            header_source_page=header_src,
            as_section=is_sec,
            row_type_override="PARENT_SECTION" if is_sec else "DETAIL",
            block_id=frag.get("block_id"),
            bbox=frag.get("bbox"),
            page_footnote_context=page_footnote_context,
        )
        if is_sec:
            parent = norm_res_text
            parent_x0 = frag_x0
    fragments.clear()
    return order, parent, parent_x0


@dataclass
class LogicalRowCandidate:
    prefix_fragments: list[dict[str, Any]] = field(default_factory=list)
    anchor_fragment: dict[str, Any] = field(default_factory=dict)
    suffix_fragments: list[dict[str, Any]] = field(default_factory=list)
    parsed_values: list[tuple[str, float | None, str | None]] = field(default_factory=list)
    parsed_line: dict[str, Any] = field(default_factory=dict)
    line: dict[str, Any] = field(default_factory=dict)
    active_block_id: str = ""
    page_no: int = 0
    header_source_page: int | None = None
    active_column_offset: int = 0
    active_expected_columns: int = 0


def _is_standalone_complete_accounting_item(label: str) -> bool:
    """Check if a label is already a standalone complete accounting item."""
    clean = clean_cell(label)
    if not clean:
        return False
    clean_no_notes = re.sub(r"(?:注\d+|\(\d+\)|（\d+）|\d+)+$", "", clean).strip()
    STANDALONE_ITEMS = (
        "长期股权投资", "投资性房地产", "其他投资", "其他投资资产",
        "现金及现金等价物", "现金、现金等价物", "定期存款",
        "债券投资", "债券型基金", "优先股", "债权投资计划", "理财产品投资",
        "股票", "权益型基金", "基金", "信托计划", "其他金融投资",
        "债权类金融资产", "股权类金融资产", "金融投资",
        "以摊余成本计量的金融资产",
        "以公允价值计量且其变动计入其他综合收益的金融资产",
        "以公允价值计量且其变动计入当期损益的金融资产",
        "交易性金融资产", "其他债权投资", "其他权益工具投资", "债权投资及其他",
        "可供出售金融资产", "持有至到期投资", "贷款及其他", "投资资产", "投资资产（合计）", "投资资产(合计)",
        "其他",
    )
    from table_capture import normalize_item_label
    norm = normalize_item_label(clean_no_notes)
    norm_orig = normalize_item_label(clean)
    if norm in STANDALONE_ITEMS or clean_no_notes in STANDALONE_ITEMS or norm_orig in STANDALONE_ITEMS or clean in STANDALONE_ITEMS:
        return True
    if any(norm == p or clean_no_notes == p for p in STANDALONE_ITEMS):
        return True
    return False


def _resolve_anchor_prefix_candidates(
    unresolved_text_fragments: list[dict[str, Any]],
    current_numeric_line: dict[str, Any],
    current_parsed: dict[str, Any],
    lines: list[dict[str, Any]],
    current_line_index: int,
    *,
    page_no: int,
    active_block_id: str,
    anchors: list[float],
    page_width: float,
    numeric_anchors: list[float] | None = None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Select candidate prefix fragments from unresolved text fragments for a numeric anchor.

    Returns:
      (prefix_fragments, remaining_unresolved)
    """
    if not unresolved_text_fragments:
        return [], []

    current_label = clean_cell(current_parsed.get("raw_label") or current_parsed.get("label") or "")
    current_x0 = float(current_parsed.get("label_x0", current_numeric_line.get("x0", 0.0)))
    current_y0 = float(current_numeric_line.get("y0", 0.0))
    current_page = int(page_no)
    current_block_id = str(active_block_id)

    # Layer 1: Hard Gates (collect contiguous wrap chain bottom-up from numeric anchor)
    candidate_fragments: list[dict[str, Any]] = []
    next_y0 = current_y0
    for f in reversed(unresolved_text_fragments):
        if len(candidate_fragments) >= 4:
            break
        # Same page and block
        if current_page and f.get("page") and int(f["page"]) != current_page:
            break
        if current_block_id and f.get("block_id") and str(f["block_id"]) != current_block_id:
            break
        # Hard gate: cannot be an explicit section title or verified structural parent
        if _is_explicit_section_label(f.get("text", "")) or bool(f.get("is_structural_parent")):
            break
        # Hard gate: column x0 alignment envelope
        frag_x0 = float(f.get("x0", 0.0))
        if not current_label and bool(current_parsed.get("has_numeric")):
            # A wrapped physical row can place the amount lanes between the
            # first and last label lines.  The numeric-only anchor therefore
            # has an x0 in the amount region and must not be compared with the
            # label fragment's x0.  Keep the fragment strictly inside the
            # certified label region to avoid welding narrative text.
            first_numeric_anchor = min(numeric_anchors or anchors)
            frag_x1 = float(f.get("x1", frag_x0))
            if frag_x0 >= first_numeric_anchor or frag_x1 > first_numeric_anchor:
                break
        elif abs(frag_x0 - current_x0) > max(35.0, page_width * 0.06):
            break
        # Hard gate: step-wise adjacent line vertical gap limit (wrap line pitch <= 18pt)
        frag_y1 = float(f.get("y1", f.get("y0", 0.0) + 10.0))
        step_gap = next_y0 - frag_y1
        if step_gap > 18.0 or step_gap < -8.0:
            break
        candidate_fragments.insert(0, f)
        next_y0 = float(f.get("y0", frag_y1 - 10.0))

    if not candidate_fragments:
        return [], unresolved_text_fragments

    # Hard gate: If current_label is ALREADY a standalone complete item on its own,
    # and candidate fragments do NOT end in incomplete connector chars, forbid prefix welding!
    INCOMPLETE_TAIL_CHARS = (
        "以", "按", "由", "且", "其", "于", "在", "并", "非", "未", "已", "净",
        "的", "及", "与", "之", "或", "金", "综", "综合", "投", "损", "成", "公允", "(", "（"
    )
    last_frag_text = str(candidate_fragments[-1].get("text", "")).strip()
    if _is_standalone_complete_accounting_item(current_label) and not last_frag_text.endswith(INCOMPLETE_TAIL_CHARS):
        return [], unresolved_text_fragments

    # Layer 2: Multi-Evidence Scoring
    score = 0
    first_frag = candidate_fragments[0]
    if bool(first_frag.get("is_structural_parent")):
        score -= 10

    from table_capture import normalize_item_label
    raw_combined = "".join(f["text"] for f in candidate_fragments) + current_label
    norm_combined = normalize_item_label(raw_combined)

    ACCOUNTING_CLOSURE_PATTERNS = (
        "金融资产", "债权投资", "股权投资", "股权计划", "信托计划", "基金",
        "资产", "负债", "所有者权益", "收入", "费用", "利润", "现金流", "现金流量",
        "变动", "损益", "综合收益", "摊余成本", "公允价值", "房地产", "存款"
    )
    if any(norm_combined.endswith(pat) or pat in norm_combined for pat in ACCOUNTING_CLOSURE_PATTERNS):
        if len(norm_combined) >= 6:
            score += 4

    INCOMPLETE_HEAD_CHARS = (
        "变动", "收益", "损失", "资产", "负债", "权益", "融", "合", "资", "益",
        "本", "价值", "的", "之", "或", "计入"
    )
    for i, f in enumerate(candidate_fragments):
        f_text = str(f.get("text", "")).strip()
        if f_text.endswith(INCOMPLETE_TAIL_CHARS):
            score += 3
        if f_text.startswith(("以", "按", "由", "包括", "属于", "其中")) and len(f_text) <= 12:
            score += 3
        next_text = (
            candidate_fragments[i + 1]["text"].strip()
            if i + 1 < len(candidate_fragments)
            else current_label.strip()
        )
        if any(next_text.startswith(hc) for hc in INCOMPLETE_HEAD_CHARS):
            score += 3

    score += 2  # Tight gap bonus

    if score >= 4:
        remaining = [f for f in unresolved_text_fragments if f not in candidate_fragments]
        return candidate_fragments, remaining
    return [], unresolved_text_fragments


def _is_valid_suffix_candidate(
    candidate: LogicalRowCandidate,
    line: dict[str, Any],
    parsed: dict[str, Any],
    *,
    page_no: int,
    active_block_id: str,
    page_width: float,
) -> bool:
    """Evaluate whether a following text-only visual line is a valid suffix of the active LogicalRowCandidate."""
    if len(candidate.suffix_fragments) >= 2:
        return False
    if parsed.get("has_numeric"):
        return False
    if int(page_no) != int(candidate.page_no):
        return False
    if str(active_block_id) != str(candidate.active_block_id):
        return False

    suffix_text = clean_cell(parsed.get("label") or line.get("text") or "")
    if not suffix_text:
        return False
    if _is_explicit_section_label(suffix_text):
        return False
    from investment_portfolio_axis_semantics import recognise_portfolio_axis_boundary
    if recognise_portfolio_axis_boundary(suffix_text).is_boundary:
        return False

    # Check alignment envelope
    anchor_label = clean_cell(candidate.anchor_fragment.get("label") or "")
    if not anchor_label and candidate.prefix_fragments:
        # For a numeric-only anchor, the nearest prefix fragment carries the
        # physical label-column alignment used to adjudicate a trailing wrap.
        anchor_x0 = float(candidate.prefix_fragments[-1].get("x0", 0.0))
    else:
        anchor_x0 = float(candidate.parsed_line.get("label_x0", candidate.line.get("x0", 0.0)))
    suffix_x0 = float(parsed.get("label_x0", line.get("x0", 0.0)))
    if abs(suffix_x0 - anchor_x0) > max(35.0, page_width * 0.06):
        return False

    # Check vertical step gap
    last_y0 = float(
        candidate.suffix_fragments[-1].get("y0")
        if candidate.suffix_fragments
        else candidate.line.get("y0", 0.0)
    )
    last_y1 = float(
        candidate.suffix_fragments[-1].get("y1")
        if candidate.suffix_fragments
        else candidate.line.get("y1", candidate.line.get("y0", 0.0) + 10.0)
    )
    line_y0 = float(line.get("y0", 0.0))
    if line_y0 <= last_y0:
        return False
    step_gap = line_y0 - last_y1
    if step_gap > 16.0 or step_gap < -8.0:
        return False

    current_raw = "".join(
        [f["text"] for f in candidate.prefix_fragments]
        + [candidate.anchor_fragment.get("label", "")]
        + [f["text"] for f in candidate.suffix_fragments]
    )

    INCOMPLETE_TAIL_CHARS = (
        "以", "按", "由", "且", "其", "于", "在", "并", "非", "未", "已", "净",
        "的", "及", "与", "之", "或", "金", "综", "综合", "投", "损", "成", "公允", "(", "（"
    )
    tail_incomplete = current_raw.endswith(INCOMPLETE_TAIL_CHARS)

    # Hard gate: If current_raw is ALREADY a standalone complete item on its own without dangling connectors,
    # it cannot absorb any suffix!
    if _is_standalone_complete_accounting_item(current_raw) and not tail_incomplete:
        return False

    # Hard gate: Suffix text cannot be a new sentence / item starter
    if any(suffix_text.startswith(p) for p in ("以", "按", "其中", "包括", "主要", "由")):
        return False

    # Hard gate: Suffix text cannot be an already standalone complete item on its own
    if _is_standalone_complete_accounting_item(suffix_text):
        return False

    from table_capture import normalize_item_label
    combined = current_raw + suffix_text
    norm_combined = normalize_item_label(combined)
    ACCOUNTING_CLOSURE_PATTERNS = (
        "金融资产", "债权投资", "股权投资", "股权计划", "信托计划", "基金",
        "资产", "负债", "所有者权益", "收入", "费用", "利润", "现金流", "现金流量",
        "变动", "损益", "综合收益", "摊余成本", "公允价值", "房地产", "存款"
    )
    resolves_closure = any(pat in norm_combined for pat in ACCOUNTING_CLOSURE_PATTERNS)

    if tail_incomplete or resolves_closure:
        return True
    return False


def _materialize_logical_row_candidate(
    candidate: LogicalRowCandidate,
    target_rows: list[Any],
    current_row_order: int,
    current_parent_section: str | None,
    current_parent_section_x0: float | None,
    columns: list[Any],
    page_context: Any,
    page_unit: Any,
    page_native_unit: Any,
    certified_unit: Any,
    certified_unit_raw: Any,
    page_footnote_context: dict[int, dict[str, Any]] | None = None,
) -> tuple[int, str | None, float | None]:
    """Materialize a completed LogicalRowCandidate into a TableRow and commit to target_rows."""
    prefix_text = "".join(f["text"] for f in candidate.prefix_fragments)
    anchor_label = candidate.anchor_fragment.get("label", "")
    suffix_text = "".join(f["text"] for f in candidate.suffix_fragments)

    raw_label_item = prefix_text + anchor_label + suffix_text
    target_label_for_norm = raw_label_item or ""

    from compound_note_engine import match_line_footnote_evidence
    ev = match_line_footnote_evidence(target_label_for_norm, candidate.page_no, page_footnote_context) if page_footnote_context else []
    for f in candidate.prefix_fragments + candidate.suffix_fragments:
        f_txt = str(f.get("text") or "")
        if f_txt and page_footnote_context:
            ev.extend(match_line_footnote_evidence(f_txt, candidate.page_no, page_footnote_context))

    from table_capture import normalize_item_label_with_evidence, classify_row_type, TableCell, TableRow
    from semantic_row_parser import classify_cell_role
    norm_res = normalize_item_label_with_evidence(target_label_for_norm, numeric_footnote_evidence=ev)
    norm = norm_res.normalized_item
    row_type = classify_row_type(norm, True) if raw_label_item else "DETAIL"
    row_role = row_type if raw_label_item else "IMPLICIT_ROW_CANDIDATE"

    parent_section = current_parent_section
    parent_section_x0 = current_parent_section_x0

    anchor_x0 = float(candidate.parsed_line.get("label_x0", candidate.line.get("x0", 0.0)))
    if parent_section and parent_section_x0 is not None:
        if (
            anchor_x0 <= parent_section_x0 + 4.0
            and not _section_parent_allows_same_indent(parent_section)
            and row_type != "SUBTOTAL"
        ):
            parent_section = None
            parent_section_x0 = None
    # A subtotal closes the active section *after* it is emitted and therefore
    # retains that section as its parent.  A final total remains a root row.
    if row_type == "TOTAL":
        parent_section = None
        parent_section_x0 = None

    output_parent = parent_section
    output_level = 1 if parent_section else 0

    cells = []
    for i, (raw, number, cell_unit) in enumerate(candidate.parsed_values):
        if not raw:
            continue
        column = next((
            cand for cand in columns
            if int(cand.ordinal) == candidate.active_column_offset + i
        ), None)
        measure = str(getattr(column, "measure", "") or "").strip()
        (
            original_unit,
            value_yuan,
            unit_source,
            unit_evidence,
        ) = _resolve_observation_unit(
            raw_cell_unit=cell_unit,
            measure=measure,
            number=number,
            certified_amount_unit=certified_unit,
            page_context_unit=page_native_unit or page_unit,
            page_context_source_page=page_context.unit_source_page,
            certified_amount_unit_code=certified_unit_raw,
        )
        cells.append(TableCell(
            column_ordinal=candidate.active_column_offset + i,
            source_column_index=candidate.active_column_offset + i + 1,
            raw=raw,
            parsed_number=number,
            unit_original=original_unit,
            value_yuan=value_yuan,
            cell_role=classify_cell_role(raw, number),
            context_source_page=page_context.unit_source_page,
            currency=page_context.currency,
            unit_source=unit_source,
            unit_evidence=unit_evidence,
        ))

    row_x0 = min(
        [float(candidate.line.get("x0", 0.0))]
        + [float(f.get("x0", 0.0)) for f in candidate.prefix_fragments + candidate.suffix_fragments if f.get("x0") is not None]
    )
    row_y0 = min(
        [float(candidate.line.get("y0", 0.0))]
        + [float(f.get("y0", 0.0)) for f in candidate.prefix_fragments if f.get("y0") is not None]
    )
    row_x1 = max(
        [float(candidate.line.get("x1", 0.0))]
        + [float(f.get("x1", 0.0)) for f in candidate.prefix_fragments + candidate.suffix_fragments if f.get("x1") is not None]
    )
    row_y1 = max(
        [float(candidate.line.get("y1", 0.0))]
        + [float(f.get("y1", 0.0)) for f in candidate.suffix_fragments if f.get("y1") is not None]
    )

    current_row_order += 1
    target_rows.append(TableRow(
        row_order=current_row_order,
        page=candidate.page_no,
        block_id=candidate.active_block_id,
        source_method="spatial_roi+column_anchors",
        raw_item=raw_label_item,
        normalized_item=norm,
        canonical_item=None,
        mapping_status="UNMAPPED",
        row_type=row_type,
        row_level=output_level,
        parent_section=output_parent,
        cells=cells,
        header_source_page=candidate.header_source_page,
        row_role=row_role,
        row_item_raw=raw_label_item,
        row_item_normalized=norm or None,
        label_derivation="EXPLICIT_TEXT" if raw_label_item else "NONE",
        bbox={
            "x0": row_x0, "y0": row_y0,
            "x1": row_x1, "y1": row_y1,
        },
        footnote_evidence=list(norm_res.footnote_evidence),
        footnote_markers=list(norm_res.footnote_markers),
        normalization_status=norm_res.normalization_status,
    ))
    target_rows[-1].leading_ws_indent = int(
        candidate.line.get("leading_ws_indent", candidate.parsed_line.get("leading_ws_indent", 0))
    )

    if row_type == "SUBTOTAL":
        parent_section = None
        parent_section_x0 = None

    return current_row_order, parent_section, parent_section_x0


def _section_parent_allows_same_indent(label: str | None) -> bool:
    """Semantic whereof markers own following rows even without indentation.

    Some annual reports align ``其中：`` and its measurement components at the
    same x-coordinate.  The explicit source marker is stronger evidence than
    indentation in that layout; ordinary section labels continue to require a
    physical indent.
    """
    return _line_compact(str(label or "")).rstrip("：:") == "其中"


def _commit_active_candidate_if_any(
    candidate: LogicalRowCandidate | None,
    target_rows: list[Any],
    current_row_order: int,
    current_parent_section: str | None,
    current_parent_section_x0: float | None,
    columns: list[Any],
    page_context: Any,
    page_unit: Any,
    page_native_unit: Any,
    certified_unit: Any,
    certified_unit_raw: Any,
    page_footnote_context: dict[int, dict[str, Any]] | None = None,
) -> tuple[LogicalRowCandidate | None, int, str | None, float | None]:
    """Helper to commit active candidate if present and reset to None."""
    if candidate is not None:
        order, parent, parent_x0 = _materialize_logical_row_candidate(
            candidate,
            target_rows,
            current_row_order,
            current_parent_section,
            current_parent_section_x0,
            columns,
            page_context,
            page_unit,
            page_native_unit,
            certified_unit,
            certified_unit_raw,
            page_footnote_context,
        )
        return None, order, parent, parent_x0
    return None, current_row_order, current_parent_section, current_parent_section_x0


def _is_probable_continuation_label(pending_text: str, next_label: str = "") -> bool:
    """Determine if a pending text-only line is a wrapped label continuation."""
    raw = clean_cell(pending_text)
    if not raw:
        return False
    if len(raw) >= 15:
        return True
    if raw.endswith(("的", "及", "与", "之", "或")):
        return True
    return False


def _is_indented_group_section(
    lines: list[dict[str, Any]],
    *,
    current_line_index: int,
    parent_x0: float,
    first_child_x0: float,
    anchors: list[float],
    page_width: float,
    numeric_anchors: list[float] | None = None,
    minimum_children: int = 2,
) -> bool:
    if first_child_x0 <= parent_x0 + 7.0:
        return False
    child_count = 1
    child_indent_tolerance = max(4.0, page_width * 0.008)
    from table_capture import classify_row_type, normalize_item_label

    for candidate_line in lines[current_line_index + 1:]:
        try:
            candidate = _line_to_spatial_cells(
                candidate_line,
                anchors,
                page_width,
                numeric_anchors=numeric_anchors,
            )
        except ValueError:
            return False
        candidate_label = clean_cell(candidate["label"])
        if not candidate_label and not candidate["has_numeric"]:
            continue
        candidate_x0 = float(candidate.get("label_x0", candidate_line.get("x0", 0.0)))
        if candidate_x0 > parent_x0 + 7.0:
            if abs(candidate_x0 - first_child_x0) > child_indent_tolerance:
                return False
            if candidate["has_numeric"]:
                child_count += 1
            continue
        return child_count >= minimum_children
    return child_count >= minimum_children


def _promote_single_child_outer_section(
    rows: list[Any],
    pending: dict[str, Any],
    lines: list[dict[str, Any]],
    *,
    current_line_index: int,
    first_child_x0: float,
    anchors: list[float],
    page_width: float,
    numeric_anchors: list[float] | None = None,
) -> str | None:
    if len(rows) < 2:
        return None
    preceding, outer = rows[-2], rows[-1]
    if (
        str(getattr(preceding, "row_type", "")) != "SUBTOTAL"
        or str(getattr(outer, "row_type", "")) != "DETAIL"
        or list(getattr(outer, "cells", []) or [])
        or int(getattr(outer, "page", -1)) != int(pending["page"])
        or str(getattr(outer, "block_id", ""))
        != str(pending.get("block_id") or "")
    ):
        return None
    outer_bbox = dict(getattr(outer, "bbox", {}) or {})
    outer_x0 = float(outer_bbox.get("x0", pending["x0"]))
    if abs(outer_x0 - float(pending["x0"])) > max(4.0, page_width * 0.008):
        return None
    if not _is_indented_group_section(
        lines,
        current_line_index=current_line_index,
        parent_x0=outer_x0,
        first_child_x0=first_child_x0,
        anchors=anchors,
        page_width=page_width,
        numeric_anchors=numeric_anchors,
        minimum_children=1,
    ):
        return None
    outer.row_type = "SECTION_HEADER"
    outer.row_role = "SECTION_HEADER"
    outer.row_level = 0
    outer.parent_section = None
    outer.label_derivation = "EXPLICIT_TEXT_SECTION_TRANSITION"
    return str(getattr(outer, "normalized_item", "") or "") or None


def _is_promoted_section_parent(rows: list[Any], parent_section: str | None) -> bool:
    normalized_parent = normalize_text(parent_section or "")
    if not normalized_parent:
        return False
    return any(
        str(getattr(row, "label_derivation", ""))
        == "EXPLICIT_TEXT_SECTION_TRANSITION"
        and normalize_text(getattr(row, "normalized_item", ""))
        == normalized_parent
        for row in reversed(rows)
    )


def _append_text_only_row(
    rows: list,
    *,
    row_order: int,
    page: int,
    text: str,
    parent_section: Optional[str],
    header_source_page: Optional[int] = None,
    as_section: bool = False,
    row_type_override: Optional[str] = None,
    block_id: Optional[str] = None,
    bbox: Optional[dict[str, float]] = None,
    page_footnote_context: Optional[dict[int, dict[str, Any]]] = None,
):
    from table_capture import TableRow, normalize_item_label_with_evidence
    from compound_note_engine import match_line_footnote_evidence

    ev = match_line_footnote_evidence(text, page, page_footnote_context or {}) if page_footnote_context else []
    norm_res = normalize_item_label_with_evidence(text, numeric_footnote_evidence=ev)
    norm = norm_res.normalized_item
    rows.append(TableRow(
        row_order=row_order,
        page=page,
        block_id=block_id or f"spatial_p{page}",
        source_method=(
            "spatial_roi+section_header"
            if as_section else
            "spatial_roi+text_only_detail"
        ),
        raw_item=text,
        normalized_item=norm,
        canonical_item=None,
        mapping_status="UNMAPPED",
        row_type=row_type_override or ("PARENT_SECTION" if as_section else "DETAIL"),
        row_level=0 if as_section else (1 if parent_section else 0),
        parent_section=None if as_section else parent_section,
        cells=[],
        header_source_page=header_source_page,
        row_role=row_type_override or ("PARENT_SECTION" if as_section else "DETAIL"),
        row_item_raw=text,
        row_item_normalized=norm,
        label_derivation="EXPLICIT_TEXT",
        bbox=bbox,
        footnote_evidence=list(norm_res.footnote_evidence),
        footnote_markers=list(norm_res.footnote_markers),
        normalization_status=norm_res.normalization_status,
    ))
    return norm


def _append_layout_noise_row(
    rows: list,
    *,
    row_order: int,
    page: int,
    line: dict[str, Any],
    row_role: str,
    block_id: Optional[str],
) -> None:
    _append_text_only_row(
        rows,
        row_order=row_order,
        page=page,
        text=clean_cell(str(line.get("text") or "")),
        parent_section=None,
        header_source_page=None,
        as_section=False,
        row_type_override=row_role,
        block_id=block_id,
        bbox={
            "x0": float(line["x0"]),
            "y0": float(line["y0"]),
            "x1": float(line["x1"]),
            "y1": float(line["y1"]),
        },
    )
    rows[-1].source_method = "spatial_roi+layout_noise"
    rows[-1].excluded_from_table_logic = True


def _numeric_values_by_ordinal(row: Any) -> dict[int, float]:
    values: dict[int, float] = {}
    for cell in getattr(row, "cells", []) or []:
        ordinal = getattr(cell, "column_ordinal", None)
        number = getattr(cell, "parsed_number", None)
        if ordinal is None or number is None:
            continue
        values[int(ordinal)] = float(number)
    return values


def _row_left(row: Any) -> float | None:
    bbox = getattr(row, "bbox", None) or {}
    value = bbox.get("x0", bbox.get("left"))
    return float(value) if value is not None else None


def _leading_whitespace_indent(row: Any) -> int:
    """Count leading ideographic spaces (U+3000) or explicit whitespace indent in the row."""
    explicit = getattr(row, "leading_ws_indent", None)
    if explicit is not None and isinstance(explicit, int) and explicit > 0:
        return explicit
    raw = str(getattr(row, "raw_item", None) or getattr(row, "row_item_raw", None) or "")
    count = 0
    for ch in raw:
        if ch == "\u3000":
            count += 1
        elif ch in (" ", "\t"):
            continue
        else:
            break
    return count


def _cell_controlled_state(cell: Any) -> tuple[str, float | None]:
    """Classify cell into one of 5 controlled states: VALUE, PRINTED_DASH, NOT_APPLICABLE, EXTRACTION_MISSING, UNRESOLVED."""
    if cell is None:
        return "EXTRACTION_MISSING", None
    parsed = getattr(cell, "parsed_number", None)
    if parsed is not None:
        try:
            return "VALUE", float(parsed)
        except (TypeError, ValueError):
            return "UNRESOLVED", None
    raw_token = str(getattr(cell, "raw", "") or "").strip()
    if not raw_token:
        return "EXTRACTION_MISSING", None
    if raw_token in {"-", "--", "—", "－", "——", "— —", "- -", "- - -", "— — —"}:
        return "PRINTED_DASH", 0.0
    if raw_token in {"/", "不适用", "N/A", "NA", "无"}:
        return "NOT_APPLICABLE", 0.0
    return "UNRESOLVED", None


def _numeric_parent_reconciles(
    parent: Any,
    children: list[Any],
    columns: list[Any] | None = None,
) -> tuple[bool, dict[int, dict[str, float]]]:
    parent_values = _numeric_values_by_ordinal(parent)
    if not parent_values:
        return False, {}
    checks: dict[int, dict[str, float]] = {}
    valid_reconciled_columns = 0
    valid_amount_reconciled_columns = 0
    col_map = {getattr(col, "ordinal", None): col for col in (columns or [])} if columns else {}

    for ordinal, reported in parent_values.items():
        valid_parts: list[float] = []
        column_missing = False
        for child in children:
            child_num_dict = _numeric_values_by_ordinal(child)
            val = child_num_dict.get(ordinal)
            if val is not None:
                valid_parts.append(float(val))
            else:
                child_cells = {getattr(c, "column_ordinal", None): c for c in getattr(child, "cells", []) or []}
                cell = child_cells.get(ordinal)
                state, default_val = _cell_controlled_state(cell)
                if state in {"PRINTED_DASH", "NOT_APPLICABLE"} and default_val is not None:
                    valid_parts.append(default_val)
                else:
                    column_missing = True
                    break
        if column_missing or not valid_parts:
            continue
        observed = sum(valid_parts)
        tolerance = max(2.0, float(len(children)))
        checks[ordinal] = {
            "reported": reported,
            "sum_children": observed,
            "tolerance": tolerance,
        }
        if abs(reported - observed) > tolerance:
            return False, checks
        valid_reconciled_columns += 1
        col = col_map.get(ordinal)
        is_percent = (
            getattr(col, "measure", None) in {"占比", "比例", "百分比"}
            or (getattr(col, "header_raw", None) and any(tok in str(col.header_raw) for tok in ("占比", "比例", "%")))
        )
        if not is_percent:
            valid_amount_reconciled_columns += 1

    if col_map:
        return valid_amount_reconciled_columns > 0 and valid_reconciled_columns > 0, checks
    return valid_reconciled_columns > 0, checks


def _infer_numeric_parent_hierarchy(rows: list[Any]) -> list[dict[str, Any]]:
    """Recover source hierarchy when a numeric parent precedes indented children.

    Some financial tables print a group total on the parent row itself and use
    indentation, rather than a label-only section row, for its breakdown.  A
    relation is accepted only inside one page/block when at least two
    consecutive numeric rows are visibly indented and reconcile to the parent
    in every populated amount column.

    Indentation is detected via two complementary signals:
      1. Physical x-coordinate offset (bbox.x0 difference >= 6 pt).
      2. Leading U+3000 ideographic spaces in the raw label text, for PDFs
         that encode indentation as whitespace characters rather than
         coordinate offsets.
    Either signal is sufficient; both are recorded in the evidence.
    """
    evidence: list[dict[str, Any]] = []
    minimum_indent = 6.0
    maximum_indent = 72.0
    for index, parent in enumerate(rows):
        if (
            getattr(parent, "excluded_from_table_logic", False)
            or getattr(parent, "parent_section", None)
            or int(getattr(parent, "row_level", 0) or 0) != 0
            or str(getattr(parent, "row_type", "") or "").upper() in {"TOTAL", "SUBTOTAL"}
            or not str(getattr(parent, "raw_item", "") or "").strip()
            or not _numeric_values_by_ordinal(parent)
        ):
            continue
        parent_left = _row_left(parent)
        if parent_left is None:
            continue
        parent_ws = _leading_whitespace_indent(parent)
        children: list[Any] = []
        indents: list[float] = []
        for child in rows[index + 1:]:
            if (
                getattr(child, "excluded_from_table_logic", False)
                or int(getattr(child, "page", 0) or 0) != int(getattr(parent, "page", 0) or 0)
                or str(getattr(child, "block_id", "") or "") != str(getattr(parent, "block_id", "") or "")
                or getattr(child, "parent_section", None)
                or not str(getattr(child, "raw_item", "") or "").strip()
                or not _numeric_values_by_ordinal(child)
            ):
                break
            child_left = _row_left(child)
            if child_left is None:
                break
            indent = child_left - parent_left
            child_ws = _leading_whitespace_indent(child)
            ws_indent = child_ws - parent_ws
            # Accept indentation from either physical coordinate offset or
            # leading ideographic-space count.  The whitespace signal covers
            # PDFs where all rows share the same bbox.x0 but use U+3000 to
            # visually indent child labels.
            has_physical_indent = minimum_indent <= indent <= maximum_indent
            has_whitespace_indent = ws_indent > 0
            if not has_physical_indent and not has_whitespace_indent:
                break
            if indent > maximum_indent:
                break
            children.append(child)
            indents.append(indent if has_physical_indent else float(ws_indent) * 9.0)
        if len(children) < 2:
            continue
        reconciles, checks = _numeric_parent_reconciles(parent, children)
        if not reconciles:
            continue
        parent_label = str(
            getattr(parent, "normalized_item", None)
            or getattr(parent, "raw_item", "")
        ).strip()
        if not parent_label:
            continue
        parent_source_row_id = getattr(parent, "source_row_id", None) or f"ROW_{getattr(parent, 'row_order', 0)}"
        if not getattr(parent, "source_row_id", None):
            parent.source_row_id = parent_source_row_id
        for child in children:
            if not getattr(child, "source_row_id", None):
                child.source_row_id = f"ROW_{getattr(child, 'row_order', 0)}"
            child_source_row_id = child.source_row_id
            child_physical_indent = float(_row_left(child) - parent_left)
            child_ws_indent = _leading_whitespace_indent(child) - parent_ws
            relation_evidence = {
                "relation": "NUMERIC_PARENT_WITH_INDENTED_CHILDREN",
                "parent_source_row_id": parent_source_row_id,
                "child_source_row_id": child_source_row_id,
                "parent_row_order": int(getattr(parent, "row_order", 0) or 0),
                "child_row_order": int(getattr(child, "row_order", 0) or 0),
                "parent_label": parent_label,
                "indent_points": child_physical_indent,
                "indent_source": (
                    "PHYSICAL_COORDINATE"
                    if child_physical_indent >= minimum_indent
                    else "IDEOGRAPHIC_SPACE"
                ),
                "ideographic_space_indent": child_ws_indent,
                "column_checks": checks,
            }
            child.parent_row_id = parent_source_row_id
            child.hierarchy_evidence = relation_evidence
            child.parent_section = parent_label
            child.row_level = int(getattr(parent, "row_level", 0) or 0) + 1
            if str(getattr(child, "row_role", "") or "") == "DETAIL":
                child.row_role = "BREAKDOWN_DETAIL"
        evidence.append({
            "relation": "NUMERIC_PARENT_WITH_INDENTED_CHILDREN",
            "page": int(getattr(parent, "page", 0) or 0),
            "block_id": str(getattr(parent, "block_id", "") or ""),
            "parent_row_order": int(getattr(parent, "row_order", 0) or 0),
            "parent_label": parent_label,
            "child_row_orders": [int(getattr(child, "row_order", 0) or 0) for child in children],
            "child_labels": [str(getattr(child, "raw_item", "") or "") for child in children],
            "parent_source_row_id": parent_source_row_id,
            "child_source_row_ids": [getattr(child, "source_row_id", None) for child in children],
            "indent_points": indents,
            "column_checks": checks,
        })
    return evidence


def _finalize_hierarchy_semantics(rows: list[Any]) -> list[dict[str, Any]]:
    """Normalize parent-child relations and standardize child contracts across all hierarchy sources.

    Pass 1 discovers PARENT_SECTION hierarchy via layout state machine.
    Pass 2 discovers NUMERIC_PARENT hierarchy via indentation + mathematical reconciliation.
    Pass 3 (this function) materializes and unifies the canonical child contract:
      - Resolves and links parent_row_id to parent TableRow.source_row_id;
      - Synchronizes parent_section string;
      - Validates and maintains row_level > parent.row_level;
      - Upgrades row_role to 'BREAKDOWN_DETAIL' for verified breakdown children;
      - Formats standardized hierarchy_evidence preserving method provenance.
    """
    evidence_list: list[dict[str, Any]] = []
    current_section_parent = None
    certified_section_stack: dict[int, Any] = {}

    for row in rows:
        rtype = str(getattr(row, "row_type", "") or "")
        rrole = str(getattr(row, "row_role", "") or "")

        # Track currently active structural section parent
        if rtype in {"PARENT_SECTION", "SECTION", "SECTION_HEADER"} or rrole == "PARENT_SECTION":
            section_level = _certified_nested_financial_section_level(
                str(getattr(row, "normalized_item", None) or getattr(row, "raw_item", ""))
            )
            if section_level == 0:
                certified_section_stack = {0: row}
                row.parent_row_id = None
                row.parent_section = None
                row.row_level = 0
            elif section_level == 1:
                outer = certified_section_stack.get(0)
                certified_section_stack = {
                    level: parent
                    for level, parent in certified_section_stack.items()
                    if level < section_level
                }
                if outer is not None:
                    parent_sid = getattr(outer, "source_row_id", None) or f"ROW_{getattr(outer, 'row_order', 0)}"
                    if not getattr(outer, "source_row_id", None):
                        outer.source_row_id = parent_sid
                    if not getattr(row, "source_row_id", None):
                        row.source_row_id = f"ROW_{getattr(row, 'row_order', 0)}"
                    parent_label = str(
                        getattr(outer, "normalized_item", None)
                        or getattr(outer, "raw_item", "")
                    ).strip()
                    row.parent_row_id = parent_sid
                    row.parent_section = parent_label
                    row.row_level = int(getattr(outer, "row_level", 0) or 0) + 1
                    row.row_role = "PARENT_SECTION"
                    evidence = {
                        "method": "certified_nested_financial_section",
                        "parent_source_row_id": parent_sid,
                        "parent_label": parent_label,
                        "parent_row_order": int(getattr(outer, "row_order", 0) or 0),
                        "child_level": int(row.row_level),
                        "evidence": {
                            "source": "audited_legacy_financial_section_contract",
                            "parent_page": getattr(outer, "page", None),
                        },
                    }
                    row.hierarchy_evidence = evidence
                    evidence_list.append(evidence)
                certified_section_stack[1] = row
            else:
                certified_section_stack.clear()
            current_section_parent = row
            continue
        elif rtype in {"TOTAL", "CLASSIFICATION_AXIS"} or not getattr(row, "parent_section", None):
            current_section_parent = None
            if rtype in {"TOTAL", "CLASSIFICATION_AXIS"}:
                certified_section_stack.clear()

        # 1. Populate text-parent child linkage (Pass 1 edge completion)
        if getattr(row, "parent_section", None) and getattr(row, "parent_row_id", None) is None:
            if current_section_parent is not None:
                parent_sid = getattr(current_section_parent, "source_row_id", None) or f"ROW_{getattr(current_section_parent, 'row_order', 0)}"
                if not getattr(current_section_parent, "source_row_id", None):
                    current_section_parent.source_row_id = parent_sid
                if not getattr(row, "source_row_id", None):
                    row.source_row_id = f"ROW_{getattr(row, 'row_order', 0)}"
                parent_lbl = str(
                    getattr(current_section_parent, "normalized_item", None)
                    or getattr(current_section_parent, "raw_item", "")
                ).strip()
                row.parent_row_id = parent_sid
                row.row_level = int(getattr(current_section_parent, "row_level", 0) or 0) + 1
                evidence = {
                    "method": "section_parent",
                    "parent_source_row_id": parent_sid,
                    "parent_label": parent_lbl,
                    "parent_row_order": int(getattr(current_section_parent, "row_order", 0) or 0),
                    "child_level": int(row.row_level),
                    "evidence": {
                        "source": "spatial_parent_state",
                        "parent_page": int(getattr(current_section_parent, "page", 0) or 0),
                    },
                }
                row.hierarchy_evidence = evidence
                evidence_list.append(evidence)

        # 2. Standardize numeric-parent child evidence schema (Pass 2 edge normalization)
        elif getattr(row, "hierarchy_evidence", None) and isinstance(row.hierarchy_evidence, dict):
            orig_ev = row.hierarchy_evidence
            if "method" not in orig_ev:
                row.hierarchy_evidence = {
                    "method": "numeric_parent_reconciliation",
                    "parent_source_row_id": orig_ev.get("parent_source_row_id"),
                    "parent_label": orig_ev.get("parent_label"),
                    "parent_row_order": orig_ev.get("parent_row_order"),
                    "child_level": int(getattr(row, "row_level", 1) or 1),
                    "evidence": orig_ev,
                }
                evidence_list.append(row.hierarchy_evidence)

        # 3. Standardize row_role to BREAKDOWN_DETAIL for verified breakdown children
        is_verified_child = bool(
            getattr(row, "parent_row_id", None) or getattr(row, "parent_section", None)
        ) and int(getattr(row, "row_level", 0) or 0) > 0

        if (
            is_verified_child
            and rtype == "DETAIL"
            and rrole not in {
                "TOTAL",
                "SUBTOTAL",
                "IMPLICIT_TOTAL",
                "PARENT",
                "PARENT_SECTION",
                "SECTION",
                "CLASSIFICATION_AXIS",
                "NOTE_TEXT",
                "MEMO_TEXT",
            }
        ):
            row.row_role = "BREAKDOWN_DETAIL"

    return evidence_list


def validate_hierarchy_graph(rows: list[Any], physical_table_id: str | None = None) -> dict[str, Any]:
    """Validate graph integrity: missing/duplicate IDs, dangling parents, cycles, self-references, cross-block anomalies."""
    source_ids: set[str] = set()
    duplicate_source_ids: set[str] = set()
    missing_source_ids: list[int] = []

    for r in rows:
        sid = str(getattr(r, "source_row_id", "") or "").strip()
        if not sid:
            missing_source_ids.append(int(getattr(r, "row_order", -1)))
        elif sid in source_ids:
            duplicate_source_ids.add(sid)
        else:
            source_ids.add(sid)

    row_map = {str(getattr(r, "source_row_id", "") or "").strip(): r for r in rows if getattr(r, "source_row_id", None)}

    dangling_edges: list[dict[str, Any]] = []
    cycle_edges: list[dict[str, Any]] = []
    self_reference_edges: list[dict[str, Any]] = []
    cross_block_edges: list[dict[str, Any]] = []
    cross_table_edges: list[dict[str, Any]] = []
    identity_conflicts: list[dict[str, Any]] = []
    review_reasons: list[str] = []
    valid_edges = 0

    if missing_source_ids:
        review_reasons.append(f"MISSING_SOURCE_ROW_IDS: 行序 {missing_source_ids} 缺失正式 source_row_id。")
    if duplicate_source_ids:
        review_reasons.append(f"DUPLICATE_SOURCE_ROW_IDS: 发现重复 source_row_id {sorted(duplicate_source_ids)}。")

    for row in rows:
        parent_id = str(getattr(row, "parent_row_id", "") or "").strip()
        if not parent_id:
            continue
        child_id = str(getattr(row, "source_row_id", "") or "").strip()
        child_label = str(getattr(row, "raw_item", "") or getattr(row, "row_item_raw", "") or "")
        child_block = str(getattr(row, "block_id", "") or "")

        # 1. Self reference
        if parent_id == child_id:
            self_reference_edges.append({
                "source_row_id": child_id,
                "label": child_label,
            })
            continue

        # 2. Dangling edge
        if parent_id not in source_ids:
            dangling_edges.append({
                "child_source_row_id": child_id,
                "dangling_parent_row_id": parent_id,
                "child_label": child_label,
            })
            continue

        parent_row = row_map.get(parent_id)
        parent_block = str(getattr(parent_row, "block_id", "") or "") if parent_row else ""
        parent_label = str(getattr(parent_row, "raw_item", "") or getattr(parent_row, "row_item_raw", "") or "") if parent_row else ""

        # 3. Cross block edge
        if child_block and parent_block and child_block != parent_block:
            cross_block_edges.append({
                "child_source_row_id": child_id,
                "parent_source_row_id": parent_id,
                "child_block": child_block,
                "parent_block": parent_block,
            })

        # 4. Identity / parent_section conflict
        row_psec = str(getattr(row, "parent_section", "") or "").strip()
        if row_psec and parent_label and row_psec != parent_label:
            if not (row_psec.startswith(parent_label) or parent_label.startswith(row_psec)):
                identity_conflicts.append({
                    "child_source_row_id": child_id,
                    "certified_parent_label": parent_label,
                    "legacy_parent_section": row_psec,
                })

        # 5. Cycle check
        visited = {child_id}
        curr = parent_id
        is_cycle = False
        while curr:
            if curr in visited:
                is_cycle = True
                break
            visited.add(curr)
            curr_parent_row = row_map.get(curr)
            curr = str(getattr(curr_parent_row, "parent_row_id", "") or "").strip() if curr_parent_row else ""
        if is_cycle:
            cycle_edges.append({
                "child_source_row_id": child_id,
                "parent_source_row_id": parent_id,
                "child_label": child_label,
            })
        else:
            valid_edges += 1

    if self_reference_edges:
        review_reasons.append(f"HIERARCHY_GRAPH_SELF_REFERENCE: 发现 {len(self_reference_edges)} 条自引用父子边。")
    if dangling_edges:
        review_reasons.append(f"HIERARCHY_GRAPH_DANGLING_EDGES: 发现 {len(dangling_edges)} 条悬空父子边。")
    if cycle_edges:
        review_reasons.append(f"HIERARCHY_GRAPH_CYCLE_EDGES: 发现 {len(cycle_edges)} 条循环层级边。")
    if cross_block_edges:
        review_reasons.append(f"HIERARCHY_GRAPH_CROSS_BLOCK_EDGES: 发现 {len(cross_block_edges)} 条跨 Block 父子边。")
    if identity_conflicts:
        review_reasons.append(f"HIERARCHY_GRAPH_IDENTITY_CONFLICTS: 发现 {len(identity_conflicts)} 条父项与旧 parent_section 冲突。")

    return {
        "status": "VALID" if not review_reasons else "REVIEW_REQUIRED",
        "valid_edges": valid_edges,
        "dangling_edges": dangling_edges,
        "cycle_edges": cycle_edges,
        "self_reference_edges": self_reference_edges,
        "cross_table_edges": cross_table_edges,
        "cross_block_edges": cross_block_edges,
        "identity_conflicts": identity_conflicts,
        "review_reasons": review_reasons,
    }


def resolve_pending_label(
    *,
    promoted_parent: str | None,
    explicit_section: bool,
    indented_group: bool,
    continuation: bool,
) -> str:
    """Single pending-label decision used by the Spatial Capture parser.

    The resolver distinguishes a structural group heading, a wrapped label and
    a same-level text-only detail before a numeric row is materialized.  Direct
    tables use the same decision and no longer need a second hierarchy pass.
    """
    if promoted_parent:
        return "PROMOTED_PARENT"
    if explicit_section or indented_group:
        return "SECTION"
    if continuation:
        return "CONTINUATION"
    return "DETAIL"


def capture_named_table_spatial(
    pdf_path: Path,
    table_query: str,
    note_number: Optional[str] = None,
    start_page_override: Optional[int] = None,
    max_pages: int = 8,
    progress_callback=None,
    header_parser_mode: str = "AUTO",
    strict_target_identity: bool = False,
    certified_target_heading: Optional[str] = None,
    certified_segments: Sequence[dict[str, Any]] | None = None,
    certified_amount_unit: str | None = None,
    physical_table_id: str | None = None,
):
    # Lazy import avoids circular import: table_capture calls this function only
    # after its dataclasses are fully defined.
    from table_capture import (
        TableColumn, TableCell, TableRow, TableCaptureResult,
        assign_source_row_identities,
        normalize_item_label, classify_row_type,
    )

    roi = locate_table_roi(
        pdf_path=pdf_path,
        table_query=table_query,
        note_number=note_number,
        start_page_override=start_page_override,
        max_pages=max_pages,
        strict_target_identity=strict_target_identity,
        certified_target_heading=certified_target_heading,
        certified_segments=certified_segments,
    )
    doc = fitz.open(str(pdf_path))

    if progress_callback:
        progress_callback({"event": "open_done", "message": "已定位目标附注ROI"})

    lines_by_page: dict[int, list[dict[str, Any]]] = {}
    certified_page_bboxes = dict(roi.get("certified_page_bboxes") or {})
    certified_geometry_source_by_page: dict[int, str] = {}
    for page_no in range(roi["start_page"], roi["end_page"] + 1):
        native_lines = _lines_in_roi(doc, roi, page_no)
        certified_bbox = certified_page_bboxes.get(page_no)
        certified_ocr_lines = (
            _certified_ocr_lines_for_page(
                certified_segments,
                page_number=page_no,
                certified_bbox=certified_bbox,
            )
            if certified_bbox is not None
            else None
        )
        if certified_ocr_lines is not None:
            lines_by_page[page_no] = _hybrid_native_label_ocr_value_lines(
                native_lines,
                certified_ocr_lines,
                certified_segments,
                page_number=page_no,
                page_width=float(roi["page_widths"][page_no]),
            )
            certified_geometry_source_by_page[page_no] = (
                "HYBRID_NATIVE_LABELS_OCR_VALUES_PDF_POINTS"
            )
        else:
            lines_by_page[page_no] = native_lines
            certified_geometry_source_by_page[page_no] = "NATIVE_PDF_WORDS"
    roi["certified_geometry_source_by_page"] = certified_geometry_source_by_page
    start_lines = lines_by_page[roi["start_page"]]
    certified_column_context = _certified_column_context(
        certified_segments,
        page_number=int(roi["start_page"]),
        lines=start_lines,
        page_width=float(roi["page_widths"][roi["start_page"]]),
    )
    if certified_column_context is None:
        certified_column_context = _direct_portfolio_column_context(
            certified_segments,
            page_number=int(roi["start_page"]),
            lines=start_lines,
            page_width=float(roi["page_widths"][roi["start_page"]]),
        )
    stacked_sections, stacked_occurrences_by_page = _vertical_period_plan(
        lines_by_page,
        roi["page_widths"],
    )
    if not stacked_sections and certified_column_context is not None:
        stacked_sections, stacked_occurrences_by_page = (
            _certified_vertical_period_plan(
                certified_column_context,
                lines_by_page,
                roi["page_widths"],
            )
        )
    from compound_note_engine import collect_page_footnote_context, match_line_footnote_evidence
    page_footnote_context = collect_page_footnote_context(
        doc,
        range(roi["start_page"], roi["end_page"] + 1),
    )
    try:
        header, header_arbitration = _arbitrate_header_candidates(
            start_lines,
            roi["page_widths"][roi["start_page"]],
            parser_mode=header_parser_mode,
        )
    except ValueError as exc:
        message = str(exc)
        fallback_allowed = (
            str(header_parser_mode or "AUTO").upper() == "AUTO"
            and (
                "HEADER_TOPOLOGY_REVIEW_REQUIRED" in message
                or "未识别到任何可用表头候选" in message
            )
        )
        if certified_column_context is None or not fallback_allowed:
            doc.close()
            raise
        if stacked_sections:
            header = dict(stacked_sections[0]["header"])
            lane_count = int(certified_column_context["lane_count"])
            parser = "CERTIFIED_VERTICAL_PERIOD_CONTEXT"
            metrics = {
                "parser": parser,
                "status": "VALID",
                "score": 100.0,
                "leaf_count": lane_count,
                "numeric_cluster_count": lane_count,
                "numeric_clusters": dict(
                    certified_column_context["numeric_clusters"]
                ),
                "hard_failures": [],
            }
            header_arbitration = {
                "mode": "AUTO",
                "auto_selected_parser": parser,
                "selected_parser": parser,
                "selection_reason": (
                    "CERTIFIED_VERTICAL_CONTEXT_VALIDATED_BY_BODY_LANES"
                ),
                "auto_abstain": False,
                "candidates": {parser: metrics},
            }
        else:
            header, header_arbitration = _certified_header(
                certified_column_context
            )

    if (
        certified_column_context is not None
        and not stacked_sections
        and str(header_parser_mode or "AUTO").upper() == "AUTO"
        and header_arbitration.get("selected_parser")
        != "CERTIFIED_COLUMN_CONTEXT"
    ):
        header, header_arbitration = _arbitrate_with_certified_context(
            header,
            header_arbitration,
            certified_column_context,
        )

    root_width = roi["page_widths"][roi["start_page"]]
    metadata, header_bottom = _header_metadata(start_lines, header, root_width)
    for i, hint in enumerate(header.get("restated_hints") or []):
        if i < len(metadata) and hint:
            metadata[i]["restated"] = True
            if "已重述" not in metadata[i]["tokens"]:
                metadata[i]["tokens"].append("已重述")
    column_metadata: list[dict[str, Any]] = []
    if stacked_sections:
        for section in stacked_sections:
            section_metadata = list(section["metadata"])
            for index, hint in enumerate(
                section["header"].get("restated_hints") or []
            ):
                if index < len(section_metadata) and hint:
                    section_metadata[index]["restated"] = True
                    if "已重述" not in section_metadata[index]["tokens"]:
                        section_metadata[index]["tokens"].append("已重述")
            for index, item in enumerate(section_metadata):
                column_metadata.append({
                    **item,
                    "ordinal": int(section["column_offset"]) + index,
                    "source_column_index": len(column_metadata) + 1,
                })
        header = stacked_sections[0]["header"]
        metadata = [
            item
            for item in column_metadata
            if int(item["ordinal"]) < int(stacked_sections[0]["column_count"])
        ]
        header_bottom = float(stacked_sections[0]["data_y_min"]) - 2.0
    else:
        _apply_certified_context_to_metadata(
            metadata,
            certified_column_context,
        )
        for index, item in enumerate(metadata):
            column_metadata.append({
                **item,
                "ordinal": index,
                "source_column_index": index + 1,
            })

    selected_metrics = (
        header_arbitration.get("candidates", {})
        .get(header_arbitration.get("selected_parser"), {})
    )
    root_numeric_assignment_anchors = _validated_numeric_assignment_anchors(
        header.get("anchors") or [],
        selected_metrics.get("numeric_clusters"),
        page_width=float(root_width),
        require_body_bounded=True,
    )
    if certified_column_context is not None:
        root_numeric_assignment_anchors = list(
            certified_column_context["numeric_assignment_anchors"]
        )
    header_arbitration["numeric_assignment_anchors"] = list(
        root_numeric_assignment_anchors or []
    )
    header_arbitration["numeric_assignment_source"] = (
        "VALIDATED_BODY_NUMERIC_CLUSTERS"
        if root_numeric_assignment_anchors
        else "HEADER_TEXT_ANCHORS"
    )

    anchor_ratios = [a / root_width for a in header["anchors"]]
    primary_table_end_y = _primary_table_end_y(
        start_lines, header_y1=header_bottom,
    )

    columns = []
    for meta in column_metadata:
        tokens = meta["tokens"]
        period = normalize_period_fields(
            source_period_label=meta.get("source_period_label"),
            period_label=meta.get("period_label"),
            year=meta.get("year"),
        )
        columns.append(TableColumn(
            ordinal=int(meta["ordinal"]),
            source_column_index=int(meta["source_column_index"]),
            header_raw=" | ".join(tokens),
            year=meta["year"],
            scope=meta["scope"],
            restated=bool(meta["restated"]),
            period_label=period.get("period_label"),
            measure=meta.get("measure") or None,
            period_kind=period.get("period_kind"),
            source_period_label=period.get("source_period_label"),
            period_year=period.get("period_year"),
            period_month=period.get("period_month"),
            period_day=period.get("period_day"),
            period_precision=period.get("period_precision"),
            period_date=period.get("period_date"),
            period_identity=period.get("period_identity"),
            period_normalization_evidence=period.get(
                "period_normalization_evidence"
            ),
        ))

    # Unit search includes the whole start page to catch "单位：" above the ROI title.
    all_start_lines = _page_lines(doc, roi["start_page"])
    from document_context_resolver import DocumentContextResolver
    context_resolver = DocumentContextResolver(doc)
    start_context = context_resolver.resolve(roi["start_page"])
    certified_unit_map = {
        "RMB": "元",
        "RMB_YUAN": "元",
        "RMB_THOUSAND": "千元",
        "RMB_TEN_THOUSAND": "万元",
        "RMB_MILLION": "百万元",
        "RMB_HUNDRED_MILLION": "亿元",
        "CNY": "元",
        "CNY_THOUSAND": "千元",
        "CNY_TEN_THOUSAND": "万元",
        "CNY_MILLION": "百万元",
        "CNY_HUNDRED_MILLION": "亿元",
    }
    certified_unit_raw = str(certified_amount_unit or "").strip()
    certified_unit = certified_unit_map.get(
        certified_unit_raw.upper(), certified_unit_raw or None,
    )
    native_unit = _extract_unit(all_start_lines) or start_context.unit
    # A Direct target's Stage-A amount unit is the certified contract for the
    # physical asset.  Native page context remains the fallback for legacy or
    # non-Direct captures, but must not override a certified unit discovered
    # for this table.
    unit = certified_unit or native_unit

    physical_segment_plans: list[dict[str, Any]] = []
    physical_segments_by_page: dict[int, list[dict[str, Any]]] = {}
    if stacked_sections:
        physical_segment_plans, physical_segments_by_page = (
            _plan_stacked_physical_table_segments(
                lines_by_page,
                roi["page_widths"],
                stacked_sections,
                note_identity=str(roi.get("resolved_note_number") or note_number or ""),
                table_identity=str(
                    certified_target_heading
                    or table_query
                    or roi.get("located_title")
                    or ""
                ),
                unit=unit,
            )
        )
    else:
        (
            physical_segment_plans,
            physical_segments_by_page,
            additional_column_metadata,
        ) = _plan_physical_table_segments(
            lines_by_page,
            roi["page_widths"],
            start_page=int(roi["start_page"]),
            end_page=int(roi["end_page"]),
            root_header=header,
            root_metadata=metadata,
            root_header_bottom=float(header_bottom),
            note_identity=str(roi.get("resolved_note_number") or note_number or ""),
            table_identity=str(
                certified_target_heading
                or table_query
                or roi.get("located_title")
                or ""
            ),
            unit=unit,
        )
        for meta in additional_column_metadata:
            tokens = list(meta.get("tokens") or [])
            period = normalize_period_fields(
                source_period_label=meta.get("source_period_label"),
                period_label=meta.get("period_label"),
                year=meta.get("year"),
            )
            columns.append(TableColumn(
                ordinal=int(meta["ordinal"]),
                source_column_index=int(meta["source_column_index"]),
                header_raw=" | ".join(tokens),
                year=meta.get("year"),
                scope=meta.get("scope"),
                restated=bool(meta.get("restated")),
                period_label=period.get("period_label"),
                measure=meta.get("measure") or None,
                period_kind=period.get("period_kind"),
                source_period_label=period.get("source_period_label"),
                period_year=period.get("period_year"),
                period_month=period.get("period_month"),
                period_day=period.get("period_day"),
                period_precision=period.get("period_precision"),
                period_date=period.get("period_date"),
                period_identity=period.get("period_identity"),
                period_normalization_evidence=period.get(
                    "period_normalization_evidence"
                ),
            ))

    _apply_certified_segment_identity(
        physical_segment_plans,
        certified_column_context,
    )

    rows: list[Any] = []
    row_order = 0
    parent_section = None
    parent_section_x0: Optional[float] = None
    unresolved_text_fragments: list[dict[str, Any]] = []
    active_candidate: Optional[LogicalRowCandidate] = None
    source_pages = []
    active_vertical_section_index: Optional[int] = None

    for page_no in range(roi["start_page"], roi["end_page"] + 1):
        lines = lines_by_page[page_no]
        page_width = roi["page_widths"][page_no]
        page_context = context_resolver.resolve(page_no)
        page_native_unit = _extract_unit(lines) or page_context.unit
        page_unit = certified_unit or page_native_unit or unit
        page_stacked_sections = _vertical_sections_for_page(
            stacked_sections,
            stacked_occurrences_by_page,
            page_no=page_no,
            page_width=page_width,
            active_section_index=active_vertical_section_index,
        )
        page_physical_segments = list(
            physical_segments_by_page.get(page_no, [])
        )

        # A page can contain more than one physical segment.  Derive numeric
        # lanes inside each segment's own y-range so a same-width supplementary
        # block cannot accidentally inherit the primary block's x topology.
        segment_numeric_assignment_anchors: dict[str, list[float] | None] = {}
        for segment_plan in page_physical_segments:
            segment_id = str(segment_plan["segment_id"])
            segment_numeric = _numeric_column_clusters(
                lines,
                header_y1=float(segment_plan["data_y_min"]) - 8.0,
                page_width=float(page_width),
                body_end_y=float(segment_plan["segment_y1"]),
            )
            segment_numeric_assignment_anchors[segment_id] = (
                _validated_numeric_assignment_anchors(
                    list(segment_plan["anchors"]),
                    segment_numeric,
                    page_width=float(page_width),
                    require_body_bounded=True,
                )
            )

        stacked_numeric_assignment_anchors: dict[str, list[float] | None] = {}
        for section in page_stacked_sections:
            section_index = int(section["section_index"])
            next_section_boundaries = [
                float(next_section["header"].get("header_y0", 0.0))
                for next_section in page_stacked_sections
                if int(next_section["section_index"]) > section_index
            ]
            section_end = (
                min(next_section_boundaries)
                if next_section_boundaries
                else max(
                    (
                        float(item.get("y1", 0.0))
                        for item in lines
                    ),
                    default=float(section["data_y_min"]),
                )
            )
            section_numeric = _numeric_column_clusters(
                lines,
                header_y1=float(section["data_y_min"]) - 8.0,
                page_width=float(page_width),
                body_end_y=section_end,
            )
            stacked_numeric_assignment_anchors[str(section["block_id"])] = (
                _validated_numeric_assignment_anchors(
                    list(section["anchors"]),
                    section_numeric,
                    page_width=float(page_width),
                    require_body_bounded=True,
                )
            )

        # HARD context reset on root page. Continuation pages may repeat headers;
        # if so, use their own anchors. Otherwise inherit normalized root anchors.
        current_header = _detect_header(
            lines,
            page_width,
            parser_mode=header_arbitration["selected_parser"],
        )
        page_numeric_assignment_anchors: list[float] | None = None
        if page_stacked_sections:
            anchors = list(page_stacked_sections[0]["anchors"])
            data_y_min = float(page_stacked_sections[0]["data_y_min"])
            header_source_page = page_stacked_sections[0].get("header_source_page")
        elif page_no == roi["start_page"]:
            anchors = list(header["anchors"])
            page_numeric_assignment_anchors = root_numeric_assignment_anchors
            data_y_min = header_bottom + 2
            header_source_page = None
        elif current_header and len(current_header["anchors"]) == len(columns):
            anchors = list(current_header["anchors"])
            current_meta, current_bottom = _header_metadata(lines, current_header, page_width)
            current_end = _primary_table_end_y(
                lines,
                header_y1=float(current_header["header_y1"]),
            )
            current_numeric = _numeric_column_clusters(
                lines,
                header_y1=float(current_header["header_y1"]),
                page_width=float(page_width),
                body_end_y=current_end,
            )
            page_numeric_assignment_anchors = _validated_numeric_assignment_anchors(
                anchors,
                current_numeric,
                page_width=float(page_width),
                require_body_bounded=True,
            )
            data_y_min = current_bottom + 2
            header_source_page = None
        else:
            anchors = [r * page_width for r in anchor_ratios]
            inherited_numeric = _numeric_column_clusters(
                lines,
                header_y1=-10.0,
                page_width=float(page_width),
            )
            page_numeric_assignment_anchors = _validated_numeric_assignment_anchors(
                anchors,
                inherited_numeric,
                page_width=float(page_width),
                require_body_bounded=True,
            )
            data_y_min = 0.0
            header_source_page = roi["start_page"]

        page_rows_before = len(rows)

        for line_index, line in enumerate(lines):
            active_column_offset = 0
            active_block_id = f"spatial_p{page_no}"
            active_expected_columns = len(anchors)
            active_section = None
            line_numeric_assignment_anchors = page_numeric_assignment_anchors
            if page_stacked_sections:
                active_section = _active_vertical_section(
                    page_stacked_sections,
                    float(line["y0"]),
                )
                if active_section is None:
                    continue
                anchors = list(active_section["anchors"])
                line_numeric_assignment_anchors = None
                line_numeric_assignment_anchors = (
                    stacked_numeric_assignment_anchors.get(
                        str(active_section["block_id"])
                    )
                )
                data_y_min = float(active_section["data_y_min"])
                active_column_offset = int(active_section["column_offset"])
                active_block_id = str(active_section["block_id"])
                active_expected_columns = int(active_section["column_count"])
                header_source_page = active_section.get("header_source_page")
                active_vertical_section_index = int(active_section["section_index"])
                active_group = stacked_sections[active_vertical_section_index]
                if page_no not in active_group["source_pages"]:
                    active_group["source_pages"].append(page_no)
            elif page_physical_segments:
                active_physical_segment = _active_physical_segment(
                    page_physical_segments,
                    float(line["y0"]),
                )
                if active_physical_segment is None:
                    continue
                anchors = list(active_physical_segment["anchors"])
                line_numeric_assignment_anchors = (
                    segment_numeric_assignment_anchors.get(
                        str(active_physical_segment["segment_id"])
                    )
                )
                data_y_min = float(active_physical_segment["data_y_min"])
                active_column_offset = int(active_physical_segment["column_offset"])
                active_block_id = str(active_physical_segment["segment_id"])
                active_expected_columns = int(active_physical_segment["column_count"])
                header_source_page = active_physical_segment.get("header_source_page")
            if line["y1"] < data_y_min:
                continue
            if active_candidate and (active_candidate.active_block_id != active_block_id or active_candidate.page_no != page_no):
                active_candidate, row_order, parent_section, parent_section_x0 = _commit_active_candidate_if_any(
                    active_candidate, rows, row_order, parent_section, parent_section_x0,
                    columns, page_context, page_unit, page_native_unit, certified_unit, certified_unit_raw, page_footnote_context
                )
            if unresolved_text_fragments and any(str(f.get("block_id") or "") != active_block_id for f in unresolved_text_fragments):
                row_order, parent_section, parent_section_x0 = _flush_pending_fragments(
                    unresolved_text_fragments, rows, row_order, parent_section, roi["start_page"], page_footnote_context, parent_section_x0,
                    lines=lines, current_line_index=line_index, anchors=anchors,
                    page_width=page_width, numeric_anchors=line_numeric_assignment_anchors,
                )
                parent_section = None
                parent_section_x0 = None
            # ``primary_table_end_y`` is segmentation evidence only.  A note
            # container may contain several same-topology classification
            # blocks after a local total, so every line up to the resolved peer
            # note boundary must reach the row parser.  Compound segmentation
            # below the capture primitive decides which rows form child blocks.

            layout_noise_role = _report_page_chrome_role(
                line,
                float(roi["page_heights"].get(page_no, 0.0) or 0.0),
            )
            if layout_noise_role:
                row_order += 1
                _append_layout_noise_row(
                    rows,
                    row_order=row_order,
                    page=page_no,
                    line=line,
                    row_role=layout_noise_role,
                    block_id=active_block_id,
                )
                continue

            parsed = _line_to_spatial_cells(
                line,
                anchors,
                page_width,
                numeric_anchors=line_numeric_assignment_anchors,
            )
            label = clean_cell(parsed["label"])
            compact = _line_compact(label)
            from semantic_row_parser import classify_non_data_text, classify_cell_role
            semantic_row_type = classify_non_data_text(
                line.get("text") or label,
                numeric_cell_count=sum(
                    1 for raw, number, _ in parsed["values"]
                    if raw and number is not None
                ),
                expected_numeric_columns=active_expected_columns,
            )

            # Ignore title/header/prose rows.
            if not label and not parsed["has_numeric"]:
                continue
            if label and (
                _contains_period_header(label)
                or _is_unit_only_header(label)
                or compact in {"本集团", "本公司", "项目", "费用项目"}
            ):
                continue
            if (
                label
                and len(label) > 55
                and not parsed["has_numeric"]
                and not semantic_row_type
            ):
                # Introductory prose sentence.
                continue

            from investment_portfolio_axis_semantics import recognise_portfolio_axis_boundary
            axis_boundary = recognise_portfolio_axis_boundary(line.get("text") or label)
            if not parsed["has_numeric"] and axis_boundary.is_boundary:
                active_candidate, row_order, parent_section, parent_section_x0 = _commit_active_candidate_if_any(
                    active_candidate, rows, row_order, parent_section, parent_section_x0,
                    columns, page_context, page_unit, page_native_unit, certified_unit, certified_unit_raw, page_footnote_context
                )
                if unresolved_text_fragments:
                    row_order, parent_section, parent_section_x0 = _flush_pending_fragments(
                        unresolved_text_fragments, rows, row_order, parent_section, roi["start_page"], page_footnote_context, parent_section_x0,
                        lines=lines, current_line_index=line_index, anchors=anchors,
                        page_width=page_width, numeric_anchors=line_numeric_assignment_anchors,
                    )
                row_order += 1
                _append_text_only_row(
                    rows,
                    row_order=row_order,
                    page=page_no,
                    text=clean_cell(line.get("text") or label),
                    parent_section=None,
                    header_source_page=(
                        roi["start_page"] if page_no > roi["start_page"] else None
                    ),
                    as_section=False,
                    row_type_override="CLASSIFICATION_AXIS",
                    block_id=active_block_id,
                    bbox={
                        "x0": float(line["x0"]), "y0": float(line["y0"]),
                        "x1": float(line["x1"]), "y1": float(line["y1"]),
                    },
                    page_footnote_context=page_footnote_context,
                )
                parent_section = None
                parent_section_x0 = None
                continue

            if semantic_row_type:
                active_candidate, row_order, parent_section, parent_section_x0 = _commit_active_candidate_if_any(
                    active_candidate, rows, row_order, parent_section, parent_section_x0,
                    columns, page_context, page_unit, page_native_unit, certified_unit, certified_unit_raw, page_footnote_context
                )
                if unresolved_text_fragments:
                    row_order, parent_section, parent_section_x0 = _flush_pending_fragments(
                        unresolved_text_fragments, rows, row_order, parent_section, roi["start_page"], page_footnote_context, parent_section_x0,
                        lines=lines, current_line_index=line_index, anchors=anchors,
                        page_width=page_width, numeric_anchors=line_numeric_assignment_anchors,
                    )
                row_order += 1
                _append_text_only_row(
                    rows,
                    row_order=row_order,
                    page=page_no,
                    text=clean_cell(line.get("text") or label),
                    parent_section=parent_section,
                    header_source_page=(
                        roi["start_page"] if page_no > roi["start_page"] else None
                    ),
                    as_section=False,
                    row_type_override=semantic_row_type,
                    block_id=active_block_id,
                    bbox={
                        "x0": float(line["x0"]), "y0": float(line["y0"]),
                        "x1": float(line["x1"]), "y1": float(line["y1"]),
                    },
                    page_footnote_context=page_footnote_context,
                )
                continue

            if parsed["has_numeric"]:
                active_candidate, row_order, parent_section, parent_section_x0 = _commit_active_candidate_if_any(
                    active_candidate, rows, row_order, parent_section, parent_section_x0,
                    columns, page_context, page_unit, page_native_unit, certified_unit, certified_unit_raw, page_footnote_context
                )

                prefix_fragments, remaining_unresolved = _resolve_anchor_prefix_candidates(
                    unresolved_text_fragments,
                    line,
                    parsed,
                    lines,
                    line_index,
                    page_no=page_no,
                    active_block_id=active_block_id,
                    anchors=anchors,
                    page_width=page_width,
                    numeric_anchors=line_numeric_assignment_anchors,
                )
                if remaining_unresolved:
                    row_order, parent_section, parent_section_x0 = _flush_pending_fragments(
                        remaining_unresolved,
                        rows,
                        row_order,
                        parent_section,
                        roi["start_page"],
                        page_footnote_context,
                        parent_section_x0,
                        lines=lines,
                        current_line_index=line_index,
                        anchors=anchors,
                        page_width=page_width,
                        numeric_anchors=line_numeric_assignment_anchors,
                    )
                unresolved_text_fragments.clear()

                active_candidate = LogicalRowCandidate(
                    prefix_fragments=prefix_fragments,
                    anchor_fragment={
                        "label": clean_cell(parsed.get("raw_label") or label or ""),
                        "x0": float(parsed.get("label_x0", line.get("x0", 0.0))),
                        "y0": float(line.get("y0", 0.0)),
                        "y1": float(line.get("y1", 0.0)),
                        "page": page_no,
                        "block_id": active_block_id,
                    },
                    suffix_fragments=[],
                    parsed_values=parsed["values"],
                    parsed_line=parsed,
                    line=line,
                    active_block_id=active_block_id,
                    page_no=page_no,
                    header_source_page=header_source_page,
                    active_column_offset=active_column_offset,
                    active_expected_columns=active_expected_columns,
                )
            else:
                if not label:
                    continue

                if active_candidate is not None and _is_valid_suffix_candidate(
                    active_candidate,
                    line,
                    parsed,
                    page_no=page_no,
                    active_block_id=active_block_id,
                    page_width=page_width,
                ):
                    active_candidate.suffix_fragments.append({
                        "text": label,
                        "x0": float(parsed.get("label_x0", line.get("x0", 0.0))),
                        "y0": float(line.get("y0", 0.0)),
                        "y1": float(line.get("y1", 0.0)),
                        "page": page_no,
                        "block_id": active_block_id,
                    })
                    combined_now = "".join(
                        [f["text"] for f in active_candidate.prefix_fragments]
                        + [active_candidate.anchor_fragment.get("label", "")]
                        + [f["text"] for f in active_candidate.suffix_fragments]
                    )
                    from table_capture import normalize_item_label
                    if any(pat in normalize_item_label(combined_now) for pat in ("金融资产", "债权投资", "股权投资", "股权计划", "信托计划", "基金", "理财产品", "现金等价物", "定期存款", "长期股权投资", "投资性房地产")):
                        active_candidate, row_order, parent_section, parent_section_x0 = _commit_active_candidate_if_any(
                            active_candidate, rows, row_order, parent_section, parent_section_x0,
                            columns, page_context, page_unit, page_native_unit, certified_unit, certified_unit_raw, page_footnote_context
                        )
                    continue

                active_candidate, row_order, parent_section, parent_section_x0 = _commit_active_candidate_if_any(
                    active_candidate, rows, row_order, parent_section, parent_section_x0,
                    columns, page_context, page_unit, page_native_unit, certified_unit, certified_unit_raw, page_footnote_context
                )

                if _is_explicit_section_label(label):
                    if unresolved_text_fragments:
                        row_order, parent_section, parent_section_x0 = _flush_pending_fragments(
                            unresolved_text_fragments, rows, row_order, parent_section, roi["start_page"], page_footnote_context, parent_section_x0,
                            lines=lines, current_line_index=line_index, anchors=anchors,
                            page_width=page_width, numeric_anchors=line_numeric_assignment_anchors,
                        )
                    row_order += 1
                    sec_norm = _append_text_only_row(
                        rows,
                        row_order=row_order,
                        page=page_no,
                        text=label,
                        parent_section=parent_section,
                        header_source_page=(
                            roi["start_page"] if page_no > roi["start_page"] else None
                        ),
                        as_section=True,
                        row_type_override="PARENT_SECTION",
                        block_id=active_block_id,
                        bbox=dict(line.get("bbox") or {
                            "x0": float(line["x0"]), "y0": float(line["y0"]),
                            "x1": float(line["x1"]), "y1": float(line["y1"]),
                        }),
                        page_footnote_context=page_footnote_context,
                    )
                    parent_section = sec_norm
                    parent_section_x0 = float(parsed["label_x0"])
                else:
                    unresolved_text_fragments.append({
                        "text": label,
                        "x0": float(parsed["label_x0"]),
                        "y0": float(line["y0"]),
                        "y1": float(line["y1"]),
                        "page": page_no,
                        "block_id": active_block_id,
                        "bbox": dict(line.get("bbox") or {
                            "x0": float(line["x0"]), "y0": float(line["y0"]),
                            "x1": float(line["x1"]), "y1": float(line["y1"]),
                        }),
                    })
                    if len(unresolved_text_fragments) > 4:
                        oldest = [unresolved_text_fragments.pop(0)]
                        row_order, parent_section, parent_section_x0 = _flush_pending_fragments(
                            oldest, rows, row_order, parent_section, roi["start_page"], page_footnote_context, parent_section_x0,
                            lines=lines, current_line_index=line_index, anchors=anchors,
                            page_width=page_width, numeric_anchors=line_numeric_assignment_anchors,
                        )

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

    active_candidate, row_order, parent_section, parent_section_x0 = _commit_active_candidate_if_any(
        active_candidate, rows, row_order, parent_section, parent_section_x0,
        columns, page_context, page_unit, page_native_unit, certified_unit, certified_unit_raw, page_footnote_context
    )
    if unresolved_text_fragments:
        _flush_geo_kwargs: dict[str, Any] = {}
        if "lines" in locals() and lines and "line_index" in locals() and "anchors" in locals() and anchors and "page_width" in locals() and page_width:
            _flush_geo_kwargs = dict(
                lines=lines,
                current_line_index=line_index,
                anchors=anchors,
                page_width=page_width,
                numeric_anchors=locals().get("line_numeric_assignment_anchors"),
            )
        row_order, parent_section, parent_section_x0 = _flush_pending_fragments(
            unresolved_text_fragments, rows, row_order, parent_section, roi["start_page"], page_footnote_context, parent_section_x0,
            **_flush_geo_kwargs,
        )

    doc.close()

    # Do this after all continuation pages have been materialised so the
    # anonymous value can be reconciled against its immediate breakdown rows.
    from implicit_total_rows import recover_implicit_total_rows
    rows = recover_implicit_total_rows(rows, parent_table=table_query)
    _mark_tail_page_number_noise(rows, roi)
    _mark_side_page_number_noise(rows, roi)
    _mark_report_footer_noise(rows)
    provisional_result = TableCaptureResult(
        pdf_name=Path(pdf_path).name,
        pdf_sha256=file_sha256(pdf_path),
        table_query=table_query,
        note_number=note_number,
        located_title=certified_target_heading or table_query,
        start_page=int(roi["start_page"]),
        end_page=int(roi["end_page"]),
        pages=list(range(int(roi["start_page"]), int(roi["end_page"]) + 1)),
        unit=unit,
        columns=columns,
        rows=rows,
        warnings=[],
        stats={"physical_table_id": physical_table_id},
        physical_table_id=physical_table_id,
    )
    assign_source_row_identities(provisional_result)
    numeric_parent_hierarchy = _infer_numeric_parent_hierarchy(rows)
    finalized_hierarchy = _finalize_hierarchy_semantics(rows)
    graph_validation = validate_hierarchy_graph(rows)
    provisional_result.stats["hierarchy_graph_validation"] = graph_validation
    if graph_validation["status"] != "VALID":
        if graph_validation["dangling_edges"]:
            provisional_result.warnings.append(
                f"HIERARCHY_GRAPH_DANGLING_EDGES: 发现 {len(graph_validation['dangling_edges'])} 条悬空父子边。"
            )
        if graph_validation["cycle_edges"]:
            provisional_result.warnings.append(
                f"HIERARCHY_GRAPH_CYCLE_EDGES: 发现 {len(graph_validation['cycle_edges'])} 条循环层级边。"
            )

    physical_segment_payloads = []
    physical_segment_block_ids: dict[str, list[str]] = {}
    for plan in physical_segment_plans:
        segment = plan["segment"]
        segment_page = int(segment.pdf_page_number)
        segment_y0 = float(segment.bbox[1])
        segment_y1 = float(segment.bbox[3])
        segment_id = str(plan["segment_id"])
        block_ids: set[str] = set()
        for row in rows:
            if int(row.page) != segment_page:
                continue
            row_bbox = row.bbox or {}
            row_y0 = float(row_bbox.get("y0", segment_y0))
            row_y1 = float(row_bbox.get("y1", row_y0))
            if row_y1 < segment_y0 or row_y0 > segment_y1:
                continue
            row.physical_segment_id = segment_id
            if row.block_id:
                block_ids.add(str(row.block_id))
        physical_segment_block_ids[segment_id] = sorted(block_ids)
        payload = plan["segment"].to_dict()
        segment_rows = [
            row
            for row in rows
            if str(getattr(row, "physical_segment_id", "") or "") == segment_id
            or str(row.block_id or "") == segment_id
        ]
        if segment_rows:
            payload["row_order_start"] = min(row.row_order for row in segment_rows)
            payload["row_order_end"] = max(row.row_order for row in segment_rows)
        physical_segment_payloads.append(payload)

    if not rows or not any(r.cells for r in rows):
        raise ValueError("空间ROI已定位并识别表头，但未重建出有效数值明细行。")

    warnings = []
    selected_metrics = (
        header_arbitration.get("candidates", {})
        .get(header_arbitration.get("selected_parser"), {})
    )
    if header_arbitration.get("mode") != "AUTO":
        warnings.append(
            "HEADER_PARSER_USER_OVERRIDE：本次整表按人工指定算法 "
            f"{header_arbitration.get('selected_parser')} 解析；"
            f"自动推荐={header_arbitration.get('auto_selected_parser')}。"
        )
    elif selected_metrics.get("status") == "VALID":
        warnings.append(
            "HEADER_PARSER_AUTO_SELECTED："
            f"{header_arbitration.get('selected_parser')}；"
            f"numeric_clusters={selected_metrics.get('numeric_cluster_count')}；"
            f"leaf_columns={selected_metrics.get('leaf_count')}。"
        )

    unresolved_amount_cells = sum(
        1
        for row in rows
        for cell in row.cells
        if str(getattr(
            next((column for column in columns if column.ordinal == cell.column_ordinal), None),
            "measure", "",
        ) or "").strip() == "金额"
        and not str(cell.unit_original or "").strip()
    )
    if unit is None:
        warnings.append("未在目标附注首页识别到明确单位；原始单位保持UNKNOWN，不做金额单位推断。")
    if unresolved_amount_cells:
        warnings.append(
            "UNIT_UNRESOLVED_AMOUNT_OBSERVATION："
            f"{unresolved_amount_cells} 个金额 observation 缺少认证单位，不得进入 Merge。"
        )
    if roi.get("boundary_confidence") == "LOW":
        warnings.append("BOUNDARY_REVIEW_REQUIRED：未发现可信的下一同级附注标题，请人工核对末尾。")
    mixed_cell_count = sum(
        1
        for row in rows
        for cell in row.cells
        if getattr(cell, "cell_role", "NUMERIC") == "MIXED"
    )
    if mixed_cell_count:
        warnings.append(
            f"MIXED_CELL_REVIEW_REQUIRED：检测到 {mixed_cell_count} 个文本/数字混合单元格。"
        )
    unresolved_segments = [
        segment
        for segment in physical_segment_payloads
        if segment.get("classification") == "UNRESOLVED"
    ]
    if unresolved_segments:
        warnings.append(
            "TABLE_SEGMENT_UNRESOLVED：检测到无法安全判定物理关系的表格片段；"
            "未自动归入续表或补充表。"
        )

    if progress_callback:
        progress_callback({"event": "done", "message": "空间整表重建完成"})

    capture_result = TableCaptureResult(
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
        physical_table_id=physical_table_id,
        stats={
            "engine": "SPATIAL_ROI_DUAL_HEADER_V1",
            "header_parser": header_arbitration.get("selected_parser"),
            "header_arbitration": header_arbitration,
            "source_pdf_path": str(Path(pdf_path).resolve()),
            "physical_table_id": physical_table_id,
            "hierarchy_graph_validation": graph_validation,
            "document_context": {
                **start_context.as_dict(),
                "unit": unit,
                "unit_source": (
                    "NATIVE_PAGE_CONTEXT" if native_unit
                    else ("CERTIFIED_DIRECT_AMOUNT_UNIT" if certified_unit else None)
                ),
            },
            "boundary_reason": roi["boundary_reason"],
            "boundary_confidence": roi.get("boundary_confidence", "LOW"),
            "boundary_evidence": roi.get("boundary_evidence") or {},
            "note_number_source": roi.get("note_number_source"),
            "resolved_note_number": roi.get("resolved_note_number"),
            "roi": {
                "start_page": roi["start_page"], "start_y": roi["start_y"],
                "end_page": roi["end_page"], "end_y": roi["end_y"],
                "certified_page_bboxes": roi.get("certified_page_bboxes") or {},
                "row_membership_semantics": roi.get(
                    "certified_roi_row_membership_semantics"
                ),
                "identity_source": roi.get("identity_source") or "TITLE",
            },
            "logical_columns": len(columns),
            "vertical_period_column_groups": [
                {
                    "block_id": section["block_id"],
                    "source_column_ordinals": list(range(
                        int(section["column_offset"]),
                        int(section["column_offset"])
                        + int(section["column_count"]),
                    )),
                    "period_labels": list(section["period_labels"]),
                    "measure_labels": list(section["measure_labels"]),
                    "data_y_min": float(section["data_y_min"]),
                    "header_page": int(section["header_page"]),
                    "header_y0": float(section["header_y0"]),
                    "source_pages": list(section["source_pages"]),
                }
                for section in stacked_sections
            ],
            "physical_table_segments": physical_segment_payloads,
            "physical_segment_column_groups": [
                {
                    "segment_id": str(plan["segment_id"]),
                    "source_column_ordinals": list(plan["source_column_ordinals"]),
                    "classification": plan["segment"].classification.value,
                    "continuation_of_segment_id": (
                        plan["segment"].continuation_of_segment_id
                    ),
                }
                for plan in physical_segment_plans
            ],
            "physical_segment_block_ids": physical_segment_block_ids,
            "primary_table_end_y": primary_table_end_y,
            "primary_table_end_applied": False,
            "post_total_disclosure_not_merged": False,
            "rows": len(rows),
            "numeric_rows": sum(bool(r.cells) for r in rows),
            "numeric_parent_hierarchy": numeric_parent_hierarchy,
            "numeric_parent_hierarchy_count": len(numeric_parent_hierarchy),
            "mixed_cell_count": mixed_cell_count,
            "unresolved_amount_unit_cell_count": unresolved_amount_cells,
            "memo_text_rows": sum(r.row_type == "MEMO_TEXT" for r in rows),
            "note_text_rows": sum(r.row_type == "NOTE_TEXT" for r in rows),
        },
        document_context={
            **start_context.as_dict(),
            "unit": unit,
            "unit_source": (
                "NATIVE_PAGE_CONTEXT" if native_unit
                else ("CERTIFIED_DIRECT_AMOUNT_UNIT" if certified_unit else None)
            ),
        },
    )
    from compound_note_engine import certify_direct_row_footnotes
    certify_direct_row_footnotes(
        capture_result,
        Path(pdf_path),
        certified_segments or [{"start_page": roi["start_page"], "pdf_page_number": roi["start_page"]}],
    )
    return capture_result
