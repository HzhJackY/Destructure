#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
llm_providers.py

Provider-agnostic bounded-choice LLM adapters.

The LLM is NEVER allowed to invent a financial value, page number, row, or
candidate. It may only:
1) choose one standard metric from a bounded list, or abstain;
2) choose one PDF candidate row from a bounded list, or abstain.

Supported:
- DeepSeek official OpenAI-compatible Chat Completions API
- Google Gemini via google-genai SDK
"""

from __future__ import annotations

import abc
import json
import os
import re
from dataclasses import dataclass
from typing import Any, Optional


@dataclass(frozen=True)
class LLMDecision:
    selected_id: Optional[str]
    confidence: float
    reason: str
    provider: str
    model: str


class LLMProvider(abc.ABC):
    provider_name: str

    def __init__(self, model: str, timeout_seconds: float = 45.0):
        self.model = model
        self.timeout_seconds = float(timeout_seconds)

    @abc.abstractmethod
    def select_standard_metric(
        self,
        user_metric: str,
        standard_candidates: list[dict[str, Any]],
    ) -> LLMDecision:
        raise NotImplementedError

    @abc.abstractmethod
    def select_candidate(
        self,
        user_metric: str,
        standard_metric: str,
        rule_config: dict[str, Any],
        candidates: list[dict[str, Any]],
    ) -> LLMDecision:
        raise NotImplementedError


def _clamp(v: Any) -> float:
    try:
        return max(0.0, min(1.0, float(v or 0.0)))
    except (TypeError, ValueError):
        return 0.0


def _strip_fence(text: str) -> str:
    return re.sub(r"^```(?:json)?\s*|\s*```$", "", text.strip(), flags=re.I | re.S).strip()


def _parse_json(text: str) -> dict[str, Any]:
    obj = json.loads(_strip_fence(text))
    if not isinstance(obj, dict):
        raise RuntimeError("LLM output must be a single JSON object.")
    return obj


def _decision(
    obj: dict[str, Any],
    id_field: str,
    valid_ids: set[str],
    provider: str,
    model: str,
) -> LLMDecision:
    selected = obj.get(id_field)
    if selected in ("", "null"):
        selected = None
    if selected is not None:
        selected = str(selected)
        if selected not in valid_ids:
            raise RuntimeError(f"LLM returned invalid {id_field}: {selected}")
    return LLMDecision(
        selected_id=selected,
        confidence=_clamp(obj.get("confidence")),
        reason=str(obj.get("reason", "")).strip(),
        provider=provider,
        model=model,
    )


class DeepSeekProvider(LLMProvider):
    provider_name = "deepseek"

    def __init__(
        self,
        model: str = "deepseek-v4-flash",
        api_key: Optional[str] = None,
        base_url: str = "https://api.deepseek.com",
        timeout_seconds: float = 45.0,
        max_retries: int = 2,
    ):
        super().__init__(model=model, timeout_seconds=timeout_seconds)
        self.api_key = api_key or os.getenv("DEEPSEEK_API_KEY")
        if not self.api_key:
            raise RuntimeError("DEEPSEEK_API_KEY is not configured.")
        try:
            from openai import OpenAI
        except ImportError as exc:
            raise RuntimeError("Missing dependency: pip install openai") from exc

        self.client = OpenAI(
            api_key=self.api_key,
            base_url=base_url.rstrip("/"),
            timeout=self.timeout_seconds,
            max_retries=max_retries,
        )

    def _call(self, system: str, payload: dict[str, Any]) -> dict[str, Any]:
        response = self.client.chat.completions.create(
            model=self.model,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
            ],
            response_format={"type": "json_object"},
            max_tokens=800,
            stream=False,
            extra_body={"thinking": {"type": "disabled"}},
        )
        content = response.choices[0].message.content or ""
        return _parse_json(content)

    def select_standard_metric(
        self,
        user_metric: str,
        standard_candidates: list[dict[str, Any]],
    ) -> LLMDecision:
        system = (
            "你是金融报表标准科目映射审计器。"
            "只能从 standard_candidates 选择 standard_metric，或返回 null。"
            "禁止创造新科目。输入过宽、证据不足或有多种合理解释时必须 abstain。"
            "只返回 JSON: standard_metric, confidence, reason。"
        )
        obj = self._call(system, {
            "user_metric": user_metric,
            "standard_candidates": standard_candidates,
        })
        valid = {str(x["standard_metric"]) for x in standard_candidates}
        return _decision(obj, "standard_metric", valid, self.provider_name, self.model)

    def select_candidate(
        self,
        user_metric: str,
        standard_metric: str,
        rule_config: dict[str, Any],
        candidates: list[dict[str, Any]],
    ) -> LLMDecision:
        system = (
            "你是财报PDF科目定位审计器。"
            "只能从 candidates 中选择 candidate_id，或返回 null。"
            "禁止编造页码、行、科目、金额、单位或任何候选。"
            "数值由确定性程序从选中行提取，你只负责选择最匹配的候选行。"
            "证据不足或存在重大歧义时必须 abstain。"
            "只返回 JSON: candidate_id, confidence, reason。"
        )
        obj = self._call(system, {
            "user_metric": user_metric,
            "standard_metric": standard_metric,
            "rule_config": rule_config,
            "candidates": candidates,
        })
        valid = {str(x["candidate_id"]) for x in candidates}
        return _decision(obj, "candidate_id", valid, self.provider_name, self.model)


class GeminiProvider(LLMProvider):
    provider_name = "gemini"

    def __init__(
        self,
        model: str = "gemini-3.5-flash",
        api_key: Optional[str] = None,
        timeout_seconds: float = 45.0,
    ):
        super().__init__(model=model, timeout_seconds=timeout_seconds)
        self.api_key = api_key or os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
        if not self.api_key:
            raise RuntimeError("GEMINI_API_KEY (or GOOGLE_API_KEY) is not configured.")
        try:
            from google import genai
            from google.genai import types
            from pydantic import BaseModel, Field
        except ImportError as exc:
            raise RuntimeError(
                "Missing dependencies: pip install google-genai pydantic"
            ) from exc

        self._genai = genai
        self._types = types
        self._BaseModel = BaseModel
        self._Field = Field
        self.client = genai.Client(api_key=self.api_key)

    def _call(self, prompt: str) -> dict[str, Any]:
        BaseModel = self._BaseModel
        Field = self._Field

        class ChoiceSchema(BaseModel):
            selected_id: str | None = Field(
                default=None,
                description="Must be one of the supplied IDs or null."
            )
            confidence: float = Field(ge=0, le=1)
            reason: str

        response = self.client.models.generate_content(
            model=self.model,
            contents=prompt,
            config=self._types.GenerateContentConfig(
                temperature=0,
                response_mime_type="application/json",
                response_schema=ChoiceSchema,
            ),
        )
        return _parse_json(response.text or "")

    def select_standard_metric(
        self,
        user_metric: str,
        standard_candidates: list[dict[str, Any]],
    ) -> LLMDecision:
        valid = {str(x["standard_metric"]) for x in standard_candidates}
        prompt = (
            "你是金融报表标准科目映射审计器。\n"
            "只能从候选 standard_metric 中选择一个，或 selected_id=null。\n"
            "禁止创造新科目；证据不足必须 abstain。\n"
            f"用户输入: {user_metric}\n"
            f"候选: {json.dumps(standard_candidates, ensure_ascii=False)}\n"
            "selected_id 必须严格等于某个候选 standard_metric 或 null。"
        )
        obj = self._call(prompt)
        return _decision(obj, "selected_id", valid, self.provider_name, self.model)

    def select_candidate(
        self,
        user_metric: str,
        standard_metric: str,
        rule_config: dict[str, Any],
        candidates: list[dict[str, Any]],
    ) -> LLMDecision:
        valid = {str(x["candidate_id"]) for x in candidates}
        prompt = (
            "你是财报PDF科目定位审计器。\n"
            "只能选择一个已有 candidate_id，或 selected_id=null。\n"
            "禁止编造页码、行、科目、金额、单位或候选。\n"
            "数值由确定性程序从选中行提取，你只负责选择行；证据不足必须 abstain。\n"
            f"用户输入: {user_metric}\n"
            f"标准科目: {standard_metric}\n"
            f"规则: {json.dumps(rule_config, ensure_ascii=False)}\n"
            f"候选: {json.dumps(candidates, ensure_ascii=False)}\n"
            "selected_id 必须严格等于某个候选 candidate_id 或 null。"
        )
        obj = self._call(prompt)
        return _decision(obj, "selected_id", valid, self.provider_name, self.model)


def build_llm_provider(
    provider: str,
    model: Optional[str] = None,
    timeout_seconds: float = 45.0,
) -> LLMProvider:
    name = provider.strip().lower()
    if name == "deepseek":
        return DeepSeekProvider(
            model=model or os.getenv("DEEPSEEK_MODEL", "deepseek-v4-flash"),
            timeout_seconds=timeout_seconds,
        )
    if name == "gemini":
        return GeminiProvider(
            model=model or os.getenv("GEMINI_MODEL", "gemini-3.5-flash"),
            timeout_seconds=timeout_seconds,
        )
    raise ValueError(f"Unsupported LLM provider: {provider}")
