from __future__ import annotations

import json
import threading
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import fitz

import fast_index
import conditional_statement_ocr as conditional_ocr_module
from version import APP_VERSION
import generic_discovery as generic_discovery_module
import generic_discovery_engine as discovery_engine_module
from fast_index import PageIndexRecord
from generic_discovery_engine import GenericDiscoveryService
from statement_note_navigation import TextIndexRecord


FAMILY = {
    "family_id": "financial_investment",
    "definition_version": "1.0",
    "display_name": "金融投资",
    "discovery_strategy": "STATEMENT_PARENT_TO_MULTI_NOTE",
    "payload": {
        "preferred_statement_types": ["BALANCE_SHEET"],
        "preferred_scope": "CONSOLIDATED",
    },
}
MEMBERS = [{
    "member_id": "debt_investment",
    "display_name": "债权投资",
    "payload": {"aliases": []},
}]


class _Definitions:
    def definition(self, _definition_id):
        return {"payload": {"table_families": ["financial_investment"]}}

    def families(self):
        return [FAMILY]

    def members(self, _family_id):
        return MEMBERS


def _blank_pdf(path: Path, pages: int = 3) -> Path:
    doc = fitz.open()
    for _ in range(pages):
        doc.new_page()
    doc.save(path)
    doc.close()
    return path


def _native_fast_record() -> PageIndexRecord:
    text = (
        "合并资产负债表\n2025年12月31日\n资产\n金融投资\n"
        "债权投资 10 100\n资产总计\n负债合计\n"
    )
    return PageIndexRecord(
        page=1,
        text=text,
        text_chars=len(text),
        source="native_text",
        ocr_used=False,
        ocr_error=None,
        ocr_rows=[],
        ocr_words=[],
    )


def test_research_definition_resolved_family_starts_native_only_and_never_requests_ocr(monkeypatch, tmp_path):
    fast_calls: list[dict] = []
    monkeypatch.setattr(
        discovery_engine_module,
        "build_fast_index",
        lambda *_args, **kwargs: (
            fast_calls.append(kwargs) or [_native_fast_record()],
            {"cache_hit": False, "ocr_pages": 0},
        ),
    )
    monkeypatch.setattr(
        discovery_engine_module,
        "statement_discover",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("conditional discovery must not run for a resolved native family")
        ),
    )

    class _Resolver:
        def resolve(self, **_kwargs):
            row = {
                "statement_item": "债权投资",
                "member_table": "debt_investment",
                "canonical_concept_id": "debt_investment",
                "evidence": {},
            }
            resolution = {
                "quality_status": "RESOLVED",
                "required_current_members": ["debt_investment"],
                "member_ids": ["debt_investment"],
            }
            return [row], [resolution]

    service = GenericDiscoveryService(_Definitions(), tmp_path / "cache")
    service.family_resolver = _Resolver()
    rows = service._statement_strategy(
        tmp_path / "not-opened.pdf", FAMILY, MEMBERS, "中国人寿", "2025", "ANNUAL_REPORT"
    )

    assert rows and rows[0]["member_table"] == "debt_investment"
    assert len(fast_calls) == 1
    assert fast_calls[0]["ocr_mode"] == "off"
    assert service.last_statement_discovery_audit["statement_index_source"] == "FAST_INDEX_NATIVE_ONLY"
    assert service.last_statement_discovery_audit["ocr_triggered"] is False


