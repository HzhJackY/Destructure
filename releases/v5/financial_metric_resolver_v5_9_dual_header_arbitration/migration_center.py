#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Historical-version migration center for v5.9 shared DATA_HOME.

Source may be:
- old version root containing workspace/
- workspace/ itself

Policy:
- PDFs, captures, reviews, batch/runs: migrate/preserve
- table taxonomy: merge conservatively
- metric_aliases: merge user rules into shared runtime rules
- old Merge projects: archive by default, because canonical outputs are derived
  assets and may be stale after parser/identity/order/header fixes
- cache: skip
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import shutil
from pathlib import Path
from typing import Any

from data_home import merge_metric_rules
from table_capture import analyze_column_dimensions


def _sha256(path: Path) -> str:
    h=hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda:f.read(1024*1024),b""):
            h.update(chunk)
    return h.hexdigest()


def detect_old_workspace(source: Path) -> tuple[Path, Path]:
    source=Path(source).expanduser().resolve()
    if (source/"workspace").is_dir():
        return source, source/"workspace"
    if source.name.lower()=="workspace" and source.is_dir():
        return source.parent, source
    # Also accept a data-home-like directory.
    if (source/"table_captures").is_dir() or (source/"uploads").is_dir():
        return source, source
    raise ValueError("未识别到旧版 workspace/data 目录。")


def scan_old_version(source: Path)->dict[str,Any]:
    root,ws=detect_old_workspace(source)
    def count_dirs(name):
        p=ws/name
        return len([x for x in p.iterdir() if x.is_dir() and x.name!="_trash"]) if p.exists() else 0
    def count_files(name,pattern="*"):
        p=ws/name
        return len(list(p.glob(pattern))) if p.exists() else 0

    return {
        "source_root":str(root),
        "workspace":str(ws),
        "pdf_count":count_files("uploads","*.pdf"),
        "capture_count":count_dirs("table_captures"),
        "merge_count":count_dirs("table_merges"),
        "batch_count":count_dirs("batch_runs"),
        "run_count":count_dirs("runs"),
        "review_file_count":count_files("reviews"),
        "has_taxonomy":(ws/"table_taxonomy.json").exists() or (ws/"config"/"table_taxonomy.json").exists(),
        "has_metric_aliases":(root/"metric_aliases.json").exists() or (ws/"config"/"metric_aliases.json").exists(),
        "cache_present":(ws/"cache").exists(),
    }


def _copy_file_dedup(src:Path,dst_dir:Path)->tuple[str,Path]:
    dst_dir.mkdir(parents=True,exist_ok=True)
    dst=dst_dir/src.name
    if not dst.exists():
        shutil.copy2(src,dst)
        return "COPIED",dst
    try:
        if src.stat().st_size==dst.stat().st_size and _sha256(src)==_sha256(dst):
            return "SKIPPED_IDENTICAL",dst
    except Exception:
        pass
    stem,suffix=src.stem,src.suffix
    n=2
    while True:
        candidate=dst_dir/f"{stem}__migrated{n}{suffix}"
        if not candidate.exists():
            shutil.copy2(src,candidate)
            return "COPIED_RENAMED",candidate
        n+=1


def _copy_dir_dedup(src:Path,dst_root:Path)->tuple[str,Path]:
    dst_root.mkdir(parents=True,exist_ok=True)
    dst=dst_root/src.name
    if not dst.exists():
        shutil.copytree(src,dst)
        return "COPIED",dst
    # Preserve both histories if run IDs collide.
    stamp=dt.datetime.now().strftime("%Y%m%dT%H%M%S")
    candidate=dst_root/f"{src.name}__migrated_{stamp}"
    n=2
    while candidate.exists():
        candidate=dst_root/f"{src.name}__migrated_{stamp}_{n}"
        n+=1
    shutil.copytree(src,candidate)
    return "COPIED_RENAMED",candidate


