"""Dependency-injected discovery strategy plugins.

No production strategy reads or mutates generic_discovery.PRESETS.
"""
from __future__ import annotations

import uuid
from pathlib import Path
from typing import Any, Protocol

from capture_models import CaptureMode, CaptureRequest, ResolvedCaptureTarget, TargetType


class DiscoveryStrategyPlugin(Protocol):
    strategy_id: str

    def supports(self, request: CaptureRequest, context: dict[str, Any]) -> bool: ...
    def discover_candidates(self, request: CaptureRequest, context: dict[str, Any]) -> list[dict[str, Any]]: ...
    def rank_candidates(self, candidates: list[dict[str, Any]], context: dict[str, Any]) -> list[dict[str, Any]]: ...
    def resolve_target(self, candidate: dict[str, Any], context: dict[str, Any]) -> ResolvedCaptureTarget: ...
    def validate_target(self, target: ResolvedCaptureTarget, context: dict[str, Any]) -> bool: ...
    def abstain_reason(self) -> str: ...


class BaseStrategy:
    strategy_id = "BASE"
    modes: set[str] = set()

    def supports(self, request: CaptureRequest, context: dict[str, Any]) -> bool:
        return request.capture_mode in self.modes

    def rank_candidates(self, candidates: list[dict[str, Any]], context: dict[str, Any]) -> list[dict[str, Any]]:
        return sorted(candidates, key=lambda row: float(row.get("confidence") or 0), reverse=True)

    def validate_target(self, target: ResolvedCaptureTarget, context: dict[str, Any]) -> bool:
        try:
            target.validate_for_execution()
            return True
        except Exception:
            return False

    def abstain_reason(self) -> str:
        return "NO_CERTIFIED_TARGET"


class CertifiedTargetStrategy(BaseStrategy):
    strategy_id = "CERTIFIED_TARGET"
    modes = {CaptureMode.CERTIFIED_TARGET.value, CaptureMode.FAILED_JOB_RETRY.value}

    def discover_candidates(self, request: CaptureRequest, context: dict[str, Any]) -> list[dict[str, Any]]:
        target = dict(request.request_metadata.get("certified_target") or {})
        if not target:
            return []
        return [target]

    def resolve_target(self, candidate: dict[str, Any], context: dict[str, Any]) -> ResolvedCaptureTarget:
        page = int(candidate.get("confirmed_note_pdf_page_index") or candidate.get("start_page") or 0)
        return ResolvedCaptureTarget.new(
            source_pdf_id=str(candidate.get("source_pdf_id") or context.get("request").source_pdf_id),
            strategy_id=self.strategy_id,
            target_type=TargetType.NOTE_TABLE.value,
            start_page=page,
            end_page=int(candidate.get("end_page") or page),
            bbox=candidate.get("bbox"),
            title=str(candidate.get("capture_query_title") or candidate.get("target_heading") or ""),
            note_reference=str(candidate.get("note_reference") or ""),
            statement_scope=str(candidate.get("statement_scope") or "UNKNOWN"),
            boundary_policy=str(candidate.get("boundary_policy") or "AUTO"),
            confidence=float(candidate.get("confidence") or 1.0),
            evidence=dict(candidate.get("evidence") or candidate),
            certification_status=str(candidate.get("status") or "CERTIFIED_NOTE_TARGET"),
        )


class ManualCertifiedRoiStrategy(BaseStrategy):
    strategy_id = "MANUAL_CERTIFIED_ROI"
    modes = {CaptureMode.MANUAL_ROI.value}

    def discover_candidates(self, request: CaptureRequest, context: dict[str, Any]) -> list[dict[str, Any]]:
        start, end = request.manual_page_range or (0, 0)
        return [{
            "start_page": start,
            "end_page": end or start,
            "bbox": request.manual_bbox,
            "title": request.member_table_id or request.request_metadata.get("table_query"),
            "status": "MANUAL_CERTIFIED",
            "confidence": 1.0,
            "evidence": {"manual_roi": request.manual_roi, "requested_by": request.requested_by},
        }]

    def resolve_target(self, candidate: dict[str, Any], context: dict[str, Any]) -> ResolvedCaptureTarget:
        return ResolvedCaptureTarget.new(
            source_pdf_id=context["request"].source_pdf_id,
            strategy_id=self.strategy_id,
            target_type=TargetType.MANUAL_ROI.value,
            start_page=int(candidate["start_page"]),
            end_page=int(candidate.get("end_page") or candidate["start_page"]),
            bbox=candidate.get("bbox"),
            title=str(candidate.get("title") or ""),
            confidence=1.0,
            evidence=dict(candidate.get("evidence") or {}),
            certification_status="MANUAL_CERTIFIED",
        )


