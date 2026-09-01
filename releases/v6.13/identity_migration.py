from __future__ import annotations

import hashlib
import json
from typing import Any

import pandas as pd


LEGACY_IDENTITY_COLUMNS = {
    "parent_section",
    "row_level",
    "row_type",
    "extractor_row_role",
    "row_path",
    "canonical_item",
    "mapping_status",
}


def _text(value: Any) -> str:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return ""
    return str(value).strip()


def _stable_row_id(row: pd.Series, occurrence: int) -> str:
    bbox = row.get("bbox")
    if isinstance(bbox, str):
        try:
            bbox = json.loads(bbox)
        except (TypeError, ValueError, json.JSONDecodeError):
            bbox = {}
    bbox = bbox if isinstance(bbox, dict) else {}
    payload = {
        "pdf_sha256": _text(row.get("pdf_sha256") or row.get("source_pdf")),
        "physical_table_id": _text(row.get("physical_table_id") or row.get("table_block_id")),
        "page": _text(row.get("page") or row.get("pdf_page")),
        "block_id": _text(row.get("table_block_id") or row.get("block_id")),
        "bbox": {key: _text(bbox.get(key)) for key in ("x0", "y0", "x1", "y1")},
        "raw_item": _text(row.get("raw_item") or row.get("item")),
        "occurrence": int(occurrence),
    }
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return "ROW_" + hashlib.sha256(encoded.encode("utf-8")).hexdigest()[:24]


def audit_identity_frame(frame: pd.DataFrame) -> dict[str, Any]:
    return {
        "rows": int(len(frame)),
        "legacy_columns_present": sorted(LEGACY_IDENTITY_COLUMNS.intersection(frame.columns)),
        "missing_source_row_id": int(
            frame["source_row_id"].astype(str).isin({"", "nan", "None"}).sum()
        ) if "source_row_id" in frame.columns else int(len(frame)),
        "missing_parent_row_id": int(
            frame["parent_row_id"].astype(str).isin({"", "nan", "None"}).sum()
        ) if "parent_row_id" in frame.columns else int(len(frame)),
    }


def migrate_identity_frame(
    frame: pd.DataFrame,
    *,
    drop_legacy: bool = True,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    out = frame.copy()
    if "source_row_id" not in out.columns:
        out["source_row_id"] = ""
    if "parent_row_id" not in out.columns:
        out["parent_row_id"] = ""
    if "row_origin" not in out.columns:
        out["row_origin"] = "SOURCE"
    if "hierarchy_evidence" not in out.columns:
        out["hierarchy_evidence"] = None

    occurrences: dict[str, int] = {}
    for index, row in out.iterrows():
        current = _text(row.get("source_row_id"))
        if not current:
            anchor = "|".join([
                _text(row.get("pdf_sha256") or row.get("source_pdf")),
                _text(row.get("physical_table_id") or row.get("table_block_id")),
                _text(row.get("page")),
                _text(row.get("raw_item") or row.get("item")),
            ])
            occurrence = occurrences.get(anchor, 0)
            occurrences[anchor] = occurrence + 1
            out.at[index, "source_row_id"] = _stable_row_id(row, occurrence)
        if not _text(row.get("row_origin")):
            out.at[index, "row_origin"] = "DERIVED" if _text(row.get("observation_type")).startswith("DERIVED") else "SOURCE"

    by_label: dict[str, list[str]] = {}
    def remember(label: str, source_id: str) -> None:
        if label and source_id and source_id not in by_label.setdefault(label, []):
            by_label[label].append(source_id)
    unresolved: list[dict[str, Any]] = []
    for index, row in out.iterrows():
        if _text(row.get("parent_row_id")):
            for label in (_text(row.get("normalized_item")), _text(row.get("raw_item"))):
                remember(label, _text(row.get("source_row_id")))
            continue
        parent = _text(row.get("parent_section"))
        if not parent:
            for label in (_text(row.get("normalized_item")), _text(row.get("raw_item"))):
                remember(label, _text(row.get("source_row_id")))
            continue
        candidates = list(by_label.get(parent, []))
        if len(candidates) == 1:
            out.at[index, "parent_row_id"] = candidates[0]
            out.at[index, "hierarchy_evidence"] = json.dumps(
                {"method": "LEGACY_PARENT_SECTION_MIGRATION", "parent_label": parent},
                ensure_ascii=False,
            )
        else:
            unresolved.append({
                "row_index": int(index),
                "parent_label": parent,
                "candidate_count": len(candidates),
                "status": "IDENTITY_MIGRATION_UNRESOLVED",
            })
        for label in (_text(row.get("normalized_item")), _text(row.get("raw_item"))):
            remember(label, _text(row.get("source_row_id")))

    audit = audit_identity_frame(out)
    audit["unresolved_parent_rows"] = unresolved
    if drop_legacy:
        out = out.drop(columns=[column for column in LEGACY_IDENTITY_COLUMNS if column in out.columns])
    return out, audit
