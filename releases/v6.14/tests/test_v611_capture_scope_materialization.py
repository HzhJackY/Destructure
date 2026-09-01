from __future__ import annotations

import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from services.capture_service import (
    CaptureService,
    _capture_bundle_identity,
    _replace_capture_bundle_children,
    _select_blocks_for_scope,
    _validate_bundle_child_orders,
    _validate_certified_scope_governance,
    _normalise_certified_segments_for_runtime,
)
from capture_models import CaptureMode,CaptureRequest
from capture_library import derive_capture_scope_state
from repositories.asset_governance_repository import AssetGovernanceRepository


def _segment(
    segment_id: str,
    classification: str,
    *,
    page: int = 1,
    periods: tuple[str, ...] = ("2024",),
    ratios: tuple[float, ...] = (0.7, 0.86),
    continuation_of: str = "",
    candidate_relation: str = "",
    reason_codes: list[str] | None = None,
) -> dict[str, object]:
    return {
        "segment_id": segment_id,
        "classification": classification,
        "continuation_of_segment_id": continuation_of,
        "candidate_relation": candidate_relation,
        "reason_codes": list(reason_codes or []),
        "pdf_page_number": page,
        "period_labels": list(periods),
        "measure_labels": [],
        "anchor_ratios": list(ratios),
        "source_column_ordinals": list(range(len(ratios))),
        "bbox": [0.0, 50.0, 800.0, 700.0],
        "relation_status": (
            "UNRESOLVED" if classification == "UNRESOLVED" else "CONFIRMED"
        ),
        "row_order_start": 1,
        "row_order_end": 2,
    }


def _block(block_id: str, segment_id: str, classification: str) -> SimpleNamespace:
    return SimpleNamespace(
        block_id=block_id,
        physical_segment_ids=[segment_id],
        segment_classification=classification,
        evidence={},
    )


def _fixture() -> tuple[SimpleNamespace, list[SimpleNamespace]]:
    segments = [
        _segment("SEG_PRIMARY", "PRIMARY_TABLE"),
        _segment(
            "SEG_PRIMARY_CONT",
            "CONTINUATION_SEGMENT",
            continuation_of="SEG_PRIMARY",
        ),
        _segment("SEG_SUPPLEMENTARY", "SUPPLEMENTARY_TABLE"),
        _segment(
            "SEG_SUPPLEMENTARY_CONT",
            "CONTINUATION_SEGMENT",
            continuation_of="SEG_SUPPLEMENTARY",
        ),
        _segment(
            "SEG_UNRESOLVED",
            "UNRESOLVED",
            candidate_relation="CONTINUATION_SEGMENT",
            reason_codes=["CONTINUATION_RELATION_UNRESOLVED"],
        ),
        _segment("SEG_PEER", "PEER_TABLE"),
    ]
    blocks = [
        _block("BLOCK_PRIMARY", "SEG_PRIMARY", "PRIMARY_TABLE"),
        _block(
            "BLOCK_PRIMARY_CONT",
            "SEG_PRIMARY_CONT",
            "CONTINUATION_SEGMENT",
        ),
        _block(
            "BLOCK_SUPPLEMENTARY",
            "SEG_SUPPLEMENTARY",
            "SUPPLEMENTARY_TABLE",
        ),
        _block(
            "BLOCK_SUPPLEMENTARY_CONT",
            "SEG_SUPPLEMENTARY_CONT",
            "CONTINUATION_SEGMENT",
        ),
        _block("BLOCK_UNRESOLVED", "SEG_UNRESOLVED", "UNRESOLVED"),
        _block("BLOCK_PEER", "SEG_PEER", "PEER_TABLE"),
    ]
    return SimpleNamespace(stats={"physical_table_segments": segments}), blocks


def _selected_ids(selection: dict[str, object]) -> list[str]:
    return [block.block_id for block in selection["selected_blocks"]]


class _InventoryCursor:
    def __init__(self,row):
        self.row=row

    def fetchone(self):
        return self.row


class _InventoryConnection:
    def __init__(self,row):
        self.row=row

    def __enter__(self):
        return self

    def __exit__(self,exc_type,exc,tb):
        return False

    def execute(self,query,parameters):
        return _InventoryCursor(self.row)


class _InventoryRegistry:
    def __init__(self,row):
        self.row=row

    def connect(self):
        return _InventoryConnection(self.row)


def _certified_target(
    classification: str,
    logical_table_id: str,
) -> dict[str,object]:
    return {
        "certified_link_id":"CLINK_FIXTURE",
        "source_pdf_id":"PDF_FIXTURE",
        "logical_table_id":logical_table_id,
        "table_classification":classification,
        "segment_manifest_status":"CERTIFIED_SEGMENT_MANIFEST",
        "note_table_inventory_id":"INVENTORY_FIXTURE",
        "note_table_inventory_status":"COMPLETE",
        "note_reference":"NOTE_FIXTURE",
        "certified_segments":[{
            "certified_segment_id":"CSEG_FIXTURE",
            "order":0,
            "classification":classification,
            "start_page":1,
            "end_page":1,
            "bbox":[0.0,50.0,800.0,700.0],
            "period_signature":{"period_labels":["2024"]},
            "amount_lane_signature":{
                "lane_count":2,
                "anchor_ratios":[0.7,0.86],
            },
            "certification_status":"CERTIFIED",
        }],
    }


