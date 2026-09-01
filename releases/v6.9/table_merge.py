#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
table_merge.py — v5.1 multi-company / multi-year table merge engine.

Safety model:
- raw capture rows are immutable evidence.
- exact normalized identities may auto-align.
- non-identical labels are NEVER silently merged.
- fuzzy similarity is suggestion-only.
- confirmed mappings can be persisted to a table taxonomy.
- duplicate/conflicting canonical keys are surfaced, not silently overwritten.
"""

from __future__ import annotations

import difflib
import json
import os
import re
import tempfile
from pathlib import Path
from typing import Any, Optional

import pandas as pd

from batch_pipeline import infer_company_year
from financial_metric_pdf_resolver import normalize_text
from financial_structure_resolver import ensure_row_paths
from visible_header_policy import VisibleHeaderDimensionPolicy, OBSERVATION_DIMENSIONS


TAXONOMY_VERSION = 1

# A Family Merge observation is source-aware before it is row-aware.  These
# fields intentionally survive all long/canonical/wide materializations.
SOURCE_IDENTITY_COLUMNS = [
    "table_family", "member_table", "member_table_role",
    "source_table_title", "note_reference", "capture_run_id", "source_pdf",
]


def _identity_text(value: Any) -> str:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return ""
    text = str(value).strip()
    return "" if text.lower() in {"nan", "none", "<na>"} else text


def _source_identity_missing(row: Any) -> bool:
    return not all(_identity_text(row.get(field)) for field in (
        "table_family", "member_table", "member_table_role",
    ))


def normalize_table_id(text: str) -> str:
    s = normalize_text(str(text or ""))
    return s or "UNNAMED_TABLE"


def normalize_section(text: Any) -> str:
    if text is None or (isinstance(text, float) and pd.isna(text)):
        return ""
    return re.sub(r"\s+", "", str(text)).strip("：:")


def source_mapping_key(parent_section: Any, normalized_item: Any) -> str:
    """Legacy key retained for taxonomy compatibility."""
    return f"{normalize_section(parent_section)}||{str(normalized_item or '').strip()}"


def assign_conditional_source_keys(df: pd.DataFrame) -> pd.DataFrame:
    """
    v5.6 identity policy:
    - if an item name appears only once in a source table, identity is the item
      name itself; parent_section is context, not a primary key.
    - only when the same normalized_item appears multiple times in the SAME
      source table do we activate contextual disambiguation using parent_section,
      row_type, and local occurrence order.

    This prevents harmless parent-section parsing differences across companies
    from blocking exact-name merges.
    """
    out = ensure_row_paths(df)
    out["source_key"] = ""
    if out.empty:
        return out

    # One structural record per original row, ignoring repeated period/value rows.
    structural = (
        out[["row_order","normalized_item","parent_section","row_type"]]
        .drop_duplicates(subset=["row_order"], keep="first")
        .copy()
    )
    structural["normalized_item"] = structural["normalized_item"].fillna("").astype(str).str.strip()
    structural["_row_order_num"] = pd.to_numeric(structural["row_order"], errors="coerce")
    structural = structural.sort_values("_row_order_num", kind="stable")

    for item, g in structural.groupby("normalized_item", sort=False):
        if not item:
            continue
        rows = g["row_order"].tolist()
        if len(rows) == 1:
            key = f"UNIQUE||{item}"
            out.loc[out["row_order"].isin(rows), "source_key"] = key
            continue

        # Same name occurs more than once in the same source: context is now
        # required. Occurrence index prevents accidental collapse even if two
        # repeated rows also share the same parent text.
        for occurrence, (_, r) in enumerate(g.iterrows(), start=1):
            parent = normalize_section(r.get("parent_section"))
            row_path = str(r.get("row_path") or "").strip()
            row_type = str(r.get("row_type") or "").strip()
            # v6.2: repeated names are identities only with their full derived
            # row path.  This prevents e.g. two "交易性金融资产" rows under
            # 股息收入 and 利息收入 from collapsing.
            key = f"CONTEXT_PATH||{item}||{row_path or parent}||{row_type}||OCC{occurrence}"
            out.loc[out["row_order"] == r["row_order"], "source_key"] = key

    # Fallback for unusual rows without normalized item.
    missing = out["source_key"].astype(str).str.len() == 0
    out.loc[missing, "source_key"] = out.loc[missing].apply(
        lambda r: f"LEGACY||{source_mapping_key(r.get('parent_section'), r.get('normalized_item'))}",
        axis=1,
    )
    return out


def _atomic_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=path.name + ".", suffix=".tmp", dir=str(path.parent))
    os.close(fd)
    tmp = Path(tmp_name)
    try:
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(tmp, path)
    finally:
        tmp.unlink(missing_ok=True)


def load_taxonomy(path: Path) -> dict[str, Any]:
    path = Path(path)
    if not path.exists():
        return {"version": TAXONOMY_VERSION, "tables": {}}
    data = json.loads(path.read_text(encoding="utf-8"))
    data.setdefault("version", TAXONOMY_VERSION)
    data.setdefault("tables", {})
    return data


def _taxonomy_lookup(taxonomy: dict[str, Any], table_id: str) -> dict[str, dict[str, Any]]:
    table = taxonomy.get("tables", {}).get(table_id, {})
    mappings = table.get("mappings", [])
    lookup: dict[str, dict[str, Any]] = {}

    # Exact stored keys.
    for m in mappings:
        for alias_key in m.get("source_keys", []):
            lookup[str(alias_key)] = m

    # Backward compatibility: old versions stored parent_section||item. For a
    # v5.6 UNIQUE||item key, reuse an old mapping only if all legacy mappings for
    # that item point to the same canonical target.
    by_item: dict[str, list[dict[str, Any]]] = {}
    for m in mappings:
        for alias_key in m.get("source_keys", []):
            key = str(alias_key)
            if key.startswith("UNIQUE||"):
                item = key.split("||",1)[1]
            elif "||" in key and not key.startswith("CONTEXT||"):
                item = key.split("||")[-1]
            else:
                continue
            by_item.setdefault(item, []).append(m)

    for item, candidates in by_item.items():
        targets = {
            (
                str(m.get("canonical_section") or ""),
                str(m.get("canonical_item") or ""),
            )
            for m in candidates
        }
        if len(targets) == 1:
            lookup.setdefault(f"UNIQUE||{item}", candidates[0])

    return lookup

def infer_capture_metadata(capture_dir: Path) -> dict[str, Any]:
    result_path = capture_dir / "table_capture_result.json"
    data = json.loads(result_path.read_text(encoding="utf-8"))
    pdf_name = data.get("pdf_name", "")
    company, filename_year = infer_company_year(Path(pdf_name), "")

    # v5.8: report/document_year must be an absolute four-digit year.
    # Relative column labels such as 本年累计数 / 上年累计数 / 去年累计数
    # are never valid document identity.
    absolute_candidates = []
    if re.fullmatch(r"20\d{2}", str(filename_year or "").strip()):
        absolute_candidates.append(str(filename_year).strip())

    for c in data.get("columns", []) or []:
        for field in ["year", "period_label", "header_raw"]:
            value = str(c.get(field) or "").strip()
            m = re.search(r"(20\d{2})", value)
            if m:
                absolute_candidates.append(m.group(1))

    document_year = max(absolute_candidates) if absolute_candidates else ""
    capture_meta_path = capture_dir / "capture_metadata.json"
    try:
        capture_meta = json.loads(capture_meta_path.read_text(encoding="utf-8")) if capture_meta_path.exists() else {}
    except (OSError, json.JSONDecodeError):
        capture_meta = {}
    stats = data.get("stats") or {}
    return {
        "capture_run_id": capture_dir.name,
        "capture_dir": str(capture_dir),
        "pdf_name": pdf_name,
        "pdf_sha256": data.get("pdf_sha256"),
        "company": company,
        "document_year": document_year,
        "table_query": data.get("table_query", ""),
        "note_number": data.get("note_number"),
        "located_title": data.get("located_title", ""),
        "table_family": capture_meta.get("table_family"),
        "member_table": capture_meta.get("member_table"),
        "member_table_role": capture_meta.get("member_table_role"),
        "source_table_title": capture_meta.get("source_table_title"),
        "note_reference": capture_meta.get("note_reference"),
        "source_pdf": capture_meta.get("source_pdf_path") or stats.get("source_pdf_path") or pdf_name,
        "member_table_order": capture_meta.get("member_table_order"),
    }


CURRENT_RELATIVE_PERIOD_TOKENS = {
    "本年累计数", "本年度累计数", "本期累计数", "本期数", "本年数",
    "本期", "本年", "本年度", "当期累计数", "当期",
    "期末", "年末", "本期期末", "本年末", "本年度末",
}
PRIOR_RELATIVE_PERIOD_TOKENS = {
    "上年累计数", "上年度累计数", "上期累计数", "上期数", "上年数",
    "上期", "上年", "上年度", "去年", "去年累计数", "去年数",
    "去年同期", "上年同期", "上年度同期", "上期同期",
}


def _is_missing_scalar(value: Any) -> bool:
    if value is None:
        return True
    try:
        return bool(pd.isna(value))
    except (TypeError, ValueError):
        return False


def _clean_scalar_text(value: Any) -> str:
    if _is_missing_scalar(value):
        return ""
    return str(value).strip()


def _clean_period_token(value: Any) -> str:
    token = _clean_scalar_text(value)
    if re.fullmatch(r"20\d{2}\.0", token):
        return token[:4]
    token = re.sub(r"\s+", "", token)
    token = token.replace("（", "(").replace("）", ")")
    token = re.sub(r"\(?(?:已重述|经重述|重述后|重述)\)?", "", token)
    token = re.sub(r"(?:人民币)?(?:亿元|百万元|万元|千元|元)$", "", token)
    return token.strip()


def _absolute_year(value: Any) -> Optional[str]:
    token = _clean_period_token(value)
    # CSV round trips commonly turn a year into `2022.0`.  It remains an
    # absolute reporting period, not a distinct observation dimension.
    m = re.fullmatch(r"(20\d{2})(?:\.0)?(?:年度|年)?", token)
    return m.group(1) if m else None


def _relative_period_kind(value: Any) -> Optional[str]:
    token = _clean_period_token(value)
    if token in CURRENT_RELATIVE_PERIOD_TOKENS:
        return "CURRENT"
    if token in PRIOR_RELATIVE_PERIOD_TOKENS:
        return "PRIOR"
    return None


def _infer_document_year_from_capture_source(
    *,
    pdf_name: Any = "",
    capture_dir: Any = "",
    columns: Optional[list[dict[str, Any]]] = None,
) -> str:
    """Infer report year from absolute evidence only."""
    _, filename_year = infer_company_year(Path(str(pdf_name or "")), "")
    y = _absolute_year(filename_year)
    if y:
        return y

    absolute_candidates: list[str] = []
    for c in columns or []:
        for field in ["year", "period_label", "header_raw"]:
            y = _absolute_year(c.get(field))
            if y:
                absolute_candidates.append(y)
    if absolute_candidates:
        return max(absolute_candidates)

    cap = Path(str(capture_dir or ""))
    result_path = cap / "table_capture_result.json"
    if result_path.exists():
        try:
            data = json.loads(result_path.read_text(encoding="utf-8"))
            _, filename_year = infer_company_year(Path(str(data.get("pdf_name") or "")), "")
            y = _absolute_year(filename_year)
            if y:
                return y
            for c in data.get("columns") or []:
                for field in ["year", "period_label", "header_raw"]:
                    y = _absolute_year(c.get(field))
                    if y:
                        absolute_candidates.append(y)
            if absolute_candidates:
                return max(absolute_candidates)
        except Exception:
            pass
    return ""


def _resolve_source_document_year(source: dict[str, Any]) -> str:
    existing = _absolute_year(source.get("document_year"))
    if existing:
        return existing
    return _infer_document_year_from_capture_source(
        pdf_name=source.get("pdf_name"),
        capture_dir=source.get("capture_dir"),
    )


def _resolve_relative_period_years(
    df: pd.DataFrame,
    document_year: Any,
) -> pd.DataFrame:
    """
    Convert relative period labels to actual years before canonical merge.

    document_year=2023:
      本年 / 本年累计数 / 本期累计数 -> 2023
      去年 / 去年累计数 / 上年累计数 / 上期累计数 -> 2022

    Original wording is retained in `source_period_label`.
    """
    out = df.copy()
    if "year" not in out.columns:
        return out

    doc = _absolute_year(document_year)

    if "source_period_label" not in out.columns:
        if "period_label" in out.columns:
            out["source_period_label"] = out["period_label"]
        else:
            out["source_period_label"] = out["year"]

    def resolve(value: Any) -> Any:
        absolute = _absolute_year(value)
        if absolute:
            return absolute
        kind = _relative_period_kind(value)
        if kind is None or doc is None:
            return value
        return doc if kind == "CURRENT" else str(int(doc) - 1)

    out["year"] = out["year"].map(resolve)

    if "column_dimension_key" in out.columns:
        def dimension_key(r: pd.Series) -> Any:
            if _is_missing_scalar(r.get("column_ordinal")):
                return r.get("column_dimension_key")
            restated_raw = r.get("restated")
            restated = False if _is_missing_scalar(restated_raw) else bool(restated_raw)
            return (
                f"{_clean_scalar_text(r.get('year'))}|"
                f"{_clean_scalar_text(r.get('scope'))}|"
                f"{'RESTATED' if restated else 'ORIGINAL'}"
            )

        out["column_dimension_key"] = out.apply(dimension_key, axis=1)
    return out


def _validate_absolute_year_resolution(
    df: pd.DataFrame,
    *,
    document_year: Any,
    capture_run_id: str,
) -> None:
    if "year" not in df.columns:
        return

    relative_values = sorted({
        str(v)
        for v in df["year"].dropna().tolist()
        if _relative_period_kind(v)
    })
    if not relative_values:
        return

    doc = _absolute_year(document_year)
    if not doc:
        raise ValueError(
            f"PERIOD_RESOLUTION_REQUIRED：来源 {capture_run_id} 包含相对期间 "
            f"{relative_values}，但报告年份 document_year 未识别为四位年份。"
            " 请在合表来源信息中填写该年报实际年份，例如 2023。"
            " 系统随后会自动将本年→2023、去年/上年→2022。"
        )

    raise ValueError(
        f"PERIOD_RESOLUTION_INVARIANT_VIOLATION：来源 {capture_run_id} "
        f"在 document_year={doc} 已知时仍残留相对 year={relative_values}。"
        " 已阻止其进入 canonical 合表。"
    )


def _repair_manifest_and_raw_periods(
    raw_long: pd.DataFrame,
    manifest: dict[str, Any],
) -> tuple[pd.DataFrame, dict[str, Any]]:
    """
    Repair existing v5.7 Merge Projects on rematerialization as well as new ones.
    """
    raw = raw_long.copy()
    # Legacy CSV projects commonly deserialize period identity columns as
    # int64.  v6.7 deliberately normalizes report/document years to canonical
    # strings so they can coexist with relative labels before resolution.  On
    # pandas 3, assigning "2023" into an int64 block is a hard TypeError.
    # Coerce only identity/presentation fields; financial value columns remain
    # untouched and no source amount is rewritten.
    for period_column in (
        "document_year", "report_year", "data_year", "year",
        "source_period_label",
    ):
        if period_column in raw.columns:
            raw[period_column] = raw[period_column].astype("string")
    manifest = dict(manifest)
    sources = [dict(s) for s in (manifest.get("sources") or [])]

    for source in sources:
        run_id = str(source.get("capture_run_id") or "")
        doc_year = _resolve_source_document_year(source)
        if doc_year:
            source["document_year"] = doc_year

        if "capture_run_id" not in raw.columns:
            continue
        mask = raw["capture_run_id"].astype(str) == run_id
        if not mask.any():
            continue

        if doc_year and "document_year" in raw.columns:
            raw.loc[mask, "document_year"] = doc_year

        repaired = _resolve_relative_period_years(
            raw.loc[mask].copy(),
            source.get("document_year"),
        )
        for col in repaired.columns:
            if col not in raw.columns:
                raw[col] = None
        raw.loc[mask, repaired.columns] = repaired.values

        _validate_absolute_year_resolution(
            raw.loc[mask],
            document_year=source.get("document_year"),
            capture_run_id=run_id,
        )

    manifest["sources"] = sources
    manifest["period_resolution_policy"] = (
        "RELATIVE_PERIOD_TO_ABSOLUTE_YEAR_BEFORE_CANONICAL_MERGE"
    )
    return raw, manifest


def load_capture_long(capture_dir: Path, metadata: dict[str, Any], table_id: str) -> pd.DataFrame:
    capture_meta_path = Path(capture_dir) / "capture_metadata.json"
    if capture_meta_path.exists():
        try:
            capture_meta = json.loads(capture_meta_path.read_text(encoding="utf-8"))
        except Exception:
            capture_meta = {}
        lifecycle = str(capture_meta.get("lifecycle_status") or "ACTIVE")
        if lifecycle != "ACTIVE":
            raise ValueError(
                f"CAPTURE_LIFECYCLE_BLOCKED：{Path(capture_dir).name} 当前状态={lifecycle}，"
                "不能进入正式 canonical Merge。请在数据资产管理中心恢复为 ACTIVE 后再合表。"
            )

    path = capture_dir / "table_raw_long.csv"
    if not path.exists():
        raise FileNotFoundError(f"缺少 {path}")
    df = pd.read_csv(path)
    if df.empty:
        return df

    # Preserve capture-layer mapping fields without colliding with merge-layer
    # canonicalization columns.
    rename_map = {}
    if "canonical_item" in df.columns:
        rename_map["canonical_item"] = "capture_canonical_item"
    if "mapping_status" in df.columns:
        rename_map["mapping_status"] = "capture_mapping_status"
    if "mapping_note" in df.columns:
        rename_map["mapping_note"] = "capture_mapping_note"
    if rename_map:
        df = df.rename(columns=rename_map)

    effective_document_year = (
        _absolute_year(metadata.get("document_year"))
        or _infer_document_year_from_capture_source(
            pdf_name=metadata.get("pdf_name"),
            capture_dir=capture_dir,
        )
        or ""
    )
    metadata["document_year"] = effective_document_year

    # Canonical Observation Contract v6.6: keep explicit source/report and
    # observation-period fields. Legacy aliases survive only for compatibility
    # with existing templates and resolvers.
    if "report_year" not in df.columns:
        df["report_year"] = effective_document_year
    else:
        df["report_year"] = effective_document_year
    if "data_year" not in df.columns:
        df["data_year"] = df.get("year", "")
    if "statement_scope" not in df.columns:
        df["statement_scope"] = df.get("scope", "")
    if "restated_flag" not in df.columns:
        df["restated_flag"] = df.get("restated", False)
    if "currency_unit" not in df.columns:
        unit_map = {
            "元": "CNY", "千元": "CNY_THOUSAND", "万元": "CNY_TEN_THOUSAND",
            "百万元": "CNY_MILLION", "亿元": "CNY_HUNDRED_MILLION", "%": "PERCENT",
        }
        df["currency_unit"] = df.get("unit", "").map(unit_map).fillna("")
    # Canonical scope values avoid mixing display labels with observation keys.
    df["statement_scope"] = df["statement_scope"].replace({"本集团": "CONSOLIDATED", "集团": "CONSOLIDATED", "本公司": "COMPANY", "公司": "COMPANY"})

    df.insert(0, "capture_run_id", metadata["capture_run_id"])
    df.insert(1, "company", metadata.get("company", ""))
    df.insert(2, "document_year", effective_document_year)
    df.insert(3, "table_id", table_id)
    # Do not infer this identity from a detail item later in canonicalization.
    # It is the semantic source of the entire Capture.
    df["table_family"] = _identity_text(metadata.get("table_family")) or str(table_id)
    df["member_table"] = _identity_text(metadata.get("member_table")) or _identity_text(metadata.get("table_query"))
    df["member_table_role"] = _identity_text(metadata.get("member_table_role")) or "COMPONENT"
    df["source_table_title"] = _identity_text(metadata.get("source_table_title")) or df["member_table"]
    df["note_reference"] = _identity_text(metadata.get("note_reference")) or _identity_text(metadata.get("note_number"))
    df["source_pdf"] = _identity_text(metadata.get("source_pdf")) or _identity_text(metadata.get("pdf_name"))
    df["member_table_order"] = metadata.get("member_table_order")
    if "period_type" not in df.columns:
        df["period_type"] = _identity_text(metadata.get("period_type")) or "ANNUAL"
    if "currency" not in df.columns:
        df["currency"] = _identity_text(metadata.get("currency"))

    # Keep legacy aliases synchronized after source metadata is authoritative.
    df["year"] = df["data_year"]
    df["scope"] = df["statement_scope"]
    df["restated"] = df["restated_flag"]

    df = _resolve_relative_period_years(df, effective_document_year)
    # The resolver canonicalises legacy `year`; make the explicit v6.6
    # observation field authoritative after that resolution as well.
    df["data_year"] = df["year"].map(lambda value: _absolute_year(value) or value)
    df["report_year"] = df["report_year"].map(lambda value: _absolute_year(value) or value)
    _validate_absolute_year_resolution(
        df,
        document_year=effective_document_year,
        capture_run_id=str(metadata["capture_run_id"]),
    )
    # Derived row-path metadata is computed from raw capture exports only.  It
    # never rewrites table_capture_result.json or machine evidence files.
    df = ensure_row_paths(df)
    df = assign_conditional_source_keys(df)
    return df


def build_mapping_queue(
    raw_long: pd.DataFrame,
    table_id: str,
    taxonomy: Optional[dict[str, Any]] = None,
) -> pd.DataFrame:
    taxonomy = taxonomy or {"tables": {}}
    lookup = _taxonomy_lookup(taxonomy, table_id)

    numeric = raw_long[raw_long["value"].notna()].copy()
    groups = []
    for source_key, g in numeric.groupby("source_key", sort=False):
        parent_section = normalize_section(g["parent_section"].iloc[0] if "parent_section" in g else "")
        normalized_item = str(g["normalized_item"].iloc[0] or "")
        companies = sorted({str(x) for x in g["company"].dropna().tolist() if str(x).strip()})
        raw_examples = []
        for x in g["raw_item"].dropna().tolist():
            sx = str(x)
            if sx not in raw_examples:
                raw_examples.append(sx)

        existing = lookup.get(source_key)
        if existing:
            canonical_section = existing.get("canonical_section", parent_section)
            canonical_item = existing.get("canonical_item", normalized_item)
            category = existing.get("category", "")
            status = "AUTO_TAXONOMY"
            suggested = canonical_item
            suggestion_score = 1.0
        else:
            canonical_section = parent_section
            canonical_item = normalized_item
            category = ""
            # Exact same normalized item/context across >=2 captures is safe identity alignment.
            capture_count = g["capture_run_id"].nunique()
            if capture_count >= 2:
                status = "AUTO_EXACT_IDENTITY"
            else:
                status = "UNMAPPED_PRESERVED"
            suggested = ""
            suggestion_score = None

        groups.append({
            "source_key": source_key,
            "parent_section": parent_section,
            "normalized_item": normalized_item,
            "occurrences": int(len(g)),
            "capture_count": int(g["capture_run_id"].nunique()),
            "companies": " | ".join(companies),
            "example_raw_items": " | ".join(raw_examples[:6]),
            "suggested_canonical_section": canonical_section,
            "suggested_canonical_item": suggested,
            "suggestion_score": suggestion_score,
            "canonical_section": canonical_section,
            "canonical_item": canonical_item,
            "category": category,
            "mapping_status": status,
            "mapping_note": "",
        })

    queue = pd.DataFrame(groups)
    if queue.empty:
        return queue

    # Suggest-only fuzzy matches among source labels and known taxonomy canonicals.
    candidates = set(queue["normalized_item"].astype(str).tolist())
    table_tax = taxonomy.get("tables", {}).get(table_id, {})
    for m in table_tax.get("mappings", []):
        if m.get("canonical_item"):
            candidates.add(str(m["canonical_item"]))

    for idx, row in queue.iterrows():
        if row["mapping_status"] != "UNMAPPED_PRESERVED":
            continue
        item = str(row["normalized_item"])
        best_name, best_score = "", 0.0
        for candidate in candidates:
            if candidate == item:
                continue
            score = difflib.SequenceMatcher(None, normalize_text(item), normalize_text(candidate)).ratio()
            if score > best_score:
                best_name, best_score = candidate, score
        if best_score >= 0.72:
            queue.at[idx, "suggested_canonical_item"] = best_name
            queue.at[idx, "suggestion_score"] = round(best_score, 4)

    return queue


def apply_mapping(raw_long: pd.DataFrame, mapping_queue: pd.DataFrame) -> pd.DataFrame:
    if raw_long.empty:
        return raw_long.copy()

    map_cols = [
        "source_key", "canonical_section", "canonical_item", "category",
        "mapping_status", "mapping_note",
    ]
    mapping = mapping_queue[map_cols].drop_duplicates("source_key")
    out = raw_long.merge(mapping, on="source_key", how="left")

    out["canonical_section"] = out["canonical_section"].fillna(
        out["parent_section"].fillna("").map(normalize_section)
    )
    out["canonical_item"] = out["canonical_item"].fillna(out["normalized_item"])
    out["mapping_status"] = out["mapping_status"].fillna("UNMAPPED_PRESERVED")
    out["category"] = out["category"].fillna("")

    accepted = {
        "AUTO_TAXONOMY",
        "AUTO_EXACT_IDENTITY",
        "CONFIRMED",
        "CONFIRMED_OVERRIDE",
    }

    def key_for(row) -> str:
        section = normalize_section(row.get("canonical_section"))
        item = str(row.get("canonical_item") or row.get("normalized_item") or "").strip()
        if row.get("mapping_status") in accepted:
            prefix = "CANON"
        else:
            prefix = "RAW"
        row_path = str(row.get("row_path") or row.get("normalized_item") or "").strip()
        family = _identity_text(row.get("table_family"))
        member = _identity_text(row.get("member_table"))
        role = _identity_text(row.get("member_table_role"))
        # Missing member identity is deliberately isolated by Capture rather
        # than collapsed into a false value comparison. materialize_canonical
        # will emit REVIEW_REQUIRED_SOURCE_IDENTITY for it.
        if not family or not member or not role:
            source_scope = f"MISSING_SOURCE::{_identity_text(row.get('capture_run_id')) or 'UNKNOWN'}"
        else:
            source_scope = f"FAMILY::{family}::MEMBER::{member}::ROLE::{role}"
        return f"{prefix}::{row.get('table_id')}::{source_scope}::{section}::{item}::{row_path}"

    out["canonical_key"] = out.apply(key_for, axis=1)
    return out


def _dimension_label(row: pd.Series) -> str:
    values = {
        "company": row.get("company"),
        "report_year": row.get("report_year", row.get("document_year")),
        "data_year": row.get("data_year", row.get("year")),
        "period_type": row.get("period_type"),
        "currency_unit": row.get("currency_unit"),
        "statement_scope": row.get("statement_scope", row.get("scope")),
        "restated_flag": row.get("restated_flag", row.get("restated")),
        "measure": row.get("measure"),
    }
    parts = []
    for key, value in values.items():
        if key == "restated_flag":
            parts.append(f"{key}={'TRUE' if _as_bool(value) else 'FALSE'}")
        elif value is not None and str(value).strip() not in {"", "nan", "None"}:
            parts.append(f"{key}={str(value).strip()}")
    return " | ".join(parts)


def _as_bool(value: Any) -> bool:
    """Interpret persisted CSV flags without treating the string 'False' as true."""
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return False
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "y", "已重述", "经重述", "重述"}
    return bool(value)


def _dimension_missing(value: Any) -> bool:
    return value is None or (isinstance(value, float) and pd.isna(value)) or str(value).strip() in {"", "nan", "None", "<NA>"}


def _unique_source_sequence(mapped_long: pd.DataFrame, capture_run_id: str) -> list[dict[str, Any]]:
    """
    Collapse long-form period rows to one structural row per original row_order.
    Preserve exact source order.
    """
    g = mapped_long[mapped_long["capture_run_id"].astype(str) == str(capture_run_id)].copy()
    if g.empty:
        return []

    g["_row_order_num"] = pd.to_numeric(g.get("row_order"), errors="coerce")
    g = g.sort_values(["_row_order_num"], kind="stable")

    rows = []
    seen_row_orders = set()
    for _, r in g.iterrows():
        ro = r.get("_row_order_num")
        if pd.isna(ro):
            continue
        ro_int = int(ro)
        if ro_int in seen_row_orders:
            continue
        seen_row_orders.add(ro_int)
        key = str(r.get("canonical_key") or "").strip()
        if not key:
            continue
        rows.append({
            "canonical_key": key,
            "row_order": ro_int,
            "row_type": str(r.get("row_type") or ""),
            "row_level": r.get("row_level"),
            "canonical_section": str(r.get("canonical_section") or ""),
            "canonical_item": str(r.get("canonical_item") or r.get("normalized_item") or ""),
            "parent_section": str(r.get("parent_section") or ""),
            "raw_item": str(r.get("raw_item") or ""),
            "table_family": _identity_text(r.get("table_family")),
            "member_table": _identity_text(r.get("member_table")),
            "member_table_role": _identity_text(r.get("member_table_role")),
            "source_table_title": _identity_text(r.get("source_table_title")),
            "note_reference": _identity_text(r.get("note_reference")),
            "member_table_order": r.get("member_table_order"),
            "row_path": _identity_text(r.get("row_path")),
        })
    return rows


def _dedupe_key_sequence(rows: list[dict[str, Any]]) -> tuple[list[str], list[dict[str, Any]]]:
    seq = []
    first_meta = {}
    duplicates = []
    for row in rows:
        key = row["canonical_key"]
        if key in first_meta:
            duplicates.append({
                "conflict_type": "DUPLICATE_CANONICAL_KEY_IN_SOURCE",
                "canonical_key": key,
                "first_row_order": first_meta[key]["row_order"],
                "duplicate_row_order": row["row_order"],
                "detail": (
                    "同一来源中多个原始行被映射到同一 canonical_key；"
                    "顺序层仅保留首次出现位置，数值层仍由 VALUE_CONFLICT/UNIT_CONFLICT 独立检查。"
                ),
            })
            continue
        first_meta[key] = row
        seq.append(key)
    return seq, duplicates


def _shared_order_conflicts(
    reference_seq: list[str],
    other_seq: list[str],
    capture_run_id: str,
) -> list[dict[str, Any]]:
    """
    Detect inversions among shared keys. Reference order is authoritative and
    will never be reordered to satisfy a conflicting source.
    """
    ref_pos = {k: i for i, k in enumerate(reference_seq)}
    shared = [k for k in other_seq if k in ref_pos]
    conflicts = []
    max_seen = -1
    max_key = None
    for key in shared:
        pos = ref_pos[key]
        if pos < max_seen:
            conflicts.append({
                "conflict_type": "ORDER_CONFLICT",
                "capture_run_id": capture_run_id,
                "canonical_key": key,
                "reference_predecessor_key": max_key,
                "detail": (
                    "该来源对共同项目的相对顺序与排序基准表冲突；"
                    "最终合表继续严格采用排序基准表顺序，不自动重排。"
                ),
            })
        if pos > max_seen:
            max_seen = pos
            max_key = key
    return conflicts


def _merge_missing_keys_preserving_context(
    base: list[str],
    incoming: list[str],
) -> list[str]:
    """
    Insert source-unique keys around the nearest already-known anchors while
    preserving their local source order. Existing keys are never reordered.

    This prevents unique child/detail rows from being dumped at the end of the
    merged table.
    """
    out = list(base)
    incoming = [k for i, k in enumerate(incoming) if k and k not in incoming[:i]]

    i = 0
    while i < len(incoming):
        if incoming[i] in out:
            i += 1
            continue

        # Collect a consecutive missing block.
        j = i
        block = []
        while j < len(incoming) and incoming[j] not in out:
            block.append(incoming[j])
            j += 1

        prev_known = None
        for k in reversed(incoming[:i]):
            if k in out:
                prev_known = k
                break

        next_known = None
        for k in incoming[j:]:
            if k in out:
                next_known = k
                break

        if prev_known is not None and next_known is not None:
            prev_idx = out.index(prev_known)
            next_idx = out.index(next_known)
            if prev_idx < next_idx:
                # Insert immediately before next anchor, keeping block order.
                insert_at = next_idx
            else:
                # Incoming source itself conflicts with established order.
                # Never reorder established keys; place after previous anchor.
                insert_at = prev_idx + 1
        elif prev_known is not None:
            insert_at = out.index(prev_known) + 1
            # Keep prior insertions after the same anchor in stable order.
            while insert_at < len(out) and out[insert_at] in incoming[:i]:
                insert_at += 1
        elif next_known is not None:
            insert_at = out.index(next_known)
        else:
            insert_at = len(out)

        out[insert_at:insert_at] = block
        i = j

    return out


def build_structural_order(
    mapped_long: pd.DataFrame,
    manifest: dict[str, Any],
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """
    Build one authoritative canonical row order.

    Policy:
    1. Reference capture order is immutable.
    2. Other captures may contribute missing keys around nearest known anchors.
    3. Shared-key inversions are reported as ORDER_CONFLICT, never used to
       reorder the reference.
    """
    if mapped_long.empty:
        return (
            pd.DataFrame(columns=[
                "canonical_order", "canonical_key", "row_type", "row_level",
                "canonical_section", "canonical_item", "parent_section", "order_source",
                "reference_row_order",
            ]),
            pd.DataFrame(),
        )

    manifest_sources = [x for x in (manifest.get("sources") or []) if x.get("capture_run_id")]
    # A Family is ordered by its explicit member order, then by the stable
    # caller/plan order. Never use one member's rows as the reference rows for
    # a different member table.
    def source_order(item: tuple[int, dict[str, Any]]) -> tuple[int, int]:
        index, source = item
        try:
            return (int(source.get("member_table_order")), index)
        except (TypeError, ValueError):
            return (10**9, index)
    manifest_sources = [source for _, source in sorted(enumerate(manifest_sources), key=source_order)]
    source_ids = [str(x.get("capture_run_id")) for x in manifest_sources]
    if not source_ids:
        source_ids = list(dict.fromkeys(mapped_long["capture_run_id"].astype(str).tolist()))

    requested_ref = str(manifest.get("reference_capture_run_id") or "")
    reference_id = requested_ref if requested_ref in source_ids else source_ids[0]

    sequences = {}
    row_meta_by_source = {}
    conflicts = []

    for source_id in source_ids:
        rows = _unique_source_sequence(mapped_long, source_id)
        seq, dup_conflicts = _dedupe_key_sequence(rows)
        for c in dup_conflicts:
            c["capture_run_id"] = source_id
        conflicts.extend(dup_conflicts)
        sequences[source_id] = seq
        row_meta_by_source[source_id] = {r["canonical_key"]: r for r in rows if r["canonical_key"]}

    base = list(sequences.get(reference_id, []))
    order_source = {k: f"REFERENCE:{reference_id}" for k in base}

    for source_id in source_ids:
        if source_id == reference_id:
            continue
        seq = sequences.get(source_id, [])
        conflicts.extend(_shared_order_conflicts(base, seq, source_id))
        before = set(base)
        merged = _merge_missing_keys_preserving_context(base, seq)
        for k in merged:
            if k not in before and k not in order_source:
                order_source[k] = f"INSERTED_FROM:{source_id}"
        base = merged

    # Include any unexpected keys not represented in manifest sources.
    all_keys = list(dict.fromkeys(mapped_long["canonical_key"].dropna().astype(str).tolist()))
    for key in all_keys:
        if key not in base:
            base.append(key)
            order_source[key] = "APPENDED_UNREFERENCED"

    # Structural metadata: reference source first, then first source containing key.
    order_rows = []
    ref_meta = row_meta_by_source.get(reference_id, {})
    for idx, key in enumerate(base, start=1):
        meta = ref_meta.get(key)
        meta_source = reference_id if meta else None
        if meta is None:
            for source_id in source_ids:
                if key in row_meta_by_source.get(source_id, {}):
                    meta = row_meta_by_source[source_id][key]
                    meta_source = source_id
                    break
        meta = meta or {}
        order_rows.append({
            "canonical_order": idx,
            "canonical_key": key,
            "row_type": meta.get("row_type", ""),
            "row_level": meta.get("row_level"),
            "canonical_section": meta.get("canonical_section", ""),
            "parent_section": meta.get("parent_section", ""),
            "canonical_item": meta.get("canonical_item", ""),
            "table_family": meta.get("table_family", ""),
            "member_table": meta.get("member_table", ""),
            "member_table_role": meta.get("member_table_role", ""),
            "source_table_title": meta.get("source_table_title", ""),
            "note_reference": meta.get("note_reference", ""),
            "member_table_order": meta.get("member_table_order"),
            "row_path": meta.get("row_path", ""),
            "order_source": order_source.get(key, f"FIRST_SEEN:{meta_source or 'UNKNOWN'}"),
            "reference_capture_run_id": reference_id,
            "reference_row_order": (
                ref_meta.get(key, {}).get("row_order")
                if key in ref_meta else None
            ),
            "metadata_source_capture_run_id": meta_source,
        })

    order_df = pd.DataFrame(order_rows)
    conflict_cols = [
        "conflict_type", "capture_run_id", "canonical_key",
        "reference_predecessor_key", "first_row_order",
        "duplicate_row_order", "detail",
    ]
    conflicts_df = pd.DataFrame(conflicts)
    for col in conflict_cols:
        if col not in conflicts_df.columns:
            conflicts_df[col] = None
    conflicts_df = conflicts_df[conflict_cols]

    return order_df, conflicts_df


def materialize_canonical(
    mapped_long: pd.DataFrame,
    structural_order: Optional[pd.DataFrame] = None,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    numeric = mapped_long[mapped_long["value"].notna()].copy()
    if numeric.empty:
        return pd.DataFrame(), pd.DataFrame(), pd.DataFrame()

    dims = [
        "table_id", "table_family", "member_table", "member_table_role",
        "source_table_title", "row_path", "canonical_key", "canonical_section", "canonical_item",
        "company", "report_year", "data_year", "statement_scope", "restated_flag",
        "period_type", "currency_unit", "unit",
        "measure",
    ]
    # Accept old capture exports while always materialising the explicit v6.6
    # canonical observation fields.
    aliases = {
        "report_year": "document_year", "data_year": "year",
        "statement_scope": "scope", "restated_flag": "restated",
    }
    for canonical, legacy in aliases.items():
        if canonical not in numeric.columns and legacy in numeric.columns:
            numeric[canonical] = numeric[legacy]
    if "currency_unit" not in numeric.columns:
        unit_map = {"元": "CNY", "千元": "CNY_THOUSAND", "万元": "CNY_TEN_THOUSAND", "百万元": "CNY_MILLION", "亿元": "CNY_HUNDRED_MILLION", "%": "PERCENT"}
        numeric["currency_unit"] = (numeric["unit"].map(unit_map).fillna("") if "unit" in numeric.columns else "")
    for column, default in {
        "table_family": "", "member_table": "", "member_table_role": "",
        "row_path": "", "period_type": "", "currency_unit": "", "unit": "", "measure": "",
        "source_table_title": "", "note_reference": "", "source_pdf": "",
    }.items():
        if column not in numeric.columns:
            numeric[column] = default
    # Old merge projects may be refreshed from CSV artifacts whose years were
    # parsed as floats and whose flags were persisted as display strings.
    # Normalise these fields before they become a wide-column identity.
    numeric["report_year"] = numeric["report_year"].map(lambda value: _absolute_year(value) or value)
    numeric["data_year"] = numeric["data_year"].map(lambda value: _absolute_year(value) or value)
    numeric["statement_scope"] = numeric["statement_scope"].replace({
        "本集团": "CONSOLIDATED", "集团": "CONSOLIDATED",
        "本公司": "COMPANY", "公司": "COMPANY",
    })
    numeric["restated_flag"] = numeric["restated_flag"].map(_as_bool)

    resolved_rows = []
    conflicts = []

    for key, g in numeric.groupby(dims, dropna=False, sort=False):
        values = [float(x) for x in g["value"].dropna().tolist()]
        unique_values = []
        for v in values:
            if not any(abs(v - u) <= max(1e-8, abs(u) * 1e-10) for u in unique_values):
                unique_values.append(v)

        conflict_reasons = []
        identity_missing = any(_source_identity_missing(row) for _, row in g.iterrows())
        if identity_missing:
            # Identity is incomplete, so this group has no right to reach value
            # conflict comparison. Rows remain auditable but require recovery.
            conflict_reasons.append("REVIEW_REQUIRED_SOURCE_IDENTITY")
        # Same key with different physical columns but incomplete dimensions is
        # not proof of inconsistent values.  Preserve evidence and request a
        # human dimension review instead of presenting it as a hard block.
        physical_columns = g.get("column_ordinal", pd.Series(dtype=float)).dropna().nunique()
        missing_dimensions = (_dimension_missing(key[dims.index("data_year")]) if "data_year" in dims else False) or (_dimension_missing(key[dims.index("statement_scope")]) if "statement_scope" in dims else False)
        dimension_ambiguous = physical_columns > 1 and missing_dimensions
        if len(unique_values) > 1 and not identity_missing:
            conflict_reasons.append("REVIEW_REQUIRED_DIMENSION_AMBIGUITY" if dimension_ambiguous else "VALUE_CONFLICT")

        base = {col: val for col, val in zip(dims, key)}
        base["source_identity_status"] = (
            "MISSING_MEMBER_TABLE_IDENTITY" if identity_missing else "SOURCE_IDENTITY_COMPLETE"
        )
        base["source_count"] = int(len(g))
        base["mapping_status"] = " | ".join(sorted(set(g["mapping_status"].astype(str))))
        base["conflict_status"] = "|".join(conflict_reasons) if conflict_reasons else "OK"
        base["conflict_severity"] = (
            "WARNING" if conflict_reasons and not any(reason == "VALUE_CONFLICT" for reason in conflict_reasons)
            else ("BLOCKING" if conflict_reasons else "OK")
        )
        base["dimension_review_required"] = bool(dimension_ambiguous)
        base["final_value"] = unique_values[0] if len(unique_values) == 1 and not conflict_reasons else None
        base["source_rows"] = " | ".join(
            f"{r.capture_run_id}:p{r.page}:{r.raw_item}"
            for r in g.itertuples()
        )
        base["source_provenance"] = json.dumps([
            {
                "capture_run_id": str(r.get("capture_run_id") or ""),
                "pdf": str(r.get("source_pdf") or r.get("pdf_name") or ""),
                "page": r.get("page"),
                "bbox": r.get("bbox"),
                "context_source_page": r.get("context_source_page"),
            }
            for _, r in g.iterrows()
        ], ensure_ascii=False)
        resolved_rows.append(base)

        if conflict_reasons:
            conflicts.append({
                **base,
                "values_found": " | ".join(map(str, unique_values)),
                "units_found": str(base.get("unit") or ""),
            })

    resolved = pd.DataFrame(resolved_rows)

    order_cols = [
        "canonical_key", "canonical_order", "row_type", "row_level", "parent_section",
        "order_source", "reference_capture_run_id", "reference_row_order",
    ]
    if structural_order is not None and not structural_order.empty:
        available_order_cols = [c for c in order_cols if c in structural_order.columns]
        resolved = resolved.merge(
            structural_order[available_order_cols].drop_duplicates("canonical_key"),
            on="canonical_key",
            how="left",
        )
        resolved = resolved.sort_values(
            ["canonical_order", "company", "report_year", "data_year"],
            kind="stable",
            na_position="last",
        ).reset_index(drop=True)
    else:
        resolved["canonical_order"] = range(1, len(resolved) + 1)
        resolved["row_type"] = ""
        resolved["order_source"] = "UNSPECIFIED"

    conflict_columns = list(resolved.columns) + ["values_found", "units_found"]
    conflicts_df = pd.DataFrame(conflicts, columns=conflict_columns)

    safe = resolved[
        (resolved["conflict_status"] == "OK")
        & resolved["final_value"].notna()
    ].copy()
    if safe.empty:
        empty_wide = pd.DataFrame(
            columns=["canonical_key", "canonical_section", "canonical_item", "unit"]
        )
        return resolved, empty_wide, conflicts_df

    safe["document_column"] = safe.apply(_dimension_label, axis=1)

    # Stable one-row-per-canonical-key metadata. Do NOT use multiple metadata
    # fields directly as pivot_table index with dropna=False, which can create a
    # Cartesian product.
    key_meta_cols = [
        "table_family", "member_table", "member_table_role", "row_path",
        "canonical_key", "canonical_order", "row_type", "row_level", "parent_section",
        "canonical_section", "canonical_item", "order_source", "source_identity_status",
    ]
    key_meta = (
        safe[[c for c in key_meta_cols if c in safe.columns]]
        .drop_duplicates(subset=["canonical_key"], keep="first")
    )

    def combine_units(series: pd.Series) -> str:
        units = sorted({
            str(x).strip()
            for x in series.dropna().tolist()
            if str(x).strip() and str(x).lower() != "nan"
        })
        if not units:
            return ""
        if len(units) == 1:
            return units[0]
        return "REVIEW_REQUIRED[" + "|".join(units) + "]"

    unit_by_key = (
        safe.groupby(["table_family", "member_table", "member_table_role", "row_path", "canonical_key"], sort=False)["unit"]
        .apply(combine_units)
        .rename("unit")
        .reset_index()
    )

    wide_values = safe.pivot_table(
        index=["table_family", "member_table", "member_table_role", "row_path", "canonical_key"],
        columns="document_column",
        values="final_value",
        aggfunc="first",
        dropna=True,
    ).reset_index()
    wide_values.columns.name = None

    wide = (
        key_meta
        .merge(unit_by_key, on=["table_family", "member_table", "member_table_role", "row_path", "canonical_key"], how="left")
        .merge(wide_values, on=["table_family", "member_table", "member_table_role", "row_path", "canonical_key"], how="left")
    )
    if "canonical_order" in wide.columns:
        wide = wide.sort_values("canonical_order", kind="stable", na_position="last").reset_index(drop=True)

    fixed = [
        "table_family", "member_table", "member_table_role", "row_path",
        "canonical_order", "row_type", "row_level", "parent_section", "canonical_section",
        "canonical_item", "unit", "canonical_key", "order_source", "source_identity_status",
    ]
    fixed = [c for c in fixed if c in wide.columns]
    wide = wide[fixed + [c for c in wide.columns if c not in fixed]]

    return resolved, wide, conflicts_df


def coverage_report(raw_long: pd.DataFrame, mapped_long: pd.DataFrame, conflicts: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for run_id, g in mapped_long[mapped_long["value"].notna()].groupby("capture_run_id", sort=False):
        total = len(g)
        confirmed = g["mapping_status"].isin(
            ["AUTO_TAXONOMY", "AUTO_EXACT_IDENTITY", "CONFIRMED", "CONFIRMED_OVERRIDE"]
        ).sum()
        preserved = (g["mapping_status"] == "UNMAPPED_PRESERVED").sum()
        rows.append({
            "capture_run_id": run_id,
            "company": g["company"].iloc[0] if len(g) else "",
            "document_year": g["document_year"].iloc[0] if len(g) else "",
            "numeric_source_rows": int(total),
            "mapped_or_exact_rows": int(confirmed),
            "unmapped_preserved_rows": int(preserved),
            "mapping_coverage": float(confirmed / total) if total else 0.0,
        })

    report = pd.DataFrame(rows)
    if not report.empty:
        report["project_conflict_count"] = int(len(conflicts))
    return report


def persist_confirmed_taxonomy(
    taxonomy_path: Path,
    table_id: str,
    mapping_queue: pd.DataFrame,
) -> dict[str, Any]:
    taxonomy = load_taxonomy(taxonomy_path)
    table = taxonomy.setdefault("tables", {}).setdefault(
        table_id,
        {"mappings": []},
    )
    existing = {
        (m.get("canonical_section", ""), m.get("canonical_item", "")): m
        for m in table.get("mappings", [])
    }

    accepted = {"CONFIRMED", "CONFIRMED_OVERRIDE", "AUTO_TAXONOMY"}
    written = 0
    for row in mapping_queue.to_dict("records"):
        if row.get("mapping_status") not in accepted:
            continue
        canonical_item = str(row.get("canonical_item") or "").strip()
        if not canonical_item:
            continue
        canonical_section = normalize_section(row.get("canonical_section"))
        key = (canonical_section, canonical_item)
        entry = existing.get(key)
        if entry is None:
            entry = {
                "canonical_section": canonical_section,
                "canonical_item": canonical_item,
                "category": str(row.get("category") or ""),
                "source_keys": [],
            }
            table["mappings"].append(entry)
            existing[key] = entry
        source_key = str(row.get("source_key"))
        if source_key not in entry["source_keys"]:
            entry["source_keys"].append(source_key)
            written += 1
        if row.get("category"):
            entry["category"] = str(row.get("category"))

    _atomic_json(Path(taxonomy_path), taxonomy)
    return {"written_source_keys": written, "taxonomy_path": str(taxonomy_path)}


def collect_merge_reconciliation(manifest: dict[str, Any]) -> pd.DataFrame:
    frames=[]
    for source in manifest.get("sources") or []:
        capture_dir=Path(str(source.get("capture_dir") or ""))
        path=capture_dir/"table_reconciliation_audit.csv"
        if not path.exists():
            try:
                from reconciliation import write_reconciliation_audit
                path=write_reconciliation_audit(capture_dir)
            except Exception:
                continue
        try:
            df=pd.read_csv(path)
        except Exception:
            continue
        if df.empty:
            continue
        df.insert(0,"capture_run_id",source.get("capture_run_id"))
        df.insert(1,"company",source.get("company"))
        df.insert(2,"document_year",source.get("document_year"))
        frames.append(df)
    return pd.concat(frames,ignore_index=True) if frames else pd.DataFrame()


def source_identity_qa(raw_long: pd.DataFrame) -> pd.DataFrame:
    """Expose source provenance before any row/value comparison is attempted."""
    columns = SOURCE_IDENTITY_COLUMNS + [
        "member_table_order", "row_path_count", "source_identity_status", "qa_detail",
    ]
    if raw_long.empty:
        return pd.DataFrame(columns=columns)
    work = raw_long.copy()
    for field in SOURCE_IDENTITY_COLUMNS:
        if field not in work.columns:
            work[field] = ""
    if "member_table_order" not in work.columns:
        work["member_table_order"] = None
    rows = []
    for capture_id, group in work.groupby("capture_run_id", dropna=False, sort=False):
        first = group.iloc[0]
        missing = [field for field in ("table_family", "member_table", "member_table_role") if not _identity_text(first.get(field))]
        rows.append({
            **{field: first.get(field) for field in SOURCE_IDENTITY_COLUMNS},
            "capture_run_id": capture_id,
            "member_table_order": first.get("member_table_order"),
            "row_path_count": int(group.get("row_path", pd.Series(dtype=str)).dropna().astype(str).nunique()),
            "source_identity_status": "MISSING_MEMBER_TABLE_IDENTITY" if missing else "SOURCE_IDENTITY_COMPLETE",
            "qa_detail": ("缺少：" + "、".join(missing)) if missing else "可进入 source-aware row alignment",
        })
    return pd.DataFrame(rows, columns=columns)


def write_presentation_wide_sheet(
    writer: Any,
    research_wide: pd.DataFrame,
    fixed_columns: list[Any],
    column_dimensions: pd.DataFrame,
    header_policy: VisibleHeaderDimensionPolicy,
) -> None:
    """Write the human-facing multi-level wide sheet without COL ids."""
    header_rows = max(1, len(header_policy.visible_header_dimensions))
    research_wide.to_excel(
        writer,
        sheet_name="canonical_wide",
        index=False,
        header=False,
        startrow=header_rows + 2,
    )
    ws = writer.sheets["canonical_wide"]
    ws.cell(row=1, column=1, value="研究宽表元数据")
    meta_text = "；".join(
        f"{dimension}={value}"
        for dimension, value in header_policy.metadata_values.items()
        if value
    )
    ws.cell(row=1, column=2, value=meta_text)
    start_col = len(fixed_columns) + 1
    for column_index, column_name in enumerate(fixed_columns, start=1):
        ws.cell(row=2, column=column_index, value=str(column_name))
        if header_rows > 1:
            ws.merge_cells(
                start_row=2,
                start_column=column_index,
                end_row=header_rows + 1,
                end_column=column_index,
            )
    for row_index, dimension in enumerate(header_policy.visible_header_dimensions, start=2):
        labels = column_dimensions.get(
            f"display_{dimension}",
            pd.Series([""] * len(column_dimensions)),
        ).tolist()
        for offset, value in enumerate(labels):
            ws.cell(row=row_index, column=start_col + offset, value=value)
        run_start = start_col
        for offset in range(1, len(labels) + 1):
            changed = offset == len(labels) or labels[offset] != labels[offset - 1]
            if changed:
                if offset > 1 and start_col + offset - 1 > run_start and labels[offset - 1]:
                    ws.merge_cells(
                        start_row=row_index,
                        start_column=run_start,
                        end_row=row_index,
                        end_column=start_col + offset - 1,
                    )
                run_start = start_col + offset
    ws.freeze_panes = f"A{header_rows + 3}"


def write_merge_outputs(
    output_dir: Path,
    manifest: dict[str, Any],
    raw_long: pd.DataFrame,
    mapping_queue: pd.DataFrame,
    taxonomy_path: Optional[Path] = None,
) -> dict[str, str]:
    output_dir.mkdir(parents=True, exist_ok=True)

    # v5.8 invariant: canonicalization never sees relative labels in `year`.
    # This also repairs already-created v5.7 merge_raw_long.csv on refresh.
    raw_long, manifest = _repair_manifest_and_raw_periods(raw_long, manifest)

    mapped = apply_mapping(raw_long, mapping_queue)
    structural_order, order_conflicts = build_structural_order(mapped, manifest)

    if not structural_order.empty:
        mapped = mapped.merge(
            structural_order[
                [
                    "canonical_key", "canonical_order", "row_type", "row_level", "parent_section",
                    "order_source", "reference_capture_run_id", "reference_row_order",
                ]
            ].drop_duplicates("canonical_key"),
            on="canonical_key",
            how="left",
            suffixes=("", "_order"),
        )
        # Preserve source evidence ordering inside each capture, while exposing
        # canonical_order for cross-company research views.
        mapped = mapped.sort_values(
            ["capture_run_id", "row_order", "canonical_order"],
            kind="stable",
            na_position="last",
        ).reset_index(drop=True)

    resolved, wide, conflicts = materialize_canonical(
        mapped,
        structural_order=structural_order,
    )
    coverage = coverage_report(raw_long, mapped, conflicts)
    reconciliation = collect_merge_reconciliation(manifest)
    identity_qa = source_identity_qa(raw_long)

    # Canonical Long is the source of truth. CSV cannot represent a real
    # hierarchical header, so its wide view uses stable encoded ids and an
    # explicit dimension mapping rather than a lossy concatenated label.
    fixed_columns = [c for c in wide.columns if not str(c).startswith("company=")]
    value_columns = [c for c in wide.columns if str(c).startswith("company=")]
    column_rows = []
    rename_columns = {}
    for ordinal, column in enumerate(value_columns, start=1):
        column_id = f"COL_{ordinal:05d}"
        rename_columns[column] = column_id
        dims = {}
        for token in str(column).split(" | "):
            if "=" in token:
                key, value = token.split("=", 1); dims[key] = value
        # Currency is retained independently even when the older v6.6
        # presentation label only carried currency_unit.
        dims.setdefault("currency", "CNY" if str(dims.get("currency_unit") or "").startswith("CNY") else "")
        column_rows.append({"column_id": column_id, "source_column_label": column, **{key: dims.get(key, "") for key in OBSERVATION_DIMENSIONS}})
    research_wide = wide.rename(columns=rename_columns)
    column_dimensions = pd.DataFrame(column_rows)
    header_policy = VisibleHeaderDimensionPolicy.from_column_dimensions(column_dimensions)
    if not column_dimensions.empty:
        display_rows = [header_policy.label_for_column(row) for row in column_dimensions.to_dict("records")]
        for dimension in header_policy.visible_header_dimensions:
            column_dimensions[f"display_{dimension}"] = [row.get(dimension, "") for row in display_rows]

    paths = {
        "manifest": output_dir / "merge_manifest.json",
        "raw_long": output_dir / "merge_raw_long.csv",
        "mapping_queue": output_dir / "merge_mapping_queue.csv",
        "canonical_long": output_dir / "merge_canonical_long.csv",
        "canonical_research_long": output_dir / "canonical_research_long.csv",
        "resolved_long": output_dir / "merge_resolved_long.csv",
        "canonical_wide": output_dir / "merge_canonical_wide.csv",
        "column_dimensions": output_dir / "column_dimensions.csv",
        "wide_metadata": output_dir / "research_wide_metadata.json",
        "conflicts": output_dir / "merge_conflicts.csv",
        "coverage": output_dir / "merge_coverage.csv",
        "structural_order": output_dir / "merge_structural_order.csv",
        "order_conflicts": output_dir / "merge_order_conflicts.csv",
        "reconciliation": output_dir / "merge_reconciliation_audit.csv",
        "source_identity_qa": output_dir / "merge_source_identity_qa.csv",
        "xlsx": output_dir / "merge_project.xlsx",
    }

    paths["manifest"].write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    raw_long.to_csv(paths["raw_long"], index=False, encoding="utf-8-sig")
    mapping_queue.to_csv(paths["mapping_queue"], index=False, encoding="utf-8-sig")
    mapped.to_csv(paths["canonical_long"], index=False, encoding="utf-8-sig")
    # Canonical Research Long is the source-of-truth observation layer. It
    # retains source rows and provenance; wide/resolved outputs are views.
    mapped.to_csv(paths["canonical_research_long"], index=False, encoding="utf-8-sig")
    resolved.to_csv(paths["resolved_long"], index=False, encoding="utf-8-sig")
    research_wide.to_csv(paths["canonical_wide"], index=False, encoding="utf-8-sig")
    column_dimensions.to_csv(paths["column_dimensions"], index=False, encoding="utf-8-sig")
    paths["wide_metadata"].write_text(json.dumps({"metadata_dimensions": list(header_policy.metadata_dimensions), "visible_header_dimensions": list(header_policy.visible_header_dimensions), "display_order": list(header_policy.display_order), "metadata_values": header_policy.metadata_values, "presentation_export_version": 2}, ensure_ascii=False, indent=2), encoding="utf-8")
    conflicts.to_csv(paths["conflicts"], index=False, encoding="utf-8-sig")
    coverage.to_csv(paths["coverage"], index=False, encoding="utf-8-sig")
    structural_order.to_csv(paths["structural_order"], index=False, encoding="utf-8-sig")
    order_conflicts.to_csv(paths["order_conflicts"], index=False, encoding="utf-8-sig")
    reconciliation.to_csv(paths["reconciliation"], index=False, encoding="utf-8-sig")
    identity_qa.to_csv(paths["source_identity_qa"], index=False, encoding="utf-8-sig")

    with pd.ExcelWriter(paths["xlsx"], engine="openpyxl") as writer:
        raw_long.to_excel(writer, sheet_name="raw_long", index=False)
        mapping_queue.to_excel(writer, sheet_name="mapping_queue", index=False)
        mapped.to_excel(writer, sheet_name="canonical_long", index=False)
        mapped.to_excel(writer, sheet_name="canonical_research_long", index=False)
        resolved.to_excel(writer, sheet_name="resolved_long", index=False)
        write_presentation_wide_sheet(
            writer,
            research_wide,
            fixed_columns,
            column_dimensions,
            header_policy,
        )
        column_dimensions.to_excel(writer, sheet_name="column_dimensions", index=False)
        conflicts.to_excel(writer, sheet_name="conflicts", index=False)
        coverage.to_excel(writer, sheet_name="coverage", index=False)
        structural_order.to_excel(writer, sheet_name="structural_order", index=False)
        order_conflicts.to_excel(writer, sheet_name="order_conflicts", index=False)
        reconciliation.to_excel(writer, sheet_name="reconciliation", index=False)
        identity_qa.to_excel(writer, sheet_name="source_identity_qa", index=False)

    if taxonomy_path and Path(taxonomy_path).exists():
        snapshot = output_dir / "taxonomy_snapshot.json"
        snapshot.write_text(Path(taxonomy_path).read_text(encoding="utf-8"), encoding="utf-8")
        paths["taxonomy_snapshot"] = snapshot

    try:
        from registry_bridge import sync_merge_run
        sync_merge_run(output_dir)
    except Exception:
        pass

    return {k: str(v) for k, v in paths.items()}


def create_merge_project(
    capture_dirs: list[Path],
    metadata_rows: list[dict[str, Any]],
    output_dir: Path,
    table_id: str,
    taxonomy_path: Path,
    reference_capture_run_id: Optional[str] = None,
) -> dict[str, str]:
    table_id = normalize_table_id(table_id)
    metadata_map = {str(r["capture_run_id"]): r for r in metadata_rows}

    frames = []
    manifest_sources = []
    for capture_dir in capture_dirs:
        inferred = infer_capture_metadata(capture_dir)
        user_meta = metadata_map.get(capture_dir.name, {})
        meta = {**inferred, **user_meta}
        frame = load_capture_long(capture_dir, meta, table_id)
        frames.append(frame)
        manifest_sources.append(meta)

    raw_long = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()
    taxonomy = load_taxonomy(taxonomy_path)
    queue = build_mapping_queue(raw_long, table_id, taxonomy)

    source_ids = [str(x.get("capture_run_id")) for x in manifest_sources]
    if reference_capture_run_id not in source_ids:
        reference_capture_run_id = source_ids[0] if source_ids else None

    manifest = {
        "version": "v6.7",
        "merge_schema_version": "6.7_SOURCE_AWARE_MEMBER_IDENTITY_WITH_MEASURE_AXIS",
        "canonical_observation_schema_version": "6.7_EXPLICIT_OBSERVATION_DIMENSIONS",
        "table_id": table_id,
        "sources": manifest_sources,
        "taxonomy_path": str(taxonomy_path),
        "order_policy": "REFERENCE_CAPTURE_PRESERVE_WITH_CONTEXTUAL_INSERTION",
        "identity_policy": "TABLE_FAMILY__MEMBER_TABLE__MEMBER_ROLE__ROW_PATH__DIMENSIONS",
        "reference_capture_run_id": reference_capture_run_id,
    }
    return write_merge_outputs(
        output_dir=output_dir,
        manifest=manifest,
        raw_long=raw_long,
        mapping_queue=queue,
        taxonomy_path=taxonomy_path,
    )


def refresh_merge_project(
    output_dir: Path,
    mapping_queue: Optional[pd.DataFrame] = None,
    persist_taxonomy: bool = False,
) -> dict[str, str]:
    output_dir = Path(output_dir)
    manifest = json.loads((output_dir / "merge_manifest.json").read_text(encoding="utf-8"))
    # A refresh is also the non-destructive migration path for old derived
    # merge artifacts. Source capture evidence and human mapping decisions are
    # retained; only generated outputs are recomputed under the current
    # observation contract.
    manifest["canonical_observation_schema_version"] = "6.7_EXPLICIT_OBSERVATION_DIMENSIONS"
    raw = pd.read_csv(output_dir / "merge_raw_long.csv")
    queue = (
        mapping_queue.copy()
        if mapping_queue is not None
        else pd.read_csv(output_dir / "merge_mapping_queue.csv")
    )
    taxonomy_path = Path(manifest.get("taxonomy_path", output_dir / "table_taxonomy.json"))

    if persist_taxonomy:
        persist_confirmed_taxonomy(taxonomy_path, manifest["table_id"], queue)

    return write_merge_outputs(
        output_dir=output_dir,
        manifest=manifest,
        raw_long=raw,
        mapping_queue=queue,
        taxonomy_path=taxonomy_path,
    )
