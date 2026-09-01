"""v6.6 implicit numeric total recovery contracts."""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from table_capture import TableCell, TableRow
from implicit_total_rows import recover_implicit_total_rows
from financial_structure_resolver import subtotal_validation
from financial_metric_pdf_resolver import extract_pdf_blocks
from table_capture import select_table_blocks, infer_columns, materialize_rows


def row(order: int, label: str | None, value: float) -> TableRow:
    return TableRow(
        row_order=order, page=1, block_id="synthetic", source_method="TEST",
        raw_item=label, normalized_item=label or "", canonical_item=None,
        mapping_status="UNMAPPED", row_type="DETAIL", row_level=0,
        parent_section=None, cells=[TableCell(0, 1, str(value), value, "万元", value * 10000)],
        header_source_page=1, row_role="DETAIL" if label else "IMPLICIT_ROW_CANDIDATE",
        row_item_raw=label, row_item_normalized=label, label_derivation="EXPLICIT_TEXT" if label else "NONE",
    )


def main() -> None:
    rows = recover_implicit_total_rows([
        row(1, "上市", 259579), row(2, "非上市", 5298), row(3, None, 264877),
    ], parent_table="其他权益工具投资")
    total = rows[-1]
    assert total.raw_item is None and total.row_item_raw is None
    assert total.row_role == "IMPLICIT_TOTAL" and total.row_type == "IMPLICIT_TOTAL"
    assert total.row_item_normalized == "其他权益工具投资总额"
    assert total.label_derivation == "DERIVED_FROM_PARENT_TABLE"
    assert total.derivation_method == "SUM_CHILDREN"
    assert total.derived_from_rows == ["上市", "非上市"]
    print("IMPLICIT_TOTAL_ROW_DETECT_PASS")
    print("IMPLICIT_TOTAL_PARENT_INHERITANCE_PASS")
    print("IMPLICIT_TOTAL_AUDIT_TRACE_PASS")

    records = []
    for item in rows:
        records.append({
            "row_order": item.row_order, "row_type": item.row_type, "row_role": item.row_role,
            "row_level": item.row_level, "parent_section": item.parent_section,
            "raw_item": item.raw_item, "normalized_item": item.normalized_item,
            "row_item_raw": item.row_item_raw, "row_item_normalized": item.row_item_normalized,
            "derived_from_rows": item.derived_from_rows, "value": item.cells[0].value_yuan,
            "unit": "元", "column_ordinal": 0, "year": "2025", "scope": "CONSOLIDATED", "restated": False,
        })
    audit = subtotal_validation(pd.DataFrame(records))
    implicit = audit[audit["evidence"] == "IMPLICIT_TOTAL_SUM_CHILDREN"]
    assert not implicit.empty and implicit.iloc[0]["status"] == "PASS_EXACT", audit
    print("IMPLICIT_TOTAL_SUM_VALIDATION_PASS")

    # Real 2025 Ping An note 12: the source PDF contains an unlabelled
    # 609,550 / 356,493 line after listed + unlisted.  It must remain raw-NULL
    # while becoming a derived, auditable total.
    pdf = Path(r"C:\dev\AXA_research\docu\中国平安2025年报.pdf")
    blocks, _ = extract_pdf_blocks(pdf, page_numbers={263})
    selected = select_table_blocks(blocks, 263, 263, "其他权益工具投资")
    real_rows = materialize_rows(selected, infer_columns(selected), parent_table="其他权益工具投资")
    recovered = next(item for item in real_rows if item.row_role == "IMPLICIT_TOTAL" and [cell.parsed_number for cell in item.cells] == [609550.0, 356493.0])
    assert recovered.raw_item is None
    assert recovered.row_item_normalized == "其他权益工具投资总额"
    assert recovered.derived_from_rows == ["上市", "非上市"]
    print("REAL_PDF_OTHER_EQUITY_INVESTMENT_PASS")


if __name__ == "__main__":
    main()