def _certified_inventory_row(logical_table_id: str) -> dict[str,object]:
    return {
        "note_table_inventory_id":"INVENTORY_FIXTURE",
        "source_pdf_id":"PDF_FIXTURE",
        "note_reference":"NOTE_FIXTURE",
        "logical_table_ids_json":json.dumps([logical_table_id]),
        "inventory_status":"COMPLETE",
        "certification_status":"CERTIFIED",
    }


def test_primary_only_materializes_only_first_primary_segment() -> None:
    result, blocks = _fixture()
    selection = _select_blocks_for_scope(
        result,
        blocks,
        capture_scope_policy="PRIMARY_ONLY",
        selected_block_roles=None,
        selected_block_ids=None,
    )

    assert _selected_ids(selection) == ["BLOCK_PRIMARY"]
    assert selection["capture_scope_limited"] is True
    assert selection["scope_boundary_decision"] == ""
    assert "CONTINUATION_EXCLUDED_BY_POLICY" not in selection["scope_warning_codes"]
    assert selection["scope_issue_codes"] == ["CONTINUATION_UNRESOLVED"]


def test_primary_only_confirms_policy_boundary_without_unresolved_relation() -> None:
    result, blocks = _fixture()
    result.stats["physical_table_segments"] = [
        segment
        for segment in result.stats["physical_table_segments"]
        if segment["segment_id"] != "SEG_UNRESOLVED"
    ]
    blocks = [block for block in blocks if block.block_id != "BLOCK_UNRESOLVED"]

    selection = _select_blocks_for_scope(
        result,
        blocks,
        capture_scope_policy="PRIMARY_ONLY",
        selected_block_roles=None,
        selected_block_ids=None,
    )

    assert selection["scope_boundary_decision"] == "POLICY_TRUNCATION"
    assert selection["scope_warning_codes"] == [
        "CONTINUATION_EXCLUDED_BY_POLICY"
    ]


def test_primary_continuation_policy_does_not_include_supplementary_chain() -> None:
    result, blocks = _fixture()
    selection = _select_blocks_for_scope(
        result,
        blocks,
        capture_scope_policy="PRIMARY_WITH_CONTINUATIONS",
        selected_block_roles=None,
        selected_block_ids=None,
    )

    assert _selected_ids(selection) == ["BLOCK_PRIMARY", "BLOCK_PRIMARY_CONT"]
    assert selection["scope_warning_codes"] == []
    assert selection["scope_issue_codes"] == ["CONTINUATION_UNRESOLVED"]


def test_all_note_tables_includes_each_confirmed_continuation_chain() -> None:
    result, blocks = _fixture()
    selection = _select_blocks_for_scope(
        result,
        blocks,
        capture_scope_policy="ALL_NOTE_TABLES",
        selected_block_roles=None,
        selected_block_ids=None,
    )

    assert _selected_ids(selection) == [
        "BLOCK_PRIMARY",
        "BLOCK_PRIMARY_CONT",
        "BLOCK_SUPPLEMENTARY",
        "BLOCK_SUPPLEMENTARY_CONT",
    ]
    assert selection["scope_warning_codes"] == []
    assert selection["scope_issue_codes"] == ["CONTINUATION_UNRESOLVED"]


def test_v2_primary_materializes_only_certified_runtime_segments() -> None:
    result, blocks = _fixture()
    selection = _select_blocks_for_scope(
        result,
        blocks,
        capture_scope_contract_version=2,
        capture_scope_policy="PRIMARY_ONLY",
        selected_logical_table_ids=None,
        selected_block_roles=None,
        selected_block_ids=None,
        certified_manifest_validation={
            "status": "VALID",
            "issue_codes": [],
            "validated_pairs": [
                {"discovered_segment_id": "SEG_PRIMARY"},
                {"discovered_segment_id": "SEG_PRIMARY_CONT"},
            ],
        },
    )

    assert _selected_ids(selection) == [
        "BLOCK_PRIMARY",
        "BLOCK_PRIMARY_CONT",
    ]
    assert selection["capture_scope_contract_version"] == 2
    assert selection["capture_scope_policy"] == "PRIMARY_ONLY"
    assert selection["requested_capture_scope_policy"] == "PRIMARY_ONLY"
    assert selection["capture_scope_limited"] is True
    assert selection["scope_warning_codes"] == []
    assert selection["scope_issue_codes"] == []


def test_v2_supplementary_materializes_only_its_certified_runtime_segments() -> None:
    result, blocks = _fixture()
    selection = _select_blocks_for_scope(
        result,
        blocks,
        capture_scope_contract_version=2,
        capture_scope_policy="SELECTED_NOTE_TABLES",
        selected_logical_table_ids=["LOGICAL_SUPPLEMENTARY"],
        selected_block_roles=None,
        selected_block_ids=None,
        certified_manifest_validation={
            "status": "VALID",
            "issue_codes": [],
            "validated_pairs": [
                {"discovered_segment_id": "SEG_SUPPLEMENTARY"},
                {"discovered_segment_id": "SEG_SUPPLEMENTARY_CONT"},
            ],
        },
    )

    assert _selected_ids(selection) == [
        "BLOCK_SUPPLEMENTARY",
        "BLOCK_SUPPLEMENTARY_CONT",
    ]
    assert selection["capture_scope_policy"] == "ALL_NOTE_TABLES"
    assert selection["requested_capture_scope_policy"] == "SELECTED_NOTE_TABLES"


def test_v2_requires_certified_runtime_segment_pairs() -> None:
    result, blocks = _fixture()
    with pytest.raises(
        PermissionError,
        match="CERTIFIED_SEGMENT_MANIFEST_RUNTIME_MATCH_REQUIRED",
    ):
        _select_blocks_for_scope(
            result,
            blocks,
            capture_scope_contract_version=2,
            capture_scope_policy="PRIMARY_ONLY",
            selected_logical_table_ids=None,
            selected_block_roles=None,
            selected_block_ids=None,
            certified_manifest_validation={
                "status": "VALID",
                "issue_codes": [],
                "validated_pairs": [],
            },
        )


