from __future__ import annotations

from pathlib import Path


ROOT=Path(__file__).resolve().parents[1]


def _text(relative: str) -> str:
    return (ROOT/relative).read_text(encoding="utf-8")


def test_capture_version_is_scoped_to_one_logical_asset_and_batch_queue_is_separate():
    source=_text("asset_workspace_ui.py")
    assert 'capture_version_service.versions(selected_asset)' in source
    assert '"asset_workspace_review_queue"' in source
    assert "跨多个逻辑资产的审核队列" in source
    assert "仅当前 Logical Asset 的历史抓取版本" in source


def test_completed_batch_exposes_review_required_queue_and_workspace_route():
    app=_text("app.py")
    guided=_text("guided_workflow_ui.py")
    for source in (app,guided):
        assert '"asset_workspace_review_queue"' in source
        assert '"_pending_main_page"]="逻辑资产工作区"' in source
        assert "REVIEW_REQUIRED" in source
        assert "审核所选 Capture（进入逻辑资产工作区）" in source


def test_review_queue_uses_the_same_actionable_capture_panel_as_asset_management():
    panel=_text("components/review_action_panel.py")
    assert "下一项必需审核" in panel
    assert "查看证据并处理此任务" in panel
    assert '"PDF_BOUNDARY_REVIEW":"附注容器与表块"' in panel


def test_research_batch_filter_is_available_in_both_asset_views():
    workspace=_text("asset_workspace_ui.py")
    app=_text("app.py")
    repo=_text("repositories/capture_repository.py")
    service=_text("services/asset_governance_services.py")
    assert '("research_batch_id","研究批次")' in workspace
    assert '"研究批次", ["全部"] + options.get("research_batch_id", [])' in app
    assert "distinct_research_batches" in repo
    assert "research_batch_members" in repo
    assert '"research_batch_id"' in service


def test_research_batch_is_resolved_as_relationship_not_capture_column():
    repo=_text("repositories/capture_repository.py")
    assert "rb.source_batch_id=captures.batch_id" in repo
    assert "GROUP_CONCAT(DISTINCT rb.research_batch_id)" in repo
    assert "research_batch_ids" in repo


def test_workspace_hides_trashed_and_historical_versions_by_default():
    repo=_text("repositories/asset_governance_repository.py")
    workspace=_text("asset_workspace_ui.py")
    for status in ("ARCHIVED","TRASHED","SUPERSEDED","INVALIDATED"):
        assert status in repo
        assert status in workspace
    assert "if not include_archived" in workspace


def test_guided_merge_preserves_research_batch_scope():
    guided=_text("guided_workflow_ui.py")
    app=_text("app.py")
    assert 'st.session_state["merge_research_batch_id"]=research_batch_id' in guided
    assert 'research_batch_id=merge_research_batch_id' in app
    assert "清除批次范围" in app
