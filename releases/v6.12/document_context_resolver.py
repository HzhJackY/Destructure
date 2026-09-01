"""Financial-statement context inheritance with page-level provenance.

Annual reports commonly declare the amount unit once at the beginning of a
financial-statement/note section.  Table continuation pages must inherit that
context until a later explicit declaration overrides it.  This module records
the page that supplied every inherited fact; it never silently assumes 元.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

import fitz


_UNIT_PATTERNS = [
    re.compile(
        r"金额\s*单位\s*(?:均\s*)?"
        r"(?:为|以|：|:)\s*"
        r"(?:人民币\s*)?"
        r"(百万元|亿元|万元|千元|元)"
    ),
    re.compile(
        r"(?:除特别注明外[，,]?\s*)?"
        r"金额\s*(?:单位)?\s*(?:均\s*)?"
        r"(?:为|以)\s*"
        r"(?:人民币\s*)?"
        r"(百万元|亿元|万元|千元|元)"
        r"(?:列示)?"
    ),
]


@dataclass
class DocumentContext:
    unit: str | None = None
    currency: str | None = None
    statement_scope: str | None = None
    restated_flag: bool | None = None
    unit_source_page: int | None = None
    unit_source_text: str | None = None
    currency_source_page: int | None = None
    statement_scope_source_page: int | None = None
    restated_source_page: int | None = None
    declarations: list[dict[str, Any]] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "unit": self.unit,
            "currency": self.currency,
            "statement_scope": self.statement_scope,
            "restated_flag": self.restated_flag,
            "unit_source_page": self.unit_source_page,
            "unit_source_text": self.unit_source_text,
            "currency_source_page": self.currency_source_page,
            "statement_scope_source_page": self.statement_scope_source_page,
            "restated_source_page": self.restated_source_page,
            "context_source_page": self.unit_source_page,
            "declarations": self.declarations,
        }


class DocumentContextResolver:
    """Resolve financial statement context at a target PDF page.

    Each explicit declaration updates the running context.  The caller can use
    ``resolve`` repeatedly for continuation pages; the result is deterministic
    and carries per-property provenance.
    """

    def __init__(self, document: fitz.Document):
        self.document = document
        self._contexts: dict[int, DocumentContext] = {}

    @staticmethod
    def _scope(text: str) -> str | None:
        compact = re.sub(r"\s+", "", text)
        if "合并财务报表" in compact or "本集团" in compact:
            return "CONSOLIDATED"
        if "公司财务报表" in compact or "本公司" in compact:
            return "COMPANY"
        return None

    @staticmethod
    def _unit(text: str) -> tuple[str, str] | None:
        # Only document/header declarations count.  Searching an entire page
        # for “元” is unsafe because ordinary data prose can contain a monetary
        # amount (for example “人民币26百万元”).
        header = re.sub(r"\s+", "", "\n".join(text.splitlines()[:14]))
        best: re.Match[str] | None = None
        for pattern in _UNIT_PATTERNS:
            match = pattern.search(header)
            if match and (best is None or len(match.group(0)) > len(best.group(0))):
                best = match
        if best is None:
            return None
        return best.group(1), best.group(0)

    def resolve(self, page_no: int) -> DocumentContext:
        page_no = max(1, min(int(page_no), len(self.document)))
        if page_no in self._contexts:
            return self._contexts[page_no]

        context = DocumentContext()
        for index in range(page_no):
            text = self.document[index].get_text("text") or ""
            header_text = "\n".join(text.splitlines()[:14])
            source_page = index + 1
            unit_hit = self._unit(text)
            if unit_hit:
                unit, unit_source_text = unit_hit
                context.unit = unit
                context.currency = "CNY" if "人民币" in text or unit in {"元", "千元", "万元", "百万元", "亿元"} else context.currency
                context.unit_source_page = source_page
                context.unit_source_text = unit_source_text
                context.currency_source_page = source_page
                context.declarations.append({
                    "kind": "unit", "value": unit,
                    "source_page": source_page, "source_text": unit_source_text,
                })
            scope = self._scope(header_text)
            if scope:
                context.statement_scope = scope
                context.statement_scope_source_page = source_page
                context.declarations.append({"kind": "statement_scope", "value": scope, "source_page": source_page})
            # A page-level restatement declaration is context only when it is
            # explicit; ordinary discussion text mentioning 重述 must not reset it.
            if re.search(r"(?:比较数据|上年度|上年同期).{0,20}(?:已)?重述|已重述", header_text):
                context.restated_flag = True
                context.restated_source_page = source_page
                context.declarations.append({"kind": "restated_flag", "value": True, "source_page": source_page})
        self._contexts[page_no] = context
        return context