def test_v2_rejects_review_required_manifest_before_materialization() -> None:
    result, blocks = _fixture()
    with pytest.raises(
        PermissionError,
        match="CERTIFIED_SEGMENT_MANIFEST_VALIDATION_REQUIRED",
    ):
        _select_blocks_for_scope(
            result,
            blocks,
            capture_scope_contract_version=2,
            capture_scope_policy="PRIMARY_ONLY",
            selected_logical_table_ids=None,
            selected_block_roles=None,
            selected_block_ids=None,
            certified_manifest_validation={
                "status": "REVIEW_REQUIRED",
                "issue_codes": ["CERTIFIED_SEGMENT_MANIFEST_DRIFT"],
                "validated_pairs": [
                    {"discovered_segment_id": "SEG_PRIMARY"},
                ],
            },
        )


def test_v2_requires_one_block_for_every_validated_runtime_segment() -> None:
    result, blocks = _fixture()
    blocks = [
        block for block in blocks
        if block.block_id != "BLOCK_PRIMARY_CONT"
    ]
    with pytest.raises(
        PermissionError,
        match="CERTIFIED_LOGICAL_TABLE_SEGMENTS_REQUIRED",
    ):
        _select_blocks_for_scope(
            result,
            blocks,
            capture_scope_contract_version=2,
            capture_scope_policy="PRIMARY_ONLY",
            selected_logical_table_ids=None,
            selected_block_roles=None,
            selected_block_ids=None,
            certified_manifest_validation={
                "status": "VALID",
                "issue_codes": [],
                "validated_pairs": [
                    {"discovered_segment_id": "SEG_PRIMARY"},
                    {"discovered_segment_id": "SEG_PRIMARY_CONT"},
                ],
            },
        )


def test_v2_allows_multiple_logical_blocks_in_one_runtime_segment() -> None:
    result, _ = _fixture()
    blocks = [
        _block("BLOCK_PRIMARY_DETAIL", "SEG_PRIMARY", "PRIMARY_TABLE"),
        _block("BLOCK_PRIMARY_MEASURE", "SEG_PRIMARY", "PRIMARY_TABLE"),
    ]

    selection = _select_blocks_for_scope(
        result,
        blocks,
        capture_scope_contract_version=2,
        capture_scope_policy="PRIMARY_ONLY",
        selected_logical_table_ids=None,
        selected_block_roles=None,
        selected_block_ids=None,
        certified_manifest_validation={
            "status": "VALID",
            "issue_codes": [],
            "validated_pairs": [
                {"discovered_segment_id": "SEG_PRIMARY"},
            ],
        },
    )

    assert _selected_ids(selection) == [
        "BLOCK_PRIMARY_DETAIL",
        "BLOCK_PRIMARY_MEASURE",
    ]


def test_explicit_block_selection_cannot_remove_primary_segment() -> None:
    result, blocks = _fixture()
    with pytest.raises(ValueError, match="CAPTURE_SCOPE_PRIMARY_SEGMENT_REQUIRED"):
        _select_blocks_for_scope(
            result,
            blocks,
            capture_scope_policy="ALL_NOTE_TABLES",
            selected_block_roles=None,
            selected_block_ids=["BLOCK_SUPPLEMENTARY"],
        )


@pytest.mark.parametrize(
    "segments",
    [
        [
            _segment("SEG_PRIMARY", "PRIMARY_TABLE"),
            _segment(
                "SEG_DANGLING",
                "CONTINUATION_SEGMENT",
                continuation_of="SEG_MISSING",
            ),
        ],
        [
            _segment("SEG_PRIMARY", "PRIMARY_TABLE"),
            _segment(
                "SEG_CYCLE_A",
                "CONTINUATION_SEGMENT",
                continuation_of="SEG_CYCLE_B",
            ),
            _segment(
                "SEG_CYCLE_B",
                "CONTINUATION_SEGMENT",
                continuation_of="SEG_CYCLE_A",
            ),
        ],
    ],
)
def test_invalid_continuation_graph_is_fail_closed(
    segments: list[dict[str, object]],
) -> None:
    blocks = [
        _block("BLOCK_PRIMARY", "SEG_PRIMARY", "PRIMARY_TABLE"),
        *[
            _block(
                f"BLOCK_{segment['segment_id']}",
                str(segment["segment_id"]),
                "CONTINUATION_SEGMENT",
            )
            for segment in segments[1:]
        ],
    ]
    selection = _select_blocks_for_scope(
        SimpleNamespace(stats={"physical_table_segments": segments}),
        blocks,
        capture_scope_policy="ALL_NOTE_TABLES",
        selected_block_roles=None,
        selected_block_ids=None,
    )

    assert _selected_ids(selection) == ["BLOCK_PRIMARY"]
    assert selection["scope_issue_codes"] == ["CONTINUATION_UNRESOLVED"]


def test_mixed_physical_segment_block_is_rejected() -> None:
    result, blocks = _fixture()
    blocks[0].physical_segment_ids = ["SEG_PRIMARY", "SEG_PRIMARY_CONT"]

    with pytest.raises(ValueError, match="CAPTURE_BLOCK_MIXED_PHYSICAL_SEGMENTS"):
        _select_blocks_for_scope(
            result,
            blocks,
            capture_scope_policy="PRIMARY_ONLY",
            selected_block_roles=None,
            selected_block_ids=None,
        )