def test_research_definition_unresolved_family_reuses_native_index_for_conditional_discovery(monkeypatch, tmp_path):
    fast_calls: list[dict] = []
    captured: dict = {}
    monkeypatch.setattr(
        discovery_engine_module,
        "build_fast_index",
        lambda *_args, **kwargs: (
            fast_calls.append(kwargs) or [_native_fast_record()],
            {"cache_hit": False, "ocr_pages": 0},
        ),
    )

    def fake_statement_discover(*_args, **kwargs):
        captured.update(kwargs)
        return []

    monkeypatch.setattr(discovery_engine_module, "statement_discover", fake_statement_discover)

    class _Resolver:
        def resolve(self, **_kwargs):
            return [], []

        def resolve_discovered_rows(self, **_kwargs):
            return [], []

    service = GenericDiscoveryService(_Definitions(), tmp_path / "cache")
    service.family_resolver = _Resolver()
    assert service._statement_strategy(
        tmp_path / "not-opened.pdf", FAMILY, MEMBERS, "中国太保", "2025", "ANNUAL_REPORT"
    ) == []

    assert len(fast_calls) == 1
    assert fast_calls[0]["ocr_mode"] == "off"
    assert len(captured["prebuilt_index"]) == 1
    assert captured["prebuilt_index"][0].text == _native_fast_record().text


def test_generic_discovery_prebuilt_native_index_skips_adapter_and_ocr(monkeypatch, tmp_path):
    text = "合并资产负债表\n金融投资 10 100\n资产总计\n负债合计\n" + ("资产项目\n" * 30)
    prebuilt = [TextIndexRecord(1, text, "合并资产负债表", "", [])]
    monkeypatch.setattr(
        generic_discovery_module,
        "build_text_index",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("adapter must not rebuild")),
    )
    audit: dict = {}
    rows = generic_discovery_module.discover(
        tmp_path / "not-opened.pdf",
        tmp_path / "cache",
        display_name="金融投资",
        discovery_context={"preferred_statement_type": "BALANCE_SHEET"},
        prebuilt_index=prebuilt,
        ocr_provider=lambda *_args: (_ for _ in ()).throw(AssertionError("OCR must not run")),
        audit_sink=audit,
    )

    assert rows
    assert audit["native_index_reused"] is True
    assert audit["ocr_triggered"] is False


def test_audited_toc_candidate_supersedes_native_summary_and_keeps_geometry(monkeypatch, tmp_path):
    summary = _native_fast_record()
    toc_text = "目录\n审计报告 1-3\n已审财务报表\n合并资产负债表 4-5\n财务报表附注 20"
    native_records = [
        summary,
        PageIndexRecord(2, toc_text, len(toc_text), "native_text", False, None, [], []),
        *[
            PageIndexRecord(page, "", 0, "native_text", False, None, [], [])
            for page in range(3, 7)
        ],
    ]
    monkeypatch.setattr(
        discovery_engine_module,
        "build_fast_index",
        lambda *_args, **_kwargs: (native_records, {"cache_hit": False, "ocr_pages": 0}),
    )

    ocr_text = "合并资产负债表\n2025年12月31日\n金融投资\n债权投资 10 100\n资产总计\n负债合计"
    ocr_record = PageIndexRecord(
        6,
        ocr_text,
        len(ocr_text),
        "ocr",
        True,
        None,
        [["合并资产负债表"], ["债权投资", "10", "100"]],
        [(10.0, 10.0, 30.0, 20.0, "债权投资", 0, 0, 0)],
    )

    def fake_conditional(*_args, **kwargs):
        kwargs["record_sink"].append(ocr_record)
        return {"6": ocr_text}, {
            "ocr_triggered": True,
            "ocr_pages": [6],
            "ocr_page_count": 1,
            "directory_statement_hints": {
                "6": {"statement_title": "合并资产负债表"},
            },
            "final_status": "FOUND_HIGH_CONFIDENCE_OCR",
        }

    monkeypatch.setattr(
        generic_discovery_module,
        "conditional_ocr_primary_statements",
        fake_conditional,
    )

    class _Resolver:
        def resolve(self, **kwargs):
            ocr_pages = [record for record in kwargs["index"] if getattr(record, "ocr_used", False)]
            if not ocr_pages:
                return ([{"statement_item": "债权投资", "member_table": "debt_investment", "evidence": {}}], [{
                    "quality_status": "RESOLVED",
                    "statement_pdf_page_index": 1,
                }])
            assert ocr_pages[0].page_number == 6
            assert ocr_pages[0].ocr_rows
            assert ocr_pages[0].ocr_words
            return ([{"statement_item": "债权投资", "member_table": "debt_investment", "evidence": {}}], [{
                "quality_status": "RESOLVED",
                "statement_pdf_page_index": 6,
            }])

        def resolve_discovered_rows(self, **_kwargs):
            raise AssertionError("OCR-aware formal resolver should decide first")

    service = GenericDiscoveryService(_Definitions(), tmp_path / "cache")
    service.family_resolver = _Resolver()
    rows = service._statement_strategy(
        tmp_path / "not-opened.pdf", FAMILY, MEMBERS, "中国太保", "2025", "ANNUAL_REPORT"
    )

    assert rows
    audit = service.last_statement_discovery_audit
    assert audit["unresolved_audited_statement_hint_pages"] == [6]
    assert audit["statement_family_resolutions"][0]["statement_pdf_page_index"] == 6
    assert audit["ocr_triggered"] is True


