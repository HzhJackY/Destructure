"""v6.13 Cross-year merged structural order boundaries & two-phase normalization contracts."""
from __future__ import annotations

import sys
from pathlib import Path
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from table_merge import (  # noqa: E402
    _merge_missing_keys_preserving_context,
    _normalize_logical_table_row_order,
    _validate_logical_table_order,
    build_structural_order,
)


def test_missing_historical_row_inserted_in_parent_subtree_before_total():
    """Verify historical missing items are inserted in their parent subtree and strictly before TOTAL."""
    base_seq = [
        "CANON::fixed_income",
        "CANON::term_deposits",
        "CANON::bonds",
        "CANON::equity_assets",
        "CANON::stocks",
        "CANON::total",
    ]
    base_meta = {
        "CANON::fixed_income": {"canonical_key": "CANON::fixed_income", "canonical_item": "固定到期日金融资产", "row_type": "PARENT", "row_level": 0, "parent_section": ""},
        "CANON::term_deposits": {"canonical_key": "CANON::term_deposits", "canonical_item": "定期存款", "row_type": "DETAIL", "row_level": 1, "parent_section": "固定到期日金融资产"},
        "CANON::bonds": {"canonical_key": "CANON::bonds", "canonical_item": "债券", "row_type": "DETAIL", "row_level": 1, "parent_section": "固定到期日金融资产"},
        "CANON::equity_assets": {"canonical_key": "CANON::equity_assets", "canonical_item": "权益类金融资产", "row_type": "PARENT", "row_level": 0, "parent_section": ""},
        "CANON::stocks": {"canonical_key": "CANON::stocks", "canonical_item": "股票", "row_type": "DETAIL", "row_level": 1, "parent_section": "权益类金融资产"},
        "CANON::total": {"canonical_key": "CANON::total", "canonical_item": "合计", "row_type": "TOTAL", "row_level": 0, "parent_section": ""},
    }

    incoming_seq = [
        "CANON::fixed_income",
        "CANON::term_deposits",
        "CANON::bonds",
        "CANON::other_fixed_income",  # Historical item under fixed_income
        "CANON::equity_assets",
        "CANON::stocks",
        "CANON::funds",               # Historical item under equity_assets
        "CANON::total",
    ]
    incoming_meta = {
        **base_meta,
        "CANON::other_fixed_income": {"canonical_key": "CANON::other_fixed_income", "canonical_item": "其他固定到期日投资", "row_type": "DETAIL", "row_level": 1, "parent_section": "固定到期日金融资产"},
        "CANON::funds": {"canonical_key": "CANON::funds", "canonical_item": "基金", "row_type": "DETAIL", "row_level": 1, "parent_section": "权益类金融资产"},
    }

    merged = _merge_missing_keys_preserving_context(
        base_seq,
        incoming_seq,
        base_meta=base_meta,
        incoming_meta=incoming_meta,
    )

    # 1. "其他固定到期日投资" must be after "债券" and BEFORE "权益类金融资产"
    assert merged.index("CANON::other_fixed_income") == merged.index("CANON::bonds") + 1
    assert merged.index("CANON::other_fixed_income") < merged.index("CANON::equity_assets")

    # 2. "基金" must be after "股票" and BEFORE "合计"
    assert merged.index("CANON::funds") == merged.index("CANON::stocks") + 1
    assert merged.index("CANON::funds") < merged.index("CANON::total")

    # 3. "合计" must remain the last row
    assert merged[-1] == "CANON::total"


