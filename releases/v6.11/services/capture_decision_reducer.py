"""v6.11 centralized capture-state decision reducer.

Every quality_status, blocking, merge_eligible, and review_inbox decision
flows through this single service.  No UI, orchestrator, or repository code
may write these fields directly.  The reducer is deterministic: identical
inputs from any entry point produce identical outputs.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class DecisionResult:
    """Immutable output of ``CaptureDecisionReducer.reduce()``."""

    quality_status: str  # READY | REVIEW_REQUIRED
    merge_eligible: bool
    review_inbox_eligible: bool
    review_status: str = "PENDING"
    asset_status: str = "ACTIVE"
    certified: bool = False
    blocking: bool = True
    bundle_status: str = "REVIEW_REQUIRED"
    blocking_issues: list[str] = field(default_factory=list)
    non_blocking_warnings: list[str] = field(default_factory=list)
    bundle_status_effect: str = ""
    decision_evidence: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "quality_status": self.quality_status,
            "merge_eligible": self.merge_eligible,
            "review_inbox_eligible": self.review_inbox_eligible,
            "review_status": self.review_status,
            "asset_status": self.asset_status,
            "certified": self.certified,
            "blocking": self.blocking,
            "bundle_status": self.bundle_status,
            "blocking_issues": self.blocking_issues,
            "non_blocking_warnings": self.non_blocking_warnings,
            "bundle_status_effect": self.bundle_status_effect,
            "decision_evidence": self.decision_evidence,
        }


class CaptureDecisionReducer:
    """Single-point capture state decision engine.

    Consolidates:
      - ``capture_readiness()``   (merge_ready, quality_status, blockers)
      - ``derive_boundary_decision()`` (boundary status + evidence)
      - ``_derive_codes()``       (issue code generation)
      - ``materialize()``         (review task requirement)

    All inputs are read-only.  The reducer never writes to the database.
    """

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def reduce(
        self,
        *,
        machine_evidence: dict[str, Any],
        research_definition: dict[str, Any] | None = None,
        capture_version: dict[str, Any] | None = None,
        human_adjudications: dict[str, Any] | None = None,
        lifecycle_state: dict[str, Any] | None = None,
        rule_version: str = "v6.11",
    ) -> DecisionResult:
        """Produce the single authoritative state decision.

        Parameters
        ----------
        machine_evidence:
            Content of ``table_capture_result.json``.
        research_definition:
            Registry research definition (optional for legacy captures).
        capture_version:
            Current ``capture_versions`` row from the database.
        human_adjudications:
            Review task and issue decisions keyed by task_type.
        lifecycle_state:
            Asset lifecycle fields (asset_status, registration_status, etc.).
        rule_version:
            Current rule version for audit trail.
        """
        evidence = dict(machine_evidence or {})
        cv = dict(capture_version or {})
        adj = dict(human_adjudications or {})
        lifecycle = dict(lifecycle_state or {})

        # --- 1. boundary decision ---
        from capture_library import (
            MERGE_READY_STATUSES,
            derive_boundary_decision,
            derive_capture_scope_state,
        )
        scope_state = derive_capture_scope_state(
            evidence,
            scope_metadata=cv,
        )
        boundary = derive_boundary_decision(
            evidence,
            scope_metadata=cv,
        )
        boundary_ready = boundary.status in MERGE_READY_STATUSES

        # --- 2. header dimension status ---
        from capture_library import derive_header_status
        header_status = derive_header_status(evidence)
        header_ready = header_status in {"AUTO_CONFIRMED", "HUMAN_CONFIRMED"}

        # --- 3. row structure analysis ---
        rows = list(evidence.get("rows") or [])
        implicit_unresolved = self._count_unresolved_implicit(rows, evidence)
        mixed_cells = self._count_mixed_cells(evidence)

        # --- 4. topology and reconciliation ---
        stats = evidence.get("stats") or {}
        topology = stats.get("v69_header_topology") or {}
        reconciliation = stats.get("v69_reconciliation") or {}
        topology_ready = bool(topology.get("consistent", True))
        reconciliation_ready = str(
            reconciliation.get("status") or "NOT_TESTABLE"
        ).upper() != "FAIL"

        # --- 5. compute structural readiness ---
        structural_ready = (
            boundary_ready
            and header_ready
            and not mixed_cells
            and not implicit_unresolved
            and topology_ready
            and reconciliation_ready
            and not scope_state["continuation_unresolved_requires_block"]
            and not scope_state["policy_evidence_incomplete"]
        )

        # --- 6. derive issue codes ---
        blocking_codes, warning_codes = self._derive_issue_codes(
            evidence=evidence,
            boundary_status=boundary.status,
            header_status=header_status,
            rows=rows,
            cv=cv,
            lifecycle=lifecycle,
            implicit_unresolved=implicit_unresolved,
            mixed_cells=mixed_cells,
            topology_ready=topology_ready,
            reconciliation_ready=reconciliation_ready,
            scope_state=scope_state,
        )

        # Research-definition identity is part of the decision input rather
        # than UI metadata.  A supplied definition must agree with the pinned
        # Capture Version identity.
        definition = dict(research_definition or {})
        expected_definition_id = str(
            definition.get("definition_id")
            or definition.get("research_definition_id")
            or ""
        ).strip()
        expected_definition_version = str(
            definition.get("definition_version") or ""
        ).strip()
        if (
            expected_definition_id
            and str(cv.get("research_definition_id") or "").strip()
            != expected_definition_id
        ):
            blocking_codes.append("RESEARCH_DEFINITION_MISMATCH")
        if (
            expected_definition_version
            and str(cv.get("definition_version") or "").strip()
            != expected_definition_version
        ):
            blocking_codes.append("DEFINITION_VERSION_MISMATCH")

        # Explicit adjudications are immutable reducer inputs.  Task decisions
        # may resolve/override individual issue codes, but UI render never does.
        resolved_codes = {
            str(code)
            for key in ("resolved_issue_codes", "overridden_issue_codes")
            for code in (adj.get(key) or [])
        }
        if resolved_codes:
            blocking_codes = [
                code for code in blocking_codes if code not in resolved_codes
            ]
            warning_codes = [
                code for code in warning_codes if code not in resolved_codes
            ]

        # No state can be READY/merge-eligible while any blocker exists.
        blocking_codes = list(dict.fromkeys(blocking_codes))
        warning_codes = list(dict.fromkeys(warning_codes))
        blocking = bool(blocking_codes)
        # Every structural failure above has an explicit blocker code. Human
        # adjudication may resolve/override those codes; no parallel boolean
        # gate is allowed to disagree with the authoritative blocker set.
        merge_ready = not blocking

        # --- 7. lifecycle/review state ---
        registration_status = str(
            lifecycle.get("registration_status")
            or cv.get("registration_status")
            or ""
        )
        existing_asset_status = str(
            lifecycle.get("asset_status") or cv.get("asset_status") or "ACTIVE"
        )
        terminal_asset_statuses = {
            "SUPERSEDED", "INVALIDATED", "TRASHED", "ARCHIVED",
        }
        if existing_asset_status in terminal_asset_statuses:
            asset_status = existing_asset_status
        else:
            asset_status = "CERTIFIED_ACTIVE" if merge_ready else "ACTIVE"

        requested_review_status = str(
            adj.get("review_status") or cv.get("review_status") or ""
        )
        if merge_ready:
            review_status = (
                requested_review_status
                if requested_review_status
                in {"CONFIRMED_HUMAN", "CONFIRMED_OVERRIDE"}
                else "CONFIRMED_AUTO"
            )
        else:
            review_status = (
                requested_review_status
                if requested_review_status in {"REJECTED", "UNRESOLVED"}
                else "PENDING"
            )
        certified = bool(
            merge_ready
            and review_status
            in {"CONFIRMED_AUTO", "CONFIRMED_HUMAN", "CONFIRMED_OVERRIDE"}
            and asset_status == "CERTIFIED_ACTIVE"
        )

        # --- 8. review inbox eligibility ---
        inbox_eligible = (
            blocking
            and registration_status == "REGISTERED"
            and bool(cv.get("is_current", True))
            and asset_status not in terminal_asset_statuses
        )

        # --- 9. bundle status effect ---
        bundle_status = "READY" if merge_ready else "REVIEW_REQUIRED"
        bundle_effect = "NO_EFFECT"
        if merge_ready and str(cv.get("quality_status") or "") != "READY":
            bundle_effect = "TRANSITION_TO_READY"
        elif not merge_ready and str(cv.get("quality_status") or "") == "READY":
            bundle_effect = "TRANSITION_TO_REVIEW_REQUIRED"

        return DecisionResult(
            quality_status="READY" if merge_ready else "REVIEW_REQUIRED",
            merge_eligible=merge_ready,
            review_inbox_eligible=inbox_eligible,
            review_status=review_status,
            asset_status=asset_status,
            certified=certified,
            blocking=blocking,
            bundle_status=bundle_status,
            blocking_issues=blocking_codes,
            non_blocking_warnings=warning_codes,
            bundle_status_effect=bundle_effect,
            decision_evidence={
                "boundary_decision": {
                    "status": boundary.status,
                    "sub_decision": boundary.sub_decision,
                    "evidence_chain": boundary.evidence_chain,
                },
                "header_status": header_status,
                "implicit_unresolved": implicit_unresolved,
                "mixed_cells": mixed_cells,
                "topology_consistent": topology_ready,
                "structural_ready_before_adjudication": structural_ready,
                "reconciliation_status": reconciliation.get("status", "NOT_TESTABLE"),
                "capture_scope_policy": scope_state["capture_scope_policy"],
                "capture_scope_limited": scope_state["capture_scope_limited"],
                "scope_boundary_decision": scope_state["scope_boundary_decision"],
                "excluded_segment_count": scope_state["excluded_segment_count"],
                "registration_status": registration_status,
                "asset_status_before": existing_asset_status,
                "resolved_issue_codes": sorted(resolved_codes),
                "rule_version": rule_version,
            },
        )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _count_unresolved_implicit(
        rows: list[dict[str, Any]], evidence: dict[str, Any]
    ) -> int:
        """Count rows that are genuinely unresolved implicit candidates."""
        from capture_library import human_layout_noise_orders, is_orphan_numeric_noise
        human_noise = human_layout_noise_orders(evidence)
        count = 0
        for index, row in enumerate(rows):
            if not bool(row.get("cells")):
                continue
            try:
                row_order = int(row.get("row_order") or 0)
            except (TypeError, ValueError):
                row_order = 0
            if row_order in human_noise:
                continue
            role = str(row.get("row_role") or "")
            if role == "ANONYMOUS_NUMERIC_ROW":
                continue
            if role == "IMPLICIT_TOTAL":
                ds = str(row.get("derived_status") or "")
                if ds in ("DERIVED_EXCLUDED", "SUPPRESSED_BY_EXPLICIT_TOTAL"):
                    continue
                if ds == "REQUIRED_DERIVED_TOTAL_UNRESOLVED":
                    count += 1
                continue
            if role == "IMPLICIT_ROW_CANDIDATE" and not is_orphan_numeric_noise(rows, index):
                count += 1
            elif not role and row.get("raw_item") is None:
                count += 1
        return count

    @staticmethod
    def _count_mixed_cells(evidence: dict[str, Any]) -> int:
        stats = evidence.get("stats") or {}
        from_rows = sum(
            1
            for row in (evidence.get("rows") or [])
            for cell in (row.get("cells") or [])
            if str(cell.get("cell_role") or "") == "MIXED"
        )
        return max(int(stats.get("mixed_cell_count") or 0), from_rows)

    @staticmethod
    def _derive_issue_codes(
        *,
        evidence: dict[str, Any],
        boundary_status: str,
        header_status: str,
        rows: list[dict[str, Any]],
        cv: dict[str, Any],
        lifecycle: dict[str, Any],
        implicit_unresolved: int,
        mixed_cells: int,
        topology_ready: bool,
        reconciliation_ready: bool,
        scope_state: dict[str, Any] | None = None,
    ) -> tuple[list[str], list[str]]:
        """Derive issue codes from machine evidence and current state."""
        blocking: list[str] = []
        warnings: list[str] = []
        if scope_state is None:
            from capture_library import derive_capture_scope_state
            scope_state = derive_capture_scope_state(
                evidence,
                scope_metadata=cv,
            )

        # Identity checks
        if not str(cv.get("research_definition_id") or "").strip():
            blocking.append("RESEARCH_DEFINITION_MISSING")
        if not str(cv.get("definition_version") or "").strip():
            blocking.append("DEFINITION_VERSION_MISSING")
        if not str(cv.get("table_family_id") or "").strip():
            blocking.append("TABLE_FAMILY_MISSING")
        if str(cv.get("statement_scope") or "UNKNOWN").upper() in {"", "UNKNOWN", "NONE"}:
            blocking.append("STATEMENT_SCOPE_UNKNOWN")
        if not cv.get("is_current"):
            blocking.append("NON_CURRENT_CAPTURE")
        if not str(
            cv.get("pdf_id")
            or cv.get("pdf_name")
            or cv.get("source_pdf_path")
            or ""
        ).strip():
            blocking.append("SOURCE_IDENTITY_MISSING")
        registration_status = str(
            lifecycle.get("registration_status")
            or cv.get("registration_status")
            or ""
        )
        if registration_status != "REGISTERED":
            blocking.append("REGISTRATION_INCOMPLETE")
        lifecycle_status = str(
            lifecycle.get("asset_status")
            or cv.get("asset_status")
            or "ACTIVE"
        )
        if lifecycle_status in {
            "SUPERSEDED", "INVALIDATED", "TRASHED", "ARCHIVED",
        }:
            blocking.append("LIFECYCLE_NOT_ACTIVE")

        # Boundary
        from capture_library import MERGE_READY_STATUSES

        if boundary_status not in MERGE_READY_STATUSES:
            blocking.append("PDF_BOUNDARY_UNCERTAIN")
        elif boundary_status == "AUTO_ACCEPTED_WITH_NON_BLOCKING_WARNING":
            warnings.append("BOUNDARY_AUTO_ACCEPTED_WITH_WARNING")
        if scope_state["continuation_unresolved_requires_block"]:
            blocking.append("CONTINUATION_UNRESOLVED")
        if scope_state["policy_evidence_incomplete"]:
            blocking.append("CAPTURE_SCOPE_POLICY_EVIDENCE_INCOMPLETE")
        blocking.extend(
            scope_state.get("certified_scope_blocking_issue_codes") or []
        )
        if (
            scope_state["continuation_excluded_by_policy"]
            and scope_state["policy_truncation_confirmed"]
        ):
            warnings.append("CONTINUATION_EXCLUDED_BY_POLICY")

        # Header
        if header_status in {"", "REVIEW_REQUIRED", "AMBIGUOUS"}:
            blocking.append("HEADER_TOPOLOGY_AMBIGUOUS")
        header_arbitration = (evidence.get("stats") or {}).get(
            "header_arbitration"
        ) or {}
        selected_parser = str(header_arbitration.get("selected_parser") or "")
        selected_metrics = (
            header_arbitration.get("candidates") or {}
        ).get(selected_parser) or {}
        if int(selected_metrics.get("numeric_cluster_count") or 0) > int(
            selected_metrics.get("leaf_count") or 0
        ):
            blocking.append("HEADER_TOPOLOGY_AMBIGUOUS")

        # Row structure
        has_ambiguous = any(
            str(r.get("row_role") or r.get("row_type")) == "AMBIGUOUS"
            for r in rows
        )
        if has_ambiguous:
            blocking.append("ROW_STRUCTURE_AMBIGUOUS")
        if mixed_cells:
            blocking.append("NUMERIC_TOKEN_ORIGIN_AMBIGUOUS")
        if implicit_unresolved:
            blocking.append("IMPLICIT_ROW_UNRESOLVED")
        if not topology_ready:
            blocking.append("HEADER_TOPOLOGY_AMBIGUOUS")

        # IMPLICIT_TOTAL
        implicit_rows = [
            r for r in rows
            if str(r.get("row_role") or r.get("row_type")) == "IMPLICIT_TOTAL"
            and not r.get("human_confirmed")
        ]
        has_required = any(
            r.get("derived_status") == "REQUIRED_DERIVED_TOTAL_UNRESOLVED"
            for r in implicit_rows
        )
        has_non_blocking = any(
            r.get("derived_status") not in (
                "DERIVED_EXCLUDED", "SUPPRESSED_BY_EXPLICIT_TOTAL",
                "REQUIRED_DERIVED_TOTAL_UNRESOLVED",
            )
            and not r.get("human_confirmed")
            for r in implicit_rows
        )
        if has_required:
            blocking.append("IMPLICIT_TOTAL_UNCERTIFIED")
        elif has_non_blocking:
            warnings.append("IMPLICIT_TOTAL_UNCERTIFIED_NON_BLOCKING")

        # Unit
        unit = evidence.get("unit") or (evidence.get("document_context") or {}).get("currency_unit")
        if not unit:
            blocking.append("UNIT_UNCERTAIN")

        # Reconciliation preserves audit evidence.  A parent total and the
        # flat sum of preceding child rows need not reconcile, so MISMATCH and
        # legacy WARNING are review warnings rather than merge blockers.
        reconciliation = (evidence.get("stats") or {}).get("v69_reconciliation") or {}
        reconciliation_status = str(reconciliation.get("status") or "").upper()
        if reconciliation_status in {"WARNING", "MISMATCH"}:
            warnings.append("RECONCILIATION_WARNING")
        elif not reconciliation_ready or reconciliation_status == "FAIL":
            blocking.append("RECONCILIATION_MISMATCH")

        # Final-column validation is part of the same authoritative machine
        # evidence decision, not a later UI-only review pass.
        if "columns" in evidence:
            from final_data_review import review_final_data_columns
            for issue in review_final_data_columns(evidence).get("issues") or []:
                code = str(issue.get("reason_code") or "").strip()
                if code:
                    blocking.append(code)

        return blocking, warnings
