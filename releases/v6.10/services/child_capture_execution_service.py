"""Unified batch execution service for Stage B certified child capture.

Both the strict-child-mapping flow and the explicit-note-target compat flow
use this service so that batch tracking, progress monitoring, retry, and
review-queue construction are identical.  The compat flow becomes a thin
adapter that only differs in how it builds the CaptureRequest list.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any


class ChildCaptureExecutionService:
    """Submit, monitor, retry, and route certified-child capture batches."""

    def __init__(
        self,
        registry: Any,
        capture_service: Any,
        table_capture_runner: Any,
        research_batch_service: Any,
        guided_capture_service: Any | None = None,
        capture_version_service: Any | None = None,
        hierarchical_child_discovery_service: Any | None = None,
        capture_orchestrator: Any | None = None,
    ) -> None:
        self.registry = registry
        self.capture_service = capture_service
        self.runner = table_capture_runner
        self.research_batch = research_batch_service
        self.guided_capture = guided_capture_service
        self.capture_version = capture_version_service
        self.child_discovery = hierarchical_child_discovery_service
        self.orchestrator = capture_orchestrator

    # ------------------------------------------------------------------
    # Batch creation
    # ------------------------------------------------------------------

    def create_execution_batch(
        self,
        *,
        display_name: str,
        certified_links: list[dict[str, Any]] | None = None,
        source_pdf_map: dict[str, Path] | None = None,
        plans: list[dict[str, Any]] | None = None,
        research_definition: dict[str, Any] | None = None,
        scope: str = "",
    ) -> dict[str, Any]:
        """Create a research batch and submit all capture requests.

        Supports two input modes:
        1. ``certified_links`` — from the strict child-mapping flow (Flow 1).
           Each link is converted to a CaptureRequest via
           ``hierarchical_child_discovery_service.certified_capture_request()``.
        2. ``plans`` — from the compat explicit-note-target flow (Flow 2).
           Each plan is executed via ``GuidedCaptureService.execute()``.

        Returns a dict with ``research_batch_id``, ``batch_ids``, ``job_count``,
        ``blocked_count``, ``plans``.
        """
        # Create or reuse research batch
        research = self.research_batch.create(
            display_name=f"{display_name.strip()}_研究引导抓取",
            table_family=display_name.strip(),
            payload={
                "source_pdf_count": len(source_pdf_map or {}),
                "stage": "CERTIFIED_CHILD_CAPTURE",
            },
            research_definition_id=(
                research_definition.get("definition_id") if research_definition else None
            ),
            definition_version=(
                research_definition.get("definition_version") if research_definition else None
            ),
        )
        research_batch_id = research["research_batch_id"]

        batch_ids: list[str] = []
        total_jobs = 0
        total_blocked = 0

        if plans and self.guided_capture:
            # Flow 2 (compat): plans already built — submit via GuidedCaptureService
            for plan in plans:
                self.research_batch.attach(
                    research_batch_id, plan_id=plan["plan_id"], role="PLAN"
                )
            results: list[dict[str, Any]] = []
            for plan in plans:
                # Resolve pdf path for each plan
                pdf_path = self._resolve_plan_pdf(plan)
                if pdf_path:
                    result = self.guided_capture.execute(
                        plan,
                        pdf_path=pdf_path,
                        research_batch_id=research_batch_id,
                    )
                    results.append(result)
            for r in results:
                if r.get("batch_id"):
                    batch_ids.append(r["batch_id"])
                total_jobs += len(r.get("jobs", []))
                total_blocked += len(r.get("blocked_items", []))
        elif certified_links and self.child_discovery:
            # Flow 1 (strict): convert each link to a CaptureRequest and batch-submit
            grouped: dict[str, list[dict[str, Any]]] = {}
            for link in certified_links:
                pdf_path = str(link.get("pdf_path", ""))
                grouped.setdefault(pdf_path, []).append(link)

            all_requests = []
            for _pdf, links in grouped.items():
                for link in links:
                    try:
                        req = self.child_discovery.certified_capture_request(
                            link,
                            Path(link.get("pdf_path", "")),
                            research_batch_id=research_batch_id,
                        )
                        all_requests.append(req)
                    except Exception:
                        total_blocked += 1

            if all_requests:
                jobs = self.capture_service.submit_batch(
                    all_requests,
                    batch_id=None,
                    max_workers=3,
                    asynchronous=True,
                )
                if jobs:
                    capture_batch_id = jobs[0]["batch_id"]
                    batch_ids.append(capture_batch_id)
                    total_jobs += len(jobs)
                    # v6.10: link the capture batch to the research batch so
                    # captures are discoverable via research_batch_id.
                    self.research_batch.attach(
                        research_batch_id,
                        source_batch_id=capture_batch_id,
                        role="SOURCE",
                    )
        else:
            # Neither plans nor certified_links — this is not an error during
            # initialisation.  The caller may not have certified links yet.
            return {
                "research_batch_id": research_batch_id,
                "batch_ids": [],
                "job_count": 0,
                "blocked_count": 0,
            }

        return {
            "research_batch_id": research_batch_id,
            "batch_ids": batch_ids,
            "job_count": total_jobs,
            "blocked_count": total_blocked,
        }

    # ------------------------------------------------------------------
    # Progress monitoring
    # ------------------------------------------------------------------

    def monitor_batch(self, batch_id: str) -> dict[str, Any]:
        """Return batch progress summary from the table capture runner."""
        return self.runner.monitor(batch_id)

    def monitor_all(
        self, batch_ids: list[str]
    ) -> list[dict[str, Any]]:
        """Return progress for all batch IDs."""
        rows: list[dict[str, Any]] = []
        for bid in batch_ids:
            summary = self.monitor_batch(bid)
            rows.append({
                "批次": bid,
                "总作业": summary["total"],
                "已完成": summary["complete"],
                "运行中": summary["counts"].get("RUNNING", 0),
                "失败": summary["counts"].get("FAILED", 0),
                "进度": f"{summary['progress']:.0%}",
            })
        return rows

    def all_terminal(self, batch_ids: list[str]) -> bool:
        """True when all jobs in all batches have reached a terminal state."""
        if not batch_ids:
            return False
        for bid in batch_ids:
            summary = self.monitor_batch(bid)
            terminal = summary["complete"] + summary["counts"].get("FAILED", 0) + summary["counts"].get("SKIPPED", 0)
            if terminal < summary["total"]:
                return False
        return True

    # ------------------------------------------------------------------
    # Retry
    # ------------------------------------------------------------------

    def retry_failed(self, batch_id: str, max_workers: int = 3) -> list[dict[str, Any]]:
        """Re-submit failed jobs in a batch."""
        return self.runner.retry_failed(batch_id=batch_id, max_workers=max_workers)

    def failed_batch_ids(self, batch_ids: list[str]) -> list[str]:
        """Return batch IDs that have at least one FAILED job."""
        failed: list[str] = []
        for bid in batch_ids:
            summary = self.monitor_batch(bid)
            if summary["counts"].get("FAILED", 0) > 0:
                failed.append(bid)
        return failed

    # ------------------------------------------------------------------
    # Review queue construction
    # ------------------------------------------------------------------

    def build_review_queue(
        self, research_batch_id: str
    ) -> list[dict[str, Any]]:
        """Build a review-queue for captures that need human attention.

        Queries the research batch for REVIEW_REQUIRED captures and returns
        entries suitable for the logical asset workspace review queue.
        """
        if not self.capture_version:
            return []
        result_rows = self.research_batch.result_review(research_batch_id)
        review_entries: list[dict[str, Any]] = []
        for result in result_rows:
            if str(result.get("capture_quality") or "") != "REVIEW_REQUIRED":
                continue
            for capture_id in result.get("capture_ids") or []:
                detail = self.capture_version.detail(str(capture_id)) or {}
                if not detail.get("logical_asset_id"):
                    continue
                review_entries.append({
                    "capture_id": str(capture_id),
                    "logical_asset_id": str(detail["logical_asset_id"]),
                    "company_id": detail.get("company_id"),
                    "report_year": detail.get("report_year"),
                    "table_family_id": detail.get("table_family_id"),
                    "member_table_id": detail.get("member_table_id") or result.get("member_table"),
                    "capture_quality": result.get("capture_quality"),
                    "quality_blockers": "；".join(
                        map(str, result.get("quality_blockers") or [])
                    ),
                    "initial_tab": "审核",
                    "return_route": "整表批量工作台",
                })
        return review_entries

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _resolve_plan_pdf(plan: dict[str, Any]) -> Path | None:
        """Resolve a PDF path from a capture plan."""
        source = plan.get("source_pdf_path") or plan.get("source_pdf")
        if source:
            p = Path(source)
            if p.is_file():
                return p
        # Try alternative keys
        for key in ("pdf_path", "anchor_pdf_path", "source_pdf_id"):
            val = plan.get(key)
            if val:
                p = Path(str(val))
                if p.is_file():
                    return p
        return None
