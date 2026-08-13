"""API-ready orchestration for v6.5 statement-anchored discovery."""
from __future__ import annotations
from pathlib import Path
from typing import Any
from generic_discovery import discover, hierarchical_backoff, assemble_statement_occurrences
from statement_anchored_family import StatementOccurrence, arbitrate_anchors, build_capture_plan, cluster_evidence
from note_target_resolver import NoteReferenceResolver
from anchor_candidate_selection import rank_and_preselect


class DiscoveryService:
    def __init__(self, discovery_registry, cache_root: Path):
        self.registry = discovery_registry
        self.cache_root = Path(cache_root) / "statement_indexes"
        self.note_resolver = NoteReferenceResolver()

    def preview(self, pdf_path: Path, *, display_name: str, company: str = "", report_year: str = "",
                filing_type: str = "ANNUAL_REPORT",
                discovery_context: dict[str, Any] | None = None) -> list[dict[str, Any]]:
        rows = discover(pdf_path, self.cache_root, display_name=display_name, company=company,
                        report_year=report_year, filing_type=filing_type,
                        discovery_context=dict(discovery_context or {}))
        for row in rows:
            row["pdf_id"] = str(pdf_path)
            row.update(self.registry.save_machine(row))
        return rows

    def fast_path_preview(self, query: dict[str, Any]) -> list[dict[str, Any]]:
        return hierarchical_backoff(query, self.registry.fast_path(query))

    def adjudicate(self, discovery_id: str, **kwargs: Any) -> dict[str, Any]:
        return self.registry.adjudicate(discovery_id, **kwargs)

    def cluster(self, rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
        clusters = cluster_evidence(rows)
        return self.registry.save_clusters(clusters)

    def proposed_occurrences(self, rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Persist proposed same-page anchors before human arbitration."""
        return [self.build_occurrence(context=x, parent_text=x["parent_text"], child_rows=x["child_rows"],
                                      source_table_title=x["source_table_title"], scope=x.get("scope", "UNKNOWN"))
                for x in assemble_statement_occurrences(rows)]

    def build_occurrence(self, *, context: dict[str, Any], parent_text: str,
                         child_rows: list[dict[str, Any]], source_table_title: str,
                         scope: str = "UNKNOWN") -> dict[str, Any]:
        """Create a reviewable occurrence; extraction supplies child evidence."""
        occ = StatementOccurrence(
            occurrence_id=context.get("occurrence_id", "OCC_PENDING"),
            display_name=context["display_name"], statement_type=context.get("statement_type", "UNKNOWN"),
            source_table_title=source_table_title, scope=scope,
            statement_pdf_page_index=context.get("statement_pdf_page_index") or context.get("statement_page"),
            statement_printed_page=context.get("statement_printed_page"), parent_text=parent_text,
            child_rows=tuple(child_rows), evidence=context.get("evidence") or {},
        )
        payload = {**context, "display_name": occ.display_name, "statement_type": occ.statement_type,
                   "source_table_title": source_table_title, "scope": scope, "parent_text": parent_text,
                   "child_rows": child_rows, "statement_pdf_page_index": occ.statement_pdf_page_index,
                   "statement_printed_page": occ.statement_printed_page, "anchor_score": occ.score(),
                   "evidence": occ.evidence}
        return self.registry.save_occurrence(payload)

    def arbitrate(self, occurrences: list[dict[str, Any]], *, scope_preference: str | None = None) -> dict[str, Any]:
        models = [StatementOccurrence(
            occurrence_id=x["occurrence_id"], display_name=x["display_name"], statement_type=x.get("statement_type", "UNKNOWN"),
            source_table_title=x.get("source_table_title", ""), scope=x.get("scope", "UNKNOWN"),
            statement_pdf_page_index=x.get("statement_pdf_page_index"), statement_printed_page=x.get("statement_printed_page"),
            parent_text=x.get("parent_text", x["display_name"]), child_rows=tuple(x.get("child_rows") or []), evidence=x.get("evidence") or {}) for x in occurrences]
        return arbitrate_anchors(models, scope_preference=scope_preference)

    def rank_anchor_candidates(
        self, occurrences: list[dict[str,Any]], *,
        scope_preference: str | None=None, required_scopes: list[str] | None=None,
        policy: dict[str,Any] | None=None,
    ) -> dict[str,Any]:
        effective_scope=scope_preference or (
            required_scopes[0] if required_scopes and len(required_scopes)==1 else None
        )
        enriched=[]
        for raw in occurrences:
            row=dict(raw); evidence=dict(row.get("evidence") or {})
            pdf=Path(str(row.get("pdf_id") or ""))
            page=row.get("statement_pdf_page_index")
            if pdf.is_file() and page:
                try:
                    from statement_anchor_capture import capture_statement_anchor
                    captured=capture_statement_anchor(
                        pdf,str(row.get("display_name") or row.get("parent_text") or ""),
                        int(page),
                    )
                    evidence.update({
                        "formal_statement_region":True,
                        "period_headers":[str(x.year) for x in captured.columns if x.year],
                        "period_header_complete":bool(captured.columns),
                        "unit":captured.unit,
                        "amount_columns_present":any(x.cells for x in captured.rows[1:]),
                        "amount_columns_aligned":bool(captured.columns),
                        "bbox_verified":bool(captured.rows and captured.rows[0].bbox),
                        "statement_anchor_geometry_capture":True,
                    })
                    captured_by_name={
                        str(x.normalized_item):x for x in captured.rows[1:]
                    }
                    children=[]
                    for child in row.get("child_rows") or []:
                        item=dict(child)
                        match=captured_by_name.get(str(item.get("item") or ""))
                        if match:
                            item["values"]=[cell.parsed_number for cell in match.cells]
                            item["bbox"]=match.bbox
                        children.append(item)
                    row["child_rows"]=children
                    if row.get("scope") in {None,"","UNKNOWN"} and effective_scope:
                        row["scope"]=effective_scope
                        evidence["scope_inferred_from_research_definition"]=effective_scope
                    if not any(token in str(row.get("source_table_title") or "") for token in ("资产负债表","利润表","现金流量表")):
                        row["source_table_title"]="正式主报表（几何证据）"
                except Exception as exc:
                    evidence["statement_anchor_geometry_error"]=type(exc).__name__
            row["evidence"]=evidence
            enriched.append(row)
        result=rank_and_preselect(
            enriched,
            {"scope_preference":scope_preference,
             "required_scopes":required_scopes or ([scope_preference] if scope_preference else [])},
            policy,
        )
        # required_scopes is a hard UI/workflow boundary. UNKNOWN may be
        # promoted to the selected lane above when formal-statement geometry
        # succeeds, but unresolved UNKNOWN occurrences must not form a second
        # review lane beside the requested scope.
        allowed_scopes=set(required_scopes or [])
        if allowed_scopes:
            result["candidates"]=[
                row for row in result["candidates"]
                if str(row.get("scope") or "UNKNOWN") in allowed_scopes
            ]
            visible_ids={row["occurrence_id"] for row in result["candidates"]}
            result["preselected_ids"]=[
                occurrence_id for occurrence_id in result["preselected_ids"]
                if occurrence_id in visible_ids
            ]
            result["scope_decisions"]={
                key:value for key,value in result["scope_decisions"].items()
                if key.rsplit("::",1)[-1] in allowed_scopes
            }
        self.registry.save_anchor_scores(result["candidates"])
        self.registry.sync_anchor_review_queue(result)
        return result

    def resolve_note_targets(self, occurrence: dict[str, Any]) -> dict[str, Any]:
        """Generate candidates only.  No candidate authorises capture by itself."""
        result = dict(occurrence)
        children = []
        pdf = Path(str(occurrence.get("pdf_id") or ""))
        for child in occurrence.get("child_rows") or []:
            row = dict(child)
            # DIRECT_NOTE_TABLE_FAMILY already supplies page/title evidence;
            # do not erase it merely because no accounting note number exists.
            if row.get("note_target_candidates"):
                children.append(row)
                continue
            reference = row.get("note_reference_normalized") or row.get("note_reference")
            if reference and pdf.exists():
                row["note_target_candidates"] = self.note_resolver.candidates_from_pdf(
                    pdf, note_reference=reference, member_table=str(row.get("member_table") or row.get("item") or "")
                )
            else:
                row["note_target_candidates"] = []
            children.append(row)
        result["child_rows"] = children
        return result

    def certified_capture_plan(self, occurrence: dict[str, Any], *, certified_ids: list[str] | None = None,
                               certified_targets: dict[str, dict[str, Any]] | None = None) -> dict[str, Any]:
        persisted = self.registry.get_occurrence(occurrence["occurrence_id"])
        if not persisted or (
            persisted.get("status") != "ANCHOR_CERTIFIED"
            and not self.registry.is_anchor_certified(occurrence["occurrence_id"])
        ):
            raise PermissionError("UNSELECTED_ANCHOR_NEVER_MATERIALIZES")
        occurrence = {**persisted, **{k: v for k, v in occurrence.items() if k in {"pdf_id", "child_rows"}}}
        target_map = certified_targets or {}
        if target_map:
            attached = []
            for child in occurrence.get("child_rows") or []:
                child = dict(child)
                member = str(child.get("member_table") or child.get("item") or "")
                if member in target_map:
                    target = self.registry.certify_note_target(
                        occurrence["occurrence_id"], member,
                        str(child.get("note_reference_normalized") or child.get("note_reference") or ""), target_map[member]
                    )
                    child["certified_note_target"] = target
                attached.append(child)
            occurrence["child_rows"] = attached
        model = StatementOccurrence(
            occurrence_id=occurrence["occurrence_id"], display_name=occurrence["display_name"],
            statement_type=occurrence.get("statement_type", "UNKNOWN"), source_table_title=occurrence.get("source_table_title", ""),
            scope=occurrence.get("scope", "UNKNOWN"), statement_pdf_page_index=occurrence.get("statement_pdf_page_index"),
            statement_printed_page=occurrence.get("statement_printed_page"), parent_text=occurrence.get("parent_text", occurrence["display_name"]),
            child_rows=tuple(occurrence.get("child_rows") or []), evidence=occurrence.get("evidence") or {})
        plan = build_capture_plan(model, certified_ids=certified_ids or [], selected_anchor=True)
        plan["anchor_occurrence_id"] = occurrence["occurrence_id"]
        plan["pdf_id"] = occurrence.get("pdf_id")
        return self.registry.save_capture_plan(plan)

    def adjudicate_anchor(self, occurrence_id: str, **kwargs: Any) -> dict[str, Any]:
        return self.registry.adjudicate_anchor(occurrence_id, **kwargs)

    def bulk_adjudicate_anchors(self, occurrence_ids: list[str], **kwargs: Any) -> list[dict[str, Any]]:
        """Certify anchors per source document, even when initiated in one UI action.

        A bulk click is only a convenience action.  It intentionally emits one
        anchor adjudication for every occurrence so 2023/2024/2025 never share
        a mutable or ambiguous anchor decision.
        """
        return self.registry.bulk_adjudicate_anchors(occurrence_ids, **kwargs)

    def bulk_adjudicate(self, discovery_ids: list[str], **kwargs: Any) -> list[dict[str, Any]]:
        return self.registry.bulk_adjudicate(discovery_ids, **kwargs)
