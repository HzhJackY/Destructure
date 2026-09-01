"""Deterministic final observation-column checks; never changes values."""
from __future__ import annotations

import re
from typing import Any


def _columns(result:dict[str,Any])->list[dict[str,Any]]:
    raw=result.get("columns") or []
    out=[]
    for index,column in enumerate(raw):
        if isinstance(column,dict):
            out.append({"column_index":index,**column})
        else:
            out.append({"column_index":index,"raw_header_path":str(column)})
    return out


def _row_values(row:dict[str,Any])->list[Any]:
    values=row.get("values")
    if isinstance(values,dict): return list(values.values())
    if isinstance(values,list): return values
    cells=row.get("value_cells")
    if isinstance(cells,list): return [x.get("raw_value") if isinstance(x,dict) else x for x in cells]
    # Spatial/structured captures store observations in ``cells``.  The final
    # review previously only understood legacy ``values``/``value_cells`` and
    # therefore reported 0/N last-column tokens for otherwise complete tables.
    cells=row.get("cells")
    if isinstance(cells,list):
        ordered=sorted(
            cells,
            key=lambda cell:int(cell.get("column_ordinal") or 0)
            if isinstance(cell,dict) else 0,
        )
        return [
            (
                cell.get("raw")
                if cell.get("raw") is not None
                else cell.get("raw_value")
                if cell.get("raw_value") is not None
                else cell.get("parsed_number")
            )
            if isinstance(cell,dict) else cell
            for cell in ordered
        ]
    return [row.get("value")] if row.get("value") is not None else []


def review_final_data_columns(result:dict[str,Any])->dict[str,Any]:
    columns=_columns(result); rows=list(result.get("rows") or [])
    data_columns=[x for x in columns if str(x.get("role") or x.get("column_role") or "VALUE").upper() not in {"ITEM","LABEL","NOTE_REFERENCE"}]
    issues=[]; mappings=[]
    for column in data_columns:
        header=str(column.get("raw_header_path") or column.get("header_path") or column.get("label") or "")
        mappings.append({
            "column_index":column["column_index"],"raw_header_path":header,
            "canonical_header_path":column.get("canonical_header_path") or header,
            "data_year":column.get("data_year") or column.get("year"),
            "period_type":column.get("period_type"),"statement_scope":column.get("statement_scope") or column.get("scope"),
            "unit":column.get("unit") or column.get("currency_unit"),"measure":column.get("measure") or "VALUE",
            "bbox":column.get("bbox"),"review_status":column.get("review_status") or "MACHINE",
        })
    expected=len(data_columns)
    mismatch_rows=[]
    contamination=[]
    for row in rows:
        values=_row_values(row)
        if expected and values and len(values)!=expected:
            mismatch_rows.append(row.get("row_order") or row.get("row_id"))
        for value in values:
            token=str(value or "").strip()
            if re.fullmatch(r"20\d{2}",token):
                contamination.append({"row":row.get("row_order"),"token":token})
    if mismatch_rows:
        issues.append({
            "reason_code":"VALUE_COLUMN_COUNT_MISMATCH","severity":"HIGH","blocking":True,
            "evidence":{"rows":mismatch_rows[:50],"expected_columns":expected},
        })
    if contamination:
        issues.append({
            "reason_code":"NUMERIC_TOKEN_ORIGIN_AMBIGUOUS","severity":"HIGH","blocking":True,
            "evidence":{"year_like_tokens":contamination[:50]},
        })
    years=[str(x.get("data_year") or "") for x in mappings if x.get("data_year")]
    if len(years)>=2 and years!=sorted(years,reverse=True):
        issues.append({
            "reason_code":"PERIOD_COLUMN_SWAP_RISK","severity":"HIGH","blocking":True,
            "evidence":{"observed_year_order":years},
        })
    last=data_columns[-1] if data_columns else None
    # IMPLICIT_TOTAL is a derived accounting row, not an independently
    # observed PDF data row.  Requiring a source token in every value column
    # creates false 0/N last-column failures for recovered totals.
    applicable_rows=[
        row for row in rows
        if str(row.get("row_role") or row.get("row_type") or "").upper()
        not in {"IMPLICIT_TOTAL","DERIVED_TOTAL"}
        and bool(_row_values(row))
    ]
    excluded_derived_rows=sum(
        str(row.get("row_role") or row.get("row_type") or "").upper()
        in {"IMPLICIT_TOTAL","DERIVED_TOTAL"}
        for row in rows
    )
    excluded_non_value_rows=sum(
        not _row_values(row)
        and str(row.get("row_role") or row.get("row_type") or "").upper()
        not in {"IMPLICIT_TOTAL","DERIVED_TOTAL"}
        for row in rows
    )
    last_tokens=0
    if last:
        last_position=max(0,expected-1)
        last_tokens=sum(
            len(_row_values(row))>last_position
            for row in applicable_rows if _row_values(row)
        )
    not_applicable=bool(last and rows and not applicable_rows and excluded_derived_rows)
    last_ok=bool(
        not_applicable or
        (last and applicable_rows and last_tokens>0 and
         (not expected or last_tokens>=max(1,int(len(applicable_rows)*0.5))))
    )
    if not last_ok:
        issues.append({
            "reason_code":"LAST_COLUMN_MAPPING_UNCERTAIN","severity":"HIGH","blocking":True,
            "evidence":{
                "last_column":last,"rows_with_last_token":last_tokens,
                "row_count":len(applicable_rows),"excluded_derived_rows":excluded_derived_rows,
                "excluded_non_value_rows":excluded_non_value_rows,
                "expected_value_columns":expected,
            },
        })
    observations=[]
    for row in rows:
        values=_row_values(row)
        for index,value in enumerate(values):
            mapping=mappings[index] if index<len(mappings) else {}
            observations.append({
                "raw_item":row.get("raw_item"),"normalized_item":row.get("normalized_item"),
                "row_path":row.get("row_path"),"row_role":row.get("row_role") or row.get("row_type"),
                **mapping,"raw_value":value,
                "normalized_value":value,"value_yuan":None,
                "source_page":row.get("source_page") or row.get("page"),
                "bbox":row.get("bbox"),"warnings":[],
                "review_status":"REVIEW_REQUIRED" if index>=len(mappings) else "MACHINE",
            })
    return {
        "column_mappings":mappings,"observations":observations,"issues":issues,
        "last_column_check":{
            "status":"NOT_APPLICABLE" if not_applicable else ("PASS" if last_ok else "REVIEW_REQUIRED"),
            "last_column":last,"rows_with_last_token":last_tokens,
            "row_count":len(applicable_rows),"excluded_derived_rows":excluded_derived_rows,
            "excluded_non_value_rows":excluded_non_value_rows,
        },
    }
