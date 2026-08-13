from __future__ import annotations

import sys
from pathlib import Path

import fitz
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from spatial_table_capture import _lines_in_roi, locate_table_roi


def _segment(page: int = 1) -> dict:
    return {
        "certified_segment_id": "CSEG_TEST",
        "classification": "PRIMARY_TABLE",
        "start_page": page,
        "end_page": page,
        "certification_status": "CERTIFIED",
        "bbox": {
            "page": page,
            "x0": 20.0,
            "y0": 100.0,
            "x1": 500.0,
            "y1": 240.0,
        },
    }


def test_lines_in_roi_excludes_same_page_sibling_by_certified_bbox() -> None:
    document = fitz.open()
    document.new_page(width=595, height=842)
    roi = {
        "start_page": 1,
        "start_y": 0.0,
        "end_page": 1,
        "end_y": 842.0,
        "certified_page_bboxes": {
            1: {"x0": 20.0, "y0": 100.0, "x1": 500.0, "y1": 240.0},
        },
    }
    lines = [
        {"x0": 30.0, "x1": 480.0, "y0": 120.0, "y1": 130.0},
        {"x0": 30.0, "x1": 480.0, "y0": 300.0, "y1": 310.0},
    ]

    class _Document:
        def __getitem__(self, index):
            return document[index]

    import spatial_table_capture as spatial
    original = spatial._page_lines
    spatial._page_lines = lambda _doc, _page: lines
    try:
        selected = _lines_in_roi(_Document(), roi, 1)
    finally:
        spatial._page_lines = original
        document.close()

    assert len(selected) == 1
    assert selected[0]["y0"] == 120.0


def test_certified_bbox_identity_allows_missing_title(tmp_path: Path) -> None:
    pdf_path = tmp_path / "missing-title.pdf"
    document = fitz.open()
    page = document.new_page(width=595, height=842)
    page.insert_text((40, 130), "2025 2024")
    page.insert_text((40, 180), "债券 100 90")
    document.save(pdf_path)
    document.close()

    result = locate_table_roi(
        pdf_path,
        "不存在的标题",
        note_number="12",
        start_page_override=1,
        strict_target_identity=True,
        certified_target_heading="不存在的标题",
        certified_segments=[_segment()],
    )

    assert result["identity_source"] == "CERTIFIED_BBOX"
    assert result["start_y"] == 100.0
    assert result["end_y"] == 240.0
    assert result["boundary_reason"] == "certified_segment_bbox"


def test_missing_title_without_certified_bbox_remains_fail_closed(tmp_path: Path) -> None:
    pdf_path = tmp_path / "missing-title.pdf"
    document = fitz.open()
    page = document.new_page(width=595, height=842)
    page.insert_text((40, 130), "2025 2024")
    document.save(pdf_path)
    document.close()

    with pytest.raises(ValueError, match="CERTIFIED_TARGET_HEADING_MISMATCH"):
        locate_table_roi(
            pdf_path,
            "不存在的标题",
            note_number="12",
            start_page_override=1,
            strict_target_identity=True,
            certified_target_heading="不存在的标题",
        )


def test_unverified_bbox_does_not_bypass_title_gate(tmp_path: Path) -> None:
    pdf_path = tmp_path / "missing-title.pdf"
    document = fitz.open()
    page = document.new_page(width=595, height=842)
    page.insert_text((40, 130), "2025 2024")
    document.save(pdf_path)
    document.close()
    unverified = _segment()
    unverified["certification_status"] = "CANDIDATE"

    with pytest.raises(ValueError, match="CERTIFIED_TARGET_HEADING_MISMATCH"):
        locate_table_roi(
            pdf_path,
            "不存在的标题",
            note_number="12",
            start_page_override=1,
            strict_target_identity=True,
            certified_target_heading="不存在的标题",
            certified_segments=[unverified],
        )
