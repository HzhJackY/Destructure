#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Best-effort registry bridge for legacy core write paths.

Core extraction/review modules may call these hooks without depending on
Streamlit or the service layer. Failures never corrupt/abort machine evidence;
registry can be rebuilt from DATA_HOME later.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Optional


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


def sync_capture_run(run_dir: Path) -> None:
    try:
        run_dir=Path(run_dir); reg=_registry(run_dir)
        if reg is None:return
        result=_read(run_dir/'table_capture_result.json');meta=_read(run_dir/'capture_metadata.json')
        stats=result.get('stats') or {}
        lifecycle=str(meta.get('lifecycle_status') or 'ACTIVE')
        root=_find_data_home(run_dir)
        pdf_name=str(result.get('pdf_name') or '')
        pdf_id=None
        source_path=str(stats.get('source_pdf_path') or '').strip()
        if source_path and Path(source_path).exists():
            pdf_id='PDF::'+str(Path(source_path).resolve()).lower()
        elif root is not None and pdf_name:
            candidate=root/'uploads'/pdf_name
            if candidate.exists():
                pdf_id='PDF::'+str(candidate.resolve()).lower()
        row={
            **meta,
            'capture_id':run_dir.name,'run_path':str(run_dir),'run_id':run_dir.name,'run_dir':str(run_dir),
            'pdf_id':pdf_id,'pdf_name':result.get('pdf_name'),'source_pdf_display':meta.get('source_pdf_display') or result.get('pdf_name'),
            'table_query':result.get('table_query') or meta.get('table_query'),'note_number':result.get('note_number'),
            'producer_version':result.get('producer_version') or meta.get('producer_version'),
            'header_parser':stats.get('header_parser') or meta.get('header_parser'),
            'lifecycle_status':lifecycle,'is_trashed':lifecycle=='TRASHED' or run_dir.parent.name=='_trash',
            'boundary_status':result.get('boundary_status') or meta.get('boundary_status'),
            'header_dimension_status':result.get('header_dimension_status') or meta.get('header_dimension_status'),
            'merge_ready':bool(meta.get('merge_ready')) and lifecycle=='ACTIVE',
        }
        reg.upsert_capture(row);reg.rebuild_batch_summaries()
    except Exception:
        return


def sync_merge_run(run_dir: Path) -> None:
    try:
        run_dir=Path(run_dir);reg=_registry(run_dir)
        if reg is None:return
        manifest=_read(run_dir/'merge_manifest.json');meta=_read(run_dir/'merge_metadata.json')
        sources=[str(x.get('capture_run_id') or '') for x in (manifest.get('sources') or []) if x.get('capture_run_id')]
        reg.upsert_merge({
            **meta,'merge_id':run_dir.name,'run_path':str(run_dir),'run_id':run_dir.name,'run_dir':str(run_dir),
            'table_id':manifest.get('table_id'),'source_count':len(sources),
            'is_trashed':run_dir.parent.name=='_trash','lifecycle_status':'TRASHED' if run_dir.parent.name=='_trash' else meta.get('lifecycle_status','ACTIVE'),
        },sources)
    except Exception:
        return
