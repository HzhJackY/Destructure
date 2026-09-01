"""DocumentContextResolver 单位声明解析回归测试。

覆盖中国太保“金额单位均为人民币X”写法（含“均”与空格拆分），
并验证 CaptureDecisionReducer 的 UNIT_UNCERTAIN 门禁不再误报、
同时真正无单位的证据仍被阻塞。
"""
from __future__ import annotations

import os
from pathlib import Path
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from document_context_resolver import DocumentContextResolver


# ---------------------------------------------------------------------------
# Layer 1: 正则单元测试
# ---------------------------------------------------------------------------

POSITIVE_CASES = [
    ("金额单位为人民币百万元", "百万元"),
    ("金额单位均为人民币千元", "千元"),
    ("金额单位：人民币元", "元"),
    ("金额均以人民币万元列示", "万元"),
    ("除特别注明外，金额单位均为人民币千元", "千元"),
    ("金额 单位 均为 人民币千元", "千元"),  # 原生文本/OCR 空格拆分
]

NEGATIVE_CASES = [
    "金额",
    "单位",
    "本表单位为人民币元",
    "金额以美元列示",
    "人民币86.282亿元",
    "总额不超过人民币13.70亿元。",
    "上述金额以审计报告为准",
    "（除特别注明外，本报表以人民币列示）",
]


@pytest.mark.parametrize("text,expected", POSITIVE_CASES)
def test_unit_regex_positive(text: str, expected: str) -> None:
    hit = DocumentContextResolver._unit(text)
    assert hit is not None
    unit, source_text = hit
    assert unit == expected
    assert expected in source_text  # 保留原始命中文本，便于审计


@pytest.mark.parametrize("text", NEGATIVE_CASES)
def test_unit_regex_negative(text: str) -> None:
    assert DocumentContextResolver._unit(text) is None


# ---------------------------------------------------------------------------
# Layer 2: 文档上下文集成测试（中国太保 2023 年报 PDF 第 169 页真实页头 fixture）
# ---------------------------------------------------------------------------

CPIC_2023_P169_HEADER = "\n".join([
    " ",
    " ",
    "中国太平洋人寿保险股份有限公司 ",
    "财务报表附注（续） ",
    "2023年度 ",
    "（除特别注明外，金额单位均为人民币千元） ",
    " ",
    "99 ",
    " ",
    "七、 ",
    "合并财务报表主要项目注释（续） ",
    " ",
    "9. ",
    "归入贷款及应收款的投资（仅适用2022年） ",
])


class _FakePage:
    def __init__(self, text: str) -> None:
        self._text = text

    def get_text(self, kind: str = "text") -> str:
        return self._text if kind == "text" else ""


class _FakeDocument:
    def __init__(self, pages: dict[int, str], total: int = 200) -> None:
        self._pages = pages
        self._total = total

    def __len__(self) -> int:
        return self._total

    def __getitem__(self, index: int) -> _FakePage:
        return _FakePage(self._pages.get(index, ""))


def test_cpic_2023_p169_context_inherits_unit_with_source_text() -> None:
    doc = _FakeDocument({168: CPIC_2023_P169_HEADER})
    ctx = DocumentContextResolver(doc).resolve(169)

    assert ctx.unit == "千元"
    assert ctx.currency == "CNY"
    assert ctx.unit_source_page == 169
    assert ctx.unit_source_text == "除特别注明外，金额单位均为人民币千元"
    assert ctx.statement_scope == "CONSOLIDATED"

    data = ctx.as_dict()
    assert data["unit"] == "千元"
    assert data["unit_source_page"] == 169
    assert data["unit_source_text"] == "除特别注明外，金额单位均为人民币千元"
    unit_decl = next(d for d in data["declarations"] if d["kind"] == "unit")
    assert unit_decl["source_page"] == 169
    assert unit_decl["source_text"] == "除特别注明外，金额单位均为人民币千元"