def test_subtotal_and_total_boundaries():
    """Verify missing items are inserted before SUBTOTAL and before TOTAL."""
    base_seq = [
        "CANON::parent_A",
        "CANON::child_A1",
        "CANON::subtotal_A",
        "CANON::total",
    ]
    base_meta = {
        "CANON::parent_A": {"canonical_key": "CANON::parent_A", "canonical_item": "投资A", "row_type": "PARENT", "parent_section": ""},
        "CANON::child_A1": {"canonical_key": "CANON::child_A1", "canonical_item": "细项A1", "row_type": "DETAIL", "parent_section": "投资A"},
        "CANON::subtotal_A": {"canonical_key": "CANON::subtotal_A", "canonical_item": "小计A", "row_type": "SUBTOTAL", "parent_section": "投资A"},
        "CANON::total": {"canonical_key": "CANON::total", "canonical_item": "合计", "row_type": "TOTAL", "parent_section": ""},
    }

    incoming_seq = [
        "CANON::parent_A",
        "CANON::child_A1",
        "CANON::child_A2",  # Missing item under parent_A
        "CANON::subtotal_A",
        "CANON::total",
    ]
    incoming_meta = {
        **base_meta,
        "CANON::child_A2": {"canonical_key": "CANON::child_A2", "canonical_item": "细项A2", "row_type": "DETAIL", "parent_section": "投资A"},
    }

    merged = _merge_missing_keys_preserving_context(
        base_seq,
        incoming_seq,
        base_meta=base_meta,
        incoming_meta=incoming_meta,
    )

    # child_A2 must be inserted before subtotal_A
    assert merged == [
        "CANON::parent_A",
        "CANON::child_A1",
        "CANON::child_A2",
        "CANON::subtotal_A",
        "CANON::total",
    ]


def test_multi_block_total_isolation():
    """Verify separate blocks maintain their own terminal TOTAL rows without cross-block leakage."""
    base_seq = [
        "CANON::B1_item1",
        "CANON::B1_total",
        "CANON::B2_item1",
        "CANON::B2_total",
    ]
    base_meta = {
        "CANON::B1_item1": {"canonical_key": "CANON::B1_item1", "table_block_id": "BLOCK_1", "row_type": "DETAIL"},
        "CANON::B1_total": {"canonical_key": "CANON::B1_total", "table_block_id": "BLOCK_1", "row_type": "TOTAL"},
        "CANON::B2_item1": {"canonical_key": "CANON::B2_item1", "table_block_id": "BLOCK_2", "row_type": "DETAIL"},
        "CANON::B2_total": {"canonical_key": "CANON::B2_total", "table_block_id": "BLOCK_2", "row_type": "TOTAL"},
    }

    incoming_seq = [
        "CANON::B1_item1",
        "CANON::B1_item2",  # Missing in Block 1
        "CANON::B1_total",
        "CANON::B2_item1",
        "CANON::B2_item2",  # Missing in Block 2
        "CANON::B2_total",
    ]
    incoming_meta = {
        **base_meta,
        "CANON::B1_item2": {"canonical_key": "CANON::B1_item2", "table_block_id": "BLOCK_1", "row_type": "DETAIL"},
        "CANON::B2_item2": {"canonical_key": "CANON::B2_item2", "table_block_id": "BLOCK_2", "row_type": "DETAIL"},
    }

    merged = _merge_missing_keys_preserving_context(
        base_seq,
        incoming_seq,
        base_meta=base_meta,
        incoming_meta=incoming_meta,
    )

    assert merged == [
        "CANON::B1_item1",
        "CANON::B1_item2",
        "CANON::B1_total",
        "CANON::B2_item1",
        "CANON::B2_item2",
        "CANON::B2_total",
    ]


def test_footnote_stays_below_total():
    """Verify footnotes/memos remain below TOTAL after normalization."""
    keys = [
        "CANON::detail_1",
        "CANON::footnote_1",
        "CANON::total",
    ]
    meta = {
        "CANON::detail_1": {"canonical_key": "CANON::detail_1", "row_type": "DETAIL", "table_block_id": "B1"},
        "CANON::footnote_1": {"canonical_key": "CANON::footnote_1", "row_type": "FOOTNOTE", "table_block_id": "B1"},
        "CANON::total": {"canonical_key": "CANON::total", "row_type": "TOTAL", "table_block_id": "B1"},
    }

    normalized = _normalize_logical_table_row_order(keys, meta)
    assert normalized == [
        "CANON::detail_1",
        "CANON::total",
        "CANON::footnote_1",
    ]