def test_primary_only_unresolved_relation_blocks_scope_evidence() -> None:
    result, _ = _fixture()
    evidence = {
        "stats": {
            **result.stats,
            "capture_scope_policy": "PRIMARY_ONLY",
            "capture_scope_limited": True,
        },
        "rows": [],
    }

    state = derive_capture_scope_state(evidence)

    assert state["continuation_unresolved"] is True
    assert state["policy_evidence_incomplete"] is True


def test_legacy_primary_only_validates_certified_page_anchor() -> None:
    result = SimpleNamespace(stats={
        "physical_table_segments": [
            _segment("SEG_RUNTIME", "PRIMARY_TABLE", page=193),
        ],
    })

    governance = _validate_certified_scope_governance(
        result,
        certified_note_target={
            "certified_link_id": "CLINK_LEGACY",
            "confirmed_note_pdf_page_index": 193,
            "table_classification": "PRIMARY_TABLE",
            "segment_manifest_status": "LEGACY_PRIMARY_ANCHOR_ONLY",
            "certified_segments": [],
        },
        capture_scope_policy="PRIMARY_ONLY",
        enabled=True,
    )

    assert governance["issue_codes"] == []
    assert governance["manifest_validation"]["status"] == "VALID"
    assert governance["manifest_validation"]["validated_pairs"][0][
        "discovered_segment_id"
    ] == "SEG_RUNTIME"
    assert governance["inventory_validation"]["required"] is False


def test_inclusive_scope_requires_manifest_and_complete_inventory() -> None:
    result = SimpleNamespace(stats={
        "physical_table_segments": [
            _segment("SEG_RUNTIME", "PRIMARY_TABLE", page=193),
        ],
    })

    governance = _validate_certified_scope_governance(
        result,
        certified_note_target={
            "certified_link_id": "CLINK_LEGACY",
            "confirmed_note_pdf_page_index": 193,
            "table_classification": "PRIMARY_TABLE",
            "segment_manifest_status": "LEGACY_PRIMARY_ANCHOR_ONLY",
            "note_table_inventory_status": "INCOMPLETE",
            "certified_segments": [],
        },
        capture_scope_policy="PRIMARY_WITH_CONTINUATIONS",
        enabled=True,
    )

    assert governance["issue_codes"] == [
        "CERTIFIED_SEGMENT_MANIFEST_REQUIRED",
        "CERTIFIED_NOTE_TABLE_INVENTORY_REQUIRED",
    ]


def test_nested_certified_signatures_are_normalised_before_drift_validation() -> None:
    runtime_segment = _segment(
        "SEG_RUNTIME",
        "PRIMARY_TABLE",
        page=194,
        periods=("2024",),
        ratios=(0.7, 0.86),
    )
    runtime_segment["header_topology_fingerprint"] = "runtime-header"
    result = SimpleNamespace(stats={
        "physical_table_segments": [runtime_segment],
    })

    governance = _validate_certified_scope_governance(
        result,
        certified_note_target={
            "table_classification": "PRIMARY_TABLE",
            "segment_manifest_status": "CERTIFIED_SEGMENT_MANIFEST",
            "note_table_inventory_id": "NTINV_12",
            "note_table_inventory_status": "COMPLETE",
            "certified_segments": [{
                "certified_segment_id": "CERT_PRIMARY",
                "order": 0,
                "classification": "PRIMARY_TABLE",
                "start_page": 193,
                "end_page": 193,
                "bbox": {"x0": 0.0, "top": 50.0, "x1": 800.0, "bottom": 700.0},
                "period_signature": {"period_labels": ["2023"]},
                "header_signature": {
                    "fingerprint": "certified-header",
                    "labels": [],
                },
                "amount_lane_signature": {
                    "lane_count": 3,
                    "anchor_ratios": [0.5, 0.7, 0.9],
                },
            }],
        },
        capture_scope_policy="ALL_NOTE_TABLES",
        enabled=True,
    )

    assert governance["issue_codes"] == ["CERTIFIED_SEGMENT_MANIFEST_DRIFT"]
    assert set(
        governance["manifest_validation"]["validated_pairs"][0]["drift_fields"]
    ) >= {"PAGE", "HEADER", "PERIOD", "LANE"}


def test_runtime_segment_mapping_uses_page_and_classification_not_array_position() -> None:
    discovered = [
        _segment("SEG_PRIMARY", "PRIMARY_TABLE", page=195),
        _segment("SEG_SUPPLEMENTARY", "SUPPLEMENTARY_TABLE", page=195),
        _segment("SEG_SUPPLEMENTARY_NEXT", "SUPPLEMENTARY_TABLE", page=196),
    ]
    certified = [{
        "certified_segment_id": "CERT_SUPPLEMENTARY",
        "order": 0,
        "classification": "SUPPLEMENTARY_TABLE",
        "start_page": 195,
        "end_page": 195,
        "bbox": discovered[1]["bbox"],
        "period_signature": {"period_labels": ["2024"]},
        "amount_lane_signature": {
            "lane_count": 2,
            "anchor_ratios": [0.7, 0.86],
        },
    }]

    normalised = _normalise_certified_segments_for_runtime(
        certified, discovered,
    )

    assert normalised[0]["runtime_segment_id"] == "SEG_SUPPLEMENTARY"


