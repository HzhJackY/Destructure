#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
financial_metric_pdf_resolver.py

PDF-first 财报任意指标提取器

Pipeline:
L0 规则知识库标准化
L1 pdfplumber 表格 + 坐标行重建 + 确定性候选评分
L2 可选 DeepSeek/Gemini bounded-choice 语义裁决
Output:
- results.json      机器读取
- audit.jsonl       完整审计
- report.html       人工阅读
- report.md         人工阅读/版本管理

Important safety design:
- LLM never invents financial values.
- LLM can only choose a pre-extracted candidate row or abstain.
- Values and unit conversion are performed deterministically by Python.
"""

from __future__ import annotations

import argparse
import dataclasses
import datetime as dt
import difflib
import hashlib
import html
import json
import math
import os
import re
import sys
from pathlib import Path
from typing import Any, Optional

import pdfplumber

from llm_providers import LLMProvider, build_llm_provider


# -------------------- data models --------------------

@dataclasses.dataclass
class PDFBlock:
    block_id: str
    page: int
    source_method: str
    table_type: str
    unit_hint: Optional[str]
    rows: list[list[str]]
    page_text_preview: str


@dataclasses.dataclass
class ExtractedValue:
    column_index: int
    raw: str
    parsed_number: Optional[float]
    header_context: str
    unit_original: Optional[str]
    unit_multiplier: Optional[float]
    value_yuan: Optional[float]
    period_score: float


@dataclasses.dataclass
class Candidate:
    candidate_id: str
    page: int
    block_id: str
    source_method: str
    table_type: str
    row_index: int
    label: str
    normalized_label: str
    score: float
    score_detail: dict[str, float]
    unit_hint: Optional[str]
    values: list[ExtractedValue]
    snippet_rows: list[list[str]]

    def to_dict(self) -> dict[str, Any]:
        return dataclasses.asdict(self)


@dataclasses.dataclass
class Resolution:
    file: str
    file_sha256: str
    metric_input: str
    aliases_input: list[str]
    standard_metric: Optional[str]
    layer: str
    confidence: float
    status: str
    reason: str
    selected: Optional[Candidate]
    primary_value: Optional[ExtractedValue]
    primary_value_confidence: str
    warnings: list[str]
    top_candidates: list[Candidate]

    def to_dict(self) -> dict[str, Any]:
        return dataclasses.asdict(self)


# -------------------- normalization --------------------

_PUNCT_RE = re.compile(r"[\s\u3000:：,，;；。\.、_/\\\-—–·'\"“”‘’（）()【】\[\]{}<>《》]+")
_PREFIX_RE = re.compile(
    r"^(?:[一二三四五六七八九十]+[、.]|\d+[、.]|"
    r"[（(][一二三四五六七八九十\d]+[）)]|其中|加|减)[:：]?"
)
_NUMBER_RE = re.compile(
    r"^\s*([+-]?)\(?\s*([0-9][0-9,，]*(?:\.[0-9]+)?)\s*\)?\s*"
    r"(元|千元|万元|百万元|亿元)?\s*(%)?\s*$"
)
_YEAR_RE = re.compile(r"(20\d{2})")
_UNIT_MULTIPLIERS = {
    "元": 1.0,
    "千元": 1_000.0,
    "万元": 10_000.0,
    "百万元": 1_000_000.0,
    "亿元": 100_000_000.0,
}


def normalize_text(value: Any) -> str:
    if value is None:
        return ""
    s = str(value).strip()
    if not s or s.lower() == "nan":
        return ""
    s = s.replace("－", "-").replace("–", "-").replace("—", "-")
    for _ in range(3):
        s2 = _PREFIX_RE.sub("", s).strip()
        if s2 == s:
            break
        s = s2
    return _PUNCT_RE.sub("", s).lower()


def clean_cell(value: Any) -> str:
    if value is None:
        return ""
    s = str(value).replace("\r", " ").replace("\n", " ")
    s = re.sub(r"\s+", " ", s).strip()
    return "" if s.lower() == "none" else s


def string_similarity(a: str, b: str) -> float:
    if not a or not b:
        return 0.0
    return difflib.SequenceMatcher(None, a, b).ratio()


def file_sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def parse_number(cell: str) -> tuple[Optional[float], Optional[str], bool]:
    s = clean_cell(cell)
    if not s or s in {"-", "—", "–", "－", "不适用", "N/A", "n/a"}:
        return None, None, False
    # Accounting negatives: (1,234.50)
    negative_by_parentheses = s.startswith("(") and ")" in s
    s2 = s.replace("（", "(").replace("）", ")")
    m = _NUMBER_RE.match(s2)
    if not m:
        return None, None, False
    sign, num, unit, pct = m.groups()
    try:
        value = float(num.replace(",", "").replace("，", ""))
    except ValueError:
        return None, unit, False
    if sign == "-" or negative_by_parentheses:
        value = -value
    if pct:
        # Keep raw percentage as numeric percent points, but do not convert to yuan.
        return value, "%", True
    return value, unit, True


def format_number(value: Optional[float]) -> str:
    if value is None:
        return "-"
    if abs(value) >= 100_000_000:
        return f"{value / 100_000_000:,.2f} 亿元"
    if abs(value) >= 10_000:
        return f"{value / 10_000:,.2f} 万元"
    return f"{value:,.2f} 元"


# -------------------- rulebook --------------------

class RuleBook:
    def __init__(self, path: Path):
        self.raw = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(self.raw, dict):
            raise ValueError("Rule file top level must be an object.")
        self.alias_index: dict[str, tuple[str, str]] = {}
        self._build()

    def _build(self) -> None:
        collisions: dict[str, list[tuple[str, str]]] = {}
        for standard, cfg in self.raw.items():
            names = [(standard, "standard")]
            names += [(x, "alias") for x in cfg.get("aliases", [])]
            names += [(x, "soft_alias") for x in cfg.get("soft_aliases", [])]
            for name, kind in names:
                n = normalize_text(name)
                if n:
                    collisions.setdefault(n, []).append((standard, kind))
        bad = {k: v for k, v in collisions.items() if len({x[0] for x in v}) > 1}
        if bad:
            raise ValueError(f"Cross-metric alias collision: {list(bad.items())[:10]}")
        rank = {"standard": 3, "alias": 2, "soft_alias": 1}
        for key, entries in collisions.items():
            self.alias_index[key] = sorted(entries, key=lambda x: rank[x[1]], reverse=True)[0]

    def normalize_metric(self, user_metric: str) -> tuple[Optional[str], Optional[dict], str]:
        hit = self.alias_index.get(normalize_text(user_metric))
        if not hit:
            return None, None, "no_exact_rule"
        standard, kind = hit
        return standard, self.raw[standard], kind

    def config(self, standard: str) -> dict[str, Any]:
        return self.raw[standard]


# -------------------- PDF extraction --------------------

def infer_table_type(text: str) -> str:
    n = normalize_text(text)
    scores = {
        "资产负债表": sum(normalize_text(k) in n for k in ["资产总计", "负债合计", "所有者权益"]),
        "利润表": sum(normalize_text(k) in n for k in ["营业收入", "利润总额", "净利润"]),
        "现金流量表": sum(normalize_text(k) in n for k in ["经营活动产生的现金流量", "投资活动产生的现金流量", "筹资活动产生的现金流量"]),
        "综合收益表": sum(normalize_text(k) in n for k in ["其他综合收益", "综合收益总额"]),
    }
    best = max(scores, key=scores.get)
    return best if scores[best] > 0 else "未知表"


def detect_unit_hint(text: str) -> Optional[str]:
    patterns = [
        r"单位\s*[:：]\s*(?:人民币)?\s*(百万元|亿元|万元|千元|元)",
        r"(?:人民币)?\s*(百万元|亿元|万元|千元|元)",
    ]
    for p in patterns:
        m = re.search(p, text)
        if m:
            return m.group(1)
    return None


def table_signature(rows: list[list[str]]) -> str:
    joined = "\n".join("|".join(normalize_text(c) for c in row) for row in rows[:20])
    return hashlib.sha1(joined.encode("utf-8")).hexdigest()


def sanitize_table(table: Any) -> list[list[str]]:
    rows: list[list[str]] = []
    if not table:
        return rows
    max_cols = max((len(r or []) for r in table), default=0)
    for raw in table:
        if raw is None:
            continue
        row = [clean_cell(x) for x in list(raw) + [""] * (max_cols - len(raw))]
        if any(row):
            rows.append(row)
    return rows


def words_to_rows(words: list[dict[str, Any]], y_tolerance: float = 3.5, gap_tolerance: float = 10.0) -> list[list[str]]:
    if not words:
        return []
    ordered = sorted(words, key=lambda w: (float(w.get("top", 0)), float(w.get("x0", 0))))
    row_groups: list[list[dict[str, Any]]] = []
    for word in ordered:
        top = float(word.get("top", 0))
        placed = False
        for group in reversed(row_groups[-4:]):
            avg_top = sum(float(x.get("top", 0)) for x in group) / len(group)
            if abs(top - avg_top) <= y_tolerance:
                group.append(word)
                placed = True
                break
        if not placed:
            row_groups.append([word])

    rows: list[list[str]] = []
    for group in row_groups:
        group = sorted(group, key=lambda w: float(w.get("x0", 0)))
        cells: list[str] = []
        current = ""
        last_x1: Optional[float] = None
        for w in group:
            txt = clean_cell(w.get("text", ""))
            if not txt:
                continue
            x0 = float(w.get("x0", 0))
            x1 = float(w.get("x1", x0))
            if last_x1 is None or x0 - last_x1 <= gap_tolerance:
                current += txt
            else:
                if current:
                    cells.append(current)
                current = txt
            last_x1 = x1
        if current:
            cells.append(current)
        if cells:
            rows.append(cells)
    return rows


def extract_pdf_blocks(pdf_path: Path) -> tuple[list[PDFBlock], dict[str, Any]]:
    blocks: list[PDFBlock] = []
    stats = {
        "pages": 0,
        "pages_with_text": 0,
        "pages_with_tables": 0,
        "table_blocks": 0,
        "fallback_row_blocks": 0,
        "likely_scanned_pages": [],
    }
    seen_signatures: set[tuple[int, str]] = set()
    block_seq = 0

    table_settings_variants = [
        None,
        {
            "vertical_strategy": "text",
            "horizontal_strategy": "text",
            "snap_tolerance": 3,
            "join_tolerance": 3,
            "intersection_tolerance": 5,
            "min_words_vertical": 2,
            "min_words_horizontal": 1,
        },
    ]

    with pdfplumber.open(str(pdf_path)) as pdf:
        stats["pages"] = len(pdf.pages)
        for page_no, page in enumerate(pdf.pages, start=1):
            page_text = page.extract_text(x_tolerance=2, y_tolerance=3) or ""
            if len(page_text.strip()) >= 30:
                stats["pages_with_text"] += 1
            else:
                stats["likely_scanned_pages"].append(page_no)

            page_table_count = 0
            for settings in table_settings_variants:
                try:
                    tables = page.extract_tables(table_settings=settings) if settings else page.extract_tables()
                except Exception:
                    tables = []
                for table in tables or []:
                    rows = sanitize_table(table)
                    if len(rows) < 2:
                        continue
                    sig = table_signature(rows)
                    key = (page_no, sig)
                    if key in seen_signatures:
                        continue
                    seen_signatures.add(key)
                    block_seq += 1
                    combined = page_text[:2500] + "\n" + "\n".join(" | ".join(r) for r in rows[:30])
                    blocks.append(PDFBlock(
                        block_id=f"p{page_no}_t{block_seq}",
                        page=page_no,
                        source_method="pdfplumber_table",
                        table_type=infer_table_type(combined),
                        unit_hint=detect_unit_hint(combined),
                        rows=rows,
                        page_text_preview=page_text[:500],
                    ))
                    page_table_count += 1
                    stats["table_blocks"] += 1

            if page_table_count:
                stats["pages_with_tables"] += 1

            # Coordinate-row fallback: useful when table extraction fails or merged cells break structure.
            try:
                words = page.extract_words(
                    use_text_flow=True,
                    keep_blank_chars=False,
                    x_tolerance=2,
                    y_tolerance=3,
                )
            except Exception:
                words = []
            fallback_rows = words_to_rows(words)
            if len(fallback_rows) >= 2:
                sig = table_signature(fallback_rows)
                key = (page_no, sig)
                if key not in seen_signatures:
                    seen_signatures.add(key)
                    block_seq += 1
                    combined = page_text[:3000] + "\n" + "\n".join(" | ".join(r) for r in fallback_rows[:80])
                    blocks.append(PDFBlock(
                        block_id=f"p{page_no}_r{block_seq}",
                        page=page_no,
                        source_method="coordinate_rows",
                        table_type=infer_table_type(combined),
                        unit_hint=detect_unit_hint(combined),
                        rows=fallback_rows,
                        page_text_preview=page_text[:500],
                    ))
                    stats["fallback_row_blocks"] += 1

    return blocks, stats


# -------------------- candidate construction --------------------

def is_number_like(text: str) -> bool:
    _, _, ok = parse_number(text)
    return ok


def find_label(row: list[str]) -> tuple[Optional[int], Optional[str]]:
    for i, cell in enumerate(row[:8]):
        s = clean_cell(cell)
        if not s or is_number_like(s):
            continue
        if len(s) <= 150:
            return i, s
    return None, None


def period_score(header: str) -> float:
    n = normalize_text(header)
    score = 0.0
    years = [int(y) for y in _YEAR_RE.findall(header)]
    if years:
        # Make adjacent years meaningfully separable (2025 > 2024 by 1 point).
        score += max(years) - 2000
    if any(k in n for k in map(normalize_text, ["本期", "本年", "期末", "年末", "本报告期"])):
        score += 0.35
    if any(k in n for k in map(normalize_text, ["上期", "上年", "期初", "年初", "上年同期"])):
        score -= 0.15
    return score


def header_context(rows: list[list[str]], row_idx: int, col_idx: int, lookback: int = 50) -> str:
    parts: list[str] = []
    for r in range(max(0, row_idx - lookback), row_idx):
        if col_idx < len(rows[r]):
            s = clean_cell(rows[r][col_idx])
            if s and len(s) <= 80 and not is_number_like(s):
                parts.append(s)
    dedup: list[str] = []
    for x in parts:
        if x not in dedup:
            dedup.append(x)
    return " | ".join(dedup[-3:])


def make_values(block: PDFBlock, row_idx: int, label_col: int) -> list[ExtractedValue]:
    row = block.rows[row_idx]
    values: list[ExtractedValue] = []
    for c in range(label_col + 1, len(row)):
        raw = clean_cell(row[c])
        if not raw:
            continue
        number, cell_unit, ok = parse_number(raw)
        if not ok:
            continue
        unit = cell_unit if cell_unit not in (None, "%") else block.unit_hint
        multiplier = _UNIT_MULTIPLIERS.get(unit) if unit and unit != "%" else None
        value_yuan = None
        if number is not None and multiplier is not None:
            value_yuan = number * multiplier
        ctx = header_context(block.rows, row_idx, c)
        values.append(ExtractedValue(
            column_index=c,
            raw=raw,
            parsed_number=number,
            header_context=ctx,
            unit_original=cell_unit or block.unit_hint,
            unit_multiplier=multiplier,
            value_yuan=value_yuan,
            period_score=period_score(ctx),
        ))
    return values


def position_bonus(position_hint: str, row_idx: int, nrows: int) -> float:
    if nrows <= 1 or position_hint == "any":
        return 0.0
    ratio = row_idx / max(1, nrows - 1)
    if position_hint == "top":
        return max(0.0, 1 - ratio / 0.4) * 0.04
    if position_hint == "bottom":
        return max(0.0, 1 - (1 - ratio) / 0.4) * 0.04
    if position_hint == "middle":
        return max(0.0, 1 - abs(ratio - 0.5) / 0.5) * 0.02
    return 0.0


def score_label(
    label: str,
    standard: str,
    cfg: dict[str, Any],
    user_aliases: list[str],
    table_type: str,
    row_idx: int,
    nrows: int,
    values: list[ExtractedValue],
) -> tuple[float, dict[str, float]]:
    nl = normalize_text(label)
    ns = normalize_text(standard)
    aliases = [normalize_text(x) for x in cfg.get("aliases", [])]
    soft = [normalize_text(x) for x in cfg.get("soft_aliases", [])]
    query_aliases = [normalize_text(x) for x in user_aliases if normalize_text(x)]
    excludes = [normalize_text(x) for x in cfg.get("exclude", []) if normalize_text(x)]
    keywords = [normalize_text(x) for x in cfg.get("keywords", []) if normalize_text(x)]
    d: dict[str, float] = {}

    if any(e in nl for e in excludes):
        d["exclude_penalty"] = -0.85

    if nl == ns:
        d["exact_standard"] = 1.0
    elif nl in aliases:
        d["exact_alias"] = 0.97
    elif nl in query_aliases:
        d["exact_user_alias"] = 0.93
    elif nl in soft:
        d["exact_soft_alias"] = 0.86
    else:
        names = [ns] + aliases + query_aliases + soft
        sim = max((string_similarity(nl, x) for x in names if x), default=0.0)
        d["string_similarity"] = sim * 0.63
        contains = 0.0
        if ns and ns in nl:
            contains = 0.80
        for x in aliases:
            if x and x in nl:
                contains = max(contains, 0.76)
        for x in query_aliases:
            if x and x in nl:
                contains = max(contains, 0.72)
        if contains:
            d["contains_name"] = contains
        if keywords:
            hit = sum(k in nl for k in keywords)
            d["keyword_overlap"] = (hit / len(keywords)) * 0.22

    hints = set(cfg.get("table_hint", []))
    if table_type in hints:
        d["table_bonus"] = 0.08
    elif table_type != "未知表" and hints:
        d["table_mismatch_penalty"] = -0.05

    d["position_bonus"] = position_bonus(cfg.get("position_hint", "any"), row_idx, nrows)
    if values:
        d["numeric_bonus"] = min(0.04, 0.015 + len(values) * 0.01)
    else:
        d["no_numeric_penalty"] = -0.08

    exact_keys = {"exact_standard", "exact_alias", "exact_user_alias", "exact_soft_alias"}
    exact = next((d[k] for k in exact_keys if k in d), None)
    if exact is not None:
        score = exact + sum(v for k, v in d.items() if k not in exact_keys)
    else:
        score = sum(d.values())
    return max(0.0, min(1.0, score)), {k: round(v, 6) for k, v in d.items()}


def build_candidates(
    blocks: list[PDFBlock],
    standard: str,
    cfg: dict[str, Any],
    user_aliases: list[str],
    top_k: int,
) -> list[Candidate]:
    out: list[Candidate] = []
    seen: set[tuple[int, str, tuple[str, ...]]] = set()
    seq = 0
    for block in blocks:
        for r, row in enumerate(block.rows):
            label_col, label = find_label(row)
            if label_col is None or not label:
                continue
            values = make_values(block, r, label_col)
            score, detail = score_label(
                label, standard, cfg, user_aliases,
                block.table_type, r, len(block.rows), values,
            )
            if score < 0.20:
                continue
            signature = (
                block.page,
                normalize_text(label),
                tuple(v.raw for v in values),
            )
            if signature in seen:
                continue
            seen.add(signature)
            seq += 1
            lo = max(0, r - 1)
            hi = min(len(block.rows), r + 2)
            out.append(Candidate(
                candidate_id=f"c{seq:04d}",
                page=block.page,
                block_id=block.block_id,
                source_method=block.source_method,
                table_type=block.table_type,
                row_index=r,
                label=label,
                normalized_label=normalize_text(label),
                score=round(score, 6),
                score_detail=detail,
                unit_hint=block.unit_hint,
                values=values,
                snippet_rows=block.rows[lo:hi],
            ))
    out.sort(key=lambda c: c.score, reverse=True)
    return out[:top_k]


def deterministic_pick(
    candidates: list[Candidate],
    high_threshold: float,
    medium_threshold: float,
    margin_threshold: float,
) -> tuple[Optional[Candidate], float, str]:
    if not candidates:
        return None, 0.0, "no_candidate"
    top = candidates[0]
    second = candidates[1].score if len(candidates) > 1 else 0.0
    margin = top.score - second
    if top.score >= high_threshold:
        return top, top.score, "high_score"
    if top.score >= medium_threshold and margin >= margin_threshold:
        return top, top.score, f"medium_score_margin={margin:.3f}"
    return None, top.score, f"ambiguous_top={top.score:.3f}_margin={margin:.3f}"


def choose_primary_value(values: list[ExtractedValue]) -> tuple[Optional[ExtractedValue], str, list[str]]:
    warnings: list[str] = []
    if not values:
        return None, "NONE", ["匹配到科目行，但未从该行确定性解析出数值。"]
    if len(values) == 1:
        return values[0], "HIGH", warnings

    ranked = sorted(values, key=lambda v: (v.period_score, -v.column_index), reverse=True)
    top = ranked[0]
    second = ranked[1]
    if top.period_score > second.period_score + 0.10:
        return top, "MEDIUM", warnings

    # Chinese financial statements usually put current period before comparative period,
    # but this is only a fallback and must be disclosed.
    leftmost = sorted(values, key=lambda v: v.column_index)[0]
    warnings.append(
        "存在多个数值列且期间标题不足以唯一判断最新一期；primary_value 暂取最左侧数值，人工报告会同时展示全部数值列。"
    )
    return leftmost, "LOW", warnings


# -------------------- metric normalization / LLM --------------------

def standard_metric_candidates(rulebook: RuleBook, user_metric: str, top_k: int = 8) -> list[dict[str, Any]]:
    n = normalize_text(user_metric)
    scored: list[tuple[float, str]] = []
    for standard, cfg in rulebook.raw.items():
        names = [standard] + cfg.get("aliases", []) + cfg.get("soft_aliases", [])
        sim = max((string_similarity(n, normalize_text(x)) for x in names if normalize_text(x)), default=0.0)
        kws = [normalize_text(x) for x in cfg.get("keywords", []) if normalize_text(x)]
        kw = sum(k in n for k in kws) / len(kws) if kws else 0.0
        scored.append((sim * 0.80 + kw * 0.20, standard))
    scored.sort(reverse=True)
    return [
        {
            "standard_metric": std,
            "score": round(score, 4),
            "aliases": rulebook.raw[std].get("aliases", [])[:6],
            "table_hint": rulebook.raw[std].get("table_hint", []),
        }
        for score, std in scored[:top_k]
    ]


def bounded_candidate_payload(candidates: list[Candidate]) -> list[dict[str, Any]]:
    payload = []
    for c in candidates:
        payload.append({
            "candidate_id": c.candidate_id,
            "page": c.page,
            "source_method": c.source_method,
            "table_type": c.table_type,
            "label": c.label,
            "rule_score": c.score,
            "unit_hint": c.unit_hint,
            "values": [
                {
                    "raw": v.raw,
                    "header_context": v.header_context,
                }
                for v in c.values[:6]
            ],
            "snippet_rows": c.snippet_rows,
        })
    return payload


def resolve_metric(
    pdf_path: Path,
    sha: str,
    blocks: list[PDFBlock],
    rulebook: RuleBook,
    metric_input: str,
    user_aliases: list[str],
    llm: Optional[LLMProvider],
    top_k: int,
    high_threshold: float,
    medium_threshold: float,
    margin_threshold: float,
) -> Resolution:
    standard, cfg, hit_kind = rulebook.normalize_metric(metric_input)
    layer = "L0"

    if standard is None:
        std_cands = standard_metric_candidates(rulebook, metric_input)
        if std_cands and std_cands[0]["score"] >= 0.78:
            standard = std_cands[0]["standard_metric"]
            cfg = rulebook.config(standard)
            hit_kind = f"fuzzy_metric_normalization:{std_cands[0]['score']:.3f}"
            layer = "L1"
        elif llm is not None and std_cands:
            decision = llm.select_standard_metric(metric_input, std_cands)
            if decision.selected_id and decision.confidence >= 0.70:
                standard = decision.selected_id
                cfg = rulebook.config(standard)
                hit_kind = f"{decision.provider}:{decision.model}:{decision.reason}"
                layer = "L2"
            else:
                return Resolution(
                    file=str(pdf_path), file_sha256=sha,
                    metric_input=metric_input, aliases_input=user_aliases,
                    standard_metric=None, layer="L2",
                    confidence=decision.confidence,
                    status="UNRESOLVED",
                    reason=f"无法安全映射标准科目: {decision.reason}",
                    selected=None, primary_value=None,
                    primary_value_confidence="NONE",
                    warnings=["建议人工确认标准科目后，将别名加入规则库。"],
                    top_candidates=[],
                )
        else:
            return Resolution(
                file=str(pdf_path), file_sha256=sha,
                metric_input=metric_input, aliases_input=user_aliases,
                standard_metric=None, layer="L1",
                confidence=std_cands[0]["score"] if std_cands else 0.0,
                status="UNRESOLVED",
                reason="输入无法安全映射到规则库标准科目；未启用LLM或候选不足。",
                selected=None, primary_value=None,
                primary_value_confidence="NONE",
                warnings=["建议提供更明确科目名/别名，或扩充 metric_aliases.json。"],
                top_candidates=[],
            )

    assert cfg is not None
    candidates = build_candidates(blocks, standard, cfg, user_aliases, top_k=top_k)
    selected, conf, reason = deterministic_pick(
        candidates, high_threshold, medium_threshold, margin_threshold
    )

    if selected is None and llm is not None and candidates:
        decision = llm.select_candidate(
            user_metric=metric_input,
            standard_metric=standard,
            rule_config={
                "aliases": cfg.get("aliases", []),
                "soft_aliases": cfg.get("soft_aliases", []),
                "exclude": cfg.get("exclude", []),
                "table_hint": cfg.get("table_hint", []),
                "user_aliases": user_aliases,
            },
            candidates=bounded_candidate_payload(candidates),
        )
        if decision.selected_id and decision.confidence >= 0.70:
            selected = next(c for c in candidates if c.candidate_id == decision.selected_id)
            conf = decision.confidence
            reason = f"{decision.provider}:{decision.model}: {decision.reason}"
            layer = "L2"
        else:
            return Resolution(
                file=str(pdf_path), file_sha256=sha,
                metric_input=metric_input, aliases_input=user_aliases,
                standard_metric=standard, layer="L2",
                confidence=decision.confidence,
                status="REVIEW_REQUIRED",
                reason=f"LLM abstained/low confidence: {decision.reason}",
                selected=None, primary_value=None,
                primary_value_confidence="NONE",
                warnings=["存在多个合理候选或证据不足，系统拒绝自动落库。"],
                top_candidates=candidates,
            )

    if selected is None:
        status = "REVIEW_REQUIRED" if candidates else "UNRESOLVED"
        return Resolution(
            file=str(pdf_path), file_sha256=sha,
            metric_input=metric_input, aliases_input=user_aliases,
            standard_metric=standard, layer=layer if layer != "L0" else "L1",
            confidence=conf, status=status,
            reason=f"{hit_kind}; {reason}",
            selected=None, primary_value=None,
            primary_value_confidence="NONE",
            warnings=["请查看人工报告中的候选表格片段进行复核。"],
            top_candidates=candidates,
        )

    if layer == "L0":
        exact = any(k in selected.score_detail for k in (
            "exact_standard", "exact_alias", "exact_user_alias", "exact_soft_alias"
        ))
        if not exact:
            layer = "L1"

    primary, pconf, warnings = choose_primary_value(selected.values)
    if primary and primary.unit_original is None:
        warnings.append("未可靠识别原始单位；value_yuan 未自动生成或需人工确认。")
    if selected.source_method == "coordinate_rows":
        warnings.append("该候选来自坐标行重建而非结构化表格识别，建议人工核对PDF原页。")

    return Resolution(
        file=str(pdf_path), file_sha256=sha,
        metric_input=metric_input, aliases_input=user_aliases,
        standard_metric=standard, layer=layer,
        confidence=conf, status="RESOLVED",
        reason=f"{hit_kind}; {reason}",
        selected=selected, primary_value=primary,
        primary_value_confidence=pconf,
        warnings=warnings, top_candidates=candidates,
    )


# -------------------- human reports --------------------

def safe_json(obj: Any) -> Any:
    if dataclasses.is_dataclass(obj):
        return dataclasses.asdict(obj)
    return obj


def snippet_markdown(rows: list[list[str]]) -> str:
    if not rows:
        return "_无可用表格片段_"
    width = max(len(r) for r in rows)
    norm = [r + [""] * (width - len(r)) for r in rows]
    header = [f"列{i+1}" for i in range(width)]
    lines = [
        "| " + " | ".join(header) + " |",
        "| " + " | ".join(["---"] * width) + " |",
    ]
    for row in norm:
        lines.append("| " + " | ".join(clean_cell(x).replace("|", "\\|") for x in row) + " |")
    return "\n".join(lines)


def value_table_md(values: list[ExtractedValue]) -> str:
    if not values:
        return "_未解析出数值列_"
    lines = [
        "| 列 | 原始值 | 列标题/期间上下文 | 原始单位 | 换算为元 |",
        "|---:|---:|---|---|---:|",
    ]
    for v in values:
        lines.append(
            f"| {v.column_index+1} | {v.raw} | {v.header_context or '-'} | "
            f"{v.unit_original or '-'} | {format_number(v.value_yuan) if v.value_yuan is not None else '-'} |"
        )
    return "\n".join(lines)


def generate_markdown(
    pdf_path: Path,
    stats: dict[str, Any],
    results: list[Resolution],
) -> str:
    resolved = sum(r.status == "RESOLVED" for r in results)
    review = sum(r.status == "REVIEW_REQUIRED" for r in results)
    unresolved = sum(r.status == "UNRESOLVED" for r in results)
    out = [
        "# 财报 PDF 指标提取人工复核报告",
        "",
        f"- 源文件：`{pdf_path.name}`",
        f"- 生成时间：{dt.datetime.now().astimezone().isoformat(timespec='seconds')}",
        f"- PDF页数：{stats['pages']}",
        f"- 结构化表格块：{stats['table_blocks']}",
        f"- 坐标行重建块：{stats['fallback_row_blocks']}",
        f"- 结果：RESOLVED {resolved} / REVIEW_REQUIRED {review} / UNRESOLVED {unresolved}",
        "",
    ]
    if stats.get("likely_scanned_pages"):
        out += [
            "> [!WARNING]",
            f"> 可能为扫描/低文本页：{stats['likely_scanned_pages']}。本版本默认不做OCR，这些页可能漏检。",
            "",
        ]

    out += ["## 汇总", "", "| 查询指标 | 标准科目 | 状态 | 层级 | 页码 | 匹配原文 | 主值 | 置信度 |",
            "|---|---|---|---|---:|---|---:|---:|"]
    for r in results:
        s = r.selected
        page = str(s.page) if s else "-"
        label = s.label if s else "-"
        primary = "-"
        if r.primary_value:
            primary = (
                format_number(r.primary_value.value_yuan)
                if r.primary_value.value_yuan is not None
                else r.primary_value.raw
            )
        out.append(
            f"| {r.metric_input} | {r.standard_metric or '-'} | {r.status} | {r.layer} | "
            f"{page} | {label.replace('|','\\|')} | {primary} | {r.confidence:.3f} |"
        )

    for r in results:
        out += ["", "---", "", f"## {r.metric_input}", ""]
        out += [
            f"- 标准科目：**{r.standard_metric or '-'}**",
            f"- 状态：**{r.status}**",
            f"- 决策层：**{r.layer}**",
            f"- 置信度：**{r.confidence:.3f}**",
            f"- 判断理由：{r.reason}",
        ]
        if r.aliases_input:
            out.append(f"- 本次用户别名：{', '.join(r.aliases_input)}")
        if r.selected:
            out += [
                f"- PDF页码：**{r.selected.page}**",
                f"- 匹配原始科目：**{r.selected.label}**",
                f"- 解析方式：`{r.selected.source_method}`",
                f"- 推断表类型：{r.selected.table_type}",
                f"- 单位提示：{r.selected.unit_hint or '未识别'}",
            ]
            if r.primary_value:
                pv = r.primary_value
                out += [
                    f"- 主值选择置信度：**{r.primary_value_confidence}**",
                    f"- 主值原文：**{pv.raw}**",
                    f"- 主值期间上下文：{pv.header_context or '未识别'}",
                    f"- 换算为元：**{format_number(pv.value_yuan) if pv.value_yuan is not None else '未自动换算'}**",
                ]
            if r.warnings:
                out += ["", "### 人工复核提示", ""]
                out += [f"- {w}" for w in r.warnings]

            out += ["", "### 数值列", "", value_table_md(r.selected.values)]
            out += ["", "### PDF 表格上下文", "", snippet_markdown(r.selected.snippet_rows)]
        else:
            if r.warnings:
                out += ["", "### 人工复核提示", ""]
                out += [f"- {w}" for w in r.warnings]

        if r.top_candidates:
            out += ["", "### Top 候选", "", "| 排名 | 页码 | 原始科目 | 表类型 | 来源 | 分数 |",
                    "|---:|---:|---|---|---|---:|"]
            for i, c in enumerate(r.top_candidates[:5], 1):
                out.append(
                    f"| {i} | {c.page} | {c.label.replace('|','\\|')} | "
                    f"{c.table_type} | {c.source_method} | {c.score:.3f} |"
                )
    return "\n".join(out) + "\n"


def html_table(rows: list[list[str]], highlight_label: Optional[str] = None) -> str:
    if not rows:
        return "<p class='muted'>无可用表格片段</p>"
    width = max(len(r) for r in rows)
    norm = [r + [""] * (width - len(r)) for r in rows]
    parts = ["<div class='table-wrap'><table><tbody>"]
    target = normalize_text(highlight_label or "")
    for row in norm:
        row_text = normalize_text(" ".join(row))
        cls = " class='hit-row'" if target and target in row_text else ""
        parts.append(f"<tr{cls}>")
        for cell in row:
            parts.append(f"<td>{html.escape(clean_cell(cell))}</td>")
        parts.append("</tr>")
    parts.append("</tbody></table></div>")
    return "".join(parts)


def generate_html(
    pdf_path: Path,
    stats: dict[str, Any],
    results: list[Resolution],
) -> str:
    resolved = sum(r.status == "RESOLVED" for r in results)
    review = sum(r.status == "REVIEW_REQUIRED" for r in results)
    unresolved = sum(r.status == "UNRESOLVED" for r in results)

    rows = []
    for r in results:
        s = r.selected
        pv = r.primary_value
        primary = "-"
        if pv:
            primary = format_number(pv.value_yuan) if pv.value_yuan is not None else pv.raw
        rows.append(
            "<tr>"
            f"<td>{html.escape(r.metric_input)}</td>"
            f"<td>{html.escape(r.standard_metric or '-')}</td>"
            f"<td><span class='badge {r.status.lower()}'>{r.status}</span></td>"
            f"<td>{html.escape(r.layer)}</td>"
            f"<td>{s.page if s else '-'}</td>"
            f"<td>{html.escape(s.label if s else '-')}</td>"
            f"<td>{html.escape(primary)}</td>"
            f"<td>{r.confidence:.3f}</td>"
            "</tr>"
        )

    detail_parts = []
    for r in results:
        s = r.selected
        pv = r.primary_value
        warnings = "".join(f"<li>{html.escape(w)}</li>" for w in r.warnings)
        candidate_rows = ""
        for i, c in enumerate(r.top_candidates[:5], 1):
            candidate_rows += (
                f"<tr><td>{i}</td><td>{c.page}</td><td>{html.escape(c.label)}</td>"
                f"<td>{html.escape(c.table_type)}</td><td>{html.escape(c.source_method)}</td>"
                f"<td>{c.score:.3f}</td></tr>"
            )

        if s:
            value_rows = ""
            for v in s.values:
                yuan = format_number(v.value_yuan) if v.value_yuan is not None else "-"
                value_rows += (
                    f"<tr><td>{v.column_index+1}</td><td>{html.escape(v.raw)}</td>"
                    f"<td>{html.escape(v.header_context or '-')}</td>"
                    f"<td>{html.escape(v.unit_original or '-')}</td><td>{html.escape(yuan)}</td></tr>"
                )
            primary_html = ""
            if pv:
                primary_display = format_number(pv.value_yuan) if pv.value_yuan is not None else pv.raw
                primary_html = (
                    "<div class='primary-value'>"
                    f"<div><span>主值</span><strong>{html.escape(primary_display)}</strong></div>"
                    f"<small>原文 {html.escape(pv.raw)} · 期间 {html.escape(pv.header_context or '未识别')} · "
                    f"选择置信度 {html.escape(r.primary_value_confidence)}</small>"
                    "</div>"
                )
            selected_html = f"""
                <div class="meta-grid">
                  <div><span>PDF页码</span><strong>{s.page}</strong></div>
                  <div><span>匹配原文</span><strong>{html.escape(s.label)}</strong></div>
                  <div><span>解析方式</span><strong>{html.escape(s.source_method)}</strong></div>
                  <div><span>表类型</span><strong>{html.escape(s.table_type)}</strong></div>
                  <div><span>单位提示</span><strong>{html.escape(s.unit_hint or '未识别')}</strong></div>
                  <div><span>规则分数</span><strong>{s.score:.3f}</strong></div>
                </div>
                {primary_html}
                <h4>全部数值列</h4>
                <div class="table-wrap"><table><thead><tr><th>列</th><th>原始值</th><th>期间/标题上下文</th><th>原始单位</th><th>换算为元</th></tr></thead>
                <tbody>{value_rows or "<tr><td colspan='5'>未解析出数值</td></tr>"}</tbody></table></div>
                <h4>PDF表格上下文</h4>
                {html_table(s.snippet_rows, s.label)}
            """
        else:
            selected_html = "<p class='muted'>系统没有安全确定唯一候选，请查看下方 Top 候选并人工复核。</p>"

        detail_parts.append(f"""
        <section class="metric-card">
          <div class="metric-head">
            <div>
              <h2>{html.escape(r.metric_input)}</h2>
              <p>{html.escape(r.standard_metric or '未映射标准科目')}</p>
            </div>
            <span class="badge {r.status.lower()}">{r.status}</span>
          </div>
          <div class="decision">
            <strong>{html.escape(r.layer)} · confidence {r.confidence:.3f}</strong>
            <span>{html.escape(r.reason)}</span>
          </div>
          {selected_html}
          {"<div class='warning'><strong>人工复核提示</strong><ul>"+warnings+"</ul></div>" if warnings else ""}
          {"<h4>Top 候选</h4><div class='table-wrap'><table><thead><tr><th>#</th><th>页码</th><th>原始科目</th><th>表类型</th><th>来源</th><th>分数</th></tr></thead><tbody>"+candidate_rows+"</tbody></table></div>" if candidate_rows else ""}
        </section>
        """)

    scanned = ""
    if stats.get("likely_scanned_pages"):
        scanned = (
            "<div class='warning'><strong>扫描页风险</strong>"
            f"<p>可能为扫描或低文本页面：{html.escape(str(stats['likely_scanned_pages']))}。"
            "本版本默认不做OCR，这些页面可能漏检。</p></div>"
        )

    return f"""<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>财报PDF指标提取人工复核报告</title>