def test_validate_logical_table_order_invariants():
    """Verify QA Invariants 1-6 are strictly enforced and violations detected."""
    # Valid case
    valid_keys = ["CANON::A", "CANON::B", "CANON::TOTAL"]
    meta = {
        "CANON::A": {"canonical_key": "CANON::A", "row_type": "DETAIL", "table_block_id": "B1"},
        "CANON::B": {"canonical_key": "CANON::B", "row_type": "DETAIL", "table_block_id": "B1"},
        "CANON::TOTAL": {"canonical_key": "CANON::TOTAL", "row_type": "TOTAL", "table_block_id": "B1"},
    }
    violations = _validate_logical_table_order(valid_keys, meta, "CAP_REF", ["CANON::A", "CANON::TOTAL"])
    assert len(violations) == 0

    # Invariant 1 violation: detail after total
    invalid_keys = ["CANON::A", "CANON::TOTAL", "CANON::B"]
    violations = _validate_logical_table_order(invalid_keys, meta, "CAP_REF", ["CANON::A", "CANON::TOTAL"])
    assert any(v["conflict_type"] == "DATA_ROW_AFTER_TOTAL" for v in violations)

    # Invariant 6 violation: benchmark inversion
    inverted_keys = ["CANON::TOTAL", "CANON::A"]
    violations = _validate_logical_table_order(inverted_keys, meta, "CAP_REF", ["CANON::A", "CANON::TOTAL"])
    assert any(v["conflict_type"] == "BENCHMARK_ORDER_INVERSION" for v in violations)


def test_build_structural_order_end_to_end():
    """Verify full end-to-end structural order building with cross-year sources."""
    rows = [
        # Reference capture 2024
        {"capture_run_id": "CAP_2024", "row_order": 1, "canonical_key": "K_PARENT", "canonical_item": "固定收益", "row_type": "PARENT", "table_block_id": "BLOCK_1", "table_family": "INV", "member_table": "DEBT"},
        {"capture_run_id": "CAP_2024", "row_order": 2, "canonical_key": "K_ITEM1", "canonical_item": "定期存款", "row_type": "DETAIL", "parent_section": "固定收益", "table_block_id": "BLOCK_1", "table_family": "INV", "member_table": "DEBT"},
        {"capture_run_id": "CAP_2024", "row_order": 3, "canonical_key": "K_TOTAL", "canonical_item": "合计", "row_type": "TOTAL", "table_block_id": "BLOCK_1", "table_family": "INV", "member_table": "DEBT"},
        # Historical capture 2023 (has extra item under K_PARENT)
        {"capture_run_id": "CAP_2023", "row_order": 1, "canonical_key": "K_PARENT", "canonical_item": "固定收益", "row_type": "PARENT", "table_block_id": "BLOCK_1", "table_family": "INV", "member_table": "DEBT"},
        {"capture_run_id": "CAP_2023", "row_order": 2, "canonical_key": "K_ITEM1", "canonical_item": "定期存款", "row_type": "DETAIL", "parent_section": "固定收益", "table_block_id": "BLOCK_1", "table_family": "INV", "member_table": "DEBT"},
        {"capture_run_id": "CAP_2023", "row_order": 3, "canonical_key": "K_ITEM2", "canonical_item": "债券", "row_type": "DETAIL", "parent_section": "固定收益", "table_block_id": "BLOCK_1", "table_family": "INV", "member_table": "DEBT"},
        {"capture_run_id": "CAP_2023", "row_order": 4, "canonical_key": "K_TOTAL", "canonical_item": "合计", "row_type": "TOTAL", "table_block_id": "BLOCK_1", "table_family": "INV", "member_table": "DEBT"},
    ]
    df = pd.DataFrame(rows)
    manifest = {
        "sources": [{"capture_run_id": "CAP_2024", "member_table_order": 1}, {"capture_run_id": "CAP_2023", "member_table_order": 2}],
        "reference_capture_run_id": "CAP_2024",
    }

    order_df, conflicts_df = build_structural_order(df, manifest)

    assert order_df["canonical_key"].tolist() == [
        "K_PARENT",
        "K_ITEM1",
        "K_ITEM2",
        "K_TOTAL",
    ]
    assert len(conflicts_df) == 0