def test_runtime_segment_mapping_uses_bbox_for_same_page_segments() -> None:
    discovered = [
        _segment("SEG_SUPPLEMENTARY_TOP", "SUPPLEMENTARY_TABLE", page=195),
        _segment("SEG_SUPPLEMENTARY_BOTTOM", "SUPPLEMENTARY_TABLE", page=195),
    ]
    discovered[0]["bbox"] = [0.0, 50.0, 800.0, 300.0]
    discovered[1]["bbox"] = [0.0, 320.0, 800.0, 700.0]
    certified = [{
        "certified_segment_id": "CERT_SUPPLEMENTARY_BOTTOM",
        "order": 0,
        "classification": "SUPPLEMENTARY_TABLE",
        "start_page": 195,
        "end_page": 195,
        "bbox": {"x0": 0.0, "y0": 320.0, "x1": 800.0, "y1": 700.0},
        "period_signature": {"period_labels": ["2024"]},
        "amount_lane_signature": {
            "lane_count": 2,
            "anchor_ratios": [0.7, 0.86],
        },
    }]

    normalised = _normalise_certified_segments_for_runtime(
        certified, discovered,
    )

    assert normalised[0]["runtime_segment_id"] == "SEG_SUPPLEMENTARY_BOTTOM"


def test_runtime_segment_mapping_uses_target_logical_bbox_when_segment_bbox_missing() -> None:
    discovered = [
        _segment("SEG_SUPPLEMENTARY_TOP", "SUPPLEMENTARY_TABLE", page=195),
        _segment("SEG_SUPPLEMENTARY_BOTTOM", "SUPPLEMENTARY_TABLE", page=195),
    ]
    discovered[0]["bbox"] = [0.0, 50.0, 800.0, 300.0]
    discovered[1]["bbox"] = [0.0, 320.0, 800.0, 700.0]
    certified = [{
        "certified_segment_id": "CERT_SUPPLEMENTARY_BOTTOM",
        "order": 0,
        "classification": "SUPPLEMENTARY_TABLE",
        "start_page": 195,
        "end_page": 195,
        "period_signature": {"period_labels": ["2024"]},
        "amount_lane_signature": {
            "lane_count": 2,
            "anchor_ratios": [0.7, 0.86],
        },
    }]

    normalised = _normalise_certified_segments_for_runtime(
        certified,
        discovered,
        target_logical_bbox={
            "pages": [{
                "page": 195,
                "bbox": {"x0": 0.0, "y0": 320.0, "x1": 800.0, "y1": 700.0},
            }],
        },
    )

    assert normalised[0]["runtime_segment_id"] == "SEG_SUPPLEMENTARY_BOTTOM"


def test_certified_continuation_parent_is_mapped_to_runtime_segment_id() -> None:
    result = SimpleNamespace(stats={
        "physical_table_segments": [
            _segment("SEG_RUNTIME_PRIMARY", "PRIMARY_TABLE", page=193),
            _segment(
                "SEG_RUNTIME_CONTINUATION",
                "CONTINUATION_SEGMENT",
                page=194,
                continuation_of="SEG_RUNTIME_PRIMARY",
            ),
        ],
    })
    certified_segments = [
        {
            "certified_segment_id": "CERT_PRIMARY",
            "order": 0,
            "classification": "PRIMARY_TABLE",
            "start_page": 193,
            "end_page": 193,
            "bbox": {"x0": 0.0, "y0": 50.0, "x1": 800.0, "y1": 700.0},
            "period_signature": {"period_labels": ["2024"]},
            "amount_lane_signature": {"lane_count": 2, "anchor_ratios": [0.7, 0.86]},
        },
        {
            "certified_segment_id": "CERT_CONTINUATION",
            "order": 1,
            "classification": "CONTINUATION_SEGMENT",
            "start_page": 194,
            "end_page": 194,
            "bbox": {"x0": 0.0, "y0": 50.0, "x1": 800.0, "y1": 700.0},
            "continuation_of_segment_id": "CERT_PRIMARY",
            "period_signature": {"period_labels": ["2024"]},
            "amount_lane_signature": {"lane_count": 2, "anchor_ratios": [0.7, 0.86]},
        },
    ]

    governance = _validate_certified_scope_governance(
        result,
        certified_note_target={
            "table_classification": "PRIMARY_TABLE",
            "segment_manifest_status": "CERTIFIED_SEGMENT_MANIFEST",
            "note_table_inventory_id": "NTINV_12",
            "note_table_inventory_status": "COMPLETE",
            "certified_segments": certified_segments,
        },
        capture_scope_policy="PRIMARY_WITH_CONTINUATIONS",
        enabled=True,
    )

    assert governance["issue_codes"] == []
    assert governance["manifest_validation"]["validated_pairs"][1][
        "continuation"
    ]["match"] is True


def test_local_primary_aligns_to_certified_supplementary_without_rewrite() -> None:
    discovered = _segment("SEG_LOCAL", "PRIMARY_TABLE", page=193)
    result = SimpleNamespace(stats={"physical_table_segments": [discovered]})

    governance = _validate_certified_scope_governance(
        result,
        certified_note_target={
            "table_classification": "SUPPLEMENTARY_TABLE",
            "segment_manifest_status": "CERTIFIED_SEGMENT_MANIFEST",
            "certified_segments": [{
                "certified_segment_id": "CERT_SUPPLEMENTARY",
                "order": 0,
                "classification": "SUPPLEMENTARY_TABLE",
                "start_page": 193,
                "end_page": 193,
                "bbox": {"x0": 0.0, "y0": 50.0, "x1": 800.0, "y1": 700.0},
                "period_signature": {"period_labels": ["2024"]},
                "amount_lane_signature": {"lane_count": 2, "anchor_ratios": [0.7, 0.86]},
            }],
        },
        capture_scope_policy="PRIMARY_ONLY",
        enabled=True,
    )

    assert governance["issue_codes"] == []
    assert governance["manifest_validation"]["alignment_exceptions"][0][
        "code"
    ] == "LOCAL_ANCHOR_CLASSIFICATION_CONTEXT"
    assert discovered["classification"] == "PRIMARY_TABLE"


