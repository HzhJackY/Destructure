"""Shared fixtures and locators for v6.11 user journey tests.

Run with: pytest --browser chromium --headed tests/user_journeys/
Requires: pytest-playwright, streamlit running on localhost:8501
"""
from __future__ import annotations

import pytest

BASE_URL = "http://localhost:8501"

# Stable locators using Streamlit component keys and labels.
# Streamlit does not support data-testid directly; we use button labels,
# session-state keys mapped to widget keys, and expander titles.
LOCATORS = {
    # Merge page (整表合表)
    "merge_page_title": "text=整表合表",
    "merge_ready_message": "text=可用于正式合表",
    "no_merge_ready_message": "text=当前没有边界已确认",

    # Guided capture workflow
    "certify_child_links_btn": "button:has-text('认证所选子表关系')",
    "capture_all_certified_btn": "button:has-text('确认并抓取全部已认证子表')",
    "refresh_progress_btn": "button:has-text('刷新进度')",
    "open_review_btn": "button:has-text('审核所选 Capture')",
    "go_merge_btn": "button:has-text('进入合表')",

    # Stage B — strict flow
    "strict_child_mapping_section": "text=审核子表映射（严格分级召回）",
    # Stage B — compat flow
    "compat_note_target_section": "text=兼容流程：审核显式附注目标",

    # Review inbox
    "review_inbox_tab": "text=审核",

    # Navigation
    "logical_asset_workspace": "text=逻辑资产工作区",
}


@pytest.fixture(scope="session")
def browser_context(browser):
    context = browser.new_context(locale="zh-CN")
    yield context
    context.close()
