#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Stable shared DATA_HOME for Financial Metric Resolver.

Priority:
1. FIN_METRIC_DATA_HOME environment variable
2. data_home.json beside the application
3. ~/FinancialMetricResolverData

Code versions can live anywhere; all versions can point to the same DATA_HOME.
"""

from __future__ import annotations

import json
import os
import shutil
from pathlib import Path
from typing import Any


SCHEMA_VERSION = "6.7"


def _global_pointer_path() -> Path:
    return Path.home() / ".financial_metric_resolver" / "data_home.json"


def resolve_data_home(app_dir: Path) -> Path:
    env = str(os.environ.get("FIN_METRIC_DATA_HOME") or "").strip()
    if env:
        return Path(env).expanduser().resolve()

    # Stable user-level pointer survives code-version upgrades.
    for cfg in [_global_pointer_path(), Path(app_dir) / "data_home.json"]:
        if cfg.exists():
            try:
                data = json.loads(cfg.read_text(encoding="utf-8"))
                value = str(data.get("data_home") or "").strip()
                if value:
                    return Path(value).expanduser().resolve()
            except Exception:
                pass

    return (Path.home() / "FinancialMetricResolverData").resolve()


def save_data_home_config(app_dir: Path, data_home: Path) -> None:
    payload = {
        "data_home": str(Path(data_home).expanduser().resolve())
    }

    # Stable global pointer: future v5.7/v5.8 code folders read this automatically.
    global_path = _global_pointer_path()
    global_path.parent.mkdir(parents=True, exist_ok=True)
    global_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    # Local copy is useful when moving the whole code folder between machines.
    local_path = Path(app_dir) / "data_home.json"
    local_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def ensure_data_home(data_home: Path, bundled_rules: Path) -> dict[str, Path]:
    root = Path(data_home)
    paths = {
        "root": root,
        "uploads": root / "uploads",
        "runs": root / "runs",
        "rule_backups": root / "rule_backups",
        "reviews": root / "reviews",
        "cache": root / "cache",
        "batch_runs": root / "batch_runs",
        "table_captures": root / "table_captures",
        "table_capture_trash": root / "table_captures" / "_trash",
        "table_merges": root / "table_merges",
        "merge_trash": root / "table_merges" / "_trash",
        "config": root / "config",
        "archive": root / "archive",
        "migration_reports": root / "migration_reports",
        "runtime": root / "runtime",
        "asset_reports": root / "asset_reports",
        "text_indexes": root / "text_indexes",
        "research_exports": root / "research_exports",
        "metadata_db": root / "metadata.db",
    }
    for p in paths.values():
        if p.suffix == "":
            p.mkdir(parents=True, exist_ok=True)

    rules = paths["config"] / "metric_aliases.json"
    if not rules.exists():
        shutil.copy2(bundled_rules, rules)
    else:
        # Forward-merge bundled/new version rules without removing user aliases.
        merge_metric_rules(rules, bundled_rules)

    taxonomy = paths["config"] / "table_taxonomy.json"
    if not taxonomy.exists():
        taxonomy.write_text(
            json.dumps({"version": 1, "tables": {}}, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    manifest = root / "data_manifest.json"
    if manifest.exists():
        try:
            data = json.loads(manifest.read_text(encoding="utf-8"))
        except Exception:
            data = {}
    else:
        data = {}
    data["data_schema_version"] = SCHEMA_VERSION
    data.setdefault("created_by", "v6.1")
    data["last_opened_by"] = "v6.7"
    manifest.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

    paths["rules"] = rules
    paths["taxonomy"] = taxonomy
    paths["manifest"] = manifest
    return paths


def _merge_list(dst: list, src: list) -> list:
    out = list(dst or [])
    for x in src or []:
        if x not in out:
            out.append(x)
    return out


def merge_metric_rules(target_path: Path, incoming_path: Path) -> dict[str, Any]:
    """
    Merge metric rules conservatively:
    - keep target/user-edited values
    - add new standard metrics from incoming
    - union list-valued alias/keyword/exclude/table hints
    """
    target_path = Path(target_path)
    incoming_path = Path(incoming_path)
    target = json.loads(target_path.read_text(encoding="utf-8")) if target_path.exists() else {}
    incoming = json.loads(incoming_path.read_text(encoding="utf-8")) if incoming_path.exists() else {}

    added_metrics = 0
    merged_lists = 0
    for metric, inc_cfg in incoming.items():
        if metric not in target:
            target[metric] = inc_cfg
            added_metrics += 1
            continue
        dst_cfg = target[metric]
        for field in ["aliases", "soft_aliases", "keywords", "exclude", "table_hint"]:
            if field in inc_cfg:
                before = list(dst_cfg.get(field) or [])
                after = _merge_list(before, list(inc_cfg.get(field) or []))
                if after != before:
                    merged_lists += 1
                dst_cfg[field] = after
        # New scalar fields are adopted only when absent in user target.
        for key, value in inc_cfg.items():
            if key not in dst_cfg:
                dst_cfg[key] = value

    target_path.parent.mkdir(parents=True, exist_ok=True)
    target_path.write_text(json.dumps(target, ensure_ascii=False, indent=2), encoding="utf-8")
    return {"added_metrics": added_metrics, "merged_list_fields": merged_lists}
