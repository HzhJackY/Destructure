"""Unified capture request and resolved-target contracts for v6.8."""
from __future__ import annotations

import datetime as dt
import re
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


class CaptureScopePolicy(str, Enum):
    PRIMARY_ONLY = "PRIMARY_ONLY"
    PRIMARY_WITH_CONTINUATIONS = "PRIMARY_WITH_CONTINUATIONS"
    ALL_NOTE_TABLES = "ALL_NOTE_TABLES"
    SELECTED_NOTE_TABLES = "SELECTED_NOTE_TABLES"


LEGACY_CAPTURE_SCOPE_CONTRACT_VERSION = 1
CAPTURE_SCOPE_CONTRACT_VERSION = 2


CAPTURE_SCOPE_BLOCK_ROLES = frozenset({
    "PRIMARY_TABLE",
    "CONTINUATION_SEGMENT",
    "SUPPLEMENTARY_TABLE",
    "PEER_TABLE",
    "UNRESOLVED",
})


_NOTE_HEADING_PREFIX_RE = re.compile(
    r"^\s*(?:附注\s*)?(?:"
    r"[（(][一二三四五六七八九十百\d]+[）)]|"
    r"[一二三四五六七八九十百\d]+[、.．]|"
    r"[一二三四五六七八九十百\d]+\s+"
    r")\s*"
)
_INTERNAL_LOGICAL_TITLE_SUFFIX_RE = re.compile(
    r"::SUPPLEMENTARY::[0-9a-f]{8,64}$",
    re.IGNORECASE,
)


def literal_capture_query_title(value: Any) -> str:
    """Strip a note ordinal without normalising PDF-native title glyphs."""
    raw = str(value or "").strip()
    literal = _INTERNAL_LOGICAL_TITLE_SUFFIX_RE.sub("", raw).strip()
    stripped = _NOTE_HEADING_PREFIX_RE.sub("", literal, count=1).strip()
    return stripped.rstrip("。；;：:").strip() or raw


def normalise_capture_scope_selection(
    capture_scope_policy: str | CaptureScopePolicy | None = None,
    selected_block_roles: Any = None,
    selected_block_ids: Any = None,
) -> tuple[str, tuple[str, ...], tuple[str, ...]]:
    raw_policy = capture_scope_policy or CaptureScopePolicy.PRIMARY_ONLY.value
    policy = (
        raw_policy.value
        if isinstance(raw_policy, CaptureScopePolicy)
        else str(raw_policy).strip().upper()
    )
    legacy_policies = {
        CaptureScopePolicy.PRIMARY_ONLY.value,
        CaptureScopePolicy.PRIMARY_WITH_CONTINUATIONS.value,
        CaptureScopePolicy.ALL_NOTE_TABLES.value,
    }
    if policy not in legacy_policies:
        raise ValueError(f"UNSUPPORTED_CAPTURE_SCOPE_POLICY:{policy}")

    raw_roles = (
        [selected_block_roles]
        if isinstance(selected_block_roles, str)
        else list(selected_block_roles or [])
    )
    roles = tuple(dict.fromkeys(
        str(value).strip().upper() for value in raw_roles if str(value).strip()
    ))
    unsupported_roles = sorted(set(roles) - CAPTURE_SCOPE_BLOCK_ROLES)
    if unsupported_roles:
        raise ValueError(
            "UNSUPPORTED_CAPTURE_BLOCK_ROLE:" + ",".join(unsupported_roles)
        )
    allowed_roles = {
        CaptureScopePolicy.PRIMARY_ONLY.value: {"PRIMARY_TABLE"},
        CaptureScopePolicy.PRIMARY_WITH_CONTINUATIONS.value: {
            "PRIMARY_TABLE", "CONTINUATION_SEGMENT",
        },
        CaptureScopePolicy.ALL_NOTE_TABLES.value: {
            "PRIMARY_TABLE", "CONTINUATION_SEGMENT",
            "SUPPLEMENTARY_TABLE",
        },
    }[policy]
    out_of_scope_roles = sorted(set(roles) - allowed_roles)
    if out_of_scope_roles:
        raise ValueError(
            "BLOCK_ROLE_OUTSIDE_CAPTURE_SCOPE:" + ",".join(out_of_scope_roles)
        )

    raw_ids = (
        [selected_block_ids]
        if isinstance(selected_block_ids, str)
        else list(selected_block_ids or [])
    )
    block_ids = tuple(dict.fromkeys(
        str(value).strip() for value in raw_ids if str(value).strip()
    ))
    return policy, roles, block_ids


