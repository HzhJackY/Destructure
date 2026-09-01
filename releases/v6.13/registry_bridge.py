#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Best-effort registry bridge for legacy core write paths.

Core extraction/review modules may call these hooks without depending on
Streamlit or the service layer. Failures never corrupt/abort machine evidence;
registry can be rebuilt from DATA_HOME later.
"""
from __future__ import annotations

import json
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

_SYNC_LOCK = threading.RLock()
_SYNC_ATTEMPTS = 4


def _read(path: Path) -> dict[str, Any]:
    try:return json.loads(path.read_text(encoding='utf-8'))
    except Exception:return {}


def _find_data_home(path: Path) -> Optional[Path]:
    p=Path(path).resolve()
    for parent in [p,*p.parents]:
        if parent.name in {'table_captures','table_merges','uploads','batch_runs'}:
            return parent.parent
    return None


def _registry(path: Path):
    root=_find_data_home(path)
    if root is None:return None
    try:
        from metadata_registry import MetadataRegistry
        return MetadataRegistry(root/'metadata.db')
    except Exception:return None


def _write_json_atomic(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    staged = path.with_suffix(path.suffix + ".tmp")
    staged.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )
    staged.replace(path)


def _record_sync_error(path: Path, operation: str, exc: BaseException) -> None:
    root = _find_data_home(path)
    if root is None:
        return
    error_path = root / "runtime" / "registry_sync_errors.jsonl"
    error_path.parent.mkdir(parents=True, exist_ok=True)
    event = {
        "at": datetime.now(timezone.utc).isoformat(),
        "operation": operation,
        "path": str(Path(path).resolve()),
        "error_type": type(exc).__name__,
        "error": str(exc),
    }
    with error_path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(event, ensure_ascii=False, default=str) + "\n")


def _sync_capture_once(run_dir: Path) -> dict[str, Any]:
    run_dir=Path(run_dir); reg=_registry(run_dir)
    if reg is None:
        raise RuntimeError("REGISTRY_UNAVAILABLE")
    result=_read(run_dir/'table_capture_result.json');meta=_read(run_dir/'capture_metadata.json')
    stats=result.get('stats') or {}
    lifecycle=str(meta.get('lifecycle_status') or 'ACTIVE')
    root=_find_data_home(run_dir)
    pdf_name=str(result.get('pdf_name') or '')
    pdf_id=None
    source_path=str(stats.get('source_pdf_path') or '').strip()
    if source_path and Path(source_path).is_file():
        pdf_id='PDF::'+str(Path(source_path).resolve()).lower()
    elif root is not None and pdf_name:
        candidate=root/'uploads'/pdf_name
        if candidate.is_file():
            pdf_id='PDF::'+str(candidate.resolve()).lower()
    # Registry sync registers immutable physical evidence only. Final
    # quality/review/merge state is produced by CaptureCompletionService.
    # On later re-syncs preserve that authoritative projection instead of
    # re-running a second readiness engine.
    with reg.connect() as conn:
        governed = conn.execute(
            """SELECT quality_status FROM capture_versions
               WHERE capture_id=?""",
            (run_dir.name,),
        ).fetchone()
        existing_capture = conn.execute(
            "SELECT merge_ready FROM captures WHERE capture_id=?",
            (run_dir.name,),
        ).fetchone()
    readiness={
        'boundary_status':result.get('boundary_status') or meta.get('boundary_status'),
        'header_dimension_status':result.get('header_dimension_status') or meta.get('header_dimension_status'),
        'semantic_status':meta.get('semantic_status') or 'UNASSESSED',
        'capture_quality_status':(
            governed['quality_status'] if governed else 'UNASSESSED'
        ),
        'mixed_cell_count':meta.get('mixed_cell_count'),
        'unresolved_implicit_rows':meta.get('unresolved_implicit_rows'),
        'merge_blockers':(
            list(meta.get('merge_blockers') or [])
            if governed else ['PENDING_CAPTURE_COMPLETION']
        ),
        'merge_ready':bool(existing_capture['merge_ready']) if governed and existing_capture else False,
    }
    meta.update({
        'boundary_status':readiness.get('boundary_status'),
        'header_dimension_status':readiness.get('header_dimension_status'),
        'semantic_status':readiness.get('semantic_status'),
        'capture_quality_status':readiness.get('capture_quality_status'),
        'mixed_cell_count':readiness.get('mixed_cell_count'),
        'unresolved_implicit_rows':readiness.get('unresolved_implicit_rows'),
        'merge_blockers':list(readiness.get('merge_blockers') or []),
        'merge_ready':bool(readiness.get('merge_ready')) and lifecycle=='ACTIVE',
    })
    _write_json_atomic(run_dir/'capture_metadata.json', meta)
    row={
        **meta,
        'capture_id':run_dir.name,'run_path':str(run_dir),'run_id':run_dir.name,'run_dir':str(run_dir),
        'pdf_id':pdf_id,'pdf_name':result.get('pdf_name'),'source_pdf_display':meta.get('source_pdf_display') or result.get('pdf_name'),
        'table_query':result.get('table_query') or meta.get('table_query'),'note_number':result.get('note_number'),
        'producer_version':result.get('producer_version') or meta.get('producer_version'),
        'header_parser':stats.get('header_parser') or meta.get('header_parser'),
        'lifecycle_status':lifecycle,'is_trashed':lifecycle=='TRASHED' or run_dir.parent.name=='_trash',
        'boundary_status':readiness.get('boundary_status'),
        'header_dimension_status':readiness.get('header_dimension_status'),
        'merge_ready':meta['merge_ready'],
    }
    reg.upsert_capture(row);reg.rebuild_batch_summaries()
    return {
        "status": "OK",
        "capture_id": run_dir.name,
        "capture_quality_status": readiness.get("capture_quality_status"),
        "merge_ready": meta["merge_ready"],
    }


def sync_capture_run(run_dir: Path) -> dict[str, Any]:
    """Serialize concurrent completion writes and report every terminal failure."""
    run_dir = Path(run_dir)
    last_error: BaseException | None = None
    with _SYNC_LOCK:
        for attempt in range(1, _SYNC_ATTEMPTS + 1):
            try:
                return _sync_capture_once(run_dir)
            except Exception as exc:
                last_error = exc
                if attempt < _SYNC_ATTEMPTS:
                    time.sleep(0.1 * attempt)
    assert last_error is not None
    _record_sync_error(run_dir, "sync_capture_run", last_error)
    return {
        "status": "REGISTRY_SYNC_FAILED",
        "run_dir": str(run_dir),
        "attempts": _SYNC_ATTEMPTS,
        "error_type": type(last_error).__name__,
        "error": str(last_error),
    }


def _sync_merge_once(run_dir: Path) -> dict[str, Any]:
    run_dir=Path(run_dir);reg=_registry(run_dir)
    if reg is None:
        raise RuntimeError("REGISTRY_UNAVAILABLE")
    manifest=_read(run_dir/'merge_manifest.json');meta=_read(run_dir/'merge_metadata.json')
    sources=[str(x.get('capture_run_id') or '') for x in (manifest.get('sources') or []) if x.get('capture_run_id')]
    reg.upsert_merge({
        **meta,'merge_id':run_dir.name,'run_path':str(run_dir),'run_id':run_dir.name,'run_dir':str(run_dir),
        'table_id':manifest.get('table_id'),'source_count':len(sources),
        'is_trashed':run_dir.parent.name=='_trash','lifecycle_status':'TRASHED' if run_dir.parent.name=='_trash' else meta.get('lifecycle_status','ACTIVE'),
    },sources)
    return {"status": "OK", "merge_id": run_dir.name}


def sync_merge_run(run_dir: Path) -> dict[str, Any]:
    run_dir = Path(run_dir)
    last_error: BaseException | None = None
    with _SYNC_LOCK:
        for attempt in range(1, _SYNC_ATTEMPTS + 1):
            try:
                return _sync_merge_once(run_dir)
            except Exception as exc:
                last_error = exc
                if attempt < _SYNC_ATTEMPTS:
                    time.sleep(0.1 * attempt)
    assert last_error is not None
    _record_sync_error(run_dir, "sync_merge_run", last_error)
    return {
        "status": "REGISTRY_SYNC_FAILED",
        "run_dir": str(run_dir),
        "attempts": _SYNC_ATTEMPTS,
        "error_type": type(last_error).__name__,
        "error": str(last_error),
    }
