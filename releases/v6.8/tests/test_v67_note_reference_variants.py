"""Targeted v6.7.x note-reference grammar acceptance."""
from __future__ import annotations
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from statement_anchored_family import compose_note_reference
from note_target_resolver import NoteReferenceResolver, parse_note_reference


def main() -> None:
    sectioned = compose_note_reference("附注八", "11")
    assert sectioned["note_reference_normalized"] == "附注八-11"
    assert sectioned["note_reference_status"] == "COMPOSED_FROM_HEADER_AND_ROW"

    direct = compose_note_reference("附注", "11")
    assert direct["note_reference_normalized"] == "附注11"
    assert direct["note_reference_status"] == "EXPLICIT_ORDINAL_COLUMN"
    assert parse_note_reference("附注11") == ("", 11)
    assert parse_note_reference("附注八-11") == ("八", 11)

    cross = compose_note_reference("附注", "8/59(1)")
    assert cross["note_reference_normalized"] == ""
    assert cross["note_reference_status"] == "CROSS_REFERENCE_REVIEW_REQUIRED"

    pages = [
        "11. 交易性金融资产\n2023年12月31日\n2022年12月31日\n"
        "政府债 100 90\n金融债 80 70\n企业债 60 50\n合计 240 210"
    ]
    candidates = NoteReferenceResolver().candidates_from_pages(
        pages, note_reference="附注11", member_table="交易性金融资产"
    )
    assert candidates and candidates[0]["ordinal"] == 11, candidates
    assert candidates[0]["section"] == ""
    assert candidates[0]["locator_method"] == "ORDINAL_SEMANTIC", candidates
    print("NOTE_REFERENCE_SECTIONED_COMPOSITION_PASS")
    print("NOTE_REFERENCE_DIRECT_ORDINAL_PASS")
    print("NOTE_REFERENCE_CROSS_REFERENCE_ABSTAIN_PASS")
    print("NOTE_REFERENCE_DIRECT_ORDINAL_LOCATOR_PASS")


if __name__ == "__main__":
    main()
