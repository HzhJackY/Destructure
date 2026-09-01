#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations

import datetime as dt
import json
import shutil
from pathlib import Path
from typing import Any, Optional


def load_merge_manifest(run_dir: Path) -> dict[str, Any]:
    path=Path(run_dir)/"merge_manifest.json"
    return json.loads(path.read_text(encoding="utf-8"))


def ensure_merge_metadata(run_dir: Path) -> dict[str, Any]:
    run_dir=Path(run_dir)
    path=run_dir/"merge_metadata.json"
    manifest=load_merge_manifest(run_dir)

    if path.exists():
        data=json.loads(path.read_text(encoding="utf-8"))
    else:
        table_id=str(manifest.get("table_id") or "Merge")
        sources=manifest.get("sources") or []
        companies=[]
        years=[]
        for s in sources:
            c=str(s.get("company") or "").strip()
            y=str(s.get("document_year") or "").strip()
            if c and c not in companies:
                companies.append(c)
            if y and y not in years:
                years.append(y)
        scope="、".join(companies[:4])
        if len(companies)>4:
            scope+=f"等{len(companies)}家"
        year_scope="–".join(sorted(years)[:1]+sorted(years)[-1:]) if years else ""
        display=" · ".join(x for x in [table_id, scope, year_scope] if x)

        data={
            "run_id":run_dir.name,
            "display_name":display or run_dir.name,
            "note":"",
            "created_at":dt.datetime.fromtimestamp(run_dir.stat().st_mtime).isoformat(timespec="seconds"),
        }

    data.setdefault("lifecycle_status", "ACTIVE")
    data.setdefault("dependency_status", "CURRENT")
    data.setdefault("stale_capture_run_ids", [])
    data.setdefault("asset_schema_version", "6.0")
    data["table_id"]=manifest.get("table_id")
    data["source_count"]=len(manifest.get("sources") or [])
    data["reference_capture_run_id"]=manifest.get("reference_capture_run_id")
    data["order_policy"]=manifest.get("order_policy")
    path.write_text(json.dumps(data,ensure_ascii=False,indent=2),encoding="utf-8")
    return data


def update_merge_metadata(
    run_dir: Path,
    display_name: Optional[str]=None,
    note: Optional[str]=None,
)->dict[str,Any]:
    data=ensure_merge_metadata(run_dir)
    if display_name is not None:
        data["display_name"]=str(display_name).strip() or data.get("display_name") or Path(run_dir).name
    if note is not None:
        data["note"]=str(note)
    (Path(run_dir)/"merge_metadata.json").write_text(
        json.dumps(data,ensure_ascii=False,indent=2),encoding="utf-8"
    )
    return data


def merge_record(run_dir: Path)->dict[str,Any]:
    run_dir=Path(run_dir)
    meta=ensure_merge_metadata(run_dir)
    manifest=load_merge_manifest(run_dir)
    order_conflicts=run_dir/"merge_order_conflicts.csv"
    value_conflicts=run_dir/"merge_conflicts.csv"

    def count_csv_rows(path:Path)->int:
        if not path.exists() or path.stat().st_size==0:
            return 0
        try:
            import pandas as pd
            return len(pd.read_csv(path))
        except Exception:
            return 0

    return {
        **meta,
        "run_dir":str(run_dir),
        "run_id":run_dir.name,
        "table_id":manifest.get("table_id"),
        "source_count":len(manifest.get("sources") or []),
        "reference_capture_run_id":manifest.get("reference_capture_run_id"),
        "order_conflict_count":count_csv_rows(order_conflicts),
        "value_conflict_count":count_csv_rows(value_conflicts),
    }


def list_merge_records(merge_dir: Path)->list[dict[str,Any]]:
    root=Path(merge_dir)
    rows=[]
    for p in root.iterdir():
        if not p.is_dir() or p.name=="_trash":
            continue
        if (p/"merge_manifest.json").exists():
            try:
                rows.append(merge_record(p))
            except Exception:
                continue
    rows.sort(key=lambda r:Path(r["run_dir"]).stat().st_mtime,reverse=True)
    return rows


def soft_delete_merge(run_dir: Path,trash_dir: Path)->Path:
    run_dir=Path(run_dir)
    trash_dir=Path(trash_dir)
    trash_dir.mkdir(parents=True,exist_ok=True)
    target=trash_dir/run_dir.name
    if target.exists():
        target=trash_dir/f"{run_dir.name}__{dt.datetime.now().strftime('%Y%m%dT%H%M%S')}"
    return Path(shutil.move(str(run_dir),str(target)))


def restore_merge(trashed_dir: Path,merge_dir: Path)->Path:
    trashed_dir=Path(trashed_dir)
    merge_dir=Path(merge_dir)
    target=merge_dir/trashed_dir.name
    if target.exists():
        target=merge_dir/f"{trashed_dir.name}__restored_{dt.datetime.now().strftime('%Y%m%dT%H%M%S')}"
    return Path(shutil.move(str(trashed_dir),str(target)))


def permanent_delete_merge(trashed_dir: Path)->None:
    shutil.rmtree(Path(trashed_dir))
