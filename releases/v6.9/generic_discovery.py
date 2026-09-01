"""Generic Statement-Guided Discovery for v6.5.

Presets only supply optional vocabulary. The extractor retains all occurrences;
anchor arbitration is deliberately a later, reviewable step.
"""
from __future__ import annotations

import re
from typing import Any

from statement_note_navigation import build_text_index, locate_primary_statements, locate_note
from statement_anchored_family import compose_note_reference, normalize_text

# Migration/import vocabulary only. Production runtime receives immutable
# Registry-derived context through ``discovery_context``.
LEGACY_PRESET_IMPORT_SOURCE = {
    "金融投资": {
        "preferred_statement_type": "BALANCE_SHEET",
        "core_candidates": ["交易性金融资产", "债权投资", "其他债权投资", "其他权益工具投资"],
        "historical_variants": ["以公允价值计量且其变动计入当期损益的金融资产", "可供出售金融资产", "持有至到期投资"],
        "expansion_candidates": ["定期存款", "买入返售金融资产", "长期股权投资", "存出资本保证金"],
        "definition_version": "FINANCIAL_INVESTMENT_V1",
    }
}


def normalize_company(value: str) -> str:
    value = re.sub(r"^[0-9a-fA-F]{12,64}_", "", value or "")
    return re.sub(r"\s+", "", value).replace("年报", "").replace("年度报告", "")


def _tokens(display_name: str, prior: dict[str, Any]) -> list[str]:
    normalized = display_name
    for suffix in ("研究", "明细", "表族", "项目", "分析"):
        if normalized.endswith(suffix):
            normalized = normalized[:-len(suffix)]
    return list(dict.fromkeys([x for x in [display_name, normalized, *prior.get("core_candidates", []), *prior.get("historical_variants", [])] if x]))


def _extract_tail_reference(line: str, label: str, note_header: str, next_line: str = "") -> dict[str, str]:
    tail = line.split(label, 1)[-1]
    explicit = re.search(r"((?:附注|注)\s*[一二三四五六七八九十百\d]+\s*[-、.]?\s*[一二三四五六七八九十百\d]*)", tail)
    if explicit:
        return compose_note_reference("", explicit.group(1))
    # In a recognised note column, a standalone trailing cell is a row item.
    item = re.search(r"(?:^|\s)([0-9]{1,3})(?:\s|$)", tail)
    if item:
        return compose_note_reference(note_header, item.group(1))
    # PDF text extraction commonly emits a statement label and its “附注” cell
    # as two adjacent lines.  Treat the next line as a note cell only when it
    # is a standalone ordinal; values such as 380,239 are deliberately rejected.
    adjacent = str(next_line or "").strip()
    if re.fullmatch(r"[0-9]{1,3}", adjacent):
        return compose_note_reference(note_header, adjacent)
    return compose_note_reference(note_header, "")


def _locate_without_reference(index, item: str, section_context: str):
    """Fallback locator: heading/context first, then semantic/full-text proxy.

    It returns REVIEW_REQUIRED-level confidence instead of inventing a target.
    """
    candidates = []
    for rec in index:
        text = normalize_text(rec.text)
        if normalize_text(item) in text:
            score = .58 if normalize_text(item) == text else .48
            if section_context and normalize_text(section_context) in text:
                score += .05
            candidates.append((rec.page_number, "HEADING_OR_CONTEXT_MATCH", round(score, 2)))
    if not candidates:
        return None, "FULL_TEXT_FALLBACK_UNRESOLVED", .0, []
    candidates.sort(key=lambda x: x[2], reverse=True)
    page, method, score = candidates[0]
    return page, method, score, [x[0] for x in candidates[:5]]


