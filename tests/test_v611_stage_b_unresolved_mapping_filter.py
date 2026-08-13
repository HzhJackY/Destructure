from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from guided_workflow_ui import _stage_b_actionable_inventory_mappings


class _FakeChildDiscoveryRepository:
    def unresolved_inventory_cases(self, *, anchor_child_id):
        if anchor_child_id == "CHILD_WITH_CASE":
            return [{"resolution_case_id": "CASE_1"}]
        return []


class _FakeBackend:
    def __init__(self) -> None:
        self.child_discovery_repository = _FakeChildDiscoveryRepository()


def test_stage_b_actionable_inventory_mappings_skips_empty_cases() -> None:
    backend = _FakeBackend()
    mappings = [
        {
            "child": {"anchor_child_id": "CHILD_WITH_CASE"},
            "contract": {"canonical_title": "有 case"},
        },
        {
            "child": {"anchor_child_id": "CHILD_WITHOUT_CASE"},
            "contract": {"canonical_title": "无 case"},
        },
    ]

    actionable = _stage_b_actionable_inventory_mappings(backend, mappings)

    assert len(actionable) == 1
    item, cases = actionable[0]
    assert item["child"]["anchor_child_id"] == "CHILD_WITH_CASE"
    assert cases == [{"resolution_case_id": "CASE_1"}]