def test_v2_primary_requires_full_manifest_but_not_inventory() -> None:
    result = SimpleNamespace(stats={
        "physical_table_segments":[
            _segment("SEG_RUNTIME","PRIMARY_TABLE"),
        ],
    })
    target=_certified_target("PRIMARY_TABLE","LOGICAL_PRIMARY")
    target["segment_manifest_status"]="LEGACY_PRIMARY_ANCHOR_ONLY"
    target["certified_segments"]=[]

    governance=_validate_certified_scope_governance(
        result,
        certified_note_target=target,
        capture_scope_contract_version=2,
        capture_scope_policy="PRIMARY_ONLY",
        selected_logical_table_ids=[],
        enabled=True,
    )

    assert governance["issue_codes"]==[
        "CERTIFIED_SEGMENT_MANIFEST_REQUIRED"
    ]
    assert governance["inventory_validation"]["required"] is False


def test_v2_supplementary_requires_registry_certified_inventory() -> None:
    result = SimpleNamespace(stats={
        "physical_table_segments":[
            _segment("SEG_RUNTIME","PRIMARY_TABLE"),
        ],
    })
    target=_certified_target(
        "SUPPLEMENTARY_TABLE","LOGICAL_SUPPLEMENTARY",
    )

    missing_authority=_validate_certified_scope_governance(
        result,
        certified_note_target=target,
        capture_scope_contract_version=2,
        capture_scope_policy="SELECTED_NOTE_TABLES",
        selected_logical_table_ids=["LOGICAL_SUPPLEMENTARY"],
        enabled=True,
    )
    assert missing_authority["issue_codes"]==[
        "CERTIFIED_NOTE_TABLE_INVENTORY_REQUIRED"
    ]

    valid=_validate_certified_scope_governance(
        result,
        certified_note_target=target,
        capture_scope_contract_version=2,
        capture_scope_policy="SELECTED_NOTE_TABLES",
        selected_logical_table_ids=["LOGICAL_SUPPLEMENTARY"],
        enabled=True,
        registry=_InventoryRegistry(
            _certified_inventory_row("LOGICAL_SUPPLEMENTARY")
        ),
    )
    assert valid["issue_codes"]==[]
    assert valid["inventory_validation"]["registry_authority_checked"] is True
    assert valid["inventory_validation"]["registry_inventory_found"] is True


def test_v2_inventory_note_reference_accepts_bare_terminal_ordinal() -> None:
    result = SimpleNamespace(stats={
        "physical_table_segments":[
            _segment("SEG_RUNTIME","PRIMARY_TABLE"),
        ],
    })
    target=_certified_target(
        "SUPPLEMENTARY_TABLE","LOGICAL_SUPPLEMENTARY",
    )
    target["note_reference"]="附注十二-13"
    inventory=_certified_inventory_row("LOGICAL_SUPPLEMENTARY")
    inventory["note_reference"]="13"

    governance=_validate_certified_scope_governance(
        result,
        certified_note_target=target,
        capture_scope_contract_version=2,
        capture_scope_policy="SELECTED_NOTE_TABLES",
        selected_logical_table_ids=["LOGICAL_SUPPLEMENTARY"],
        enabled=True,
        registry=_InventoryRegistry(inventory),
    )

    assert governance["issue_codes"]==[]
    assert governance["inventory_validation"]["status"]=="VALID"


def test_v2_inventory_note_reference_rejects_different_composed_prefix() -> None:
    result = SimpleNamespace(stats={
        "physical_table_segments":[
            _segment("SEG_RUNTIME","PRIMARY_TABLE"),
        ],
    })
    target=_certified_target(
        "SUPPLEMENTARY_TABLE","LOGICAL_SUPPLEMENTARY",
    )
    target["note_reference"]="附注十二-13"
    inventory=_certified_inventory_row("LOGICAL_SUPPLEMENTARY")
    inventory["note_reference"]="附注十三-13"

    governance=_validate_certified_scope_governance(
        result,
        certified_note_target=target,
        capture_scope_contract_version=2,
        capture_scope_policy="SELECTED_NOTE_TABLES",
        selected_logical_table_ids=["LOGICAL_SUPPLEMENTARY"],
        enabled=True,
        registry=_InventoryRegistry(inventory),
    )

    assert governance["issue_codes"]==[
        "CERTIFIED_NOTE_TABLE_INVENTORY_REQUIRED"
    ]


def test_v2_supplementary_target_must_match_selected_logical_id() -> None:
    result = SimpleNamespace(stats={
        "physical_table_segments":[
            _segment("SEG_RUNTIME","PRIMARY_TABLE"),
        ],
    })
    target=_certified_target(
        "SUPPLEMENTARY_TABLE","LOGICAL_SUPPLEMENTARY",
    )

    governance=_validate_certified_scope_governance(
        result,
        certified_note_target=target,
        capture_scope_contract_version=2,
        capture_scope_policy="PRIMARY_ONLY",
        selected_logical_table_ids=[],
        enabled=True,
        registry=_InventoryRegistry(
            _certified_inventory_row("LOGICAL_SUPPLEMENTARY")
        ),
    )

    assert governance["issue_codes"]==[
        "CERTIFIED_SELECTED_LOGICAL_TABLE_REQUIRED"
    ]


