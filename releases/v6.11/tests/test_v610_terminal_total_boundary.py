from capture_library import derive_boundary_status


def test_explicit_terminal_total_without_continuation_is_auto_high_confidence():
    result = {
        "boundary_status": "UNASSESSED",
        "stats": {"boundary_reason": "no_next_note_in_capture"},
        "rows": [
            {"row_type": "DETAIL", "raw_item": "股票"},
            {"row_type": "DETAIL", "raw_item": "未上市股权"},
            {"row_type": "TOTAL", "raw_item": "合计"},
        ],
    }
    assert derive_boundary_status(result) == "AUTO_HIGH_CONFIDENCE"


def test_terminal_total_does_not_override_continuation_warning():
    result = {
        "boundary_status": "UNASSESSED",
        "stats": {"boundary_reason": "max_pages_reached"},
        "rows": [{"row_type": "TOTAL", "raw_item": "合计"}],
    }
    assert derive_boundary_status(result) == "REVIEW_REQUIRED"