def test_failed_fast_index_ocr_is_not_reported_as_ocr_output(monkeypatch, tmp_path):
    pdf = _blank_pdf(tmp_path / "failed.pdf", pages=3)
    formal = "合并资产负债表\n2025年12月31日\n资产\n资产总计\n负债合计"
    failed = PageIndexRecord(
        2, formal, len(formal), "native_text_ocr_failed", False,
        "RuntimeError: OCR unavailable", [], [],
    )
    monkeypatch.setattr(
        conditional_ocr_module,
        "build_fast_index",
        lambda *_args, **_kwargs: ([failed], {
            "cache_hit": False,
            "ocr_page_cache_hits": 0,
            "ocr_page_cache_misses": 1,
            "ocr_page_cache_hit_pages": [],
            "ocr_page_cache_namespace": "FAST_INDEX_SHARED_OCR_PAGE_CACHE",
        }),
    )

    sink = []
    output, audit = conditional_ocr_module.conditional_ocr_primary_statements(
        pdf,
        native_pages=["", formal, ""],
        preferred_statement_type="BALANCE_SHEET",
        cache_root=tmp_path / "cache",
        config={"force_ocr_due_unqualified_target": True},
        record_sink=sink,
    )

    assert output == {}
    assert sink == [failed]
    assert audit["ocr_errors"] == ["PAGE_2:RuntimeError: OCR unavailable"]
    assert audit["final_status"] == "NO_HIGH_CONFIDENCE_TEXT_OCR_NOT_AVAILABLE"


def test_audited_toc_hint_does_not_fill_budget_with_unrelated_image_pages():
    native_pages = [
        "",
        "目录\n审计报告 1-3\n已审财务报表\n合并资产负债表 4-5\n财务报表附注 20",
        "", "", "", "", "", "",
    ]
    features = [
        {"page": page, "page_modality": "IMAGE_DOMINANT", "text_char_count": 0}
        for page in range(1, 9)
    ]
    config = {
        **conditional_ocr_module.OCR_FALLBACK_CONFIG,
        "preferred_scope": "CONSOLIDATED",
    }

    selected, reasons = conditional_ocr_module._candidate_pages(
        features, native_pages, "BALANCE_SHEET", config
    )

    assert selected == [6, 5, 7]
    assert reasons[6] == ["DIRECTORY_REFERENCED_PAGE", "DIRECTORY_NEIGHBOR"]
    assert set(reasons) == {5, 6, 7}