def test_v2_capture_target_requires_explicit_logical_identity() -> None:
    result = SimpleNamespace(stats={
        "physical_table_segments":[
            _segment("SEG_RUNTIME","PRIMARY_TABLE"),
        ],
    })
    target=_certified_target("PRIMARY_TABLE","LOGICAL_PRIMARY")
    target.pop("logical_table_id")
    target.pop("table_classification")

    governance=_validate_certified_scope_governance(
        result,
        certified_note_target=target,
        capture_scope_contract_version=2,
        capture_scope_policy="PRIMARY_ONLY",
        selected_logical_table_ids=[],
        enabled=True,
    )

    assert governance["issue_codes"]==[
        "CERTIFIED_LOGICAL_TABLE_REQUIRED"
    ]


class _RerunCaptureRepository:
    def __init__(self,run_path: Path):
        self.run_path=run_path

    def get(self,capture_id):
        return {
            "capture_id":capture_id,
            "run_path":str(self.run_path),
            "table_query":"fixture",
        }


class _RerunVersionRepository:
    def capture_versions(self,logical_asset_id):
        return [{"capture_id":"CAPTURE_FIXTURE","is_current":1}]


class _RerunOrchestrator:
    def __init__(self):
        self.repo=_RerunVersionRepository()
        self.request=None

    def execute(self,request):
        self.request=request
        return request


def _rerun_service(tmp_path,metadata):
    run_path=tmp_path/"capture"
    run_path.mkdir()
    (run_path/"table_capture_result.json").write_text(
        json.dumps({"start_page":1,"table_query":"fixture"}),
        encoding="utf-8",
    )
    (run_path/"capture_metadata.json").write_text(
        json.dumps(metadata),encoding="utf-8",
    )
    service=CaptureService(_RerunCaptureRepository(run_path),{})
    orchestrator=_RerunOrchestrator()
    service.configure(orchestrator=orchestrator)
    return service,orchestrator


def test_v2_rerun_replays_original_certified_request_snapshot(tmp_path) -> None:
    target=_certified_target("PRIMARY_TABLE","LOGICAL_PRIMARY")
    original=CaptureRequest.new(
        capture_mode=CaptureMode.CERTIFIED_TARGET,
        source_pdf_path=str(tmp_path/"fixture.pdf"),
        member_table_id="member_fixture",
        table_family_id="family_fixture",
        capture_scope_contract_version=2,
        capture_scope_policy="PRIMARY_ONLY",
        request_metadata={"certified_target":target},
    )
    service,orchestrator=_rerun_service(tmp_path,{
        "source_pdf_path":original.source_pdf_path,
        "capture_scope_contract_version":2,
        "capture_request_snapshot":original.to_dict(),
    })

    request=service.rerun("LOGICAL_ASSET_FIXTURE")

    assert request is orchestrator.request
    assert request.capture_mode=="CERTIFIED_TARGET"
    assert request.manual_page_range is None
    assert request.request_id!=original.request_id
    assert request.retry_of_request_id=="CAPTURE_FIXTURE"
    assert request.request_metadata["certified_target"]==target


def test_v2_rerun_reconstructs_existing_certified_metadata(tmp_path) -> None:
    target=_certified_target(
        "SUPPLEMENTARY_TABLE","LOGICAL_SUPPLEMENTARY",
    )
    service,_=_rerun_service(tmp_path,{
        "source_pdf_path":str(tmp_path/"fixture.pdf"),
        "capture_scope_contract_version":2,
        "requested_capture_scope_policy":"SELECTED_NOTE_TABLES",
        "selected_logical_table_ids":["LOGICAL_SUPPLEMENTARY"],
        "member_table_id":"member_fixture",
        "table_family_id":"family_fixture",
        "certified_target":target,
    })

    request=service.rerun("LOGICAL_ASSET_FIXTURE")

    assert request.capture_mode=="CERTIFIED_TARGET"
    assert request.capture_scope_policy=="SELECTED_NOTE_TABLES"
    assert request.selected_logical_table_ids==("LOGICAL_SUPPLEMENTARY",)
    assert request.request_metadata["certified_target"]==target


def test_v2_rerun_rejects_missing_certified_target_snapshot(tmp_path) -> None:
    service,_=_rerun_service(tmp_path,{
        "source_pdf_path":str(tmp_path/"fixture.pdf"),
        "capture_scope_contract_version":2,
        "capture_scope_policy":"PRIMARY_ONLY",
    })

    with pytest.raises(
        PermissionError,
        match="V2_RERUN_CERTIFIED_TARGET_SNAPSHOT_REQUIRED",
    ):
        service.rerun("LOGICAL_ASSET_FIXTURE")


