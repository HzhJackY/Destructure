"""Generic Statement-Guided Family Discovery; presets only add optional priors."""
from __future__ import annotations

from typing import Any
from statement_note_navigation import build_text_index, locate_primary_statements, locate_note

PRESETS = {
    "金融投资": {"preferred_statement_type": "BALANCE_SHEET", "core_candidates": ["交易性金融资产", "债权投资", "其他债权投资", "其他权益工具投资"],
             "historical_variants": ["以公允价值计量且其变动计入当期损益的金融资产", "可供出售金融资产", "持有至到期投资"],
             "expansion_candidates": ["定期存款", "买入返售金融资产", "长期股权投资", "存出资本保证金"], "definition_version": "FINANCIAL_INVESTMENT_V1"}
}

def normalize_company(value: str) -> str:
    return "".join((value or "").split()).replace("年报", "")

def discover(pdf_path, cache_root, *, display_name: str, company: str = "", report_year: str = "", filing_type: str = "ANNUAL_REPORT", preset_name: str | None = None, text_provider=None) -> list[dict[str, Any]]:
    """Discover candidates for any display name; never extracts or invents values."""
    prior = PRESETS.get(preset_name or display_name, {})
    index = build_text_index(pdf_path, cache_root, text_provider=text_provider)
    statements = locate_primary_statements(index)
    preferred = prior.get("preferred_statement_type")
    candidate_types = [preferred] if preferred else [kind for kind, pages in statements.items() if pages]
    # Generic names often add a research suffix (for example “债权投资研究”).
    # Remove only presentation suffixes; no financial semantic is invented.
    normalized_name = display_name
    for suffix in ("研究", "明细", "表族", "项目", "分析"):
        if normalized_name.endswith(suffix): normalized_name = normalized_name[:-len(suffix)]
    tokens = [display_name, normalized_name] + prior.get("core_candidates", []) + prior.get("historical_variants", [])
    rows: list[dict[str, Any]] = []
    for statement_type in candidate_types:
        pages = set(statements.get(statement_type, []))
        for rec in index:
            if rec.page_number not in pages: continue
            for line in rec.text.splitlines():
                text = " ".join(line.split())
                matched = next((t for t in sorted(tokens, key=len, reverse=True) if t and t in text), None)
                if not matched: continue
                # A number after the label is treated only as a proposed cross-reference.
                tail = text.split(matched, 1)[1]
                import re
                number = re.search(r"(?:附注\s*)?([0-9]{1,3})(?:\D|$)", tail)
                note_ref = number.group(1) if number else ""
                page, method, confidence = locate_note(index, note_reference=note_ref, item=matched, section_context=rec.section) if note_ref else (None, "NO_NOTE_REFERENCE", .35)
                rows.append({"company": company, "normalized_company": normalize_company(company), "report_year": str(report_year), "filing_type": filing_type,
                             "statement_type": statement_type, "display_name": display_name, "table_family": display_name,
                             "statement_item": matched, "note_reference": note_ref, "member_table": matched, "source_table_title": matched,
                             "section_context": rec.section, "statement_page": rec.page_number, "note_page": page,
                             "locator_method": method, "confidence": confidence, "status": "NEEDS_REVIEW",
                             "evidence": {"raw_line": text, "prior": prior, "statement_pages": sorted(pages)}})
    unique = {}
    for row in rows:
        key = (row["statement_type"], row["statement_item"], row["note_reference"], row["statement_page"])
        unique.setdefault(key, row)
    return list(unique.values())

def hierarchical_backoff(query: dict[str, Any], candidates: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Deterministic ML-ready ranking using the required knowledge hierarchy."""
    levels = ("normalized_company", "filing_type", "statement_type", "display_name", "member_table")
    ranked=[]
    for candidate in candidates:
        matched=sum(1 for field in levels if query.get(field) and query.get(field)==candidate.get(field))
        score=round(matched/len(levels), 3)
        ranked.append(dict(candidate) | {"backoff_score": score, "backoff_level": matched})
    return sorted(ranked, key=lambda x: (x["backoff_score"], x.get("success_count", 0)), reverse=True)
