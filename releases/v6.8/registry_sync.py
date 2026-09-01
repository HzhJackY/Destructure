#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Filesystem -> SQLite registry reconciliation for v6.1.

The filesystem remains the authoritative machine-evidence store. The registry is
an indexed metadata control plane and can always be rebuilt from DATA_HOME.
"""
from __future__ import annotations

import datetime as dt
import json
from pathlib import Path
from typing import Any

from metadata_registry import MetadataRegistry, now_iso


def _display_pdf_name(name: str) -> str:
    try:
        from batch_pipeline import display_pdf_name
        return str(display_pdf_name(name))
    except Exception:
        return str(name)


def _pdf_id(path: Path) -> str:
    return "PDF::" + str(path.resolve()).lower()


def _read_json(path: Path) -> dict[str, Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


class RegistrySynchronizer:
    def __init__(self, registry: MetadataRegistry, paths: dict[str, Path]):
        self.registry = registry
        self.paths = {k: Path(v) for k, v in paths.items()}

    def sync_pdfs(self) -> dict[str, Any]:
        upload_root = self.paths["uploads"]
        count = 0
        name_map: dict[str, str] = {}
        seen_ids: set[str] = set()
        for p in upload_root.glob("*.pdf") if upload_root.exists() else []:
            display = _display_pdf_name(p.name)
            company = ""; year = ""
            try:
                from batch_pipeline import infer_company_year
                company, year = infer_company_year(Path(display), "")
            except Exception:
                pass
            pid = _pdf_id(p)
            self.registry.upsert_pdf({
                "pdf_id": pid,
                "filename": p.name,
                "display_name": display,
                "company": company,
                "document_year": year,
                "size_bytes": p.stat().st_size,
                "path": str(p.resolve()),
                "modified_at": dt.datetime.fromtimestamp(p.stat().st_mtime).astimezone().isoformat(timespec="seconds"),
            })
            name_map[p.name] = pid
            name_map[display] = pid
            seen_ids.add(pid)
            count += 1
        with self.registry.connect() as conn:
            if seen_ids:
                marks=','.join('?' for _ in seen_ids)
                conn.execute(f"DELETE FROM pdf_assets WHERE pdf_id NOT IN ({marks})", tuple(sorted(seen_ids)))
            else:
                conn.execute("DELETE FROM pdf_assets")
        return {"count": count, "name_map": name_map}

    def sync_captures(self, pdf_name_map: dict[str, str] | None = None) -> dict[str, Any]:
        """Lightweight metadata scan; never opens large Capture CSV/Excel files."""
        from asset_management import ensure_asset_metadata
        try:
            from capture_library import capture_readiness
        except Exception:
            capture_readiness = None
        pdf_name_map = pdf_name_map or {}
        records = []
        root = self.paths["table_captures"]
        candidates: list[tuple[Path, bool]] = []
        if root.exists():
            for d in root.iterdir():
                if not d.is_dir():
                    continue
                if d.name == "_trash":
                    for q in d.iterdir():
                        if q.is_dir() and (q / "table_capture_result.json").exists():
                            candidates.append((q, True))
                elif (d / "table_capture_result.json").exists():
                    candidates.append((d, False))
        for run_dir, is_trash in candidates:
            result = _read_json(run_dir / "table_capture_result.json")
            meta = ensure_asset_metadata(run_dir)
            stats = result.get("stats") or {}
            pdf_name = str(result.get("pdf_name") or meta.get("source_pdf_display") or "")
            lifecycle = "TRASHED" if is_trash else str(meta.get("lifecycle_status") or "ACTIVE")
            if capture_readiness is not None:
                try:
                    ready = capture_readiness(result)
                    boundary_status = ready.get("boundary_status")
                    header_status = ready.get("header_dimension_status")
                    merge_ready = bool(ready.get("merge_ready") and lifecycle == "ACTIVE")
                except Exception:
                    boundary_status = result.get("boundary_status") or meta.get("boundary_status")
                    header_status = result.get("header_dimension_status") or meta.get("header_dimension_status")
                    merge_ready = bool(meta.get("merge_ready") and lifecycle == "ACTIVE")
            else:
                boundary_status = result.get("boundary_status") or meta.get("boundary_status")
                header_status = result.get("header_dimension_status") or meta.get("header_dimension_status")
                merge_ready = bool(meta.get("merge_ready") and lifecycle == "ACTIVE")
            rec = {
                **meta,
                "capture_id": run_dir.name, "run_id": run_dir.name,
                "run_path": str(run_dir), "run_dir": str(run_dir),
                "pdf_name": result.get("pdf_name"),
                "pdf_id": pdf_name_map.get(pdf_name) or pdf_name_map.get(_display_pdf_name(pdf_name)),
                "source_pdf_display": meta.get("source_pdf_display") or _display_pdf_name(pdf_name),
                "table_query": result.get("table_query") or meta.get("table_query"),
                "note_number": result.get("note_number"),
                "producer_version": result.get("producer_version") or meta.get("producer_version"),
                "header_parser": stats.get("header_parser") or meta.get("header_parser"),
                "lifecycle_status": lifecycle, "is_trashed": is_trash,
                "boundary_status": boundary_status,
                "header_dimension_status": header_status,
                "merge_ready": merge_ready,
            }
            self.registry.upsert_capture(rec)
            records.append(rec)
        seen_ids={str(r['capture_id']) for r in records}
        with self.registry.connect() as conn:
            if seen_ids:
                marks=','.join('?' for _ in seen_ids)
                conn.execute(f"DELETE FROM captures WHERE capture_id NOT IN ({marks})", tuple(sorted(seen_ids)))
            else:
                conn.execute("DELETE FROM captures")
        self.registry.rebuild_batch_summaries()
        return {"count": len(records)}

    def sync_merges(self) -> dict[str, Any]:
        """Lightweight Merge manifest/metadata scan; does not open canonical CSV/XLSX outputs."""
        rows = []
        root = self.paths["table_merges"]
        candidates: list[tuple[Path, bool]] = []
        if root.exists():
            for d in root.iterdir():
                if not d.is_dir():
                    continue
                if d.name == "_trash":
                    for q in d.iterdir():
                        if q.is_dir() and (q / "merge_manifest.json").exists():
                            candidates.append((q, True))
                elif (d / "merge_manifest.json").exists():
                    candidates.append((d, False))
        for run_dir, is_trash in candidates:
            manifest = _read_json(run_dir / "merge_manifest.json")
            meta = _read_json(run_dir / "merge_metadata.json")
            sources = [
                str(x.get("capture_run_id") or "")
                for x in (manifest.get("sources") or [])
                if x.get("capture_run_id")
            ]
            merged = {
                **meta,
                "merge_id": run_dir.name, "run_id": run_dir.name,
                "run_path": str(run_dir), "run_dir": str(run_dir),
                "table_id": manifest.get("table_id"),
                "source_count": len(sources),
                "is_trashed": is_trash,
                "lifecycle_status": "TRASHED" if is_trash else str(meta.get("lifecycle_status") or "ACTIVE"),
                "dependency_status": str(meta.get("dependency_status") or "CURRENT"),
                "created_at": meta.get("created_at") or dt.datetime.fromtimestamp(run_dir.stat().st_mtime).astimezone().isoformat(timespec="seconds"),
            }
            self.registry.upsert_merge(merged, sources)
            rows.append(merged)
        seen_ids={str(r['merge_id']) for r in rows}
        with self.registry.connect() as conn:
            if seen_ids:
                marks=','.join('?' for _ in seen_ids)
                conn.execute(f"DELETE FROM merge_projects WHERE merge_id NOT IN ({marks})", tuple(sorted(seen_ids)))
            else:
                conn.execute("DELETE FROM merge_projects")
        return {"count": len(rows)}

    def sync_all(self, *, reason: str = "MANUAL_SYNC") -> dict[str, Any]:
        started = now_iso()
        pdf = self.sync_pdfs()
        captures = self.sync_captures(pdf.get("name_map"))
        merges = self.sync_merges()
        finished = now_iso()
        result = {
            "reason": reason,
            "started_at": started,
            "finished_at": finished,
            "pdf_assets": pdf["count"],
            "captures": captures["count"],
            "merges": merges["count"],
            "registry_counts": self.registry.table_counts(),
        }
        self.registry.set_meta("last_full_sync_at", finished)
        self.registry.set_meta("last_full_sync_reason", reason)
        self.registry.event("REGISTRY_FULL_SYNC", asset_type="REGISTRY", payload=result)
        return result

    def bootstrap_if_needed(self) -> dict[str, Any]:
        last = self.registry.get_meta("last_full_sync_at")
        if last:
            return {"bootstrapped": False, "last_full_sync_at": last, "registry_counts": self.registry.table_counts()}
        result = self.sync_all(reason="V6_1_INITIAL_BOOTSTRAP")
        return {"bootstrapped": True, **result}
