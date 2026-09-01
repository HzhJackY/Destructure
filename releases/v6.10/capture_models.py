"""Unified capture request and resolved-target contracts for v6.8."""
from __future__ import annotations

import datetime as dt
import uuid
from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any

from version import APP_VERSION


class CaptureMode(str, Enum):
    GUIDED_RESEARCH = "GUIDED_RESEARCH"
    DIRECT_DISCLOSURE = "DIRECT_DISCLOSURE"
    MANUAL_ROI = "MANUAL_ROI"
    CERTIFIED_TARGET = "CERTIFIED_TARGET"
    HISTORICAL_TEMPLATE = "HISTORICAL_TEMPLATE"
    FAILED_JOB_RETRY = "FAILED_JOB_RETRY"


class TargetType(str, Enum):
    NOTE_TABLE = "NOTE_TABLE"
    DIRECT_DISCLOSURE = "DIRECT_DISCLOSURE"
    MANUAL_ROI = "MANUAL_ROI"
    HISTORICAL_TEMPLATE = "HISTORICAL_TEMPLATE"


def _now() -> str:
    return dt.datetime.now().astimezone().isoformat(timespec="seconds")


@dataclass(frozen=True)
class CaptureRequest:
    request_id: str
    request_type: str
    capture_mode: str
    source_pdf_id: str
    source_pdf_path: str
    source_pdf_sha256: str = ""
    research_project_id: str = ""
    research_task_id: str = ""
    research_batch_id: str = ""
    research_definition_id: str = ""
    definition_version: str = ""
    table_family_id: str = ""
    member_table_id: str = ""
    discovery_strategy_id: str = ""
    statement_anchor_id: str = ""
    certified_target_id: str = ""
    certified_note_target_id: str = ""
    manual_page_range: tuple[int, int] | None = None
    manual_bbox: tuple[float, float, float, float] | None = None
    manual_roi: dict[str, Any] = field(default_factory=dict)
    historical_template_id: str = ""
    requested_by: str = "USER"
    requested_at: str = field(default_factory=_now)
    priority: int = 100
    retry_of_request_id: str = ""
    producer_version: str = APP_VERSION
    capture_options: dict[str, Any] = field(default_factory=dict)
    request_metadata: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def new(cls, *, capture_mode: str | CaptureMode, source_pdf_path: str, **kwargs: Any) -> "CaptureRequest":
        mode = capture_mode.value if isinstance(capture_mode, CaptureMode) else str(capture_mode)
        return cls(
            request_id="CREQ_" + uuid.uuid4().hex,
            request_type=str(kwargs.pop("request_type", "TABLE_CAPTURE")),
            capture_mode=mode,
            source_pdf_id=str(kwargs.pop("source_pdf_id", "")),
            source_pdf_path=str(source_pdf_path),
            **kwargs,
        )

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "CaptureRequest":
        allowed = set(cls.__dataclass_fields__)
        values = {key: value for key, value in dict(payload).items() if key in allowed}
        if isinstance(values.get("manual_page_range"), list):
            values["manual_page_range"] = tuple(values["manual_page_range"])
        if isinstance(values.get("manual_bbox"), list):
            values["manual_bbox"] = tuple(values["manual_bbox"])
        return cls(**values)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def validate(self) -> None:
        if self.capture_mode not in {mode.value for mode in CaptureMode}:
            raise ValueError(f"UNSUPPORTED_CAPTURE_MODE:{self.capture_mode}")
        if not self.source_pdf_path:
            raise ValueError("SOURCE_PDF_PATH_REQUIRED")
        if self.capture_mode == CaptureMode.MANUAL_ROI.value and not (
            self.manual_page_range or self.manual_roi or self.certified_target_id
        ):
            raise ValueError("MANUAL_TARGET_REQUIRED")
        if not (self.member_table_id or self.request_metadata.get("table_query")):
            raise ValueError("MEMBER_TABLE_OR_QUERY_REQUIRED")


@dataclass(frozen=True)
class ResolvedCaptureTarget:
    target_id: str
    source_pdf_id: str
    strategy_id: str
    target_type: str
    start_page: int
    end_page: int
    bbox: tuple[float, float, float, float] | None = None
    title: str = ""
    note_reference: str = ""
    statement_scope: str = "UNKNOWN"
    boundary_policy: str = "AUTO"
    confidence: float = 0.0
    evidence: dict[str, Any] = field(default_factory=dict)
    certification_status: str = "REVIEW_REQUIRED"

    @classmethod
    def new(cls, **kwargs: Any) -> "ResolvedCaptureTarget":
        return cls(target_id="TARGET_" + uuid.uuid4().hex, **kwargs)

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "ResolvedCaptureTarget":
        values = dict(payload)
        if isinstance(values.get("bbox"), list):
            values["bbox"] = tuple(values["bbox"])
        return cls(**{key: value for key, value in values.items() if key in cls.__dataclass_fields__})

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def validate_for_execution(self) -> None:
        if self.start_page < 1 or self.end_page < self.start_page:
            raise ValueError("INVALID_TARGET_PAGE_RANGE")
        if self.certification_status not in {"CERTIFIED", "CERTIFIED_NOTE_TARGET", "MANUAL_CERTIFIED"}:
            raise PermissionError("TARGET_CERTIFICATION_GATE_BLOCKED")
