from __future__ import annotations

from compound_note_engine import segment_table_blocks
from table_capture import TableCaptureResult, TableCell, TableColumn, TableRow
from table_segment_classifier import validate_certified_segment_manifest


def _segment(
    segment_id: str,
    page: int,
    classification: str,
    *,
    periods: tuple[str, ...] = ("2024",),
    ratios: tuple[float, ...] = (0.4, 0.58, 0.76, 0.92),
    continuation_of: str | None = None,
) -> dict:
    return {
        "segment_id": segment_id,
        "pdf_page_number": page,
        "classification": classification,
        "period_labels": list(periods),
        "anchor_ratios": list(ratios),
        "source_column_ordinals": list(range(len(ratios))),
        "continuation_of_segment_id": continuation_of,
        "bbox": [0.0, 50.0, 800.0, 700.0],
    }


def _cell(ordinal: int, value: float) -> TableCell:
    return TableCell(
        column_ordinal=ordinal,
        source_column_index=ordinal + 1,
        raw=f"{value:,.0f}",
        parsed_number=value,
        unit_original="百万元",
        value_yuan=value * 1_000_000,
    )


def _row(
    order: int,
    segment_id: str,
    label: str,
    ordinals: list[int],
    *,
    excluded: bool = False,
) -> TableRow:
    return TableRow(
        row_order=order,
        page=1,
        block_id=segment_id,
        source_method="TEST_SEGMENT_MANIFEST",
        raw_item=label,
        normalized_item=label,
        canonical_item=None,
        mapping_status="UNMAPPED",
        row_type="DETAIL",
        row_level=0,
        parent_section=None,
        cells=[_cell(ordinal, float(index + 1)) for index, ordinal in enumerate(ordinals)],
        header_source_page=None,
        bbox={"x0": 50.0, "y0": order * 20.0, "x1": 760.0, "y1": order * 20.0 + 12.0},
        excluded_from_table_logic=excluded,
    )


def test_excluded_row_does_not_hide_active_physical_segment_change() -> None:
    primary = _segment("SEG_PRIMARY", 1, "PRIMARY_TABLE", ratios=(0.7, 0.86))
    supplementary = _segment("SEG_SUPPLEMENTARY", 1, "SUPPLEMENTARY_TABLE")
    result = TableCaptureResult(
        pdf_name="synthetic.pdf",
        pdf_sha256="sha256",
        table_query="债权投资",
        note_number="12",
        located_title="12 债权投资",
        start_page=1,
        end_page=1,
        pages=[1],
        unit="百万元",
        columns=[
            TableColumn(0, 1, "2024", "2024", None, False, "2024"),
            TableColumn(1, 2, "2023", "2023", None, False, "2023"),
            TableColumn(2, 3, "第一阶段", None, None, False, None, "第一阶段"),
            TableColumn(3, 4, "第二阶段", None, None, False, None, "第二阶段"),
            TableColumn(4, 5, "第三阶段", None, None, False, None, "第三阶段"),
            TableColumn(5, 6, "合计", None, None, False, None, "合计"),
        ],
        rows=[
            _row(1, "SEG_PRIMARY", "债券", [0, 1]),
            _row(2, "SEG_SUPPLEMENTARY", "续页表头噪声", [], excluded=True),
            _row(3, "SEG_SUPPLEMENTARY", "期初余额", [2, 3, 4, 5]),
        ],
        warnings=[],
        stats={
            "physical_table_segments": [primary, supplementary],
            "physical_segment_column_groups": [
                {"segment_id": "SEG_PRIMARY", "source_column_ordinals": [0, 1]},
                {"segment_id": "SEG_SUPPLEMENTARY", "source_column_ordinals": [2, 3, 4, 5]},
            ],
        },
    )

    _container, blocks = segment_table_blocks(result)

    assert len(blocks) == 2
    assert blocks[0].physical_segment_ids == ["SEG_PRIMARY"]
    assert blocks[1].physical_segment_ids == ["SEG_SUPPLEMENTARY"]
    assert blocks[0].segment_classification == "PRIMARY_TABLE"
    assert blocks[1].segment_classification == "SUPPLEMENTARY_TABLE"
    assert any(row.excluded_from_table_logic for row in blocks[0].rows)