class DirectQueryStrategy(BaseStrategy):
    """Explicit user table query; discovery happens inside the canonical executor."""
    strategy_id = "DIRECT_QUERY"
    modes = {CaptureMode.DIRECT_DISCLOSURE.value}

    def discover_candidates(self, request: CaptureRequest, context: dict[str, Any]) -> list[dict[str, Any]]:
        title = request.member_table_id or request.request_metadata.get("table_query")
        return [{"start_page": 1, "end_page": 1, "title": title,
                 "status": "MANUAL_CERTIFIED", "confidence": 1.0,
                 "evidence": {"full_book_query": True, "requested_by": request.requested_by}}]

    def resolve_target(self, candidate: dict[str, Any], context: dict[str, Any]) -> ResolvedCaptureTarget:
        return ResolvedCaptureTarget.new(
            source_pdf_id=context["request"].source_pdf_id,
            strategy_id=self.strategy_id,target_type=TargetType.DIRECT_DISCLOSURE.value,
            start_page=1,end_page=1,title=str(candidate["title"]),confidence=1.0,
            evidence=dict(candidate["evidence"]),certification_status="MANUAL_CERTIFIED",
        )


class RegistryDiscoveryStrategy(BaseStrategy):
    strategy_id = "REGISTRY_GENERIC_DISCOVERY"
    modes = {
        CaptureMode.GUIDED_RESEARCH.value,
        CaptureMode.HISTORICAL_TEMPLATE.value,
    }

    def __init__(self, generic_discovery_service):
        self.generic = generic_discovery_service

    def discover_candidates(self, request: CaptureRequest, context: dict[str, Any]) -> list[dict[str, Any]]:
        discovered = self.generic.discover(
            Path(request.source_pdf_path),
            request.research_definition_id,
            company=str(request.request_metadata.get("company") or ""),
            report_year=str(request.request_metadata.get("report_year") or ""),
            filing_type=str(request.request_metadata.get("filing_type") or "ANNUAL_REPORT"),
        )
        return list(discovered.get("candidates") or discovered.get("occurrences") or [])

    def resolve_target(self, candidate: dict[str, Any], context: dict[str, Any]) -> ResolvedCaptureTarget:
        page = int(
            candidate.get("confirmed_note_pdf_page_index")
            or candidate.get("candidate_note_pdf_page_index")
            or candidate.get("statement_pdf_page_index")
            or 0
        )
        status = str(candidate.get("certification_status") or candidate.get("status") or "REVIEW_REQUIRED")
        return ResolvedCaptureTarget.new(
            source_pdf_id=context["request"].source_pdf_id,
            strategy_id=self.strategy_id,
            target_type=(
                TargetType.DIRECT_DISCLOSURE.value
                if context["request"].capture_mode == CaptureMode.DIRECT_DISCLOSURE.value
                else TargetType.NOTE_TABLE.value
            ),
            start_page=page,
            end_page=int(candidate.get("end_page") or page),
            bbox=candidate.get("bbox"),
            title=str(candidate.get("capture_query_title") or candidate.get("target_heading") or candidate.get("statement_item") or ""),
            note_reference=str(candidate.get("note_reference") or ""),
            statement_scope=str(candidate.get("scope") or "UNKNOWN"),
            confidence=float(candidate.get("confidence") or 0),
            evidence=dict(candidate.get("evidence") or candidate),
            certification_status=status,
        )


class StrategyRegistry:
    def __init__(self, plugins: list[DiscoveryStrategyPlugin]):
        self._plugins = {plugin.strategy_id: plugin for plugin in plugins}

    def get(self, strategy_id: str) -> DiscoveryStrategyPlugin:
        try:
            return self._plugins[str(strategy_id)]
        except KeyError as exc:
            raise KeyError(f"UNKNOWN_DISCOVERY_STRATEGY:{strategy_id}") from exc

    def resolve(self, request: CaptureRequest, context: dict[str, Any]) -> DiscoveryStrategyPlugin:
        if request.discovery_strategy_id:
            plugin = self.get(request.discovery_strategy_id)
            if not plugin.supports(request, context):
                raise ValueError("DISCOVERY_STRATEGY_DOES_NOT_SUPPORT_REQUEST")
            return plugin
        supported = [plugin for plugin in self._plugins.values() if plugin.supports(request, context)]
        if len(supported) != 1:
            raise ValueError(f"DISCOVERY_STRATEGY_AMBIGUOUS:{[x.strategy_id for x in supported]}")
        return supported[0]

    def ids(self) -> list[str]:
        return sorted(self._plugins)
