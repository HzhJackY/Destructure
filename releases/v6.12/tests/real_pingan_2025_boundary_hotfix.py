"""Real 中国平安 2025 boundary-contamination acceptance."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from note_target_resolver import NoteReferenceResolver
from table_capture import capture_named_table


PDF = Path(r"C:\dev\AXA_research\docu\中国平安2025年报.pdf")
ITEMS = [
    ("以公允价值计量且其变动计入当期损益的金融资产", "附注八-9", "next_note_ordinal"),
    ("债权投资", "附注八-10", "next_note_ordinal"),
    ("其他债权投资", "附注八-11", "next_note_ordinal"),
    ("其他权益工具投资", "附注八-12", "next_note_ordinal"),
]


def main() -> None:
    resolver = NoteReferenceResolver()
    total_detail_pollution = 0
    for member, reference, expected_boundary in ITEMS:
        candidates = resolver.candidates_from_pdf(
            PDF, note_reference=reference, member_table=member
        )
        target = resolver.certify(candidates[0])
        result = capture_named_table(
            PDF,
            member,
            note_number=reference,
            start_page_override=target["confirmed_note_pdf_page_index"],
            max_pages=8,
            allow_legacy_fallback=False,
        )
        assert result.stats["boundary_reason"] == expected_boundary, (
            member, result.stats["boundary_reason"]
        )
        assert result.stats["boundary_confidence"] == "HIGH", member
        expected_next = int(expected_boundary.rsplit("_", 1)[-1])
        assert result.stats["boundary_evidence"]["next_note_ordinal"] == expected_next
        assert all(
            not (
                row.row_type == "DETAIL"
                and any(
                    token in str(row.raw_item or "")
                    for token in ("以下名称", "以下简称", "说明：", "注：")
                )
            )
            for row in result.rows
        ), member
        total_detail_pollution += sum(
            row.row_type == "DETAIL"
            and any(
                token in str(row.raw_item or "")
                for token in ("以下名称", "以下简称", "说明：", "注：")
            )
            for row in result.rows
        )
        next_title = str(result.stats["boundary_evidence"]["next_note_title"])
        assert all(next_title not in str(row.raw_item or "") for row in result.rows), member
        assert result.stats["mixed_cell_count"] == 0, member
        print(
            "REAL_BOUNDARY",
            reference,
            result.start_page,
            result.end_page,
            result.stats["boundary_reason"],
            len(result.rows),
            result.stats["memo_text_rows"],
            result.stats["note_text_rows"],
        )
    assert total_detail_pollution == 0
    print("NO_CROSS_NOTE_CONTAMINATION_PASS")
    print("REAL_PINGAN_2025_BOUNDARY_HOTFIX_PASS")


if __name__ == "__main__":
    main()
