"""Regression: production document-index entry points share the 400 DPI profile."""
from __future__ import annotations

import conditional_statement_ocr as conditional
import fast_index
import generic_discovery_engine
import run_12_filing_matrix
import fitz
from document_index_profile import (
    CERTIFIED_DOCUMENT_INDEX_PROFILE_VERSION,
    fast_index_profile_kwargs,
)
from statement_note_navigation import build_text_index


def test_profile_is_the_certified_400_dpi_single_source():
    assert CERTIFIED_DOCUMENT_INDEX_PROFILE_VERSION == "FINANCIAL_TABLE_400DPI_V1"
    assert fast_index_profile_kwargs()["ocr_dpi"] == 400
    assert fast_index.build_fast_index.__kwdefaults__["ocr_dpi"] == 400


def test_text_adapter_forwards_complete_profile(monkeypatch, tmp_path):
    calls = []
    monkeypatch.setattr(
        fast_index,
        "build_fast_index",
        lambda *args, **kwargs: (calls.append(kwargs) or [], {}),
    )
    build_text_index(tmp_path / "stub.pdf", tmp_path / "cache")
    assert len(calls) == 1
    assert {k: calls[0][k] for k in fast_index_profile_kwargs()} == fast_index_profile_kwargs()


def test_conditional_production_path_uses_shared_profile(monkeypatch, tmp_path):
    calls = []
    monkeypatch.setattr(conditional, "_candidate_pages", lambda *args: ([1], {1: ["TEST"]}))
    monkeypatch.setattr(
        conditional,
        "build_fast_index",
        lambda *args, **kwargs: (calls.append(kwargs) or [], {"ocr_pages": 0}),
    )
    source = tmp_path / "stub.pdf"
    doc = fitz.open(); doc.new_page(); doc.new_page(); doc.save(source); doc.close()
    conditional.conditional_ocr_primary_statements(
        source, native_pages=["", ""], preferred_statement_type="BALANCE_SHEET", cache_root=tmp_path / "cache"
    )
    assert len(calls) == 1
    assert calls[0] == fast_index_profile_kwargs(ocr_mode="selected", force_ocr_pages={1})


def test_offline_and_gui_entrypoints_reference_profile_helper():
    assert run_12_filing_matrix.fast_index_profile_kwargs is fast_index_profile_kwargs
    assert generic_discovery_engine.build_fast_index is fast_index.build_fast_index
