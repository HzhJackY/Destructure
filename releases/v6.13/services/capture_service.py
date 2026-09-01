from __future__ import annotations
import datetime as dt
import hashlib
import json
import re
from pathlib import Path
from typing import Any, Optional

from repositories.capture_repository import CaptureRepository
from registry_bridge import sync_capture_run
from certified_roi_membership import (
    CERTIFIED_ROI_ROW_MEMBERSHIP_SEMANTICS,
    belongs_to_certified_roi,
    normalise_bbox,
)
from capture_models import (
    CAPTURE_SCOPE_CONTRACT_VERSION,
    LEGACY_CAPTURE_SCOPE_CONTRACT_VERSION,
    CaptureMode,
    CaptureRequest,
    CaptureScopePolicy,
    ResolvedCaptureTarget,
    normalise_capture_scope_contract,
    normalise_capture_scope_selection,
)


_CERTIFIED_MANIFEST_POLICIES = {
    CaptureScopePolicy.PRIMARY_WITH_CONTINUATIONS.value,
    CaptureScopePolicy.ALL_NOTE_TABLES.value,
    CaptureScopePolicy.SELECTED_NOTE_TABLES.value,
}


def _certified_member_for_axis(
    certified_target: dict[str, Any] | None,
    classification_axis: str,
    fallback: str,
) -> str:
    target = dict(certified_target or {})
    axes = [str(value) for value in target.get("classification_axes") or []]
    members = [str(value) for value in target.get("member_table_ids") or []]
    if len(axes) == len(members) and classification_axis in axes:
        return members[axes.index(classification_axis)]
    for conditional in target.get("conditional_logical_members") or []:
        if str(conditional.get("classification_axis") or "") == classification_axis:
            return str(conditional.get("member_id") or fallback)
    if classification_axis == "PORTFOLIO_SUMMARY":
        return "portfolio_summary"
    return str(fallback)


def _explicit_certified_member_for_axis(
    certified_target: dict[str, Any] | None,
    classification_axis: str,
) -> str | None:
    target = dict(certified_target or {})
    axes = [str(value) for value in target.get("classification_axes") or []]
    members = [str(value) for value in target.get("member_table_ids") or []]
    if len(axes) == len(members) and classification_axis in axes:
        return members[axes.index(classification_axis)]
    for conditional in target.get("conditional_logical_members") or []:
        if str(conditional.get("classification_axis") or "") == classification_axis:
            return str(conditional.get("member_id") or "").strip() or None
    if classification_axis == "PORTFOLIO_SUMMARY":
        return "portfolio_summary"
    return None


def _direct_bundle_order(block: Any) -> tuple[int, int]:
    """Keep category as compatibility root while preserving physical order."""
    axis = str(getattr(block, "classification_axis", "") or "")
    priority = {
        "BY_INVESTMENT_OBJECT": 0,
        "PORTFOLIO_SUMMARY": 1,
        "BY_ACCOUNTING_MEASUREMENT": 2,
        "UNRESOLVED": 3,
    }.get(axis, 4)
    return priority, int(getattr(block, "block_order", 0) or 0)


def _capture_bundle_identity(
    *,
    container_id: str,
    certified_logical_table_id: str,
    capture_request_id: str,
    root_capture_id: str,
    scope_selection: dict[str, Any],
) -> dict[str, str]:
    scope_payload = {
        "capture_scope_contract_version":int(
            scope_selection.get("capture_scope_contract_version") or 1
        ),
        "capture_scope_policy":str(
            scope_selection.get("capture_scope_policy") or ""
        ),
        "requested_capture_scope_policy":str(
            scope_selection.get("requested_capture_scope_policy") or ""
        ),
        "selected_logical_table_ids":sorted({
            str(value) for value in (
                scope_selection.get("selected_logical_table_ids") or []
            ) if str(value)
        }),
        "selected_block_roles":sorted({
            str(value) for value in (
                scope_selection.get("selected_block_roles") or []
            ) if str(value)
        }),
        "selected_block_ids":sorted({
            str(value) for value in (
                scope_selection.get("selected_block_ids") or []
            ) if str(value)
        }),
    }
    scope_json = json.dumps(
        scope_payload,ensure_ascii=False,sort_keys=True,separators=(",",":"),
    )
    scope_signature = hashlib.sha256(scope_json.encode("utf-8")).hexdigest()[:24]
    target_payload = {
        "container_id":str(container_id),
        "certified_logical_table_id":str(certified_logical_table_id),
        "scope_signature":scope_signature,
    }
    target_json = json.dumps(
        target_payload,ensure_ascii=False,sort_keys=True,separators=(",",":"),
    )
    bundle_target_key = "BTARGET_" + hashlib.sha256(
        target_json.encode("utf-8")
    ).hexdigest()[:24]
    execution_payload = {
        "bundle_target_key":bundle_target_key,
        "capture_request_id":str(capture_request_id),
        "root_capture_id":str(root_capture_id),
    }
    execution_json = json.dumps(
        execution_payload,ensure_ascii=False,sort_keys=True,separators=(",",":"),
    )
    return {
        "bundle_id":"BUNDLE_" + hashlib.sha256(
            execution_json.encode("utf-8")
        ).hexdigest()[:24],
        "bundle_target_key":bundle_target_key,
        "bundle_scope_signature":scope_signature,
    }


def _validate_bundle_child_orders(values: list[int]) -> tuple[int,...]:
    orders = tuple(int(value) for value in values)
    if orders.count(0) != 1:
        raise ValueError("CAPTURE_BUNDLE_ROOT_CARDINALITY_INVALID")
    if any(value < 0 for value in orders) or len(set(orders)) != len(orders):
        raise ValueError("CAPTURE_BUNDLE_CHILD_ORDER_INVALID")
    if orders != tuple(range(len(orders))):
        raise ValueError("CAPTURE_BUNDLE_CHILD_ORDER_INVALID")
    return orders


def _replace_capture_bundle_children(
    conn: Any,
    *,
    bundle_id: str,
    children: list[dict[str, Any]],
    created_at: str,
) -> None:
    conn.execute(
        "DELETE FROM capture_bundle_children WHERE bundle_id=?",
        (bundle_id,),
    )
    for child in children:
        conn.execute(
            """INSERT INTO capture_bundle_children
               (bundle_id,block_id,capture_id,logical_asset_id,child_order,
                status,payload_json,created_at)
               VALUES(?,?,?,?,?,?,?,?)""",
            (
                bundle_id,
                child["block_id"],
                child["capture_id"],
                child.get("logical_asset_id"),
                int(child["child_order"]),
                child["status"],
                child["payload_json"],
                created_at,
            ),
        )


def _note_references_match(left: Any,right: Any) -> bool:
    left_value = "".join(str(left or "").split())
    right_value = "".join(str(right or "").split())
    if not left_value or not right_value or left_value == right_value:
        return True
    from table_boundary_resolver import parse_note_ordinal
    left_ordinal = parse_note_ordinal(left_value)
    right_ordinal = parse_note_ordinal(right_value)
    if left_ordinal is None or right_ordinal is None:
        return False
    bare_pattern = re.compile(
        r"^[（(]?(?:\d{1,3}|[零〇一二三四五六七八九十百]{1,5})"
        r"[）)]?[.．、]?$"
    )
    return left_ordinal == right_ordinal and bool(
        bare_pattern.fullmatch(left_value)
        or bare_pattern.fullmatch(right_value)
    )


def _normalise_certified_bbox(value: Any) -> list[float]:
    if isinstance(value, (list, tuple)):
        return [float(item) for item in value]
    if not isinstance(value, dict):
        return []
    coordinates = (
        value.get("x0"),
        value.get("y0", value.get("top")),
        value.get("x1"),
        value.get("y1", value.get("bottom")),
    )
    if any(item is None for item in coordinates):
        return []
    return [float(item) for item in coordinates]