def test_scanned_toc_expands_to_referenced_statement_in_same_fast_index_pipeline(monkeypatch, tmp_path):
    pdf = _blank_pdf(tmp_path / "scanned-toc.pdf", pages=8)
    real_candidate_pages = conditional_ocr_module._candidate_pages
    candidate_calls = 0

    def candidate_pages(features, native_pages, statement_type, config):
        nonlocal candidate_calls
        candidate_calls += 1
        if not any("目录" in text for text in native_pages):
            return [1], {1: ["IMAGE_DOMINANT"]}
        return real_candidate_pages(features, native_pages, statement_type, config)

    monkeypatch.setattr(conditional_ocr_module, "_candidate_pages", candidate_pages)
    toc_text = "目录\n审计报告 1-3\n已审财务报表\n合并资产负债表 4-5\n财务报表附注 20"
    statement_text = "合并资产负债表\n2025年12月31日\n金融投资\n债权投资\n资产总计\n负债合计"
    build_calls: list[set[int]] = []

    def fake_build(*_args, **kwargs):
        selected = set(kwargs["force_ocr_pages"])
        build_calls.append(selected)
        texts = {1: toc_text, 5: statement_text}
        records = [
            PageIndexRecord(
                page,
                texts.get(page, f"P{page}"),
                len(texts.get(page, f"P{page}")),
                "ocr",
                True,
                None,
                [[texts.get(page, f"P{page}")]],
                [(1.0, 1.0, 2.0, 2.0, texts.get(page, f"P{page}"), 0, 0, 0)],
            )
            for page in sorted(selected)
        ]
        return records, {
            "cache_hit": False,
            "ocr_page_cache_hits": 0,
            "ocr_page_cache_misses": len(selected),
            "ocr_page_cache_hit_pages": [],
            "ocr_page_cache_path": str(tmp_path / "page-cache.json"),
            "ocr_page_cache_namespace": "FAST_INDEX_SHARED_OCR_PAGE_CACHE",
        }

    monkeypatch.setattr(conditional_ocr_module, "build_fast_index", fake_build)
    sink = []
    output, audit = conditional_ocr_module.conditional_ocr_primary_statements(
        pdf,
        native_pages=[""] * 8,
        preferred_statement_type="BALANCE_SHEET",
        cache_root=tmp_path / "cache",
        record_sink=sink,
    )

    assert build_calls == [{1}, {4, 5, 6}]
    assert candidate_calls == 2
    assert output["1"] == toc_text
    assert output["5"] == statement_text
    assert audit["ocr_stage_count"] == 2
    assert audit["ocr_trigger_reason"] == "SCANNED_TOC_THEN_REFERENCED_STATEMENT"
    assert audit["ocr_page_count"] == 4
    assert audit["directory_statement_hints"]["5"]["scope"] == "CONSOLIDATED"
    assert any(record.page == 5 and record.ocr_words for record in sink)


