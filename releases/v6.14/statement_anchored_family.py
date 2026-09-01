"""Deterministic Statement-Anchored Table Family primitives for v6.5.

The module only models extracted evidence.  It never parses a financial value
from a guess and it never fabricates a value.  PDF parsing remains upstream.
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, asdict
import re
from typing import Any, Iterable


NOTE_STATUSES = {
    "EXPLICIT", "COMPOSED_FROM_HEADER_AND_ROW", "INFERRED",
    "EXPLICIT_ORDINAL_COLUMN", "CROSS_REFERENCE_REVIEW_REQUIRED",
    "ABSENT_ON_STATEMENT", "AMBIGUOUS", "NOT_APPLICABLE",
}


def normalize_text(value: str | None) -> str:
    return re.sub(r"\s+", "", str(value or "")).strip().lower()


def compose_note_reference(header: str | None, row_value: str | int | None) -> dict[str, str]:
    """Normalize a statement note cell while preserving its disclosure grammar.

    Supported, non-equivalent forms are:

    * ``附注八`` + ``11`` -> ``附注八-11``;
    * bare ``附注`` + ``11`` -> ``附注11``.

    A cross-reference such as ``8/59(1)`` is retained as evidence but is never
    silently turned into a single note target.
    """
    raw_header, raw_item = str(header or "").strip(), str(row_value or "").strip()
    section_match = re.search(r"(?:附注|注)\s*([一二三四五六七八九十百\d]+)", raw_header)
    item_match = re.fullmatch(r"([0-9]{1,3}|[一二三四五六七八九十百]+)", raw_item)
    if section_match and item_match:
        section, item = section_match.group(1), item_match.group(1)
        return {
            "note_reference_section": section,
            "note_reference_item": item,
            "note_reference_raw": f"{raw_header} / {raw_item}",
            "note_reference_normalized": f"附注{section}-{item}",
            "note_reference_status": "COMPOSED_FROM_HEADER_AND_ROW",
        }
    generic_note_column = bool(re.fullmatch(r"(?:附注|注)\s*", raw_header))
    if generic_note_column and item_match:
        item = item_match.group(1)
        return {
            "note_reference_section": "",
            "note_reference_item": item,
            "note_reference_raw": f"{raw_header} / {raw_item}",
            "note_reference_normalized": f"附注{item}",
            "note_reference_status": "EXPLICIT_ORDINAL_COLUMN",
        }
    if generic_note_column and raw_item and re.search(r"[/／（）()]", raw_item):
        return {
            "note_reference_section": "", "note_reference_item": raw_item,
            "note_reference_raw": f"{raw_header} / {raw_item}",
            "note_reference_normalized": "",
            "note_reference_status": "CROSS_REFERENCE_REVIEW_REQUIRED",
        }
    if raw_item and re.search(r"(?:附注|注)", raw_item):
        return {
            "note_reference_section": "", "note_reference_item": raw_item,
            "note_reference_raw": raw_item,
            "note_reference_normalized": re.sub(r"\s+", "", raw_item),
            "note_reference_status": "EXPLICIT",
        }
    return {
        "note_reference_section": "", "note_reference_item": raw_item,
        "note_reference_raw": raw_item, "note_reference_normalized": "",
        "note_reference_status": "ABSENT_ON_STATEMENT" if not raw_item else "AMBIGUOUS",
    }


@dataclass(frozen=True)
class StatementOccurrence:
    occurrence_id: str
    display_name: str
    statement_type: str
    source_table_title: str
    scope: str
    statement_pdf_page_index: int | None
    statement_printed_page: str | None
    parent_text: str
    child_rows: tuple[dict[str, Any], ...]
    evidence: dict[str, Any]

    def score(self, historical_bonus: float = 0.0) -> float:
        children = list(self.child_rows)
        total = len(children)
        refs = sum(bool(x.get("note_reference_normalized") or x.get("note_reference")) for x in children)
        values = sum(x.get("value") is not None for x in children)
        feasible = sum(bool(x.get("candidate_note_pdf_page_index") or x.get("candidate_note_page")) for x in children)
        # Structural evidence matters more than a hard-coded consolidated scope.
        return round(0.25 * min(total / 4, 1) + 0.35 * (refs / total if total else 0)
                     + 0.20 * (values / total if total else 0)
                     + 0.20 * (feasible / total if total else 0) + historical_bonus, 4)


def arbitrate_anchors(occurrences: Iterable[StatementOccurrence], *, scope_preference: str | None = None,
                      historical_scores: dict[str, float] | None = None) -> dict[str, Any]:
    historical_scores = historical_scores or {}
    ranked = []
    for occ in occurrences:
        bonus = historical_scores.get(occ.occurrence_id, 0.0)
        score = occ.score(bonus)
        if scope_preference and occ.scope == scope_preference:
            score = round(score + 0.02, 4)
        ranked.append({"occurrence": asdict(occ), "anchor_score": score})
    ranked.sort(key=lambda x: x["anchor_score"], reverse=True)
    if not ranked:
        return {"status": "UNRESOLVED", "selected": None, "candidates": []}
    top = ranked[0]
    multiple = len(ranked) > 1 and abs(top["anchor_score"] - ranked[1]["anchor_score"]) <= 0.03
    return {
        "status": "MULTIPLE_VALID_ANCHORS" if multiple else "SINGLE_STRONG_ANCHOR",
        "selected": None if multiple else top,
        "candidates": ranked,
    }


def build_statement_anchor_table(occurrence: StatementOccurrence, *, table_family: str | None = None) -> dict[str, Any]:
    """Return an immutable-ready anchor table: SECTION_PARENT + child items."""
    family = table_family or occurrence.display_name
    rows = [{
        "item": occurrence.parent_text or occurrence.display_name,
        "row_type": "SECTION_PARENT", "parent_item": None, "value": None,
        "note_reference_normalized": "", "member_table_role": "STATEMENT_ANCHOR",
    }]
    for child in occurrence.child_rows:
        rows.append({
            **child,
            "row_type": child.get("row_type", "STATEMENT_ITEM"),
            "parent_item": occurrence.parent_text or occurrence.display_name,
            "member_table_role": "STATEMENT_ANCHOR",
        })
    return {
        "table_family": family,
        "member_table": f"{family}_主报表构成",
        "member_table_role": "STATEMENT_ANCHOR",
        "source_table_title": occurrence.source_table_title,
        "scope": occurrence.scope,
        "statement_pdf_page_index": occurrence.statement_pdf_page_index,
        "statement_printed_page": occurrence.statement_printed_page,
        "rows": rows,
        "machine_evidence": occurrence.evidence,
    }


def build_capture_plan(occurrence: StatementOccurrence, *, table_family: str | None = None,
                       certified_ids: Iterable[str] = (), selected_anchor: bool = False,
                       allow_direct_search_fallback: bool = False) -> dict[str, Any]:
    """Build 1 statement-anchor item plus N note-detail capture items.

    A child with no confirmed/candidate page is retained as REVIEW_REQUIRED; it
    is not silently sent to a generic capture worker.
    """
    if not selected_anchor:
        # This is a service-level invariant, not a UI convention.  It prevents
        # an unselected alternative (for example standalone vs consolidated)
        # from ever becoming a plan, job, or capture.
        raise PermissionError("UNSELECTED_ANCHOR_NEVER_MATERIALIZES")
    family = table_family or occurrence.display_name
    anchor = build_statement_anchor_table(occurrence, table_family=family)
    items = [{
        "member_table": anchor["member_table"], "member_table_role": "STATEMENT_ANCHOR",
        "capture_mode": "MATERIALIZE_ANCHOR", "source_pdf_page_index": occurrence.statement_pdf_page_index,
        "source_printed_page": occurrence.statement_printed_page, "depends_on": [],
    }]
    for order, child in enumerate(occurrence.child_rows, start=1):
        certified_target = dict(child.get("certified_note_target") or {})
        target_page = certified_target.get("confirmed_note_pdf_page_index")
        target_status = certified_target.get("status")
        # Direct-search fallback is deliberately opt-in and never receives the
        # same status as a certified target.
        if not target_page and allow_direct_search_fallback:
            target_page = child.get("candidate_note_pdf_page_index") or child.get("candidate_note_page")
            target_status = "DIRECT_SEARCH_FALLBACK_REVIEW_REQUIRED" if target_page else "NOTE_TARGET_UNRESOLVED"
        items.append({
            "member_table": child.get("member_table") or child.get("item"),
            "member_table_role": "NOTE_DETAIL", "capture_mode": "NOTE_DETAIL",
            "note_reference": child.get("note_reference_normalized") or child.get("note_reference") or "",
            "candidate_note_pdf_page_index": child.get("candidate_note_pdf_page_index") or child.get("candidate_note_page"),
            "confirmed_note_pdf_page_index": target_page,
            "certified_note_target": certified_target,
            "classification_axis": child.get("classification_axis") or certified_target.get("classification_axis") or "",
            "status": "READY" if target_status == "CERTIFIED_NOTE_TARGET" and target_page else "REVIEW_REQUIRED",
            "target_status": target_status or "NOTE_TARGET_UNRESOLVED",
            "capture_order": order, "depends_on": [anchor["member_table"]],
        })
    return {
        "plan_status": "CERTIFIED" if all(x.get("status", "READY") == "READY" for x in items) else "REVIEW_REQUIRED",
        "table_family": family, "anchor": anchor, "items": items,
        "anchor_occurrence_id": occurrence.occurrence_id,
        "certified_discovery_ids": list(certified_ids),
    }


def cluster_evidence(rows: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    """Cluster locator paths into one reviewable candidate, retaining evidence."""
    groups: dict[tuple, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        page = row.get("candidate_note_pdf_page_index") or row.get("note_page")
        key = (row.get("normalized_company") or row.get("company"), row.get("report_year"),
               normalize_text(row.get("display_name")), row.get("statement_type"), row.get("scope"),
               normalize_text(row.get("member_table") or row.get("statement_item")), page)
        groups[key].append(row)
    out = []
    for key, evidence in groups.items():
        representative = max(evidence, key=lambda x: float(x.get("confidence") or 0))
        out.append({**representative, "candidate_cluster_id": "CLUSTER_" + str(abs(hash(key))),
                    "evidence_count": len(evidence), "evidence_members": evidence,
                    "confidence": max(float(x.get("confidence") or 0) for x in evidence)})
    return sorted(out, key=lambda x: (str(x.get("company")), str(x.get("report_year")), -x["confidence"]))