def _merge_taxonomy(target:Path,incoming:Path)->dict[str,int]:
    target_data=json.loads(target.read_text(encoding="utf-8")) if target.exists() else {"version":1,"tables":{}}
    inc=json.loads(incoming.read_text(encoding="utf-8")) if incoming.exists() else {"version":1,"tables":{}}
    added_tables=added_mappings=added_keys=0
    for table_id,table in (inc.get("tables") or {}).items():
        if table_id not in target_data.setdefault("tables",{}):
            target_data["tables"][table_id]=table
            added_tables+=1
            continue
        dst=target_data["tables"][table_id].setdefault("mappings",[])
        by_target={
            (str(m.get("canonical_section") or ""),str(m.get("canonical_item") or "")):m
            for m in dst
        }
        for m in table.get("mappings",[]):
            key=(str(m.get("canonical_section") or ""),str(m.get("canonical_item") or ""))
            if key not in by_target:
                dst.append(m)
                by_target[key]=m
                added_mappings+=1
            else:
                tgt=by_target[key]
                keys=tgt.setdefault("source_keys",[])
                for sk in m.get("source_keys",[]):
                    if sk not in keys:
                        keys.append(sk);added_keys+=1
    target.parent.mkdir(parents=True,exist_ok=True)
    target.write_text(json.dumps(target_data,ensure_ascii=False,indent=2),encoding="utf-8")
    return {"added_tables":added_tables,"added_mappings":added_mappings,"added_source_keys":added_keys}


def _upgrade_capture_metadata(run_dir:Path)->dict[str,Any]:
    result_path=run_dir/"table_capture_result.json"
    if not result_path.exists():
        return {"status":"NO_RESULT_JSON"}
    result=json.loads(result_path.read_text(encoding="utf-8"))

    # Preserve provenance; add schema metadata only.
    result.setdefault("producer_version","legacy_pre_v5.6")
    result["capture_schema_version"]="5.6"

    if "header_dimension_status" not in result or str(result.get("header_dimension_status")) in {"","UNASSESSED","None"}:
        check=analyze_column_dimensions(result.get("columns") or [])
        result["header_dimension_status"]=check["status"]
        stats=dict(result.get("stats") or {})
        stats["header_dimension_check"]=check
        result["stats"]=stats

    result_path.write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding="utf-8")

    # Upgrade machine snapshots without destroying official adjudicated output.
    for official,machine in [
        ("table_raw_long.csv","machine_capture_full_long.csv"),
        ("table_raw_wide.csv","machine_capture_full_wide.csv"),
    ]:
        src=run_dir/official;dst=run_dir/machine
        if src.exists() and not dst.exists():
            shutil.copy2(src,dst)

    try:
        from capture_library import ensure_capture_metadata
        ensure_capture_metadata(run_dir)
    except Exception:
        pass
    try:
        from reconciliation import write_reconciliation_audit
        write_reconciliation_audit(run_dir)
    except Exception:
        pass

    return {"status":"UPGRADED","header_dimension_status":result.get("header_dimension_status")}


