"""Application services for v6.8 logical assets, review, archive and merge gates."""
from __future__ import annotations

from typing import Any, Iterable
from review_reasons import normalize_review_reason


class LogicalAssetService:
    def __init__(self, repository, producer_version: str):
        self.repo = repository
        self.producer_version = producer_version

    def register_capture(
        self, *, capture_id: str, metadata: dict[str, Any], processing_status: str,
        registration_status: str, quality_status: str, review_status: str,
        certified: bool,
    ) -> dict[str, Any]:
        asset = self.repo.get_or_create_logical_asset(metadata)
        version = self.repo.register_capture_version(
            logical_asset_id=asset["logical_asset_id"], capture_id=capture_id,
            producer_version=self.producer_version, processing_status=processing_status,
            registration_status=registration_status, quality_status=quality_status,
            review_status=review_status, certified=certified,
        )
        return {"logical_asset": asset, "capture_version": version}

    def bootstrap_existing(self) -> dict[str, int]:
        return self.repo.bootstrap_existing_captures(self.producer_version)


class AssetLifecycleService:
    def __init__(self, repository, producer_version: str):
        self.repo = repository
        self.producer_version = producer_version

    def transition(
        self, *, logical_asset_id: str | None, capture_id: str | None,
        previous_status: str | None, new_status: str, actor: str = "SYSTEM",
        reason: str = "", evidence: dict[str, Any] | None = None,
        source_ui_action: str = "",
    ) -> str:
        return self.repo.transition(
            logical_asset_id=logical_asset_id, capture_id=capture_id,
            previous_status=previous_status, new_status=new_status, actor=actor,
            reason=reason, evidence=evidence, source_ui_action=source_ui_action,
            producer_version=self.producer_version,
        )


