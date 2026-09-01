from __future__ import annotations

import pandas as pd

from identity_migration import migrate_identity_frame


def test_identity_migration_creates_stable_ids_and_drops_legacy_columns() -> None:
    frame = pd.DataFrame([
        {
            "pdf_sha256": "sha",
            "table_block_id": "BLOCK",
            "page": 10,
            "bbox": '{"x0": 10, "y0": 20, "x1": 100, "y1": 30}',
            "raw_item": "债权类金融资产",
            "normalized_item": "债权类金融资产",
            "parent_section": None,
            "row_level": 0,
            "row_type": "DETAIL",
            "row_path": "债权类金融资产",
            "canonical_item": None,
            "mapping_status": "RAW",
        },
        {
            "pdf_sha256": "sha",
            "table_block_id": "BLOCK",
            "page": 10,
            "bbox": '{"x0": 20, "y0": 32, "x1": 100, "y1": 42}',
            "raw_item": "－债券",
            "normalized_item": "－债券",
            "parent_section": "债权类金融资产",
            "row_level": 1,
            "row_type": "DETAIL",
            "row_path": "债权类金融资产 / －债券",
            "canonical_item": None,
            "mapping_status": "RAW",
        },
    ])
    migrated, audit = migrate_identity_frame(frame)
    assert "source_row_id" in migrated.columns
    assert migrated.loc[1, "parent_row_id"] == migrated.loc[0, "source_row_id"]
    assert not set((
        "parent_section", "row_level", "row_type", "row_path",
        "canonical_item", "mapping_status",
    )).intersection(migrated.columns)
    assert audit["unresolved_parent_rows"] == []


def test_identity_migration_marks_ambiguous_parent_without_guessing() -> None:
    frame = pd.DataFrame([
        {"pdf_sha256": "sha", "page": 1, "raw_item": "资产", "normalized_item": "资产"},
        {"pdf_sha256": "sha", "page": 1, "raw_item": "资产", "normalized_item": "资产"},
        {"pdf_sha256": "sha", "page": 1, "raw_item": "现金", "normalized_item": "现金", "parent_section": "资产"},
    ])
    migrated, audit = migrate_identity_frame(frame)
    assert migrated.loc[2, "parent_row_id"] == ""
    assert audit["unresolved_parent_rows"][0]["status"] == "IDENTITY_MIGRATION_UNRESOLVED"
