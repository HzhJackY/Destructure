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

    # De-duplicate overlapping detections, keeping maximal semantic spans.
    # This prevents 2024 + 2024年度 (or 本年 + 本年累计数) from becoming
    # duplicate physical leaf columns.
    candidates.sort(key=lambda h: (-h["_span_len"], -(h["x1"]-h["x0"]), h["xc"]))
    selected: list[dict[str, Any]] = []
    for hit in candidates:
        duplicate=False
        for old in selected:
            same_semantic=(
                hit.get("year")==old.get("year")
                and hit.get("period_kind")==old.get("period_kind")
            )
            same_baseline=abs(hit["yc"]-old["yc"])<=7
            overlap=max(0.0,min(hit["x1"],old["x1"])-max(hit["x0"],old["x0"]))
            denom=max(1.0,min(hit["x1"]-hit["x0"],old["x1"]-old["x0"]))
            overlap_ratio=overlap/denom
            if same_semantic and same_baseline and (
                overlap_ratio>=0.55 or abs(hit["xc"]-old["xc"])<=10
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
            if len(set(years))!=1:
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
            if not _is_numeric_fragment(w["text"]):
                continue
            # exclude bare 4-digit years in possible repeated headers
            compact=_line_compact(w["text"])
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
    }


def _primary_table_end_y(lines:list[dict[str,Any]], *, header_y1:float)->float|None:
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
        has_number=any(_is_numeric_fragment(w.get("text", "")) for w in line.get("words") or [])
        # Test for prose before updating ``last_data_y``: footnote markers such
        # as “(1)” are numeric fragments but are not table values.
        if (
            last_total_y is not None
            and line["y0"] > last_total_y
            and len(text) >= 24
            and not compact.startswith(("其中", "注", "说明"))
        ):
            return last_data_y or last_total_y
        if has_total and has_number:
            last_total_y=float(line["y1"])
            last_data_y=last_total_y
            continue
        if last_total_y is not None and has_number:
            last_data_y=float(line["y1"])
    return None


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
        elif leaf_count+1<numeric_count:
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
    if len(original) < 1 or numeric["count"] <= len(original):
        return header
    centers = [float(x) for x in numeric["centers"]]
    # Only accept a repeated-measure topology when nearby header text actually
    # names a measure at the discovered numeric centers.
    labels: list[str] = []
    for center in centers:
        matches=[]
        for line in lines[max(0, int(header["line_index"]) - 1): min(len(lines), int(header["line_index"]) + 8)]:
            for word in line.get("words") or []:
                text=clean_cell(word.get("text", ""))
                norm=normalize_text(text)
                if ("账面值" in norm or "比例" in norm or "收益率" in norm or "金额" in norm) and abs(float(word["xc"])-center) <= max(30.0, page_width*.045):
                    matches.append(text)
        labels.append(matches[0] if matches else "")
    # This promotion is deliberately narrow: it is for repeated *measures*
    # (e.g. 账面值 + 占比), not ordinary multi-year balance-sheet tables that
    # happen to mention a value/balance label once in their header.
    if not all(labels) or not any("比例" in normalize_text(x) for x in labels) or len({normalize_text(x) for x in labels}) < 2:
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
    })
    return expanded


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
) -> dict[str, Any]:
    doc = fitz.open(str(pdf_path))
    note_reference_raw = str(note_number).strip() if note_number else None
    from table_boundary_resolver import parse_note_ordinal, resolve_table_boundary
    parsed_note_ordinal = parse_note_ordinal(note_reference_raw)
    note_number = str(parsed_note_ordinal) if parsed_note_ordinal is not None else note_reference_raw

    best = None
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
            doc.close()
            raise ValueError(
                "CERTIFIED_TARGET_HEADING_MISMATCH：认证页中未找到匹配的"
                f"附注标题（note={note_reference_raw}, table={table_query}）。"
            )
        title_line = max(candidates, key=lambda x: x[0])[1] if candidates else {
            "text": table_query, "y0": 0.0, "y1": 0.0, "x0": 0.0,
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
    )
    end_page = int(boundary["end_page"])
    end_y = float(boundary["end_y"])
    boundary_reason = str(boundary["boundary_reason"])

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
        "boundary_confidence": boundary["boundary_confidence"],
        "boundary_evidence": boundary["boundary_evidence"],
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
            assigned[i]=hits[region]
        return assigned

    nearest=hits[0]
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
    row_type_override: Optional[str] = None,
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
        row_type=row_type_override or ("SECTION_HEADER" if as_section else "DETAIL"),
        row_level=0 if as_section else (1 if parent_section else 0),
        parent_section=None if as_section else parent_section,
        cells=[],
        header_source_page=header_source_page,
        row_role=row_type_override or ("SECTION_HEADER" if as_section else "DETAIL"),
        row_item_raw=text,
        row_item_normalized=norm,
        label_derivation="EXPLICIT_TEXT",
    ))
    return norm


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
        strict_target_identity=strict_target_identity,
        certified_target_heading=certified_target_heading,
    )
    doc = fitz.open(str(pdf_path))

    if progress_callback:
        progress_callback({"event": "open_done", "message": "已定位目标附注ROI"})

    start_lines = _lines_in_roi(doc, roi, roi["start_page"])
    try:
        header, header_arbitration = _arbitrate_header_candidates(
            start_lines,
            roi["page_widths"][roi["start_page"]],
            parser_mode=header_parser_mode,
        )
    except Exception:
        doc.close()
        raise

    metadata, header_bottom = _header_metadata(
        start_lines, header, roi["page_widths"][roi["start_page"]]
    )
    for i, hint in enumerate(header.get("restated_hints") or []):
        if i < len(metadata) and hint:
            metadata[i]["restated"] = True
            if "已重述" not in metadata[i]["tokens"]:
                metadata[i]["tokens"].append("已重述")
    root_width = roi["page_widths"][roi["start_page"]]
    anchor_ratios = [a / root_width for a in header["anchors"]]
    primary_table_end_y = _primary_table_end_y(
        start_lines, header_y1=header_bottom,
    )

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
            measure=meta.get("measure") or None,
        ))

    # Unit search includes the whole start page to catch "单位：" above the ROI title.
    all_start_lines = _page_lines(doc, roi["start_page"])
    from document_context_resolver import DocumentContextResolver
    context_resolver = DocumentContextResolver(doc)
    start_context = context_resolver.resolve(roi["start_page"])
    unit = _extract_unit(all_start_lines) or start_context.unit

    rows: list[Any] = []
    row_order = 0
    parent_section = None
    pending: Optional[dict[str, Any]] = None
    source_pages = []

    for page_no in range(roi["start_page"], roi["end_page"] + 1):
        lines = _lines_in_roi(doc, roi, page_no)
        page_width = roi["page_widths"][page_no]
        page_context = context_resolver.resolve(page_no)
        page_unit = _extract_unit(lines) or page_context.unit or unit

        # HARD context reset on root page. Continuation pages may repeat headers;
        # if so, use their own anchors. Otherwise inherit normalized root anchors.
        current_header = _detect_header(
            lines,
            page_width,
            parser_mode=header_arbitration["selected_parser"],
        )
        if page_no == roi["start_page"]:
            anchors = header["anchors"]
            data_y_min = header_bottom + 2
            header_source_page = None
        elif current_header and len(current_header["anchors"]) == len(columns):
            anchors = current_header["anchors"]
            current_meta, current_bottom = _header_metadata(lines, current_header, page_width)
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
            # Do not fold a second, differently-shaped disclosure table into
            # the current note-detail table.  The first-table boundary is only
            # used when it was established from a total followed by prose.
            if (
                page_no == roi["start_page"]
                and primary_table_end_y is not None
                and line["y0"] > primary_table_end_y
            ):
                break

            parsed = _line_to_spatial_cells(line, anchors, page_width)
            label = clean_cell(parsed["label"])
            compact = _line_compact(label)
            from semantic_row_parser import classify_non_data_text, classify_cell_role
            semantic_row_type = classify_non_data_text(
                line.get("text") or label,
                numeric_cell_count=sum(
                    1 for raw, number, _ in parsed["values"]
                    if raw and number is not None
                ),
                expected_numeric_columns=len(columns),
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
            if semantic_row_type:
                if pending:
                    row_order += 1
                    _append_text_only_row(
                        rows,
                        row_order=row_order,
                        page=pending["page"],
                        text=pending["text"],
                        parent_section=parent_section,
                        header_source_page=(
                            roi["start_page"]
                            if pending["page"] > roi["start_page"] else None
                        ),
                        as_section=_is_explicit_section_label(pending["text"]),
                    )
                    pending = None
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
                )
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

                cells = []
                for i, (raw, number, cell_unit) in enumerate(parsed["values"]):
                    if not raw:
                        continue
                    if cell_unit == "%":
                        original_unit = "%"
                        value_yuan = None
                    else:
                        original_unit = cell_unit or page_unit
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
                        cell_role=classify_cell_role(raw, number),
                        context_source_page=page_context.unit_source_page,
                        currency=page_context.currency,
                    ))

                if not cells:
                    continue
                norm = normalize_item_label(label or "")
                row_type = classify_row_type(norm, True) if label else "DETAIL"
                row_role = row_type if label else "IMPLICIT_ROW_CANDIDATE"

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
                    raw_item=label or None,
                    normalized_item=norm,
                    canonical_item=None,
                    mapping_status="UNMAPPED",
                    row_type=row_type,
                    row_level=output_level,
                    parent_section=output_parent,
                    cells=cells,
                    header_source_page=header_source_page,
                    row_role=row_role,
                    row_item_raw=label or None,
                    row_item_normalized=norm or None,
                    label_derivation="EXPLICIT_TEXT" if label else "NONE",
                    bbox={
                        "x0": float(line["x0"]), "y0": float(line["y0"]),
                        "x1": float(line["x1"]), "y1": float(line["y1"]),
                    },
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

    # Do this after all continuation pages have been materialised so the
    # anonymous value can be reconciled against its immediate breakdown rows.
    from implicit_total_rows import recover_implicit_total_rows
    rows = recover_implicit_total_rows(rows, parent_table=table_query)

    if not rows or not any(r.cells for r in rows):
        raise ValueError("空间ROI已定位并识别表头，但未重建出有效数值明细行。")

    warnings = []
    if primary_table_end_y is not None:
        warnings.append(
            "POST_TOTAL_DISCLOSURE_NOT_MERGED：合计后出现独立说明或后续表格块；"
            "本 Capture 仅保存与主报表金额对应的首张明细表，后续内容保留在 PDF 证据范围内，"
            "不得被误并入本表。"
        )
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

    if unit is None:
        warnings.append("未在目标附注首页识别到明确单位；原始单位保持UNKNOWN，不做金额单位推断。")
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
            "engine": "SPATIAL_ROI_DUAL_HEADER_V1",
            "header_parser": header_arbitration.get("selected_parser"),
            "header_arbitration": header_arbitration,
            "source_pdf_path": str(Path(pdf_path).resolve()),
            "document_context": start_context.as_dict(),
            "boundary_reason": roi["boundary_reason"],
            "boundary_confidence": roi.get("boundary_confidence", "LOW"),
            "boundary_evidence": roi.get("boundary_evidence") or {},
            "note_number_source": roi.get("note_number_source"),
            "resolved_note_number": roi.get("resolved_note_number"),
            "roi": {
                "start_page": roi["start_page"], "start_y": roi["start_y"],
                "end_page": roi["end_page"], "end_y": roi["end_y"],
            },
            "logical_columns": len(columns),
            "primary_table_end_y": primary_table_end_y,
            "post_total_disclosure_not_merged": primary_table_end_y is not None,
            "rows": len(rows),
            "numeric_rows": sum(bool(r.cells) for r in rows),
            "mixed_cell_count": mixed_cell_count,
            "memo_text_rows": sum(r.row_type == "MEMO_TEXT" for r in rows),
            "note_text_rows": sum(r.row_type == "NOTE_TEXT" for r in rows),
        },
        document_context=start_context.as_dict(),
    )