def discover(pdf_path, cache_root, *, display_name: str, company: str = "", report_year: str = "",
             filing_type: str = "ANNUAL_REPORT", preset_name: str | None = None,
             discovery_context: dict[str, Any] | None = None, text_provider=None) -> list[dict[str, Any]]:
    """Return immutable raw evidence for any display name, never financial guesses."""
    # ``preset_name`` remains import compatibility only; production callers
    # pass a Registry snapshot in discovery_context and never mutate globals.
    prior = dict(discovery_context or {})
    if not prior and preset_name:
        prior = dict(LEGACY_PRESET_IMPORT_SOURCE.get(preset_name, {}))
    index = build_text_index(pdf_path, cache_root, text_provider=text_provider)
    statements = locate_primary_statements(index)
    preferred = prior.get("preferred_statement_type")
    candidate_types = [preferred] if preferred else [kind for kind, pages in statements.items() if pages]
    tokens = _tokens(display_name, prior)
    rows: list[dict[str, Any]] = []
    for statement_type in candidate_types:
        pages = set(statements.get(statement_type, []))
        for rec in index:
            if rec.page_number not in pages:
                continue
            note_header = ""
            page_lines = rec.text.splitlines()
            for line_index, raw_line in enumerate(page_lines):
                text = " ".join(raw_line.split())
                # The statement note column can either expose a section
                # (附注八) or merely say 附注. Both are valid grammars.
                if re.fullmatch(r"(?:附注|注)(?:\s*[一二三四五六七八九十百\d]+)?", text):
                    note_header = text
                matched = next((t for t in sorted(tokens, key=len, reverse=True) if t in text), None)
                if not matched:
                    continue
                next_line = page_lines[line_index + 1] if line_index + 1 < len(page_lines) else ""
                note = _extract_tail_reference(text, matched, note_header, next_line)
                note_ref = note["note_reference_normalized"]
                if note_ref:
                    page, method, confidence = locate_note(index, note_reference=note_ref, item=matched, section_context=rec.section)
                    candidates = [page] if page else []
                else:
                    page, method, confidence, candidates = _locate_without_reference(index, matched, rec.section)
                rows.append({
                    "company": company, "normalized_company": normalize_company(company), "report_year": str(report_year),
                    "filing_type": filing_type, "statement_type": statement_type, "scope": "UNKNOWN",
                    "display_name": display_name, "table_family": display_name, "statement_item": matched,
                    "member_table": matched, "source_table_title": rec.section or statement_type,
                    "section_context": rec.section, "statement_pdf_page_index": rec.page_number,
                    "statement_page": rec.page_number, "statement_printed_page": None,
                    "candidate_note_pdf_page_index": page, "note_page": page, "candidate_note_pages": candidates,
                    "confirmed_note_pdf_page_index": None, "locator_method": method, "confidence": confidence,
                    "status": "REVIEW_REQUIRED" if not note_ref or confidence < .80 else "NEEDS_REVIEW",
                    **note,
                    "note_reference": note_ref,
                    "evidence": {"raw_line": text, "note_header": note_header, "prior": prior,
                                 "statement_pages": sorted(pages), "locator_candidates": candidates},
                })
    # Preserve different statement occurrence/scope contexts. Only exact same
    # source line is deduplicated here; later clustering preserves all evidence.
    unique: dict[tuple, dict[str, Any]] = {}
    for row in rows:
        key = (row["statement_type"], row["source_table_title"], row["statement_item"],
               row["note_reference"], row["statement_pdf_page_index"], row["evidence"]["raw_line"])
        unique.setdefault(key, row)
    return list(unique.values())


def assemble_statement_occurrences(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Build proposed parent + contiguous candidate children per statement page.

    This is deliberately conservative: it uses only candidates found on the
    same primary-statement page and retains the raw rows as evidence.  A later
    anchor review is required to decide scope and to add/remove members.
    """
    groups: dict[tuple, list[dict[str, Any]]] = {}
    for row in rows:
        key = (row.get("pdf_id"), row.get("display_name"), row.get("statement_type"),
               row.get("statement_pdf_page_index") or row.get("statement_page"), row.get("source_table_title"))
        groups.setdefault(key, []).append(row)
    occurrences = []
    for key, members in groups.items():
        first = members[0]
        children = []
        for item in members:
            # display_name itself may be a section heading and has no number.
            if normalize_text(item.get("statement_item")) == normalize_text(item.get("display_name")):
                continue
            children.append({
                "item": item.get("statement_item"), "member_table": item.get("member_table"),
                "value": item.get("statement_value"), "note_reference_normalized": item.get("note_reference_normalized") or item.get("note_reference") or "",
                "note_reference_status": item.get("note_reference_status"),
                "candidate_note_pdf_page_index": item.get("candidate_note_pdf_page_index") or item.get("note_page"),
                "candidate_note_printed_page": item.get("candidate_note_printed_page"),
                "locator_method": item.get("locator_method"), "confidence": item.get("confidence"),
                "source_discovery_id": item.get("discovery_id"),
            })
        if children:
            occurrences.append({
                **first, "parent_text": first.get("display_name"), "child_rows": children,
                "scope": first.get("scope", "UNKNOWN"), "source_table_title": first.get("source_table_title") or first.get("statement_type"),
                "evidence": {"raw_discovery_ids": [x.get("discovery_id") for x in members], "assembly": "SAME_STATEMENT_PAGE"},
            })
    return occurrences


def hierarchical_backoff(query: dict[str, Any], candidates: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """ML-ready deterministic backoff; no numeric field participates."""
    levels = ("normalized_company", "filing_type", "statement_type", "scope", "display_name", "member_table")
    ranked = []
    for candidate in candidates:
        matched = sum(1 for field in levels if query.get(field) and query.get(field) == candidate.get(field))
        ranked.append(dict(candidate) | {"backoff_score": round(matched / len(levels), 3), "backoff_level": matched})
    return sorted(ranked, key=lambda x: (x["backoff_score"], x.get("success_count", 0)), reverse=True)
