from __future__ import annotations

import tempfile
from pathlib import Path

import fitz

from conditional_statement_ocr import classify_page, conditional_ocr_primary_statements
from generic_discovery import discover


def _image_pdf(path: Path, pages: int = 3) -> Path:
    doc = fitz.open()
    pix = fitz.Pixmap(fitz.csRGB, fitz.IRect(0, 0, 600, 800), 0)
    pix.clear_with(255)
    payload = pix.tobytes("png")
    for _ in range(pages):
        page = doc.new_page(width=600, height=800)
        page.insert_image(page.rect, stream=payload)
    doc.save(path)
    doc.close()
    return path


OCR_STATEMENT = """合并资产负债表
2023年12月31日 人民币元
资产
金融投资 100
债权投资
负债
所有者权益
资产总计
负债合计"""


OCR_FINANCIAL_INVESTMENT_PARENT = """合并资产负债表
2023年12月31日
资产                 附注七
金融投资：
交易性金融资产       10 1,000
债权投资             11 2,000
其他债权投资         12 3,000
其他权益工具投资     13 4,000
资产总计"""


OCR_FINANCIAL_INVESTMENT_CHILDREN_ONLY = """合并资产负债表
2023年12月31日
资产                 附注七
交易性金融资产       10 1,000
债权投资             11 2,000
其他债权投资         12 3,000
其他权益工具投资     13 4,000
资产总计"""


def test_high_confidence_text_path_does_not_trigger_ocr_and_keeps_text_mode():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp); pdf = _image_pdf(root / "text.pdf", 1); audit = {}
        rows = discover(
            pdf, root / "cache", display_name="金融投资",
            discovery_context={"preferred_statement_type": "BALANCE_SHEET", "core_candidates": ["债权投资"]},
            text_provider=lambda _: [OCR_STATEMENT],
            ocr_provider=lambda *_: (_ for _ in ()).throw(AssertionError("OCR must not run")),
            audit_sink=audit,
        )
        assert rows and audit["ocr_triggered"] is False
        assert {row["discovery_mode"] for row in rows} == {"TEXT_LAYER"}
        assert audit["final_status"] == "FOUND_HIGH_CONFIDENCE_TEXT"


def test_image_statement_uses_bounded_ocr_and_reuses_existing_scoring_path():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp); pdf = _image_pdf(root / "image.pdf"); audit = {}
        rows = discover(
            pdf, root / "cache", display_name="金融投资",
            discovery_context={"preferred_statement_type": "BALANCE_SHEET", "core_candidates": ["债权投资"]},
            text_provider=lambda _: ["", "", ""],
            ocr_provider=lambda _, page, __: OCR_STATEMENT if page == 2 else "封面图片",
            audit_sink=audit,
        )
        assert audit["ocr_triggered"] is True
        assert 2 in audit["ocr_pages"]
        assert audit["ocr_page_count"] <= 12
        assert audit["ocr_page_count"] < audit["total_pages"]
        assert audit["full_document_ocr_count"] == 0
        assert any(row["statement_pdf_page_index"] == 2 for row in rows)
        assert all(row["discovery_mode"] == "OCR_FALLBACK" for row in rows)


def test_image_cover_is_not_false_positive_statement():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp); pdf = _image_pdf(root / "cover.pdf"); audit = {}
        rows = discover(
            pdf, root / "cache", display_name="金融投资",
            discovery_context={"preferred_statement_type": "BALANCE_SHEET", "core_candidates": ["债权投资"]},
            text_provider=lambda _: ["", "", ""],
            ocr_provider=lambda *_: "年度报告 封面 公司宣传图片",
            audit_sink=audit,
        )
        assert rows == []
        assert audit["final_status"] == "OCR_COMPLETED_NO_QUALIFIED_CANDIDATE"


def test_directory_hint_includes_image_statement_page_and_neighbors():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp); pdf = _image_pdf(root / "directory.pdf", 5)
        _, audit = conditional_ocr_primary_statements(
            pdf, native_pages=[
                "目录\n已审财务报表\n合并资产负债表\n2 - 3\n财务报表附注\n4 - 5",
                "", "", "", "",
            ],
            preferred_statement_type="BALANCE_SHEET", cache_root=root / "cache",
            ocr_provider=lambda _, page, __: OCR_STATEMENT if page == 3 else "图片",
        )
        assert 3 in audit["ocr_pages"]
        assert "DIRECTORY_REFERENCED_PAGE" in audit["ocr_page_reasons"]["3"]


def test_ocr_unavailable_is_explicit_and_does_not_crash():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp); pdf = _image_pdf(root / "unavailable.pdf")
        _, audit = conditional_ocr_primary_statements(
            pdf, native_pages=["", "", ""], preferred_statement_type="BALANCE_SHEET",
            cache_root=root / "cache",
            ocr_provider=lambda *_: (_ for _ in ()).throw(RuntimeError("OCR missing")),
        )
        assert audit["ocr_triggered"] is True
        assert audit["final_status"] == "NO_HIGH_CONFIDENCE_TEXT_OCR_NOT_AVAILABLE"
        assert audit["ocr_errors"]


