"""DEPRECATED compatibility adapter.

Production navigation no longer calls this module.  It delegates to the
canonical Logical Asset Workspace and contains no review or persistence logic.
"""
from __future__ import annotations


def render_compound_inspection(st, backend, data_paths=None) -> None:
    st.warning("“附注多表检查”已合并到逻辑资产工作区；此兼容入口将直接显示同一工作区。")
    from asset_workspace_ui import render_asset_workspace
    render_asset_workspace(st,backend)
