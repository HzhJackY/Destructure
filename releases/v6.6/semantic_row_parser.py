"""Conservative semantic row classification for financial-note extraction."""
from __future__ import annotations

import re
from typing import Any


NOTE_PREFIXES = ("注：", "注:", "说明：", "说明:")
MEMO_TOKENS = ("以下名称", "以下简称", "截至", "包括", "上述", "不构成")


def classify_non_data_text(
    text: Any,
    *,
    numeric_cell_count: int = 0,
    expected_numeric_columns: int = 0,
) -> str | None:
    raw = re.sub(r"\s+", "", str(text or "")).strip()
    if not raw:
        return None
    insufficient = numeric_cell_count < max(1, expected_numeric_columns)
    if raw.startswith(NOTE_PREFIXES) and insufficient:
        return "NOTE_TEXT"
    memo_hit = any(token in raw for token in MEMO_TOKENS)
    long_prose = len(raw) >= 12 or any(mark in raw for mark in ("，", "。", "；", "："))
    if memo_hit and long_prose and insufficient:
        return "MEMO_TEXT"
    if raw.startswith("其中") and len(raw) >= 12 and insufficient:
        return "MEMO_TEXT"
    return None


def classify_cell_role(raw: Any, parsed_number: Any) -> str:
    text = str(raw or "").strip()
    has_text = bool(re.search(r"[A-Za-z\u4e00-\u9fff]", text))
    has_number = bool(re.search(r"\d", text))
    if has_text and has_number:
        return "MIXED"
    if parsed_number is not None or has_number:
        return "NUMERIC"
    return "TEXT"
