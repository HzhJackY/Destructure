#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
table_capture.py

v5.1 named-table capture engine with spatial ROI default.

Design:
- Locate a named note/table in a PDF.
- Deep-parse the bounded page range with the existing deterministic PDF engine.
- Preserve raw item labels and source provenance.
- Parse multi-level column headers.
- Support cross-page continued tables through v4.9 context propagation.
- Never require detail-item canonicalization in order to retain data.

This is intentionally separate from resolve_metric().
"""

from __future__ import annotations

import dataclasses
import hashlib
import html
import json
import re
from pathlib import Path
from typing import Any, Optional

import pandas as pd
import pdfplumber

from financial_metric_pdf_resolver import (
    PDFBlock,
    clean_cell,
    normalize_text,
    is_number_like,
    parse_number,
    extract_pdf_blocks,
    file_sha256,
    is_period_header,
)


@dataclasses.dataclass
class TableColumn:
    ordinal: int
    source_column_index: int
    header_raw: str
    year: Optional[str]
    scope: Optional[str]
    restated: bool
    period_label: Optional[str]


@dataclasses.dataclass
class TableCell:
    column_ordinal: int
    source_column_index: int
    raw: str
    parsed_number: Optional[float]
    unit_original: Optional[str]
    value_yuan: Optional[float]


@dataclasses.dataclass
class TableRow:
    row_order: int
    page: int
    block_id: str
    source_method: str
    raw_item: str
    normalized_item: str
    canonical_item: Optional[str]
    mapping_status: str
    row_type: str
    row_level: int
    parent_section: Optional[str]
    cells: list[TableCell]
    header_source_page: Optional[int]


@dataclasses.dataclass
class TableCaptureResult:
    pdf_name: str
    pdf_sha256: str
    table_query: str
    note_number: Optional[str]
    located_title: str
    start_page: int
    end_page: int
    pages: list[int]
    unit: Optional[str]
    columns: list[TableColumn]
    rows: list[TableRow]
    warnings: list[str]
    stats: dict[str, Any]
    boundary_status: str = "UNASSESSED"
    boundary_review: Optional[dict[str, Any]] = None
    header_dimension_status: str = "UNASSESSED"
    header_review: Optional[dict[str, Any]] = None

    def to_dict(self) -> dict[str, Any]:
        return dataclasses.asdict(self)


def analyze_column_dimensions(
    columns: list[TableColumn] | list[dict[str, Any]],
) -> dict[str, Any]:
    """
    Validate whether each logical numeric column has a unique dimension identity.

    A financial table with:
        2022, 2021, 2022, 2021
    cannot safely enter merge if scope is missing, because same-year values from
    本集团/本公司 collapse into one natural key and create false VALUE_CONFLICTs.
    """
    normalized = []
    for idx, c in enumerate(columns):
        if isinstance(c, dict):
            year = str(c.get("year") or "").strip()
            scope = str(c.get("scope") or "").strip()
            restated = bool(c.get("restated"))
            ordinal = int(c.get("ordinal", idx))
            header_raw = str(c.get("header_raw") or "")
        else:
            year = str(c.year or "").strip()
            scope = str(c.scope or "").strip()
            restated = bool(c.restated)
            ordinal = int(c.ordinal)
            header_raw = str(c.header_raw or "")

        normalized.append({
            "ordinal": ordinal,
            "year": year,
            "scope": scope,
            "restated": restated,
            "header_raw": header_raw,
            "dimension_key": f"{year}|{scope}|{'RESTATED' if restated else 'ORIGINAL'}",
        })

    issues = []
    years = [x["year"] for x in normalized if x["year"]]
    repeated_years = {y for y in years if years.count(y) > 1}

    for year in sorted(repeated_years):
        same_year = [x for x in normalized if x["year"] == year]
        missing_scope = [x for x in same_year if not x["scope"]]
        if missing_scope:
            issues.append({
                "issue": "DUPLICATE_PERIOD_WITHOUT_COMPLETE_SCOPE",
                "year": year,
                "ordinals": [x["ordinal"] for x in same_year],
                "missing_scope_ordinals": [x["ordinal"] for x in missing_scope],
                "detail": (
                    f"年份 {year} 出现多个逻辑列，但至少一列缺少 scope；"
                    "可能存在本集团/本公司等父级表头未绑定。"
                ),
            })

    key_map: dict[str, list[int]] = {}
    for x in normalized:
        if not x["year"]:
            issues.append({
                "issue": "MISSING_PERIOD_DIMENSION",
                "ordinal": x["ordinal"],
                "detail": "逻辑列缺少 year/period 维度。",
            })
        key_map.setdefault(x["dimension_key"], []).append(x["ordinal"])

    for key, ordinals in key_map.items():
        if len(ordinals) > 1:
            issues.append({
                "issue": "HEADER_DIMENSION_COLLISION",
                "dimension_key": key,
                "ordinals": ordinals,
                "detail": "多个逻辑数值列拥有相同 year/scope/restated 维度，无法唯一识别。",
            })

    status = "AUTO_CONFIRMED" if not issues else "REVIEW_REQUIRED"
    return {
        "status": status,
        "issues": issues,
        "columns": normalized,
    }


_NOTE_RE = re.compile(r"(?m)^\s*(\d{1,3})\s*(?:[\.．、]\s*)?([^\n]{2,100})")
_YEAR_RE = re.compile(r"(20\d{2})")


def normalize_item_label(text: str) -> str:
    """
    Deterministic, semantics-preserving detail-label cleanup only.
    Does NOT merge economic concepts.
    """
    s = clean_cell(text)
    s = re.sub(r"[（(]\s*注(?:\s*\d+)?\s*[）)]", "", s)
    s = re.sub(r"[（(]\s*附注(?:\s*\d+)?\s*[）)]", "", s)
    s = re.sub(r"\s+", "", s)
    return s.strip("：:")


def _page_texts(pdf_path: Path) -> list[str]:
    texts: list[str] = []
    with pdfplumber.open(str(pdf_path)) as pdf:
        for page in pdf.pages:
            try:
                txt = page.extract_text(x_tolerance=2, y_tolerance=3) or ""
            except Exception:
                txt = ""
            texts.append(txt)
    return texts


def locate_named_table(
    pdf_path: Path,
    table_query: str,
    note_number: Optional[str] = None,
    start_page_override: Optional[int] = None,
    max_pages: int = 6,
) -> tuple[int, int, str, list[str]]:
    texts = _page_texts(pdf_path)
    if not texts:
        raise ValueError("PDF 没有可读取页面。")

    qn = normalize_text(table_query)
    note_number = str(note_number).strip() if note_number else None

    if start_page_override:
        start = int(start_page_override)
        if start < 1 or start > len(texts):
            raise ValueError(f"指定起始页超出PDF范围：{start}")
        located_title = table_query
    else:
        candidates: list[tuple[int, int, str]] = []
        for i, text in enumerate(texts, start=1):
            nt = normalize_text(text)
            score = 0
            if qn and qn in nt:
                score += 10
            if note_number:
                # Strong note-number/title co-occurrence.
                note_pat = re.compile(
                    rf"(?m)^\s*{re.escape(note_number)}\s*[\.．、]\s*([^\n]{{1,120}})"
                )
                m = note_pat.search(text)
                if m:
                    score += 8
                    if qn and qn in normalize_text(m.group(1)):
                        score += 8
            if score:
                title = table_query
                matches = list(_NOTE_RE.finditer(text))
                matching_title = None
                for m2 in matches:
                    if note_number and m2.group(1) != note_number:
                        continue
                    title_text = clean_cell(m2.group(2))
                    if qn and qn not in normalize_text(title_text):
                        continue
                    matching_title = m2
                    break
                if matching_title:
                    title = f"{matching_title.group(1)}. {clean_cell(matching_title.group(2))}"
                candidates.append((score, -i, title))

        if not candidates:
            raise ValueError(
                f"未在PDF文字层定位到目标表/附注：{table_query!r}"
                + (f"，附注号={note_number}" if note_number else "")
            )

        candidates.sort(reverse=True)
        _, neg_page, located_title = candidates[0]
        start = -neg_page

    # Infer note number from the actually located title when the user left it blank.
    resolved_note_number = note_number
    if not resolved_note_number:
        m_title = re.match(r"^\s*(\d{1,3})\s*(?:[\.．、]\s*)?(.+)$", located_title)
        if m_title and normalize_text(table_query) in normalize_text(m_title.group(2)):
            resolved_note_number = m_title.group(1)

    # End bound: next note number when reliable, otherwise bounded max_pages.
    hard_end = min(len(texts), start + max(1, int(max_pages)) - 1)
    end = hard_end

    if resolved_note_number and resolved_note_number.isdigit():
        next_no = str(int(resolved_note_number) + 1)
        next_pat = re.compile(rf"(?m)^\s*{re.escape(next_no)}\s*(?:[\.．、]\s*)?[^\n]+")
        for p in range(start, hard_end):
            # Search subsequent pages only. Same-page boundaries are handled by block selection.
            if next_pat.search(texts[p]):
                end = p
                break

    return start, end, located_title, texts


def _numeric_count(row: list[str]) -> int:
    return sum(
        1 for x in row
        if clean_cell(x) and is_number_like(clean_cell(x))
    )


def _block_shape(block: PDFBlock) -> int:
    counts = [_numeric_count(r) for r in block.rows]
    counts = [c for c in counts if c]
    if not counts:
        return 0
    freq: dict[int, int] = {}
    for c in counts:
        freq[c] = freq.get(c, 0) + 1
    return max(freq, key=lambda c: (freq[c], c))


def _block_data_score(
    block: PDFBlock,
    expected_shape: Optional[int] = None,
    target_terms: Optional[list[str]] = None,
) -> float:
    numeric_rows = sum(1 for r in block.rows if _numeric_count(r) >= 1)
    labels = sum(
        1 for r in block.rows
        if r and clean_cell(r[0]) and not is_number_like(clean_cell(r[0]))
    )
    score = numeric_rows * 2.0 + min(labels, 30) * 0.2

    shape = _block_shape(block)
    if expected_shape and shape:
        if shape == expected_shape:
            score += 10
        elif abs(shape - expected_shape) == 1:
            score += 3
        else:
            score -= 5

    if block.source_method.startswith("pdfplumber_table"):
        score += 4

    joined = normalize_text(
        (block.page_text_preview or "")
        + "\n"
        + "\n".join(" | ".join(r) for r in block.rows[:80])
    )
    for term in target_terms or []:
        if normalize_text(term) in joined:
            score += 8

    return score


def select_table_blocks(
    blocks: list[PDFBlock],
    start_page: int,
    end_page: int,
    table_query: str,
) -> list[PDFBlock]:
    by_page: dict[int, list[PDFBlock]] = {}
    for b in blocks:
        if start_page <= b.page <= end_page:
            by_page.setdefault(b.page, []).append(b)

    selected: list[PDFBlock] = []
    expected_shape: Optional[int] = None
    terms = [table_query]

    for page in range(start_page, end_page + 1):
        page_blocks = by_page.get(page, [])
        if not page_blocks:
            continue

        scored = [
            (
                _block_data_score(
                    b,
                    expected_shape=expected_shape,
                    target_terms=terms if page == start_page else None,
                ),
                b,
            )
            for b in page_blocks
        ]
        scored.sort(key=lambda x: x[0], reverse=True)
        best_score, best = scored[0]

        # Reject pages with no meaningful tabular numeric evidence.
        if _block_shape(best) == 0:
            continue

        selected.append(best)
        if expected_shape is None:
            expected_shape = _block_shape(best)

    return selected


def _first_data_row_index(block: PDFBlock) -> Optional[int]:
    for i, row in enumerate(block.rows):
        if _numeric_count(row) >= 1:
            # Require a plausible label before numeric values when possible.
            labelish = any(
                clean_cell(x) and not is_number_like(clean_cell(x))
                for x in row[:3]
            )
            if labelish:
                return i
    return None


def _value_positions(row: list[str]) -> list[int]:
    return [
        i for i, cell in enumerate(row)
        if clean_cell(cell) and is_number_like(clean_cell(cell))
    ]


def _header_tokens_for_columns(
    block: PDFBlock,
    data_row_idx: int,
    value_cols: list[int],
) -> list[list[str]]:
    """
    Build multi-level header tokens for each numeric value column.

    Handles PDF extraction shifts such as:
      header row -> [2025年度, 2025年度, 2024年度, 2024年度]
      data row   -> [手续费及佣金支出, v1, v2, v3, v4]
    """
    n = len(value_cols)
    tokens: list[list[str]] = [[] for _ in range(n)]
    if n == 0:
        return tokens

    for row in block.rows[max(0, data_row_idx - 12):data_row_idx]:
        cells = [clean_cell(x) for x in row]
        nonempty = [x for x in cells if x and not is_number_like(x)]
        if not nonempty:
            continue

        # Ignore obvious prose/title lines.
        if len(nonempty) == 1 and len(nonempty[0]) > 35:
            continue

        mapped: list[Optional[str]] = [None] * n

        # Strong PDF-shift rule:
        # If the header row has exactly n physical cells while the data row has
        # one label cell + n numeric cells, the blank label-header cell was lost.
        # In that case header cells are ordinal-aligned to the n value columns.
        #
        # This also correctly handles sparse annotation rows such as:
        #   ["", "", "（已重述）", "（已重述）"]
        # which should bind only to the last two value columns.
        if len(cells) == n:
            for j, x in enumerate(cells):
                if x and not is_number_like(x):
                    mapped[j] = x
        else:
            # Exact source-column mapping when physical column structure is retained.
            for j, source_col in enumerate(value_cols):
                if source_col < len(cells):
                    x = cells[source_col]
                    if x and not is_number_like(x):
                        mapped[j] = x

        # Strong shifted-header rule: exactly n meaningful header tokens.
        meaningful = [
            x for x in nonempty
            if len(x) <= 30
        ]
        if len(meaningful) == n:
            mapped = meaningful[:]

        # If header has n+1 cells and first is label header such as 项目, drop it.
        if len(meaningful) == n + 1:
            first = normalize_text(meaningful[0])
            if first in {
                normalize_text(x)
                for x in ["项目", "费用项目", "按费用项目", "科目", "项目名称"]
            }:
                mapped = meaningful[1:]

        for j, x in enumerate(mapped):
            if x and x not in tokens[j]:
                tokens[j].append(x)

    # Cross-page inherited periods.
    inherited = block.inherited_period_headers or []
    if inherited:
        if len(inherited) == n:
            for j, x in enumerate(inherited):
                if x and x not in tokens[j]:
                    tokens[j].insert(0, x)
        else:
            for j, x in enumerate(inherited[:n]):
                if x and x not in tokens[j]:
                    tokens[j].insert(0, x)

    return tokens


def _parse_column_header(
    ordinal: int,
    source_column_index: int,
    tokens: list[str],
) -> TableColumn:
    raw = " | ".join(tokens)
    year_match = _YEAR_RE.search(raw)
    year = year_match.group(1) if year_match else None

    n = normalize_text(raw)
    scope = None
    if normalize_text("本集团") in n or normalize_text("集团") in n:
        scope = "本集团"
    if normalize_text("本公司") in n or normalize_text("公司") in n:
        # Prefer explicit 本公司 if both appear through noisy merge.
        scope = "本公司" if normalize_text("本公司") in n else (scope or "本公司")

    restated = any(
        normalize_text(x) in n
        for x in ["已重述", "重述", "经重述"]
    )

    period_label = None
    period_tokens = [x for x in tokens if is_period_header(x)]
    if period_tokens:
        period_label = period_tokens[0]
    elif year:
        period_label = year

    return TableColumn(
        ordinal=ordinal,
        source_column_index=source_column_index,
        header_raw=raw,
        year=year,
        scope=scope,
        restated=restated,
        period_label=period_label,
    )


def infer_columns(selected_blocks: list[PDFBlock]) -> list[TableColumn]:
    for block in selected_blocks:
        data_idx = _first_data_row_index(block)
        if data_idx is None:
            continue
        value_cols = _value_positions(block.rows[data_idx])
        if not value_cols:
            continue
        tokens = _header_tokens_for_columns(block, data_idx, value_cols)
        return [
            _parse_column_header(i, col, tokens[i])
            for i, col in enumerate(value_cols)
        ]
    return []


def _row_label_and_values(
    row: list[str],
    expected_n: int,
) -> tuple[Optional[str], list[tuple[int, str, Optional[float], Optional[str], bool]]]:
    numeric = []
    for i, cell in enumerate(row):
        raw = clean_cell(cell)
        if not raw:
            continue
        num, unit, ok = parse_number(raw)
        if ok:
            numeric.append((i, raw, num, unit, ok))

    if not numeric:
        # Section header candidate.
        nonempty = [clean_cell(x) for x in row if clean_cell(x)]
        if len(nonempty) == 1 and not is_number_like(nonempty[0]):
            return nonempty[0], []
        return None, []

    first_numeric_col = min(x[0] for x in numeric)
    label_parts = [
        clean_cell(x)
        for x in row[:first_numeric_col]
        if clean_cell(x) and not is_number_like(clean_cell(x))
    ]
    label = "".join(label_parts).strip()
    if not label:
        return None, []

    # Prefer the right-most expected_n numerics when note references / row numbers appear earlier.
    if expected_n and len(numeric) > expected_n:
        numeric = numeric[-expected_n:]

    return label, numeric


def classify_row_type(label: str, has_values: bool) -> str:
    n = normalize_text(label)
    if not has_values:
        return "SECTION_HEADER"
    if n in {normalize_text("合计"), normalize_text("总计")} or n.endswith(normalize_text("合计")):
        return "TOTAL"
    if normalize_text("小计") in n:
        return "SUBTOTAL"
    if any(
        normalize_text(x) in n
        for x in [
            "可归属于保险合同组合的费用",
            "不可归属于保险合同组合的费用",
        ]
    ):
        return "CLASSIFICATION_TOTAL"
    return "DETAIL"


def materialize_rows(
    selected_blocks: list[PDFBlock],
    columns: list[TableColumn],
) -> list[TableRow]:
    rows_out: list[TableRow] = []
    parent_section: Optional[str] = None
    row_order = 0
    expected_n = len(columns)

    # Dedup equivalent rows produced by repeated continuation/table extraction.
    seen: set[str] = set()

    for block in sorted(selected_blocks, key=lambda b: (b.page, b.block_id)):
        for row in block.rows:
            label, numeric = _row_label_and_values(row, expected_n)
            if not label:
                continue

            norm = normalize_item_label(label)

            # Skip obvious table header/title rows.
            nlabel = normalize_text(norm)
            if any(
                normalize_text(x) == nlabel
                for x in [
                    "项目", "费用项目", "科目",
                    "本集团", "本公司",
                ]
            ):
                continue
            if is_period_header(norm):
                continue

            row_type = classify_row_type(norm, bool(numeric))
            if row_type == "SECTION_HEADER":
                parent_section = norm

            # For numeric rows, align numerics left-to-right to canonical columns.
            cells: list[TableCell] = []
            if numeric:
                numeric = sorted(numeric, key=lambda x: x[0])
                for j, (source_col, raw, number, cell_unit, _) in enumerate(numeric[:expected_n]):
                    # Percentage remains percentage. Otherwise inherit block unit.
                    if cell_unit == "%":
                        unit_original = "%"
                        value_yuan = None
                    else:
                        unit_original = cell_unit or block.unit_hint
                        mult = {
                            "元": 1.0,
                            "千元": 1_000.0,
                            "万元": 10_000.0,
                            "百万元": 1_000_000.0,
                            "亿元": 100_000_000.0,
                        }.get(unit_original or "")
                        value_yuan = (
                            number * mult
                            if number is not None and mult is not None
                            else None
                        )
                    cells.append(TableCell(
                        column_ordinal=j,
                        source_column_index=source_col,
                        raw=raw,
                        parsed_number=number,
                        unit_original=unit_original,
                        value_yuan=value_yuan,
                    ))

            sig = hashlib.sha1(
                json.dumps(
                    [norm, [c.raw for c in cells], block.page],
                    ensure_ascii=False,
                ).encode("utf-8")
            ).hexdigest()
            if sig in seen:
                continue
            seen.add(sig)

            row_order += 1
            rows_out.append(TableRow(
                row_order=row_order,
                page=block.page,
                block_id=block.block_id,
                source_method=block.source_method,
                raw_item=label,
                normalized_item=norm,
                canonical_item=None,
                mapping_status="UNMAPPED",
                row_type=row_type,
                row_level=0 if row_type == "SECTION_HEADER" else (1 if parent_section else 0),
                parent_section=parent_section if row_type != "SECTION_HEADER" else None,
                cells=cells,
                header_source_page=block.header_source_page,
            ))

    return rows_out


def _capture_named_table_legacy(
    pdf_path: Path,
    table_query: str,
    note_number: Optional[str] = None,
    start_page_override: Optional[int] = None,
    max_pages: int = 6,
    progress_callback=None,
) -> TableCaptureResult:
    start_page, end_page, located_title, _ = locate_named_table(
        pdf_path=pdf_path,
        table_query=table_query,
        note_number=note_number,
        start_page_override=start_page_override,
        max_pages=max_pages,
    )

    page_numbers = set(range(start_page, end_page + 1))
    blocks, parse_stats = extract_pdf_blocks(
        pdf_path,
        progress_callback=progress_callback,
        page_numbers=page_numbers,
    )
    selected = select_table_blocks(
        blocks,
        start_page=start_page,
        end_page=end_page,
        table_query=table_query,
    )
    if not selected:
        raise ValueError(
            f"已定位目标表到 PDF p.{start_page}–{end_page}，但没有识别出可用表格块。"
        )

    columns = infer_columns(selected)
    if not columns:
        raise ValueError("识别到表格块，但无法建立数值列/多层表头结构。")

    rows = materialize_rows(selected, columns)
    if not rows:
        raise ValueError("表头已识别，但没有提取到有效明细行。")

    units = []
    for row in rows:
        for cell in row.cells:
            if cell.unit_original and cell.unit_original not in units:
                units.append(cell.unit_original)
    unit = units[0] if len(units) == 1 else None

    warnings: list[str] = []
    if len(units) > 1:
        warnings.append("表内存在多个原始单位：" + " | ".join(units))
    inherited = sorted({
        r.header_source_page for r in rows
        if r.header_source_page is not None
    })
    if inherited:
        warnings.append(
            "存在跨页表头继承，表头来源页：" + ", ".join(map(str, inherited))
        )

    return TableCaptureResult(
        pdf_name=pdf_path.name,
        pdf_sha256=file_sha256(pdf_path),
        table_query=table_query,
        note_number=str(note_number) if note_number else None,
        located_title=located_title,
        start_page=start_page,
        end_page=end_page,
        pages=sorted({b.page for b in selected}),
        unit=unit,
        columns=columns,
        rows=rows,
        warnings=warnings,
        stats={
            "selected_blocks": len(selected),
            "rows": len(rows),
            "columns": len(columns),
            "detail_rows": sum(r.row_type == "DETAIL" for r in rows),
            "total_rows": sum(r.row_type in {"TOTAL", "SUBTOTAL", "CLASSIFICATION_TOTAL"} for r in rows),
            "section_rows": sum(r.row_type == "SECTION_HEADER" for r in rows),
            "parse_stats": parse_stats,
        },
    )


def capture_named_table(
    pdf_path: Path,
    table_query: str,
    note_number: Optional[str] = None,
    start_page_override: Optional[int] = None,
    max_pages: int = 8,
    progress_callback=None,
    engine: str = "spatial",
) -> TableCaptureResult:
    """
    v5.1 default: spatial ROI engine.

    Fallback to legacy extraction only when the spatial engine cannot establish
    a valid ROI/header model. The fallback is explicitly recorded in warnings.
    """
    if str(engine).lower() == "legacy":
        return _capture_named_table_legacy(
            pdf_path=pdf_path,
            table_query=table_query,
            note_number=note_number,
            start_page_override=start_page_override,
            max_pages=max_pages,
            progress_callback=progress_callback,
        )

    spatial_exc = None
    try:
        from spatial_table_capture import capture_named_table_spatial
        return capture_named_table_spatial(
            pdf_path=pdf_path,
            table_query=table_query,
            note_number=note_number,
            start_page_override=start_page_override,
            max_pages=max_pages,
            progress_callback=progress_callback,
        )
    except Exception as exc:
        spatial_exc = exc

    try:
        legacy = _capture_named_table_legacy(
            pdf_path=pdf_path,
            table_query=table_query,
            note_number=note_number,
            start_page_override=start_page_override,
            max_pages=max_pages,
            progress_callback=progress_callback,
        )
    except Exception as legacy_exc:
        raise ValueError(
            "整表抓取的空间引擎与legacy回退均失败。"
            f" SPATIAL={type(spatial_exc).__name__}: {spatial_exc};"
            f" LEGACY={type(legacy_exc).__name__}: {legacy_exc}"
        ) from legacy_exc

    legacy.warnings.insert(
        0,
        "SPATIAL_CAPTURE_FALLBACK：空间ROI引擎失败，已回退legacy表格解析。"
        f" 原因={type(spatial_exc).__name__}: {spatial_exc}"
    )
    legacy.stats["engine"] = "LEGACY_FALLBACK"
    return legacy


def capture_to_long_df(result: TableCaptureResult) -> pd.DataFrame:
    records = []
    col_map = {c.ordinal: c for c in result.columns}

    for row in result.rows:
        if not row.cells:
            records.append({
                "pdf_name": result.pdf_name,
                "table_query": result.table_query,
                "note_number": result.note_number,
                "located_title": result.located_title,
                "row_order": row.row_order,
                "row_type": row.row_type,
                "row_level": row.row_level,
                "parent_section": row.parent_section,
                "raw_item": row.raw_item,
                "normalized_item": row.normalized_item,
                "canonical_item": row.canonical_item,
                "mapping_status": row.mapping_status,
                "column_ordinal": None,
                "source_column_index": None,
                "column_dimension_key": None,
                "year": None,
                "period_label": None,
                "scope": None,
                "restated": None,
                "header_raw": None,
                "value_raw": None,
                "value": None,
                "value_yuan": None,
                "unit": None,
                "page": row.page,
                "header_source_page": row.header_source_page,
                "source_method": row.source_method,
            })
            continue

        for cell in row.cells:
            col = col_map.get(cell.column_ordinal)
            records.append({
                "pdf_name": result.pdf_name,
                "table_query": result.table_query,
                "note_number": result.note_number,
                "located_title": result.located_title,
                "row_order": row.row_order,
                "row_type": row.row_type,
                "row_level": row.row_level,
                "parent_section": row.parent_section,
                "raw_item": row.raw_item,
                "normalized_item": row.normalized_item,
                "canonical_item": row.canonical_item,
                "mapping_status": row.mapping_status,
                "column_ordinal": cell.column_ordinal,
                "source_column_index": cell.source_column_index,
                "column_dimension_key": (
                    f"{str(col.year or '').strip()}|{str(col.scope or '').strip()}|"
                    f"{'RESTATED' if bool(col.restated) else 'ORIGINAL'}"
                    if col else None
                ),
                "year": col.year if col else None,
                "period_label": col.period_label if col else None,
                "scope": col.scope if col else None,
                "restated": col.restated if col else None,
                "header_raw": col.header_raw if col else None,
                "value_raw": cell.raw,
                "value": (
                    cell.value_yuan
                    if cell.value_yuan is not None
                    else cell.parsed_number
                ),
                "value_yuan": cell.value_yuan,
                "unit": (
                    "元"
                    if cell.value_yuan is not None
                    else cell.unit_original
                ),
                "original_unit": cell.unit_original,
                "page": row.page,
                "header_source_page": row.header_source_page,
                "source_method": row.source_method,
            })

    return pd.DataFrame(records)


def capture_to_wide_df(result: TableCaptureResult) -> pd.DataFrame:
    """
    Human/research-friendly wide table preserving exactly one row per numeric
    original item.

    v5.5 safety:
    if year/scope/restated dimensions collide, preserve every physical logical
    column with a [colN] suffix instead of silently collapsing duplicate columns.
    """
    long_df = capture_to_long_df(result)
    numeric = long_df[long_df["value"].notna()].copy()
    if numeric.empty:
        return pd.DataFrame()

    def base_col_name(row) -> str:
        parts = [
            str(row.get("year") or "").strip(),
            str(row.get("scope") or "").strip(),
            "已重述" if bool(row.get("restated")) else "",
        ]
        label = " ".join(x for x in parts if x)
        return label or str(row.get("header_raw") or "value")

    numeric["_base_value_column"] = numeric.apply(base_col_name, axis=1)

    # Detect duplicated logical dimensions across physical columns.
    dimension_cols = (
        numeric[
            ["column_ordinal", "_base_value_column"]
        ]
        .dropna(subset=["column_ordinal"])
        .drop_duplicates()
    )
    duplicate_labels = {
        label
        for label, g in dimension_cols.groupby("_base_value_column")
        if g["column_ordinal"].nunique() > 1
    }

    def final_col_name(row) -> str:
        base = row["_base_value_column"]
        if base in duplicate_labels:
            try:
                ordinal = int(row.get("column_ordinal"))
                return f"{base} [col{ordinal}]"
            except Exception:
                return f"{base} [duplicate]"
        return base

    numeric["value_column"] = numeric.apply(final_col_name, axis=1)

    value_wide = numeric.pivot_table(
        index="row_order",
        columns="value_column",
        values="value",
        aggfunc="first",
        dropna=True,
    ).reset_index()
    value_wide.columns.name = None

    meta_cols = [
        "row_order",
        "row_type",
        "parent_section",
        "raw_item",
        "normalized_item",
    ]
    meta = (
        numeric[meta_cols]
        .drop_duplicates(subset=["row_order"], keep="first")
    )

    def row_unit(series: pd.Series) -> str:
        units = {
            str(x).strip()
            for x in series.dropna().tolist()
            if str(x).strip()
        }
        if not units:
            return ""
        if len(units) == 1:
            return next(iter(units))
        return "REVIEW_REQUIRED[" + "|".join(sorted(units)) + "]"

    units = (
        numeric.groupby("row_order", sort=False)["unit"]
        .apply(row_unit)
        .rename("unit")
        .reset_index()
    )

    wide = (
        meta.merge(units, on="row_order", how="left")
        .merge(value_wide, on="row_order", how="left")
        .sort_values("row_order")
        .reset_index(drop=True)
    )

    fixed = [
        "row_order",
        "row_type",
        "parent_section",
        "raw_item",
        "normalized_item",
        "unit",
    ]
    value_cols = [c for c in wide.columns if c not in fixed]
    return wide[fixed + value_cols]


def item_dictionary_df(result: TableCaptureResult) -> pd.DataFrame:
    rows = []
    seen = set()
    for row in result.rows:
        if row.row_type == "SECTION_HEADER":
            continue
        key = row.normalized_item
        if key in seen:
            continue
        seen.add(key)
        rows.append({
            "normalized_item": row.normalized_item,
            "example_raw_item": row.raw_item,
            "canonical_item": "",
            "category": "",
            "mapping_status": "UNMAPPED",
            "mapping_note": "",
        })
    return pd.DataFrame(rows)


def generate_capture_markdown(result: TableCaptureResult) -> str:
    lines = [
        "# 整表抓取报告",
        "",
        f"- PDF: `{result.pdf_name}`",
        f"- 查询表: `{result.table_query}`",
        f"- 定位标题: `{result.located_title}`",
        f"- 页码: `{result.start_page}–{result.end_page}`",
        f"- 实际表格页: `{', '.join(map(str, result.pages))}`",
        f"- 列数: `{len(result.columns)}`",
        f"- 行数: `{len(result.rows)}`",
        "",
        "## 列结构",
        "",
    ]
    for c in result.columns:
        lines.append(
            f"- col{c.ordinal}: year={c.year or '-'} | scope={c.scope or '-'} | "
            f"restated={c.restated} | raw={c.header_raw or '-'}"
        )
    if result.warnings:
        lines += ["", "## 警告", ""]
        lines += [f"- {x}" for x in result.warnings]
    lines += [
        "",
        "## 说明",
        "",
        "- `raw_item` 永久保留PDF原始行名。",
        "- `normalized_item` 只做确定性文本清洗，不改变经济含义。",
        "- `canonical_item` 整表抓取层默认不强制映射；跨公司细项统一由“合表 / Taxonomy”工作区完成。",
    ]
    return "\n".join(lines)


def generate_capture_html(result: TableCaptureResult) -> str:
    md = generate_capture_markdown(result)
    wide = capture_to_wide_df(result)
    table_html = wide.to_html(index=False, escape=True) if not wide.empty else "<p>无宽表数据</p>"
    return f"""<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8">
