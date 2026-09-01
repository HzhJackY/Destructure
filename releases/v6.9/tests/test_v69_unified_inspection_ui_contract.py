from __future__ import annotations

from pathlib import Path


ROOT=Path(__file__).resolve().parents[1]


def _text(relative: str) -> str:
    return (ROOT/relative).read_text(encoding="utf-8")


def test_unified_workspace_is_the_single_detail_implementation():
    workspace=_text("asset_workspace_ui.py")
    inbox=_text("review_inbox_ui.py")
    compound=_text("compound_inspection_ui.py")
    assert "render_capture_inspection_panel" in workspace
    assert "render_capture_inspection_panel" not in inbox
    assert "render_pdf_evidence_panel" not in inbox
    assert "DEPRECATED" in compound
    assert "render_asset_workspace" in compound


def test_review_actions_and_pdf_evidence_have_one_production_owner():
    action=_text("components/review_action_panel.py")
    evidence=_text("components/pdf_evidence_panel.py")
    panel=_text("components/capture_inspection_panel.py")
    assert "review_service.adjudicate_capture" in action
    assert "page_preview" in evidence
    assert "render_pdf_evidence_panel" in panel
    for relative in (
        "asset_workspace_ui.py","review_inbox_ui.py","compound_inspection_ui.py",
        "components/capture_inspection_panel.py","components/review_action_panel.py",
    ):
        source=_text(relative)
        assert ".execute(" not in source
        assert "sqlite3" not in source


def test_navigation_and_merge_sources_route_to_workspace():
    app=_text("app.py")
    nav=app[app.index("page = st.sidebar.radio"):app.index("st.sidebar.divider()")]
    assert '"附注多表检查"' not in nav
    assert '"人工复核"' not in nav
    assert '"逻辑资产工作区"' in nav
    merge=app[app.index('elif page == "合表"'):app.index('elif page == "报告与审计"')]
    assert "set_inspection_route" in merge
    assert "在逻辑资产工作区检查此来源" in merge
    assert "在逻辑资产工作区检查已选来源" in merge


def test_inspection_route_contract_uses_stable_identifiers():
    route=_text("inspection_route.py")
    for field in (
        "logical_asset_id","capture_version_id","table_block_id",
        "initial_tab","return_route","review_queue_item_id",
    ):
        assert field in route
