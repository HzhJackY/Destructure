from __future__ import annotations

import json
from typing import Any, Iterable

from repositories.batch_repository import BatchRepository
from services.asset_service import AssetService


_TERMINAL_JOB_STATUSES = {
    "SUCCESS", "REVIEW_REQUIRED", "FAILED", "CANCELLED", "SKIPPED",
}
_CONFIRMED_REVIEW_STATUSES = {
    "CONFIRMED_AUTO", "CONFIRMED_HUMAN", "CONFIRMED_OVERRIDE",
}
_INACTIVE_CAPTURE_VERSION_STATUSES = {
    "ARCHIVED", "TRASHED", "SUPERSEDED", "INVALIDATED",
}
_RESOLVED_REVIEW_TASK_STATUSES = {
    "CONFIRMED", "NOT_REQUIRED", "RESOLVED", "REJECTED",
}


class BatchService:
    def __init__(
        self,
        repo: BatchRepository,
        assets: AssetService,
        merge_eligibility_service: Any | None = None,
    ) -> None:
        self.repo = repo
        self.assets = assets
        self.merge_eligibility_service = merge_eligibility_service

    def configure(self, *, merge_eligibility_service: Any) -> None:
        self.merge_eligibility_service = merge_eligibility_service

    def list_batches(
        self, *, include_fully_trashed: bool = False,
        only_with_trash: bool = False,
    ) -> list[dict[str, Any]]:
        return self.repo.list(
            include_fully_trashed=include_fully_trashed,
            only_with_trash=only_with_trash,
        )

    def capture_ids(
        self, batch_id: str, *, include_trash: bool = False,
    ) -> list[str]:
        return self.repo.capture_ids(batch_id, include_trash=include_trash)

    def trashed_capture_ids(self, batch_id: str) -> list[str]:
        return [
            row["capture_id"] for row in self.assets.capture_repo.list(
                batch_id=batch_id, only_trash=True, include_trash=True,
                limit=100000,
            )
        ]

    def selected_capture_ids(
        self, batch_ids: Iterable[str], *, include_trash: bool = False,
    ) -> list[str]:
        selected: list[str] = []
        seen: set[str] = set()
        for batch_id in batch_ids:
            for capture_id in self.capture_ids(
                str(batch_id), include_trash=include_trash,
            ):
                if capture_id not in seen:
                    seen.add(capture_id)
                    selected.append(capture_id)
        return selected

    def invalidate(
        self, batch_ids: Iterable[str], *, reason_code: str, note: str = "",
    ) -> dict[str, Any]:
        return self.assets.invalidate(
            self.selected_capture_ids(batch_ids),
            reason_code=reason_code,
            note=note,
        )

    def trash(self, batch_ids: Iterable[str]):
        return self.assets.trash(self.selected_capture_ids(batch_ids))

    def rerun(
        self, batch_ids: Iterable[str], *, parser_mode: str = "AUTO",
        batch_id: str | None = None,
    ):
        return self.assets.rerun(
            self.selected_capture_ids(batch_ids),
            parser_mode=parser_mode,
            batch_id=batch_id,
        )

    @staticmethod
    def _job_capture_id(job: dict[str, Any]) -> str:
        target_capture_id = str(job.get("target_asset_id") or "").strip()
        if target_capture_id:
            return target_capture_id
        try:
            result = json.loads(job.get("result_json") or "{}")
        except (TypeError, json.JSONDecodeError):
            result = {}
        return str(result.get("capture_id") or "").strip()

    def list_monitorable_batches(
        self, *, limit: int = 1000,
    ) -> list[dict[str, Any]]:
        """List batches with running/retryable work or a live current output.

        Historical batches whose only outputs are trashed or superseded are not
        actionable in the monitor and therefore stay out of the default picker.
        """
        sql = """
            WITH grouped AS (
                SELECT j.batch_id,
                       MAX(COALESCE(j.updated_at,j.created_at,'')) AS updated_at,
                       SUM(CASE WHEN j.status='QUEUED' THEN 1 ELSE 0 END) AS queued_count,
                       SUM(CASE WHEN j.status='RUNNING' THEN 1 ELSE 0 END) AS running_count,
                       SUM(CASE WHEN j.status='FAILED' THEN 1 ELSE 0 END) AS failed_count
                  FROM jobs j
                 WHERE COALESCE(j.batch_id,'')<>''
                 GROUP BY j.batch_id
            ), projected AS (
                SELECT grouped.*,
                       (
                           SELECT COUNT(DISTINCT captures.capture_id)
                             FROM jobs batch_job
                             JOIN captures ON captures.capture_id=COALESCE(
                                 NULLIF(batch_job.target_asset_id,''),
                                 json_extract(batch_job.result_json,'$.capture_id')
                             )
                             JOIN capture_versions ON capture_versions.capture_id=captures.capture_id
                             JOIN logical_assets ON logical_assets.logical_asset_id=capture_versions.logical_asset_id
                            WHERE batch_job.batch_id=grouped.batch_id
                              AND captures.is_trashed=0
                              AND captures.lifecycle_status='ACTIVE'
                              AND capture_versions.is_current=1
                              AND capture_versions.registration_status='REGISTERED'
                              AND capture_versions.asset_status NOT IN (
                                  'ARCHIVED','TRASHED','SUPERSEDED','INVALIDATED'
                              )
                              AND logical_assets.current_capture_id=captures.capture_id
                              AND logical_assets.direct_asset_status='ACTIVE'
                              AND logical_assets.archived_by_parent=0
                       ) AS active_current_capture_count
                  FROM grouped
            )
            SELECT * FROM projected
             WHERE queued_count>0 OR running_count>0 OR failed_count>0
                OR active_current_capture_count>0
             ORDER BY updated_at DESC
             LIMIT ?
        """
        with self.repo.registry.connect() as connection:
            rows = connection.execute(sql, (max(1, int(limit)),)).fetchall()
        return [dict(row) for row in rows]

    def execution_readiness(self, batch_id: str) -> dict[str, Any]:
        """Project one batch into an explicit, fail-closed UI readiness state.

        Job terminality is execution state only. Business readiness follows the
        job's persisted target Capture, its current-version lifecycle, bundle-root
        projection, and the existing authoritative MergeEligibilityService.
        """
        with self.repo.registry.connect() as connection:
            raw_jobs = connection.execute(
                "SELECT * FROM jobs WHERE batch_id=? ORDER BY created_at,job_id",
                (str(batch_id),),
            ).fetchall()
            jobs = [dict(row) for row in raw_jobs]

            status_counts: dict[str, int] = {}
            for job in jobs:
                status = str(job.get("status") or "UNKNOWN")
                status_counts[status] = status_counts.get(status, 0) + 1

            job_capture_ids = {
                str(job["job_id"]): self._job_capture_id(job) for job in jobs
            }
            capture_ids = list(dict.fromkeys(
                capture_id for capture_id in job_capture_ids.values()
                if capture_id
            ))

            capture_rows: dict[str, dict[str, Any]] = {}
            for start in range(0, len(capture_ids), 800):
                chunk = capture_ids[start:start + 800]
                placeholders = ",".join("?" for _ in chunk)
                rows = connection.execute(
                    f"""SELECT captures.*,
                               capture_versions.logical_asset_id,
                               capture_versions.is_current,
                               capture_versions.registration_status,
                               capture_versions.quality_status,
                               capture_versions.review_status,
                               capture_versions.asset_status,
                               logical_assets.current_capture_id,
                               logical_assets.direct_asset_status,
                               logical_assets.archived_by_parent,
                               logical_assets.company_id,
                               logical_assets.report_year,
                               logical_assets.table_family_id,
                               logical_assets.member_table_id
                          FROM captures
                          LEFT JOIN capture_versions
                            ON capture_versions.capture_id=captures.capture_id
                          LEFT JOIN logical_assets
                            ON logical_assets.logical_asset_id=capture_versions.logical_asset_id
                         WHERE captures.capture_id IN ({placeholders})""",
                    tuple(chunk),
                ).fetchall()
                capture_rows.update({str(row["capture_id"]): dict(row) for row in rows})

            active_current: dict[str, dict[str, Any]] = {}
            inactive_capture_ids: list[str] = []
            for capture_id in capture_ids:
                row = capture_rows.get(capture_id)
                is_active_current = bool(
                    row
                    and not bool(row.get("is_trashed"))
                    and str(row.get("lifecycle_status") or "") == "ACTIVE"
                    and bool(row.get("is_current"))
                    and str(row.get("registration_status") or "") == "REGISTERED"
                    and str(row.get("asset_status") or "")
                    not in _INACTIVE_CAPTURE_VERSION_STATUSES
                    and str(row.get("current_capture_id") or "") == capture_id
                    and str(row.get("direct_asset_status") or "") == "ACTIVE"
                    and not bool(row.get("archived_by_parent"))
                )
                if is_active_current:
                    active_current[capture_id] = row
                else:
                    inactive_capture_ids.append(capture_id)

            bundle_rows: dict[str, list[dict[str, Any]]] = {
                capture_id: [] for capture_id in active_current
            }
            active_ids = list(active_current)
            for start in range(0, len(active_ids), 800):
                chunk = active_ids[start:start + 800]
                placeholders = ",".join("?" for _ in chunk)
                rows = connection.execute(
                    f"""SELECT capture_bundle_children.capture_id,
                               capture_bundle_children.bundle_id,
                               capture_bundle_children.child_order,
                               capture_bundle_children.status AS child_status,
                               capture_bundles.status AS bundle_status
                          FROM capture_bundle_children
                          JOIN capture_bundles
                            ON capture_bundles.bundle_id=capture_bundle_children.bundle_id
                         WHERE capture_bundle_children.capture_id IN ({placeholders})
                           AND capture_bundle_children.status<>'SUPERSEDED'""",
                    tuple(chunk),
                ).fetchall()
                for row in rows:
                    bundle_rows[str(row["capture_id"])].append(dict(row))

            root_capture_ids: list[str] = []
            invalid_bundle_capture_ids: list[str] = []
            bundle_by_capture: dict[str, str] = {}
            for capture_id in active_current:
                memberships = bundle_rows.get(capture_id) or []
                if not memberships:
                    root_capture_ids.append(capture_id)
                    continue
                if len(memberships) != 1:
                    invalid_bundle_capture_ids.append(capture_id)
                    continue
                membership = memberships[0]
                bundle_by_capture[capture_id] = str(membership["bundle_id"])
                if (
                    int(membership.get("child_order") or 0) != 0
                    or str(membership.get("child_status") or "") != "CAPTURED"
                    or str(membership.get("bundle_status") or "") != "READY"
                ):
                    invalid_bundle_capture_ids.append(capture_id)
                    continue
                root_capture_ids.append(capture_id)

            review_required_capture_ids = [
                capture_id for capture_id, row in active_current.items()
                if (
                    str(row.get("quality_status") or "") != "READY"
                    or str(row.get("review_status") or "")
                    not in _CONFIRMED_REVIEW_STATUSES
                )
            ]

            review_by_capture: dict[str, dict[str, Any]] = {}
            if active_ids:
                placeholders = ",".join("?" for _ in active_ids)
                rows = connection.execute(
                    f"""SELECT * FROM review_queue
                         WHERE capture_id IN ({placeholders}) AND status='PENDING'
                         ORDER BY created_at""",
                    tuple(active_ids),
                ).fetchall()
                for row in rows:
                    review_by_capture.setdefault(str(row["capture_id"]), dict(row))

                task_rows = connection.execute(
                    f"""SELECT capture_version_id,blocking,status,task_type,
                               reason_codes_json
                          FROM review_tasks
                         WHERE capture_version_id IN ({placeholders})""",
                    tuple(active_ids),
                ).fetchall()
            else:
                task_rows = []

        active_blocking_tasks = [
            dict(row) for row in task_rows
            if bool(row["blocking"])
            and str(row["status"] or "") not in _RESOLVED_REVIEW_TASK_STATUSES
        ]
        non_blocking_warning_tasks = [
            dict(row) for row in task_rows
            if not bool(row["blocking"])
            and str(row["status"] or "") == "PENDING"
        ]

        review_queue = []
        for capture_id in review_required_capture_ids:
            capture = active_current[capture_id]
            queue_row = review_by_capture.get(capture_id, {})
            review_queue.append({
                "review_item_id": str(queue_row.get("review_item_id") or ""),
                "capture_id": capture_id,
                "logical_asset_id": str(capture.get("logical_asset_id") or ""),
                "company_id": capture.get("company_id") or capture.get("company"),
                "report_year": capture.get("report_year") or capture.get("document_year"),
                "table_family_id": capture.get("table_family_id"),
                "member_table_id": capture.get("member_table_id") or capture.get("table_query"),
                "primary_review_reason": str(
                    queue_row.get("primary_review_reason")
                    or "CAPTURE_NOT_MERGE_ELIGIBLE"
                ),
                "initial_tab": "审核",
                "return_route": "整表批量工作台",
            })

        eligible_capture_ids: set[str] = set()
        eligibility_available = self.merge_eligibility_service is not None
        if eligibility_available and root_capture_ids:
            eligible_capture_ids = {
                str(row.get("capture_id") or "")
                for row in self.merge_eligibility_service.eligible_assets()
                if row.get("capture_id")
            }
        ineligible_root_capture_ids = sorted(
            set(root_capture_ids) - eligible_capture_ids
        )

        total = len(jobs)
        terminal_count = sum(
            status_counts.get(status, 0) for status in _TERMINAL_JOB_STATUSES
        )
        missing_output_job_ids = [
            job_id for job_id, capture_id in job_capture_ids.items()
            if not capture_id or capture_id not in capture_rows
        ]
        duplicate_output_capture_ids = sorted({
            capture_id for capture_id in capture_ids
            if list(job_capture_ids.values()).count(capture_id) > 1
        })

        gate_reasons: list[str] = []
        if not total:
            gate_reasons.append("NO_JOBS")
        if terminal_count != total:
            gate_reasons.append("JOBS_NOT_TERMINAL")
        for status in ("FAILED", "CANCELLED", "SKIPPED"):
            if status_counts.get(status, 0):
                gate_reasons.append(f"{status}_JOBS")
        if missing_output_job_ids:
            gate_reasons.append("MISSING_CAPTURE_OUTPUT")
        if duplicate_output_capture_ids:
            gate_reasons.append("DUPLICATE_JOB_CAPTURE_OUTPUT")
        if inactive_capture_ids:
            gate_reasons.append("INACTIVE_OR_HISTORICAL_CAPTURE_OUTPUT")
        if not active_current:
            gate_reasons.append("NO_ACTIVE_CURRENT_CAPTURE")
        if invalid_bundle_capture_ids:
            gate_reasons.append("BUNDLE_ROOT_NOT_READY")
        if review_required_capture_ids or active_blocking_tasks:
            gate_reasons.append("CAPTURE_REVIEW_REQUIRED")
        if root_capture_ids and not eligibility_available:
            gate_reasons.append("MERGE_ELIGIBILITY_SERVICE_UNAVAILABLE")
        if ineligible_root_capture_ids:
            gate_reasons.append("CAPTURE_NOT_MERGE_ELIGIBLE")

        gate_reasons = list(dict.fromkeys(gate_reasons))
        return {
            "batch_id": str(batch_id),
            "total_jobs": total,
            "terminal_jobs": terminal_count,
            "business_ready_jobs": (
                total if not gate_reasons else 0
            ),
            "status_counts": status_counts,
            "is_running": bool(
                status_counts.get("QUEUED") or status_counts.get("RUNNING")
            ),
            "all_terminal": bool(total and terminal_count == total),
            "job_capture_ids": job_capture_ids,
            "active_current_capture_ids": sorted(active_current),
            "active_current_capture_count": len(active_current),
            "root_capture_ids": sorted(root_capture_ids),
            "eligible_root_capture_ids": sorted(
                set(root_capture_ids) & eligible_capture_ids
            ),
            "ineligible_root_capture_ids": ineligible_root_capture_ids,
            "inactive_capture_ids": sorted(inactive_capture_ids),
            "invalid_bundle_capture_ids": sorted(invalid_bundle_capture_ids),
            "bundle_by_capture": bundle_by_capture,
            "missing_output_job_ids": sorted(missing_output_job_ids),
            "duplicate_output_capture_ids": duplicate_output_capture_ids,
            "review_required_capture_ids": sorted(review_required_capture_ids),
            "review_required_capture_count": len(review_required_capture_ids),
            "review_queue": review_queue,
            "active_blocking_task_count": len(active_blocking_tasks),
            "non_blocking_warning_count": len(non_blocking_warning_tasks),
            "gate_reasons": gate_reasons,
            "can_enter_merge": bool(not gate_reasons),
        }
