"""Native-first topology resolver for directly disclosed investment portfolios.

The resolver is a discovery component only.  It identifies source tables and
classification-axis blocks, but never parses or certifies financial values.
Its candidates continue through the existing Generic Structure Parser,
Stage-A/Stage-B review, Whole-table Capture, Canonical and Merge pipeline.
"""
from __future__ import annotations

import hashlib
import re
from pathlib import Path
from typing import Any, Iterable

from investment_portfolio_topology_contract import (
    INVESTMENT_PORTFOLIO_TOPOLOGY_CONTRACT,
)
from statement_anchored_family import normalize_text
from investment_portfolio_axis_semantics import (
    BY_ACCOUNTING_MEASUREMENT,
    BY_INVESTMENT_OBJECT,
    portfolio_axes_in_text,
)


_DIRECT_TITLES = (
    "集团合并投资组合", "集團合併投資組合",
    "保险资金投资组合", "保險資金投資組合",
    "投资组合情况", "投資組合情況",
    "投资资产情况", "投資資產情況",
    "投资组合（按投资品种）", "投資組合（按投資品種）",
    "投资组合(按投资品种)", "投資組合(按投資品種)",
    "投资组合（按会计计量）", "投資組合（按會計計量）",
    "投资组合(按会计计量)", "投資組合(按會計計量)",
    "按投资品种分类", "按投資品種分類",
    "按投资品种划分", "按投資品種劃分",
    "按投资计量分类", "按投資計量分類",
    "按会计计量分类", "按會計計量分類",
    "按投资资产类别分类", "按投資資產類別分類",
    "总投资资产组合", "總投資資產組合",
    "按投資對象劃分的投資資產組合", "按投资对象划分的投资资产组合",
    "按投資對象劃分", "按投资对象划分",
    "金融投资", "金融投資",
    "投资资产", "投資資產",
    "投资组合", "投資組合",
    "總投資", "总投资",
)
_TOTAL_MARKERS = (
    "投资资产（合计）", "投資資產（合計）",
    "投资资产(合计)", "投資資產(合計)",
    "投资资产合计", "投資資產合計",
    "投资资产", "投資資產",
    "投资资产总额", "投資資產總額",
    "总投资资产", "總投資資產",
    "总投资", "總投資",
    "合计", "合計",
    "总计", "總計",
    "保單持有人及股東", "保单持有人及股东",
    "保單持有人及股東總計", "保单持有人及股东总计",
)
_UNIT_MARKERS = (
    "人民币百万元", "人民幣百萬元", "单位：百万元", "單位：百萬元", "单位:百万元", "單位:百萬元",
    "百万美元", "百萬美元", "单位：百万美元", "單位：百萬美元", "US$m", "US$ millions", "RMB million",
    "百万元", "百萬元",
)
_NUMBER_RE = re.compile(r"(?<!\d)(?:\d{1,3}(?:,\d{3})+|\d{4,})(?!\d)")
_PERIOD_RE = re.compile(
    r"(?<!\d)(20\d{2})[^\S\r\n]*年"
    r"(?:"
    r"[^\S\r\n]*(\d{1,2})[^\S\r\n]*月"
    r"[^\S\r\n]*(\d{1,2})[^\S\r\n]*日"
    r"|[^\S\r\n]*(末|初)"
    r")?"
    r"(?!\d)"
)


def _first_present(text: str, values: Iterable[str]) -> str:
    normalized = normalize_text(text)
    return next((value for value in values if normalize_text(value) in normalized), "")


def _stable_id(*parts: Any, prefix: str) -> str:
    material = "::".join(normalize_text(str(part)) for part in parts)
    return prefix + hashlib.sha256(material.encode("utf-8")).hexdigest()[:20]


