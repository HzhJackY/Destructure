from __future__ import annotations

from io import StringIO

import pandas as pd

from financial_structure_resolver import project_certified_row_hierarchy


def test_legacy_empty_parent_column_accepts_projected_string_id() -> None:
    """Old CSVs may infer an all-empty parent_row_id column as float64."""
    rows = pd.read_csv(StringIO(
        "source_row_id,parent_row_id,row_order,raw_item,normalized_item,parent_section\n"
        ",,1,固定到期日金融资产,固定到期日金融资产,\n"
        ",,2,定期存款,定期存款,固定到期日金融资产\n"
    ))
    assert str(rows["parent_row_id"].dtype) == "float64"

    projected = project_certified_row_hierarchy(
        rows,
        allow_legacy_compatibility=True,
    )

    child = projected.loc[projected["source_row_id"] == "LEGACY_ROW_ORDER::2"].iloc[0]
    assert child["parent_row_id"] == "LEGACY_ROW_ORDER::1"
    assert child["hierarchy_path"] == "固定到期日金融资产 / 定期存款"


def test_identity_columns_are_writable_with_arrow_string_input() -> None:
    rows = pd.DataFrame({
        "source_row_id": pd.array(["", ""], dtype="string"),
        "parent_row_id": pd.array(["", ""], dtype="string"),
        "row_order": [1, 2],
        "raw_item": ["投资资产", "债券"],
        "normalized_item": ["投资资产", "债券"],
        "parent_section": ["", "投资资产"],
    })

    projected = project_certified_row_hierarchy(
        rows,
        allow_legacy_compatibility=True,
    )

    assert projected.loc[1, "source_row_id"] == "LEGACY_ROW_ORDER::2"
    assert projected.loc[1, "parent_row_id"] == "LEGACY_ROW_ORDER::1"
    assert projected.loc[1, "hierarchy_path"] == "投资资产 / 债券"
