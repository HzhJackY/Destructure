"""Regression: unresolved period status must remain reviewable, not disappear."""
from __future__ import annotations

from pathlib import Path

from hierarchical_child_discovery import ChildDiscoveryRepository
from metadata_registry import MetadataRegistry


def test_only_explicit_noncurrent_or_outside_rows_are_excluded(tmp_path: Path) -> None:
    repo = ChildDiscoveryRepository(MetadataRegistry(tmp_path / "metadata.db"))
    anchor = {
        "occurrence_id": "OCC_PERIOD_GATE",
        "scope": "CONSOLIDATED",
        "display_name": "金融投资",
        "report_year": "2023",
        "child_rows": [
            {"item": "交易性金融资产", "member_period_status": "UNRESOLVED", "note_reference": "附注4-11", "values": [1]},
            {"item": "债权投资", "member_period_status": "ACTIVE_CURRENT_PERIOD", "note_reference": "附注4-12", "values": [2]},
            {"item": "旧准则比较数", "member_period_status": "COMPARATIVE_ONLY_LEGACY_MEMBER", "values": [3]},
            {"item": "长期股权投资", "member_period_status": "OUTSIDE_FAMILY", "values": [4]},
        ],
    }
    concepts = repo.create_anchor_children(anchor)
    assert [row["raw_label"] for row in concepts] == ["交易性金融资产", "债权投资"]
    assert concepts[0]["inline_note_reference"] == "附注四-11"
    assert concepts[0]["inline_note_reference_evidence"]["period_status_policy"] == "REVIEWABLE_UNRESOLVED_MEMBER"
