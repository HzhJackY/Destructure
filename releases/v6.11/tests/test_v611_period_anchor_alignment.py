from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from spatial_table_capture import (  # noqa: E402
    _detect_header_generalized,
    _line_to_spatial_cells,
    _page_lines,
    _period_words_generalized,
    _validated_numeric_assignment_anchors,
)


PAGE_WIDTH = 595.276


def _canonical_xinhua_2025_pdf() -> Path:
    for parent in Path(__file__).resolve().parents:
        candidate = parent / "docu" / "新华保险2025年报.pdf"
        if candidate.exists():
            return candidate
    return Path(__file__).resolve().parents[3] / "docu" / "新华保险2025年报.pdf"


def _word(x0: float, x1: float, text: str, y0: float) -> dict:
    return {
        "x0": x0,
        "x1": x1,
        "y0": y0,
        "y1": y0 + 27.0,
        "xc": (x0 + x1) / 2.0,
        "yc": y0 + 13.5,
        "text": text,
    }


def _line(words: list[dict]) -> dict:
    return {
        "words": words,
        "text": " ".join(str(word["text"]) for word in words),
        "x0": min(word["x0"] for word in words),
        "x1": max(word["x1"] for word in words),
        "y0": min(word["y0"] for word in words),
        "y1": max(word["y1"] for word in words),
        "yc": sum(word["yc"] for word in words) / len(words),
    }


def test_adjacent_absolute_dates_do_not_form_cross_column_period_hit() -> None:
    line = _line([
        _word(389.7, 462.05, "2025年12月31日", 102.0),
        _word(474.74, 547.08, "2024年12月31日", 102.0),
    ])

    hits = _period_words_generalized(line)

    assert [hit["year"] for hit in hits] == ["2025", "2024"]
    assert [hit["xc"] for hit in hits] == pytest.approx([425.875, 510.91], abs=0.001)


def test_adjacent_date_header_keeps_both_amount_columns() -> None:
    header_line = _line([
        _word(389.7, 462.05, "2025年12月31日", 102.0),
        _word(474.74, 547.08, "2024年12月31日", 102.0),
    ])
    header = _detect_header_generalized([header_line], PAGE_WIDTH)
    assert header is not None

    amount_line = _line([
        _word(62.3, 110.5, "未上市股权", 150.7),
        _word(451.33, 462.06, "24", 157.8),
        _word(536.37, 547.10, "22", 158.3),
    ])

    parsed = _line_to_spatial_cells(amount_line, header["anchors"], PAGE_WIDTH)

    assert parsed["label"] == "未上市股权"
    assert [value[0] for value in parsed["values"]] == ["24", "22"]


def test_assignment_anchor_helper_requires_prevalidated_lane_support() -> None:
    """Boundary selection stays upstream; weak or absent summaries disable lanes."""
    header_anchors = [468.4, 510.9]
    assert _validated_numeric_assignment_anchors(
        header_anchors,
        None,
        page_width=595.3,
    ) is None
    assert _validated_numeric_assignment_anchors(
        header_anchors,
        {"centers": [450.2, 535.3], "supports": [1, 1], "lines": 1},
        page_width=595.3,
    ) is None
    assert _validated_numeric_assignment_anchors(
        header_anchors,
        {"centers": [450.2, 535.3], "supports": [4, 4], "lines": 4},
        page_width=595.3,
    ) == [450.2, 535.3]


@pytest.mark.skipif(
    not _canonical_xinhua_2025_pdf().exists(),
    reason="canonical Xinhua 2025 PDF is not available in this checkout",
)
def test_real_xinhua_2025_unlisted_equity_retains_both_period_values() -> None:
    fitz = pytest.importorskip("fitz")

    pdf_path = _canonical_xinhua_2025_pdf()
    document = fitz.open(str(pdf_path))
    try:
        lines = _page_lines(document, 198)
        header = _detect_header_generalized(
            lines,
            float(document[197].rect.width),
        )
        assert header is not None
        target = next(line for line in lines if "未上市股权" in line["text"])
        parsed = _line_to_spatial_cells(
            target,
            header["anchors"],
            float(document[197].rect.width),
        )
        assert [value[0] for value in parsed["values"]] == ["24", "22"]
    finally:
        document.close()
