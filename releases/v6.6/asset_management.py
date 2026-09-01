#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Legacy-compatible file lifecycle primitives used behind v6.1 services."""
from __future__ import annotations

import datetime as dt
import json
import shutil
from collections import defaultdict
from pathlib import Path
from typing import Any, Iterable, Optional

import pandas as pd

LIFECYCLE_ACTIVE = "ACTIVE"
LIFECYCLE_INVALIDATED = "INVALIDATED"
LIFECYCLE_TRASHED = "TRASHED"
VALID_LIFECYCLES = {LIFECYCLE_ACTIVE, LIFECYCLE_INVALIDATED, LIFECYCLE_TRASHED}

INVALIDATION_REASON_CODES = [
    "PARSER_ERROR",
    "HEADER_TOPOLOGY_ERROR",
    "WRONG_TABLE_LOCATION",
    "WRONG_BOUNDARY",
    "WRONG_SOURCE_PDF",
    "DUPLICATE_CAPTURE",
    "TEST_RUN",
    "OTHER",
]


def now_iso() -> str:
    return dt.datetime.now().astimezone().isoformat(timespec="seconds")


def read_json(path: Path, default: Any = None) -> Any:
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except Exception:
        return {} if default is None else default


def write_json(path: Path, payload: Any) -> None:
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _capture_result(run_dir: Path) -> dict[str, Any]:
    return read_json(Path(run_dir) / "table_capture_result.json", {})


def _capture_meta_path(run_dir: Path) -> Path:
    return Path(run_dir) / "capture_metadata.json"


def _infer_company_year(pdf_name: str) -> tuple[str, str]:
    try:
        from batch_pipeline import infer_company_year
        return infer_company_year(Path(str(pdf_name or "")), "")
    except Exception:
        return "", ""


def ensure_asset_metadata(
    run_dir: Path,
    *,
    batch_id: Optional[str] = None,
    supersedes_capture_id: Optional[str] = None,
) -> dict[str, Any]:
    """Backfill v6 lifecycle/index metadata without destroying prior fields."""
    run_dir = Path(run_dir)
    path = _capture_meta_path(run_dir)
    meta = read_json(path, {}) if path.exists() else {}
    result = _capture_result(run_dir)
    stats = result.get("stats") or {}
    pdf_name = str(result.get("pdf_name") or meta.get("source_pdf_display") or "")
    company, year = _infer_company_year(pdf_name)

    created = meta.get("created_at") or dt.datetime.fromtimestamp(run_dir.stat().st_mtime).astimezone().isoformat(timespec="seconds")
    default_batch = f"LEGACY_SINGLE::{run_dir.name}"
    meta.setdefault("run_id", run_dir.name)
    meta.setdefault("lifecycle_status", LIFECYCLE_ACTIVE)
    meta.setdefault("pre_trash_status", None)
    meta.setdefault("batch_id", batch_id or stats.get("capture_batch_id") or default_batch)
    meta.setdefault("producer_version", str(result.get("producer_version") or "legacy"))
    meta.setdefault("header_parser", str(stats.get("header_parser") or "legacy"))
    meta.setdefault("company", company)
    meta.setdefault("document_year", year)
    meta.setdefault("created_at", created)
    meta.setdefault("invalidated_at", None)
    meta.setdefault("invalidation_reason_code", None)
    meta.setdefault("invalidation_note", None)
    meta.setdefault("trashed_at", None)
    meta.setdefault("restored_at", None)
    meta.setdefault("supersedes_capture_id", supersedes_capture_id)
    meta.setdefault("superseded_by_capture_id", None)
    meta.setdefault("asset_schema_version", "6.1")
    write_json(path, meta)
    return meta


def set_capture_batch(run_dir: Path, batch_id: str, *, supersedes_capture_id: Optional[str] = None) -> dict[str, Any]:
    meta = ensure_asset_metadata(run_dir, batch_id=batch_id, supersedes_capture_id=supersedes_capture_id)
    meta["batch_id"] = str(batch_id)
    if supersedes_capture_id is not None:
        meta["supersedes_capture_id"] = str(supersedes_capture_id)
    write_json(_capture_meta_path(run_dir), meta)
    return meta


def capture_lifecycle(run_dir: Path) -> str:
    return str(ensure_asset_metadata(run_dir).get("lifecycle_status") or LIFECYCLE_ACTIVE)


