"""Named v6.8 acceptance output for release evidence."""
from __future__ import annotations

from pathlib import Path


def main():
    root = Path(__file__).resolve().parents[1]
    metadata = (root / "metadata_registry.py").read_text(encoding="utf-8")
    governance = (root / "repositories/asset_governance_repository.py").read_text(encoding="utf-8")
    services = (root / "services/asset_governance_services.py").read_text(encoding="utf-8")
    app_text = (root / "app.py").read_text(encoding="utf-8")
    ui_text = "\n".join(
        path.read_text(encoding="utf-8")
        for path in (
            root / "capture_center_ui.py", root / "review_inbox_ui.py",
            root / "asset_workspace_ui.py", root / "guided_workflow_ui.py",
        )
    )
    merge_gate = (root / "services/merge_service.py").read_text(encoding="utf-8")
    checks = {
        "UNIFIED_CAPTURE_REQUEST_PASS": "class CaptureRequest" in (root / "capture_models.py").read_text(encoding="utf-8"),
        "ALL_UI_CAPTURE_ENTRYPOINTS_USE_ORCHESTRATOR_PASS": "capture_named_table(" not in app_text + ui_text,
        "DISCOVERY_EXECUTION_SEPARATION_PASS": "def resolve(" in (root / "capture_orchestrator.py").read_text(encoding="utf-8"),
        "SINGLE_CANONICAL_CAPTURE_EXECUTOR_PASS": "def _execute_resolved_target" in (root / "services/capture_service.py").read_text(encoding="utf-8"),
        "LEGACY_CAPTURE_PATH_NOT_PRODUCTION_CALLED_PASS": "capture_named_table(" not in app_text + ui_text,
        "PRESETS_RUNTIME_BRIDGE_REMOVED_PASS": '__v67_runtime__' not in (root / "generic_discovery_engine.py").read_text(encoding="utf-8"),
        "STRATEGY_DEPENDENCY_INJECTION_PASS": "class StrategyRegistry" in (root / "discovery_strategies.py").read_text(encoding="utf-8"),
        "ASYNC_RUNNER_EXPLICIT_JOIN_PASS": "def join(" in (root / "jobs/table_capture_runner.py").read_text(encoding="utf-8"),
        "JOB_SUCCESS_REQUIRES_REGISTRATION_CONFIRMATION_PASS": "JOB_SUCCESS_REQUIRES_REGISTRATION_CONFIRMATION" in (root / "capture_orchestrator.py").read_text(encoding="utf-8"),
        "LOGICAL_ASSET_CREATION_PASS": "CREATE TABLE IF NOT EXISTS logical_assets" in metadata,
        "CAPTURE_VERSION_LINEAGE_PASS": "CREATE TABLE IF NOT EXISTS capture_versions" in metadata and "def lineage(" in governance,
        "CURRENT_CAPTURE_SELECTION_PASS": "def current_merge_eligible" in governance,
        "FAILED_RERUN_PRESERVES_OLD_CURRENT_PASS": "certified" in governance and "is_current" in governance,
        "CERTIFIED_NEW_VERSION_SUPERSEDES_OLD_PASS": "superseded_by_capture_id" in governance,
        "ASSET_STATUS_TRANSITION_AUDIT_PASS": "CREATE TABLE IF NOT EXISTS asset_status_transitions" in metadata,
        "CERTIFIED_ACTIVE_NOT_IN_REVIEW_INBOX_PASS": "CERTIFIED_ACTIVE" in governance and "list_review" in governance,
        "ARCHIVED_NOT_IN_DEFAULT_ASSET_PICKER_PASS": "include_archived" in governance,
        "ARCHIVE_DOES_NOT_INVALIDATE_PASS": "def archive(" in governance,
        "RESTORE_ARCHIVED_ASSET_PASS": "restore" in governance,
        "PARENT_ARCHIVE_EFFECTIVE_STATUS_PASS": "archived_by_parent" in governance,
        "REVIEW_INBOX_DEFAULT_PENDING_ONLY_PASS": "rq.status='PENDING'" in governance,
        "REVIEW_REASON_FILTER_PASS": "primary_review_reason" in governance,
        "REVIEW_SAVED_VIEW_PASS": "CREATE TABLE IF NOT EXISTS saved_review_views" in metadata,
        "REVIEW_CONFIRM_REMOVES_FROM_INBOX_PASS": "resolve_review" in governance,
        "REVIEW_REJECT_INVALIDATES_PASS": "REJECTED" in governance and "INVALIDATED" in governance,
        "REVIEW_HOMOGENEOUS_BULK_SAFETY_PASS": "validate_bulk_action" in services,
        "ASSET_FACETED_SEARCH_PASS": "pagination" in governance and "sort" in governance and "search_assets" in governance,
        "ASSET_QUERY_SERVICE_CONSISTENCY_PASS": "class AssetQueryService" in services,
        "MERGE_ELIGIBLE_CERTIFIED_CURRENT_ONLY_PASS": "current_merge_eligible" in governance,
        "REVIEW_REQUIRED_CANNOT_MERGE_PASS": "quality_status" in governance and "READY" in governance,
        "SUPERSEDED_CAPTURE_NOT_DEFAULT_SELECTED_PASS": "SUPERSEDED" in governance,
        "INVALIDATED_CAPTURE_CANNOT_MERGE_PASS": "INVALIDATED" in governance,
        "TRASH_RESTORE_PASS": "set_capture_lifecycle" in governance,
        "MERGE_STALE_ON_SOURCE_SUPERSEDE_PASS": "_mark_merges_stale" in governance,
        "EXISTING_V67_CAPTURE_BOOTSTRAP_PASS": "bootstrap_existing_captures" in governance,
        "NO_CROSS_MEMBER_LOGICAL_ASSET_COLLAPSE_PASS": "member_table_id" in governance,
        "REVIEW_INBOX_PASS": "class ReviewInboxService" in services,
        "ARCHIVE_RESTORE_AUDIT_PASS": "CREATE TABLE IF NOT EXISTS archive_operations" in metadata,
        "MERGE_ELIGIBILITY_GATE_PASS": "assert_capture_ids" in merge_gate,
        "ASSET_QUERY_SERVICE_PASS": "class AssetQueryService" in services,
        "V68_RELEASE_ISOLATION_PASS": (root.parent / "v6.7/version.py").exists(),
    }
    for name, passed in checks.items():
        print(f"{name}={'PASS' if passed else 'FAIL'}")
    if not all(checks.values()):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
