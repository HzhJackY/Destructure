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

_NOTE_LINE_RE = re.compile(r"^\s*(\d{1,3})\s*[\.．、]\s*(.+?)\s*$")
_YEAR_RE = re.compile(r"(20\d{2})")
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


def _title_score(line_text: str, table_query: str, note_number: Optional[str]) -> int:
    compact = _line_compact(line_text)
    q = _line_compact(table_query)
    score = 0
    if q and q in compact:
        score += 20
    m = _NOTE_LINE_RE.match(compact)
    if note_number and m and m.group(1) == str(note_number):
        score += 15
        if q and q in _line_compact(m.group(2)):
            score += 15
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
                if i + 1 < len(lines):
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

    hard_end_page = min(doc.page_count, start_page + max(1, int(max_pages)) - 1)
    end_page = hard_end_page
    end_y = float(doc[end_page - 1].rect.height)
    boundary_reason = "max_pages"

    # Strongest boundary: exact next numbered note, including same-page position.
    next_no = str(int(note_number) + 1) if note_number and note_number.isdigit() else None
    if next_no:
        for p in range(start_page, hard_end_page + 1):
            for line in _page_lines(doc, p):
                if p == start_page and line["y0"] <= start_y:
                    continue
                compact = _line_compact(line["text"])
                m = _NOTE_LINE_RE.match(compact)
                if m and m.group(1) == next_no:
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
    hits = []
    for w in line["words"]:
        m = _YEAR_RE.search(w["text"])
        if m:
            hits.append({**w, "year": m.group(1)})
    return hits


def _detect_header(
    lines: list[dict[str, Any]],
    page_width: float,
) -> Optional[dict[str, Any]]:
    candidates = []
    for i, line in enumerate(lines[:80]):
        hits = _year_words(line)
        if not hits:
            continue
        # Financial detail tables generally have 1-8 logical period/scope columns.
        if 1 <= len(hits) <= 8:
            spread = max(h["xc"] for h in hits) - min(h["xc"] for h in hits) if len(hits) > 1 else 0
            score = len(hits) * 10 + spread / max(page_width, 1) * 10
            candidates.append((score, i, line, hits))
    if not candidates:
        return None
    _, idx, line, hits = max(candidates, key=lambda x: x[0])
    hits = sorted(hits, key=lambda x: x["xc"])
    return {
        "line_index": idx,
        "line": line,
        "anchors": [h["xc"] for h in hits],
        "years": [h["year"] for h in hits],
        "header_y0": line["y0"],
        "header_y1": line["y1"],
    }


def _nearest_anchor_index(x: float, anchors: list[float]) -> int:
    return min(range(len(anchors)), key=lambda i: abs(x - anchors[i]))


def _column_half_widths(anchors: list[float], page_width: float) -> list[float]:
    if len(anchors) == 1:
        return [page_width * 0.18]
    widths = []
    for i, a in enumerate(anchors):
        left_gap = a - anchors[i - 1] if i > 0 else anchors[1] - a
        right_gap = anchors[i + 1] - a if i < len(anchors) - 1 else a - anchors[i - 1]
        widths.append(max(20.0, min(left_gap, right_gap) * 0.48))
    return widths


def _is_numeric_fragment(text: str) -> bool:
    s = re.sub(r"\s+", "", str(text))
    if not s:
        return False
    allowed = set("0123456789,.-—–()（）%％")
    return all(ch in allowed for ch in s) and any(ch.isdigit() for ch in s)


def _is_numeric_punct(text: str) -> bool:
    s = re.sub(r"\s+", "", str(text))
    return bool(s) and all(ch in "()（）-—–" for ch in s)


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