def _iter_capture_dirs(root: Path, include_trash: bool = False):
    root = Path(root)
    if not root.exists():
        return
    for p in root.iterdir():
        if not p.is_dir():
            continue
        if p.name == "_trash":
            if include_trash:
                for q in p.iterdir():
                    if q.is_dir() and (q / "table_capture_result.json").exists():
                        yield q, True
            continue
        if (p / "table_capture_result.json").exists():
            yield p, False


def capture_asset_record(run_dir: Path, *, is_trashed: bool = False) -> dict[str, Any]:
    from capture_library import capture_record
    run_dir = Path(run_dir)
    try:
        rec = capture_record(run_dir)
    except Exception:
        rec = {"run_id": run_dir.name, "run_dir": str(run_dir)}
    meta = ensure_asset_metadata(run_dir)
    result = _capture_result(run_dir)
    lifecycle = LIFECYCLE_TRASHED if is_trashed else str(meta.get("lifecycle_status") or LIFECYCLE_ACTIVE)
    return {
        **rec,
        **meta,
        "run_id": run_dir.name,
        "run_dir": str(run_dir),
        "lifecycle_status": lifecycle,
        "is_trashed": bool(is_trashed),
        "producer_version": meta.get("producer_version") or result.get("producer_version"),
        "header_parser": meta.get("header_parser") or (result.get("stats") or {}).get("header_parser"),
        "company": meta.get("company"),
        "document_year": meta.get("document_year"),
        "batch_id": meta.get("batch_id"),
    }


def list_capture_assets(table_capture_dir: Path, *, include_trash: bool = False) -> list[dict[str, Any]]:
    rows = [capture_asset_record(p, is_trashed=trash) for p, trash in _iter_capture_dirs(table_capture_dir, include_trash)]
    rows.sort(key=lambda r: str(r.get("created_at") or ""), reverse=True)
    return rows


def _find_dependent_merges(capture_run_ids: set[str], merge_root: Path) -> list[dict[str, Any]]:
    deps = []
    merge_root = Path(merge_root)
    if not merge_root.exists():
        return deps
    for d in merge_root.iterdir():
        if not d.is_dir() or d.name == "_trash" or not (d / "merge_manifest.json").exists():
            continue
        manifest = read_json(d / "merge_manifest.json", {})
        used = {
            str(s.get("capture_run_id") or "")
            for s in (manifest.get("sources") or [])
        }
        hit = sorted(capture_run_ids & used)
        if hit:
            deps.append({"merge_run_id": d.name, "run_dir": str(d), "capture_run_ids": hit})
    return deps


def dependency_impact(capture_run_ids: Iterable[str], merge_root: Path) -> dict[str, Any]:
    ids = {str(x) for x in capture_run_ids}
    deps = _find_dependent_merges(ids, merge_root)
    return {
        "capture_count": len(ids),
        "dependent_merge_count": len(deps),
        "dependent_merges": deps,
    }


def _mark_merges_stale(capture_run_ids: set[str], merge_root: Path, reason: str) -> list[str]:
    affected = []
    for dep in _find_dependent_merges(capture_run_ids, merge_root):
        d = Path(dep["run_dir"])
        path = d / "merge_metadata.json"
        meta = read_json(path, {})
        stale = sorted(set(meta.get("stale_capture_run_ids") or []) | set(dep["capture_run_ids"]))
        meta["dependency_status"] = "STALE_SOURCE_INVALIDATED"
        meta["stale_capture_run_ids"] = stale
        meta["stale_reason"] = reason
        meta["stale_at"] = now_iso()
        write_json(path, meta)
        affected.append(d.name)
    return affected


def invalidate_captures(
    run_dirs: Iterable[Path],
    *,
    reason_code: str,
    note: str,
    merge_root: Path,
) -> dict[str, Any]:
    if reason_code not in INVALIDATION_REASON_CODES:
        raise ValueError(f"Unknown invalidation reason: {reason_code}")
    changed = []
    ids = set()
    ts = now_iso()
    for d in run_dirs:
        d = Path(d)
        if not d.exists():
            continue
        meta = ensure_asset_metadata(d)
        meta["lifecycle_status"] = LIFECYCLE_INVALIDATED
        meta["invalidated_at"] = ts
        meta["invalidation_reason_code"] = reason_code
        meta["invalidation_note"] = str(note or "")
        meta["asset_updated_at"] = ts
        write_json(_capture_meta_path(d), meta)
        changed.append(d.name)
        ids.add(d.name)
    affected = _mark_merges_stale(ids, merge_root, f"{reason_code}: {note}")
    return {"invalidated": changed, "stale_merges": affected}


