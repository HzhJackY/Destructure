from __future__ import annotations

import hierarchical_child_discovery as discovery
import spatial_table_capture


def _line(text: str, y0: float, *, words: list[str] | None = None) -> dict:
    tokens = words if words is not None else text.split()
    return {
        "text": text,
        "x0": 60.0,
        "y0": y0,
        "x1": 520.0,
        "y1": y0 + 10.0,
        "words": [{"text": token} for token in tokens],
    }


def test_numeric_prose_after_total_is_a_boundary() -> None:
    lines = [
        _line("2025年12月31日 2024年12月31日", 100, words=["2025", "2024"]),
        _line("股票 70,535 27,327", 120, words=["股票", "70,535", "27,327"]),
        _line("合计 169,046 115,778", 140, words=["合计", "169,046", "115,778"]),
        _line("其中：", 160),
        _line("－累计公允价值变动 8,698 8,326", 180, words=["－累计公允价值变动", "8,698", "8,326"]),
        _line(
            "2025年度，根据本集团流动性安排，处置了成本为人民币22,371百万元。",
            205,
            words=["2025年度", "22,371"],
        ),
    ]
    assert discovery._post_total_narrative_boundary_y(
        lines, title_bottom=90.0
    ) == 205.0


def test_table_without_total_does_not_invent_narrative_boundary() -> None:
    lines = [
        _line("2025年12月31日 2024年12月31日", 100, words=["2025", "2024"]),
        _line("投资收益 308,251 129,639", 120, words=["投资收益", "308,251", "129,639"]),
        _line("2025年度，根据本集团安排说明如下。", 150, words=["2025年度"]),
    ]
    assert discovery._post_total_narrative_boundary_y(
        lines, title_bottom=90.0
    ) is None


def test_local_source_target_uses_exact_native_title_and_next_family_peer(
    monkeypatch,
) -> None:
    pages = {
        10: [
            _line("交易性金融资产", 100),
            _line("合计", 220),
        ],
        11: [
            _line("其他债权投资", 105),
        ],
    }

    class FakeDoc:
        def __len__(self) -> int:
            return 20

    monkeypatch.setattr(
        spatial_table_capture,
        "_page_lines",
        lambda _doc, page: pages.get(page, []),
    )
    context = discovery._source_target_local_context(
        FakeDoc(), start_page=10, table_title="交易性金融资产"
    )
    assert context is not None
    assert context["title_bbox"]["y0"] == 100.0
    assert context["next_peer_page"] == 11
    assert context["next_peer_title"] == "其他债权投资"


def test_narrative_boundary_precedes_later_peer() -> None:
    context = {
        "title_line": "其他权益工具投资",
        "next_peer_page": 20,
        "next_peer_title": "定期存款",
        "next_peer_bbox": {"x0": 90, "y0": 110, "x1": 150, "y1": 120},
    }
    boundary = discovery._source_target_boundary_contract(
        context, start_page=19, narrative_y0=500.0
    )
    assert boundary["boundary_status"] == "HARD_BOUNDARY_CONFIRMED"
    assert boundary["end_y"] == 499.99
    assert boundary["boundary_evidence"]["next_note_verified"] is True


def test_compact_ocr_date_tokens_are_reconstructed_from_explicit_components() -> None:
    words = [
        {"text": "2025712", "x0": 350, "x1": 401, "y0": 130, "y1": 140, "yc": 135},
        {"text": "A318", "x0": 406, "x1": 432, "y0": 130, "y1": 140, "yc": 135},
        {"text": "20244712", "x0": 458, "x1": 501, "y0": 130, "y1": 140, "yc": 135},
        {"text": "A318", "x0": 505, "x1": 531, "y0": 130, "y1": 140, "yc": 135},
    ]
    repaired = discovery._repair_compact_ocr_period_words(words)
    assert [row["text"] for row in sorted(repaired, key=lambda row: row["x0"])] == [
        "2025年12月31日", "2024年12月31日",
    ]