def migrate_old_version(
    source:Path,
    data_paths:dict[str,Path],
    archive_old_merges:bool=True,
)->dict[str,Any]:
    root,ws=detect_old_workspace(source)
    started=dt.datetime.now()
    events=[]

    # PDFs
    old_uploads=ws/"uploads"
    if old_uploads.exists():
        for f in old_uploads.glob("*.pdf"):
            status,target=_copy_file_dedup(f,data_paths["uploads"])
            events.append({"type":"PDF","source":str(f),"target":str(target),"status":status})

    # Captures incl. adjudication assets.
    old_caps=ws/"table_captures"
    if old_caps.exists():
        for d in old_caps.iterdir():
            if not d.is_dir() or d.name=="_trash":continue
            copy_status,target=_copy_dir_dedup(d,data_paths["table_captures"])
            upgrade=_upgrade_capture_metadata(target)
            events.append({
                "type":"CAPTURE","source":str(d),"target":str(target),
                "status":upgrade.get("status","UPGRADED"),
                "copy_status":copy_status,
                "header_dimension_status":upgrade.get("header_dimension_status"),
            })

        old_cap_trash=old_caps/"_trash"
        if old_cap_trash.exists():
            for d in old_cap_trash.iterdir():
                if not d.is_dir():continue
                status,target=_copy_dir_dedup(d,data_paths["table_capture_trash"])
                events.append({
                    "type":"CAPTURE_TRASH","source":str(d),"target":str(target),
                    "status":status,
                })

    # Batch/runs/reviews/rule backups.
    for old_name,path_key in [
        ("batch_runs","batch_runs"),("runs","runs"),("rule_backups","rule_backups")
    ]:
        src_root=ws/old_name
        if src_root.exists():
            for d in src_root.iterdir():
                if d.is_dir():
                    status,target=_copy_dir_dedup(d,data_paths[path_key])
                    events.append({"type":old_name.upper(),"source":str(d),"target":str(target),"status":status})

    old_reviews=ws/"reviews"
    if old_reviews.exists():
        for f in old_reviews.iterdir():
            if f.is_file():
                status,target=_copy_file_dedup(f,data_paths["reviews"])
                events.append({"type":"REVIEW","source":str(f),"target":str(target),"status":status})

    # Taxonomy.
    tax_candidates=[ws/"config"/"table_taxonomy.json",ws/"table_taxonomy.json"]
    for tax in tax_candidates:
        if tax.exists():
            stats=_merge_taxonomy(data_paths["taxonomy"],tax)
            events.append({"type":"TAXONOMY","source":str(tax),"target":str(data_paths["taxonomy"]),"status":"MERGED",**stats})
            break

    # L0 metric rules.
    rules_candidates=[ws/"config"/"metric_aliases.json",root/"metric_aliases.json"]
    for rules in rules_candidates:
        if rules.exists():
            stats=merge_metric_rules(data_paths["rules"],rules)
            events.append({"type":"METRIC_RULES","source":str(rules),"target":str(data_paths["rules"]),"status":"MERGED",**stats})
            break

    # Merge projects are derived assets: archive, don't promote to current formal Merge Library.
    old_merges=ws/"table_merges"
    archived_merges=[]
    if old_merges.exists():
        legacy_root=data_paths["archive"]/f"legacy_merges_{started.strftime('%Y%m%dT%H%M%S')}"
        for d in old_merges.iterdir():
            if not d.is_dir() or d.name=="_trash":continue
            if archive_old_merges:
                status,target=_copy_dir_dedup(d,legacy_root)
                archived_merges.append(str(target))
                events.append({
                    "type":"LEGACY_MERGE","source":str(d),"target":str(target),
                    "status":"ARCHIVED_REBUILD_RECOMMENDED",
                    "copy_status":status,
                })

        old_merge_trash=old_merges/"_trash"
        if old_merge_trash.exists() and archive_old_merges:
            trash_archive=legacy_root/"_trash"
            for d in old_merge_trash.iterdir():
                if not d.is_dir():continue
                status,target=_copy_dir_dedup(d,trash_archive)
                events.append({
                    "type":"LEGACY_MERGE_TRASH","source":str(d),"target":str(target),
                    "status":"ARCHIVED",
                    "copy_status":status,
                })

    # Cache deliberately skipped.
    if (ws/"cache").exists():
        events.append({"type":"CACHE","source":str(ws/"cache"),"target":"","status":"SKIPPED_BY_POLICY"})

    finished=dt.datetime.now()
    report={
        "migration_version":"5.9",
        "source_root":str(root),
        "source_workspace":str(ws),
        "target_data_home":str(data_paths["root"]),
        "started_at":started.isoformat(timespec="seconds"),
        "finished_at":finished.isoformat(timespec="seconds"),
        "policy":{
            "captures":"MIGRATE_AND_SCHEMA_UPGRADE",
            "pdfs":"MIGRATE",
            "taxonomy":"MERGE",
            "metric_rules":"MERGE",
            "legacy_merges":"ARCHIVE_REBUILD_RECOMMENDED",
            "cache":"SKIP",
        },
        "events":events,
        "archived_merges":archived_merges,
        "summary":{},
    }
    counts={}
    for e in events:
        k=f"{e['type']}::{e['status']}"
        counts[k]=counts.get(k,0)+1
    report["summary"]=counts

    out=data_paths["migration_reports"]/f"migration_{started.strftime('%Y%m%dT%H%M%S')}.json"
    out.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding="utf-8")
    report["report_path"]=str(out)

    # update manifest
    manifest_path=data_paths["manifest"]
    manifest=json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["last_migrated_from"]=str(root)
    manifest["last_migration_report"]=str(out)
    manifest_path.write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding="utf-8")
    return report