def normalise_capture_scope_contract(
    capture_scope_contract_version: int | str | None = None,
    capture_scope_policy: str | CaptureScopePolicy | None = None,
    selected_logical_table_ids: Any = None,
    selected_block_roles: Any = None,
    selected_block_ids: Any = None,
) -> tuple[int, str, tuple[str, ...], tuple[str, ...], tuple[str, ...]]:
    try:
        contract_version = int(
            capture_scope_contract_version
            if capture_scope_contract_version is not None
            else CAPTURE_SCOPE_CONTRACT_VERSION
        )
    except (TypeError,ValueError) as exc:
        raise ValueError("INVALID_CAPTURE_SCOPE_CONTRACT_VERSION") from exc
    if contract_version not in {
        LEGACY_CAPTURE_SCOPE_CONTRACT_VERSION,
        CAPTURE_SCOPE_CONTRACT_VERSION,
    }:
        raise ValueError(
            f"UNSUPPORTED_CAPTURE_SCOPE_CONTRACT_VERSION:{contract_version}"
        )
    raw_logical_ids = (
        [selected_logical_table_ids]
        if isinstance(selected_logical_table_ids,str)
        else list(selected_logical_table_ids or [])
    )
    logical_table_ids = tuple(dict.fromkeys(
        str(value).strip() for value in raw_logical_ids if str(value).strip()
    ))
    if contract_version == LEGACY_CAPTURE_SCOPE_CONTRACT_VERSION:
        if logical_table_ids:
            raise ValueError("V1_CAPTURE_SCOPE_REJECTS_LOGICAL_TABLE_SELECTION")
        policy,roles,block_ids = normalise_capture_scope_selection(
            capture_scope_policy,selected_block_roles,selected_block_ids,
        )
        return contract_version,policy,(),roles,block_ids

    raw_policy = capture_scope_policy or CaptureScopePolicy.PRIMARY_ONLY.value
    policy = (
        raw_policy.value
        if isinstance(raw_policy,CaptureScopePolicy)
        else str(raw_policy).strip().upper()
    )
    if policy == CaptureScopePolicy.PRIMARY_WITH_CONTINUATIONS.value:
        policy = CaptureScopePolicy.PRIMARY_ONLY.value
    if policy not in {
        CaptureScopePolicy.PRIMARY_ONLY.value,
        CaptureScopePolicy.SELECTED_NOTE_TABLES.value,
    }:
        raise ValueError(f"UNSUPPORTED_V2_CAPTURE_SCOPE_POLICY:{policy}")
    raw_roles = (
        [selected_block_roles]
        if isinstance(selected_block_roles,str)
        else list(selected_block_roles or [])
    )
    raw_block_ids = (
        [selected_block_ids]
        if isinstance(selected_block_ids,str)
        else list(selected_block_ids or [])
    )
    if any(str(value).strip() for value in [*raw_roles,*raw_block_ids]):
        raise ValueError("V2_CAPTURE_SCOPE_REJECTS_BLOCK_SELECTION")
    if policy == CaptureScopePolicy.PRIMARY_ONLY.value and logical_table_ids:
        raise ValueError("PRIMARY_ONLY_REJECTS_SUPPLEMENTARY_SELECTION")
    if (
        policy == CaptureScopePolicy.SELECTED_NOTE_TABLES.value
        and not logical_table_ids
    ):
        raise ValueError("SELECTED_NOTE_TABLE_IDS_REQUIRED")
    return contract_version,policy,logical_table_ids,(),()


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
    classification_axis_hint: str = ""
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
    capture_scope_contract_version: int = CAPTURE_SCOPE_CONTRACT_VERSION
    capture_scope_policy: str = CaptureScopePolicy.PRIMARY_ONLY.value
    selected_logical_table_ids: tuple[str, ...] = ()
    selected_block_roles: tuple[str, ...] = ()
    selected_block_ids: tuple[str, ...] = ()
    capture_options: dict[str, Any] = field(default_factory=dict)
    request_metadata: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def new(cls, *, capture_mode: str | CaptureMode, source_pdf_path: str, **kwargs: Any) -> "CaptureRequest":
        mode = capture_mode.value if isinstance(capture_mode, CaptureMode) else str(capture_mode)
        contract_version,scope_policy,logical_table_ids,block_roles,block_ids = (
            normalise_capture_scope_contract(
                kwargs.pop(
                    "capture_scope_contract_version",
                    CAPTURE_SCOPE_CONTRACT_VERSION,
                ),
                kwargs.pop("capture_scope_policy",None),
                kwargs.pop("selected_logical_table_ids",None),
                kwargs.pop("selected_block_roles",None),
                kwargs.pop("selected_block_ids",None),
            )
        )
        return cls(
            request_id="CREQ_" + uuid.uuid4().hex,
            request_type=str(kwargs.pop("request_type", "TABLE_CAPTURE")),
            capture_mode=mode,
            source_pdf_id=str(kwargs.pop("source_pdf_id", "")),
            source_pdf_path=str(source_pdf_path),
            capture_scope_contract_version=contract_version,
            capture_scope_policy=scope_policy,
            selected_logical_table_ids=logical_table_ids,
            selected_block_roles=block_roles,
            selected_block_ids=block_ids,
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
        contract_version = values.get("capture_scope_contract_version")
        if contract_version is None:
            contract_version = LEGACY_CAPTURE_SCOPE_CONTRACT_VERSION
        (
            contract_version,scope_policy,logical_table_ids,
            block_roles,block_ids,
        ) = normalise_capture_scope_contract(
            contract_version,
            values.get("capture_scope_policy"),
            values.get("selected_logical_table_ids"),
            values.get("selected_block_roles"),
            values.get("selected_block_ids"),
        )
        values["capture_scope_contract_version"] = contract_version
        values["capture_scope_policy"] = scope_policy
        values["selected_logical_table_ids"] = logical_table_ids
        values["selected_block_roles"] = block_roles
        values["selected_block_ids"] = block_ids
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
        (
            contract_version,scope_policy,logical_table_ids,
            block_roles,block_ids,
        ) = normalise_capture_scope_contract(
            self.capture_scope_contract_version,
            self.capture_scope_policy,
            self.selected_logical_table_ids,
            self.selected_block_roles,
            self.selected_block_ids,
        )
        if (
            self.capture_scope_contract_version != contract_version
            or self.capture_scope_policy != scope_policy
            or tuple(self.selected_logical_table_ids) != logical_table_ids
            or tuple(self.selected_block_roles) != block_roles
            or tuple(self.selected_block_ids) != block_ids
        ):
            raise ValueError("CAPTURE_SCOPE_SELECTION_NOT_NORMALISED")


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
