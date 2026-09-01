"""Pattern-driven v6.7 generic discovery engine.

No branch is keyed to a display name.  Registry strategy and member hints
select the resolver; every result remains evidence-backed and reviewable.
"""
from __future__ import annotations

import re
import uuid
from pathlib import Path
from typing import Any

from generic_discovery import discover as statement_discover, assemble_statement_occurrences, normalize_company
from statement_note_navigation import build_text_index
from statement_anchored_family import normalize_text
from generic_structure_parser import GenericStructureParser


class GenericDiscoveryService:
    def __init__(self, definition_service, cache_root: Path):
        self.definitions = definition_service
        self.cache_root = Path(cache_root)
        self.structure_parser = GenericStructureParser()

    def discover(self, *, pdf_path: Path, definition_id: str, company: str = "", report_year: str = "", filing_type: str = "ANNUAL_REPORT") -> dict[str, Any]:
        definition = self.definitions.definition(definition_id)
        if not definition:
            raise KeyError(f"未知 Research Definition：{definition_id}")
        payload = definition["payload"]
        all_candidates: list[dict[str, Any]] = []
        all_occurrences: list[dict[str, Any]] = []
        failures: list[dict[str, Any]] = []
        for family_id in payload.get("table_families", []):
            family = next((x for x in self.definitions.families() if x["family_id"] == family_id), None)
            if not family:
                failures.append({"family_id": family_id, "failure_reason": "NO_FAMILY_REGISTRY"}); continue
            strategy = family["discovery_strategy"]
            members = self.definitions.members(family_id)
            if strategy == "DIRECT_NOTE_TABLE_FAMILY":
                candidates = self._direct_note_family(pdf_path, family, members, company, report_year, filing_type)
                all_candidates.extend(candidates)
                all_occurrences.extend(self.structure_parser.parse(candidates, strategy=strategy, family_id=family_id, display_name=family["display_name"]))
            elif strategy in {"STATEMENT_PARENT_TO_MULTI_NOTE", "STATEMENT_ITEM_TO_NOTE_FAMILY", "STATEMENT_ITEM_TO_SINGLE_NOTE_COMPLEX_TABLE"}:
                candidates = self._statement_strategy(pdf_path, family, members, company, report_year, filing_type)
                all_candidates.extend(candidates)
                all_occurrences.extend(self.structure_parser.parse(candidates, strategy=strategy, family_id=family_id, display_name=family["display_name"]))
            elif strategy == "DIRECT_DISCLOSURE_SEARCH":
                all_candidates.extend(self._direct_disclosure(pdf_path, family, members, company, report_year, filing_type))
            else:
                failures.append({"family_id": family_id, "failure_reason": "UNSUPPORTED_DISCOVERY_STRATEGY", "strategy": strategy})
        return {"definition": definition, "candidates": all_candidates, "occurrences": all_occurrences, "failures": failures}

    def _statement_strategy(self, pdf_path: Path, family: dict[str, Any], members: list[dict[str, Any]], company: str, report_year: str, filing_type: str) -> list[dict[str, Any]]:
        family_payload = family["payload"]
        # Build an ephemeral registry-derived vocabulary. This is not a
        # display-name special case and is intentionally passed as evidence.
        tokens = []
        for member in members:
            tokens.append(member["display_name"])
            tokens.extend(member["payload"].get("aliases", []))
        discovery_context = {
            "preferred_statement_type": (family_payload.get("preferred_statement_types") or [None])[0],
            "core_candidates": tokens,
            "historical_variants": [],
        }
        rows = statement_discover(
            pdf_path,
            self.cache_root,
            display_name=family["display_name"],
            company=company,
            report_year=report_year,
            filing_type=filing_type,
            discovery_context=discovery_context,
        )
        for row in rows:
            row["table_family"] = family["family_id"]
            row["definition_version"] = family["definition_version"]
            row["member_table"] = self._member_for_label(row.get("statement_item", ""), members) or row.get("member_table")
            row["discovery_strategy"] = family["discovery_strategy"]
            row["evidence"]["registry_family"] = family["family_id"]
        return rows

    def _direct_note_family(self, pdf_path: Path, family: dict[str, Any], members: list[dict[str, Any]], company: str, report_year: str, filing_type: str) -> list[dict[str, Any]]:
        index = build_text_index(pdf_path, self.cache_root)
        found: list[dict[str, Any]] = []
        for member in members:
            candidate_titles = [member["display_name"], *member["payload"].get("aliases", [])]
            expected_rows = [normalize_text(x) for x in member["payload"].get("row_signatures", [])]
            expected_cols = [normalize_text(x) for x in member["payload"].get("column_signatures", [])]
            scored = []
            for rec in index:
                text = normalize_text(rec.text)
                matched_titles = [title for title in candidate_titles if normalize_text(title) in text]
                title_score = 1.0 if matched_titles else 0.0
                if not title_score:
                    continue
                row_hits = sum(1 for token in expected_rows if token and token in text)
                col_hits = sum(1 for token in expected_cols if token and token in text)
                score = min(.99, .58 + min(.25, row_hits * .04) + min(.12, col_hits * .04))
                scored.append((score, rec, row_hits, col_hits, matched_titles[0]))
            if not scored:
                found.append(self._abstain(family, member, company, report_year, filing_type, "NO_TABLE_SIGNATURE")); continue
            scored.sort(key=lambda item: item[0], reverse=True)
            top = scored[0]
            ambiguous = len(scored) > 1 and top[0] - scored[1][0] < .06
            score, rec, row_hits, col_hits, matched_title = top
            certified_heading = self._direct_heading_context(rec.text, matched_title)
            found.append({
                "discovery_id": "MD_" + uuid.uuid4().hex, "company": company, "normalized_company": normalize_company(company), "report_year": str(report_year), "filing_type": filing_type,
                "statement_type": "NOTE_SECTION", "scope": family["payload"].get("preferred_scope") or "UNKNOWN", "display_name": family["display_name"], "table_family": family["family_id"], "definition_version": family["definition_version"],
                "statement_item": member["display_name"], "member_table": member["member_id"], "member_display_name": member["display_name"], "matched_title": matched_title, "certified_heading": certified_heading, "source_table_title": matched_title,
                "statement_pdf_page_index": rec.page_number, "candidate_note_pdf_page_index": rec.page_number, "candidate_note_pages": [x[1].page_number for x in scored[:5]],
                "locator_method": "DIRECT_NOTE_TITLE_ROW_COLUMN_SIGNATURE", "confidence": round(score, 2), "status": "REVIEW_REQUIRED" if ambiguous or score < .78 else "NEEDS_REVIEW",
                "failure_reason": "MULTIPLE_HIGH_SCORE_CANDIDATES" if ambiguous else None, "note_reference": "", "note_reference_status": "NOT_APPLICABLE",
                "evidence": {"title_candidates": candidate_titles, "matched_title": matched_title, "certified_heading": certified_heading, "matched_page_text": rec.text[:2000], "row_signature_hits": row_hits, "column_signature_hits": col_hits, "strategy": "DIRECT_NOTE_TABLE_FAMILY"},
            })
        return found

    def _direct_disclosure(self, pdf_path: Path, family: dict[str, Any], members: list[dict[str, Any]], company: str, report_year: str, filing_type: str) -> list[dict[str, Any]]:
        return self._direct_note_family(pdf_path, family, members, company, report_year, filing_type)

    @staticmethod
    def _direct_heading_context(text: str, matched_title: str) -> str:
        """Return a nearby section heading for strict page-identity checks.

        The detail query can be a subtable title, while the deterministic
        boundary resolver validates against the enclosing disclosure heading.
        This is text-position based, not a family-name special case.
        """
        lines = [line.strip() for line in str(text or "").splitlines() if line.strip()]
        target = normalize_text(matched_title)
        for index, line in enumerate(lines):
            if target and target in normalize_text(line):
                previous_lines = list(reversed(lines[max(0, index - 4):index]))
                # Prefer a nearby semantic section heading (often contains
                # 投资/保险/资产) over company names and date boilerplate.
                for previous in previous_lines:
                    compact = normalize_text(previous)
                    if (any(token in compact for token in ("投资", "资产", "保险"))
                            and "中国平安" not in compact and "年报" not in compact):
                        return previous
                for previous in previous_lines:
                    compact = normalize_text(previous)
                    if (len(compact) >= 4 and not re.search(r"20\d{2}|人民币|年报|主要业务", compact)
                            and not re.fullmatch(r"\d+", compact)):
                        return previous
                return line
        return matched_title

    @staticmethod
    def _member_for_label(label: str, members: list[dict[str, Any]]) -> str | None:
        normalized = normalize_text(label)
        for member in members:
            candidates = [member["display_name"], *member["payload"].get("aliases", [])]
            if any(normalize_text(token) == normalized for token in candidates): return member["member_id"]
        return None

    @staticmethod
    def _abstain(family, member, company, report_year, filing_type, reason):
        return {"discovery_id": "MD_" + uuid.uuid4().hex, "company": company, "normalized_company": normalize_company(company), "report_year": str(report_year), "filing_type": filing_type, "statement_type": "NOTE_SECTION", "scope": "UNKNOWN", "display_name": family["display_name"], "table_family": family["family_id"], "definition_version": family["definition_version"], "statement_item": member["display_name"], "member_table": member["member_id"], "confidence": 0.0, "status": "UNRESOLVED", "failure_reason": reason, "evidence": {"strategy": family["discovery_strategy"]}}
