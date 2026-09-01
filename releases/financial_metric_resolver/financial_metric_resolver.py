#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
financial_metric_resolver.py

三层财务科目解析器：
L0 人工规则标准化 + 精确匹配
L1 宽松字符串 + 表格特征评分
L2 可选 LLM 语义兜底（仅从候选中选择，不允许编造数值）

默认不配置 LLM 也能完整运行前两层。
"""

from __future__ import annotations

import argparse
import dataclasses
import datetime as dt
import difflib
import hashlib
import json
import math
import os
import re
import sys
from pathlib import Path
from typing import Any, Optional

import pandas as pd


@dataclasses.dataclass
class Candidate:
    candidate_id: str
    sheet: str
    sheet_type: str
    excel_row: int
    label_col_zero_based: int
    label: str
    normalized_label: str
    score: float
    score_detail: dict[str, float]
    values: list[dict[str, Any]]
    unit_hint: Optional[str] = None


@dataclasses.dataclass
class Resolution:
    file: str
    file_sha256: str
    metric_input: str
    standard_metric: Optional[str]
    layer: str
    confidence: float
    status: str
    reason: str
    selected: Optional[Candidate]
    top_candidates: list[Candidate]


_PUNCT_RE = re.compile(r"[\s\u3000:：,，;；。\.、_/\\\-—–·'\"“”‘’（）()【】\[\]{}<>《》]+")
_PREFIX_RE = re.compile(
    r"^(?:[一二三四五六七八九十]+[、.]|\d+[、.]|[（(][一二三四五六七八九十\d]+[）)]|其中|加|减)[:：]?"
)


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


def excel_col_name(n: int) -> str:
    s = ""
    while n:
        n, rem = divmod(n - 1, 26)
        s = chr(65 + rem) + s
    return s


def json_safe(v: Any) -> Any:
    if v is None:
        return None
    if hasattr(v, "item"):
        try:
            return v.item()
        except Exception:
            pass
    if isinstance(v, (pd.Timestamp, dt.datetime, dt.date)):
        return v.isoformat()
    if isinstance(v, float) and math.isnan(v):
        return None
    return v


class RuleBook:
    def __init__(self, path: Path):
        self.raw = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(self.raw, dict):
            raise ValueError("规则文件顶层必须是 JSON object")
        self._alias_index: dict[str, tuple[str, str]] = {}
        self._build_index()

    def _build_index(self) -> None:
        collisions: dict[str, list[tuple[str, str]]] = {}
        for standard, cfg in self.raw.items():
            names = [(standard, "standard")]
            names += [(x, "alias") for x in cfg.get("aliases", [])]
            names += [(x, "soft_alias") for x in cfg.get("soft_aliases", [])]
            for name, kind in names:
                n = normalize_text(name)
                if n:
                    collisions.setdefault(n, []).append((standard, kind))

        cross_conflicts = {
            k: v for k, v in collisions.items()
            if len({standard for standard, _ in v}) > 1
        }
        if cross_conflicts:
            raise ValueError(f"规则存在跨标准科目别名冲突: {list(cross_conflicts.items())[:10]}")

        rank = {"standard": 3, "alias": 2, "soft_alias": 1}
        for n, entries in collisions.items():
            self._alias_index[n] = sorted(entries, key=lambda x: rank[x[1]], reverse=True)[0]

    def validate(self) -> list[str]:
        errors: list[str] = []
        required_lists = ["aliases", "soft_aliases", "keywords", "exclude", "table_hint"]
        for standard, cfg in self.raw.items():
            for key in required_lists:
                if key not in cfg:
                    errors.append(f"{standard}: 缺少 {key}")
                elif not isinstance(cfg[key], list):
                    errors.append(f"{standard}.{key} 必须是 list")
            if cfg.get("position_hint") not in {"top", "middle", "bottom", "any"}:
                errors.append(f"{standard}.position_hint 非法")
        return errors

    def normalize_metric(self, user_input: str) -> tuple[Optional[str], Optional[dict], str]:
        """L0 仅做规范化后的精确相等，不做危险的 substring alias 匹配。"""
        hit = self._alias_index.get(normalize_text(user_input))
        if hit is None:
            return None, None, "no_exact_rule"
        standard, kind = hit
        return standard, self.raw[standard], kind


# ---------- Excel 扫描 ----------

def is_number_like(v: Any) -> bool:
    if v is None:
        return False
    if isinstance(v, (int, float)) and not isinstance(v, bool):
        return not (isinstance(v, float) and math.isnan(v))
    s = str(v).strip()
    if not s or s.lower() == "nan" or s in {"-", "—", "–", "－"}:
        return False
    s = s.replace(",", "").replace("，", "").replace("%", "")
    s = s.replace("(", "-").replace(")", "")
    try:
        float(s)
        return True
    except ValueError:
        return False


def likely_label_cell(v: Any) -> bool:
    if v is None or is_number_like(v):
        return False
    s = str(v).strip()
    if not s or s.lower() == "nan" or len(s) > 120:
        return False
    if re.fullmatch(r"\d{4}[-/.年]\d{1,2}([-/\.月]\d{1,2}日?)?", s):
        return False
    return True


def find_label_in_row(row: pd.Series, max_label_cols: int = 8) -> tuple[Optional[int], Optional[str]]:
    for col in range(min(max_label_cols, len(row))):
        v = row.iloc[col]
        if likely_label_cell(v):
            return col, str(v).strip()
    return None, None


def infer_sheet_type(sheet_name: str, df: pd.DataFrame) -> str:
    n = normalize_text(sheet_name)
    name_hints = {
        "资产负债表": ["资产负债表", "资产负债", "balancesheet"],
        "利润表": ["利润表", "损益表", "incomestatement"],
        "现金流量表": ["现金流量表", "现金流", "cashflow"],
        "综合收益表": ["综合收益表", "综合收益"],
    }
    for typ, words in name_hints.items():
        if any(normalize_text(w) in n for w in words):
            return typ

    sample = " ".join(
        normalize_text(x)
        for x in df.iloc[:min(len(df), 120), :min(df.shape[1], 8)].values.flatten()
        if normalize_text(x)
    )
    scores = {
        "资产负债表": sum(normalize_text(k) in sample for k in ["资产总计", "负债合计", "所有者权益"]),
        "利润表": sum(normalize_text(k) in sample for k in ["营业收入", "利润总额", "净利润"]),
        "现金流量表": sum(normalize_text(k) in sample for k in ["经营活动产生的现金流量", "投资活动产生的现金流量"]),
        "综合收益表": sum(normalize_text(k) in sample for k in ["其他综合收益", "综合收益总额"]),
    }
    best = max(scores, key=scores.get)
    return best if scores[best] else "未知表"


def detect_unit_hint(df: pd.DataFrame) -> Optional[str]:
    text = " ".join(
        str(x) for x in df.iloc[:min(len(df), 15), :min(df.shape[1], 10)].values.flatten()
        if x is not None and str(x).lower() != "nan"
    )
    m = re.search(r"单位\s*[:：]\s*(?:人民币)?\s*(元|千元|万元|百万元|亿元)", text)
    return m.group(0) if m else None


def nearest_header_context(df: pd.DataFrame, row_idx: int, col_idx: int, lookback: int = 12) -> str:
    parts: list[str] = []
    for r in range(max(0, row_idx - lookback), row_idx):
        if col_idx >= df.shape[1]:
            continue
        v = df.iat[r, col_idx]
        if v is None or str(v).lower() == "nan" or is_number_like(v):
            continue
        s = str(v).strip()
        if s and len(s) <= 40:
            parts.append(s)
    dedup: list[str] = []
    for x in parts:
        if x not in dedup:
            dedup.append(x)
    return " | ".join(dedup[-3:])


def extract_row_values(df: pd.DataFrame, row_idx: int, label_col: int) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    row = df.iloc[row_idx]
    for c in range(label_col + 1, df.shape[1]):
        v = row.iloc[c]
        if v is None or str(v).lower() == "nan" or str(v).strip() == "":
            continue
        out.append({
            "column_zero_based": c,
            "excel_col": excel_col_name(c + 1),
            "header_context": nearest_header_context(df, row_idx, c),
            "raw_value": json_safe(v),
            "number_like": is_number_like(v),
        })
    return out


def load_workbook_raw(path: Path):
    sheets = pd.read_excel(path, sheet_name=None, header=None, dtype=object, engine="openpyxl")
    result = []
    for sheet_name, df in sheets.items():
        df = df.dropna(how="all").reset_index(drop=True)
        result.append((sheet_name, df, infer_sheet_type(sheet_name, df), detect_unit_hint(df)))
    return result


# ---------- L1 评分 ----------

def position_bonus(position_hint: str, row_idx: int, nrows: int) -> float:
    if nrows <= 1 or position_hint == "any":
        return 0.0
    ratio = row_idx / max(nrows - 1, 1)
    if position_hint == "top":
        return max(0.0, 1.0 - ratio / 0.35) * 0.04
    if position_hint == "bottom":
        return max(0.0, 1.0 - (1.0 - ratio) / 0.35) * 0.04
    if position_hint == "middle":
        return max(0.0, 1.0 - abs(ratio - 0.5) / 0.5) * 0.02
    return 0.0


def score_label(label: str, standard: str, cfg: dict, sheet_type: str,
                row_idx: int, nrows: int, values: list[dict[str, Any]]) -> tuple[float, dict[str, float]]:
    nl, ns = normalize_text(label), normalize_text(standard)
    aliases = [normalize_text(x) for x in cfg.get("aliases", [])]
    soft_aliases = [normalize_text(x) for x in cfg.get("soft_aliases", [])]
    excludes = [normalize_text(x) for x in cfg.get("exclude", [])]
    keywords = [normalize_text(x) for x in cfg.get("keywords", []) if normalize_text(x)]
    detail: dict[str, float] = {}

    if any(e and e in nl for e in excludes):
        detail["exclude_penalty"] = -0.80

    if nl == ns:
        detail["exact_standard"] = 1.00
    elif nl in aliases:
        detail["exact_alias"] = 0.97
    elif nl in soft_aliases:
        detail["exact_soft_alias"] = 0.86
    else:
        contain = 0.0
        if ns and ns in nl:
            contain = max(contain, 0.80)
        for a in aliases:
            if a and a in nl:
                contain = max(contain, 0.76)
        for a in soft_aliases:
            if a and a in nl:
                contain = max(contain, 0.68)
        if contain:
            detail["contains_name"] = contain

        sim = max([string_similarity(nl, ns)] + [string_similarity(nl, a) for a in aliases + soft_aliases if a])
        detail["string_similarity"] = sim * 0.62
        if keywords:
            hit = sum(1 for k in keywords if k in nl)
            detail["keyword_overlap"] = (hit / len(keywords)) * 0.22

    table_hints = set(cfg.get("table_hint", []))
    if sheet_type in table_hints:
        detail["table_bonus"] = 0.08
    elif sheet_type != "未知表" and table_hints:
        detail["table_mismatch_penalty"] = -0.05

    detail["position_bonus"] = position_bonus(cfg.get("position_hint", "any"), row_idx, nrows)
    if values:
        numeric_ratio = sum(1 for v in values if v["number_like"]) / len(values)
        detail["numeric_bonus"] = min(0.04, numeric_ratio * 0.04)
    else:
        detail["no_values_penalty"] = -0.05

    exact_key = next((k for k in ["exact_standard", "exact_alias", "exact_soft_alias"] if k in detail), None)
    if exact_key:
        score = detail[exact_key] + detail.get("table_bonus", 0) + detail.get("position_bonus", 0) + detail.get("numeric_bonus", 0) + detail.get("exclude_penalty", 0)
    else:
        score = sum(detail.values())
    return max(0.0, min(1.0, score)), detail


def build_candidates(workbook, standard: str, cfg: dict, top_k: int = 12) -> list[Candidate]:
    candidates: list[Candidate] = []
    seq = 0
    for sheet_name, df, sheet_type, unit_hint in workbook:
        for r in range(len(df)):
            label_col, label = find_label_in_row(df.iloc[r])
            if label_col is None or label is None:
                continue
            values = extract_row_values(df, r, label_col)
            score, detail = score_label(label, standard, cfg, sheet_type, r, len(df), values)
            if score < 0.20:
                continue
            seq += 1
            candidates.append(Candidate(
                candidate_id=f"c{seq:04d}", sheet=sheet_name, sheet_type=sheet_type,
                excel_row=r + 1, label_col_zero_based=label_col, label=label,
                normalized_label=normalize_text(label), score=round(score, 6),
                score_detail={k: round(v, 6) for k, v in detail.items()},
                values=values, unit_hint=unit_hint,
            ))
    candidates.sort(key=lambda x: x.score, reverse=True)
    return candidates[:top_k]


def deterministic_decision(candidates: list[Candidate], high_threshold: float,
                           medium_threshold: float, margin_threshold: float):
    if not candidates:
        return None, 0.0, "no_candidate"
    top = candidates[0]
    second = candidates[1].score if len(candidates) > 1 else 0.0
    margin = top.score - second
    if top.score >= high_threshold:
        return top, top.score, "high_score"
    if top.score >= medium_threshold and margin >= margin_threshold:
        return top, top.score, f"medium_score_with_margin_{margin:.3f}"
    return None, top.score, f"ambiguous_top={top.score:.3f}_margin={margin:.3f}"


# ---------- L2 可选 LLM ----------

def llm_select_standard_metric(user_metric: str, standard_candidates: list[dict[str, Any]], model: str):
    """当人工规则连标准科目都无法确定时，仅允许 LLM 从有限标准科目候选中选择。"""
    if not os.getenv("OPENAI_API_KEY"):
        raise RuntimeError("未配置 OPENAI_API_KEY")
    try:
        from openai import OpenAI
    except ImportError as e:
        raise RuntimeError("未安装 openai；请 pip install openai") from e

    instructions = (
        "你是金融报表标准科目映射审计器。只能从给定 standard_candidates 中选择一个 standard_metric，或返回 null。"
        "禁止创造新的标准科目。若输入过于宽泛或存在多种合理解释，必须 abstain。"
        "只输出单个 JSON 对象，不要 markdown。"
    )
    prompt = {
        "user_metric": user_metric,
        "standard_candidates": standard_candidates,
        "output_schema": {"standard_metric": "string|null", "confidence": "0..1", "reason": "short string"},
    }
    client = OpenAI()
    response = client.responses.create(model=model, instructions=instructions, input=json.dumps(prompt, ensure_ascii=False))
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", response.output_text.strip(), flags=re.I | re.S).strip()
    obj = json.loads(text)
    standard = obj.get("standard_metric")
    conf = float(obj.get("confidence", 0.0) or 0.0)
    reason = str(obj.get("reason", ""))
    valid = {x["standard_metric"] for x in standard_candidates}
    if standard is not None and standard not in valid:
        raise RuntimeError(f"LLM 返回不存在的 standard_metric={standard}")
    return standard, max(0.0, min(1.0, conf)), reason


def llm_select_candidate(user_metric: str, standard_metric: str, cfg: dict,
                         candidates: list[Candidate], model: str):
    if not os.getenv("OPENAI_API_KEY"):
        raise RuntimeError("未配置 OPENAI_API_KEY")
    try:
        from openai import OpenAI
    except ImportError as e:
        raise RuntimeError("未安装 openai；请 pip install openai") from e

    payload = [{
        "candidate_id": c.candidate_id,
        "sheet": c.sheet,
        "sheet_type": c.sheet_type,
        "excel_row": c.excel_row,
        "label": c.label,
        "rule_score": c.score,
        "value_preview": c.values[:4],
    } for c in candidates]

    instructions = (
        "你是金融报表科目映射审计器。只能从给定 candidates 中选择一个 candidate_id，或返回 null。"
        "绝对禁止编造候选、行号、金额或财务事实。若证据不足必须 abstain。"
        "只输出单个 JSON 对象，不要 markdown。"
    )
    prompt = {
        "user_metric": user_metric,
        "standard_metric": standard_metric,
        "rule_config": {
            "aliases": cfg.get("aliases", []),
            "soft_aliases": cfg.get("soft_aliases", []),
            "exclude": cfg.get("exclude", []),
            "table_hint": cfg.get("table_hint", []),
        },
        "candidates": payload,
        "output_schema": {"candidate_id": "string|null", "confidence": "0..1", "reason": "short string"},
    }

    client = OpenAI()
    response = client.responses.create(
        model=model,
        instructions=instructions,
        input=json.dumps(prompt, ensure_ascii=False),
    )
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", response.output_text.strip(), flags=re.I | re.S).strip()
    obj = json.loads(text)
    cid = obj.get("candidate_id")
    conf = float(obj.get("confidence", 0.0) or 0.0)
    reason = str(obj.get("reason", ""))
    valid_ids = {c.candidate_id for c in candidates}
    if cid is not None and cid not in valid_ids:
        raise RuntimeError(f"LLM 返回不存在的 candidate_id={cid}")
    return cid, max(0.0, min(1.0, conf)), reason


# ---------- 主流程 ----------

def resolve_metric(path: Path, workbook, rulebook: RuleBook, metric_input: str,
                   enable_llm: bool, llm_model: str, top_k: int,
                   high_threshold: float, medium_threshold: float,
                   margin_threshold: float, sha256: str) -> Resolution:
    standard, cfg, rule_hit_kind = rulebook.normalize_metric(metric_input)
    standard_selected_by_llm = False

    if standard is None:
        n_input = normalize_text(metric_input)
        std_candidates: list[tuple[float, str]] = []
        for std, std_cfg in rulebook.raw.items():
            names = [std] + std_cfg.get("aliases", []) + std_cfg.get("soft_aliases", [])
            sim = max(string_similarity(n_input, normalize_text(x)) for x in names if normalize_text(x))
            kws = [normalize_text(k) for k in std_cfg.get("keywords", []) if normalize_text(k)]
            kw_hit = sum(k in n_input for k in kws) / len(kws) if kws else 0.0
            std_candidates.append((sim * 0.78 + kw_hit * 0.22, std))
        std_candidates.sort(reverse=True)
        if std_candidates and std_candidates[0][0] >= 0.72:
            standard = std_candidates[0][1]
            cfg = rulebook.raw[standard]
            rule_hit_kind = f"fuzzy_metric_normalization:{std_candidates[0][0]:.3f}"
        elif enable_llm and std_candidates:
            bounded = []
            for score, std in std_candidates[:8]:
                scfg = rulebook.raw[std]
                bounded.append({
                    "standard_metric": std,
                    "heuristic_score": round(score, 4),
                    "aliases": scfg.get("aliases", [])[:8],
                    "soft_aliases": scfg.get("soft_aliases", [])[:8],
                    "exclude": scfg.get("exclude", [])[:8],
                    "table_hint": scfg.get("table_hint", []),
                })
            try:
                chosen_std, std_conf, std_reason = llm_select_standard_metric(metric_input, bounded, llm_model)
            except Exception as e:
                return Resolution(str(path), sha256, metric_input, None, "L2",
                                  std_candidates[0][0], "UNRESOLVED",
                                  f"标准科目 LLM fallback failed safely: {type(e).__name__}: {e}", None, [])
            if chosen_std is None or std_conf < 0.70:
                return Resolution(str(path), sha256, metric_input, None, "L2", std_conf,
                                  "UNRESOLVED", f"标准科目映射 abstained/low confidence: {std_reason}", None, [])
            standard = chosen_std
            cfg = rulebook.raw[standard]
            rule_hit_kind = f"llm_bounded_metric_normalization:{std_reason}"
            standard_selected_by_llm = True
        else:
            return Resolution(str(path), sha256, metric_input, None, "L1",
                              std_candidates[0][0] if std_candidates else 0.0,
                              "UNRESOLVED",
                              "输入科目无法安全映射到规则库标准科目；建议新增规则、人工复核或启用 LLM bounded-choice。",
                              None, [])

    assert standard is not None and cfg is not None
    candidates = build_candidates(workbook, standard, cfg, top_k)
    selected, conf, reason = deterministic_decision(candidates, high_threshold, medium_threshold, margin_threshold)

    if selected is not None:
        exact = any(k in selected.score_detail for k in ["exact_standard", "exact_alias", "exact_soft_alias"])
        if standard_selected_by_llm:
            layer = "L2"
        else:
            layer = "L0" if exact and rule_hit_kind in {"standard", "alias", "soft_alias"} else "L1"
        return Resolution(str(path), sha256, metric_input, standard, layer, conf,
                          "RESOLVED", f"{rule_hit_kind}; {reason}", selected, candidates)

    if not enable_llm:
        return Resolution(str(path), sha256, metric_input, standard, "L1", conf,
                          "REVIEW_REQUIRED", f"{rule_hit_kind}; {reason}; LLM disabled",
                          None, candidates)

    try:
        cid, llm_conf, llm_reason = llm_select_candidate(metric_input, standard, cfg, candidates, llm_model)
    except Exception as e:
        return Resolution(str(path), sha256, metric_input, standard, "L2", conf,
                          "REVIEW_REQUIRED",
                          f"LLM fallback failed safely: {type(e).__name__}: {e}", None, candidates)

    llm_selected = next((c for c in candidates if c.candidate_id == cid), None)
    if llm_selected is None or llm_conf < 0.70:
        return Resolution(str(path), sha256, metric_input, standard, "L2", llm_conf,
                          "REVIEW_REQUIRED", f"LLM abstained/low confidence: {llm_reason}",
                          None, candidates)
    return Resolution(str(path), sha256, metric_input, standard, "L2", llm_conf,
                      "RESOLVED", f"LLM bounded-choice: {llm_reason}", llm_selected, candidates)


def append_audit(path: Path, record: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {"timestamp_utc": dt.datetime.now(dt.timezone.utc).isoformat(), **record}
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(payload, ensure_ascii=False, default=json_safe) + "\n")


def collect_xlsx(input_path: Path) -> list[Path]:
    if input_path.is_file():
        if input_path.suffix.lower() not in {".xlsx", ".xlsm"}:
            raise ValueError("当前支持 .xlsx/.xlsm；老式 .xls 建议先转换为 .xlsx")
        return [input_path]
    if input_path.is_dir():
        return sorted(p for p in input_path.rglob("*") if p.suffix.lower() in {".xlsx", ".xlsm"} and not p.name.startswith("~$"))
    raise FileNotFoundError(input_path)


def asdict_resolution(res: Resolution) -> dict[str, Any]:
    return dataclasses.asdict(res)


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="三层财务科目解析器：规则 -> 启发式 -> 可选LLM")
    p.add_argument("--input", required=True, help="单个 .xlsx/.xlsm 或目录")
    p.add_argument("--metrics", nargs="+", required=True, help="待提取科目，可传多个")
    p.add_argument("--rules", default="metric_aliases.json", help="规则 JSON")
    p.add_argument("--output", default="resolution_results.json", help="结果 JSON")
    p.add_argument("--audit", default="audit.jsonl", help="审计 JSONL")
    p.add_argument("--enable-llm", action="store_true", help="低置信度时启用 LLM 兜底")
    p.add_argument("--llm-model", default=os.getenv("OPENAI_MODEL", "gpt-5.5"))
    p.add_argument("--top-k", type=int, default=12)
    p.add_argument("--high-threshold", type=float, default=0.88)
    p.add_argument("--medium-threshold", type=float, default=0.76)
    p.add_argument("--margin-threshold", type=float, default=0.10)
    p.add_argument("--validate-rules-only", action="store_true")
    return p.parse_args()


def main() -> int:
    args = parse_args()
    rulebook = RuleBook(Path(args.rules))
    errors = rulebook.validate()
    if errors:
        print("规则校验失败：", file=sys.stderr)
        for e in errors:
            print(f" - {e}", file=sys.stderr)
        return 2
    if args.validate_rules_only:
        print(f"规则校验通过：{len(rulebook.raw)} 个标准科目")
        return 0

    files = collect_xlsx(Path(args.input))
    if not files:
        print("未找到 xlsx/xlsm 文件", file=sys.stderr)
        return 2

    all_results: list[dict[str, Any]] = []
    audit_path = Path(args.audit)
    for file in files:
        try:
            sha = file_sha256(file)
            workbook = load_workbook_raw(file)
        except Exception as e:
            rec = {"file": str(file), "status": "FILE_ERROR", "error": f"{type(e).__name__}: {e}"}
            all_results.append(rec)
            append_audit(audit_path, rec)
            continue

        for metric in args.metrics:
            res = resolve_metric(file, workbook, rulebook, metric, args.enable_llm,
                                 args.llm_model, args.top_k, args.high_threshold,
                                 args.medium_threshold, args.margin_threshold, sha)
            d = asdict_resolution(res)
            all_results.append(d)
            append_audit(audit_path, d)
            if res.selected:
                loc = f"{res.selected.sheet}!{excel_col_name(res.selected.label_col_zero_based + 1)}{res.selected.excel_row}"
                label = res.selected.label
            else:
                loc, label = "-", "-"
            print(f"[{res.status:15}] {file.name} | {metric} -> {res.standard_metric or '-'} | {res.layer} | conf={res.confidence:.3f} | {loc} | {label}")

    Path(args.output).write_text(json.dumps(all_results, ensure_ascii=False, indent=2, default=json_safe), encoding="utf-8")
    print(f"\n结果: {args.output}")
    print(f"审计: {args.audit}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