def reactivate_captures(run_dirs: Iterable[Path]) -> dict[str, Any]:
    changed = []
    ts = now_iso()
    for d in run_dirs:
        d = Path(d)
        if not d.exists():
            continue
        meta = ensure_asset_metadata(d)
        meta["lifecycle_status"] = LIFECYCLE_ACTIVE
        meta["reactivated_at"] = ts
        meta["asset_updated_at"] = ts
        write_json(_capture_meta_path(d), meta)
        changed.append(d.name)
    return {"reactivated": changed}


def trash_captures(run_dirs: Iterable[Path], trash_dir: Path, *, merge_root: Path) -> dict[str, Any]:
    moved = []
    ids = set()
    ts = now_iso()
    trash_dir = Path(trash_dir)
    trash_dir.mkdir(parents=True, exist_ok=True)
    for d in run_dirs:
        d = Path(d)
        if not d.exists():
            continue
        meta = ensure_asset_metadata(d)
        meta["pre_trash_status"] = meta.get("lifecycle_status") or LIFECYCLE_ACTIVE
        meta["lifecycle_status"] = LIFECYCLE_TRASHED
        meta["trashed_at"] = ts
        write_json(_capture_meta_path(d), meta)
        target = trash_dir / d.name
        if target.exists():
            target = trash_dir / f"{d.name}__{dt.datetime.now().strftime('%Y%m%dT%H%M%S')}"
        target = Path(shutil.move(str(d), str(target)))
        moved.append(str(target))
        ids.add(d.name)
    affected = _mark_merges_stale(ids, merge_root, "SOURCE_CAPTURE_TRASHED")
    return {"trashed": moved, "stale_merges": affected}


def restore_trashed_captures(trashed_dirs: Iterable[Path], capture_root: Path) -> dict[str, Any]:
    restored = []
    capture_root = Path(capture_root)
    ts = now_iso()
    for d in trashed_dirs:
        d = Path(d)
        if not d.exists():
            continue
        meta = ensure_asset_metadata(d)
        status = meta.get("pre_trash_status") or LIFECYCLE_ACTIVE
        if status not in {LIFECYCLE_ACTIVE, LIFECYCLE_INVALIDATED}:
            status = LIFECYCLE_ACTIVE
        meta["lifecycle_status"] = status
        meta["restored_at"] = ts
        meta["trashed_at"] = None
        write_json(_capture_meta_path(d), meta)
        target = capture_root / d.name
        if target.exists():
            target = capture_root / f"{d.name}__restored_{dt.datetime.now().strftime('%Y%m%dT%H%M%S')}"
        target = Path(shutil.move(str(d), str(target)))
        restored.append(str(target))
    return {"restored": restored}


def purge_trashed_captures(trashed_dirs: Iterable[Path]) -> dict[str, Any]:
    deleted = []
    for d in trashed_dirs:
        d = Path(d)
        if d.exists():
            shutil.rmtree(d)
            deleted.append(d.name)
    return {"purged": deleted}


