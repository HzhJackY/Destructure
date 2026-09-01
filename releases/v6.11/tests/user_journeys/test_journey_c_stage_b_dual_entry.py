"""Journey C: Stage B dual entry — both flows share the same execution component.

Invariant: BUG-005 — Both strict-child-mapping and explicit-note-target
flows use the same CertifiedChildCaptureExecutionPanel and service.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))


def test_both_flows_use_same_panel() -> None:
    """Both adapters converge before one shared panel render."""
    content = Path(ROOT / "guided_workflow_ui.py").read_text(encoding="utf-8")

    # Both flows import the same component
    import_count = content.count("from components.child_capture_execution_panel import")
    assert import_count >= 1, "No import of shared panel found"

    # Both adapters are combined before the one shared component call.
    call_count = content.count("render_child_capture_execution_panel(")
    assert call_count == 1, (
        f"Expected 1 shared panel call, found {call_count}"
    )

    # Entry origin must not fork the execution-session/widget namespace.
    assert 'strict_stage_b_key_prefix = "v611_stage_b_capture"' in content
    assert 'compat_stage_b_key_prefix = "v611_stage_b_capture"' in content
    assert "v610_strict_child" not in content
    assert "v610_compat_child" not in content

    # Old per-child synchronous loop must be gone
    assert "通过 Capture Orchestrator 抓取已认证子表" not in content, (
        "Old synchronous orchestrator button still present"
    )
    # Old per-plan guided batch tracking must be gone
    assert "v651_guided_batch_ids" not in content, "Old batch ID tracking still present"
    assert "v651_refresh_guided_jobs" not in content, "Old refresh button still present"

    print("JOURNEY_C_SAME_PANEL_PASS")


def test_both_flows_use_same_service() -> None:
    """ChildCaptureExecutionService is imported and used by the panel."""
    from services.child_capture_execution_service import ChildCaptureExecutionService
    from components.child_capture_execution_panel import render_child_capture_execution_panel

    # The panel references backend.child_capture_execution_service
    panel_source = Path(
        ROOT / "components" / "child_capture_execution_panel.py"
    ).read_text(encoding="utf-8")
    assert "child_capture_execution_service" in panel_source, (
        "Panel does not reference child_capture_execution_service"
    )

    # The service has create_execution_batch (shared entry point)
    assert hasattr(ChildCaptureExecutionService, "create_execution_batch")
    assert hasattr(ChildCaptureExecutionService, "prepare_capture_plans")
    assert hasattr(ChildCaptureExecutionService, "restore_execution")
    assert hasattr(ChildCaptureExecutionService, "monitor_all")
    assert hasattr(ChildCaptureExecutionService, "build_review_queue")

    print("JOURNEY_C_SAME_SERVICE_PASS")


def test_batch_lineage_consistent() -> None:
    """Both adapters use Capture Plan → ResearchBatch → SOURCE_BATCH."""
    svc_source = Path(
        ROOT / "services" / "child_capture_execution_service.py"
    ).read_text(encoding="utf-8")

    assert "source_batch_id" in svc_source, (
        "Unified flow does not attach source_batch_id to research batch"
    )
    assert 'role="PLAN"' in svc_source
    assert 'role="SOURCE_BATCH"' in svc_source
    assert "certified_capture_request(" not in svc_source
    assert 'CALLBACK_KEY = "GuidedCaptureService.execute"' in svc_source

    print("JOURNEY_C_BATCH_LINEAGE_CONSISTENT_PASS")


def test_review_redirect_same() -> None:
    """Both flows redirect to the same Logical Asset Workspace."""
    panel_source = Path(
        ROOT / "components" / "child_capture_execution_panel.py"
    ).read_text(encoding="utf-8")

    # Both flows set the same session state for review redirect
    assert "asset_workspace_review_queue" in panel_source
    assert "逻辑资产工作区" in panel_source
    assert "_pending_main_page" in panel_source

    print("JOURNEY_C_REVIEW_REDIRECT_SAME_PASS")


def main() -> None:
    test_both_flows_use_same_panel()
    test_both_flows_use_same_service()
    test_batch_lineage_consistent()
    test_review_redirect_same()
    print("\n=== JOURNEY C (STAGE B DUAL ENTRY): ALL CHECKS PASSED ===")


if __name__ == "__main__":
    main()
