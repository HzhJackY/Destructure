"""Reusable merge picker restricted to current certified active versions."""
from __future__ import annotations


def render_merge_asset_picker(st, backend, *, key: str = "v68_merge_assets") -> list[str]:
    rows = backend.merge_eligibility_service.eligible_assets()
    event = st.dataframe(rows, use_container_width=True, hide_index=True,
                         selection_mode="multi-row", on_select="rerun", key=key)
    selected = event.selection.rows if event else []
    return [str(rows[i]["capture_id"]) for i in selected if i < len(rows)]