def _normalise_certified_segments_for_runtime(
    certified_segments: list[dict[str, Any]],
    discovered_segments: list[dict[str, Any]],
    *,
    target_logical_bbox: Any = None,
) -> list[dict[str, Any]]:
    indexed_segments = list(enumerate(certified_segments))
    indexed_segments.sort(key=lambda item: int(item[1].get("order", item[0])))
    runtime_ids_by_certified_id: dict[str, str] = {}

    def _page_range(segment: dict[str, Any]) -> tuple[int | None, int | None]:
        def _as_int(value: Any) -> int | None:
            try:
                return int(value) if value is not None else None
            except (TypeError, ValueError):
                return None

        start = _as_int(
            segment.get("pdf_page_number")
            or segment.get("start_page")
            or segment.get("page")
        )
        end = _as_int(
            segment.get("end_page")
            or segment.get("end_page_hint")
            or start
        )
        return start, end or start

    def _bbox(segment: dict[str, Any]) -> list[float]:
        return _normalise_certified_bbox(segment.get("bbox"))

    context_bboxes: dict[int, list[list[float]]] = {}
    raw_context_pages = (
        target_logical_bbox.get("pages")
        if isinstance(target_logical_bbox, dict)
        else None
    )
    if isinstance(raw_context_pages, list):
        for page_entry in raw_context_pages:
            if not isinstance(page_entry, dict):
                continue
            try:
                page_number = int(page_entry.get("page"))
            except (TypeError, ValueError):
                continue
            page_bbox = _normalise_certified_bbox(page_entry.get("bbox"))
            if page_bbox:
                context_bboxes.setdefault(page_number, []).append(page_bbox)
    elif isinstance(target_logical_bbox, dict):
        page_bbox = _normalise_certified_bbox(target_logical_bbox.get("bbox"))
        if page_bbox:
            page_number = target_logical_bbox.get("page")
            try:
                context_bboxes.setdefault(int(page_number), []).append(page_bbox)
            except (TypeError, ValueError):
                pass

    def _bbox_overlap(left: list[float], right: list[float]) -> float | None:
        if len(left) != 4 or len(right) != 4:
            return None
        lx0, ly0, lx1, ly1 = left
        rx0, ry0, rx1, ry1 = right
        left_area = max(0.0, lx1 - lx0) * max(0.0, ly1 - ly0)
        right_area = max(0.0, rx1 - rx0) * max(0.0, ry1 - ry0)
        if left_area <= 0.0 or right_area <= 0.0:
            return None
        ix = max(0.0, min(lx1, rx1) - max(lx0, rx0))
        iy = max(0.0, min(ly1, ry1) - max(ly0, ry0))
        return (ix * iy) / left_area

    def _bbox_exact(left: list[float], right: list[float]) -> bool:
        return bool(
            len(left) == 4
            and len(right) == 4
            and all(
                abs(float(left[index]) - float(right[index])) <= 12.0
                for index in range(4)
            )
        )

    def _classification(segment: dict[str, Any]) -> str:
        return str(
            segment.get("classification")
            or segment.get("segment_classification")
            or ""
        ).strip().upper()

    def _sequence(segment: dict[str, Any], key: str, nested: str) -> tuple[str, ...]:
        values = segment.get(key)
        if not values:
            values = (segment.get(nested) or {}).get(key) or []
        return tuple(str(value).strip() for value in values if str(value).strip())

    def _anchor_ratios(segment: dict[str, Any]) -> tuple[float, ...]:
        values = segment.get("anchor_ratios")
        if not values:
            values = (segment.get("amount_lane_signature") or {}).get(
                "anchor_ratios"
            ) or []
        try:
            return tuple(float(value) for value in values)
        except (TypeError, ValueError):
            return ()

    def _header_fingerprint(segment: dict[str, Any]) -> str:
        return str(
            segment.get("header_topology_fingerprint")
            or (segment.get("header_signature") or {}).get("fingerprint")
            or ""
        ).strip()

    def _match_score(certified: dict[str, Any], discovered: dict[str, Any]) -> tuple:
        certified_start, certified_end = _page_range(certified)
        discovered_start, discovered_end = _page_range(discovered)
        page_match = bool(
            certified_start is not None
            and discovered_start is not None
            and discovered_start <= certified_start <= (discovered_end or discovered_start)
        )
        class_match = bool(
            _classification(certified)
            and _classification(certified) == _classification(discovered)
        )
        certified_bbox = _bbox(certified)
        discovered_bbox = _bbox(discovered)
        if not certified_bbox and certified_start is not None:
            context_candidates = context_bboxes.get(certified_start) or []
            if context_candidates:
                certified_bbox = context_candidates[0]
        bbox_exact = _bbox_exact(discovered_bbox, certified_bbox)
        overlap = _bbox_overlap(certified_bbox, discovered_bbox) or 0.0
        certified_periods = _sequence(certified, "period_labels", "period_signature")
        discovered_periods = _sequence(discovered, "period_labels", "period_signature")
        period_match = bool(
            certified_periods and discovered_periods
            and certified_periods == discovered_periods
        )
        header_match = bool(
            _header_fingerprint(certified)
            and _header_fingerprint(certified) == _header_fingerprint(discovered)
        )
        certified_anchors = _anchor_ratios(certified)
        discovered_anchors = _anchor_ratios(discovered)
        anchor_match = bool(
            certified_anchors
            and discovered_anchors
            and len(certified_anchors) == len(discovered_anchors)
            and all(
                abs(left - right) <= 0.04
                for left, right in zip(certified_anchors, discovered_anchors)
            )
        )
        # Page and classification are identity evidence; bbox/signatures break
        # ties when several logical segments share one physical page.
        return (
            int(page_match),
            int(class_match),
            int(bbox_exact),
            round(overlap, 6),
            int(header_match),
            int(period_match),
            int(anchor_match),
        )

    used_runtime_ids: set[str] = set()
    for _, certified in indexed_segments:
        certified_id = str(
            certified.get("certified_segment_id")
            or certified.get("segment_id")
            or ""
        ).strip()
        if not certified_id:
            continue
        explicit_runtime_id = str(
            certified.get("runtime_segment_id") or ""
        ).strip()
        explicit = next(
            (
                segment for segment in discovered_segments
                if str(segment.get("segment_id") or "").strip()
                == explicit_runtime_id
                and explicit_runtime_id
                and explicit_runtime_id not in used_runtime_ids
            ),
            None,
        )
        candidates = [
            segment for segment in discovered_segments
            if str(segment.get("segment_id") or "").strip()
            and str(segment.get("segment_id") or "").strip()
            not in used_runtime_ids
        ]
        if explicit is not None:
            selected = explicit
        else:
            certified_start, _ = _page_range(certified)
            page_candidates = [
                segment for segment in candidates
                if certified_start is not None
                and _page_range(segment)[0] == certified_start
            ]
            pool = page_candidates or candidates
            selected = None
            if len(pool) == 1:
                selected = pool[0]
            elif pool:
                ranked = sorted(
                    pool,
                    key=lambda segment: _match_score(certified, segment),
                    reverse=True,
                )
                top_score = _match_score(certified, ranked[0])
                next_score = (
                    _match_score(certified, ranked[1])
                    if len(ranked) > 1 else None
                )
                # Do not fall back to array position when identity evidence is
                # ambiguous; leaving the runtime ID absent keeps governance
                # fail-closed instead of certifying the wrong segment.
                if next_score is None or top_score > next_score:
                    selected = ranked[0]
        runtime_id = str(
            (selected or {}).get("segment_id") or ""
        ).strip()
        if runtime_id:
            runtime_ids_by_certified_id[certified_id] = runtime_id
            used_runtime_ids.add(runtime_id)

    normalised: list[dict[str, Any]] = []
    for runtime_index, (_, certified) in enumerate(indexed_segments):
        payload = dict(certified)
        period_signature = dict(payload.get("period_signature") or {})
        header_signature = dict(payload.get("header_signature") or {})
        lane_signature = dict(payload.get("amount_lane_signature") or {})
        runtime_id = str(
            runtime_ids_by_certified_id.get(
                str(
                    certified.get("certified_segment_id")
                    or certified.get("segment_id")
                    or ""
                ).strip()
            )
            or ""
        ).strip()
        if runtime_id:
            payload["runtime_segment_id"] = runtime_id
        if payload.get("pdf_page_number") is None and payload.get("start_page") is not None:
            payload["pdf_page_number"] = int(payload["start_page"])
        payload["bbox"] = _normalise_certified_bbox(payload.get("bbox"))
        payload["period_labels"] = list(
            payload.get("period_labels")
            or period_signature.get("period_labels")
            or period_signature.get("periods")
            or []
        )
        header_columns = list(header_signature.get("columns") or [])
        payload["measure_labels"] = list(
            payload.get("measure_labels")
            or header_signature.get("labels")
            or (
                header_columns
                if [str(value) for value in header_columns]
                != [str(value) for value in payload["period_labels"]]
                else []
            )
            or []
        )
        payload["header_topology_fingerprint"] = str(
            payload.get("header_topology_fingerprint")
            or header_signature.get("fingerprint")
            or ""
        )
        if payload.get("lane_count") is None and lane_signature.get("lane_count") is not None:
            payload["lane_count"] = int(lane_signature["lane_count"])
        payload["anchor_ratios"] = list(
            payload.get("anchor_ratios")
            or lane_signature.get("anchor_ratios")
            or []
        )
        payload["source_column_ordinals"] = list(
            payload.get("source_column_ordinals")
            or lane_signature.get("source_column_ordinals")
            or []
        )
        certified_parent_id = str(
            payload.get("continuation_of_segment_id") or ""
        ).strip()
        if certified_parent_id:
            payload["continuation_of_segment_id"] = (
                runtime_ids_by_certified_id.get(certified_parent_id)
                or certified_parent_id
            )
        normalised.append(payload)
    return normalised


def _bbox_payload(value: Any) -> dict[str, float]:
    return normalise_bbox(value)


def _compact_identity_text(value: Any) -> str:
    return re.sub(r"[\s（）()：:·•]+", "", str(value or "")).lower()


def _validate_direct_portfolio_physical_manifest(
    result: Any,
    *,
    discovered_segments: list[dict[str, Any]],
    certified_segments: list[dict[str, Any]],
    manifest_status: str,
    target: dict[str, Any],
) -> dict[str, Any]:
    """Validate a certified direct-disclosure ROI without note-table rules.

    The generic manifest validator compares note-specific column and
    continuation signatures.  A direct portfolio table is instead certified
    by one physical asset identity, page, source heading, and a closed ROI.
    Every extracted row must remain inside that ROI.
    """
    issue_codes: list[str] = []
    if manifest_status != "CERTIFIED_SEGMENT_MANIFEST":
        issue_codes.append("CERTIFIED_SEGMENT_MANIFEST_REQUIRED")
    if len(certified_segments) != 1:
        issue_codes.append("DIRECT_PORTFOLIO_CERTIFIED_SEGMENT_COUNT_INVALID")
    if len(discovered_segments) != 1:
        issue_codes.append("DIRECT_PORTFOLIO_RUNTIME_SEGMENT_COUNT_INVALID")
    certified = certified_segments[0] if len(certified_segments) == 1 else {}
    discovered = discovered_segments[0] if len(discovered_segments) == 1 else {}
    certified_bbox = _bbox_payload(certified.get("bbox"))
    if (
        not certified_bbox
        or certified_bbox["x1"] <= certified_bbox["x0"]
        or certified_bbox["y1"] <= certified_bbox["y0"]
    ):
        issue_codes.append("DIRECT_PORTFOLIO_CERTIFIED_BBOX_INVALID")
    try:
        certified_page = int(
            certified.get("pdf_page_number")
            or certified.get("start_page")
        )
    except (TypeError, ValueError):
        certified_page = 0
        issue_codes.append("DIRECT_PORTFOLIO_CERTIFIED_PAGE_REQUIRED")
    try:
        discovered_page = int(discovered.get("pdf_page_number") or 0)
    except (TypeError, ValueError):
        discovered_page = 0
    if certified_page and discovered_page != certified_page:
        issue_codes.append("DIRECT_PORTFOLIO_RUNTIME_PAGE_DRIFT")
    if str(discovered.get("classification") or "").upper() != "PRIMARY_TABLE":
        issue_codes.append("DIRECT_PORTFOLIO_RUNTIME_CLASSIFICATION_DRIFT")

    target_heading = _compact_identity_text(
        target.get("target_heading") or target.get("capture_query_title")
    )
    runtime_heading = _compact_identity_text(
        discovered.get("table_identity")
        or discovered.get("text_evidence")
        or getattr(result, "located_title", "")
    )
    if not target_heading or (
        target_heading not in runtime_heading
        and runtime_heading not in target_heading
    ):
        issue_codes.append("DIRECT_PORTFOLIO_RUNTIME_HEADING_DRIFT")

    active_rows = [
        row
        for row in list(getattr(result, "rows", []) or [])
        if not getattr(row, "excluded_from_table_logic", False)
    ]
    if not active_rows:
        issue_codes.append("DIRECT_PORTFOLIO_RUNTIME_ROWS_REQUIRED")
    if certified_page and any(
        int(getattr(row, "page", 0) or 0) != certified_page
        for row in active_rows
    ):
        issue_codes.append("DIRECT_PORTFOLIO_RUNTIME_ROW_PAGE_DRIFT")
    for row in active_rows:
        row_bbox = _bbox_payload(getattr(row, "bbox", None))
        if not row_bbox:
            issue_codes.append("DIRECT_PORTFOLIO_RUNTIME_ROW_BBOX_REQUIRED")
            break
        if certified_bbox and not belongs_to_certified_roi(
            row_bbox, certified_bbox
        ):
            issue_codes.append("DIRECT_PORTFOLIO_RUNTIME_ROW_OUTSIDE_CERTIFIED_ROI")
            break
    issue_codes = list(dict.fromkeys(issue_codes))
    certified_id = str(certified.get("certified_segment_id") or "")
    discovered_id = str(discovered.get("segment_id") or "")
    return {
        "status": "VALID" if not issue_codes else "REVIEW_REQUIRED",
        "issue_codes": issue_codes,
        "manifest_status": manifest_status,
        "validation_mode": "DIRECT_PORTFOLIO_PHYSICAL_ROI",
        "row_membership_semantics": (
            CERTIFIED_ROI_ROW_MEMBERSHIP_SEMANTICS
        ),
        "physical_asset_id": str(target.get("physical_asset_id") or ""),
        "classification_axis": str(target.get("classification_axis") or ""),
        "validated_pairs": (
            [{
                "certified_segment_id": certified_id,
                "discovered_segment_id": discovered_id,
                "drift_fields": list(issue_codes),
            }]
            if certified_id or discovered_id
            else []
        ),
        "discovered_segments": list(discovered_segments),
        "certified_segments": list(certified_segments),
    }