def _period_headers(text: str) -> list[str]:
    """Extract distinct Chinese period labels from native PDF text.

    PyMuPDF can insert horizontal whitespace between Chinese date glyphs even
    when the rendered header is visually continuous.  Normalize only matched
    date tokens; do not remove line breaks or search across unrelated rows.
    """
    headers: list[str] = []
    for match in _PERIOD_RE.finditer(str(text or "")):
        year, month, day, boundary = match.groups()
        if month and day:
            value = f"{year}年{month}月{day}日"
        elif boundary:
            value = f"{year}年{boundary}"
        else:
            value = f"{year}年"
        if value not in headers:
            headers.append(value)
    # Narrative prose can contain a bare year before a later, geometry-backed
    # full date for the same year. Prefer the more precise identity so the
    # two-column gate cannot be satisfied by two precision variants of one
    # period.
    full_date_years = {
        value[:4] for value in headers
        if re.fullmatch(r"20\d{2}年\d{1,2}月\d{1,2}日", value)
    }
    return [
        value for value in headers
        if not (re.fullmatch(r"20\d{2}年", value) and value[:4] in full_date_years)
    ]


def ocr_period_headers_from_words(words: Iterable[Any]) -> list[str]:
    """Reconstruct Chinese dates split across OCR baselines using word BBoxes.

    Tesseract can place ``YYYY``/``31日`` and ``年12月`` on adjacent baselines
    even though they are one visual header. Reconstruction is limited to a
    left-to-right sequence on the same visual band; it never joins plain text
    lines or infers a missing month/day from the filing year. Fast Index words
    use ``[x0, y0, x1, y1, text]`` pixel coordinates.
    """
    tokens: list[tuple[float, float, str]] = []
    for word in words or []:
        if not isinstance(word, (list, tuple)) or len(word) < 5:
            continue
        try:
            x0, y0, x1, y1 = (float(word[index]) for index in range(4))
        except (TypeError, ValueError):
            continue
        token = normalize_text(str(word[4] or ""))
        if token:
            tokens.append(((x0 + x1) / 2.0, (y0 + y1) / 2.0, token))

    headers: list[str] = []
    year_tokens = [item for item in tokens if re.fullmatch(r"20\d{2}", item[2])]
    component_patterns = (
        re.compile(r"年"),
        re.compile(r"(?:1[0-2]|[1-9])"),
        re.compile(r"月"),
        re.compile(r"(?:3[01]|[12]\d|[1-9])"),
        re.compile(r"日"),
    )
    for year_x, year_y, year in sorted(year_tokens, key=lambda item: (item[1], item[0])):
        cursor_x = year_x
        selected: list[str] = []
        for pattern in component_patterns:
            matches = [
                item for item in tokens
                if item[0] > cursor_x
                and item[0] - year_x <= 520.0
                and abs(item[1] - year_y) <= 55.0
                and pattern.fullmatch(item[2])
            ]
            if not matches:
                selected = []
                break
            chosen = min(matches, key=lambda item: item[0])
            cursor_x = chosen[0]
            selected.append(chosen[2])
        if len(selected) != 5:
            continue
        _, month, _, day, _ = selected
        value = f"{year}年{int(month)}月{int(day)}日"
        if value not in headers:
            headers.append(value)
    return headers


def _reported_totals(text: str) -> list[int]:
    """Return source-disclosed totals near the first portfolio-total label.

    These are locator evidence only.  They never enter Capture/Canonical and
    are compared with Golden only after machine extraction.
    """
    lines = [line.strip() for line in str(text or "").splitlines() if line.strip()]
    candidates = []
    exact_markers = {normalize_text(marker) for marker in _TOTAL_MARKERS}
    for index, line in enumerate(lines):
        normalized_line = normalize_text(line)
        looks_like_total = (
            normalized_line in exact_markers
            or "合计" in normalized_line
            or normalized_line.endswith("投资资产")
            or normalized_line.startswith("投资资产")
            or normalized_line.endswith("投资资产（合计）")
            or normalized_line.endswith("投资资产(合计)")
        )
        if looks_like_total and "投资资产规模" not in normalized_line:
            window = " ".join(lines[index : index + 5])
            values = []
            for token in _NUMBER_RE.findall(window):
                value = int(token.replace(",", ""))
                if value > 19000101 or value < 10000:  # exclude dates/ratios
                    continue
                if value not in values:
                    values.append(value)
            if len(values) >= 2:
                candidates.append(values[:2])
    return candidates[-1] if candidates else []