def test_recovered_ocr_geometry_is_frozen_on_segment_and_replayable() -> None:
    structure = {
        "segment_candidates": [{
            "segment_candidate_id": "SEG_1",
            "start_page": 142,
            "evidence": {"source": "NATIVE_PDF_LINES"},
        }],
    }
    ocr_lines = [{
        "text": "2023年12月31日 383,020",
        "x0": 300.0, "y0": 100.0, "x1": 500.0, "y1": 112.0,
        "words": [
            {"text": "2023年12月31日", "x0": 300.0, "y0": 100.0,
             "x1": 390.0, "y1": 112.0},
            {"text": "383,020", "x0": 440.0, "y0": 100.0,
             "x1": 500.0, "y1": 112.0},
        ],
    }]
    frozen = discovery._freeze_certified_ocr_geometry(
        structure, page_number=142, ocr_lines=ocr_lines,
        recovery_audit={"ocr_pages": [142], "ocr_cache_hits": 1},
    )
    evidence = frozen["segment_candidates"][0]["evidence"]
    assert evidence["certified_column_geometry_source"] == (
        "FAST_INDEX_OCR_WORDS_PDF_POINTS"
    )
    assert evidence["certified_ocr_geometry_contract_version"] == 1
    assert evidence["ocr_recovery_pages"] == [142]
    replayed = spatial_table_capture._certified_ocr_lines_for_page(
        [{
            "start_page": 142,
            "certification_status": "CERTIFIED",
            "evidence": evidence,
        }],
        page_number=142,
        certified_bbox={"x0": 250.0, "y0": 80.0, "x1": 520.0, "y1": 140.0},
    )
    assert replayed is not None
    assert "383,020" in " ".join(line["text"] for line in replayed)


def test_recovered_ocr_geometry_requires_exactly_one_page_segment() -> None:
    structure = {"segment_candidates": [
        {"segment_candidate_id": "SEG_1", "start_page": 142},
        {"segment_candidate_id": "SEG_2", "start_page": 142},
    ]}
    try:
        discovery._freeze_certified_ocr_geometry(
            structure,
            page_number=142,
            ocr_lines=[{"words": [{
                "text": "1", "x0": 1.0, "y0": 1.0, "x1": 2.0, "y1": 2.0,
            }]}],
            recovery_audit={},
        )
    except ValueError as exc:
        assert str(exc) == "CERTIFIED_OCR_GEOMETRY_SEGMENT_CARDINALITY_REQUIRED"
    else:
        raise AssertionError("ambiguous segment geometry must fail closed")


def test_post_total_numeric_noise_outside_amount_lane_does_not_expand_bbox() -> None:
    lines = [
        _line("2023年12月31日", 100, words=["2023年12月31日"]),
        {
            **_line("合计 96,541", 190, words=["合计", "96,541"]),
            "words": [
                {"text": "合计", "xc": 80.0},
                {"text": "96,541", "xc": 500.0},
            ],
        },
        {
            **_line("F20235R MRARAROERH UWE SKAAARM3 0430 A TNE", 260),
            "words": [
                {"text": "F20235R", "xc": 85.0},
                {"text": "MRARAROERH", "xc": 170.0},
                {"text": "0430", "xc": 342.0},
            ],
        },
    ]
    assert spatial_table_capture._primary_table_end_y(
        lines, header_y1=112.0, amount_anchors=[500.0], page_width=595.0,
    ) == 200.0


def test_post_total_value_on_certified_lane_remains_inside_table() -> None:
    lines = [
        {
            **_line("合计 96,541", 190),
            "words": [
                {"text": "合计", "xc": 80.0},
                {"text": "96,541", "xc": 500.0},
            ],
        },
        {
            **_line("其中成本 93,213", 220),
            "words": [
                {"text": "其中成本", "xc": 100.0},
                {"text": "93,213", "xc": 500.0},
            ],
        },
    ]
    assert spatial_table_capture._primary_table_end_y(
        lines, header_y1=112.0, amount_anchors=[500.0], page_width=595.0,
    ) is None