def batch_summaries(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for r in records:
        groups[str(r.get("batch_id") or f"LEGACY_SINGLE::{r.get('run_id')}")].append(r)
    rows = []
    for batch_id, items in groups.items():
        statuses = [str(x.get("lifecycle_status") or LIFECYCLE_ACTIVE) for x in items]
        created = sorted(str(x.get("created_at") or "") for x in items)
        tables = sorted({str(x.get("table_query") or "") for x in items if x.get("table_query")})
        versions = sorted({str(x.get("producer_version") or "") for x in items if x.get("producer_version")})
        rows.append({
            "batch_id": batch_id,
            "capture_count": len(items),
            "active": statuses.count(LIFECYCLE_ACTIVE),
            "invalidated": statuses.count(LIFECYCLE_INVALIDATED),
            "trashed": statuses.count(LIFECYCLE_TRASHED),
            "table_query": " | ".join(tables[:3]),
            "producer_versions": " | ".join(versions),
            "created_at": created[0] if created else "",
            "last_created_at": created[-1] if created else "",
        })
    rows.sort(key=lambda r: r["last_created_at"], reverse=True)
    return rows


def capture_dirs_for_batch(records: list[dict[str, Any]], batch_id: str) -> list[Path]:
    return [Path(r["run_dir"]) for r in records if str(r.get("batch_id")) == str(batch_id) and not r.get("is_trashed")]


def list_merge_assets(merge_root: Path, *, include_trash: bool = False) -> list[dict[str, Any]]:
    from merge_library import merge_record
    rows = []
    root = Path(merge_root)
    for d in root.iterdir() if root.exists() else []:
        if not d.is_dir():
            continue
        if d.name == "_trash":
            if include_trash:
                for q in d.iterdir():
                    if q.is_dir() and (q / "merge_manifest.json").exists():
                        rec = merge_record(q)
                        rec["lifecycle_status"] = "TRASHED"
                        rec["is_trashed"] = True
                        rows.append(rec)
            continue
        if (d / "merge_manifest.json").exists():
            rec = merge_record(d)
            rec["lifecycle_status"] = str(rec.get("lifecycle_status") or "ACTIVE")
            rec["is_trashed"] = False
            rows.append(rec)
    rows.sort(key=lambda r: str(r.get("created_at") or ""), reverse=True)
    return rows


def trash_merges(run_dirs: Iterable[Path], trash_dir: Path) -> dict[str, Any]:
    from merge_library import soft_delete_merge
    moved = []
    for d in run_dirs:
        d = Path(d)
        if d.exists():
            moved.append(str(soft_delete_merge(d, trash_dir)))
    return {"trashed": moved}


def restore_merges(run_dirs: Iterable[Path], merge_root: Path) -> dict[str, Any]:
    from merge_library import restore_merge
    restored = []
    for d in run_dirs:
        d = Path(d)
        if d.exists():
            restored.append(str(restore_merge(d, merge_root)))
    return {"restored": restored}


def purge_merges(run_dirs: Iterable[Path]) -> dict[str, Any]:
    deleted = []
    for d in run_dirs:
        d = Path(d)
        if d.exists():
            shutil.rmtree(d)
            deleted.append(d.name)
    return {"purged": deleted}


def pdf_asset_records(upload_root: Path, capture_records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    refs = defaultdict(list)
    for r in capture_records:
        name = str(r.get("pdf_name") or r.get("source_pdf_display") or "")
        if name:
            refs[name].append(r.get("run_id"))
    rows=[]
    for p in sorted(Path(upload_root).glob("*.pdf"), key=lambda x:x.stat().st_mtime, reverse=True):
        display = p.name
        try:
            from batch_pipeline import display_pdf_name
            display = display_pdf_name(p.name)
        except Exception:
            pass
        company, year = _infer_company_year(display)
        ref_ids = refs.get(p.name, []) + refs.get(display, [])
        rows.append({
            "filename": p.name,
            "display_name": display,
            "company": company,
            "document_year": year,
            "size_mb": round(p.stat().st_size/1024/1024, 2),
            "capture_reference_count": len(set(ref_ids)),
            "capture_run_ids": " | ".join(sorted(set(str(x) for x in ref_ids if x))),
            "modified_at": dt.datetime.fromtimestamp(p.stat().st_mtime).astimezone().isoformat(timespec="seconds"),
            "path": str(p),
        })
    return rows


def export_asset_inventory(records: list[dict[str, Any]], output_dir: Path) -> Path:
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    path = output_dir / f"asset_inventory_{dt.datetime.now().strftime('%Y%m%dT%H%M%S')}.csv"
    pd.DataFrame(records).to_csv(path, index=False, encoding="utf-8-sig")
    return path


def new_batch_id(prefix: str = "TABLE_CAPTURE_BATCH") -> str:
    return f"{prefix}_{dt.datetime.now().strftime('%Y%m%dT%H%M%S')}"


def _resolve_source_pdf(run_dir: Path, upload_root: Path) -> Optional[Path]:
    result = _capture_result(run_dir)
    stats = result.get("stats") or {}
    source = str(stats.get("source_pdf_path") or "").strip()
    if source and Path(source).exists():
        return Path(source)
    pdf_name = str(result.get("pdf_name") or "")
    exact = Path(upload_root) / pdf_name
    if exact.exists():
        return exact
    try:
        from batch_pipeline import display_pdf_name
        target_display = display_pdf_name(pdf_name)
        for p in Path(upload_root).glob("*.pdf"):
            if display_pdf_name(p.name) == target_display:
                return p
    except Exception:
        pass
    return None


def rerun_capture_assets(
    run_dirs: Iterable[Path],
    *,
    capture_root: Path,
    upload_root: Path,
    parser_mode: str = "AUTO",
    batch_id: Optional[str] = None,
    progress_callback=None,
) -> dict[str, Any]:
    """Re-capture selected assets from their original PDFs without overwriting history."""
    from table_capture import capture_named_table, write_capture_artifacts
    from capture_library import initialize_capture_library_run
    try:
        from batch_pipeline import display_pdf_name
    except Exception:
        display_pdf_name = lambda x: str(x)

    batch_id = batch_id or new_batch_id("RERUN_BATCH")
    outputs=[]
    failures=[]
    dirs=[Path(x) for x in run_dirs]
    for idx, old_dir in enumerate(dirs, 1):
        try:
            result_old=_capture_result(old_dir)
            source_pdf=_resolve_source_pdf(old_dir, upload_root)
            if source_pdf is None:
                raise FileNotFoundError("原始 PDF 不可用")
            table_query=str(result_old.get("table_query") or "").strip()
            if not table_query:
                raise ValueError("旧 Capture 缺少 table_query")
            start_page=int(result_old.get("start_page") or 1)
            end_page=int(result_old.get("end_page") or start_page)
            stamp=dt.datetime.now().strftime("%Y%m%dT%H%M%S_%f")
            safe_source=Path(display_pdf_name(source_pdf.name)).stem.replace("/","_").replace("\\","_")[:65]
            safe_title=table_query.replace("/","_").replace("\\","_")[:55]
            new_dir=Path(capture_root)/f"{safe_source}__{safe_title}__rerun_{stamp}"
            new_result=capture_named_table(
                pdf_path=source_pdf,
                table_query=table_query,
                note_number=result_old.get("note_number") or None,
                start_page_override=start_page,
                max_pages=max(2,end_page-start_page+3),
                header_parser_mode=parser_mode,
            )
            write_capture_artifacts(new_dir,new_result)
            initialize_capture_library_run(
                new_dir,
                source_pdf_display=display_pdf_name(source_pdf.name),
                table_query=table_query,
                batch_id=batch_id,
                supersedes_capture_id=old_dir.name,
            )
            new_meta=ensure_asset_metadata(new_dir,batch_id=batch_id,supersedes_capture_id=old_dir.name)
            old_meta=ensure_asset_metadata(old_dir)
            old_meta["superseded_by_capture_id"]=new_dir.name
            old_meta["asset_updated_at"]=now_iso()
            write_json(_capture_meta_path(old_dir),old_meta)
            outputs.append(str(new_dir))
            if progress_callback:
                progress_callback({"index":idx,"total":len(dirs),"status":"SUCCESS","source":old_dir.name,"new":new_dir.name})
        except Exception as exc:
            failures.append({"source":old_dir.name,"error":f"{type(exc).__name__}: {exc}"})
            if progress_callback:
                progress_callback({"index":idx,"total":len(dirs),"status":"FAILED","source":old_dir.name,"error":str(exc)})
    return {"batch_id":batch_id,"created":outputs,"failures":failures}


def refresh_merge_dependency_statuses(capture_root: Path, merge_root: Path) -> dict[str, Any]:
    status_by_id={}
    for r in list_capture_assets(capture_root,include_trash=True):
        status_by_id[str(r.get("run_id"))]=str(r.get("lifecycle_status") or LIFECYCLE_ACTIVE)
    updated=[]
    for d in Path(merge_root).iterdir() if Path(merge_root).exists() else []:
        if not d.is_dir() or d.name=="_trash" or not (d/"merge_manifest.json").exists():
            continue
        manifest=read_json(d/"merge_manifest.json",{})
        bad=[]
        missing=[]
        for s in manifest.get("sources") or []:
            rid=str(s.get("capture_run_id") or "")
            status=status_by_id.get(rid)
            if status is None:
                missing.append(rid)
            elif status!=LIFECYCLE_ACTIVE:
                bad.append(rid)
        meta_path=d/"merge_metadata.json"
        meta=read_json(meta_path,{})
        if bad or missing:
            meta["dependency_status"]="STALE_SOURCE_INVALIDATED" if bad else "STALE_SOURCE_MISSING"
            meta["stale_capture_run_ids"]=sorted(set(bad+missing))
        else:
            meta["dependency_status"]="CURRENT"
            meta["stale_capture_run_ids"]=[]
            meta["stale_reason"]=None
        meta["dependency_checked_at"]=now_iso()
        write_json(meta_path,meta)
        updated.append({"merge_run_id":d.name,"dependency_status":meta["dependency_status"],"stale_capture_run_ids":meta["stale_capture_run_ids"]})
    return {"updated":updated}
