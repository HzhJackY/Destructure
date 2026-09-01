"""v6.6 boundary and note-text contamination regressions."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from semantic_row_parser import classify_cell_role, classify_non_data_text
from table_boundary_resolver import parse_note_ordinal, resolve_table_boundary


def main() -> None:
    assert parse_note_ordinal("附注八-9") == 9
    assert parse_note_ordinal("（十）") == 10
    assert parse_note_ordinal("(10)") == 10
    assert parse_note_ordinal("10.") == 10

    lines = {
        1: [
            {"text": "9. 当前附注", "x0": 10, "y0": 10},
            {"text": "数据 100 200", "x0": 10, "y0": 80},
            {"text": "10. 下一附注", "x0": 10, "y0": 220},
        ]
    }
    boundary = resolve_table_boundary(
        note_reference="附注八-9",
        title="9. 当前附注",
        start_page=1,
        start_y=20,
        title_x0=10,
        page_count=1,
        page_height=lambda _: 800,
        page_lines=lambda page: lines[page],
    )
    assert boundary["boundary_reason"] == "next_note_ordinal"
    assert boundary["end_y"] == 218
    assert boundary["boundary_confidence"] == "HIGH"

    false_numeric_peer = {
        1: [
            {"text": "9. 当前附注", "x0": 10, "y0": 10},
            {
                "text": "10. 1,234 5,678",
                "x0": 10,
                "y0": 120,
                "words": [
                    {"text": "10."},
                    {"text": "1,234"},
                    {"text": "5,678"},
                ],
            },
            {"text": "11. 后续同级附注", "x0": 10, "y0": 220, "words": [{"text": "11."}]},
        ]
    }
    peer_boundary = resolve_table_boundary(
        note_reference="附注八-9",
        title="9. 当前附注",
        start_page=1,
        start_y=20,
        title_x0=10,
        page_count=1,
        page_height=lambda _: 800,
        page_lines=lambda page: false_numeric_peer[page],
    )
    assert peer_boundary["boundary_reason"] == "next_peer_heading", peer_boundary
    assert peer_boundary["boundary_confidence"] == "MEDIUM", peer_boundary
    assert peer_boundary["boundary_evidence"]["method"] == "NEXT_PEER_HEADING", peer_boundary

    assert classify_non_data_text(
        "注：上述金额不包括应计利息。", numeric_cell_count=0, expected_numeric_columns=2
    ) == "NOTE_TEXT"
    assert classify_non_data_text(
        "（以下简称“京沪高铁”）", numeric_cell_count=0, expected_numeric_columns=2
    ) == "MEMO_TEXT"
    assert classify_non_data_text(
        "其中：", numeric_cell_count=0, expected_numeric_columns=2
    ) is None
    assert classify_cell_role("（京沪高铁）9,489-49,493", None) == "MIXED"
    assert classify_cell_role("9,489", 9489) == "NUMERIC"

    print("TABLE_BOUNDARY_NEXT_NOTE_PASS")
    print("NUMERIC_ROW_FALSE_BOUNDARY_REJECTED_PASS")
    print("NON_ADJACENT_PEER_BOUNDARY_REVIEW_REQUIRED_PASS")
    print("NOTE_TEXT_SEPARATION_PASS")
    print("ROW_TYPE_CLASSIFICATION_PASS")
    print("MIXED_CELL_DETECTION_PASS")


if __name__ == "__main__":
    main()
