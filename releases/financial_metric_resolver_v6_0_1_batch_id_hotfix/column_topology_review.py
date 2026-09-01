#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Safe manual column-topology adjudication for v5.9.

Scope:
- KEEP
- DROP_DUPLICATE / DROP_FALSE_COLUMN

It intentionally does not concatenate conflicting physical value fragments.
When a true physical-column merge is required, use parser selection or a future
explicit merge adjudicator rather than guessing values.
"""

from __future__ import annotations

import datetime as dt
import json
from pathlib import Path
from typing import Any

from table_capture import analyze_column_dimensions
from header_review import rematerialize_official_capture


def _load(run_dir:Path)->dict[str,Any]:
    return json.loads((Path(run_dir)/"table_capture_result.json").read_text(encoding="utf-8"))


def _save(run_dir:Path,data:dict[str,Any])->None:
    (Path(run_dir)/"table_capture_result.json").write_text(
        json.dumps(data,ensure_ascii=False,indent=2),encoding="utf-8"
    )


def apply_column_topology_review(
    run_dir:Path,
    actions:list[dict[str,Any]],
    reviewer_note:str="",
)->dict[str,Any]:
    run_dir=Path(run_dir)
    result=_load(run_dir)
    machine_cols=sorted(result.get("columns") or [],key=lambda c:int(c.get("ordinal",0)))
    action_map={int(x["ordinal"]):str(x.get("action") or "KEEP").upper() for x in actions}

    active=[]
    dropped=[]
    for c in machine_cols:
        ordinal=int(c.get("ordinal",0))
        action=action_map.get(ordinal,"KEEP")
        if action in {"DROP","DROP_DUPLICATE","DROP_FALSE_COLUMN"}:
            dropped.append(ordinal)
        elif action=="KEEP":
            active.append(ordinal)
        else:
            raise ValueError(f"不支持的列拓扑动作：ordinal={ordinal}, action={action}")

    if not active:
        raise ValueError("列拓扑复核不能删除全部逻辑列。")

    active_cols=[c for c in machine_cols if int(c.get("ordinal",0)) in set(active)]
    check=analyze_column_dimensions(active_cols)

    review={
        "status":"HUMAN_CONFIRMED",
        "active_ordinals":active,
        "dropped_ordinals":dropped,
        "actions":[
            {"ordinal":int(c.get("ordinal",0)),"action":action_map.get(int(c.get("ordinal",0)),"KEEP")}
            for c in machine_cols
        ],
        "reviewed_at":dt.datetime.now().isoformat(timespec="seconds"),
        "reviewer_note":str(reviewer_note or ""),
        "dimension_check_after_topology":check,
        "contract":"SAFE_KEEP_DROP_ONLY_NO_VALUE_CONCATENATION",
    }
    (run_dir/"column_topology_review.json").write_text(
        json.dumps(review,ensure_ascii=False,indent=2),encoding="utf-8"
    )

    result["column_topology_review"]=review
    # Existing dimension review may reference columns that were dropped; clear it.
    result["header_review"]=None
    (run_dir/"header_review.json").unlink(missing_ok=True)
    result["header_dimension_status"]=(
        "HUMAN_CONFIRMED" if not check["issues"] else "REVIEW_REQUIRED"
    )
    _save(run_dir,result)
    materialized=rematerialize_official_capture(run_dir)
    return {**review,**materialized}


def reset_column_topology_review(run_dir:Path)->dict[str,Any]:
    run_dir=Path(run_dir)
    result=_load(run_dir)
    result["column_topology_review"]=None
    result["header_review"]=None
    (run_dir/"column_topology_review.json").unlink(missing_ok=True)
    (run_dir/"header_review.json").unlink(missing_ok=True)
    check=analyze_column_dimensions(result.get("columns") or [])
    result["header_dimension_status"]=check["status"]
    _save(run_dir,result)
    rematerialize_official_capture(run_dir)
    return check