def test_scanned_toc_expansion_keeps_budget_when_native_summary_forces_ocr(monkeypatch, tmp_path):
    pdf = _blank_pdf(tmp_path / "forced-scanned-toc.pdf", pages=20)
    real_candidate_pages = conditional_ocr_module._candidate_pages

    def candidate_pages(features, native_pages, statement_type, config):
        if not any("目录" in text for text in native_pages):
            return list(range(1, 13)), {
                page: ["IMAGE_DOMINANT"] for page in range(1, 13)
            }
        return real_candidate_pages(features, native_pages, statement_type, config)

    monkeypatch.setattr(conditional_ocr_module, "_candidate_pages", candidate_pages)
    toc_text = "目录\n审计报告 1-3\n已审财务报表\n合并资产负债表 10-11\n财务报表附注 20"
    statement_text = "合并资产负债表\n2025年12月31日\n金融投资\n债权投资\n资产总计\n负债合计"
    build_calls: list[set[int]] = []

    def fake_build(*_args, **kwargs):
        selected = set(kwargs["force_ocr_pages"])
        build_calls.append(selected)
        texts = {3: toc_text, 13: statement_text}
        records = [
            PageIndexRecord(
                page, texts.get(page, f"P{page}"), len(texts.get(page, f"P{page}")),
                "ocr", True, None, [[texts.get(page, f"P{page}")]],
                [(1.0, 1.0, 2.0, 2.0, texts.get(page, f"P{page}"), 0, 0, 0)],
            )
            for page in sorted(selected)
        ]
        return records, {
            "cache_hit": False,
            "ocr_page_cache_hits": 0,
            "ocr_page_cache_misses": len(selected),
            "ocr_page_cache_path": str(tmp_path / "page-cache.json"),
            "ocr_page_cache_namespace": "FAST_INDEX_SHARED_OCR_PAGE_CACHE",
        }

    monkeypatch.setattr(conditional_ocr_module, "build_fast_index", fake_build)
    native_summary = "合并资产负债表\n2025年12月31日\n金融投资\n债权投资\n资产总计\n负债合计"
    output, audit = conditional_ocr_module.conditional_ocr_primary_statements(
        pdf,
        native_pages=[native_summary, *([""] * 19)],
        preferred_statement_type="BALANCE_SHEET",
        cache_root=tmp_path / "cache",
        config={"force_ocr_due_unqualified_target": True},
    )

    assert build_calls == [set(range(1, 10)), {12, 13, 14}]
    assert output["13"] == statement_text
    assert audit["ocr_stage_count"] == 2
    assert audit["ocr_page_count"] == 12
    assert audit["ocr_scope_reserved_for_scanned_toc_expansion"] is True


def test_generic_discovery_preserves_conditional_ocr_unavailable_status(monkeypatch, tmp_path):
    prebuilt = [TextIndexRecord(1, "", "", "", tuple())]

    def failed_conditional(*_args, **_kwargs):
        return {}, {
            "ocr_triggered": True,
            "ocr_pages": [1],
            "ocr_page_count": 1,
            "ocr_errors": ["PAGE_1:RuntimeError: OCR unavailable"],
            "final_status": "NO_HIGH_CONFIDENCE_TEXT_OCR_NOT_AVAILABLE",
        }

    monkeypatch.setattr(
        generic_discovery_module,
        "conditional_ocr_primary_statements",
        failed_conditional,
    )
    audit = {}
    rows = generic_discovery_module.discover(
        tmp_path / "not-opened.pdf",
        tmp_path / "cache",
        display_name="金融投资",
        discovery_context={"preferred_statement_type": "BALANCE_SHEET"},
        prebuilt_index=prebuilt,
        audit_sink=audit,
    )

    assert rows == []
    assert audit["final_status"] == "NO_HIGH_CONFIDENCE_TEXT_OCR_NOT_AVAILABLE"
    assert audit["ocr_errors"]


def test_overlapping_selected_sets_reuse_fast_index_page_ocr_cache(monkeypatch, tmp_path):
    pdf = _blank_pdf(tmp_path / "overlap.pdf", pages=3)
    cache_root = tmp_path / "cache"
    calls: list[int] = []

    def fake_ocr(page, _language, _dpi):
        page_number = page.number + 1
        calls.append(page_number)
        return [(10, 10, 80, 30, f"第{page_number}页")]

    monkeypatch.setattr(fast_index, "_ocr_words_with_fallback", fake_ocr)
    first_records, first_meta = fast_index.build_fast_index(
        pdf, cache_root, ocr_mode="selected", force_ocr_pages={1, 2}
    )
    events: list[dict] = []
    second_records, second_meta = fast_index.build_fast_index(
        pdf,
        cache_root,
        ocr_mode="selected",
        force_ocr_pages={2, 3},
        progress_callback=events.append,
    )

    assert calls == [1, 2, 3]
    assert first_meta["ocr_page_cache_hits"] == 0
    assert first_meta["ocr_page_cache_misses"] == 2
    assert second_meta["ocr_page_cache_hits"] == 1
    assert second_meta["ocr_page_cache_misses"] == 1
    assert second_meta["ocr_page_cache_hit_pages"] == [2]
    assert second_meta["ocr_page_cache_miss_pages"] == [3]
    assert [event["page"] for event in events if event["event"] == "ocr_start"] == [3]
    assert [event["page"] for event in events if event["event"] == "ocr_page_cache_hit"] == [2]
    page_two_first = next(record for record in first_records if record.page == 2)
    page_two_second = next(record for record in second_records if record.page == 2)
    assert page_two_second.text == page_two_first.text
    assert page_two_second.ocr_rows == page_two_first.ocr_rows
    assert page_two_second.ocr_words == page_two_first.ocr_words
    assert first_meta["ocr_page_cache_path"] == second_meta["ocr_page_cache_path"]