class ReviewInboxService:
    PRESET_VIEWS = {
        "待我处理": {"status": "PENDING"},
        "高严重度": {"status": "PENDING", "severity": "HIGH"},
        "边界待审核": {"status": "PENDING", "primary_review_reason": "BOUNDARY_LOW_CONFIDENCE"},
        "表头待审核": {"status": "PENDING", "primary_review_reason": "HEADER_AMBIGUOUS"},
        "单位待审核": {"status": "PENDING", "primary_review_reason": "UNIT_UNCERTAIN"},
        "结构待审核": {"status": "PENDING", "primary_review_reason": "ROW_STRUCTURE_AMBIGUOUS"},
        "合表前阻塞": {"status": "PENDING", "quality_status": "REVIEW_REQUIRED"},
        "最近七天": {"status": "PENDING", "recent_days": 7},
        "中国平安待审核": {"status": "PENDING", "company_id": "中国平安"},
    }
    def __init__(self, repository):
        self.repo = repository
        self.review_service = None

    def configure(self, review_service) -> None:
        self.review_service = review_service

    def route(
        self, *, logical_asset_id: str, capture_id: str,
        reasons: Iterable[str], evidence: dict[str, Any] | None = None,
    ) -> str:
        ordered = [normalize_review_reason(reason) for reason in reasons if reason]
        primary = ordered[0] if ordered else "STRUCTURE_REVIEW_REQUIRED"
        severity = "HIGH" if any("MISSING" in x or "CONFLICT" in x for x in ordered) else "MEDIUM"
        return self.repo.enqueue_review(
            logical_asset_id=logical_asset_id, capture_id=capture_id,
            primary_reason=primary, secondary_reasons=ordered[1:],
            severity=severity, evidence=evidence,
        )

    def list(self, **filters: Any) -> list[dict[str, Any]]:
        return self.repo.list_review(**filters)

    def resolve(self, capture_id: str, status: str = "CONFIRMED") -> None:
        if self.review_service is None:
            raise RuntimeError("REVIEW_SERVICE_NOT_CONFIGURED")
        return self.review_service.adjudicate_capture(capture_id=capture_id, action=status)

    def validate_bulk_action(self, capture_ids: Iterable[str], action: str) -> dict[str, Any]:
        requested = {str(value) for value in capture_ids}
        rows = [row for row in self.repo.list_review(status="PENDING", page_size=1000)
                if str(row["capture_id"]) in requested]
        if len(rows) != len(requested):
            return {"allowed": False, "reason": "SELECTION_NOT_ALL_PENDING", "rows": rows}
        reasons = {str(row["primary_review_reason"]) for row in rows}
        hard_conflict = any(
            "CONFLICT" in str(row["primary_review_reason"])
            or "MISSING" in str(row["primary_review_reason"])
            for row in rows
        )
        evidence_complete = all(bool(row.get("evidence_summary_json")) for row in rows)
        safe_confirm = len(reasons) == 1 and evidence_complete and not hard_conflict
        allowed = action.upper() != "CONFIRMED" or safe_confirm
        return {
            "allowed": allowed,
            "reason": "" if allowed else "BULK_CONFIRM_REQUIRES_HOMOGENEOUS_COMPLETE_NON_CONFLICT_EVIDENCE",
            "rows": rows,
            "primary_reasons": sorted(reasons),
        }

    def bulk_resolve(self, capture_ids: Iterable[str], status: str) -> int:
        ids = list(dict.fromkeys(map(str, capture_ids)))
        decision = self.validate_bulk_action(ids, status)
        if not decision["allowed"]:
            raise ValueError(str(decision["reason"]))
        for capture_id in ids:
            self.resolve(capture_id, status)
        return len(ids)

    def save_view(self, display_name: str, filters: dict[str, Any], sort: dict[str, Any] | None = None):
        return self.repo.save_view(kind="REVIEW", display_name=display_name, filters=filters, sort=sort)

    def list_views(self):
        return self.repo.list_views("REVIEW")

    def delete_view(self, view_id: str):
        self.repo.delete_view("REVIEW", view_id)

    def rename_view(self, view_id: str, display_name: str):
        current = next((row for row in self.list_views() if row["view_id"] == view_id), None)
        if not current:
            raise KeyError(view_id)
        return self.repo.save_view(
            kind="REVIEW", view_id=view_id, display_name=display_name,
            filters=current.get("filters") or {}, sort=current.get("sort") or {},
        )