def _physical_table_bbox(
    pdf_path: Path,
    page_number: int,
    title: str,
) -> dict[str, float]:
    """Resolve a bounded native-page ROI for Stage-B certification."""
    if not Path(pdf_path).is_file():
        return {}
    try:
        import fitz
        document = fitz.open(pdf_path)
        page = document[int(page_number) - 1]
        title_rects = page.search_for(str(title or ""))
        if not title_rects:
            document.close()
            return {}
        start = min(title_rects, key=lambda rect: rect.y0)
        boundaries = []
        for marker in (
            "投资组合（按投资品种）",
            "投资组合（按会计计量）",
            "投资组合(按投资品种)",
            "投资组合(按会计计量)",
            "注：",
            "注:",
        ):
            for rect in page.search_for(marker):
                if rect.y0 > start.y1 + 2:
                    boundaries.append(float(rect.y0))
        end_y = min(boundaries) - 2 if boundaries else float(page.rect.height) - 28
        bbox = {
            "x0": max(0.0, float(page.rect.x0) + 24),
            "y0": max(0.0, float(start.y0) - 2),
            # Footnote markers at the end of a legitimate row can extend into
            # the right page margin (for example CPIC's 注1/注2 labels).  The
            # certified ROI is still vertically bounded by the title/next
            # section; use the physical page edge horizontally so those source
            # labels do not create a false row-outside-ROI failure.
            "x1": float(page.rect.x1),
            "y1": min(float(page.rect.y1), max(float(start.y1) + 20, end_y)),
        }
        document.close()
        return {key: round(value, 2) for key, value in bbox.items()}
    except Exception:
        return {}