def test_concurrent_overlapping_sets_merge_cache_and_ocr_each_page_once(monkeypatch, tmp_path):
    pdf = _blank_pdf(tmp_path / "concurrent.pdf", pages=3)
    cache_root = tmp_path / "cache"
    calls: list[int] = []
    calls_lock = threading.Lock()
    start_barrier = threading.Barrier(2)

    def fake_ocr(page, _language, _dpi):
        page_number = int(page.number) + 1
        with calls_lock:
            calls.append(page_number)
        time.sleep(0.05)
        return [(10.0, 10.0, 20.0, 20.0, f"P{page_number}", 0, 0, 0)]

    monkeypatch.setattr(fast_index, "_ocr_words_with_fallback", fake_ocr)

    def run(selected):
        start_barrier.wait()
        return fast_index.build_fast_index(
            pdf,
            cache_root,
            ocr_mode="selected",
            force_ocr_pages=set(selected),
        )[1]

    with ThreadPoolExecutor(max_workers=2) as executor:
        first_future = executor.submit(run, {1, 2})
        second_future = executor.submit(run, {2, 3})
        metas = [first_future.result(), second_future.result()]

    assert Counter(calls) == Counter({1: 1, 2: 1, 3: 1})
    assert sum(meta["ocr_page_cache_hits"] for meta in metas) == 1
    assert sum(meta["ocr_page_cache_misses"] for meta in metas) == 3
    assert len({meta["ocr_page_cache_path"] for meta in metas}) == 1
    cache_path = Path(metas[0]["ocr_page_cache_path"])
    payload = json.loads(cache_path.read_text(encoding="utf-8"))
    assert set(payload["pages"]) == {"1", "2", "3"}
    assert not cache_path.with_suffix(cache_path.suffix + ".lock").exists()


def test_force_rebuild_bypasses_page_ocr_cache(monkeypatch, tmp_path):
    pdf = _blank_pdf(tmp_path / "force.pdf", pages=2)
    cache_root = tmp_path / "cache"
    calls: list[int] = []

    def fake_ocr(page, _language, _dpi):
        calls.append(page.number + 1)
        return [(10, 10, 80, 30, "资产负债表")]

    monkeypatch.setattr(fast_index, "_ocr_words_with_fallback", fake_ocr)
    fast_index.build_fast_index(pdf, cache_root, ocr_mode="selected", force_ocr_pages={1})
    _, rebuilt_meta = fast_index.build_fast_index(
        pdf,
        cache_root,
        ocr_mode="selected",
        force_ocr_pages={1},
        force_rebuild=True,
    )

    assert calls == [1, 1]
    assert rebuilt_meta["ocr_page_cache_hits"] == 0
    assert rebuilt_meta["ocr_page_cache_misses"] == 1


def test_v6121_release_identity_is_authoritative():
    assert APP_VERSION in ("v6.12.1", "v6.13")


def test_full_index_cache_key_includes_native_text_threshold():
    base = dict(
        ocr_mode="auto",
        language="chi_sim+eng",
        dpi=400,
        ocr_quality_threshold=0.5,
        force_ocr_pages=set(),
    )
    assert fast_index.cache_key(**base, min_native_chars=40) != fast_index.cache_key(
        **base,
        min_native_chars=80,
    )
