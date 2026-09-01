"""API-ready orchestration for v6.5 statement-anchored discovery."""
from __future__ import annotations
from pathlib import Path
from typing import Any
from generic_discovery import discover, hierarchical_backoff, assemble_statement_occurrences
from statement_anchored_family import StatementOccurrence, arbitrate_anchors, build_capture_plan, cluster_evidence
from note_target_resolver import NoteReferenceResolver


class DiscoveryService:
    def __init__(self, discovery_registry, cache_root: Path):
        self.registry = discovery_registry
        self.cache_root = Path(cache_root) / "statement_indexes"
        self.note_resolver = NoteReferenceResolver()

    def preview(self, pdf_path: Path, *, display_name: str, company: str = "", report_year: str = "",
                filing_type: str = "ANNUAL_REPORT", preset_name: str | None = None) -> list[dict[str, Any]]:
        rows = discover(pdf_path, self.cache_root, display_name=display_name, company=company,
                        report_year=report_year, filing_type=filing_type, preset_name=preset_name)
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

    def resolve_note_targets(self, occurrence: dict[str, Any]) -> dict[str, Any]:
        """Generate candidates only.  No candidate authorises capture by itself."""
        result = dict(occurrence)
        children = []
        pdf = Path(str(occurrence.get("pdf_id") or ""))
        for child in occurrence.get("child_rows") or []:
            row = dict(child)
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
        if not persisted or persisted.get("status") != "ANCHOR_CERTIFIED":
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