def test_bundle_identity_isolates_logical_target_and_capture_version():
    scope={
        "capture_scope_contract_version":2,
        "capture_scope_policy":"ALL_NOTE_TABLES",
        "requested_capture_scope_policy":"SELECTED_NOTE_TABLES",
        "selected_logical_table_ids":["LOGICAL_A"],
        "selected_block_roles":[],
        "selected_block_ids":[],
    }
    first=_capture_bundle_identity(
        container_id="NOTE_SHARED",certified_logical_table_id="LOGICAL_A",
        capture_request_id="REQ_1",root_capture_id="CAP_1",
        scope_selection=scope,
    )
    repeated=_capture_bundle_identity(
        container_id="NOTE_SHARED",certified_logical_table_id="LOGICAL_A",
        capture_request_id="REQ_1",root_capture_id="CAP_1",
        scope_selection=scope,
    )
    other_target=_capture_bundle_identity(
        container_id="NOTE_SHARED",certified_logical_table_id="LOGICAL_B",
        capture_request_id="REQ_1",root_capture_id="CAP_1",
        scope_selection=scope,
    )
    other_version=_capture_bundle_identity(
        container_id="NOTE_SHARED",certified_logical_table_id="LOGICAL_A",
        capture_request_id="REQ_2",root_capture_id="CAP_2",
        scope_selection=scope,
    )
    assert first==repeated
    assert first["bundle_target_key"]!=other_target["bundle_target_key"]
    assert first["bundle_id"]!=other_target["bundle_id"]
    assert first["bundle_target_key"]==other_version["bundle_target_key"]
    assert first["bundle_id"]!=other_version["bundle_id"]


def test_logical_asset_identity_uses_certified_table_not_capture_policy():
    base={
        "company_id":"新华保险","report_year":"2025",
        "table_family_id":"financial_investment",
        "member_table_id":"debt_investment",
        "logical_source_role":"NOTE_DETAIL",
        "certified_logical_table_id":"LOGICAL_ECL_2025",
        "capture_scope_policy":"PRIMARY_ONLY",
        "selected_logical_table_ids":["LOGICAL_ECL_2025"],
    }
    changed_scope={
        **base,
        "capture_scope_policy":"PRIMARY_WITH_CONTINUATIONS",
        "selected_logical_table_ids":["LOGICAL_ECL_2025","OTHER"],
    }
    changed_table={**base,"certified_logical_table_id":"LOGICAL_BALANCE"}
    assert AssetGovernanceRepository.identity_payload(base)==(
        AssetGovernanceRepository.identity_payload(changed_scope)
    )
    assert AssetGovernanceRepository.identity_payload(base)!=(
        AssetGovernanceRepository.identity_payload(changed_table)
    )
    legacy={
        key:value for key,value in base.items()
        if key!="certified_logical_table_id"
    }
    assert "certified_logical_table_id" not in (
        AssetGovernanceRepository.identity_payload(legacy)
    )


def test_bundle_child_orders_require_one_normalised_root():
    assert _validate_bundle_child_orders([0,1,2])==(0,1,2)
    with pytest.raises(
        ValueError,match="CAPTURE_BUNDLE_ROOT_CARDINALITY_INVALID",
    ):
        _validate_bundle_child_orders([0,0,1])
    with pytest.raises(
        ValueError,match="CAPTURE_BUNDLE_CHILD_ORDER_INVALID",
    ):
        _validate_bundle_child_orders([0,2,2])
    with pytest.raises(
        ValueError,match="CAPTURE_BUNDLE_ROOT_CARDINALITY_INVALID",
    ):
        _validate_bundle_child_orders([1,2])


def test_same_bundle_replay_replaces_children_atomically(tmp_path):
    from metadata_registry import MetadataRegistry

    registry=MetadataRegistry(tmp_path/"metadata.db")
    now="2026-08-05T00:00:00+08:00"
    with registry.connect() as conn:
        conn.execute(
            """INSERT INTO capture_bundles
               (bundle_id,request_id,container_id,status,payload_json,
                created_at,updated_at)
               VALUES(?,?,?,?,?,?,?)""",
            ("BUNDLE_REPLAY","REQ_REPLAY","NOTE_REPLAY","COMPLETED","{}",now,now),
        )
        for block_id,capture_id,child_order in (
            ("STALE_ROOT","CAP_STALE_ROOT",0),
            ("STALE_CHILD","CAP_STALE_CHILD",1),
        ):
            conn.execute(
                """INSERT INTO capture_bundle_children
                   (bundle_id,block_id,capture_id,logical_asset_id,child_order,
                    status,payload_json,created_at)
                   VALUES(?,?,?,?,?,?,?,?)""",
                (
                    "BUNDLE_REPLAY",block_id,capture_id,None,child_order,
                    "CAPTURED","{}",now,
                ),
            )

    replacement=[{
        "block_id":"FRESH_ROOT",
        "capture_id":"CAP_FRESH_ROOT",
        "logical_asset_id":None,
        "child_order":0,
        "status":"CAPTURED",
        "payload_json":"{}",
    }]
    with registry.connect() as conn:
        _replace_capture_bundle_children(
            conn,bundle_id="BUNDLE_REPLAY",children=replacement,created_at=now,
        )
    with registry.connect() as conn:
        rows=conn.execute(
            """SELECT block_id,capture_id,child_order
               FROM capture_bundle_children WHERE bundle_id=?""",
            ("BUNDLE_REPLAY",),
        ).fetchall()
    assert [tuple(row) for row in rows]==[
        ("FRESH_ROOT","CAP_FRESH_ROOT",0),
    ]

    duplicate_replacement=[replacement[0],{
        **replacement[0],"capture_id":"CAP_DUPLICATE",
    }]
    with pytest.raises(Exception):
        with registry.connect() as conn:
            _replace_capture_bundle_children(
                conn,
                bundle_id="BUNDLE_REPLAY",
                children=duplicate_replacement,
                created_at=now,
            )
    with registry.connect() as conn:
        rows=conn.execute(
            """SELECT block_id,capture_id,child_order
               FROM capture_bundle_children WHERE bundle_id=?""",
            ("BUNDLE_REPLAY",),
        ).fetchall()
    assert [tuple(row) for row in rows]==[
        ("FRESH_ROOT","CAP_FRESH_ROOT",0),
    ]