def test_hybrid_page_is_classified_and_generates_no_duplicate_candidate():
    config = {"ocr_text_min_chars": 40, "ocr_image_area_threshold": 0.55}
    feature = classify_page(text="文字" * 30, image_count=1, largest_image_area_ratio=.8,
                            total_image_area_ratio=.8, config=config)
    assert feature["page_modality"] == "HYBRID"
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp); pdf = _image_pdf(root / "hybrid.pdf", 2); audit = {}
        rows = discover(
            pdf, root / "cache", display_name="金融投资",
            discovery_context={"preferred_statement_type": "BALANCE_SHEET", "core_candidates": ["债权投资"]},
            text_provider=lambda _: ["债权投资", ""],
            ocr_provider=lambda *_: OCR_STATEMENT,
            audit_sink=audit,
        )
        assert rows
        assert {row["discovery_mode"] for row in rows} == {"HYBRID_TEXT_OCR"}


def test_formal_statement_without_qualified_target_triggers_bounded_ocr():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp); pdf = _image_pdf(root / "wrong-target.pdf", 3); audit = {}
        native = """合并资产负债表
2023年12月31日 人民币元
资产
债权投资
负债
所有者权益
资产总计
负债合计"""
        rows = discover(
            pdf, root / "cache", display_name="金融投资",
            discovery_context={"preferred_statement_type": "BALANCE_SHEET", "core_candidates": ["债权投资"]},
            text_provider=lambda _: [native, "", ""],
            ocr_provider=lambda _, page, __: OCR_STATEMENT if page == 1 else "",
            audit_sink=audit,
        )
        assert audit["ocr_triggered"] is True
        assert audit["ocr_trigger_reason"] == "FORMAL_STATEMENT_FOUND_BUT_RESEARCH_TARGET_UNQUALIFIED"
        assert rows and {row["statement_pdf_page_index"] for row in rows} == {1}


def test_no_statement_returns_completed_no_qualified_candidate_not_not_found_claim():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp); pdf = _image_pdf(root / "none.pdf", 2); audit = {}
        discover(
            pdf, root / "cache", display_name="金融投资",
            discovery_context={"preferred_statement_type": "BALANCE_SHEET", "core_candidates": ["债权投资"]},
            text_provider=lambda _: ["", ""], ocr_provider=lambda *_: "无关页面",
            audit_sink=audit,
        )
        assert audit["final_status"] == "OCR_COMPLETED_NO_QUALIFIED_CANDIDATE"


def test_ocr_recovers_real_section_parent_and_header_row_note_references():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp); pdf = _image_pdf(root / "parent.pdf", 3); audit = {}
        rows = discover(
            pdf, root / "cache", display_name="金融投资",
            discovery_context={
                "preferred_statement_type": "BALANCE_SHEET",
                "require_note_reference": True,
                "core_candidates": ["交易性金融资产", "债权投资", "其他债权投资", "其他权益工具投资"],
            },
            text_provider=lambda _: ["", "", ""],
            ocr_provider=lambda _, page, __: OCR_FINANCIAL_INVESTMENT_PARENT if page == 2 else "封面图片",
            audit_sink=audit,
        )
        parent = next(row for row in rows if row["statement_item"] == "金融投资")
        assert parent["family_parent_recovery_status"] == "SOURCE_PARENT_RECOVERED"
        refs = {row["statement_item"]: row["note_reference_normalized"] for row in rows}
        assert refs["交易性金融资产"] == "附注七-10"
        assert refs["债权投资"] == "附注七-11"
        assert refs["其他债权投资"] == "附注七-12"
        assert refs["其他权益工具投资"] == "附注七-13"
        evidence = audit["qualified_target_page_reasons"]
        assert evidence[2] == "EXPLICIT_PARENT_WITH_CHILD_NOTE_CLUSTER"


def test_ocr_child_cluster_without_source_parent_is_explicitly_review_required():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp); pdf = _image_pdf(root / "children-only.pdf", 3); audit = {}
        rows = discover(
            pdf, root / "cache", display_name="金融投资",
            discovery_context={
                "preferred_statement_type": "BALANCE_SHEET",
                "require_note_reference": True,
                "core_candidates": ["交易性金融资产", "债权投资", "其他债权投资", "其他权益工具投资"],
            },
            text_provider=lambda _: ["", "", ""],
            ocr_provider=lambda _, page, __: OCR_FINANCIAL_INVESTMENT_CHILDREN_ONLY if page == 2 else "封面图片",
            audit_sink=audit,
        )
        assert rows
        assert all(row["statement_item"] != "金融投资" for row in rows)
        assert {row["family_parent_recovery_status"] for row in rows} == {
            "REVIEW_REQUIRED_OCR_PARENT_UNREADABLE"
        }
        assert audit["qualified_target_page_reasons"][2] == "INFERRED_PARENT_FROM_CHILD_CLUSTER"
