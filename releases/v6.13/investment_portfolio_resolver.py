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
    "集团合并投资组合",
    "保险资金投资组合",
    "投资组合情况",
    "投资资产情况",
    "投资组合（按投资品种）",
    "投资组合(按投资品种)",
)
_TOTAL_MARKERS = (
    "投资资产（合计）",
    "投资资产(合计)",
    "投资资产合计",
    "投资资产",
    "合计",
)
_UNIT_MARKERS = ("人民币百万元", "单位：百万元", "单位:百万元")
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

        # Prefer the highest score, then the earliest physical page.  A single
        # annual report is expected to have one primary portfolio disclosure;
        # lower-ranked hits remain in audit evidence for reviewer inspection.
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
        if separate_titles:
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
            if topology == "DIRECT_SEPARATE_TABLES_SAME_PAGE":
                physical_id = _stable_id(
                    Path(pdf_path).name,
                    page,
                    member_id,
                    prefix="PORTFOLIO_PHYSICAL_",
                )
                matched_title = str(member.get("display_name") or physical_title)
                split_reason = "SEPARATE_SOURCE_TABLE"
            else:
                physical_id = base_physical_id
                matched_title = physical_title
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
                page,
                matched_title,
            )
            confidence = round(min(0.99, 0.82 + score * 0.01), 2)
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
                "reported_totals_locator_evidence": totals,
                "period_headers": period_headers[:2],
                "period_header_complete": len(period_headers) >= 2,
                "unit": "RMB_MILLION" if signals["unit_marker"] else "",
                "amount_columns_present": bool(totals),
                "formal_statement_region": False,
                "research_definition_match": True,
                "page_signals": signals,
                "candidate_pages": [
                    {"page": int(row[1].page_number), "score": row[0]}
                    for row in scored[:5]
                ],
            }
            candidates.append(
                {
                    "discovery_id": _stable_id(
                        Path(pdf_path).name,
                        page,
                        member_id,
                        prefix="DPT_",
                    ),
                    "company": company,
                    "report_year": str(report_year or ""),
                    "filing_type": filing_type,
                    "pdf_id": str(Path(pdf_path)),
                    "statement_type": "DISCLOSURE_SECTION",
                    "scope": "CONSOLIDATED",
                    "statement_item": physical_title,
                    "member_table": member_id,
                    "member_display_name": member.get("display_name") or member_id,
                    "matched_title": matched_title,
                    "certified_heading": physical_title,
                    "source_table_title": physical_title,
                    "statement_pdf_page_index": page,
                    "candidate_note_pdf_page_index": page,
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