def _header_metadata(
    lines: list[dict[str, Any]],
    header: dict[str, Any],
    page_width: float,
) -> tuple[list[dict[str, Any]], float]:
    anchors = header["anchors"]
    years = header["years"]
    half = _column_half_widths(anchors, page_width)
    metadata = [
        {"year": years[i], "scope": None, "restated": False, "tokens": [years[i]]}
        for i in range(len(anchors))
    ]

    header_bottom = header["header_y1"]
    # Inspect a limited band below the year line until first plausible numeric data row.
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
            if any(normalize_text(x) in nt for x in ["本集团", "集团"]):
                metadata[idx]["scope"] = "本集团"
                metadata[idx]["tokens"].append(t)
                used = True
            if any(normalize_text(x) in nt for x in ["本公司", "公司"]):
                metadata[idx]["scope"] = "本公司"
                metadata[idx]["tokens"].append(t)
                used = True
            if any(normalize_text(x) in nt for x in ["已重述", "经重述", "重述"]):
                metadata[idx]["restated"] = True
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
            period_label=meta["year"],
        ))

    # Unit search includes the whole start page to catch "单位：" above the ROI title.
    all_start_lines = _page_lines(doc, roi["start_page"])
    unit = _extract_unit(all_start_lines)

    rows: list[Any] = []
    row_order = 0
    parent_section = None
    pending: Optional[dict[str, Any]] = None
    source_pages = []

    section_keywords = [
        "按费用项目", "可归属于保险合同组合的费用",
        "不可归属于保险合同组合的费用",
    ]

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
            if label and (_YEAR_RE.search(label) or compact in {"本集团", "本公司", "项目", "费用项目"}):
                continue
            if label and len(label) > 55 and not parsed["has_numeric"]:
                # Introductory prose sentence.
                continue

            if parsed["has_numeric"]:
                # Resolve pending text-only line: wrapped label vs section header.
                if pending:
                    pending_text = pending["text"]
                    is_section = (
                        pending_text.rstrip().endswith(("：", ":"))
                        or any(normalize_text(k) in normalize_text(pending_text) for k in section_keywords)
                        or pending["x0"] < parsed["label_x0"] - 8
                    )
                    if is_section:
                        row_order += 1
                        section_norm = normalize_item_label(pending_text)
                        rows.append(TableRow(
                            row_order=row_order,
                            page=pending["page"],
                            block_id=f"spatial_p{pending['page']}",
                            source_method="spatial_roi",
                            raw_item=pending_text,
                            normalized_item=section_norm,
                            canonical_item=None,
                            mapping_status="UNMAPPED",
                            row_type="SECTION_HEADER",
                            row_level=0,
                            parent_section=None,
                            cells=[],
                            header_source_page=(
                                roi["start_page"] if pending["page"] > roi["start_page"] else None
                            ),
                        ))
                        parent_section = section_norm
                    else:
                        label = pending_text + label
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
                    row_level=1 if parent_section else 0,
                    parent_section=parent_section,
                    cells=cells,
                    header_source_page=header_source_page,
                ))
            else:
                if not label:
                    continue
                # Flush previous pending as a standalone section before replacing.
                if pending:
                    prev_text = pending["text"]
                    prev_norm = normalize_item_label(prev_text)
                    row_order += 1
                    rows.append(TableRow(
                        row_order=row_order,
                        page=pending["page"],
                        block_id=f"spatial_p{pending['page']}",
                        source_method="spatial_roi",
                        raw_item=prev_text,
                        normalized_item=prev_norm,
                        canonical_item=None,
                        mapping_status="UNMAPPED",
                        row_type="SECTION_HEADER",
                        row_level=0,
                        parent_section=None,
                        cells=[],
                        header_source_page=(
                            roi["start_page"] if pending["page"] > roi["start_page"] else None
                        ),
                    ))
                    parent_section = prev_norm
                pending = {"text": label, "x0": parsed["label_x0"], "page": page_no}

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
        text = pending["text"]
        norm = normalize_item_label(text)
        row_order += 1
        rows.append(TableRow(
            row_order=row_order,
            page=pending["page"],
            block_id=f"spatial_p{pending['page']}",
            source_method="spatial_roi",
            raw_item=text,
            normalized_item=norm,
            canonical_item=None,
            mapping_status="UNMAPPED",
            row_type="SECTION_HEADER",
            row_level=0,
            parent_section=None,
            cells=[],
            header_source_page=(
                roi["start_page"] if pending["page"] > roi["start_page"] else None
            ),
        ))

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
        note_number=str(note_number) if note_number else None,
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
            "roi": {
                "start_page": roi["start_page"], "start_y": roi["start_y"],
                "end_page": roi["end_page"], "end_y": roi["end_y"],
            },
            "logical_columns": len(columns),
            "rows": len(rows),
            "numeric_rows": sum(bool(r.cells) for r in rows),
        },
    )
