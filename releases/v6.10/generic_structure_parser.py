"""Generic evidence-first table/statement structure parser for v6.7.

It consumes candidate evidence from any discovery strategy and returns
reviewable parent/child structures. It never invents note numbers or values.
"""
from __future__ import annotations
from typing import Any

class GenericStructureParser:
    def parse(self, candidates: list[dict[str, Any]], *, strategy: str, family_id: str, display_name: str) -> list[dict[str, Any]]:
        if strategy == "DIRECT_NOTE_TABLE_FAMILY":
            return self._direct(candidates, family_id, display_name)
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
                    statement_amount_raw=item.get("statement_amount_raw")
                    statement_amount_normalized=item.get("statement_amount_normalized")
                    statement_amounts=item.get("statement_amounts")
                    values=(
                        statement_amounts if statement_amounts not in (None, "", [])
                        else statement_amount_normalized if statement_amount_normalized not in (None, "", [])
                        else statement_amount_raw
                    )
                    children.append({"item":item.get("statement_item"),"member_table":item.get("member_table"),"note_reference_normalized":item.get("note_reference_normalized") or item.get("note_reference") or "","note_reference_status":item.get("note_reference_status"),"candidate_note_pdf_page_index":target_page,"candidate_note_printed_page":item.get("candidate_note_printed_page"),"confidence":item.get("confidence"),"locator_method":item.get("locator_method"),"note_target_candidates":target_candidates,"source_discovery_id":item.get("discovery_id"),"statement_family_member_id":item.get("statement_family_member_id"),"member_origin":item.get("member_origin"),"raw_parent_row_id":item.get("raw_parent_row_id"),"raw_member_label":item.get("raw_member_label"),"presentation_regime":item.get("presentation_regime"),"comparability_status":item.get("comparability_status"),"family_total_status":item.get("family_total_status"),"statement_amount_raw":statement_amount_raw,"statement_amount_normalized":statement_amount_normalized,"statement_amounts":statement_amounts,"values":values,"amount_source_present":values not in (None, "", [])})
            if not children: continue
            coverage=sum(1 for child in children if child.get("note_reference_normalized")) / len(children)
            confidence=round(sum(float(x.get("confidence") or 0) for x in items)/len(items),2)
            output.append({**first,"parent_text":display_name,"child_rows":children,"table_family":family_id,"structure_confidence":confidence,"structure_evidence":{"parser":"GENERIC_STRUCTURE_PARSER","strategy":strategy,"child_count":len(children),"note_reference_coverage":coverage},"failure_reason":None if children else "NO_ANCHOR_PATTERN"})
        return output

    def _direct(self,candidates,family_id,display_name):
        output=[]
        for candidate in candidates:
            page=candidate.get("candidate_note_pdf_page_index")
            if not page: continue
            # Registry member names are stable identities; the exact matched
            # heading is the execution query and must survive certification.
            query_title=candidate.get("matched_title") or candidate.get("member_display_name") or candidate.get("statement_item")
            heading=candidate.get("certified_heading") or query_title
            child={"item":candidate.get("member_display_name") or candidate.get("statement_item"),"member_table":candidate.get("member_display_name") or candidate.get("member_table"),"member_id":candidate.get("member_table"),"note_reference_normalized":"","note_reference_status":"NOT_APPLICABLE","candidate_note_pdf_page_index":page,"confidence":candidate.get("confidence"),"note_target_candidates":[{"pdf_page_index":page,"heading":heading,"capture_query_title":query_title,"locator_method":candidate.get("locator_method"),"score":candidate.get("confidence",0),"status":"DIRECT_DISCLOSURE_CANDIDATE","evidence":candidate.get("evidence",{})}]}
            output.append({**candidate,"parent_text":display_name,"child_rows":[child],"table_family":family_id,"structure_confidence":candidate.get("confidence"),"structure_evidence":{"parser":"GENERIC_STRUCTURE_PARSER","strategy":"DIRECT_NOTE_TABLE_FAMILY","row_signature":candidate.get("evidence",{}).get("row_signature_hits")},"failure_reason":None})
        return output
