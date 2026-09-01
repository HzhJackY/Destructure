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


TAXONOMY_VERSION = 1


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
    out = df.copy()
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
            row_type = str(r.get("row_type") or "").strip()
            key = f"CONTEXT||{item}||{parent}||{row_type}||OCC{occurrence}"
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


def _clean_period_token(value: Any) -> str:
    token = str(value or "").strip()
    if re.fullmatch(r"20\d{2}\.0", token):
        return token[:4]
    token = re.sub(r"\s+", "", token)
    token = token.replace("（", "(").replace("）", ")")
    token = re.sub(r"\(?(?:已重述|经重述|重述后|重述)\)?", "", token)
    token = re.sub(r"(?:人民币)?(?:亿元|百万元|万元|千元|元)$", "", token)
    return token.strip()


def _absolute_year(value: Any) -> Optional[str]:
    token = _clean_period_token(value)
    m = re.fullmatch(r"(20\d{2})(?:年度|年)?", token)
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
        out["column_dimension_key"] = out.apply(
            lambda r: (
                f"{str(r.get('year') or '').strip()}|"
                f"{str(r.get('scope') or '').strip()}|"
                f"{'RESTATED' if bool(r.get('restated')) else 'ORIGINAL'}"
            )
            if pd.notna(r.get("column_ordinal")) else r.get("column_dimension_key"),
            axis=1,
        )
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

    df.insert(0, "capture_run_id", metadata["capture_run_id"])
    df.insert(1, "company", metadata.get("company", ""))
    df.insert(2, "document_year", effective_document_year)
    df.insert(3, "table_id", table_id)

    df = _resolve_relative_period_years(df, effective_document_year)
    _validate_absolute_year_resolution(
        df,
        document_year=effective_document_year,
        capture_run_id=str(metadata["capture_run_id"]),
    )
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
        return f"{prefix}::{row.get('table_id')}::{section}::{item}"

    out["canonical_key"] = out.apply(key_for, axis=1)
    return out


