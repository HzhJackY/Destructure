"""Historical structure-template retrieval; predictor interface is ML-ready."""
from __future__ import annotations
from dataclasses import dataclass
from difflib import SequenceMatcher
import json
from pathlib import Path
from typing import Protocol


@dataclass(frozen=True)
class TemplateMatch:
    template_id: str
    score: float
    template: dict


class StructurePredictor(Protocol):
    def rank(self, query: dict, candidates: list[dict]) -> list[TemplateMatch]: ...


class SimilarityStructurePredictor:
    """Deterministic baseline replaceable by a LightGBM/embedding model later."""
    def rank(self, query: dict, candidates: list[dict]) -> list[TemplateMatch]:
        q_rows = "|".join(query.get("row_paths") or [])
        ranked = []
        for candidate in candidates:
            c_rows = "|".join(candidate.get("row_paths") or [])
            company_bonus = .20 if query.get("company") and query.get("company") == candidate.get("company") else 0.0
            table_bonus = .25 if query.get("table_id") and query.get("table_id") == candidate.get("table_id") else 0.0
            score = min(1.0, SequenceMatcher(None, q_rows, c_rows).ratio() * .55 + company_bonus + table_bonus)
            ranked.append(TemplateMatch(str(candidate.get("template_id")), round(score, 4), candidate))
        return sorted(ranked, key=lambda x: x.score, reverse=True)


class HistoricalTemplateStore:
    def __init__(self, path: Path, predictor: StructurePredictor | None = None):
        self.path = Path(path)
        self.predictor = predictor or SimilarityStructurePredictor()
    def _load(self) -> list[dict]:
        if not self.path.exists(): return []
        return list(json.loads(self.path.read_text(encoding="utf-8")).get("templates") or [])
    def learn(self, template: dict) -> dict:
        templates = self._load(); template = dict(template)
        template.setdefault("template_id", f"{template.get('company','UNKNOWN')}::{template.get('table_id','UNNAMED')}::{template.get('document_year','')}")
        templates = [x for x in templates if x.get("template_id") != template["template_id"]] + [template]
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps({"version": 1, "templates": templates}, ensure_ascii=False, indent=2), encoding="utf-8")
        return template
    def retrieve(self, query: dict, limit: int = 5) -> list[TemplateMatch]:
        return self.predictor.rank(query, self._load())[:max(1, int(limit))]
