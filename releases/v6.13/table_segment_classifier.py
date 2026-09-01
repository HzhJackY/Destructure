from __future__ import annotations

import copy
import hashlib
import json
import re
from collections.abc import Mapping
from dataclasses import dataclass
from enum import Enum
from typing import Any, Iterable, Optional, Sequence


class SegmentClassification(str, Enum):
    PRIMARY_TABLE = "PRIMARY_TABLE"
    CONTINUATION_SEGMENT = "CONTINUATION_SEGMENT"
    SUPPLEMENTARY_TABLE = "SUPPLEMENTARY_TABLE"
    PEER_TABLE = "PEER_TABLE"
    UNRESOLVED = "UNRESOLVED"


_CONTINUATION_RE = re.compile(r"(?:[（(]续(?:表)?[）)]|续表)")
_PEER_NOTE_RE = re.compile(
    r"^(?:附注\s*)?(?:[一二三四五六七八九十]+\s*[、.]|\d+\s*[.、])"
)


def _normalise(value: object) -> str:
    return re.sub(r"\s+", "", str(value or "")).strip("：:")


def _enum_text(value: object) -> str:
    return str(getattr(value, "value", value) or "").upper()


def _normalise_sequence(values: Iterable[object] | None) -> tuple[str, ...]:
    return tuple(_normalise(value) for value in (values or []) if _normalise(value))


def _optional_match(
    current: Iterable[object] | None,
    parent: Iterable[object] | None,
) -> Optional[bool]:
    current_values = _normalise_sequence(current)
    parent_values = _normalise_sequence(parent)
    if not current_values or not parent_values:
        return None
    return current_values == parent_values


def _optional_scalar_match(current: object, parent: object) -> Optional[bool]:
    current_value = _normalise(current)
    parent_value = _normalise(parent)
    if not current_value or not parent_value:
        return None
    return current_value == parent_value


def _anchor_match(
    current: Sequence[float] | None,
    parent: Sequence[float] | None,
    *,
    tolerance: float = 0.04,
) -> Optional[bool]:
    current_values = tuple(float(value) for value in (current or []))
    parent_values = tuple(float(value) for value in (parent or []))
    if not current_values or not parent_values:
        return None
    if len(current_values) != len(parent_values):
        return False
    return all(
        abs(value - parent_values[index]) <= tolerance
        for index, value in enumerate(current_values)
    )


@dataclass(frozen=True)
class ConsistencyAudit:
    topology_match: Optional[bool] = None
    amount_lane_match: Optional[bool] = None
    period_match: Optional[bool] = None
    measure_match: Optional[bool] = None
    unit_match: Optional[bool] = None
    note_identity_match: Optional[bool] = None
    table_identity_match: Optional[bool] = None

    def to_dict(self) -> dict[str, Optional[bool]]:
        return {
            "topology_match": self.topology_match,
            "amount_lane_match": self.amount_lane_match,
            "period_match": self.period_match,
            "measure_match": self.measure_match,
            "unit_match": self.unit_match,
            "note_identity_match": self.note_identity_match,
            "table_identity_match": self.table_identity_match,
        }


@dataclass(frozen=True)
class TableSegment:
    segment_id: str
    classification: SegmentClassification
    pdf_page_number: int
    bbox: tuple[float, float, float, float]
    note_identity: str
    table_identity: str
    header_topology_fingerprint: str
    consistency_audit: ConsistencyAudit
    text_evidence: str
    confidence: str
    reason_codes: tuple[str, ...]
    continuation_of_segment_id: Optional[str] = None
    candidate_relation: Optional[str] = None
    source_column_ordinals: tuple[int, ...] = ()
    anchor_ratios: tuple[float, ...] = ()
    period_labels: tuple[str, ...] = ()
    measure_labels: tuple[str, ...] = ()
    unit: Optional[str] = None
    header_y0: Optional[float] = None
    header_y1: Optional[float] = None
    data_y_min: Optional[float] = None
    data_y_max: Optional[float] = None
    row_order_start: Optional[int] = None
    row_order_end: Optional[int] = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "segment_id": self.segment_id,
            "classification": self.classification.value,
            "continuation_of_segment_id": self.continuation_of_segment_id,
            "candidate_relation": self.candidate_relation,
            "pdf_page_number": self.pdf_page_number,
            "bbox": [round(value, 3) for value in self.bbox],
            "note_identity": self.note_identity,
            "table_identity": self.table_identity,
            "header_topology_fingerprint": self.header_topology_fingerprint,
            "source_column_ordinals": list(self.source_column_ordinals),
            "anchor_ratios": [round(value, 6) for value in self.anchor_ratios],
            "period_labels": list(self.period_labels),
            "measure_labels": list(self.measure_labels),
            "unit": self.unit,
            "consistency_audit": self.consistency_audit.to_dict(),
            "text_evidence": self.text_evidence,
            "confidence": self.confidence,
            "reason_codes": list(self.reason_codes),
            "header_y0": self.header_y0,
            "header_y1": self.header_y1,
            "data_y_min": self.data_y_min,
            "data_y_max": self.data_y_max,
            "row_order_start": self.row_order_start,
            "row_order_end": self.row_order_end,
        }