def _dimension_label(row: pd.Series) -> str:
    parts = [
        str(row.get("company") or "").strip(),
        str(row.get("document_year") or "").strip(),
    ]
    value_year = str(row.get("year") or "").strip()
    if value_year and value_year not in {"nan", "None"}:
        parts.append(value_year)
    scope = str(row.get("scope") or "").strip()
    if scope and scope not in {"nan", "None"}:
        parts.append(scope)
    if bool(row.get("restated")):
        parts.append("已重述")
    return " | ".join(x for x in parts if x)


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

    source_ids = [
        str(x.get("capture_run_id"))
        for x in (manifest.get("sources") or [])
        if x.get("capture_run_id")
    ]
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
        "table_id", "canonical_key", "canonical_section", "canonical_item",
        "company", "document_year", "year", "scope", "restated",
    ]

    resolved_rows = []
    conflicts = []

    for key, g in numeric.groupby(dims, dropna=False, sort=False):
        values = [float(x) for x in g["value"].dropna().tolist()]
        units = sorted({str(x) for x in g["unit"].dropna().tolist() if str(x).strip()})
        unique_values = []
        for v in values:
            if not any(abs(v - u) <= max(1e-8, abs(u) * 1e-10) for u in unique_values):
                unique_values.append(v)

        conflict_reasons = []
        if len(unique_values) > 1:
            conflict_reasons.append("VALUE_CONFLICT")
        if len(units) > 1:
            conflict_reasons.append("UNIT_CONFLICT")

        base = {col: val for col, val in zip(dims, key)}
        base["unit"] = units[0] if len(units) == 1 else (
            "REVIEW_REQUIRED[" + "|".join(units) + "]" if units else ""
        )
        base["source_count"] = int(len(g))
        base["mapping_status"] = " | ".join(sorted(set(g["mapping_status"].astype(str))))
        base["conflict_status"] = "|".join(conflict_reasons) if conflict_reasons else "OK"
        base["final_value"] = unique_values[0] if len(unique_values) == 1 and not conflict_reasons else None
        base["source_rows"] = " | ".join(
            f"{r.capture_run_id}:p{r.page}:{r.raw_item}"
            for r in g.itertuples()
        )
        resolved_rows.append(base)

        if conflict_reasons:
            conflicts.append({
                **base,
                "values_found": " | ".join(map(str, unique_values)),
                "units_found": " | ".join(units),
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
            ["canonical_order", "company", "document_year", "year"],
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
        "canonical_key", "canonical_order", "row_type", "row_level", "parent_section",
        "canonical_section", "canonical_item", "order_source",
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
        safe.groupby("canonical_key", sort=False)["unit"]
        .apply(combine_units)
        .rename("unit")
        .reset_index()
    )

    wide_values = safe.pivot_table(
        index="canonical_key",
        columns="document_column",
        values="final_value",
        aggfunc="first",
        dropna=True,
    ).reset_index()
    wide_values.columns.name = None

    wide = (
        key_meta
        .merge(unit_by_key, on="canonical_key", how="left")
        .merge(wide_values, on="canonical_key", how="left")
    )
    if "canonical_order" in wide.columns:
        wide = wide.sort_values("canonical_order", kind="stable", na_position="last").reset_index(drop=True)

    fixed = [
        "canonical_order", "row_type", "row_level", "parent_section", "canonical_section",
        "canonical_item", "unit", "canonical_key", "order_source",
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

    paths = {
        "manifest": output_dir / "merge_manifest.json",
        "raw_long": output_dir / "merge_raw_long.csv",
        "mapping_queue": output_dir / "merge_mapping_queue.csv",
        "canonical_long": output_dir / "merge_canonical_long.csv",
        "resolved_long": output_dir / "merge_resolved_long.csv",
        "canonical_wide": output_dir / "merge_canonical_wide.csv",
        "conflicts": output_dir / "merge_conflicts.csv",
        "coverage": output_dir / "merge_coverage.csv",
        "structural_order": output_dir / "merge_structural_order.csv",
        "order_conflicts": output_dir / "merge_order_conflicts.csv",
        "reconciliation": output_dir / "merge_reconciliation_audit.csv",
        "xlsx": output_dir / "merge_project.xlsx",
    }

    paths["manifest"].write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    raw_long.to_csv(paths["raw_long"], index=False, encoding="utf-8-sig")
    mapping_queue.to_csv(paths["mapping_queue"], index=False, encoding="utf-8-sig")
    mapped.to_csv(paths["canonical_long"], index=False, encoding="utf-8-sig")
    resolved.to_csv(paths["resolved_long"], index=False, encoding="utf-8-sig")
    wide.to_csv(paths["canonical_wide"], index=False, encoding="utf-8-sig")
    conflicts.to_csv(paths["conflicts"], index=False, encoding="utf-8-sig")
    coverage.to_csv(paths["coverage"], index=False, encoding="utf-8-sig")
    structural_order.to_csv(paths["structural_order"], index=False, encoding="utf-8-sig")
    order_conflicts.to_csv(paths["order_conflicts"], index=False, encoding="utf-8-sig")
    reconciliation.to_csv(paths["reconciliation"], index=False, encoding="utf-8-sig")

    with pd.ExcelWriter(paths["xlsx"], engine="openpyxl") as writer:
        raw_long.to_excel(writer, sheet_name="raw_long", index=False)
        mapping_queue.to_excel(writer, sheet_name="mapping_queue", index=False)
        mapped.to_excel(writer, sheet_name="canonical_long", index=False)
        resolved.to_excel(writer, sheet_name="resolved_long", index=False)
        wide.to_excel(writer, sheet_name="canonical_wide", index=False)
        conflicts.to_excel(writer, sheet_name="conflicts", index=False)
        coverage.to_excel(writer, sheet_name="coverage", index=False)
        structural_order.to_excel(writer, sheet_name="structural_order", index=False)
        order_conflicts.to_excel(writer, sheet_name="order_conflicts", index=False)
        reconciliation.to_excel(writer, sheet_name="reconciliation", index=False)

    if taxonomy_path and Path(taxonomy_path).exists():
        snapshot = output_dir / "taxonomy_snapshot.json"
        snapshot.write_text(Path(taxonomy_path).read_text(encoding="utf-8"), encoding="utf-8")
        paths["taxonomy_snapshot"] = snapshot

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
        "version": "v6.0",
        "merge_schema_version": "6.0",
        "table_id": table_id,
        "sources": manifest_sources,
        "taxonomy_path": str(taxonomy_path),
        "order_policy": "REFERENCE_CAPTURE_PRESERVE_WITH_CONTEXTUAL_INSERTION",
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