def _validate_certified_scope_governance(
    result: Any,
    *,
    certified_note_target: dict[str, Any] | None,
    capture_scope_contract_version: int = LEGACY_CAPTURE_SCOPE_CONTRACT_VERSION,
    capture_scope_policy: str | CaptureScopePolicy,
    selected_logical_table_ids: list[str] | tuple[str, ...] | None = None,
    enabled: bool,
    registry: Any | None = None,
) -> dict[str, Any]:
    (
        contract_version,policy,logical_table_ids,_,_,
    ) = normalise_capture_scope_contract(
        capture_scope_contract_version,
        capture_scope_policy,
        selected_logical_table_ids,
        None,
        None,
    )
    stats = dict(getattr(result, "stats", {}) or {})
    discovered_segments = [
        dict(segment)
        for segment in (stats.get("physical_table_segments") or [])
        if isinstance(segment, dict)
    ]
    if not enabled:
        return {
            "issue_codes": [],
            "manifest_validation": {
                "status": "NOT_APPLICABLE",
                "issue_codes": [],
                "capture_scope_contract_version": contract_version,
                "capture_scope_policy": policy,
            },
            "inventory_validation": {
                "status": "NOT_APPLICABLE",
                "required": False,
            },
        }

    target = dict(certified_note_target or {})
    direct_portfolio_table = bool(target.get("direct_portfolio_table"))
    manifest_status = str(
        target.get("segment_manifest_status")
        or "LEGACY_PRIMARY_ANCHOR_ONLY"
    ).strip().upper()
    table_classification = str(
        target.get("table_classification")
        or (
            "PRIMARY_TABLE"
            if contract_version == LEGACY_CAPTURE_SCOPE_CONTRACT_VERSION
            else ""
        )
    ).strip().upper()
    logical_table_id = str(target.get("logical_table_id") or "").strip()
    target_issue_codes: list[str] = []
    if contract_version == CAPTURE_SCOPE_CONTRACT_VERSION:
        if (
            not logical_table_id
            or table_classification not in {
                "PRIMARY_TABLE","SUPPLEMENTARY_TABLE",
            }
        ):
            target_issue_codes.append("CERTIFIED_LOGICAL_TABLE_REQUIRED")
        elif table_classification == "SUPPLEMENTARY_TABLE" and (
            policy != CaptureScopePolicy.SELECTED_NOTE_TABLES.value
            or logical_table_id not in set(logical_table_ids)
        ):
            target_issue_codes.append(
                "CERTIFIED_SELECTED_LOGICAL_TABLE_REQUIRED"
            )
    if direct_portfolio_table and (
        not str(target.get("physical_asset_id") or "").strip()
        or not str(target.get("classification_axis") or "").strip()
        or str(target.get("relation_type") or "").strip().upper()
        != "DIRECT_PORTFOLIO_WHOLE_TABLE"
    ):
        target_issue_codes.append(
            "CERTIFIED_DIRECT_PORTFOLIO_IDENTITY_REQUIRED"
        )
    certified_segments = [
        dict(segment)
        for segment in (target.get("certified_segments") or [])
        if isinstance(segment, dict)
    ]
    if (
        contract_version == LEGACY_CAPTURE_SCOPE_CONTRACT_VERSION
        and manifest_status == "LEGACY_PRIMARY_ANCHOR_ONLY"
        and not certified_segments
    ):
        certified_segments = [{
            "certified_segment_id": str(
                target.get("certified_link_id") or "LEGACY_PRIMARY_ANCHOR"
            ),
            "order": 0,
            "classification": table_classification,
            "start_page": target.get("confirmed_note_pdf_page_index"),
            "pdf_page_number": target.get("confirmed_note_pdf_page_index"),
        }]
    target_evidence = target.get("evidence")
    if not isinstance(target_evidence, dict):
        target_evidence = {}
    target_logical_bbox = target_evidence.get("logical_table_bbox")
    normalised_segments = _normalise_certified_segments_for_runtime(
        certified_segments,
        discovered_segments,
        target_logical_bbox=target_logical_bbox,
    )
    if direct_portfolio_table:
        manifest_validation = _validate_direct_portfolio_physical_manifest(
            result,
            discovered_segments=discovered_segments,
            certified_segments=certified_segments,
            manifest_status=manifest_status,
            target=target,
        )
    else:
        from table_segment_classifier import validate_certified_segment_manifest
        manifest_validation = validate_certified_segment_manifest(
            discovered_segments,
            normalised_segments,
            manifest_status,
            (
                CaptureScopePolicy.PRIMARY_ONLY.value
                if contract_version == CAPTURE_SCOPE_CONTRACT_VERSION
                else policy
            ),
            table_classification,
        )
    manifest_validation = {
        **manifest_validation,
        "capture_scope_contract_version":contract_version,
        "capture_scope_policy":policy,
    }
    manifest_issue_codes = list(
        manifest_validation.get("issue_codes") or []
    )
    if (
        contract_version == CAPTURE_SCOPE_CONTRACT_VERSION
        and (
            manifest_status != "CERTIFIED_SEGMENT_MANIFEST"
            or not certified_segments
        )
    ):
        manifest_issue_codes = list(dict.fromkeys([
            *manifest_issue_codes,
            "CERTIFIED_SEGMENT_MANIFEST_REQUIRED",
        ]))
        manifest_validation = {
            **manifest_validation,
            "status":"REVIEW_REQUIRED",
            "issue_codes":manifest_issue_codes,
            "capture_scope_contract_version":contract_version,
            "capture_scope_policy":policy,
        }

    inventory_required = (
        policy in _CERTIFIED_MANIFEST_POLICIES
        if contract_version == LEGACY_CAPTURE_SCOPE_CONTRACT_VERSION
        else table_classification == "SUPPLEMENTARY_TABLE"
    )
    inventory_id = str(target.get("note_table_inventory_id") or "").strip()
    inventory_status = str(
        target.get("note_table_inventory_status") or ""
    ).strip().upper()
    inventory_record: dict[str, Any] | None = None
    if (
        inventory_required
        and contract_version == CAPTURE_SCOPE_CONTRACT_VERSION
        and registry is not None
        and inventory_id
    ):
        with registry.connect() as conn:
            row = conn.execute(
                """SELECT * FROM certified_note_table_inventories
                   WHERE note_table_inventory_id=?""",
                (inventory_id,),
            ).fetchone()
        inventory_record = dict(row) if row else None
    inventory_logical_ids: list[str] = []
    if inventory_record:
        try:
            parsed_logical_ids = json.loads(
                inventory_record.get("logical_table_ids_json") or "[]"
            )
        except (TypeError,json.JSONDecodeError):
            parsed_logical_ids = []
        if isinstance(parsed_logical_ids,list):
            inventory_logical_ids = [
                str(value) for value in parsed_logical_ids if str(value)
            ]
    inventory_valid = not inventory_required
    if (
        inventory_required
        and contract_version == LEGACY_CAPTURE_SCOPE_CONTRACT_VERSION
    ):
        inventory_valid = bool(
            inventory_id and inventory_status == "COMPLETE"
        )
    elif inventory_required:
        source_pdf_matches = bool(
            inventory_record
            and (
                not str(target.get("source_pdf_id") or "")
                or str(inventory_record.get("source_pdf_id") or "")
                == str(target.get("source_pdf_id") or "")
            )
        )
        note_matches = bool(
            inventory_record
            and _note_references_match(
                inventory_record.get("note_reference"),
                target.get("note_reference"),
            )
        )
        inventory_valid = bool(
            inventory_record
            and str(
                inventory_record.get("inventory_status") or ""
            ).upper() == "COMPLETE"
            and str(
                inventory_record.get("certification_status") or ""
            ).upper() == "CERTIFIED"
            and source_pdf_matches
            and note_matches
            and logical_table_id in set(inventory_logical_ids)
        )
    inventory_validation = {
        "status": "VALID" if inventory_valid else "REVIEW_REQUIRED",
        "required": inventory_required,
        "capture_scope_contract_version":contract_version,
        "note_table_inventory_id": inventory_id,
        "note_table_inventory_status": inventory_status,
        "registry_authority_checked": bool(
            inventory_required
            and contract_version == CAPTURE_SCOPE_CONTRACT_VERSION
        ),
        "registry_inventory_found": bool(inventory_record),
        "logical_table_ids":inventory_logical_ids,
        "issue_codes": (
            [] if inventory_valid else ["CERTIFIED_NOTE_TABLE_INVENTORY_REQUIRED"]
        ),
    }
    issue_codes = list(dict.fromkeys([
        *target_issue_codes,
        *manifest_issue_codes,
        *list(inventory_validation["issue_codes"]),
    ]))
    return {
        "issue_codes": issue_codes,
        "manifest_validation": manifest_validation,
        "inventory_validation": inventory_validation,
    }


def _block_segment_ids(block: Any) -> tuple[str, ...]:
    values = getattr(block, "physical_segment_ids", None)
    if not values:
        evidence = dict(getattr(block, "evidence", {}) or {})
        values = evidence.get("physical_segment_ids") or []
    return tuple(
        dict.fromkeys(str(value).strip() for value in values if str(value).strip())
    )


