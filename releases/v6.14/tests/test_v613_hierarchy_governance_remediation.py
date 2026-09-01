from __future__ import annotations

from io import StringIO
from pathlib import Path
import pandas as pd
import pytest

from compound_note_engine import _semantic_graph, restore_certified_direct_group_rows
from financial_structure_resolver import project_certified_row_hierarchy
from services.capture_decision_reducer import CaptureDecisionReducer
from spatial_table_capture import (
    _numeric_parent_reconciles,
    validate_hierarchy_graph,
)
from table_capture import (
    TableCell,
    TableColumn,
    TableRow,
    TableCaptureResult,
    capture_to_long_df,
    capture_to_wide_df,
)
from table_merge import assign_semantic_row_keys


def _make_row(order: int, label: str, values: tuple[float | None, ...] = (), x0: float = 100.0,
              parent_sec: str | None = None, parent_id: str | None = None,
              source_id: str | None = None, block_id: str = "b1",
              raw_tokens: tuple[str, ...] | None = None) -> TableRow:
    cells = []
    for ord_idx, val in enumerate(values):
        raw_tok = raw_tokens[ord_idx] if raw_tokens and ord_idx < len(raw_tokens) else (str(val) if val is not None else "")
        cells.append(TableCell(
            column_ordinal=ord_idx,
            source_column_index=ord_idx + 1,
            raw=raw_tok,
            parsed_number=val,
            unit_original="百万元",
            value_yuan=val * 1_000_000 if val is not None else None,
        ))
    return TableRow(
        row_order=order,
        page=1,
        block_id=block_id,
        source_method="spatial",
        raw_item=label,
        normalized_item=label,
        canonical_item=None,
        mapping_status="UNMAPPED",
        row_type="DETAIL" if values else "PARENT_SECTION",
        row_level=1 if parent_sec or parent_id else 0,
        parent_section=parent_sec,
        cells=cells,
        header_source_page=None,
        row_role="BREAKDOWN_DETAIL" if parent_sec or parent_id else "DETAIL",
        row_item_raw=label,
        row_item_normalized=label,
        label_derivation="EXPLICIT",
        bbox={"x0": x0, "y0": float(order * 10), "x1": 500.0, "y1": float(order * 10 + 8)},
        source_row_id=source_id or f"ROW_SRC_{order}",
        parent_row_id=parent_id,
    )


def test_v613_new_capture_missing_id_fails_closed() -> None:
    """Node 2: A v6.13 capture missing source_row_id is flagged as REVIEW_REQUIRED_SOURCE_IDENTITY."""
    df = pd.DataFrame([{
        "capture_run_id": "CAP_2024_NEW",
        "producer_version": "v6.13",
        "schema_version": 17,
        "source_row_id": None,
        "parent_row_id": None,
        "row_order": 1,
        "raw_item": "债权投资",
        "normalized_item": "债权投资",
        "parent_section": None,
        "value": 100.0,
    }])
    keyed = assign_semantic_row_keys(df)
    assert keyed.loc[0, "hierarchy_status"] == "REVIEW_REQUIRED_SOURCE_IDENTITY"
    assert "UNRESOLVED_SOURCE" in keyed.loc[0, "semantic_row_key"]


def test_empty_raw_cell_not_treated_as_printed_dash() -> None:
    """Node 3: Empty string is NOT treated as printed dash; missing extraction blocks reconciliation."""
    parent = _make_row(1, "合计", (300.0, 300.0), raw_tokens=("300", "300"))
    c1 = _make_row(2, "子项1", (100.0, None), parent_sec="合计", raw_tokens=("100", ""))
    c2 = _make_row(3, "子项2", (200.0, 300.0), parent_sec="合计", raw_tokens=("200", "300"))

    reconciles, checks = _numeric_parent_reconciles(parent, [c1, c2])
    assert not reconciles or 1 not in checks


def test_printed_dash_and_not_applicable_reconcile() -> None:
    """Node 3: Explicit dashes and not applicable contribute 0.0 to reconciliation."""
    parent = _make_row(1, "合计", (300.0, 50.0), raw_tokens=("300", "50"))
    c1 = _make_row(2, "子项1", (100.0, None), parent_sec="合计", raw_tokens=("100", "-"))
    c2 = _make_row(3, "子项2", (200.0, 50.0), parent_sec="合计", raw_tokens=("200", "50"))

    reconciles, checks = _numeric_parent_reconciles(parent, [c1, c2])
    assert reconciles is True
    assert checks[0]["sum_children"] == 300.0
    assert checks[1]["sum_children"] == 50.0


