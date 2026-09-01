"""Shared semantic boundary recognition for direct investment portfolios.

This module is deliberately pure and contains no PDF, Registry or Capture I/O.
Discovery and post-Capture logical segmentation must use the same vocabulary
and boundary grammar so a reviewed axis cannot change meaning at runtime.
"""
from __future__ import annotations

import re
from dataclasses import dataclass


BY_INVESTMENT_OBJECT = "BY_INVESTMENT_OBJECT"
BY_ACCOUNTING_MEASUREMENT = "BY_ACCOUNTING_MEASUREMENT"
UNRESOLVED_AXIS_BOUNDARY = "UNRESOLVED_AXIS_BOUNDARY"

_OBJECT_TERMS = (
    "投资资产类别",
    "投资对象",
    "投资品种",
    "投资种类",
    "投资类别",
    "资产类别",
)
_MEASUREMENT_TERMS = (
    "会计核算方法",
    "会计计量",
    "计量方式",
    "计量方法",
    "计量属性",
    "核算方法",
)
_BOUNDARY_SUFFIXES = ("分类", "划分", "列示", "构成", "分")


def compact_axis_text(value: str) -> str:
    return re.sub(r"\s+", "", str(value or "")).strip("：:")


@dataclass(frozen=True)
class AxisBoundary:
    is_boundary: bool
    classification_axis: str | None
    matched_prefix: str
    semantic_term: str
    unresolved: bool = False


def recognise_portfolio_axis_boundary(value: str) -> AxisBoundary:
    """Recognise a leading ``按...`` boundary and resolve its semantic axis.

    A syntactically valid but unknown boundary is retained as unresolved.  It
    is never coerced to the closest known investment axis.
    """
    compact = compact_axis_text(value)
    if not compact.startswith("按"):
        return AxisBoundary(False, None, "", "")

    best: tuple[str, str, str] | None = None
    for term in (*_OBJECT_TERMS, *_MEASUREMENT_TERMS):
        for suffix in _BOUNDARY_SUFFIXES:
            prefix = f"按{term}{suffix}"
            if compact.startswith(prefix):
                candidate = (prefix, term, suffix)
                if best is None or len(prefix) > len(best[0]):
                    best = candidate
    if best is not None:
        prefix, term, _ = best
        axis = (
            BY_INVESTMENT_OBJECT
            if term in _OBJECT_TERMS
            else BY_ACCOUNTING_MEASUREMENT
        )
        return AxisBoundary(True, axis, prefix, term)

    generic = re.match(r"^(按.{1,24}?(?:分类|划分|列示|构成|分))", compact)
    if generic:
        return AxisBoundary(
            True,
            UNRESOLVED_AXIS_BOUNDARY,
            generic.group(1),
            "",
            unresolved=True,
        )
    return AxisBoundary(False, None, "", "")


def portfolio_axes_in_text(value: str) -> list[str]:
    """Return distinct known axes disclosed anywhere in native page text."""
    compact = compact_axis_text(value)
    axes: list[str] = []
    for term, axis in (
        *((term, BY_INVESTMENT_OBJECT) for term in _OBJECT_TERMS),
        *((term, BY_ACCOUNTING_MEASUREMENT) for term in _MEASUREMENT_TERMS),
    ):
        # Some insurers use a compact parenthesised title such as
        # ``投资组合（按投资品种）`` without repeating ``分类/分``.  The
        # closing bracket is the structural boundary in that form; it is
        # still constrained by a known semantic term and cannot resolve an
        # arbitrary ``按...`` phrase.
        if any(
            f"按{term}{suffix}" in compact
            for suffix in _BOUNDARY_SUFFIXES
        ) or f"按{term}）" in compact or f"按{term})" in compact:
            if axis not in axes:
                axes.append(axis)
    return axes


def strip_recognised_axis_prefix(value: str, expected_axis: str) -> tuple[str, str]:
    """Strip only a certified known heading prefix from a glued data label."""
    boundary = recognise_portfolio_axis_boundary(value)
    if boundary.classification_axis != str(expected_axis or "").upper():
        return str(value or ""), ""
    compact = compact_axis_text(value)
    remainder = compact[len(boundary.matched_prefix):]
    return remainder, boundary.matched_prefix
