#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations

import json
import os
import shutil
import tempfile
import datetime as dt
from pathlib import Path
from typing import Any

from financial_metric_pdf_resolver import RuleBook, normalize_text


def _atomic_write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(
        prefix=path.name + ".",
        suffix=".tmp",
        dir=str(path.parent),
    )
    os.close(fd)
    tmp = Path(tmp_name)
    try:
        tmp.write_text(
            json.dumps(data, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        os.replace(tmp, path)
    finally:
        if tmp.exists():
            tmp.unlink(missing_ok=True)


def persist_verified_alias(
    rules_path: Path,
    standard_metric: str,
    alias: str,
) -> dict[str, Any]:
    """
    Persist a strong L0 alias and prove that the production RuleBook can resolve it.

    Success contract:
      write -> reload -> normalize_metric(alias) == standard_metric

    No UI/session cache is trusted as proof.
    """
    rules_path = Path(rules_path).resolve()
    alias = str(alias or "").strip()
    standard_metric = str(standard_metric or "").strip()

    if not alias:
        return {"ok": False, "error": "别名为空。"}
    if not rules_path.exists():
        return {"ok": False, "error": f"规则文件不存在：{rules_path}"}

    raw = json.loads(rules_path.read_text(encoding="utf-8"))
    if standard_metric not in raw:
        return {
            "ok": False,
            "error": f"标准科目不存在于规则库：{standard_metric}",
        }

    # Detect cross-metric collision using the current production RuleBook.
    before = RuleBook(rules_path)
    existing_standard, _, existing_kind = before.normalize_metric(alias)
    if existing_standard and existing_standard != standard_metric:
        return {
            "ok": False,
            "error": (
                f"别名冲突：{alias!r} 当前已映射到 "
                f"{existing_standard!r} ({existing_kind})"
            ),
        }

    # If it already resolves correctly, still return verified success.
    if existing_standard == standard_metric:
        return {
            "ok": True,
            "changed": False,
            "verified_standard": existing_standard,
            "verified_kind": existing_kind,
            "rules_path": str(rules_path),
            "message": "该查询名已能通过 L0 解析到目标标准科目，无需重复写入。",
        }

    aliases = raw[standard_metric].setdefault("aliases", [])
    if alias not in aliases:
        aliases.append(alias)

    # Backup exact pre-write file.
    stamp = dt.datetime.now().strftime("%Y%m%d_%H%M%S")
    backup = rules_path.with_name(
        f"{rules_path.stem}.backup_{stamp}{rules_path.suffix}"
    )
    shutil.copy2(rules_path, backup)

    try:
        _atomic_write_json(rules_path, raw)

        # Production reload verification.
        after = RuleBook(rules_path)
        verified_standard, _, verified_kind = after.normalize_metric(alias)
        ok = (
            verified_standard == standard_metric
            and verified_kind in {"alias", "standard"}
        )
        if not ok:
            # Roll back on failed verification.
            shutil.copy2(backup, rules_path)
            return {
                "ok": False,
                "error": (
                    "L0_ALIAS_WRITEBACK_FAILED：写入后 RuleBook 即时验证失败；"
                    f"得到 standard={verified_standard!r}, kind={verified_kind!r}。"
                    "已回滚规则文件。"
                ),
                "backup": str(backup),
            }

        return {
            "ok": True,
            "changed": True,
            "verified_standard": verified_standard,
            "verified_kind": verified_kind,
            "rules_path": str(rules_path),
            "backup": str(backup),
            "message": (
                f"L0_ALIAS_WRITEBACK_VERIFIED：{alias!r} -> "
                f"{verified_standard!r} ({verified_kind})"
            ),
        }
    except Exception as exc:
        # Best-effort rollback.
        try:
            shutil.copy2(backup, rules_path)
        except Exception:
            pass
        return {
            "ok": False,
            "error": f"{type(exc).__name__}: {exc}",
            "backup": str(backup),
        }