def test_legacy_primary_only_validates_anchor_and_retains_all_discovery() -> None:
    discovered = [
        _segment("SEG_PRIMARY", 193, "PRIMARY_TABLE", ratios=(0.7, 0.86)),
        _segment("SEG_ECL_2024", 193, "SUPPLEMENTARY_TABLE"),
    ]
    certified = [{
        **_segment("SEG_PRIMARY", 193, "PRIMARY_TABLE", ratios=(0.7, 0.86)),
        "certified_segment_id": "CERT_PRIMARY",
        "runtime_segment_id": "SEG_PRIMARY",
    }]

    result = validate_certified_segment_manifest(
        discovered,
        certified,
        "LEGACY_PRIMARY_ANCHOR_ONLY",
        "PRIMARY_ONLY",
        "PRIMARY_TABLE",
    )

    assert result["status"] == "VALID"
    assert result["issue_codes"] == []
    assert len(result["discovered_segments"]) == 2
    assert len(result["validated_pairs"]) == 1
    assert result["validated_pairs"][0]["certified_segment_id"] == "CERT_PRIMARY"


def test_including_segments_requires_full_certified_manifest() -> None:
    discovered = [_segment("SEG_PRIMARY", 193, "PRIMARY_TABLE")]
    legacy_anchor = [{
        **_segment("SEG_PRIMARY", 193, "PRIMARY_TABLE"),
        "certified_segment_id": "CERT_PRIMARY",
        "runtime_segment_id": "SEG_PRIMARY",
    }]

    result = validate_certified_segment_manifest(
        discovered,
        legacy_anchor,
        "LEGACY_PRIMARY_ANCHOR_ONLY",
        "PRIMARY_WITH_CONTINUATIONS",
        "PRIMARY_TABLE",
    )

    assert result["status"] == "REVIEW_REQUIRED"
    assert result["issue_codes"] == ["CERTIFIED_SEGMENT_MANIFEST_REQUIRED"]
    assert result["discovered_segments"] == discovered
    assert result["certified_segments"] == legacy_anchor


def test_manifest_page_classification_period_lane_and_relation_drift() -> None:
    discovered = [_segment(
        "SEG_RUNTIME",
        194,
        "CONTINUATION_SEGMENT",
        periods=("2024",),
        continuation_of="SEG_PRIMARY",
    )]
    discovered[0]["header_topology_fingerprint"] = "runtime-header"
    certified = [{
        **_segment(
            "SEG_RUNTIME",
            195,
            "SUPPLEMENTARY_TABLE",
            periods=("2023",),
            ratios=(0.4, 0.66, 0.9),
            continuation_of=None,
        ),
        "certified_segment_id": "CERT_ECL_2023",
        "runtime_segment_id": "SEG_RUNTIME",
        "header_topology_fingerprint": "certified-header",
    }]

    result = validate_certified_segment_manifest(
        discovered,
        certified,
        "CERTIFIED_SEGMENT_MANIFEST",
        "ALL_NOTE_TABLES",
        "SUPPLEMENTARY_TABLE",
    )

    assert result["status"] == "REVIEW_REQUIRED"
    assert result["issue_codes"] == ["CERTIFIED_SEGMENT_MANIFEST_DRIFT"]
    assert set(result["validated_pairs"][0]["drift_fields"]) >= {
        "PAGE",
        "CLASSIFICATION",
        "HEADER",
        "PERIOD",
        "LANE",
        "CONTINUATION_RELATION",
    }


def test_local_primary_can_align_to_certified_supplementary_without_rewrite() -> None:
    discovered = [_segment("SEG_LOCAL", 193, "PRIMARY_TABLE")]
    certified = [{
        **_segment("SEG_LOCAL", 193, "SUPPLEMENTARY_TABLE"),
        "certified_segment_id": "CERT_SUPPLEMENTARY",
    }]

    result = validate_certified_segment_manifest(
        discovered,
        certified,
        "CERTIFIED_SEGMENT_MANIFEST",
        "PRIMARY_ONLY",
        "SUPPLEMENTARY_TABLE",
    )

    assert result["status"] == "VALID"
    assert result["issue_codes"] == []
    assert result["alignment_exceptions"] == [{
        "code": "LOCAL_ANCHOR_CLASSIFICATION_CONTEXT",
        "certified_segment_id": "CERT_SUPPLEMENTARY",
        "discovered_segment_id": "SEG_LOCAL",
        "certified_classification": "SUPPLEMENTARY_TABLE",
        "machine_classification": "PRIMARY_TABLE",
    }]
    assert discovered[0]["classification"] == "PRIMARY_TABLE"
    assert result["discovered_segments"][0]["classification"] == "PRIMARY_TABLE"
