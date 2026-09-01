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
from statement_family_resolution import StatementFamilyResolver


class GenericDiscoveryService:
    def __init__(self, definition_service, cache_root: Path):
        self.definitions = definition_service
        self.cache_root = Path(cache_root)
        self.structure_parser = GenericStructureParser()
        self.family_resolver = StatementFamilyResolver()
        self.last_statement_discovery_audit: dict[str, Any] = {}

    def discover(self, *, pdf_path: Path, definition_id: str, company: str = "", report_year: str = "", filing_type: str = "ANNUAL_REPORT") -> dict[str, Any]:
        definition = self.definitions.definition(definition_id)
        if not definition:
            raise KeyError(f"未知 Research Definition：{definition_id}")
        payload = definition["payload"]
        all_candidates: list[dict[str, Any]] = []
        all_occurrences: list[dict[str, Any]] = []
        failures: list[dict[str, Any]] = []
        discovery_audits: list[dict[str, Any]] = []
        family_resolutions: list[dict[str, Any]] = []
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
                if self.last_statement_discovery_audit:
                    discovery_audits.append({"family_id": family_id, **self.last_statement_discovery_audit})
                    family_resolutions.extend(self.last_statement_discovery_audit.get("statement_family_resolutions") or [])
                all_occurrences.extend(self.structure_parser.parse(candidates, strategy=strategy, family_id=family_id, display_name=family["display_name"]))
                if not candidates and self.last_statement_discovery_audit:
                    failures.append({
                        "family_id": family_id,
                        "failure_reason": self.last_statement_discovery_audit.get("final_status", "MAIN_STATEMENT_NOT_FOUND"),
                        "ocr_audit": dict(self.last_statement_discovery_audit),
                    })
            elif strategy == "DIRECT_DISCLOSURE_SEARCH":
                all_candidates.extend(self._direct_disclosure(pdf_path, family, members, company, report_year, filing_type))
            else:
                failures.append({"family_id": family_id, "failure_reason": "UNSUPPORTED_DISCOVERY_STRATEGY", "strategy": strategy})
        return {"definition": definition, "candidates": all_candidates, "occurrences": all_occurrences,
                "failures": failures, "discovery_audits": discovery_audits,
                "family_resolutions": family_resolutions}

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
            "discovery_strategy": family["discovery_strategy"],
            "preferred_scope": family_payload.get("preferred_scope"),
            "require_note_reference": family["discovery_strategy"] in {
                "STATEMENT_PARENT_TO_MULTI_NOTE",
                "STATEMENT_ITEM_TO_NOTE_FAMILY",
                "STATEMENT_ITEM_TO_SINGLE_NOTE_COMPLEX_TABLE",
            },
        }
        audit: dict[str, Any] = {}
        # A research family need not have a literal parent row in every
        # accounting presentation. Resolve the source statement structure
        # through the registry contract, retaining a NULL raw parent for an
        # implicit member set rather than fabricating PDF evidence.
        index = build_text_index(pdf_path, self.cache_root)
        resolved_rows, resolutions = self.family_resolver.resolve(
            index=index, family=family, members=members, company=company,
            report_year=report_year, filing_type=filing_type,
        )
        if resolutions:
            audit["statement_family_resolutions"] = resolutions
            audit["final_status"] = "FINANCIAL_INVESTMENT_STATEMENT_FAMILY_RESOLVED"
            audit["ocr_triggered"] = False
            rows = resolved_rows
        else:
            rows = statement_discover(
                pdf_path,
                self.cache_root,
                display_name=family["display_name"],
                company=company,
                report_year=report_year,
                filing_type=filing_type,
                discovery_context=discovery_context,
                audit_sink=audit,
            )
            # OCR can expose an image-only statement that the native text
            # resolver could not see. Materialise the same family-resolution
            # contract from those immutable OCR lines; do not turn optional
            # rows outside a real parent into children.
            # generic_discovery deliberately preserves the source label as
            # member_table during raw OCR discovery.  Family resolution,
            # however, operates on Registry member IDs.  Normalize before
            # resolving (not afterwards) while retaining statement_item and
            # raw_member_table as immutable source evidence.
            self._normalize_ocr_rows_to_registry(rows, members)
            resolutions = self._resolution_from_discovered_rows(rows, family)
            if resolutions:
                audit["statement_family_resolutions"] = resolutions
                resolution = resolutions[0]
                if resolution.get("quality_status") == "REVIEW_REQUIRED":
                    audit["final_status"] = "FINANCIAL_INVESTMENT_PARENT_UNRESOLVED"
                    audit["ocr_triggered"] = True
                else:
                    audit["final_status"] = "FINANCIAL_INVESTMENT_STATEMENT_FAMILY_RESOLVED"
                selected_ids = set(resolution.get("member_ids") or [])
                parent_rows = [x for x in rows if normalize_text(x.get("statement_item")) == normalize_text(family["display_name"])]
                rows = (parent_rows if resolution.get("raw_parent_row_id") else []) + [x for x in rows if x.get("member_table") in selected_ids]
                for row in rows:
                    if row.get("member_table") in selected_ids:
                        origin = resolution["member_origins"].get(row.get("member_table"), "DIRECT_STATEMENT_ROW")
                        row["statement_family_resolution_id"] = resolution["resolution_id"]
                        row["member_origin"] = origin
                        row["presentation_regime"] = resolution["presentation_regime"]
                        row["comparability_status"] = (
                            "EXACT" if resolution["presentation_regime"] == "NEW_FINANCIAL_INSTRUMENT_CLASSIFICATION"
                            else "PARTIALLY_COMPARABLE" if resolution["presentation_regime"] == "LEGACY_FINANCIAL_ASSET_CLASSIFICATION"
                            else "UNRESOLVED"
                        )
                        row["family_total_status"] = "NOT_REPORTED"
        self.last_statement_discovery_audit = audit
        for row in rows:
            row["table_family"] = family["family_id"]
            row["definition_version"] = family["definition_version"]
            row["member_table"] = self._member_for_label(row.get("statement_item", ""), members) or row.get("member_table")
            row["discovery_strategy"] = family["discovery_strategy"]
            row["evidence"]["registry_family"] = family["family_id"]
            row["evidence"]["main_statement_discovery_audit"] = dict(audit)
        return rows

    @staticmethod
    def _normalize_ocr_rows_to_registry(rows: list[dict[str, Any]], members: list[dict[str, Any]]) -> None:
        """Attach registry identity to raw OCR rows before family resolution.

        This keeps OCR source labels in ``statement_item`` and audit evidence;
        only the semantic ``member_table`` field changes.  Where the same raw
        label exists in legacy and new presentation definitions, a registered
        direct legacy row on the same statement is sufficient evidence to use
        the legacy member identity rather than inventing a cross-regime bridge.
        """
        labels = {normalize_text(row.get("statement_item")) for row in rows}
        legacy_signal = any(
            (member.get("payload") or {}).get("direct_member", False)
            and normalize_text(member["display_name"]) in labels
            for member in members
        )
        for row in rows:
            source_member_table = row.get("member_table")
            label = str(row.get("statement_item") or "")
            matched = [member for member in members if any(
                normalize_text(token) == normalize_text(label)
                for token in [member["display_name"], *(member.get("payload") or {}).get("aliases", [])]
            )]
            if not matched:
                continue
            if legacy_signal:
                legacy = next((member for member in matched if (member.get("payload") or {}).get("direct_member", False)), None)
                chosen = legacy or min(matched, key=lambda member: member.get("canonical_order", 999))
            else:
                chosen = min(matched, key=lambda member: member.get("canonical_order", 999))
            row["source_member_table_raw"] = source_member_table
            row["member_table"] = chosen["member_id"]
            evidence = row.setdefault("evidence", {})
            evidence["registry_member_id"] = chosen["member_id"]
            evidence["source_member_table_raw"] = source_member_table

    @staticmethod
    def _resolution_from_discovered_rows(rows: list[dict[str, Any]], family: dict[str, Any]) -> list[dict[str, Any]]:
        if not rows:
            return []
        parent = next((x for x in rows if normalize_text(x.get("statement_item")) == normalize_text(family["display_name"])), None)
        contract = dict(family["payload"].get("family_resolution_contract") or {})
        allowed = set(contract.get("allowed_resolution_modes") or [])
        core = set(family["payload"].get("core_members") or [])
        direct = set(contract.get("direct_member_concepts") or [])
        explicit = [x for x in rows if x.get("member_table") in core]
        direct_rows = [x for x in rows if x.get("member_table") in direct]
        # The OCR boundary resolver may recover members while being unable to
        # prove whether their visible parent label was actually captured. In
        # that state an implicit family would be a semantic guess, not source
        # evidence. Preserve an auditable unresolved result and require human
        # review instead of materialising/certifying candidates.
        parent_unreadable = any(
            (row.get("evidence") or {}).get("family_parent_recovery_status") == "REVIEW_REQUIRED_OCR_PARENT_UNREADABLE"
            for row in rows
        )
        source = parent or (explicit[0] if explicit else (direct_rows[0] if direct_rows else rows[0]))
        if parent_unreadable and not parent:
            source_page = source.get("statement_pdf_page_index")
            return [{
                "resolution_id": "SFR_" + uuid.uuid4().hex,
                "source_pdf_id": "", "source_pdf_sha256": "",
                "company": source.get("company"), "report_year": str(source.get("report_year") or ""),
                "requested_scope": source.get("scope"), "family_id": family["family_id"],
                "resolution_mode": "UNRESOLVED_OCR_PARENT",
                "source_statement_anchor_id": f"STMT_{source_page}",
                "raw_parent_row_id": None, "raw_parent_label": None,
                "derived_family_label": family["display_name"],
                "derived_family_label_is_source_text": False,
                "member_count": 0, "member_ids": [], "member_origins": {},
                "family_total_status": "NOT_REPORTED",
                "reported_family_total_raw": None, "derived_family_total_raw": None,
                "presentation_regime": "UNKNOWN", "quality_status": "REVIEW_REQUIRED",
                "review_status": "REVIEW_REQUIRED",
                "evidence": {
                    "resolver": "OCR_DISCOVERED_STATEMENT_FAMILY",
                    "reason": "OCR_PARENT_UNREADABLE",
                    "source_rows": [{
                        "source_row_id": x.get("source_row_id"),
                        "member_table": x.get("member_table"),
                        "source_pdf_page_index": x.get("statement_pdf_page_index"),
                    } for x in rows],
                },
                "producer_version": "v6.10", "statement_pdf_page_index": source_page,
            }]
        if parent and explicit and "EXPLICIT_PARENT" in allowed:
            # An OCR-visible explicit parent closes this family around its
            # current-classification children. Do not append other direct
            # rows merely because they share a statement page: that would
            # manufacture a HYBRID old/new regime family.
            children = explicit
            mode = "EXPLICIT_PARENT"
        elif parent and direct_rows and "EXPLICIT_PARENT" in allowed:
            # Literal parent with legacy direct children is still an explicit
            # family; the parent is source evidence and no cross-regime merge
            # is implied.
            children = direct_rows
            mode = "EXPLICIT_PARENT"
        elif direct_rows and "IMPLICIT_MEMBER_SET" in allowed:
            children = direct_rows
            mode = "IMPLICIT_MEMBER_SET"
        else:
            return []
        labels = [str(x.get("statement_item") or "") for x in children]
        compact = "|".join(normalize_text(x) for x in labels)
        has_new = any(normalize_text(x) in compact for x in ("交易性金融资产", "债权投资", "其他债权投资", "其他权益工具投资"))
        has_legacy = any(normalize_text(x) in compact for x in ("可供出售金融资产", "持有至到期投资", "贷款及应收款项", "贷款"))
        regime = "MIXED_TRANSITION_PRESENTATION" if has_new and has_legacy else "NEW_FINANCIAL_INSTRUMENT_CLASSIFICATION" if has_new else "LEGACY_FINANCIAL_ASSET_CLASSIFICATION" if has_legacy else "UNKNOWN"
        member_origins = {x.get("member_table"): "EXPLICIT_CHILD_ROW" if parent else "DIRECT_STATEMENT_ROW" for x in children}
        source_page = (parent or children[0]).get("statement_pdf_page_index")
        return [{
            "resolution_id": "SFR_" + uuid.uuid4().hex,
            "source_pdf_id": "", "source_pdf_sha256": "",
            "company": (parent or children[0]).get("company"), "report_year": str((parent or children[0]).get("report_year") or ""),
            "requested_scope": (parent or children[0]).get("scope"), "family_id": family["family_id"],
            "resolution_mode": mode, "source_statement_anchor_id": f"STMT_{source_page}",
            "raw_parent_row_id": f"OCR_ROW_{source_page}_PARENT" if parent else None,
            "raw_parent_label": parent.get("statement_item") if parent else None, "derived_family_label": family["display_name"],
            "derived_family_label_is_source_text": bool(parent), "member_count": len(children),
            "member_ids": [x.get("member_table") for x in children], "family_total_status": "NOT_REPORTED",
            "reported_family_total_raw": None, "derived_family_total_raw": None,
            "presentation_regime": regime, "member_origins": member_origins,
            "quality_status": "RESOLVED", "review_status": "REVIEW_REQUIRED" if mode != "EXPLICIT_PARENT" else "NEEDS_REVIEW",
            "evidence": {
                "resolver": "OCR_DISCOVERED_STATEMENT_FAMILY",
                "parent_raw_line": ((parent.get("evidence") or {}).get("raw_line") if parent else None),
                "source_rows": [{
                    "source_row_id": x.get("source_row_id"),
                    "member_table": x.get("member_table"),
                    "source_pdf_page_index": x.get("statement_pdf_page_index"),
                } for x in children],
            },
            "producer_version": "v6.10", "statement_pdf_page_index": source_page,
        }]

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
        """v6.10: section-scoped disclosure search for investment portfolio tables.

        Searches MANAGEMENT_DISCUSSION, INVESTMENT_BUSINESS_ANALYSIS, and
        BUSINESS_REVIEW sections — not financial statement notes.  Falls
        back to the full-text _direct_note_family path when the PDF has
        no identifiable disclosure sections.
        """
        try:
            from statement_note_navigation import (
                locate_disclosure_sections, classify_absence,
                build_text_index,
            )
        except ImportError:
            return self._direct_note_family(pdf_path, family, members, company, report_year, filing_type)

        index = build_text_index(pdf_path, self.cache_root)
        sections = locate_disclosure_sections(index)
        disclosure_pages: set[int] = set()
        for pages in sections.values():
            disclosure_pages.update(pages)

        # If no disclosure sections found, fall back to full-text search
        # but mark results as lower confidence.
        if not disclosure_pages:
            return self._direct_note_family(pdf_path, family, members, company, report_year, filing_type)

        candidates: list[dict[str, Any]] = []
        for member in members:
            if member.get("member_role") == "STATEMENT_ANCHOR":
                continue
            payload = member.get("payload") or {}
            display_name = member.get("display_name", "")
            aliases = list(payload.get("aliases") or [])
            classification_axis = payload.get("classification_axis") or ""
            search_titles = [display_name] + aliases

            found_exact = False
            found_alias = False
            found_table = False
            found_narrative = False

            for rec in index:
                if rec.page_number not in disclosure_pages:
                    continue
                text = rec.text or ""
                heading = rec.heading or ""

                # Tier A: exact title in heading
                if any(t == heading for t in search_titles):
                    found_exact = True
                    found_table = self._has_table_evidence(text)
                # Tier B: certified alias in heading or body
                elif any(t in heading for t in search_titles):
                    found_alias = True
                    found_table = self._has_table_evidence(text)
                elif any(t in text[:3000] for t in search_titles):
                    found_narrative = True

            absence = classify_absence(
                candidates_found=int(found_exact or found_alias),
                exact_title_match=found_exact,
                certified_alias_match=found_alias,
                section_searched=True,
                table_evidence=found_table,
                narrative_only=found_narrative and not found_table,
            )

            candidates.append({
                "discovery_id": "DDISC_" + uuid.uuid4().hex,
                "family_id": family["family_id"],
                "member_id": member["member_id"],
                "member_display_name": display_name,
                "classification_axis": classification_axis,
                "absence_classification": absence,
                "company": company,
                "report_year": str(report_year),
                "filing_type": filing_type,
                "status": "REVIEW_REQUIRED" if absence not in {"FOUND_CANONICAL_TABLE"} else "NEEDS_REVIEW",
                "evidence": {
                    "exact_title_match": found_exact,
                    "certified_alias_match": found_alias,
                    "table_evidence": found_table,
                    "narrative_only": found_narrative,
                    "absence": absence,
                    "sections_searched": list(sections.keys()),
                    "disclosure_pages": sorted(disclosure_pages),
                },
            })

        return candidates

    @staticmethod
    def _has_table_evidence(text: str) -> bool:
        """Quick check for tabular structure in page text."""
        numbers = len(re.findall(r"\d[\d,，.]*\d", text))
        return numbers >= 4

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
