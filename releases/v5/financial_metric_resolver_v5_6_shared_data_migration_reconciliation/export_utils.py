#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations

import shutil
from pathlib import Path


def save_csv_as(
    source_path: Path,
    directory: str | Path,
    filename: str,
    overwrite: bool = False,
) -> Path:
    source = Path(source_path)
    if not source.exists():
        raise FileNotFoundError(f"源CSV不存在：{source}")

    name = str(filename or "").strip()
    if not name:
        raise ValueError("文件名不能为空。")
    if any(sep in name for sep in ["/", "\\"]):
        raise ValueError("文件名中不能包含路径分隔符；路径请放在 directory。")
    if not name.lower().endswith(".csv"):
        name += ".csv"

    target_dir = Path(str(directory).strip()).expanduser()
    if not str(target_dir).strip():
        raise ValueError("保存目录不能为空。")
    target_dir.mkdir(parents=True, exist_ok=True)
    target = target_dir / name

    if target.exists() and not overwrite:
        raise FileExistsError(f"目标文件已存在：{target}")

    shutil.copy2(source, target)
    return target