def compute_header_fingerprint(
    headers: Sequence[str],
    anchor_ratios: Sequence[float] | None = None,
) -> str:
    payload = {
        "leaf_count": max(len(headers), len(anchor_ratios or [])),
        "anchor_ratios": [round(float(value), 4) for value in (anchor_ratios or [])],
        "labels": [_normalise(value) for value in headers],
    }
    material = json.dumps(payload, ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(material.encode("utf-8")).hexdigest()[:16]


def classify_table_segment(
    segment_id: str,
    pdf_page_number: int,
    bbox: Sequence[float],
    note_identity: str,
    table_identity: str,
    text_lines: Sequence[str],
    headers: Sequence[str],
    parent_segment: Optional[TableSegment] = None,
    *,
    anchor_ratios: Sequence[float] | None = None,
    source_column_ordinals: Sequence[int] | None = None,
    period_labels: Sequence[str] | None = None,
    measure_labels: Sequence[str] | None = None,
    unit: Optional[str] = None,
    independent_header: bool = False,
    narrative_separator: bool = False,
    local_total_before: bool = False,
    peer_note_detected: bool = False,
    page_adjacent: Optional[bool] = None,
    candidate_relation: Optional[str] = None,
    header_y0: Optional[float] = None,
    header_y1: Optional[float] = None,
    data_y_min: Optional[float] = None,
    data_y_max: Optional[float] = None,
) -> TableSegment:
    ratios = tuple(float(value) for value in (anchor_ratios or []))
    periods = tuple(str(value or "") for value in (period_labels or []))
    measures = tuple(str(value or "") for value in (measure_labels or []))
    ordinals = tuple(int(value) for value in (source_column_ordinals or []))
    full_text = " ".join(str(line or "") for line in text_lines).strip()
    explicit_continuation = bool(_CONTINUATION_RE.search(full_text))
    peer_heading = peer_note_detected or bool(_PEER_NOTE_RE.search(full_text))
    fingerprint = compute_header_fingerprint(headers, ratios)
    box = tuple(float(value) for value in bbox)
    if len(box) != 4:
        raise ValueError("TABLE_SEGMENT_BBOX_REQUIRES_FOUR_COORDINATES")

    def build(
        classification: SegmentClassification,
        *,
        audit: ConsistencyAudit,
        confidence: str,
        reason_codes: Sequence[str],
        continuation_of: Optional[str] = None,
        candidate: Optional[str] = None,
    ) -> TableSegment:
        return TableSegment(
            segment_id=segment_id,
            classification=classification,
            continuation_of_segment_id=continuation_of,
            candidate_relation=candidate,
            pdf_page_number=int(pdf_page_number),
            bbox=(box[0], box[1], box[2], box[3]),
            note_identity=str(note_identity or ""),
            table_identity=str(table_identity or ""),
            header_topology_fingerprint=fingerprint,
            source_column_ordinals=ordinals,
            anchor_ratios=ratios,
            period_labels=periods,
            measure_labels=measures,
            unit=unit,
            consistency_audit=audit,
            text_evidence=full_text,
            confidence=confidence,
            reason_codes=tuple(dict.fromkeys(str(code) for code in reason_codes)),
            header_y0=header_y0,
            header_y1=header_y1,
            data_y_min=data_y_min,
            data_y_max=data_y_max,
        )

    if parent_segment is None:
        empty_audit = ConsistencyAudit()
        if explicit_continuation:
            return build(
                SegmentClassification.UNRESOLVED,
                audit=empty_audit,
                confidence="LOW",
                reason_codes=(
                    "ORPHAN_CONTINUATION_MARKER",
                    "CONTINUATION_RELATION_UNRESOLVED",
                ),
                candidate=SegmentClassification.CONTINUATION_SEGMENT.value,
            )
        if peer_note_detected:
            return build(
                SegmentClassification.PEER_TABLE,
                audit=empty_audit,
                confidence="HIGH",
                reason_codes=("PEER_NOTE_HEADING_DETECTED",),
            )
        return build(
            SegmentClassification.PRIMARY_TABLE,
            audit=empty_audit,
            confidence="HIGH",
            reason_codes=("FIRST_CERTIFIED_NOTE_SEGMENT",),
        )

    note_match = _optional_scalar_match(note_identity, parent_segment.note_identity)
    table_match = _optional_scalar_match(table_identity, parent_segment.table_identity)
    lane_match = _anchor_match(ratios, parent_segment.anchor_ratios)
    period_match = _optional_match(periods, parent_segment.period_labels)
    measure_match = _optional_match(measures, parent_segment.measure_labels)
    unit_match = _optional_scalar_match(unit, parent_segment.unit)
    topology_match = lane_match
    audit = ConsistencyAudit(
        topology_match=topology_match,
        amount_lane_match=lane_match,
        period_match=period_match,
        measure_match=measure_match,
        unit_match=unit_match,
        note_identity_match=note_match,
        table_identity_match=table_match,
    )

    if peer_heading or note_match is False:
        return build(
            SegmentClassification.PEER_TABLE,
            audit=audit,
            confidence="HIGH",
            reason_codes=(
                "PEER_NOTE_HEADING_DETECTED"
                if peer_heading
                else "NOTE_IDENTITY_CHANGED",
            ),
        )

    topology_reset = independent_header and (
        lane_match is False
        or measure_match is False
        or period_match is False
        or table_match is False
    )
    independent_table_evidence = (
        independent_header
        and local_total_before
        and narrative_separator
    )
    period_axis_reset = (
        page_adjacent is True
        and period_match is False
        and note_match is not False
    )
    if note_match is not False and (
        topology_reset
        or independent_table_evidence
        or period_axis_reset
    ):
        reasons = ["INDEPENDENT_LOCAL_HEADER"]
        if lane_match is False:
            reasons.append("AMOUNT_LANE_TOPOLOGY_RESET")
        if measure_match is False:
            reasons.append("MEASURE_AXIS_RESET")
        if period_match is False:
            reasons.append("PERIOD_AXIS_RESET")
        if local_total_before:
            reasons.append("PRECEDING_LOCAL_TOTAL")
        if narrative_separator:
            reasons.append("NARRATIVE_SEPARATOR")
        return build(
            SegmentClassification.SUPPLEMENTARY_TABLE,
            audit=audit,
            confidence="HIGH" if topology_reset else "MEDIUM",
            reason_codes=reasons,
        )

    conflicting_audits = any(
        value is False
        for value in (lane_match, period_match, measure_match, unit_match)
    )
    period_confirmed = (
        period_match is True
        or (not parent_segment.period_labels and not periods)
    )
    measure_confirmed = (
        measure_match is True
        or (not parent_segment.measure_labels and not measures)
    )
    continuation_evidence = (
        page_adjacent is True
        and table_match is not False
        and lane_match is True
        and period_confirmed
        and measure_confirmed
        and not conflicting_audits
        and not independent_header
    )
    if continuation_evidence:
        continuation_root = (
            parent_segment.continuation_of_segment_id
            or parent_segment.segment_id
        )
        reasons = ["ADJACENT_PAGE", "AMOUNT_LANE_TOPOLOGY_MATCH"]
        if explicit_continuation:
            reasons.append("EXPLICIT_CONTINUATION_MARKER")
        else:
            reasons.append("STRUCTURAL_CONTINUATION")
        return build(
            SegmentClassification.CONTINUATION_SEGMENT,
            audit=audit,
            confidence="HIGH",
            reason_codes=reasons,
            continuation_of=continuation_root,
        )

    suspected_continuation = (
        explicit_continuation
        or candidate_relation == SegmentClassification.CONTINUATION_SEGMENT.value
        or (
            page_adjacent is True
            and note_match is not False
            and table_match is not False
            and not independent_header
        )
    )
    reasons = ["SEGMENT_RELATION_EVIDENCE_INSUFFICIENT"]
    resolved_candidate = candidate_relation
    if suspected_continuation:
        reasons.append("CONTINUATION_RELATION_UNRESOLVED")
        resolved_candidate = SegmentClassification.CONTINUATION_SEGMENT.value
    if conflicting_audits:
        reasons.append("SEGMENT_CONSISTENCY_CONFLICT")
    return build(
        SegmentClassification.UNRESOLVED,
        audit=audit,
        confidence="LOW" if conflicting_audits else "MEDIUM",
        reason_codes=reasons,
        continuation_of=(
            parent_segment.continuation_of_segment_id
            or parent_segment.segment_id
            if suspected_continuation
            else None
        ),
        candidate=resolved_candidate,
    )


def _segment_payload(segment: TableSegment | Mapping[str, Any]) -> dict[str, Any]:
    if isinstance(segment, TableSegment):
        return segment.to_dict()
    if isinstance(segment, Mapping):
        return copy.deepcopy(dict(segment))
    raise TypeError(f"UNSUPPORTED_SEGMENT_MANIFEST_ENTRY:{type(segment).__name__}")


def _manifest_page(segment: Mapping[str, Any]) -> Optional[int]:
    value = (
        segment.get("pdf_page_number")
        if segment.get("pdf_page_number") is not None
        else segment.get("page_number")
        if segment.get("page_number") is not None
        else segment.get("page")
    )
    return int(value) if value is not None else None


def _manifest_segment_id(segment: Mapping[str, Any]) -> str:
    return str(
        segment.get("certified_segment_id")
        or segment.get("segment_id")
        or ""
    )


def _manifest_runtime_segment_id(segment: Mapping[str, Any]) -> str:
    return str(
        segment.get("runtime_segment_id")
        or segment.get("discovered_segment_id")
        or segment.get("segment_id")
        or segment.get("certified_segment_id")
        or ""
    )


def _manifest_lane_count(segment: Mapping[str, Any]) -> Optional[int]:
    for key in ("amount_lane_count", "lane_count"):
        if segment.get(key) is not None:
            return int(segment[key])
    ratios = segment.get("anchor_ratios") or []
    if ratios:
        return len(ratios)
    ordinals = segment.get("source_column_ordinals") or []
    if ordinals:
        return len(ordinals)
    return None


def _bbox_match(
    discovered: Sequence[float] | None,
    certified: Sequence[float] | None,
    *,
    tolerance: float = 12.0,
) -> Optional[bool]:
    if not discovered or not certified:
        return None
    if len(discovered) != 4 or len(certified) != 4:
        return False
    return all(
        abs(float(value) - float(certified[index])) <= tolerance
        for index, value in enumerate(discovered)
    )


def validate_certified_segment_manifest(
    discovered_segments: Sequence[TableSegment | Mapping[str, Any]],
    certified_segments: Sequence[TableSegment | Mapping[str, Any]],
    manifest_status: str,
    capture_scope_policy: str,
    certified_table_classification: str,
) -> dict[str, Any]:
    """Validate runtime segment evidence against an external certification.

    The function is deliberately read-only.  It returns every discovered
    segment for audit, but never promotes discovery into certification and
    never rewrites a machine classification to match the manifest.
    """
    discovered = [_segment_payload(segment) for segment in discovered_segments]
    certified = [_segment_payload(segment) for segment in certified_segments]
    status = _enum_text(manifest_status)
    policy = _enum_text(capture_scope_policy or "PRIMARY_ONLY")
    certified_classification = _enum_text(certified_table_classification)
    include_policies = {"PRIMARY_WITH_CONTINUATIONS", "ALL_NOTE_TABLES"}
    legacy_anchor = status == "LEGACY_PRIMARY_ANCHOR_ONLY"
    missing_manifest = status in {"", "MISSING", "NOT_AVAILABLE", "UNRESOLVED"}
    full_manifest_available = bool(certified) and not legacy_anchor and not missing_manifest

    result: dict[str, Any] = {
        "status": "VALID",
        "issue_codes": [],
        "manifest_status": status,
        "capture_scope_policy": policy,
        "certified_table_classification": certified_classification,
        "discovered_segments": copy.deepcopy(discovered),
        "certified_segments": copy.deepcopy(certified),
        "validated_pairs": [],
        "alignment_exceptions": [],
    }

    if not certified or (policy in include_policies and not full_manifest_available):
        result["status"] = "REVIEW_REQUIRED"
        result["issue_codes"] = ["CERTIFIED_SEGMENT_MANIFEST_REQUIRED"]
        return result
    if policy == "PRIMARY_ONLY" and legacy_anchor:
        expected_segments = certified[:1]
    elif full_manifest_available:
        expected_segments = certified
    else:
        result["status"] = "REVIEW_REQUIRED"
        result["issue_codes"] = ["CERTIFIED_SEGMENT_MANIFEST_REQUIRED"]
        return result

    discovered_by_id = {
        str(segment.get("segment_id") or ""): (index, segment)
        for index, segment in enumerate(discovered)
        if segment.get("segment_id")
    }
    matched_discovered_ids: set[str] = set()
    drift_detected = False

    for certified_index, expected in enumerate(expected_segments):
        certified_segment_id = _manifest_segment_id(expected)
        runtime_segment_id = _manifest_runtime_segment_id(expected)
        match = discovered_by_id.get(runtime_segment_id)
        if match is None and legacy_anchor and certified_index == 0 and discovered:
            match = (0, discovered[0])
        if match is None:
            drift_detected = True
            result["validated_pairs"].append({
                "certified_segment_id": certified_segment_id,
                "discovered_segment_id": None,
                "page": {
                    "certified": _manifest_page(expected),
                    "discovered": None,
                    "match": False,
                },
                "classification": {
                    "certified": str(expected.get("classification") or certified_classification),
                    "discovered": None,
                    "match": False,
                },
                "header": {
                    "certified": expected.get("header_topology_fingerprint"),
                    "discovered": None,
                    "match": False,
                },
                "period": {
                    "certified": list(expected.get("period_labels") or []),
                    "discovered": None,
                    "match": False,
                },
                "lane": {
                    "certified": _manifest_lane_count(expected),
                    "discovered": None,
                    "match": False,
                },
                "continuation": {
                    "certified": expected.get("continuation_of_segment_id"),
                    "discovered": None,
                    "match": False,
                },
                "drift_fields": ["SEGMENT_MISSING"],
            })
            continue

        discovered_index, actual = match
        discovered_segment_id = str(actual.get("segment_id") or "")
        matched_discovered_ids.add(discovered_segment_id)
        expected_page = _manifest_page(expected)
        actual_page = _manifest_page(actual)
        page_match = expected_page is None or actual_page == expected_page

        expected_class = _enum_text(
            expected.get("classification") or certified_classification or ""
        )
        actual_class = _enum_text(actual.get("classification"))
        local_anchor_exception = bool(
            discovered_index == 0
            and actual_class == SegmentClassification.PRIMARY_TABLE.value
            and expected_class == SegmentClassification.SUPPLEMENTARY_TABLE.value
            and certified_classification == SegmentClassification.SUPPLEMENTARY_TABLE.value
        )
        classification_match = expected_class in {"", actual_class} or local_anchor_exception
        if local_anchor_exception:
            result["alignment_exceptions"].append({
                "code": "LOCAL_ANCHOR_CLASSIFICATION_CONTEXT",
                "certified_segment_id": certified_segment_id,
                "discovered_segment_id": discovered_segment_id,
                "certified_classification": expected_class,
                "machine_classification": actual_class,
            })

        expected_header_fingerprint = _normalise(
            expected.get("header_topology_fingerprint")
        )
        actual_header_fingerprint = _normalise(
            actual.get("header_topology_fingerprint")
        )
        expected_measures = _normalise_sequence(expected.get("measure_labels") or [])
        actual_measures = _normalise_sequence(actual.get("measure_labels") or [])
        if expected_header_fingerprint:
            header_match = bool(
                actual_header_fingerprint
                and expected_header_fingerprint == actual_header_fingerprint
            )
        elif expected_measures:
            header_match = expected_measures == actual_measures
        else:
            header_match = True
        expected_periods = _normalise_sequence(expected.get("period_labels") or [])
        actual_periods = _normalise_sequence(actual.get("period_labels") or [])
        period_match = not expected_periods or expected_periods == actual_periods
        expected_lanes = _manifest_lane_count(expected)
        actual_lanes = _manifest_lane_count(actual)
        lane_count_match = expected_lanes is None or expected_lanes == actual_lanes
        anchor_match = _anchor_match(
            actual.get("anchor_ratios") or [],
            expected.get("anchor_ratios") or [],
        )
        lane_match = lane_count_match and anchor_match is not False
        continuation_field_present = "continuation_of_segment_id" in expected
        expected_continuation = expected.get("continuation_of_segment_id")
        actual_continuation = actual.get("continuation_of_segment_id")
        continuation_match = (
            not continuation_field_present
            or expected_continuation == actual_continuation
        )
        position_match = _bbox_match(actual.get("bbox"), expected.get("bbox"))

        drift_fields = []
        if not page_match:
            drift_fields.append("PAGE")
        if not classification_match:
            drift_fields.append("CLASSIFICATION")
        if not header_match:
            drift_fields.append("HEADER")
        if not period_match:
            drift_fields.append("PERIOD")
        if not lane_match:
            drift_fields.append("LANE")
        if not continuation_match:
            drift_fields.append("CONTINUATION_RELATION")
        if position_match is False:
            drift_fields.append("BBOX")
        if drift_fields:
            drift_detected = True

        result["validated_pairs"].append({
            "certified_segment_id": certified_segment_id,
            "discovered_segment_id": discovered_segment_id,
            "page": {
                "certified": expected_page,
                "discovered": actual_page,
                "match": page_match,
            },
            "classification": {
                "certified": expected_class,
                "discovered": actual_class,
                "match": classification_match,
            },
            "header": {
                "certified": expected_header_fingerprint,
                "discovered": actual_header_fingerprint,
                "match": header_match,
            },
            "period": {
                "certified": list(expected.get("period_labels") or []),
                "discovered": list(actual.get("period_labels") or []),
                "match": period_match,
            },
            "lane": {
                "certified": expected_lanes,
                "discovered": actual_lanes,
                "match": lane_match,
            },
            "continuation": {
                "certified": expected_continuation,
                "discovered": actual_continuation,
                "match": continuation_match,
            },
            "bbox": {
                "certified": copy.deepcopy(expected.get("bbox")),
                "discovered": copy.deepcopy(actual.get("bbox")),
                "match": position_match,
            },
            "drift_fields": drift_fields,
        })

    if full_manifest_available and policy in include_policies:
        relevant_classes = (
            {
                SegmentClassification.PRIMARY_TABLE.value,
                SegmentClassification.CONTINUATION_SEGMENT.value,
            }
            if policy == "PRIMARY_WITH_CONTINUATIONS"
            else {
                SegmentClassification.PRIMARY_TABLE.value,
                SegmentClassification.CONTINUATION_SEGMENT.value,
                SegmentClassification.SUPPLEMENTARY_TABLE.value,
                SegmentClassification.UNRESOLVED.value,
            }
        )
        unexpected = [
            str(segment.get("segment_id") or "")
            for segment in discovered
            if _enum_text(segment.get("classification")) in relevant_classes
            and str(segment.get("segment_id") or "") not in matched_discovered_ids
        ]
        if unexpected:
            drift_detected = True
            result["unexpected_discovered_segment_ids"] = unexpected

    if drift_detected:
        result["status"] = "REVIEW_REQUIRED"
        result["issue_codes"] = ["CERTIFIED_SEGMENT_MANIFEST_DRIFT"]
    return result