class InvestmentPortfolioTopologyResolver:
    """Resolve direct portfolio disclosure topology from a native text index."""

    strategy_id = "DIRECT_PORTFOLIO_TABLES"

    def evidence_recovery_pages(self, index: list[Any]) -> list[int]:
        """Return only Native-identified table pages missing numeric evidence.

        OCR is never allowed to discover a generic portfolio page by itself.
        The Native page must already contain the physical title, at least one
        certified classification axis, a total-row marker and a unit marker.
        """
        pages: list[int] = []
        for record in index:
            text = str(record.text or "")
            title = _first_present(text, _DIRECT_TITLES)
            axes = portfolio_axes_in_text(text)
            total = _first_present(text, _TOTAL_MARKERS)
            unit = _first_present(text, _UNIT_MARKERS)
            if (
                title
                and axes
                and total
                and unit
                and len(_NUMBER_RE.findall(text)) < 4
            ):
                pages.append(int(record.page_number))
        return sorted(set(pages))

    def resolve(
        self,
        *,
        pdf_path: Path,
        index: list[Any],
        members: list[dict[str, Any]],
        company: str,
        report_year: str,
        filing_type: str,
    ) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        member_map = {str(row["member_id"]): row for row in members}
        scored: list[tuple[int, Any, dict[str, Any]]] = []
        for record in index:
            text = str(record.text or "")
            normalized = normalize_text(text)
            title = _first_present(text, _DIRECT_TITLES)
            semantic_axes = portfolio_axes_in_text(text)
            category = BY_INVESTMENT_OBJECT if BY_INVESTMENT_OBJECT in semantic_axes else ""
            measurement = (
                BY_ACCOUNTING_MEASUREMENT
                if BY_ACCOUNTING_MEASUREMENT in semantic_axes else ""
            )
            total = _first_present(text, _TOTAL_MARKERS)
            unit = _first_present(text, _UNIT_MARKERS)
            amount_count = len(_NUMBER_RE.findall(text))
            score = (
                (5 if title else 0)
                + (3 if category else 0)
                + (3 if measurement else 0)
                + (1 if total else 0)
                + (1 if unit else 0)
                + (1 if amount_count >= 4 else 0)
            )
            # A portfolio label without a source table is narrative, not a
            # table candidate.  Conversely, the general China Life heading is
            # accepted only with axis, total and numeric evidence.
            if score >= 9 and title and (category or measurement) and amount_count >= 4:
                scored.append(
                    (
                        score,
                        record,
                        {
                            "matched_title": title,
                            "category_marker": category,
                            "measurement_marker": measurement,
                            "total_marker": total,
                            "unit_marker": unit,
                            "amount_token_count": amount_count,
                            "normalized_page_chars": len(normalized),
                        },
                    )
                )

        if not scored:
            return [], {
                "strategy": self.strategy_id,
                "final_status": "NO_DIRECT_PORTFOLIO_TABLE",
                "native_pages_scanned": len(index),
                "ocr_used": False,
            }

        # Collect category and measurement candidates
        cat_matches = [row for row in scored if row[2]["category_marker"]]
        meas_matches = [row for row in scored if row[2]["measurement_marker"]]

        separate_pair = None
        for cat_row in cat_matches:
            c_pno = int(cat_row[1].page_number)
            for meas_row in meas_matches:
                m_pno = int(meas_row[1].page_number)
                if 0 < abs(c_pno - m_pno) <= 5:
                    separate_pair = (cat_row, meas_row)
                    break
            if separate_pair:
                break

        scored.sort(key=lambda row: (-row[0], int(row[1].page_number)))
        score, record, signals = scored[0]
        text = str(record.text or "")
        page = int(record.page_number)
        period_headers = _period_headers(text)
        category = bool(signals["category_marker"])
        measurement = bool(signals["measurement_marker"])
        separate_titles = (
            normalize_text("投资组合（按投资品种）") in normalize_text(text)
            and normalize_text("投资组合（按会计计量）") in normalize_text(text)
        )
        if separate_pair:
            topology = "DIRECT_SEPARATE_TABLES_SAME_PAGE"
        elif separate_titles:
            topology = "DIRECT_SEPARATE_TABLES_SAME_PAGE"
        elif category and measurement:
            topology = "DIRECT_COMPOUND_TABLE"
        elif category:
            topology = "DIRECT_SINGLE_AXIS_TABLE"
        else:
            return [], {
                "strategy": self.strategy_id,
                "final_status": "PORTFOLIO_TABLE_AXIS_UNRESOLVED",
                "candidate_page": page,
                "native_pages_scanned": len(index),
                "ocr_used": False,
            }

        contract = INVESTMENT_PORTFOLIO_TOPOLOGY_CONTRACT["topologies"][topology]
        applicable = list(contract.get("applicable_members") or [])
        not_applicable = list(contract.get("not_applicable_members") or [])
        physical_title = signals["matched_title"]
        base_physical_id = _stable_id(
            Path(pdf_path).name,
            page,
            physical_title,
            prefix="PORTFOLIO_PHYSICAL_",
        )
        totals = _reported_totals(text)
        candidates: list[dict[str, Any]] = []
        for member_id in applicable:
            member = member_map.get(member_id)
            if not member:
                continue
            member_payload = member.get("payload") or {}
            classification_axis = str(member_payload.get("classification_axis") or "")
            
            # Determine specific page and signals for this member
            if separate_pair:
                item_row = separate_pair[0] if classification_axis == BY_INVESTMENT_OBJECT else separate_pair[1]
                item_page = int(item_row[1].page_number)
                item_text = str(item_row[1].text or "")
                item_signals = item_row[2]
                item_score = item_row[0]
                item_headers = _period_headers(item_text)
                item_totals = _reported_totals(item_text)
                item_title = item_signals["matched_title"]
            else:
                item_row = scored[0]
                item_page = page
                item_text = text
                item_signals = signals
                item_score = score
                item_headers = period_headers
                item_totals = totals
                item_title = physical_title

            if topology == "DIRECT_SEPARATE_TABLES_SAME_PAGE":
                physical_id = _stable_id(
                    Path(pdf_path).name,
                    item_page,
                    member_id,
                    prefix="PORTFOLIO_PHYSICAL_",
                )
                matched_title = str(member.get("display_name") or item_title)
                split_reason = "SEPARATE_SOURCE_TABLE"
            else:
                physical_id = base_physical_id
                matched_title = item_title
                split_reason = (
                    "CLASSIFICATION_AXIS_TRANSITION"
                    if topology == "DIRECT_COMPOUND_TABLE"
                    else "SINGLE_DISCLOSED_AXIS"
                )
            logical_block_id = _stable_id(
                physical_id,
                classification_axis,
                prefix="PORTFOLIO_BLOCK_",
            )
            physical_bbox = _physical_table_bbox(
                pdf_path,
                item_page,
                matched_title,
            )
            confidence = round(min(0.99, 0.82 + item_score * 0.01), 2)
            unit_val = "USD_MILLION" if ("美元" in str(item_signals.get("unit_marker") or "") or "US$" in str(item_signals.get("unit_marker") or "")) else ("RMB_MILLION" if item_signals.get("unit_marker") else "")
            evidence = {
                "strategy": self.strategy_id,
                "native_text_only": True,
                "ocr_used": False,
                "disclosure_topology": topology,
                "physical_asset_id": physical_id,
                "logical_block_id": logical_block_id,
                "classification_axis": classification_axis,
                "physical_bbox": physical_bbox,
                "split_reason": split_reason,
                "applicable_members": applicable,
                "required_members": list(contract.get("required_members") or []),
                "not_applicable_members": not_applicable,
                "reported_total_policy": contract.get("reported_total_policy"),
                "reported_totals_locator_evidence": item_totals,
                "period_headers": item_headers[:2],
                "period_header_complete": len(item_headers) >= 2,
                "unit": unit_val,
                "amount_columns_present": bool(item_totals),
                "formal_statement_region": False,
                "research_definition_match": True,
                "page_signals": item_signals,
                "candidate_pages": [
                    {"page": int(row[1].page_number), "score": row[0]}
                    for row in scored[:5]
                ],
            }
            candidates.append(
                {
                    "discovery_id": _stable_id(
                        Path(pdf_path).name,
                        item_page,
                        member_id,
                        prefix="DPT_",
                    ),
                    "company": company,
                    "report_year": str(report_year or ""),
                    "filing_type": filing_type,
                    "pdf_id": str(Path(pdf_path)),
                    "statement_type": "DISCLOSURE_SECTION",
                    "scope": "CONSOLIDATED",
                    "statement_item": item_title,
                    "member_table": member_id,
                    "member_display_name": member.get("display_name") or member_id,
                    "matched_title": matched_title,
                    "certified_heading": item_title,
                    "source_table_title": item_title,
                    "statement_pdf_page_index": item_page,
                    "candidate_note_pdf_page_index": item_page,
                    "candidate_note_pages": [int(row[1].page_number) for row in scored[:5]],
                    "locator_method": "DIRECT_PORTFOLIO_NATIVE_TOPOLOGY",
                    "confidence": confidence,
                    "status": "NEEDS_REVIEW",
                    "failure_reason": None,
                    "note_reference": "",
                    "note_reference_status": "NOT_APPLICABLE",
                    "direct_portfolio_table": True,
                    "portfolio_source_kind": "DIRECT_PHYSICAL_TABLE",
                    "direct_end_page": page,
                    "disclosure_topology": topology,
                    "physical_asset_id": physical_id,
                    "logical_block_id": logical_block_id,
                    "classification_axis": classification_axis,
                    "physical_bbox": physical_bbox,
                    "applicable_members": applicable,
                    "not_applicable_members": not_applicable,
                    "reported_total_policy": contract.get("reported_total_policy"),
                    "unit": evidence["unit"],
                    "evidence": evidence,
                }
            )

        return candidates, {
            "strategy": self.strategy_id,
            "final_status": "DIRECT_PORTFOLIO_TABLE_FOUND",
            "native_pages_scanned": len(index),
            "ocr_used": False,
            "selected_page": page,
            "selected_topology": topology,
            "selected_score": score,
            "physical_asset_count": len({row["physical_asset_id"] for row in candidates}),
            "logical_block_count": len(candidates),
            "not_applicable_members": not_applicable,
        }