<title>整表抓取报告</title>
<style>
body{{font-family:Arial,'Microsoft YaHei',sans-serif;margin:28px;color:#1f2937}}
pre{{white-space:pre-wrap;background:#f6f8fa;padding:16px;border-radius:8px}}
table{{border-collapse:collapse;width:100%;font-size:13px}}
th,td{{border:1px solid #d1d5db;padding:6px 8px;text-align:right}}
th:first-child,td:first-child{{text-align:left}}
</style></head><body>
<h1>整表抓取报告</h1>
<pre>{html.escape(md)}</pre>
<h2>宽表预览</h2>
{table_html}
</body></html>"""


def write_capture_artifacts(
    output_dir: Path,
    result: TableCaptureResult,
) -> dict[str, str]:
    output_dir.mkdir(parents=True, exist_ok=True)

    # Derive initial boundary status.
    if not result.boundary_status or result.boundary_status == "UNASSESSED":
        reason = str((result.stats or {}).get("boundary_reason") or "")
        if reason.startswith("next_note_"):
            result.boundary_status = "HARD_BOUNDARY_CONFIRMED"
        else:
            result.boundary_status = "REVIEW_REQUIRED"

    # Derive header-dimension status independently from boundary status.
    dimension_check = analyze_column_dimensions(result.columns)
    if not result.header_dimension_status or result.header_dimension_status == "UNASSESSED":
        result.header_dimension_status = dimension_check["status"]
    result.stats["header_dimension_check"] = dimension_check
    if result.header_dimension_status == "REVIEW_REQUIRED":
        warning = (
            "表头维度存在碰撞/缺失：重复期间列无法由 year/scope/restated 唯一区分；"
            "请完成“表头维度复核”后再进入正式合表。"
        )
        if warning not in result.warnings:
            result.warnings.append(warning)

    result_json = output_dir / "table_capture_result.json"
    raw_long = output_dir / "table_raw_long.csv"
    raw_wide = output_dir / "table_raw_wide.csv"
    machine_long = output_dir / "machine_capture_full_long.csv"
    machine_wide = output_dir / "machine_capture_full_wide.csv"
    dictionary = output_dir / "table_item_dictionary.csv"
    report_md = output_dir / "table_report.md"
    report_html = output_dir / "table_report.html"
    xlsx = output_dir / "table_capture.xlsx"

    result_payload = result.to_dict()
    result_payload["producer_version"] = "v5.8"
    result_payload["capture_schema_version"] = "5.8"
    result_payload["reconciliation_schema_version"] = 2
    result_json.write_text(
        json.dumps(result_payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    long_df = capture_to_long_df(result)
    wide_df = capture_to_wide_df(result)
    dict_df = item_dictionary_df(result)

    # Immutable machine evidence.
    long_df.to_csv(machine_long, index=False, encoding="utf-8-sig")
    wide_df.to_csv(machine_wide, index=False, encoding="utf-8-sig")

    # Official output initially equals machine output. Human boundary adjudication
    # may later truncate these while machine files remain unchanged.
    long_df.to_csv(raw_long, index=False, encoding="utf-8-sig")
    wide_df.to_csv(raw_wide, index=False, encoding="utf-8-sig")
    dict_df.to_csv(dictionary, index=False, encoding="utf-8-sig")

    report_md.write_text(generate_capture_markdown(result), encoding="utf-8")
    report_html.write_text(generate_capture_html(result), encoding="utf-8")

    # Warning-only total/subtotal arithmetic audit.
    from reconciliation import reconciliation_audit_from_long
    reconciliation_df = reconciliation_audit_from_long(long_df)
    reconciliation_path = output_dir / "table_reconciliation_audit.csv"
    reconciliation_df.to_csv(reconciliation_path, index=False, encoding="utf-8-sig")

    with pd.ExcelWriter(xlsx, engine="openpyxl") as writer:
        long_df.to_excel(writer, sheet_name="raw_long", index=False)
        wide_df.to_excel(writer, sheet_name="raw_wide", index=False)
        dict_df.to_excel(writer, sheet_name="item_dictionary", index=False)
        long_df.to_excel(writer, sheet_name="machine_full_long", index=False)
        wide_df.to_excel(writer, sheet_name="machine_full_wide", index=False)
        pd.DataFrame().to_excel(writer, sheet_name="boundary_excluded", index=False)
        reconciliation_df.to_excel(writer, sheet_name="reconciliation", index=False)

    return {
        "result_json": str(result_json),
        "raw_long": str(raw_long),
        "raw_wide": str(raw_wide),
        "machine_full_long": str(machine_long),
        "machine_full_wide": str(machine_wide),
        "item_dictionary": str(dictionary),
        "reconciliation": str(reconciliation_path),
        "report_md": str(report_md),
        "report_html": str(report_html),
        "xlsx": str(xlsx),
    }