def _block_segment_classification(block: Any) -> str:
    evidence = dict(getattr(block, "evidence", {}) or {})
    return str(
        getattr(block, "segment_classification", "")
        or evidence.get("segment_classification")
        or evidence.get("classification")
        or "UNRESOLVED"
    ).strip().upper()


def _segment_root(
    segment_id: str,
    segment_map: dict[str, dict[str, Any]],
) -> tuple[str, str] | None:
    current_id = str(segment_id or "").strip()
    visited: set[str] = set()
    while current_id and current_id not in visited:
        visited.add(current_id)
        if current_id not in segment_map:
            return None
        segment = segment_map[current_id]
        classification = str(
            segment.get("classification")
            or segment.get("segment_classification")
            or "UNRESOLVED"
        ).strip().upper()
        if classification != "CONTINUATION_SEGMENT":
            return current_id, classification
        current_id = str(segment.get("continuation_of_segment_id") or "").strip()
    return None


def _select_blocks_for_scope(
    result: Any,
    blocks: list[Any],
    *,
    capture_scope_contract_version: int = LEGACY_CAPTURE_SCOPE_CONTRACT_VERSION,
    capture_scope_policy: str | CaptureScopePolicy,
    selected_logical_table_ids: list[str] | tuple[str, ...] | None = None,
    selected_block_roles: list[str] | tuple[str, ...] | None,
    selected_block_ids: list[str] | tuple[str, ...] | None,
    certified_manifest_validation: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if int(capture_scope_contract_version) == CAPTURE_SCOPE_CONTRACT_VERSION:
        (
            contract_version,policy,_,role_filter,id_filter,
        ) = normalise_capture_scope_contract(
            capture_scope_contract_version,
            capture_scope_policy,
            selected_logical_table_ids,
            selected_block_roles,
            selected_block_ids,
        )
    else:
        policy,role_filter,id_filter = normalise_capture_scope_selection(
            capture_scope_policy,
            selected_block_roles,
            selected_block_ids,
        )
        contract_version = LEGACY_CAPTURE_SCOPE_CONTRACT_VERSION
    stats = dict(getattr(result, "stats", {}) or {})
    physical_segments = [
        dict(segment)
        for segment in (stats.get("physical_table_segments") or [])
        if isinstance(segment, dict)
    ]
    segment_map = {
        str(segment.get("segment_id") or "").strip(): segment
        for segment in physical_segments
        if str(segment.get("segment_id") or "").strip()
    }
    for block in blocks:
        segment_ids = _block_segment_ids(block)
        if len(segment_ids) > 1:
            raise ValueError("CAPTURE_BLOCK_MIXED_PHYSICAL_SEGMENTS")
        manifest_classifications = {
            str(
                segment_map[segment_id].get("classification")
                or segment_map[segment_id].get("segment_classification")
                or "UNRESOLVED"
            ).strip().upper()
            for segment_id in segment_ids
            if segment_id in segment_map
        }
        if manifest_classifications and manifest_classifications != {
            _block_segment_classification(block)
        }:
            raise ValueError("CAPTURE_BLOCK_SEGMENT_CLASSIFICATION_CONFLICT")
    if contract_version == CAPTURE_SCOPE_CONTRACT_VERSION:
        validation = dict(certified_manifest_validation or {})
        validation_pairs = list(validation.get("validated_pairs") or [])
        validation_issue_codes = list(validation.get("issue_codes") or [])
        if (
            str(validation.get("status") or "") != "VALID"
            or validation_issue_codes
            or any(pair.get("drift_fields") for pair in validation_pairs)
        ):
            raise PermissionError(
                "CERTIFIED_SEGMENT_MANIFEST_VALIDATION_REQUIRED"
            )
        runtime_segment_id_list = [
            str(pair.get("discovered_segment_id") or "")
            for pair in validation_pairs
        ]
        selected_runtime_segment_ids = set(runtime_segment_id_list)
        if (
            not selected_runtime_segment_ids
            or any(not value for value in runtime_segment_id_list)
            or len(selected_runtime_segment_ids)
            != len(runtime_segment_id_list)
        ):
            raise PermissionError("CERTIFIED_SEGMENT_MANIFEST_RUNTIME_MATCH_REQUIRED")
        selected = [
            block for block in blocks
            if selected_runtime_segment_ids.intersection(
                _block_segment_ids(block)
            )
        ]
        excluded = [block for block in blocks if block not in selected]
        if not selected:
            raise PermissionError("CERTIFIED_LOGICAL_TABLE_SEGMENTS_REQUIRED")
        selected_runtime_occurrences = [
            segment_id
            for block in selected
            for segment_id in _block_segment_ids(block)
            if segment_id in selected_runtime_segment_ids
        ]
        if (
            set(selected_runtime_occurrences)
            != selected_runtime_segment_ids
        ):
            raise PermissionError("CERTIFIED_LOGICAL_TABLE_SEGMENTS_REQUIRED")
        selected_segment_ids = {
            segment_id
            for block in selected
            for segment_id in _block_segment_ids(block)
        }
        excluded_segment_ids = {
            segment_id
            for block in excluded
            for segment_id in _block_segment_ids(block)
        }
        selected_manifest = [
            segment for segment in physical_segments
            if str(segment.get("segment_id") or "")
            in selected_segment_ids
        ]
        excluded_manifest = [
            segment for segment in physical_segments
            if str(segment.get("segment_id") or "")
            in excluded_segment_ids
        ]
        decision_scope_policy = (
            CaptureScopePolicy.ALL_NOTE_TABLES.value
            if policy == CaptureScopePolicy.SELECTED_NOTE_TABLES.value
            else policy
        )
        return {
            "capture_scope_contract_version":contract_version,
            "capture_scope_policy":decision_scope_policy,
            "requested_capture_scope_policy":policy,
            "selected_blocks":selected,
            "excluded_blocks":excluded,
            "selected_segment_manifest":selected_manifest,
            "excluded_segment_manifest":excluded_manifest,
            "capture_scope_limited":bool(
                policy == CaptureScopePolicy.PRIMARY_ONLY.value
                or [
                    block for block in excluded
                    if _block_segment_classification(block) != "PEER_TABLE"
                ]
            ),
            "scope_boundary_decision":"",
            "scope_warning_codes":[],
            "scope_issue_codes":[],
        }
    requested_roles = set(role_filter)
    requested_ids = set(id_filter)
    selected: list[Any] = []
    excluded: list[Any] = []
    invalid_continuation_relation = False
    for block in blocks:
        classification = _block_segment_classification(block)
        segment_ids = _block_segment_ids(block)
        roots = [
            root
            for segment_id in segment_ids
            if (root := _segment_root(segment_id, segment_map)) is not None
        ]
        if classification == "CONTINUATION_SEGMENT" and (
            not segment_ids
            or len(roots) != len(segment_ids)
            or any(
                root_classification
                not in {"PRIMARY_TABLE", "SUPPLEMENTARY_TABLE"}
                for _, root_classification in roots
            )
        ):
            invalid_continuation_relation = True
        root_classifications = {classification for _, classification in roots}
        default_selected = classification == "PRIMARY_TABLE"
        if classification == "CONTINUATION_SEGMENT":
            default_selected = bool(
                policy in {
                    CaptureScopePolicy.PRIMARY_WITH_CONTINUATIONS.value,
                    CaptureScopePolicy.ALL_NOTE_TABLES.value,
                }
                and "PRIMARY_TABLE" in root_classifications
            ) or bool(
                policy == CaptureScopePolicy.ALL_NOTE_TABLES.value
                and "SUPPLEMENTARY_TABLE" in root_classifications
            )
        elif classification == "SUPPLEMENTARY_TABLE":
            default_selected = policy == CaptureScopePolicy.ALL_NOTE_TABLES.value
        elif classification in {"PEER_TABLE", "UNRESOLVED"}:
            default_selected = False
        if requested_roles and classification not in requested_roles:
            default_selected = False
        if requested_ids:
            block_id = str(getattr(block, "block_id", "") or "").strip()
            default_selected = default_selected and bool(
                block_id in requested_ids or requested_ids.intersection(segment_ids)
            )
        (selected if default_selected else excluded).append(block)
    if not selected or not any(
        _block_segment_classification(block) == "PRIMARY_TABLE"
        for block in selected
    ):
        raise ValueError("CAPTURE_SCOPE_PRIMARY_SEGMENT_REQUIRED")
    selected_segment_ids = {
        segment_id for block in selected for segment_id in _block_segment_ids(block)
    }
    excluded_segment_ids = {
        segment_id for block in excluded for segment_id in _block_segment_ids(block)
    }
    selected_manifest = [
        segment for segment in physical_segments
        if str(segment.get("segment_id") or "") in selected_segment_ids
    ]
    excluded_manifest = [
        segment for segment in physical_segments
        if str(segment.get("segment_id") or "") in excluded_segment_ids
    ]
    if not physical_segments:
        selected_manifest = [
            {
                "segment_id": segment_id,
                "segment_classification": _block_segment_classification(block),
            }
            for block in selected
            for segment_id in _block_segment_ids(block)
        ]
        excluded_manifest = [
            {
                "segment_id": segment_id,
                "segment_classification": _block_segment_classification(block),
            }
            for block in excluded
            for segment_id in _block_segment_ids(block)
        ]
    confirmed_excluded_continuation = any(
        str(
            segment.get("classification")
            or segment.get("segment_classification")
            or ""
        ).strip().upper() == "CONTINUATION_SEGMENT"
        and bool(str(segment.get("continuation_of_segment_id") or "").strip())
        and str(segment.get("relation_status") or "CONFIRMED").strip().upper()
        not in {"UNRESOLVED", "REJECTED", "CANDIDATE"}
        for segment in excluded_manifest
    )
    unresolved_continuation = any(
        str(segment.get("classification") or "").strip().upper() == "UNRESOLVED"
        and str(segment.get("candidate_relation") or "").strip().upper()
        == "CONTINUATION_SEGMENT"
        and "CONTINUATION_RELATION_UNRESOLVED" in {
            str(code or "").strip().upper()
            for code in (segment.get("reason_codes") or [])
        }
        for segment in physical_segments
    ) or invalid_continuation_relation
    warning_codes: list[str] = []
    if (
        policy == CaptureScopePolicy.PRIMARY_ONLY.value
        and confirmed_excluded_continuation
        and not unresolved_continuation
    ):
        warning_codes.append("CONTINUATION_EXCLUDED_BY_POLICY")
    issue_codes = (
        ["CONTINUATION_UNRESOLVED"] if unresolved_continuation else []
    )
    relevant_exclusions = [
        block for block in excluded
        if _block_segment_classification(block) != "PEER_TABLE"
    ]
    return {
        "capture_scope_contract_version":contract_version,
        "capture_scope_policy": policy,
        "requested_capture_scope_policy":policy,
        "selected_blocks": selected,
        "excluded_blocks": excluded,
        "selected_segment_manifest": selected_manifest,
        "excluded_segment_manifest": excluded_manifest,
        "capture_scope_limited": bool(
            policy == CaptureScopePolicy.PRIMARY_ONLY.value
            or relevant_exclusions
            or requested_roles
            or requested_ids
        ),
        "scope_boundary_decision": (
            "POLICY_TRUNCATION"
            if policy == CaptureScopePolicy.PRIMARY_ONLY.value
            and confirmed_excluded_continuation
            and not unresolved_continuation
            else ""
        ),
        "scope_warning_codes": warning_codes,
        "scope_issue_codes": issue_codes,
    }


class CaptureService:
    """Headless Capture use-cases shared by CLI/future FastAPI/Streamlit."""
    def __init__(self,repo:CaptureRepository,paths:dict[str,Path]):
        self.repo=repo;self.paths={k:Path(v) for k,v in paths.items()}
        self.orchestrator=None;self.runner=None
    def configure(self, *, orchestrator, runner=None):
        self.orchestrator=orchestrator;self.runner=runner
    def submit(self, request:CaptureRequest, *, asynchronous:bool=False):
        if self.orchestrator is None: raise RuntimeError("CAPTURE_ORCHESTRATOR_NOT_CONFIGURED")
        if asynchronous:
            if self.runner is None: raise RuntimeError("CAPTURE_RUNNER_NOT_CONFIGURED")
            return self.runner.enqueue_requests([request])
        return self.orchestrator.execute(request)
    def submit_batch(self, requests:list[CaptureRequest], *, batch_id:str|None=None,
                     max_workers:int=3, asynchronous:bool=True):
        if not asynchronous:
            return [self.submit(request) for request in requests]
        if self.runner is None: raise RuntimeError("CAPTURE_RUNNER_NOT_CONFIGURED")
        jobs=self.runner.enqueue_requests(requests,batch_id=batch_id)
        if jobs:self.runner.start(batch_id=jobs[0]["batch_id"],max_workers=max_workers)
        return jobs
    def execute_queued_request(self, request:CaptureRequest):
        if self.orchestrator is None: raise RuntimeError("CAPTURE_ORCHESTRATOR_NOT_CONFIGURED")
        return self.orchestrator.execute(request)
    def retry(self, job_id_or_request, **overrides):
        if isinstance(job_id_or_request,CaptureRequest):
            request=job_id_or_request
        else:
            if self.runner is None:raise RuntimeError("CAPTURE_RUNNER_NOT_CONFIGURED")
            job=self.runner.job_service.get(str(job_id_or_request))
            if not job:raise KeyError(job_id_or_request)
            request=CaptureRequest.from_dict((job.get("payload") or {})["capture_request"])
        payload=request.to_dict();payload.update(overrides)
        payload["request_id"]="CREQ_"+dt.datetime.now().strftime("%Y%m%d%H%M%S%f")
        payload["capture_mode"]=CaptureMode.FAILED_JOB_RETRY.value
        payload["retry_of_request_id"]=request.request_id
        return self.submit(CaptureRequest.from_dict(payload))
    def rerun(self, logical_asset_id:str, options:dict[str,Any]|None=None, *, requested_by:str="USER"):
        if self.orchestrator is None:raise RuntimeError("CAPTURE_ORCHESTRATOR_NOT_CONFIGURED")
        versions=self.orchestrator.repo.capture_versions(logical_asset_id)
        current=next((row for row in versions if row["is_current"]),None)
        if not current:raise KeyError(f"NO_CURRENT_CAPTURE:{logical_asset_id}")
        capture_id=str(current["capture_id"]);record=self.repo.get(capture_id)
        if not record:raise KeyError(capture_id)
        run_dir=Path(record["run_path"])
        evidence=json.loads((run_dir/"table_capture_result.json").read_text(encoding="utf-8"))
        metadata_path=run_dir/"capture_metadata.json"
        metadata=json.loads(metadata_path.read_text(encoding="utf-8")) if metadata_path.exists() else {}
        source=str(metadata.get("source_pdf_path") or (evidence.get("stats") or {}).get("source_pdf_path") or "")
        if not source:raise FileNotFoundError("SOURCE_PDF_PATH_REQUIRED")
        contract_version = int(
            metadata.get("capture_scope_contract_version")
            or LEGACY_CAPTURE_SCOPE_CONTRACT_VERSION
        )
        if contract_version == CAPTURE_SCOPE_CONTRACT_VERSION:
            snapshot = dict(metadata.get("capture_request_snapshot") or {})
            if snapshot:
                snapshot_metadata = dict(
                    snapshot.get("request_metadata") or {}
                )
                certified_target = dict(
                    snapshot_metadata.get("certified_target") or {}
                )
                if not certified_target:
                    raise PermissionError(
                        "V2_RERUN_CERTIFIED_TARGET_SNAPSHOT_REQUIRED"
                    )
                snapshot.update({
                    "request_id":"CREQ_" + dt.datetime.now().strftime(
                        "%Y%m%d%H%M%S%f"
                    ),
                    "capture_mode":CaptureMode.CERTIFIED_TARGET.value,
                    "requested_by":requested_by,
                    "requested_at":dt.datetime.now().astimezone().isoformat(
                        timespec="seconds"
                    ),
                    "retry_of_request_id":capture_id,
                    "request_metadata":{
                        **snapshot_metadata,
                        **dict(options or {}),
                        "certified_target":certified_target,
                        "rerun_of_capture_id":capture_id,
                    },
                })
                request = CaptureRequest.from_dict(snapshot)
            else:
                certified_target = dict(
                    metadata.get("certified_target") or {}
                )
                if not certified_target:
                    raise PermissionError(
                        "V2_RERUN_CERTIFIED_TARGET_SNAPSHOT_REQUIRED"
                    )
                request = CaptureRequest.new(
                    capture_mode=CaptureMode.CERTIFIED_TARGET,
                    source_pdf_path=source,
                    source_pdf_id=str(metadata.get("pdf_id") or ""),
                    member_table_id=str(
                        metadata.get("member_table_id")
                        or metadata.get("member_table")
                        or record.get("table_query")
                        or ""
                    ),
                    table_family_id=str(
                        metadata.get("table_family_id")
                        or metadata.get("table_family")
                        or ""
                    ),
                    research_definition_id=str(
                        metadata.get("research_definition_id") or ""
                    ),
                    definition_version=str(
                        metadata.get("definition_version") or ""
                    ),
                    certified_target_id=str(
                        certified_target.get("target_id") or ""
                    ),
                    certified_note_target_id=str(
                        certified_target.get("certified_note_target_id") or ""
                    ),
                    requested_by=requested_by,
                    retry_of_request_id=capture_id,
                    capture_scope_contract_version=contract_version,
                    capture_scope_policy=str(
                        metadata.get("requested_capture_scope_policy")
                        or metadata.get("capture_scope_policy")
                        or CaptureScopePolicy.PRIMARY_ONLY.value
                    ),
                    selected_logical_table_ids=(
                        metadata.get("selected_logical_table_ids") or []
                    ),
                    selected_block_roles=[],
                    selected_block_ids=[],
                    request_metadata={
                        **dict(options or {}),
                        "table_query":str(
                            certified_target.get("capture_query_title")
                            or certified_target.get("target_heading")
                            or evidence.get("table_query")
                            or record.get("table_query")
                            or ""
                        ),
                        "note_number":certified_target.get("note_reference"),
                        "note_reference":certified_target.get("note_reference"),
                        "guided_target_required":True,
                        "certified_target":certified_target,
                        "member_table_role":metadata.get("member_table_role"),
                        "source_table_title":metadata.get("source_table_title"),
                        "statement_scope":metadata.get("statement_scope"),
                        "rerun_of_capture_id":capture_id,
                    },
                )
        else:
            start=int(evidence.get("start_page") or 1)
            request=CaptureRequest.new(
                capture_mode=CaptureMode.MANUAL_ROI,source_pdf_path=source,
                member_table_id=str(metadata.get("member_table") or record.get("table_query") or ""),
                table_family_id=str(metadata.get("table_family") or ""),
                manual_page_range=(start,start),requested_by=requested_by,
                retry_of_request_id=capture_id,
                capture_scope_contract_version=contract_version,
                capture_scope_policy=str(
                    metadata.get("requested_capture_scope_policy")
                    or metadata.get("capture_scope_policy")
                    or CaptureScopePolicy.PRIMARY_ONLY.value
                ),
                selected_logical_table_ids=[],
                selected_block_roles=metadata.get("selected_block_roles") or [],
                selected_block_ids=metadata.get("selected_block_ids") or [],
                request_metadata={
                    **dict(options or {}),"table_query":evidence.get("table_query") or record.get("table_query"),
                    "rerun_of_capture_id":capture_id,"member_table_role":metadata.get("member_table_role"),
                },
            )
        return self.submit(request)
    def list(self,**filters)->list[dict[str,Any]]:return self.repo.list(**filters)
    def count(self,**filters)->int:return self.repo.count(**filters)
    def get(self,capture_id:str):return self.repo.get(capture_id)
    def register_run(self,run_dir:Path):
        sync=sync_capture_run(run_dir)
        if sync.get("status")!="OK":
            raise RuntimeError(f"CAPTURE_REGISTRY_SYNC_FAILED: {sync}")
        registered=self.repo.get(Path(run_dir).name)
        if registered is None:
            raise RuntimeError(f"CAPTURE_REGISTRY_RECORD_MISSING: {Path(run_dir).name}")
        return registered
    def filter_options(self)->dict[str,list[str]]:
        return {k:self.repo.distinct_values(k) for k in ['lifecycle_status','table_query','company','document_year','producer_version','batch_id','header_parser']}

    def create(
        self, *, pdf_path:Path, table_query:str, note_number:Optional[str]=None,
        start_page_override:Optional[int]=None, max_pages:int=8,
        header_parser_mode:str='AUTO', batch_id:Optional[str]=None,
        output_dir:Optional[Path]=None, progress_callback=None,
        guided_target_required:bool=False, certified_note_target:dict[str,Any]|None=None,
        table_family:str|None=None, member_table:str|None=None,
        member_table_role:str|None=None, source_table_title:str|None=None,
        note_reference:str|None=None, member_table_order:int|None=None,
        capture_scope_contract_version:int=CAPTURE_SCOPE_CONTRACT_VERSION,
        capture_scope_policy:str|CaptureScopePolicy=CaptureScopePolicy.PRIMARY_ONLY,
        selected_logical_table_ids:list[str]|tuple[str,...]|None=None,
        selected_block_roles:list[str]|tuple[str,...]|None=None,
        selected_block_ids:list[str]|tuple[str,...]|None=None,
        classification_axis_hint: str | None = None,
    )->dict[str,Any]:
        """Compatibility adapter: all callers now enter the unified orchestrator."""
        certified=dict(certified_note_target or {})
        if start_page_override and not certified:
            certified={
                "confirmed_note_pdf_page_index":int(start_page_override),
                "target_heading":str(table_query),"capture_query_title":str(table_query),
                "note_reference":str(note_reference or note_number or ""),
                "status":"MANUAL_CERTIFIED","confidence":1.0,
            }
        mode=CaptureMode.CERTIFIED_TARGET if certified else CaptureMode.DIRECT_DISCLOSURE
        request=CaptureRequest.new(
            capture_mode=mode,source_pdf_path=str(Path(pdf_path).resolve()),
            member_table_id=str(member_table or table_query),
            table_family_id=str(table_family or ""),
            manual_page_range=None,
            capture_scope_contract_version=capture_scope_contract_version,
            capture_scope_policy=capture_scope_policy,
            selected_logical_table_ids=selected_logical_table_ids,
            selected_block_roles=selected_block_roles,
            selected_block_ids=selected_block_ids,
            classification_axis_hint=str(
                classification_axis_hint or certified.get("classification_axis") or ""
            ),
            request_metadata={
                "table_query":str(table_query),"note_number":note_number,
                "max_pages":int(max_pages),"header_parser_mode":header_parser_mode,
                "batch_id":batch_id,"output_dir":str(output_dir) if output_dir else "",
                "guided_target_required":bool(guided_target_required),
                "certified_target":certified,"member_table_role":member_table_role,
                "source_table_title":source_table_title,"note_reference":note_reference,
                "member_table_order":member_table_order,
            },
        )
        return self.submit(request)

    def _execute_resolved_target(
        self, request:CaptureRequest, target:ResolvedCaptureTarget,
    )->dict[str,Any]:
        options=dict(request.capture_options);options.update(request.request_metadata)
        direct_full_book=target.target_type=="DIRECT_DISCLOSURE" and bool(target.evidence.get("full_book_query"))
        configured_max_pages=int(options.get("max_pages",8))
        certified_target_payload=dict(target.evidence or {})
        return self._create_legacy(
            pdf_path=Path(request.source_pdf_path),
            table_query=str(target.title or request.member_table_id or options.get("table_query")),
            note_number=target.note_reference or options.get("note_number"),
            start_page_override=None if direct_full_book else target.start_page,
            max_pages=configured_max_pages,
            header_parser_mode=str(options.get("header_parser_mode") or "AUTO"),
            batch_id=options.get("batch_id"),output_dir=Path(options["output_dir"]) if options.get("output_dir") else None,
            guided_target_required=not direct_full_book,
            certified_note_target={
                **certified_target_payload,
                "status":"CERTIFIED_NOTE_TARGET",
                "confirmed_note_pdf_page_index":target.start_page,
                "target_heading":target.title,
            },
            table_family=request.table_family_id,member_table=request.member_table_id,
            member_table_role=options.get("member_table_role"),
            source_table_title=options.get("source_table_title"),
            note_reference=target.note_reference or options.get("note_reference"),
            member_table_order=options.get("member_table_order"),
            capture_scope_contract_version=(
                request.capture_scope_contract_version
            ),
            capture_scope_policy=request.capture_scope_policy,
            selected_logical_table_ids=request.selected_logical_table_ids,
            selected_block_roles=request.selected_block_roles,
            selected_block_ids=request.selected_block_ids,
            classification_axis_hint=request.classification_axis_hint,
            capture_request_id=request.request_id,
        )

    def _create_legacy(
        self,
        *,
        pdf_path:Path,
        table_query:str,
        note_number:Optional[str]=None,
        start_page_override:Optional[int]=None,
        max_pages:int=8,
        header_parser_mode:str='AUTO',
        batch_id:Optional[str]=None,
        output_dir:Optional[Path]=None,
        progress_callback=None, guided_target_required: bool=False, certified_note_target: dict[str,Any]|None=None,
        table_family: str | None = None, member_table: str | None = None,
        member_table_role: str | None = None, source_table_title: str | None = None,
        note_reference: str | None = None, member_table_order: int | None = None,
        capture_scope_contract_version: int = LEGACY_CAPTURE_SCOPE_CONTRACT_VERSION,
        capture_scope_policy: str | CaptureScopePolicy = CaptureScopePolicy.PRIMARY_ONLY,
        selected_logical_table_ids: list[str] | tuple[str, ...] | None = None,
        selected_block_roles: list[str] | tuple[str, ...] | None = None,
        selected_block_ids: list[str] | tuple[str, ...] | None = None,
        classification_axis_hint: str | None = None,
        capture_request_id: str = "",
    )->dict[str,Any]:
        """Create one audited table Capture without importing any UI framework."""
        from table_capture import capture_named_table,write_capture_artifacts
        if guided_target_required:
            target=dict(certified_note_target or {})
            if target.get("status")!="CERTIFIED_NOTE_TARGET" or not target.get("confirmed_note_pdf_page_index"):
                raise PermissionError("NO_UNCERTIFIED_FULLBOOK_FALLBACK")
            if int(start_page_override or 0)!=int(target["confirmed_note_pdf_page_index"]):
                raise PermissionError("CERTIFIED_TARGET_PAGE_MISMATCH")
        from capture_library import initialize_capture_library_run
        try:
            from batch_pipeline import display_pdf_name
        except Exception:
            display_pdf_name=lambda x:str(x)
        pdf_path=Path(pdf_path)
        # Register source metadata before Capture insert so the SQLite FK can be
        # resolved even when this service is used headlessly outside Streamlit.
        try:
            from batch_pipeline import display_pdf_name, infer_company_year
            display = display_pdf_name(pdf_path.name)
            company, year = infer_company_year(Path(display), "")
            self.repo.registry.upsert_pdf({
                "pdf_id": "PDF::" + str(pdf_path.resolve()).lower(),
                "filename": pdf_path.name,
                "display_name": display,
                "company": company,
                "document_year": year,
                "size_bytes": pdf_path.stat().st_size,
                "path": str(pdf_path.resolve()),
                "modified_at": dt.datetime.fromtimestamp(pdf_path.stat().st_mtime).astimezone().isoformat(timespec="seconds"),
            })
        except Exception:
            pass
        if output_dir is None:
            stamp=dt.datetime.now().strftime('%Y%m%dT%H%M%S_%f')
            source=re.sub(r'[\\/:*?"<>|]+','_',Path(display_pdf_name(pdf_path.name)).stem)[:65]
            title=re.sub(r'[\\/:*?"<>|]+','_',str(table_query).strip())[:55]
            output_dir=self.paths['table_captures']/f'{source}__{title}__{stamp}'
        output_dir=Path(output_dir)
        direct_portfolio_target = bool(
            (certified_note_target or {}).get("direct_portfolio_table")
        )
        certified_direct_unit = str(
            (certified_note_target or {}).get("unit") or ""
        ).strip()
        if str(member_table_role or "").upper() == "STATEMENT_ANCHOR":
            # Statement anchors have their header above the display_name.  A
            # note-table ROI starts below the title and would otherwise lose
            # its scope/year columns.
            from statement_anchor_capture import capture_statement_anchor
            result = capture_statement_anchor(pdf_path, str(table_query).strip(), int(start_page_override or 1), note_number=note_number)
        else:
            result=capture_named_table(
                pdf_path=pdf_path,table_query=str(table_query).strip(),note_number=note_number,
                start_page_override=start_page_override,max_pages=int(max_pages),progress_callback=progress_callback,
                header_parser_mode=header_parser_mode,
                allow_legacy_fallback=not guided_target_required,
                strict_target_identity=guided_target_required,
                certified_target_heading=(
                    str((certified_note_target or {}).get("target_heading") or table_query)
                    if guided_target_required else None
                ),
                certified_segments=(
                    list((certified_note_target or {}).get("certified_segments") or [])
                    if guided_target_required else None
                ),
                certified_amount_unit=(
                    certified_direct_unit
                    if direct_portfolio_target else None
                ),
                physical_table_id=(
                    str((certified_note_target or {}).get("physical_asset_id") or "")
                    if guided_target_required else None
                ),
            )
        if direct_portfolio_target and not result.unit and certified_direct_unit:
            result.unit = certified_direct_unit
            result.stats = {
                **dict(result.stats or {}),
                "unit_source": "CERTIFIED_DIRECT_PORTFOLIO_NATIVE_PAGE",
            }
            result.warnings = [
                warning
                for warning in list(result.warnings or [])
                if "未在目标附注首页识别到明确单位" not in str(warning)
            ]
            result.warnings.append(
                "DIRECT_PORTFOLIO_CERTIFIED_UNIT：单位来自同页原生文本定位证据。"
            )
        if direct_portfolio_target:
            from compound_note_engine import (
                certify_direct_row_footnotes,
                restore_certified_direct_group_rows,
            )

            restore_certified_direct_group_rows(
                result,
                pdf_path,
                list((certified_note_target or {}).get("certified_segments") or []),
            )
            certify_direct_row_footnotes(
                result,
                pdf_path,
                list((certified_note_target or {}).get("certified_segments") or []),
            )
        # v6.9 keeps the existing capture primitive as the only extraction
        # entrypoint, then turns a compound note into independently auditable
        # child blocks.  A single-table note remains exactly one child.
        from compound_note_engine import (
            coalesce_certified_physical_table_blocks,
            materialize_block_result,
            segment_table_blocks,
            serialise_block,
        )
        container, blocks = segment_table_blocks(
            result,
            classification_axis_hint=classification_axis_hint,
        )
        if direct_portfolio_target:
            blocks = coalesce_certified_physical_table_blocks(
                result,
                container,
                list(blocks),
                physical_asset_id=str(
                    (certified_note_target or {}).get("physical_asset_id")
                    or ""
                ),
                title=str(
                    (certified_note_target or {}).get("target_heading")
                    or table_query
                ),
                classification_axis=str(
                    (certified_note_target or {}).get("classification_axis")
                    or classification_axis_hint
                    or "UNRESOLVED"
                ),
                preserve_logical_axes=(
                    str((certified_note_target or {}).get("disclosure_topology") or "")
                    == "DIRECT_COMPOUND_TABLE"
                    and len(
                        (certified_note_target or {}).get("logical_block_ids") or []
                    ) > 1
                ),
            )
        all_blocks = list(blocks)
        certified_scope_governance = _validate_certified_scope_governance(
            result,
            certified_note_target=certified_note_target,
            capture_scope_contract_version=capture_scope_contract_version,
            capture_scope_policy=capture_scope_policy,
            selected_logical_table_ids=selected_logical_table_ids,
            enabled=bool(
                guided_target_required
                and str(member_table_role or "").upper() != "STATEMENT_ANCHOR"
            ),
            registry=getattr(self.repo,"registry",None),
        )
        if (
            int(capture_scope_contract_version)
            == CAPTURE_SCOPE_CONTRACT_VERSION
            and certified_scope_governance["issue_codes"]
        ):
            raise PermissionError(
                "CERTIFIED_SCOPE_GOVERNANCE_BLOCKED:"
                + ",".join(certified_scope_governance["issue_codes"])
            )
        scope_selection = _select_blocks_for_scope(
            result,
            all_blocks,
            capture_scope_contract_version=capture_scope_contract_version,
            capture_scope_policy=capture_scope_policy,
            selected_logical_table_ids=selected_logical_table_ids,
            selected_block_roles=selected_block_roles,
            selected_block_ids=selected_block_ids,
            certified_manifest_validation=(
                certified_scope_governance["manifest_validation"]
            ),
        )
        scope_selection["scope_issue_codes"] = list(dict.fromkeys([
            *list(scope_selection["scope_issue_codes"]),
            *list(certified_scope_governance["issue_codes"]),
        ]))
        blocks = list(scope_selection["selected_blocks"])
        if direct_portfolio_target:
            blocks = sorted(blocks, key=_direct_bundle_order)
        result.stats = {
            **dict(result.stats or {}),
            "capture_scope_contract_version":scope_selection[
                "capture_scope_contract_version"
            ],
            "capture_scope_policy":scope_selection["capture_scope_policy"],
            "requested_capture_scope_policy":scope_selection[
                "requested_capture_scope_policy"
            ],
            "selected_logical_table_ids":list(
                selected_logical_table_ids or []
            ),
            "capture_scope_limited":scope_selection["capture_scope_limited"],
            "scope_boundary_decision":scope_selection["scope_boundary_decision"],
            "selected_segment_manifest":scope_selection["selected_segment_manifest"],
            "excluded_segment_manifest":scope_selection["excluded_segment_manifest"],
            "scope_warning_codes":scope_selection["scope_warning_codes"],
            "scope_issue_codes":scope_selection["scope_issue_codes"],
            "certified_segment_manifest_validation":certified_scope_governance["manifest_validation"],
            "certified_note_table_inventory_validation":certified_scope_governance["inventory_validation"],
        }
        result.warnings = list(dict.fromkeys(
            list(result.warnings or []) + list(scope_selection["scope_warning_codes"])
        ))
        certified_target_payload = dict(certified_note_target or {})
        certified_logical_table_id = str(
            certified_target_payload.get("logical_table_id")
            or certified_target_payload.get("logical_table_candidate_id")
            or ""
        ).strip()
        bundle_identity = _capture_bundle_identity(
            container_id=container.container_id,
            certified_logical_table_id=(
                certified_logical_table_id
                or f"LEGACY::{member_table or table_query}"
            ),
            capture_request_id=str(capture_request_id or ""),
            root_capture_id=output_dir.name,
            scope_selection={
                **scope_selection,
                "selected_logical_table_ids":list(
                    selected_logical_table_ids or []
                ),
                "selected_block_roles":list(selected_block_roles or []),
                "selected_block_ids":list(selected_block_ids or []),
            },
        )
        bundle_id = bundle_identity["bundle_id"]
        child_runs: list[dict[str, Any]] = []
        primary_output_dir = output_dir
        for bundle_child_order,block in enumerate(blocks):
            child_result = materialize_block_result(result, block)
            suffix = re.sub(r'[^0-9A-Za-z_\-]+', '_', block.title)[:35] or f"block_{block.block_order + 1}"
            child_dir = primary_output_dir if bundle_child_order == 0 else primary_output_dir.with_name(
                f"{primary_output_dir.name}__b{bundle_child_order + 1}_{suffix}"
            )
            artifacts = write_capture_artifacts(child_dir, child_result)
            child_runs.append({
                "block":block,"run_dir":child_dir,"result":child_result,
                "artifacts":artifacts,"bundle_child_order":bundle_child_order,
            })
        _validate_bundle_child_orders([
            int(child["bundle_child_order"]) for child in child_runs
        ])
        # The first block is retained as the compatibility capture result.
        output_dir = child_runs[0]["run_dir"]
        result = child_runs[0]["result"]
        artifacts = child_runs[0]["artifacts"]
        primary_member_table = _certified_member_for_axis(
            certified_note_target,
            str(child_runs[0]["block"].classification_axis or ""),
            str(member_table or table_query),
        )
        metadata=initialize_capture_library_run(
            output_dir,source_pdf_display=display_pdf_name(pdf_path.name),table_query=str(table_query).strip(),batch_id=batch_id,
        )
        # Preserve the Table Family identity at the Capture boundary.  Machine
        # table evidence remains immutable; this is source provenance required
        # by the downstream Family Merge observation contract.
        metadata_path = output_dir / "capture_metadata.json"
        persisted = json.loads(metadata_path.read_text(encoding="utf-8")) if metadata_path.exists() else dict(metadata)
        persisted.update({
            "table_family": str(table_family or persisted.get("table_family") or "").strip(),
            "member_table": str(primary_member_table or persisted.get("member_table") or table_query).strip(),
            "member_table_id": str(primary_member_table or member_table or table_query).strip(),
            "member_table_role": str(member_table_role or persisted.get("member_table_role") or "COMPONENT").strip(),
            "source_table_title": str(source_table_title or persisted.get("source_table_title") or member_table or table_query).strip(),
            "note_reference": str(note_reference or persisted.get("note_reference") or note_number or "").strip(),
            "member_table_order": member_table_order if member_table_order is not None else persisted.get("member_table_order"),
            "source_pdf_path": str(pdf_path.resolve()),
            "capture_scope_contract_version":scope_selection[
                "capture_scope_contract_version"
            ],
            "capture_scope_policy":scope_selection["capture_scope_policy"],
            "requested_capture_scope_policy":scope_selection[
                "requested_capture_scope_policy"
            ],
            "selected_logical_table_ids":list(
                selected_logical_table_ids or []
            ),
            "selected_block_roles":list(selected_block_roles or []),
            "selected_block_ids":list(selected_block_ids or []),
            "certified_logical_table_id":certified_logical_table_id,
            "capture_request_id":str(capture_request_id or ""),
            "bundle_target_key":bundle_identity["bundle_target_key"],
            "bundle_scope_signature":bundle_identity[
                "bundle_scope_signature"
            ],
            "capture_scope_limited":scope_selection["capture_scope_limited"],
            "scope_boundary_decision":scope_selection["scope_boundary_decision"],
            "selected_segment_manifest":scope_selection["selected_segment_manifest"],
            "excluded_segment_manifest":scope_selection["excluded_segment_manifest"],
            "scope_warning_codes":scope_selection["scope_warning_codes"],
            "scope_issue_codes":scope_selection["scope_issue_codes"],
            "certified_segment_manifest_validation":certified_scope_governance["manifest_validation"],
            "certified_note_table_inventory_validation":certified_scope_governance["inventory_validation"],
        })
        metadata_path.write_text(json.dumps(persisted, ensure_ascii=False, indent=2), encoding="utf-8")
        metadata = persisted
        sync=sync_capture_run(output_dir)
        if sync.get("status")!="OK":
            raise RuntimeError(f"CAPTURE_REGISTRY_SYNC_FAILED: {sync}")
        if self.repo.get(output_dir.name) is None:
            raise RuntimeError(f"CAPTURE_REGISTRY_RECORD_MISSING: {output_dir.name}")
        # Persist the immutable container/block graph in one transaction, then
        # synchronise derived capture runs *after that transaction commits*.
        # `sync_capture_run` opens its own metadata.db writer.  Calling it from
        # inside this transaction self-locks SQLite and previously left a
        # physical child capture without a registry record.
        child_payloads=[]
        derived_child_dirs=[]
        now=dt.datetime.now().astimezone().isoformat(timespec="seconds")
        for child in child_runs:
            block=child["block"]; child_dir=child["run_dir"]
            explicit_block_member = _explicit_certified_member_for_axis(
                certified_note_target,
                str(block.classification_axis or ""),
            )
            block_member_table = _certified_member_for_axis(
                certified_note_target,
                str(block.classification_axis or ""),
                str(member_table or block.title),
            )
            if child_dir != output_dir:
                child_meta=initialize_capture_library_run(
                    child_dir,source_pdf_display=display_pdf_name(pdf_path.name),
                    table_query=block.title,batch_id=batch_id,
                )
                child_meta_path=child_dir/'capture_metadata.json'
                child_meta.update({"table_family":str(table_family or ""),"member_table":block_member_table,
                    "member_table_id":(
                        explicit_block_member
                        or f"{member_table or 'MEMBER'}::{block.block_id}"
                    ),
                    "member_table_role":"NOTE_DETAIL","member_subtable_id":block.block_id,
                    "capture_bundle_id":bundle_id,"source_pdf_path":str(pdf_path.resolve()),
                    "container_id":container.container_id,"table_block_id":block.block_id,
                    "block_order":block.block_order,"classification_axis":block.classification_axis,
                    "block_role":block.role,"block_terminal_type":block.block_terminal_type,
                    "certified_logical_table_id":certified_logical_table_id,
                    "capture_request_id":str(capture_request_id or ""),
                    "bundle_target_key":bundle_identity["bundle_target_key"],
                    "bundle_scope_signature":bundle_identity[
                        "bundle_scope_signature"
                    ],
                    "capture_scope_contract_version":persisted["capture_scope_contract_version"],
                    "capture_scope_policy":persisted["capture_scope_policy"],
                    "requested_capture_scope_policy":persisted[
                        "requested_capture_scope_policy"
                    ],
                    "selected_logical_table_ids":persisted["selected_logical_table_ids"],
                    "selected_block_roles":persisted["selected_block_roles"],
                    "selected_block_ids":persisted["selected_block_ids"],
                    "capture_scope_limited":persisted["capture_scope_limited"],
                    "scope_boundary_decision":persisted["scope_boundary_decision"],
                    "selected_segment_manifest":persisted["selected_segment_manifest"],
                    "excluded_segment_manifest":persisted["excluded_segment_manifest"],
                    "scope_warning_codes":persisted["scope_warning_codes"],
                    "scope_issue_codes":persisted["scope_issue_codes"],
                    "certified_segment_manifest_validation":persisted["certified_segment_manifest_validation"],
                    "certified_note_table_inventory_validation":persisted["certified_note_table_inventory_validation"]})
                child_meta_path.write_text(json.dumps(child_meta,ensure_ascii=False,indent=2),encoding='utf-8')
                derived_child_dirs.append(child_dir)
            child_payloads.append({
                "capture_id":child_dir.name,"run_path":str(child_dir),
                "block":serialise_block(block),
                "child_order":int(child["bundle_child_order"]),
                "certified_member_table_id":explicit_block_member,
                "member_table":block_member_table,
            })
        child_by_block_id = {
            str(child["block"].block_id):child for child in child_runs
        }
        excluded_block_manifest=[]
        for block in all_blocks:
            if str(block.block_id) in child_by_block_id:
                continue
            classification=_block_segment_classification(block)
            exclusion_reason=(
                "PEER_TABLE_BOUNDARY"
                if classification=="PEER_TABLE"
                else "SEGMENT_RELATION_UNRESOLVED"
                if classification=="UNRESOLVED"
                else "EXCLUDED_BY_CAPTURE_SCOPE_POLICY"
            )
            excluded_block_manifest.append({
                **serialise_block(block),
                "exclusion_reason":exclusion_reason,
            })
        bundle_payload = {
            "engine":"v6.11",
            "bundle_target_key":bundle_identity["bundle_target_key"],
            "bundle_scope_signature":bundle_identity[
                "bundle_scope_signature"
            ],
            "certified_logical_table_id":certified_logical_table_id,
            "root_capture_id":output_dir.name,
            "block_count":len(all_blocks),
            "selected_block_count":len(blocks),
            "capture_scope_contract_version":scope_selection[
                "capture_scope_contract_version"
            ],
            "capture_scope_policy":scope_selection["capture_scope_policy"],
            "requested_capture_scope_policy":scope_selection[
                "requested_capture_scope_policy"
            ],
            "selected_logical_table_ids":list(
                selected_logical_table_ids or []
            ),
            "selected_block_roles":list(selected_block_roles or []),
            "selected_block_ids":list(selected_block_ids or []),
            "capture_scope_limited":scope_selection["capture_scope_limited"],
            "scope_boundary_decision":scope_selection[
                "scope_boundary_decision"
            ],
            "scope_warning_codes":scope_selection["scope_warning_codes"],
            "scope_issue_codes":scope_selection["scope_issue_codes"],
            "certified_segment_manifest_validation":(
                certified_scope_governance["manifest_validation"]
            ),
            "certified_note_table_inventory_validation":(
                certified_scope_governance["inventory_validation"]
            ),
            "selected_segment_manifest":scope_selection[
                "selected_segment_manifest"
            ],
            "excluded_segment_manifest":scope_selection[
                "excluded_segment_manifest"
            ],
            "excluded_block_count":len(excluded_block_manifest),
            "excluded_block_manifest":excluded_block_manifest,
        }
        try:
            with self.repo.registry.connect() as conn:
                conn.execute("""INSERT OR REPLACE INTO note_containers
                    (container_id,source_pdf_id,source_pdf_sha256,source_pdf_path,note_reference,note_title,start_pdf_page,end_pdf_page,context_json,layout_graph_json,created_at)
                    VALUES(?,?,?,?,?,?,?,?,?,?,?)""", (
                    container.container_id, "PDF::" + str(pdf_path.resolve()).lower(), container.source_pdf_sha256,
                    str(pdf_path.resolve()), container.note_reference, container.note_title, container.start_pdf_page,
                    container.end_pdf_page, json.dumps(dict(result.document_context or {}),ensure_ascii=False),
                    json.dumps(container.layout_evidence,ensure_ascii=False), now))
                existing_bundle = conn.execute(
                    "SELECT request_id,payload_json FROM capture_bundles "
                    "WHERE bundle_id=?",(bundle_id,),
                ).fetchone()
                if existing_bundle:
                    try:
                        existing_payload = json.loads(
                            existing_bundle["payload_json"] or "{}"
                        )
                    except (TypeError,json.JSONDecodeError):
                        existing_payload = {}
                    if (
                        str(existing_bundle["request_id"] or "")
                        != str(capture_request_id or "")
                        or str(existing_payload.get("bundle_target_key") or "")
                        != bundle_identity["bundle_target_key"]
                        or str(existing_payload.get("root_capture_id") or "")
                        != output_dir.name
                    ):
                        raise ValueError("CAPTURE_BUNDLE_IDENTITY_COLLISION")
                conn.execute("""INSERT INTO capture_bundles
                    (bundle_id,request_id,container_id,table_family_id,member_table_id,status,payload_json,created_at,updated_at)
                    VALUES(?,?,?,?,?,?,?,?,?)
                    ON CONFLICT(bundle_id) DO UPDATE SET
                        request_id=excluded.request_id,
                        container_id=excluded.container_id,
                        table_family_id=excluded.table_family_id,
                        member_table_id=excluded.member_table_id,
                        status=excluded.status,
                        payload_json=excluded.payload_json,
                        updated_at=excluded.updated_at""", (
                    bundle_id,str(capture_request_id or "") or None,
                    container.container_id,table_family,member_table,"COMPLETED",
                    json.dumps(bundle_payload,ensure_ascii=False),now,now,
                ))
                bundle_children=[]
                for block in all_blocks:
                    child=child_by_block_id.get(str(block.block_id))
                    classification=_block_segment_classification(block)
                    block_status=(
                        "CAPTURED"
                        if child
                        else "PEER_BOUNDARY_NOT_MATERIALIZED"
                        if classification=="PEER_TABLE"
                        else "UNRESOLVED_NOT_MATERIALIZED"
                        if classification=="UNRESOLVED"
                        else "EXCLUDED_BY_POLICY"
                    )
                    block_evidence={
                        **dict(block.evidence or {}),
                        "scope_materialization":{
                            "selected":bool(child),
                            "status":block_status,
                            "capture_scope_contract_version":scope_selection[
                                "capture_scope_contract_version"
                            ],
                            "capture_scope_policy":scope_selection["capture_scope_policy"],
                        },
                    }
                    conn.execute("""INSERT OR REPLACE INTO table_blocks
                        (block_id,container_id,block_order,block_title,block_role,classification_axis,block_terminal_type,start_pdf_page,end_pdf_page,bbox_json,header_topology_json,semantic_graph_json,reconciliation_json,quality_status,status,evidence_json,created_at)
                        VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""", (
                        block.block_id,container.container_id,block.block_order,block.title,block.role,
                        block.classification_axis,block.block_terminal_type,block.start_pdf_page,block.end_pdf_page,
                        json.dumps(block.bbox,ensure_ascii=False),json.dumps(block.header_topology,ensure_ascii=False),
                        json.dumps(block.semantic_graph,ensure_ascii=False),json.dumps(block.reconciliation,ensure_ascii=False),
                        block.quality_status,block_status,
                        json.dumps(block_evidence,ensure_ascii=False),now))
                    if child:
                        child_dir=child["run_dir"]
                        bundle_children.append({
                            "block_id":block.block_id,
                            "capture_id":child_dir.name,
                            "logical_asset_id":None,
                            "child_order":int(child["bundle_child_order"]),
                            "status":"CAPTURED",
                            "payload_json":json.dumps(
                                serialise_block(block),ensure_ascii=False,
                            ),
                        })
                _replace_capture_bundle_children(
                    conn,
                    bundle_id=bundle_id,
                    children=bundle_children,
                    created_at=now,
                )
        except Exception as exc:
            metadata["bundle_registration_status"]="BUNDLE_GRAPH_PERSIST_FAILED"
            metadata["bundle_registration_error"]=f"{type(exc).__name__}:{exc}"
            (output_dir/'capture_metadata.json').write_text(json.dumps(metadata,ensure_ascii=False,indent=2),encoding='utf-8')
            raise RuntimeError(f"CAPTURE_BUNDLE_GRAPH_PERSIST_FAILED:{type(exc).__name__}:{exc}") from exc
        child_sync_failures=[]
        for child_dir in derived_child_dirs:
            child_sync=sync_capture_run(child_dir)
            if child_sync.get("status")!="OK":
                child_sync_failures.append({"capture_id":child_dir.name,"sync":child_sync})
        if child_sync_failures:
            metadata["bundle_registration_status"]="CHILD_CAPTURE_REGISTRY_SYNC_FAILED"
            metadata["child_capture_registry_sync_failures"]=child_sync_failures
            (output_dir/'capture_metadata.json').write_text(json.dumps(metadata,ensure_ascii=False,indent=2),encoding='utf-8')
            raise RuntimeError(f"CAPTURE_CHILD_REGISTRY_SYNC_FAILED:{child_sync_failures}")
        metadata["bundle_registration_status"]="COMMITTED_AND_CHILDREN_SYNCED"
        primary_block=blocks[0]
        metadata.update({"capture_bundle_id":bundle_id,"note_container_id":container.container_id,
                         "container_id":container.container_id,"v69_block_count":len(blocks),
                         "discovered_block_count":len(all_blocks),
                         "excluded_block_count":len(all_blocks)-len(blocks),
                         "excluded_block_manifest":excluded_block_manifest,
                         "member_subtable_id":primary_block.block_id,
                         "table_block_id":primary_block.block_id,
                         "block_order":primary_block.block_order,
                         "classification_axis":primary_block.classification_axis,
                         "block_role":primary_block.role,
                         "block_terminal_type":primary_block.block_terminal_type})
        (output_dir/'capture_metadata.json').write_text(json.dumps(metadata,ensure_ascii=False,indent=2),encoding='utf-8')
        return {'capture_id':output_dir.name,'run_path':str(output_dir),'artifacts':artifacts,'metadata':metadata,
                'result':result.to_dict() if hasattr(result,'to_dict') else result,
                'capture_bundle_id':bundle_id,'note_container_id':container.container_id,'child_captures':child_payloads,
                'selected_segment_manifest':scope_selection["selected_segment_manifest"],
                'excluded_segment_manifest':scope_selection["excluded_segment_manifest"],
                'certified_segment_manifest_validation':certified_scope_governance["manifest_validation"],
                'certified_note_table_inventory_validation':certified_scope_governance["inventory_validation"],
                'excluded_block_manifest':excluded_block_manifest}