def test_note_ordinal_cross_year_accounting_measurement_total_position():
    """Verify China Life style cross-year accounting measurement old/new standard items sit before TOTAL."""
    rows = [
        # 2025 reference year items (new standard)
        {"capture_run_id": "CAP_2025", "row_order": 1, "canonical_key": "K_FVTPL", "canonical_item": "交易性金融资产", "row_type": "DETAIL", "member_table": "portfolio_by_measurement", "table_family": "INV", "table_block_id": "BLOCK_2025"},
        {"capture_run_id": "CAP_2025", "row_order": 2, "canonical_key": "K_AC", "canonical_item": "债权投资", "row_type": "DETAIL", "member_table": "portfolio_by_measurement", "table_family": "INV", "table_block_id": "BLOCK_2025"},
        {"capture_run_id": "CAP_2025", "row_order": 3, "canonical_key": "K_TOTAL", "canonical_item": "合计", "row_type": "TOTAL", "member_table": "portfolio_by_measurement", "table_family": "INV", "table_block_id": "BLOCK_2025"},
        # 2023 historical items (old standard + different physical table_block_id)
        {"capture_run_id": "CAP_2023", "row_order": 1, "canonical_key": "K_FVTPL", "canonical_item": "交易性金融资产", "row_type": "DETAIL", "member_table": "portfolio_by_measurement", "table_family": "INV", "table_block_id": "BLOCK_2023"},
        {"capture_run_id": "CAP_2023", "row_order": 2, "canonical_key": "K_AFS", "canonical_item": "可供出售金融资产", "row_type": "DETAIL", "member_table": "portfolio_by_measurement", "table_family": "INV", "table_block_id": "BLOCK_2023"},
        {"capture_run_id": "CAP_2023", "row_order": 3, "canonical_key": "K_HTM", "canonical_item": "持有至到期投资", "row_type": "DETAIL", "member_table": "portfolio_by_measurement", "table_family": "INV", "table_block_id": "BLOCK_2023"},
        {"capture_run_id": "CAP_2023", "row_order": 4, "canonical_key": "K_TOTAL", "canonical_item": "合计", "row_type": "TOTAL", "member_table": "portfolio_by_measurement", "table_family": "INV", "table_block_id": "BLOCK_2023"},
    ]
    df = pd.DataFrame(rows)
    manifest = {
        "order_policy": "NOTE_ORDINAL_REFERENCE_YEAR",
        "reference_report_year": "2025",
        "sources": [
            {"capture_run_id": "CAP_2025", "report_year": "2025", "member_table": "portfolio_by_measurement", "member_table_order": 1, "note_reference": "附注7.1"},
            {"capture_run_id": "CAP_2023", "report_year": "2023", "member_table": "portfolio_by_measurement", "member_table_order": 1, "note_reference": "附注7.1"},
        ],
        "reference_capture_run_id": "CAP_2025",
    }

    order_df, conflicts_df = build_structural_order(df, manifest)

    keys = order_df["canonical_key"].tolist()
    # TOTAL must be the LAST item of the partition
    assert keys[-1] == "K_TOTAL"
    # Both new and old standard items must precede TOTAL
    assert keys.index("K_FVTPL") < keys.index("K_TOTAL")
    assert keys.index("K_AC") < keys.index("K_TOTAL")
    assert keys.index("K_AFS") < keys.index("K_TOTAL")
    assert keys.index("K_HTM") < keys.index("K_TOTAL")
    assert len(conflicts_df) == 0

