"""Generic evidence-first table/statement structure parser for v6.7.

It consumes candidate evidence from any discovery strategy and returns
reviewable parent/child structures. It never invents note numbers or values.
"""
from __future__ import annotations
from typing import Any

class GenericStructureParser:
    def parse(self, candidates: list[dict[str, Any]], *, strategy: str, family_id: str, display_name: str) -> list[dict[str, Any]]:
        if strategy in {
            "DIRECT_NOTE_TABLE_FAMILY",
            "DIRECT_MAIN_STATEMENT_TABLE",
            "DIRECT_PORTFOLIO_TABLES",
        }:
            return self._direct(candidates, family_id, display_name, strategy=strategy)
        return self._statement(candidates, family_id, display_name, strategy)

    def _statement(self, candidates, family_id, display_name, strategy):
        groups={}
        for candidate in candidates:
            key=(candidate.get("pdf_id"),candidate.get("statement_type"),candidate.get("scope"),candidate.get("statement_pdf_page_index"),candidate.get("source_table_title"))
            groups.setdefault(key,[]).append(candidate)
        output=[]
        for _,items in groups.items():
            first=items[0]
            children=[]
            for item in items:
                single_item_strategy = strategy in {
                    "STATEMENT_ITEM_TO_NOTE_FAMILY",
                    "STATEMENT_ITEM_TO_SINGLE_NOTE_COMPLEX_TABLE",
                }
                if item.get("member_table") and (
                    item.get("statement_item") != display_name or single_item_strategy
                ):
                    target_page = item.get("candidate_note_pdf_page_index") or item.get("note_page")
                    # The review UI certifies a concrete target candidate, not
                    # a bare page field.  Preserve the locator result as a
                    # candidate object so generic statement discovery follows
                    # the same Discovery -> Review -> Certified Plan contract
                    # as the legacy Statement→Note workflow.
                    target_candidates = []
                    if target_page:
                        target_candidates.append({
                            "pdf_page_index": target_page,
                            "heading": item.get("statement_item") or item.get("member_table"),
                            "capture_query_title": item.get("statement_item") or item.get("member_table"),
                            "locator_method": item.get("locator_method") or "UNRESOLVED",
                            "score": float(item.get("confidence") or 0),
                            "status": "NOTE_TARGET_CANDIDATE",
                            "evidence": item.get("evidence") or {},
                        })
                    # Keep the complete statement-member amount contract here.
                    # ``create_anchor_children`` consumes this structure later;
                    # retaining only the raw display value caused all child
                    # mappings to persist an empty amount array.
                    ocr_used = bool(item.get("ocr_used"))
                    member_period_status = str(
                        item.get("member_period_status") or "UNRESOLVED"
                    )
                    native_value_geometry_present = bool(
                        item.get("native_value_geometry_present")
                    )
                    if ocr_used:
                        # OCR page text is a locator/token source only.  It has
                        # no trustworthy native cell geometry, so numeric
                        # tokens must never enter the canonical value channel.
                        statement_amount_raw = []
                        statement_amount_normalized = []
                        statement_amounts = []
                        values = []
                        amount_source_present = False
                        # OCR figures must remain outside the certified
                        # Statement/Canonical value channel.  A TSV/BBox-bound
                        # observation is nevertheless valid *Anchor review*
                        # evidence: Golden Stage-A compares that separate
                        # evidence field, never ``statement_amount_*``.
                        value_evidence_status = (
                            "OCR_SPATIAL_COLUMN_GEOMETRY_OBSERVATION"
                            if item.get("anchor_amount_observations")
                            and bool(item.get("ocr_spatial_geometry_verified"))
                            else "REJECTED_OCR_WITHOUT_NATIVE_GEOMETRY"
                        )
                        # Keep OCR tokens in a separate presentation-only
                        # field.  They may help a reviewer recognise the
                        # statement row, but must never become certified
                        # StatementFamilyMember amounts.
                        ocr_amount_candidates = list(
                            item.get("ocr_amount_candidates") or []
                        )
                    else:
                        statement_amount_raw = item.get("statement_amount_raw")
                        statement_amount_normalized = item.get(
                            "statement_amount_normalized"
                        )
                        statement_amounts = item.get("statement_amounts")
                        values = (
                            statement_amounts
                            if statement_amounts not in (None, "", [])
                            else statement_amount_normalized
                            if statement_amount_normalized not in (None, "", [])
                            else statement_amount_raw
                        )
                        amount_source_present = values not in (None, "", [])
                        if amount_source_present and native_value_geometry_present:
                            value_evidence_status = "ACCEPTED_NATIVE_GEOMETRY"
                        elif amount_source_present:
                            value_evidence_status = (
                                "REVIEW_REQUIRED_MISSING_NATIVE_GEOMETRY"
                            )
                        else:
                            value_evidence_status = "NO_VALUE_EVIDENCE"
                        ocr_amount_candidates = []
                    stage_b_eligibility = (
                        "ELIGIBLE"
                        if (
                            member_period_status == "ACTIVE_CURRENT_PERIOD"
                            and (
                                (native_value_geometry_present and not ocr_used)
                                # Spatial OCR can drive only the reviewable
                                # Statement→Note link; it never certifies a
                                # financial amount for Capture/Canonical.
                                or (
                                    ocr_used
                                    and bool(item.get("ocr_spatial_geometry_verified"))
                                    and bool(item.get("anchor_amount_observations"))
                                )
                            )
                        )
                        else "REVIEW_REQUIRED_ACTIONABLE"
                    )
                    children.append({"item":item.get("statement_item"),"member_table":item.get("member_table"),"presentation_member_id":item.get("presentation_member_id") or item.get("member_table"),"canonical_concept_id":item.get("canonical_concept_id") or item.get("member_table"),"canonical_display_name":item.get("member_display_name") or item.get("member_table"),"canonical_analysis_bucket":item.get("canonical_analysis_bucket"),"analysis_bridge_groups":list(item.get("analysis_bridge_groups") or []),"period_applicability":list(item.get("period_applicability") or []),"source_row_id":item.get("source_row_id"),"concept_aliases":list(item.get("concept_aliases") or []),"note_reference_normalized":item.get("note_reference_normalized") or item.get("note_reference") or "","note_reference_status":item.get("note_reference_status"),"candidate_note_pdf_page_index":target_page,"candidate_note_printed_page":item.get("candidate_note_printed_page"),"confidence":item.get("confidence"),"locator_method":item.get("locator_method"),"note_target_candidates":target_candidates,"source_discovery_id":item.get("discovery_id"),"statement_family_member_id":item.get("statement_family_member_id"),"member_origin":item.get("member_origin"),"raw_parent_row_id":item.get("raw_parent_row_id"),"raw_member_label":item.get("raw_member_label"),"presentation_regime":item.get("presentation_regime"),"comparability_status":item.get("comparability_status"),"family_total_status":item.get("family_total_status"),"member_period_status":member_period_status,"stage_b_eligibility":stage_b_eligibility,"ocr_used":ocr_used,"native_value_geometry_present":native_value_geometry_present,"value_evidence_status":value_evidence_status,"ocr_token_provenance":(item.get("evidence") or {}).get("ocr_token_provenance"),"ocr_amount_candidates":ocr_amount_candidates,"statement_amount_raw":statement_amount_raw,"statement_amount_normalized":statement_amount_normalized,"statement_amounts":statement_amounts,"values":values,"amount_source_present":amount_source_present,"anchor_amount_observations":list(item.get("anchor_amount_observations") or []),"anchor_period_observations":list(item.get("anchor_period_observations") or []),"ocr_spatial_geometry_verified":bool(item.get("ocr_spatial_geometry_verified"))})
            if not children: continue
            coverage=sum(1 for child in children if child.get("note_reference_normalized")) / len(children)
            confidence=round(sum(float(x.get("confidence") or 0) for x in items)/len(items),2)
            output.append({**first,"parent_text":display_name,"child_rows":children,"table_family":family_id,"structure_confidence":confidence,"structure_evidence":{"parser":"GENERIC_STRUCTURE_PARSER","strategy":strategy,"child_count":len(children),"note_reference_coverage":coverage},"failure_reason":None if children else "NO_ANCHOR_PATTERN"})
        return output

    def _direct(self,candidates,family_id,display_name,*,strategy="DIRECT_NOTE_TABLE_FAMILY"):
        if strategy == "DIRECT_PORTFOLIO_TABLES":
            return self._direct_portfolio(candidates, family_id, display_name)
        output=[]
        for candidate in candidates:
            page=candidate.get("candidate_note_pdf_page_index")
            if not page: continue
            # Registry member names are stable identities; the exact matched
            # heading is the execution query and must survive certification.
            query_title=candidate.get("matched_title") or candidate.get("member_display_name") or candidate.get("statement_item")
            heading=candidate.get("certified_heading") or query_title
            direct_main = strategy == "DIRECT_MAIN_STATEMENT_TABLE"
            child={"item":candidate.get("member_display_name") or candidate.get("statement_item"),"member_table":candidate.get("member_table"),"member_id":candidate.get("member_table"),"canonical_concept_id":candidate.get("member_table"),"canonical_display_name":candidate.get("member_display_name") or candidate.get("statement_item"),"note_reference_normalized":"","note_reference_status":"NOT_APPLICABLE","candidate_note_pdf_page_index":page,"confidence":candidate.get("confidence"),"direct_main_statement":direct_main,"direct_capture_title":query_title,"direct_end_page":candidate.get("direct_end_page") or page,"note_target_candidates":[{"pdf_page_index":page,"heading":heading,"capture_query_title":query_title,"locator_method":candidate.get("locator_method"),"score":candidate.get("confidence",0),"status":"DIRECT_MAIN_STATEMENT_CANDIDATE" if direct_main else "DIRECT_DISCLOSURE_CANDIDATE","evidence":candidate.get("evidence",{})}]}
            output.append({**candidate,"display_name":display_name,"parent_text":display_name,"child_rows":[child],"table_family":family_id,"structure_confidence":candidate.get("confidence"),"structure_evidence":{"parser":"GENERIC_STRUCTURE_PARSER","strategy":strategy,"row_signature":candidate.get("evidence",{}).get("row_signature_hits")},"failure_reason":None})
        return output

    def _direct_portfolio(self, candidates, family_id, display_name):
        """Group logical blocks by physical source-table identity."""
        groups = {}
        for candidate in candidates:
            key = (
                candidate.get("pdf_id"),
                candidate.get("candidate_note_pdf_page_index"),
            )
            groups.setdefault(key, []).append(candidate)
        output = []
        for items in groups.values():
            first = items[0]
            page = first.get("candidate_note_pdf_page_index")
            if not page:
                continue
            children = []
            for candidate in sorted(items, key=lambda row: str(row.get("logical_block_id") or "")):
                query_title = candidate.get("matched_title") or candidate.get("source_table_title")
                evidence = candidate.get("evidence") or {}
                children.append({
                    "item": candidate.get("member_display_name") or candidate.get("member_table"),
                    "member_table": candidate.get("member_table"),
                    "member_id": candidate.get("member_table"),
                    "canonical_concept_id": candidate.get("member_table"),
                    "canonical_display_name": candidate.get("member_display_name") or candidate.get("member_table"),
                    "note_reference_normalized": "",
                    "note_reference_status": "NOT_APPLICABLE",
                    "candidate_note_pdf_page_index": page,
                    "confidence": candidate.get("confidence"),
                    "direct_portfolio_table": True,
                    "portfolio_source_kind": "DIRECT_PHYSICAL_TABLE",
                    "direct_capture_title": query_title,
                    "direct_end_page": candidate.get("direct_end_page") or page,
                    "disclosure_topology": candidate.get("disclosure_topology"),
                    "physical_asset_id": candidate.get("physical_asset_id"),
                    "logical_block_id": candidate.get("logical_block_id"),
                    "classification_axis": candidate.get("classification_axis"),
                    "physical_bbox": dict(candidate.get("physical_bbox") or {}),
                    "applicable_members": list(candidate.get("applicable_members") or []),
                    "not_applicable_members": list(candidate.get("not_applicable_members") or []),
                    "reported_total_policy": candidate.get("reported_total_policy"),
                        "unit": candidate.get("unit") or evidence.get("unit") or "",
                        "period_headers": list(evidence.get("period_headers") or []),
                    "note_target_candidates": [{
                        "pdf_page_index": page,
                        "heading": candidate.get("certified_heading") or query_title,
                        "capture_query_title": query_title,
                        "locator_method": candidate.get("locator_method"),
                        "score": candidate.get("confidence", 0),
                        "status": "DIRECT_PORTFOLIO_TABLE_CANDIDATE",
                        "evidence": evidence,
                    }],
                })
            output.append({
                **first,
                "display_name": display_name,
                "parent_text": display_name,
                "child_rows": children,
                "table_family": family_id,
                "structure_confidence": min(float(row.get("confidence") or 0) for row in items),
                "structure_evidence": {
                    "parser": "GENERIC_STRUCTURE_PARSER",
                    "strategy": "DIRECT_PORTFOLIO_TABLES",
                    "disclosure_topology": first.get("disclosure_topology"),
                    "physical_asset_ids": sorted({
                        str(row.get("physical_asset_id") or "") for row in items
                    }),
                    "physical_asset_count": len({
                        str(row.get("physical_asset_id") or "") for row in items
                    }),
                    "logical_block_count": len(children),
                    "not_applicable_members": list(first.get("not_applicable_members") or []),
                    "portfolio_source_kinds": ["DIRECT_PHYSICAL_TABLE"],
                },
                "failure_reason": None,
            })
        return output