<style>
:root{{--bg:#f5f7fb;--card:#fff;--text:#172033;--muted:#687386;--line:#dfe4ec;--blue:#275efe;--green:#0b7a53;--amber:#9a6700;--red:#b42318}}
*{{box-sizing:border-box}} body{{margin:0;background:var(--bg);font-family:-apple-system,BlinkMacSystemFont,"Segoe UI","Microsoft YaHei",sans-serif;color:var(--text);line-height:1.55}}
main{{max-width:1180px;margin:auto;padding:28px 20px 60px}} h1{{margin:0 0 6px;font-size:28px}} h2{{margin:0;font-size:21px}} h4{{margin:24px 0 10px}} .sub{{color:var(--muted);margin:0 0 22px}}
.summary{{display:grid;grid-template-columns:repeat(4,1fr);gap:12px;margin:18px 0}} .stat{{background:var(--card);border:1px solid var(--line);border-radius:14px;padding:16px}} .stat span{{display:block;color:var(--muted);font-size:13px}} .stat strong{{font-size:24px}}
.panel,.metric-card{{background:var(--card);border:1px solid var(--line);border-radius:16px;padding:20px;margin:16px 0}} .metric-head{{display:flex;justify-content:space-between;gap:14px;align-items:flex-start}} .metric-head p{{color:var(--muted);margin:3px 0}}
.badge{{display:inline-block;padding:4px 9px;border-radius:999px;font-size:12px;font-weight:700}} .resolved{{background:#e8f7f0;color:var(--green)}} .review_required{{background:#fff4d6;color:var(--amber)}} .unresolved{{background:#feeceb;color:var(--red)}}
.decision{{display:flex;flex-direction:column;background:#f8faff;border-left:4px solid var(--blue);padding:10px 12px;margin:14px 0;border-radius:8px}} .decision span{{color:var(--muted);font-size:13px}}
.meta-grid{{display:grid;grid-template-columns:repeat(3,1fr);gap:10px;margin:14px 0}} .meta-grid div{{border:1px solid var(--line);border-radius:10px;padding:10px}} .meta-grid span{{display:block;color:var(--muted);font-size:12px}} .meta-grid strong{{display:block;margin-top:3px}}
.primary-value{{background:#eef3ff;border-radius:12px;padding:14px;margin:14px 0}} .primary-value div{{display:flex;gap:14px;align-items:baseline}} .primary-value span{{color:var(--muted)}} .primary-value strong{{font-size:24px}} .primary-value small{{color:var(--muted)}}
.table-wrap{{overflow:auto;border:1px solid var(--line);border-radius:10px}} table{{border-collapse:collapse;width:100%;font-size:13px}} th,td{{border-bottom:1px solid var(--line);padding:8px 10px;text-align:left;vertical-align:top;white-space:nowrap}} th{{background:#f7f9fc}} tr:last-child td{{border-bottom:0}} .hit-row td{{background:#fff6d8;font-weight:600}} .warning{{background:#fff8e6;border:1px solid #f0d48b;border-radius:10px;padding:12px 14px;margin:14px 0}} .warning ul{{margin:8px 0 0 20px}} .muted{{color:var(--muted)}}
@media(max-width:800px){{.summary,.meta-grid{{grid-template-columns:1fr 1fr}}}} @media(max-width:520px){{.summary,.meta-grid{{grid-template-columns:1fr}} main{{padding:18px 12px}}}}
</style>
</head>
<body><main>
<h1>财报 PDF 指标提取人工复核报告</h1>
<p class="sub">源文件：{html.escape(pdf_path.name)} · 生成时间：{dt.datetime.now().astimezone().isoformat(timespec="seconds")}</p>
<div class="summary">
  <div class="stat"><span>PDF页数</span><strong>{stats["pages"]}</strong></div>
  <div class="stat"><span>自动解析成功</span><strong>{resolved}</strong></div>
  <div class="stat"><span>需人工复核</span><strong>{review}</strong></div>
  <div class="stat"><span>未解析</span><strong>{unresolved}</strong></div>
</div>
{scanned}
<section class="panel"><h2>结果汇总</h2><div class="table-wrap"><table><thead><tr><th>查询指标</th><th>标准科目</th><th>状态</th><th>层级</th><th>页码</th><th>匹配原文</th><th>主值</th><th>置信度</th></tr></thead><tbody>
{''.join(rows)}
</tbody></table></div></section>
{''.join(detail_parts)}
</main></body></html>"""


# -------------------- CLI / audit --------------------

def parse_alias_args(items: list[str]) -> dict[str, list[str]]:
    mapping: dict[str, list[str]] = {}
    for item in items:
        if "=" not in item:
            raise ValueError(f"--alias format must be 标准查询名=别名1|别名2, got: {item}")
        key, value = item.split("=", 1)
        aliases = [x.strip() for x in value.split("|") if x.strip()]
        mapping.setdefault(key.strip(), []).extend(aliases)
    return mapping


def append_audit(path: Path, record: dict[str, Any]) -> None:
    payload = {
        "timestamp_utc": dt.datetime.now(dt.timezone.utc).isoformat(),
        **record,
    }
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(payload, ensure_ascii=False, default=safe_json) + "\n")


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="PDF-first 财报指标提取：规则 -> pdfplumber候选 -> 可选DeepSeek/Gemini -> 人工HTML报告"
    )
    p.add_argument("pdf", help="财报 PDF 路径")
    p.add_argument("--metrics", nargs="+", required=True, help="需要提取的指标，可传多个")
    p.add_argument(
        "--alias", action="append", default=[],
        help='本次查询别名，格式: "营业收入=营业总收入|收入"，可重复传入'
    )
    p.add_argument("--rules", default="metric_aliases.json")
    p.add_argument("--output-dir", default="output_pdf_extract")
    p.add_argument("--enable-llm", action="store_true")
    p.add_argument("--llm-provider", choices=["deepseek", "gemini"], default=os.getenv("LLM_PROVIDER", "deepseek"))
    p.add_argument("--llm-model", default=None)
    p.add_argument("--llm-timeout", type=float, default=45.0)
    p.add_argument("--top-k", type=int, default=12)
    p.add_argument("--high-threshold", type=float, default=0.88)
    p.add_argument("--medium-threshold", type=float, default=0.76)
    p.add_argument("--margin-threshold", type=float, default=0.10)
    return p.parse_args()


def main() -> int:
    args = parse_args()
    pdf_path = Path(args.pdf)
    if not pdf_path.exists() or pdf_path.suffix.lower() != ".pdf":
        print(f"ERROR: PDF not found: {pdf_path}", file=sys.stderr)
        return 2

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    rules_path = Path(args.rules)
    if not rules_path.exists():
        # Also allow rules next to this script.
        candidate = Path(__file__).resolve().parent / args.rules
        if candidate.exists():
            rules_path = candidate
    rulebook = RuleBook(rules_path)
    alias_map = parse_alias_args(args.alias)

    llm: Optional[LLMProvider] = None
    if args.enable_llm:
        try:
            llm = build_llm_provider(
                args.llm_provider,
                model=args.llm_model,
                timeout_seconds=args.llm_timeout,
            )
        except Exception as exc:
            print(f"WARNING: LLM initialization failed safely: {exc}", file=sys.stderr)
            llm = None

    print("1/4 正在解析 PDF 文本、表格和坐标行...")
    blocks, stats = extract_pdf_blocks(pdf_path)
    print(
        f"   pages={stats['pages']} table_blocks={stats['table_blocks']} "
        f"fallback_blocks={stats['fallback_row_blocks']}"
    )
    sha = file_sha256(pdf_path)

    results: list[Resolution] = []
    audit_path = output_dir / "audit.jsonl"
    if audit_path.exists():
        audit_path.unlink()

    print("2/4 正在解析指标...")
    for metric in args.metrics:
        res = resolve_metric(
            pdf_path=pdf_path,
            sha=sha,
            blocks=blocks,
            rulebook=rulebook,
            metric_input=metric,
            user_aliases=alias_map.get(metric, []),
            llm=llm,
            top_k=args.top_k,
            high_threshold=args.high_threshold,
            medium_threshold=args.medium_threshold,
            margin_threshold=args.margin_threshold,
        )
        results.append(res)
        append_audit(audit_path, res.to_dict())
        page = res.selected.page if res.selected else "-"
        label = res.selected.label if res.selected else "-"
        pv = res.primary_value.raw if res.primary_value else "-"
        print(
            f"   [{res.status:15}] {metric} -> {res.standard_metric or '-'} | "
            f"{res.layer} | conf={res.confidence:.3f} | p.{page} | {label} | {pv}"
        )

    print("3/4 正在生成机器结果和人工报告...")
    results_path = output_dir / "results.json"
    results_path.write_text(
        json.dumps(
            {
                "source_file": str(pdf_path),
                "file_sha256": sha,
                "extraction_stats": stats,
                "results": [r.to_dict() for r in results],
            },
            ensure_ascii=False,
            indent=2,
            default=safe_json,
        ),
        encoding="utf-8",
    )

    md = generate_markdown(pdf_path, stats, results)
    html_report = generate_html(pdf_path, stats, results)
    (output_dir / "report.md").write_text(md, encoding="utf-8")
    (output_dir / "report.html").write_text(html_report, encoding="utf-8")

    print("4/4 完成")
    print(f"   人工HTML报告: {output_dir / 'report.html'}")
    print(f"   人工Markdown报告: {output_dir / 'report.md'}")
    print(f"   机器JSON: {results_path}")
    print(f"   审计JSONL: {audit_path}")

    if stats.get("likely_scanned_pages"):
        print(
            "   WARNING: 检测到可能的扫描/低文本页。若目标数据只存在于这些页，需要增加OCR层。",
            file=sys.stderr,
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