# ---------------------------------------------------------------------------
# Layer 3: 决策门禁回归测试（CaptureDecisionReducer 只读校验）
# ---------------------------------------------------------------------------


def _reduce(evidence: dict) -> object:
    from services.capture_decision_reducer import CaptureDecisionReducer

    return CaptureDecisionReducer().reduce(
        machine_evidence=evidence,
        capture_version={},
        lifecycle_state={},
        rule_version="v6.11-test",
    )


def test_unit_uncertain_no_longer_blocks_when_context_unit_resolved() -> None:
    doc = _FakeDocument({168: CPIC_2023_P169_HEADER})
    ctx = DocumentContextResolver(doc).resolve(169)
    evidence = {
        "unit": ctx.unit,
        "document_context": ctx.as_dict(),
        "rows": [],
        "columns": [],
        "stats": {},
    }
    decision = _reduce(evidence)
    assert "UNIT_UNCERTAIN" not in decision.blocking_issues


def test_unit_uncertain_still_blocks_without_any_unit_evidence() -> None:
    # 模拟修复前真实机器证据形态：unit 与 document_context.currency_unit 均缺失
    evidence = {
        "unit": None,
        "document_context": {
            "unit": None,
            "currency": None,
            "statement_scope": "CONSOLIDATED",
            "unit_source_page": None,
        },
        "rows": [],
        "columns": [],
        "stats": {},
    }
    decision = _reduce(evidence)
    assert "UNIT_UNCERTAIN" in decision.blocking_issues


def test_unit_uncertain_still_blocks_for_empty_evidence() -> None:
    decision = _reduce({})
    assert "UNIT_UNCERTAIN" in decision.blocking_issues


# ---------------------------------------------------------------------------
# 真实 PDF Canary：太保 2023 第 169 页（PDF 不可用时跳过）
# ---------------------------------------------------------------------------


def _cpic_2023_pdf_candidates() -> list[Path]:
    candidates: list[Path] = []
    env_home = os.environ.get("FIN_METRIC_DATA_HOME")
    if env_home:
        candidates.append(
            Path(env_home)
            / "uploads"
            / "9440391625bd_中国太保2023年报.pdf"
        )
    candidates.append(
        Path(r"C:\Users\HzhJa\FinancialMetricResolverData\uploads\9440391625bd_中国太保2023年报.pdf")
    )
    return [p for p in candidates if p.is_file()]


def test_real_pdf_cpic_2023_page_169_unit_canary() -> None:
    pdfs = _cpic_2023_pdf_candidates()
    if not pdfs:
        pytest.skip("中国太保2023年报 PDF 未找到，跳过真实 PDF Canary")

    import fitz

    doc = fitz.open(str(pdfs[0]))
    try:
        text = doc[168].get_text("text") or ""
        actual = "\n".join(text.splitlines()[:14])
        assert actual == CPIC_2023_P169_HEADER  # fixture 防漂移
        ctx = DocumentContextResolver(doc).resolve(169)
        assert ctx.unit == "千元"
        assert ctx.unit_source_page == 169
        assert ctx.unit_source_text == "除特别注明外，金额单位均为人民币千元"
    finally:
        doc.close()


def test_real_pdf_cpic_2023_asset_no_longer_unit_blocked() -> None:
    pdfs = _cpic_2023_pdf_candidates()
    if not pdfs:
        pytest.skip("中国太保2023年报 PDF 未找到，跳过真实 PDF Canary")

    import fitz

    doc = fitz.open(str(pdfs[0]))
    try:
        ctx = DocumentContextResolver(doc).resolve(169)
        evidence = {
            "unit": ctx.unit,
            "document_context": ctx.as_dict(),
            "rows": [],
            "columns": [],
            "stats": {},
        }
        decision = _reduce(evidence)
        assert "UNIT_UNCERTAIN" not in decision.blocking_issues
    finally:
        doc.close()
