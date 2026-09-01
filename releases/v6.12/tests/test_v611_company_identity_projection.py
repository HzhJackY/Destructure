from __future__ import annotations

from pathlib import Path
import sys
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from batch_pipeline import infer_company_year
from pdf_selection_workspace import infer_pdf_dimensions
from spatial_table_capture import (
    _is_indented_group_section,
    _promote_single_child_outer_section,
)
from table_capture import normalize_item_label


@pytest.mark.parametrize(
    ("filename", "expected_company", "expected_year"),
    [
        ("中国人寿2023年年度报告.pdf", "中国人寿", "2023"),
        ("5ea1048c3a93_中国人寿2023年年度报告.pdf", "中国人寿", "2023"),
        ("中国平安2023年报.pdf", "中国平安", "2023"),
        ("新华保险2024年度报告.pdf", "新华保险", "2024"),
    ],
)
def test_company_identity_drops_report_year_linker_suffix(
    filename: str,
    expected_company: str,
    expected_year: str,
) -> None:
    path = Path(filename)
    assert infer_company_year(path, "") == (expected_company, expected_year)
    assert infer_pdf_dimensions(path) == {
        "company": expected_company,
        "year": expected_year,
    }


@pytest.mark.parametrize(
    ("raw_label", "expected"),
    [
        ("保户质押贷款(a)", "保户质押贷款"),
        ("其他贷款（b）", "其他贷款"),
        ("已计提减值金额（附注十、32）", "已计提减值金额"),
        ("其他注", "其他"),
        ("股权型投资其他注", "股权型投资其他"),
        ("备注", "备注"),
        ("附注", "附注"),
        ("5年以内（含5年）", "5年以内（含5年）"),
    ],
)
def test_normalized_item_strips_only_trailing_footnote_identity_noise(
    raw_label: str,
    expected: str,
) -> None:
    assert normalize_item_label(raw_label) == expected


def _word(text: str, x0: float, x1: float) -> dict[str, float | str]:
    return {
        "text": text,
        "x0": x0,
        "x1": x1,
        "xc": (x0 + x1) / 2,
    }


def _line(*words: dict[str, float | str]) -> dict[str, object]:
    return {
        "words": list(words),
        "text": " ".join(str(word["text"]) for word in words),
        "x0": min(float(word["x0"]) for word in words),
    }


def test_indented_sibling_rows_closed_by_subtotal_form_section() -> None:
    lines = [
        _line(_word("债权型投资", 10, 30)),
        _line(_word("国债", 20, 30), _word("100", 80, 88), _word("90", 100, 108)),
        _line(_word("企业债券", 20, 40), _word("200", 80, 88), _word("180", 100, 108)),
        _line(_word("小计", 10, 20), _word("300", 80, 88), _word("270", 100, 108)),
    ]
    assert _is_indented_group_section(
        lines,
        current_line_index=1,
        parent_x0=10,
        first_child_x0=20,
        anchors=[84, 104],
        page_width=120,
    )


def test_single_indented_wrapped_label_is_not_section() -> None:
    lines = [
        _line(_word("当期发生的保费获取", 10, 45)),
        _line(_word("现金流", 20, 30), _word("100", 80, 88), _word("90", 100, 108)),
        _line(_word("管理费用", 10, 30), _word("200", 80, 88), _word("180", 100, 108)),
        _line(_word("合计", 10, 20), _word("300", 80, 88), _word("270", 100, 108)),
    ]
    assert not _is_indented_group_section(
        lines,
        current_line_index=1,
        parent_x0=10,
        first_child_x0=20,
        anchors=[84, 104],
        page_width=120,
    )


def test_single_child_axis_after_subtotal_promotes_outer_section() -> None:
    lines = [
        _line(_word("股权型投资", 10, 30)),
        _line(_word("其他注", 20, 35), _word("–", 80, 88), _word("17", 100, 108)),
        _line(_word("合计", 10, 20), _word("300", 80, 88), _word("270", 100, 108)),
    ]
    rows = [
        SimpleNamespace(row_type="SUBTOTAL", cells=[object()], page=1, block_id="B"),
        SimpleNamespace(
            row_type="DETAIL",
            row_role="DETAIL",
            cells=[],
            page=1,
            block_id="B",
            bbox={"x0": 10},
            normalized_item="以成本计量的可供出售金融资产",
            parent_section="股权型投资",
            row_level=1,
            label_derivation="EXPLICIT_TEXT",
        ),
    ]
    parent = _promote_single_child_outer_section(
        rows,
        {"x0": 10, "page": 1, "block_id": "B"},
        lines,
        current_line_index=1,
        first_child_x0=20,
        anchors=[84, 104],
        page_width=120,
    )
    assert parent == "以成本计量的可供出售金融资产"
    assert rows[-1].row_type == "SECTION_HEADER"
    assert rows[-1].parent_section is None
