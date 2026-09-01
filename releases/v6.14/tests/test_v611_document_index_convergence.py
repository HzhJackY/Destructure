"""Focused compatibility tests for the unified production document index."""
from __future__ import annotations

from pathlib import Path

import fitz

import conditional_statement_ocr as conditional
import fast_index
from fast_index import PageIndexRecord
from statement_note_navigation import build_text_index


def _blank_pdf(path: Path, pages: int = 2) -> Path:
    doc = fitz.open()
    for _ in range(pages):
        doc.new_page()
    doc.save(path)
    doc.close()
    return path


def test_build_text_index_is_a_fast_index_semantic_adapter(monkeypatch, tmp_path):
    source = _blank_pdf(tmp_path / "source.pdf")
    calls = []

    def fake_fast(pdf_path, cache_root, **kwargs):
        calls.append((Path(pdf_path), Path(cache_root), kwargs))
        return [PageIndexRecord(
            page=1, text="附注七\n债权投资", text_chars=8, source="ocr",
            ocr_used=True, ocr_error=None, ocr_rows=[["债权投资"]],
            ocr_words=[(1, 1, 20, 10, "债权投资")],
        )], {"cache_hit": False}

    monkeypatch.setattr(fast_index, "build_fast_index", fake_fast)
    index = build_text_index(source, tmp_path / "cache")

    assert len(calls) == 1
    assert calls[0][2]["ocr_mode"] == "auto"
    assert index[0].page_number == 1
    assert index[0].ocr_used is True
    assert index[0].ocr_words


def test_conditional_policy_delegates_production_ocr_to_fast_index(monkeypatch, tmp_path):
    source = _blank_pdf(tmp_path / "source.pdf")
    calls = []

    def fake_candidates(features, native_pages, statement_type, config):
        return [1], {1: ["TEST_BOUNDED_PAGE"]}

    def fake_fast(pdf_path, cache_root, **kwargs):
        calls.append(kwargs)
        return [PageIndexRecord(
            page=1, text="合并资产负债表\n资产总计\n负债合计", text_chars=15,
            source="ocr", ocr_used=True, ocr_error=None, ocr_rows=[],
        )], {"cache_hit": False}

    monkeypatch.setattr(conditional, "_candidate_pages", fake_candidates)
    monkeypatch.setattr(conditional, "build_fast_index", fake_fast)
    output, audit = conditional.conditional_ocr_primary_statements(
        source, native_pages=["", ""], preferred_statement_type="BALANCE_SHEET",
        cache_root=tmp_path / "cache",
    )

    assert calls == [{
        "ocr_mode": "selected", "ocr_language": "chi_sim+eng", "ocr_dpi": 400,
        "ocr_psm": 4,
        "ocr_quality_threshold": 0.5, "min_native_chars": 40,
        "force_ocr_pages": {1},
    }]
    assert output["1"].startswith("合并资产负债表")
    assert audit["ocr_cache_namespace"] == "FAST_INDEX_SHARED_OCR_PAGE_CACHE"
