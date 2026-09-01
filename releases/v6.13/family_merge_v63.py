"""v6.3 family merge: dual-axis union with explicit table identities."""
from __future__ import annotations
import json
from typing import Any
import pandas as pd
from period_identity import normalize_period_fields

OBSERVATION_KEY = ["company", "report_year", "table_family", "member_table", "row_path", "period_identity", "scope", "restated", "period_type", "unit"]
COLUMN_DIMENSIONS = ["period_identity", "period_label", "period_year", "period_month", "period_day", "period_precision", "period_date", "data_year", "scope", "restated", "period_type", "unit"]

def _with_period_identity(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    rows = [
        normalize_period_fields(
            source_period_label=row.get("source_period_label"),
            period_label=row.get("period_label"),
            year=row.get("year", row.get("data_year")),
        )
        for _, row in out.iterrows()
    ]
    period = pd.DataFrame(rows, index=out.index)
    for column in [
        "period_identity", "period_label", "period_year", "period_month",
        "period_day", "period_precision", "period_date",
    ]:
        if column not in out or out[column].isna().all():
            out[column] = period[column]
    if "data_year" not in out:
        out["data_year"] = out["period_year"]
    return out

def enrich_family_identity(df: pd.DataFrame, *, table_family: str, member_table: str, source_table_title: str = "", note_reference: str = "") -> pd.DataFrame:
    out = df.copy()
    out["table_family"] = table_family
    out["member_table"] = member_table
    out["source_table_title"] = source_table_title or member_table
    out["note_reference"] = note_reference
    out["row_path"] = out.get("row_path", out.get("normalized_item", "")).fillna("").astype(str)
    prefix = f"{member_table} / "
    out["row_path"] = out["row_path"].map(lambda x: x if x.startswith(prefix) else prefix + x)
    return out

def family_merge_long(frames: list[pd.DataFrame]) -> tuple[pd.DataFrame, pd.DataFrame]:
    data = pd.concat(frames, ignore_index=True, sort=False) if frames else pd.DataFrame()
    if data.empty:
        return data, pd.DataFrame(columns=["conflict_status", "conflict_severity"])
    data = _with_period_identity(data)
    for c in OBSERVATION_KEY:
        if c not in data: data[c] = "" if c != "restated" else False
    data["value"] = pd.to_numeric(data.get("value"), errors="coerce")
    grouped = data.groupby(OBSERVATION_KEY, dropna=False, sort=False)
    conflicts=[]; keep=[]
    for key, group in grouped:
        values=group["value"].dropna().unique()
        if len(values)>1:
            conflicts.append(dict(zip(OBSERVATION_KEY,key)) | {"conflict_status":"VALUE_CONFLICT", "conflict_severity":"BLOCKING", "values_json":json.dumps(values.tolist())})
        else:
            keep.append(group.iloc[0])
    return pd.DataFrame(keep).reset_index(drop=True), pd.DataFrame(conflicts)

def column_dimension_map(long_df: pd.DataFrame) -> pd.DataFrame:
    long_df = _with_period_identity(long_df)
    rows=[]
    for ordinal, key in enumerate(long_df[COLUMN_DIMENSIONS].drop_duplicates().itertuples(index=False, name=None), 1):
        entry=dict(zip(COLUMN_DIMENSIONS,key)); entry["column_id"]=f"C{ordinal:04d}"; rows.append(entry)
    return pd.DataFrame(rows)

def research_wide(long_df: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    dims=column_dimension_map(long_df)
    if long_df.empty: return long_df, dims
    merge=long_df.merge(dims,on=COLUMN_DIMENSIONS,how="left")
    index=[c for c in ["table_family","member_table","row_path","item","row_type"] if c in merge]
    wide=merge.pivot_table(index=index,columns="column_id",values="value",aggfunc="first",sort=False).reset_index()
    return wide, dims
