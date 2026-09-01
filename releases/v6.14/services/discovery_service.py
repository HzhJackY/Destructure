"""API-ready orchestration for v6.5 statement-anchored discovery."""
from __future__ import annotations
import hashlib
import json
from pathlib import Path
from typing import Any
try:
    import pymupdf as fitz
except ImportError:  # pragma: no cover
    import fitz  # type: ignore
from generic_discovery import discover, hierarchical_backoff, assemble_statement_occurrences
from statement_anchored_family import StatementOccurrence, arbitrate_anchors, build_capture_plan, cluster_evidence
from note_target_resolver import NoteReferenceResolver
from anchor_candidate_selection import rank_and_preselect
from financial_investment_period_contract import (
    expected_member_union,
    financial_member_contract_snapshot,
)


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

    @staticmethod
    def _is_financial_investment(row: dict[str, Any]) -> bool:
        # Persistent v6.13 certification rows use the stable family key while
        # fresh v6.14 discovery rows use the Registry definition id.  They are
        # one financial-investment route; excluding the former skips Evidence
        # V2 and leaks a combined-scope source row into the UI filter.
        return str(row.get("table_family") or "").strip().upper() in {
            "FINANCIAL_INVESTMENT_V1", "FINANCIAL_INVESTMENT",
        }

    @staticmethod
    def _evidence_revision_key(
        row: dict[str, Any],
        evidence: dict[str, Any],
        *,
        revision_kind: str,
    ) -> str:
        # The evidence payload, not just page/cache identity, owns the
        # append-only revision.  A parser/contract change over the same cached
        # page must create a new immutable occurrence instead of silently
        # returning a stale earlier revision.
        revision_metadata = {
            "evidence_revision_key",
            "evidence_revision_kind",
            "evidence_revision_parent_occurrence_id",
            "evidence_root_occurrence_id",
            "recovery_revision_key",
            "recovery_parent_occurrence_id",
        }
        evidence_payload = {
            key: value for key, value in evidence.items()
            if key not in revision_metadata
        }
        identity = {
            "revision_kind": revision_kind,
            "parent_occurrence": row.get("occurrence_id"),
            "pdf": str(row.get("pdf_id") or ""),
            "page": row.get("statement_pdf_page_index"),
            "evidence": evidence_payload,
            "child_rows": list(row.get("child_rows") or []),
        }
        return hashlib.sha256(
            json.dumps(identity, ensure_ascii=False, sort_keys=True, default=str).encode("utf-8")
        ).hexdigest()[:24]

    def _materialize_evidence_revision(
        self,
        row: dict[str, Any],
        *,
        revision_kind: str,
    ) -> dict[str, Any]:
        """Persist the exact ranked V2 evidence as an immutable occurrence.

        Ranking enriches original discovery occurrences with Evidence V2.  If
        that enriched object remains transient, UI review can display one
        object while certification later reloads an older occurrence without
        its periods, geometry or member bindings.  Append a deterministic
        revision so ranking, adjudication and later Stage B all refer to the
        same persisted payload.
        """
        save = getattr(self.registry, "save_occurrence", None)
        if not callable(save):
            # Lightweight/unit-test registries that do not own persistence
            # still receive the enriched in-memory candidate unchanged.
            return row
        evidence = dict(row.get("evidence") or {})
        revision_key = self._evidence_revision_key(
            row,
            evidence,
            revision_kind=revision_kind,
        )
        parent_id = str(row.get("occurrence_id") or "")
        root_id = str(evidence.get("evidence_root_occurrence_id") or parent_id)
        prefix = "OCC_REC_" if revision_kind == "OCR_RECOVERY" else "OCC_EVD_"
        occurrence_id = prefix + hashlib.sha256(
            f"{parent_id}|{revision_kind}|{revision_key}".encode("utf-8")
        ).hexdigest()[:24]
        evidence.update({
            "evidence_revision_key": revision_key,
            "evidence_revision_kind": revision_kind,
            "evidence_revision_parent_occurrence_id": parent_id,
            "evidence_root_occurrence_id": root_id,
        })
        if revision_kind == "OCR_RECOVERY":
            evidence.update({
                "recovery_revision_key": revision_key,
                "recovery_parent_occurrence_id": parent_id,
            })
        payload = {**row, "occurrence_id": occurrence_id, "evidence": evidence, "status": "NEEDS_ANCHOR_REVIEW"}
        get_existing = getattr(self.registry, "get_occurrence", None)
        if callable(get_existing):
            existing = get_existing(occurrence_id)
            if existing:
                return existing
        return save(payload)

    def _materialize_recovery_revision(self, row: dict[str, Any]) -> dict[str, Any]:
        """Append one idempotent OCR recovery evidence revision."""
        return self._materialize_evidence_revision(
            row,
            revision_kind="OCR_RECOVERY",
        )

    def _enrich_financial_row(
        self,
        raw: dict[str, Any],
        *,
        scope_preference: str | None,
        ocr_page_payload: dict[str, Any] | None = None,
        recovery_stage: str = "NATIVE_DISCOVERY",
    ) -> dict[str, Any]:
        """Bind one candidate to V2 evidence without changing Capture semantics."""
        row = dict(raw)
        evidence = dict(row.get("evidence") or {})
        pdf = Path(str(row.get("pdf_id") or ""))
        page = row.get("statement_pdf_page_index")
        direct_portfolio = bool(row.get("direct_portfolio_table") or evidence.get("strategy") == "DIRECT_PORTFOLIO_TABLES")
        if not (pdf.is_file() and page and self._is_financial_investment(row) and not direct_portfolio):
            if direct_portfolio:
                evidence["statement_anchor_geometry_capture"] = False
                evidence["statement_anchor_geometry_not_applicable"] = True
            row["evidence"] = evidence
            return row
        try:
            from statement_anchor_evidence_v2 import build_statement_anchor_evidence_v2
            member_contract = financial_member_contract_snapshot(row)
            anchor_evidence = build_statement_anchor_evidence_v2(
                pdf, int(page), str(row.get("report_year") or ""),
                parent_aliases=(str(row.get("display_name") or ""), str(row.get("parent_text") or "")),
                member_contract=member_contract,
                ocr_words=list((ocr_page_payload or {}).get("ocr_words") or []),
                ocr_metadata=dict((ocr_page_payload or {}).get("metadata") or {}),
                recovery_stage=recovery_stage,
            ).payload()
            evidence.update(anchor_evidence)
            evidence.update({
                "formal_statement_region": bool(anchor_evidence.get("title")),
                "period_headers": [str(item.get("period_label") or item.get("period_year")) for item in anchor_evidence.get("period_columns") or []],
                "period_header_complete": bool(anchor_evidence.get("period_columns")),
                "amount_columns_present": any(item.get("amount_cells") for item in anchor_evidence.get("members") or []),
                "amount_columns_aligned": bool(anchor_evidence.get("period_columns")),
                "bbox_verified": bool(anchor_evidence.get("title_bbox")),
            })
            row["source_statement_scope"] = str(anchor_evidence.get("source_statement_scope") or "UNKNOWN")
            row["scope"] = scope_preference if row["source_statement_scope"] == "COMBINED_CONSOLIDATED_AND_PARENT" and scope_preference else row["source_statement_scope"]
            row["source_table_title"] = str(anchor_evidence.get("title") or row.get("source_table_title") or "")
            matches_by_member: dict[str, list[dict[str, Any]]] = {}
            for member_match in anchor_evidence.get("members") or []:
                matches_by_member.setdefault(
                    str(member_match.get("presentation_member_id") or member_match.get("member_table") or ""), []
                ).append(dict(member_match))

            def select_physical_occurrence(member_id: str) -> tuple[dict[str, Any] | None, int]:
                occurrences = list(matches_by_member.get(member_id) or [])
                active = [item for item in occurrences if item.get("member_period_status") == "ACTIVE_CURRENT_PERIOD"]
                historical = [item for item in occurrences if item.get("member_period_status") in {
                    "COMPARATIVE_ONLY_LEGACY_MEMBER", "ACTIVE_COMPARATIVE_PERIOD",
                }]
                selected = (
                    active[0] if len(active) == 1 else
                    historical[0] if not active and len(historical) == 1 else
                    occurrences[0] if len(occurrences) == 1 else
                    None
                )
                return selected, len(occurrences)
            spec_by_member = {
                str(item.get("member_table") or ""): item
                for item in member_contract.get("members") or []
            }
            children = []
            original_children = list(row.get("child_rows") or [])
            original_ids = {
                str(item.get("member_table") or item.get("item") or "")
                for item in original_children
            }
            for member in expected_member_union(member_contract):
                if member not in original_ids and member in matches_by_member:
                    spec = spec_by_member.get(member) or {}
                    original_children.append({
                        "member_table": member,
                        "item": spec.get("display_name") or member,
                        "canonical_concept_id": member,
                        "canonical_display_name": spec.get("display_name") or member,
                        "concept_aliases": list(spec.get("aliases") or []),
                        "presentation_regime": spec.get("presentation_regime"),
                        "member_origin": "V2_PERIOD_MATRIX_SUPPLEMENT",
                    })
            for child in original_children:
                item = dict(child)
                member_id = str(item.get("presentation_member_id") or item.get("member_table") or item.get("item") or "")
                match, occurrence_count = select_physical_occurrence(member_id)
                if match:
                    cells = list(match.get("amount_cells") or [])
                    status = str(match.get("member_period_status") or item.get("member_period_status") or "UNRESOLVED")
                    current_cells = [cell for cell in cells if cell.get("period_role") == "CURRENT"]
                    current_geometry = bool(
                        current_cells
                        and all(cell.get("bbox") for cell in current_cells)
                        and any(cell.get("period_value_status") in {"VALUE_PRESENT", "LEGAL_DASH"} for cell in current_cells)
                    )
                    item.update({
                        "source_row_id": match.get("source_row_id"), "bbox": match.get("label_bbox"),
                        "presentation_member_id": match.get("presentation_member_id") or match.get("member_table"),
                        "canonical_analysis_bucket": match.get("canonical_analysis_bucket"),
                        "comparability_status": match.get("comparability_status"),
                        "analysis_bridge_groups": list(match.get("analysis_bridge_groups") or []),
                        "period_applicability": list(match.get("period_applicability") or []),
                        "source_occurrence_count": occurrence_count,
                        "values": [cell.get("value") for cell in current_cells],
                        "period_values": cells,
                        "member_period_status": status,
                        "native_value_geometry_present": current_geometry and anchor_evidence.get("geometry_evidence_mode") == "NATIVE",
                        "ocr_spatial_geometry_verified": current_geometry and anchor_evidence.get("geometry_evidence_mode") in {
                            "OCR_SUPPLEMENTED", "HYBRID_NATIVE_IDENTITY_OCR_VALUES",
                        },
                        "identity_source": match.get("identity_source"),
                        "value_source": match.get("value_source"),
                        "alignment_evidence": match.get("alignment_evidence"),
                        "stage_b_eligibility": (
                            "ELIGIBLE" if status == "ACTIVE_CURRENT_PERIOD" and current_geometry
                            else "HISTORICAL_EVIDENCE_ONLY" if status in {"COMPARATIVE_ONLY_LEGACY_MEMBER", "ACTIVE_COMPARATIVE_PERIOD"}
                            else "REVIEW_REQUIRED_ACTIONABLE"
                        ),
                        "note_reference": match.get("note_reference") or item.get("note_reference"),
                        "note_reference_normalized": match.get("note_reference") or item.get("note_reference_normalized"),
                        "note_reference_status": match.get("note_reference_status"),
                    })
                elif occurrence_count > 1:
                    item.update({
                        "presentation_member_id": member_id,
                        "source_occurrence_count": occurrence_count,
                        "stage_b_eligibility": "REVIEW_REQUIRED_ACTIONABLE",
                        "source_identity_status": "PRESENTATION_MEMBER_OCCURRENCE_AMBIGUOUS",
                    })
                children.append(item)
            row["child_rows"] = children
        except Exception as exc:
            evidence["statement_anchor_evidence_v2_error"] = f"{type(exc).__name__}:{exc}"
        row["evidence"] = evidence
        return row

    @staticmethod
    def _recoverable_evidence_gap(candidate: dict[str, Any]) -> bool:
        gates = dict(candidate.get("hard_gate_results") or {})
        if candidate.get("hard_gates_passed") or not gates:
            return False
        recoverable = {
            "amount_columns_present", "period_recognized", "current_period_matches_report_year",
            "required_member_coverage", "required_current_member_status_valid",
            "value_geometry_verified", "unit_valid",
        }
        failed = {key for key, value in gates.items() if not value}
        return bool(failed) and failed <= recoverable

    @staticmethod
    def _qualified_physical_groups(candidates: list[dict[str, Any]]) -> set[tuple[str, str, int]]:
        return {
            (str(row.get("pdf_id") or ""), str(row.get("source_statement_scope") or row.get("scope") or "UNKNOWN"), int(row.get("statement_pdf_page_index") or 0))
            for row in candidates if row.get("hard_gates_passed")
        }

    def rank_anchor_candidates(
        self, occurrences: list[dict[str,Any]], *,
        scope_preference: str | None=None, required_scopes: list[str] | None=None,
        policy: dict[str,Any] | None=None,
    ) -> dict[str,Any]:
        context = {
            "scope_preference": scope_preference,
            "required_scopes": required_scopes or ([scope_preference] if scope_preference else []),
        }
        rank = lambda rows: rank_and_preselect(rows, context, policy)
        enriched = []
        for raw in occurrences:
            item = self._enrich_financial_row(
                raw,
                scope_preference=scope_preference,
            )
            item_evidence = dict(item.get("evidence") or {})
            if (
                self._is_financial_investment(item)
                and item_evidence.get("schema_version") == "STATEMENT_ANCHOR_EVIDENCE_V2"
                and not item_evidence.get("statement_anchor_evidence_v2_error")
            ):
                item = self._materialize_evidence_revision(
                    item,
                    revision_kind="NATIVE_V2",
                )
            enriched.append(item)
        provisional = rank(enriched)
        recovery_audit: dict[str, Any] = {"recovery_stage": "NATIVE_DISCOVERY", "attempts": []}

        # Stage 2: the physical candidate is already correct, but its native
        # evidence misses a recoverable column/period/member geometry fact.
        # Scope conflicts, wrong parents and non-statement pages are excluded
        # before OCR, so OCR can supplement geometry but never rewrite facts.
        recoverable_ids = {
            str(row.get("occurrence_id")) for row in provisional["candidates"]
            if self._recoverable_evidence_gap(row)
        }
        candidate_pages_by_pdf: dict[Path, set[int]] = {}
        for row in enriched:
            if str(row.get("occurrence_id")) not in recoverable_ids:
                continue
            pdf = Path(str(row.get("pdf_id") or "")); page = row.get("statement_pdf_page_index")
            if pdf.is_file() and page:
                candidate_pages_by_pdf.setdefault(pdf, set()).add(int(page))
        if candidate_pages_by_pdf:
            from conditional_statement_ocr import ocr_statement_page_group
            # Recoveries are per PDF, but ranking is over the complete selected
            # corpus.  The former loop reassigned ``enriched`` to the last
            # processed PDF's rows and silently dropped every other filing
            # whenever two or more candidates required evidence recovery.
            recovered_by_original_id: dict[str, dict[str, Any]] = {}
            for pdf, pages in candidate_pages_by_pdf.items():
                with fitz.open(str(pdf)) as document:
                    page_count = len(document)
                page_payloads, audit = ocr_statement_page_group(
                    pdf, cache_root=self.cache_root, page_numbers=pages,
                    native_page_count=page_count, recovery_stage="CANDIDATE_EVIDENCE_RECOVERY",
                )
                recovery_audit["attempts"].append(audit)
                for row in enriched:
                    if Path(str(row.get("pdf_id") or "")) != pdf:
                        continue
                    payload = page_payloads.get(int(row.get("statement_pdf_page_index") or 0))
                    if payload and str(row.get("occurrence_id")) in recoverable_ids:
                        item = self._enrich_financial_row(
                            row, scope_preference=scope_preference,
                            ocr_page_payload=payload,
                            recovery_stage="CANDIDATE_EVIDENCE_RECOVERY",
                        )
                        recovered_by_original_id[str(row.get("occurrence_id"))] = self._materialize_recovery_revision(item)
            enriched = [
                recovered_by_original_id.get(str(row.get("occurrence_id")), row)
                for row in enriched
            ]
            recovery_audit["recovery_stage"] = "CANDIDATE_EVIDENCE_RECOVERY"
            provisional = rank(enriched)

        # Stage 3: only financial-investment candidates enter the automatic
        # complete-document fallback.  It scans untried pages in 12-page Fast
        # Index batches and lets the *same* V2 hard gates decide whether to
        # stop; title scores alone never decide an Anchor.
        has_financial_profile = any(self._is_financial_investment(row) for row in occurrences)
        if has_financial_profile and not self._qualified_physical_groups(provisional["candidates"]):
            from conditional_statement_ocr import iter_full_document_ocr_batches
            full_result = None
            full_status = "OCR_FULL_SCAN_NO_QUALIFIED_CANDIDATE"
            by_pdf: dict[Path, list[dict[str, Any]]] = {}
            for row in enriched:
                pdf = Path(str(row.get("pdf_id") or ""))
                if pdf.is_file() and self._is_financial_investment(row):
                    by_pdf.setdefault(pdf, []).append(row)
            for pdf, source_rows in by_pdf.items():
                with fitz.open(str(pdf)) as document:
                    page_count = len(document)
                attempted = set(candidate_pages_by_pdf.get(pdf) or set())
                template = source_rows[0]
                template_contract = financial_member_contract_snapshot(template)
                for payloads, audit in iter_full_document_ocr_batches(
                    pdf, cache_root=self.cache_root, page_count=page_count,
                    attempted_pages=attempted, record_sink=None,
                ):
                    recovery_audit["attempts"].append(audit)
                    discovered: list[dict[str, Any]] = []
                    for page, payload in payloads.items():
                        seed = {
                            **template,
                            "occurrence_id": f"OCR_RECOVERY_{hashlib.sha256((str(pdf) + ':' + str(page)).encode()).hexdigest()[:20]}",
                            "statement_pdf_page_index": page,
                            "scope": "UNKNOWN",
                            "source_statement_scope": "UNKNOWN",
                            "source_table_title": "",
                            "child_rows": [
                                {"member_table": member, "item": member}
                                for member in expected_member_union(template_contract)
                            ],
                            "member_contract_snapshot": template_contract,
                            "evidence": {
                                "recovery_origin": "FULL_DOCUMENT_RECOVERY",
                                "member_contract_snapshot": template_contract,
                            },
                        }
                        item = self._enrich_financial_row(
                            seed, scope_preference=scope_preference,
                            ocr_page_payload=payload, recovery_stage="FULL_DOCUMENT_RECOVERY",
                        )
                        evidence = item.get("evidence") or {}
                        if evidence.get("formal_statement_region") and evidence.get("members"):
                            discovered.append(self._materialize_recovery_revision(item))
                    if discovered:
                        trial = rank([*enriched, *discovered])
                        groups = self._qualified_physical_groups(trial["candidates"])
                        if len(groups) == 1:
                            enriched = [*enriched, *discovered]
                            full_result = trial
                            full_status = "OCR_FULL_SCAN_UNIQUE_QUALIFIED_CANDIDATE"
                            break
                        if len(groups) >= 2:
                            enriched = [*enriched, *discovered]
                            full_result = trial
                            full_status = "ANCHOR_SELECTION_REQUIRED"
                            break
                    attempted.update(payloads)
                if full_result is not None:
                    break
            recovery_audit.update({"recovery_stage": "FULL_DOCUMENT_RECOVERY", "final_status": full_status})
            provisional = full_result or rank(enriched)

        result = provisional
        result["recovery_audit"] = recovery_audit
        # required_scopes is a hard UI/workflow boundary.  V2 preserves source
        # facts, so UNKNOWN and parent-company pages are never relabelled into
        # a requested consolidated review lane.
        allowed_scopes=set(required_scopes or [])
        if allowed_scopes:
            result["excluded_scope_candidates"]= [
                row for row in result["candidates"]
                if str(row.get("scope") or "UNKNOWN") not in allowed_scopes
            ]
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
            if row.get("member_period_status") in {
                "COMPARATIVE_ONLY_LEGACY_MEMBER",
                "ACTIVE_COMPARATIVE_PERIOD",
                "INACTIVE_CURRENT_PERIOD",
            }:
                row["note_target_candidates"] = []
                row["stage_b_requirement"] = "HISTORICAL_COVERAGE_GAP_NON_BLOCKING"
                children.append(row)
                continue
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