class AssetQueryService:
    def __init__(self, repository):
        self.repo = repository

    def search(
        self, *, filters: dict[str, Any] | None = None, include_archived: bool = False,
        pagination: dict[str, Any] | None = None, sort: dict[str, Any] | None = None,
        search: str = "",
    ):
        return self.repo.search_assets(
            filters=filters, include_archived=include_archived,
            pagination=pagination, sort=sort, search=search,
        )

    def facets(self, rows: list[dict[str, Any]] | None = None) -> dict[str, list[str]]:
        rows = rows if rows is not None else self.search()
        fields = ("company_id", "report_year", "statement_scope", "table_family_id",
                  "member_table_id", "quality_status", "review_status", "asset_status")
        return {field: sorted({str(row.get(field) or "") for row in rows if row.get(field)}) for field in fields}

    def status_counts(self, filters: dict[str, Any] | None = None) -> dict[str, int]:
        counts: dict[str, int] = {}
        for row in self.search(filters=filters, include_archived=True, pagination={"page_size": 2000}):
            status = str(row.get("asset_status") or "UNKNOWN")
            counts[status] = counts.get(status, 0) + 1
        return counts

    def merge_eligible(self, filters: dict[str, Any] | None = None):
        return self.repo.current_merge_eligible(filters)

    search_assets = search

    def get_logical_asset(self, asset_id: str):
        return self.repo.get_logical_asset(asset_id)

    def get_current_capture(self, logical_asset_id: str):
        versions = self.repo.capture_versions(logical_asset_id)
        return next((row for row in versions if row["is_current"]), None)

    def get_capture_versions(self, logical_asset_id: str):
        return self.repo.capture_versions(logical_asset_id)

    def get_asset_lineage(self, asset_id: str):
        return self.repo.lineage(asset_id)

    def list_review_queue(self, filters: dict[str, Any] | None = None):
        return self.repo.list_review(**dict(filters or {}))

    list_merge_eligible_assets = merge_eligible

    def list_archived_assets(self, filters: dict[str, Any] | None = None):
        return [row for row in self.search(filters=filters, include_archived=True)
                if row["direct_asset_status"] == "ARCHIVED" or row["archived_by_parent"]]

    def list_superseded_assets(self, filters: dict[str, Any] | None = None):
        return [row for row in self.search(filters=filters, include_archived=True)
                if row["asset_status"] == "SUPERSEDED"]

    def list_invalidated_assets(self, filters: dict[str, Any] | None = None):
        return [row for row in self.search(filters=filters, include_archived=True)
                if row["asset_status"] == "INVALIDATED"]

    def list_trashed_assets(self, filters: dict[str, Any] | None = None):
        return [row for row in self.search(filters=filters, include_archived=True)
                if row["asset_status"] == "TRASHED"]

    get_status_counts = status_counts

    def save_view(self, display_name: str, filters: dict[str, Any], sort: dict[str, Any] | None = None):
        return self.repo.save_view(kind="ASSET", display_name=display_name, filters=filters, sort=sort)

    def list_views(self):
        return self.repo.list_views("ASSET")

    def delete_view(self, view_id: str):
        self.repo.delete_view("ASSET", view_id)

    def rename_view(self, view_id: str, display_name: str):
        current = next((row for row in self.list_views() if row["view_id"] == view_id), None)
        if not current:
            raise KeyError(view_id)
        return self.repo.save_view(
            kind="ASSET", view_id=view_id, display_name=display_name,
            filters=current.get("filters") or {}, sort=current.get("sort") or {},
        )


class ArchiveService:
    def __init__(self, repository):
        self.repo = repository

    def archive(self, logical_asset_ids: Iterable[str], *, actor: str = "USER", reason: str = ""):
        return self.repo.archive(logical_asset_ids, actor=actor, reason=reason, restore=False)

    def restore(self, logical_asset_ids: Iterable[str], *, actor: str = "USER", reason: str = ""):
        return self.repo.archive(logical_asset_ids, actor=actor, reason=reason, restore=True)

    def archive_versions(self, capture_ids: Iterable[str], *, actor: str = "USER", reason: str = ""):
        return self.repo.set_capture_lifecycle(
            capture_ids, status="ARCHIVED", actor=actor, reason=reason
        )

    def restore_versions(self, capture_ids: Iterable[str], *, actor: str = "USER", reason: str = ""):
        return self.repo.set_capture_lifecycle(
            capture_ids, status="ACTIVE", actor=actor, reason=reason, restore=True
        )

    def archive_parent(self, target_type: str, target_id: str, *, actor: str = "USER", reason: str = ""):
        return self.repo.archive_parent(target_type=target_type, target_id=target_id, actor=actor, reason=reason)

    def restore_parent(self, target_type: str, target_id: str, *, actor: str = "USER", reason: str = ""):
        return self.repo.archive_parent(target_type=target_type, target_id=target_id, actor=actor, reason=reason, restore=True)


class MergeEligibilityService:
    def __init__(self, query_service: AssetQueryService):
        self.query = query_service

    def eligible_assets(self, filters: dict[str, Any] | None = None):
        return self.query.merge_eligible(filters)

    def assert_capture_ids(self, capture_ids: Iterable[str]) -> None:
        requested = {str(x) for x in capture_ids}
        eligible = {str(row["capture_id"]) for row in self.eligible_assets()}
        blocked = sorted(requested - eligible)
        if blocked:
            raise ValueError(f"CAPTURE_NOT_CURRENT_CERTIFIED_ACTIVE:{blocked}")
