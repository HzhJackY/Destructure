"""PDF review preview must be useful for real evidence and safe on bad inputs."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from pdf_evidence import extract_statement_anchor, page_preview
from guided_workflow_ui import _resolve_pdf_path


PDF_DIR = Path(r"C:\dev\AXA_research\docu")


def main() -> None:
    pdf = sorted(PDF_DIR.glob("中国平安20*.pdf"))[-1]
    anchor = extract_statement_anchor(pdf)
    assert anchor["status"] == "FOUND", anchor

    valid = page_preview(
        pdf,
        int(anchor["statement_pdf_page_index"]) - 1,
        ["金融投资", "债权投资", "其他债权投资"],
    )
    assert valid["status"] == "OK", valid
    assert valid["png"], valid
    assert valid["evidence_level"] == "LEVEL_1_BBOX", valid
    assert valid["bboxes"], valid

    out_of_range = page_preview(pdf, 999999, ["金融投资"])
    assert out_of_range["status"] == "PAGE_OUT_OF_RANGE", out_of_range
    assert out_of_range["png"] is None, out_of_range

    missing = page_preview(PDF_DIR / "missing-review-evidence.pdf", 0, ["金融投资"])
    assert missing["status"] == "PDF_MISSING", missing
    assert missing["png"] is None, missing
    assert _resolve_pdf_path({"pdf_id": "PDF::" + str(pdf)}) == pdf

    print("REAL_PDF_REVIEW_PREVIEW_PASS", pdf.name, valid["pdf_page_index"])
    print("PDF_PAGE_OUT_OF_RANGE_NON_CRASH_PASS")
    print("PDF_MISSING_NON_CRASH_PASS")
    print("OPAQUE_PDF_ID_PREVIEW_RESOLUTION_PASS")


if __name__ == "__main__":
    main()
