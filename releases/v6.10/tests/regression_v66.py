"""Focused v6.6 hard-invariant and note-resolver contracts."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from note_target_resolver import NoteReferenceResolver, chinese_ordinal
from statement_anchored_family import StatementOccurrence, build_capture_plan


def occurrence() -> StatementOccurrence:
    return StatementOccurrence(
        occurrence_id="A", display_name="金融投资", statement_type="BALANCE_SHEET",
        source_table_title="合并资产负债表", scope="CONSOLIDATED", statement_pdf_page_index=183,
        statement_printed_page="183", parent_text="金融投资",
        child_rows=({"item": "债权投资", "member_table": "债权投资", "note_reference_normalized": "附注八-10", "value": 1270569},), evidence={},
    )


def main() -> None:
    try:
        build_capture_plan(occurrence())
        raise AssertionError("unselected anchor unexpectedly materialised")
    except PermissionError as error:
        assert str(error) == "UNSELECTED_ANCHOR_NEVER_MATERIALIZES"
    plan = build_capture_plan(occurrence(), selected_anchor=True)
    assert plan["items"][1]["status"] == "REVIEW_REQUIRED"
    target = {"status": "CERTIFIED_NOTE_TARGET", "confirmed_note_pdf_page_index": 210}
    child = dict(occurrence().child_rows[0]) | {"certified_note_target": target}
    selected = StatementOccurrence(**{**occurrence().__dict__, "child_rows": (child,)})
    plan = build_capture_plan(selected, selected_anchor=True)
    assert plan["items"][1]["status"] == "READY"
    assert plan["items"][1]["confirmed_note_pdf_page_index"] == 210
    assert [chinese_ordinal(x) for x in ["10", "十", "（十）", "(10)"]] == [10, 10, 10, 10]
    pages = ["八、合并财务报表主要项目注释\n10.\n债权\n投资\n2025年12月31日 2024年12月31日\n政府债 1,000\n金融债 2,000\n企业债 3,000\n合计 6,000"]
    candidates = NoteReferenceResolver().candidates_from_pages(pages, note_reference="附注八-10", member_table="债权投资")
    assert candidates and candidates[0]["locator_method"] == "SECTION_ORDINAL_SEMANTIC"
    assert candidates[0]["following_table_signature"]
    print("UNSELECTED_ANCHOR_NEVER_MATERIALIZES_PASS")
    print("NOTE_TARGET_REQUIRED_BEFORE_CAPTURE_PASS")
    print("NOTE_SECTION_ORDINAL_SEMANTIC_RECALL_PASS")
    print("NOTE_ORDINAL_VARIANT_NORMALIZATION_PASS")
    print("SPLIT_HEADING_BLOCK_RECALL_PASS")
    print("FOLLOWING_TABLE_SIGNATURE_PASS")


if __name__ == "__main__":
    main()
