#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Header-dimension adjudication for v5.5.

Machine-detected columns remain in table_capture_result.json["columns"].
Human corrections are stored separately in header_review.json / header_review.

Official table_raw_* outputs are rematerialized from the same immutable row/cell
evidence with corrected year/scope/restated dimensions.
"""

from __future__ import annotations

import datetime as dt
import json
from pathlib import Path
from typing import Any

import pandas as pd

from table_capture import (
    TableColumn,
    TableCell,
    TableRow,
    TableCaptureResult,
    analyze_column_dimensions,
    capture_to_long_df,
    capture_to_wide_df,
)


HEADER_MERGE_READY_STATUSES = {"AUTO_CONFIRMED", "HUMAN_CONFIRMED"}


def load_result(run_dir: Path) -> dict[str, Any]:
    return json.loads((Path(run_dir) / "table_capture_result.json").read_text(encoding="utf-8"))


def save_result(run_dir: Path, data: dict[str, Any]) -> None:
    (Path(run_dir) / "table_capture_result.json").write_text(
        json.dumps(data, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def derive_header_dimension_status(result: dict[str, Any]) -> str:
    explicit = str(result.get("header_dimension_status") or "").strip()
    if explicit and explicit != "UNASSESSED":
        return explicit
    return analyze_column_dimensions(topology_filtered_machine_columns(result))["status"]


def topology_active_ordinals(result: dict[str, Any]) -> Optional[set[int]]:
    review=result.get("column_topology_review") or {}
    if str(review.get("status") or "")!="HUMAN_CONFIRMED":
        return None
    active=review.get("active_ordinals")
    if active is None:
        return None
    return {int(x) for x in active}


def topology_filtered_machine_columns(result: dict[str, Any]) -> list[dict[str, Any]]:
    cols=list(result.get("columns") or [])
    active=topology_active_ordinals(result)
    if active is None:
        return cols
    return [c for c in cols if int(c.get("ordinal",0)) in active]


def effective_columns(result: dict[str, Any]) -> list[dict[str, Any]]:
    review = result.get("header_review") or {}
    reviewed = review.get("columns")
    if reviewed:
        return reviewed
    return topology_filtered_machine_columns(result)


def _result_dataclass(
    result: dict[str, Any],
    columns_data: list[dict[str, Any]],
) -> TableCaptureResult:
    columns = [
        TableColumn(
            ordinal=int(c.get("ordinal", i)),
            source_column_index=int(c.get("source_column_index", i + 1)),
            header_raw=str(c.get("header_raw") or ""),
            year=(str(c.get("year")).strip() if c.get("year") is not None else None),
            scope=(str(c.get("scope")).strip() if c.get("scope") not in [None, ""] else None),
            restated=bool(c.get("restated")),
            period_label=(
                str(c.get("period_label")).strip()
                if c.get("period_label") not in [None, ""]
                else (str(c.get("year")).strip() if c.get("year") is not None else None)
            ),
        )
        for i, c in enumerate(columns_data)
    ]

    allowed_ordinals={int(c.ordinal) for c in columns}
    rows = []
    for r in result.get("rows") or []:
        cells = [
            TableCell(
                column_ordinal=int(c.get("column_ordinal", 0)),
                source_column_index=int(c.get("source_column_index", int(c.get("column_ordinal", 0)) + 1)),
                raw=str(c.get("raw") or ""),
                parsed_number=c.get("parsed_number"),
                unit_original=c.get("unit_original"),
                value_yuan=c.get("value_yuan"),
            )
            for c in (r.get("cells") or [])
            if int(c.get("column_ordinal",0)) in allowed_ordinals
        ]
        rows.append(TableRow(
            row_order=int(r.get("row_order")),
            page=int(r.get("page")),
            block_id=str(r.get("block_id") or ""),
            source_method=str(r.get("source_method") or ""),
            raw_item=str(r.get("raw_item") or ""),
            normalized_item=str(r.get("normalized_item") or ""),
            canonical_item=r.get("canonical_item"),
            mapping_status=str(r.get("mapping_status") or "UNMAPPED"),
            row_type=str(r.get("row_type") or "DETAIL"),
            row_level=int(r.get("row_level") or 0),
            parent_section=r.get("parent_section"),
            cells=cells,
            header_source_page=r.get("header_source_page"),
        ))

    return TableCaptureResult(
        pdf_name=str(result.get("pdf_name") or ""),
        pdf_sha256=str(result.get("pdf_sha256") or ""),
        table_query=str(result.get("table_query") or ""),
        note_number=result.get("note_number"),
        located_title=str(result.get("located_title") or ""),
        start_page=int(result.get("start_page") or 1),
        end_page=int(result.get("end_page") or 1),
        pages=[int(x) for x in (result.get("pages") or [])],
        unit=result.get("unit"),
        columns=columns,
        rows=rows,
        warnings=list(result.get("warnings") or []),
        stats=dict(result.get("stats") or {}),
        boundary_status=str(result.get("boundary_status") or "UNASSESSED"),
        boundary_review=result.get("boundary_review"),
        header_dimension_status=str(result.get("header_dimension_status") or "UNASSESSED"),
        header_review=result.get("header_review"),
    )


def _dictionary_from_long(long_df: pd.DataFrame) -> pd.DataFrame:
    if long_df.empty:
        return pd.DataFrame(columns=[
            "normalized_item", "example_raw_item", "canonical_item",
            "category", "mapping_status", "mapping_note",
        ])
    work = long_df.copy()
    if "row_type" in work:
        work = work[work["row_type"].astype(str) != "SECTION_HEADER"]
    rows = []
    seen = set()
    for _, row in work.iterrows():
        norm = str(row.get("normalized_item") or "").strip()
        if not norm or norm in seen:
            continue
        seen.add(norm)
        rows.append({
            "normalized_item": norm,
            "example_raw_item": row.get("raw_item"),
            "canonical_item": "",
            "category": "",
            "mapping_status": "UNMAPPED",
            "mapping_note": "",
        })
    return pd.DataFrame(rows)


def rematerialize_official_capture(run_dir: Path) -> dict[str, int]:
    """
    Rebuild official outputs using effective header dimensions and current
    boundary adjudication. Machine-full CSVs are never overwritten.
    """
    run_dir = Path(run_dir)
    result = load_result(run_dir)
    result_dc = _result_dataclass(result, effective_columns(result))

    full_long = capture_to_long_df(result_dc)
    full_wide = capture_to_wide_df(result_dc)

    cutoff = None
    boundary_review = result.get("boundary_review") or {}
    if str(boundary_review.get("status")) == "HUMAN_CONFIRMED":
        cutoff = boundary_review.get("last_included_row_order")

    if cutoff is not None:
        cutoff = int(cutoff)
        long_orders = pd.to_numeric(full_long["row_order"], errors="coerce")
        official_long = full_long[long_orders <= cutoff].copy()
        excluded = full_long[long_orders > cutoff].copy()
        if "row_order" in full_wide:
            wide_orders = pd.to_numeric(full_wide["row_order"], errors="coerce")
            official_wide = full_wide[wide_orders <= cutoff].copy()
        else:
            official_wide = full_wide.copy()
    else:
        official_long = full_long.copy()
        official_wide = full_wide.copy()
        excluded = pd.DataFrame(columns=full_long.columns)

    dictionary = _dictionary_from_long(official_long)

    official_long.to_csv(run_dir / "table_raw_long.csv", index=False, encoding="utf-8-sig")
    official_wide.to_csv(run_dir / "table_raw_wide.csv", index=False, encoding="utf-8-sig")
    dictionary.to_csv(run_dir / "table_item_dictionary.csv", index=False, encoding="utf-8-sig")
    excluded.to_csv(run_dir / "boundary_excluded_rows.csv", index=False, encoding="utf-8-sig")

    from reconciliation import reconciliation_audit_from_long
    reconciliation = reconciliation_audit_from_long(official_long)
    reconciliation.to_csv(
        run_dir / "table_reconciliation_audit.csv",
        index=False,
        encoding="utf-8-sig",
    )

    machine_long = (
        pd.read_csv(run_dir / "machine_capture_full_long.csv")
        if (run_dir / "machine_capture_full_long.csv").exists()
        else pd.DataFrame()
    )
    machine_wide = (
        pd.read_csv(run_dir / "machine_capture_full_wide.csv")
        if (run_dir / "machine_capture_full_wide.csv").exists()
        else pd.DataFrame()
    )
    parser_candidates = pd.DataFrame()
    parser_candidates_path = run_dir / "header_parser_candidates.csv"
    if parser_candidates_path.exists() and parser_candidates_path.stat().st_size > 3:
        try:
            parser_candidates = pd.read_csv(parser_candidates_path)
        except pd.errors.EmptyDataError:
            parser_candidates = pd.DataFrame()
    arbitration = (result.get("stats") or {}).get("header_arbitration") or {}
    topology_review = result.get("column_topology_review") or {}

    with pd.ExcelWriter(run_dir / "table_capture.xlsx", engine="openpyxl") as writer:
        official_long.to_excel(writer, sheet_name="raw_long", index=False)
        official_wide.to_excel(writer, sheet_name="raw_wide", index=False)
        dictionary.to_excel(writer, sheet_name="item_dictionary", index=False)
        machine_long.to_excel(writer, sheet_name="machine_full_long", index=False)
        machine_wide.to_excel(writer, sheet_name="machine_full_wide", index=False)
        excluded.to_excel(writer, sheet_name="boundary_excluded", index=False)

        machine_cols = pd.DataFrame(result.get("columns") or [])
        effective_cols = pd.DataFrame(effective_columns(result))
        machine_cols.to_excel(writer, sheet_name="machine_headers", index=False)
        effective_cols.to_excel(writer, sheet_name="effective_headers", index=False)
        reconciliation.to_excel(writer, sheet_name="reconciliation", index=False)
        parser_candidates.to_excel(writer, sheet_name="header_candidates", index=False)
        pd.DataFrame([{
            "mode": arbitration.get("mode"),
            "auto_selected_parser": arbitration.get("auto_selected_parser"),
            "selected_parser": arbitration.get("selected_parser"),
            "selection_reason": arbitration.get("selection_reason"),
            "auto_abstain": arbitration.get("auto_abstain"),
        }]).to_excel(writer, sheet_name="header_arbitration", index=False)
        pd.DataFrame(topology_review.get("actions") or []).to_excel(
            writer, sheet_name="topology_review", index=False
        )

    return {
        "official_long_rows": int(len(official_long)),
        "official_table_rows": int(official_long["row_order"].nunique()) if "row_order" in official_long else 0,
        "excluded_long_rows": int(len(excluded)),
    }


def apply_header_dimension_review(
    run_dir: Path,
    edited_columns: list[dict[str, Any]],
    reviewer_note: str = "",
) -> dict[str, Any]:
    run_dir = Path(run_dir)
    result = load_result(run_dir)

    # Preserve physical identity/order. User edits only dimensions.
    # If topology review dropped false duplicate columns, only active columns
    # participate in the dimension review.
    machine_cols = sorted(
        topology_filtered_machine_columns(result),
        key=lambda c: int(c.get("ordinal", 0)),
    )
    edited_by_ordinal = {int(c["ordinal"]): c for c in edited_columns}
    reviewed = []

    for machine in machine_cols:
        ordinal = int(machine.get("ordinal", 0))
        edited = edited_by_ordinal.get(ordinal)
        if edited is None:
            raise ValueError(f"缺少逻辑列 ordinal={ordinal} 的复核结果。")

        year = str(edited.get("year") or "").strip()
        scope = str(edited.get("scope") or "").strip()
        restated = bool(edited.get("restated"))
        if not year:
            raise ValueError(f"col{ordinal} 的 year 不能为空。")

        tokens = [x for x in [scope, year, "已重述" if restated else ""] if x]
        reviewed.append({
            "ordinal": ordinal,
            "source_column_index": int(machine.get("source_column_index", ordinal + 1)),
            "header_raw": " | ".join(tokens),
            "machine_header_raw": machine.get("header_raw"),
            "year": year,
            "scope": scope or None,
            "restated": restated,
            "period_label": year,
        })

    check = analyze_column_dimensions(reviewed)
    if check["issues"]:
        issue_text = "; ".join(str(x.get("issue")) for x in check["issues"])
        raise ValueError(
            "复核后的列维度仍不唯一，不能确认：" + issue_text
        )

    review = {
        "status": "HUMAN_CONFIRMED",
        "columns": reviewed,
        "reviewed_at": dt.datetime.now().isoformat(timespec="seconds"),
        "reviewer_note": str(reviewer_note or ""),
        "dimension_check": check,
    }
    (run_dir / "header_review.json").write_text(
        json.dumps(review, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    result["header_dimension_status"] = "HUMAN_CONFIRMED"
    result["header_review"] = review
    save_result(run_dir, result)
    materialized = rematerialize_official_capture(run_dir)
    return {**review, **materialized}


def reset_header_dimension_review(run_dir: Path) -> dict[str, Any]:
    run_dir = Path(run_dir)
    result = load_result(run_dir)
    result["header_review"] = None
    check = analyze_column_dimensions(topology_filtered_machine_columns(result))
    result["header_dimension_status"] = check["status"]
    stats = dict(result.get("stats") or {})
    stats["header_dimension_check"] = check
    result["stats"] = stats
    save_result(run_dir, result)
    (run_dir / "header_review.json").unlink(missing_ok=True)
    rematerialize_official_capture(run_dir)
    return check