def test_semantic_graph_only_consumes_formal_parent_row_id() -> None:
    """Node 4: _semantic_graph builds PARENT_OF strictly from parent_row_id."""
    r1 = _make_row(1, "债权资产", source_id="ROW_P1")
    r2 = _make_row(2, "企业债", parent_id="ROW_P1", parent_sec="债权资产", source_id="ROW_C1")
    r3 = _make_row(3, "国债", parent_sec="债权资产", source_id="ROW_C2")

    graph = _semantic_graph([r1, r2, r3])
    parent_of = [rel for rel in graph["relations"] if rel["type"] == "PARENT_OF"]
    unresolved_hints = [rel for rel in graph["relations"] if rel["type"] == "UNRESOLVED_PARENT_HINT"]

    assert len(parent_of) == 1
    assert parent_of[0]["parent"] == "债权资产"
    assert parent_of[0]["child"] == "企业债"
    assert parent_of[0]["parent_source_row_id"] == "ROW_P1"

    assert len(unresolved_hints) == 1
    assert unresolved_hints[0]["child"] == "国债"
    assert unresolved_hints[0]["hint_parent_section"] == "债权资产"


def test_validate_hierarchy_graph_covers_dangling_cycle_self_ref_cross_block() -> None:
    """Node 5: validate_hierarchy_graph detects dangling edges, cycles, self-references, and cross block."""
    # 1. Valid parent-child
    r1 = _make_row(1, "父项", source_id="ROW_1", block_id="b1")
    r2 = _make_row(2, "子项", parent_id="ROW_1", source_id="ROW_2", block_id="b1")
    val_ok = validate_hierarchy_graph([r1, r2])
    assert val_ok["status"] == "VALID"
    assert val_ok["valid_edges"] == 1

    # 2. Dangling edge
    r_dang = _make_row(3, "孤儿子项", parent_id="NON_EXISTENT_ID", source_id="ROW_3", block_id="b1")
    val_dang = validate_hierarchy_graph([r1, r2, r_dang])
    assert val_dang["status"] == "REVIEW_REQUIRED"
    assert len(val_dang["dangling_edges"]) == 1

    # 3. Self reference
    r_self = _make_row(4, "自引用", parent_id="ROW_4", source_id="ROW_4", block_id="b1")
    val_self = validate_hierarchy_graph([r_self])
    assert val_self["status"] == "REVIEW_REQUIRED"
    assert len(val_self["self_reference_edges"]) == 1

    # 4. Cycle
    r_cyc1 = _make_row(5, "环1", parent_id="ROW_6", source_id="ROW_5", block_id="b1")
    r_cyc2 = _make_row(6, "环2", parent_id="ROW_5", source_id="ROW_6", block_id="b1")
    val_cyc = validate_hierarchy_graph([r_cyc1, r_cyc2])
    assert val_cyc["status"] == "REVIEW_REQUIRED"
    assert len(val_cyc["cycle_edges"]) >= 1

    # 5. Cross block
    r_xb = _make_row(7, "跨块子项", parent_id="ROW_1", source_id="ROW_7", block_id="b2")
    val_xb = validate_hierarchy_graph([r1, r_xb])
    assert val_xb["status"] == "REVIEW_REQUIRED"
    assert len(val_xb["cross_block_edges"]) == 1


def test_capture_to_long_df_does_not_mutate_input_rows() -> None:
    """Node 6: capture_to_long_df does not mutate rows in input TableCaptureResult."""
    r1 = _make_row(1, "父项", source_id="ROW_1")
    r2 = _make_row(2, "子项", values=(100.0,), parent_id=None, source_id="ROW_2")
    r2.hierarchy_evidence = {"parent_row_order": 1}

    result = TableCaptureResult(
        pdf_name="test.pdf",
        pdf_sha256="abc",
        table_query="query",
        note_number="1",
        located_title="title",
        start_page=1,
        end_page=1,
        pages=[1],
        unit="百万元",
        columns=[TableColumn(0, 1, "2024", "2024", None, False, "2024")],
        rows=[r1, r2],
        warnings=[],
        stats={},
    )
    long_df = capture_to_long_df(result)
    assert not long_df.empty
    # Input r2.parent_row_id must remain untouched (None)
    assert r2.parent_row_id is None


def test_capture_decision_reducer_blocks_on_hierarchy_review_required() -> None:
    """Node 5: CaptureDecisionReducer adds REVIEW_REQUIRED_SOURCE_IDENTITY when hierarchy validation fails."""
    evidence = {
        "rows": [{"row_order": 1, "raw_item": "测试", "cells": [{"cell_role": "NUMERIC"}]}],
        "stats": {
            "hierarchy_graph_validation": {
                "status": "REVIEW_REQUIRED",
                "review_reasons": ["HIERARCHY_GRAPH_DANGLING_EDGES: 发现 1 条悬空父子边。"],
            },
            "v69_header_topology": {"consistent": True},
            "v69_reconciliation": {"status": "PASS"},
        },
        "unit": "百万元",
    }
    decision = CaptureDecisionReducer().reduce(machine_evidence=evidence)
    assert "REVIEW_REQUIRED_SOURCE_IDENTITY" in decision.blocking_issues
    assert decision.quality_status == "REVIEW_REQUIRED"
    assert decision.merge_eligible is False
