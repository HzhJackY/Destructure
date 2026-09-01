"""Stable v6.8 review reason registry."""
from __future__ import annotations

from enum import Enum


class ReviewReason(str, Enum):
    BOUNDARY_LOW_CONFIDENCE = "BOUNDARY_LOW_CONFIDENCE"
    HEADER_AMBIGUOUS = "HEADER_AMBIGUOUS"
    ROW_STRUCTURE_AMBIGUOUS = "ROW_STRUCTURE_AMBIGUOUS"
    UNIT_UNCERTAIN = "UNIT_UNCERTAIN"
    SCOPE_UNCERTAIN = "SCOPE_UNCERTAIN"
    RESTATEMENT_UNCERTAIN = "RESTATEMENT_UNCERTAIN"
    SOURCE_IDENTITY_MISSING = "SOURCE_IDENTITY_MISSING"
    RECONCILIATION_WARNING = "RECONCILIATION_WARNING"
    IMPLICIT_TOTAL_UNCERTIFIED = "IMPLICIT_TOTAL_UNCERTIFIED"
    MIXED_CELL = "MIXED_CELL"
    MULTIPLE_HIGH_SCORE_TARGETS = "MULTIPLE_HIGH_SCORE_TARGETS"
    UNSUPPORTED_LAYOUT = "UNSUPPORTED_LAYOUT"
    MANUAL_OVERRIDE_REQUIRED = "MANUAL_OVERRIDE_REQUIRED"


def normalize_review_reason(raw: str) -> str:
    token = str(raw or "").upper()
    if token.startswith("BOUNDARY:") or "BOUNDARY" in token: return ReviewReason.BOUNDARY_LOW_CONFIDENCE.value
    if token.startswith("HEADER:") or "HEADER" in token: return ReviewReason.HEADER_AMBIGUOUS.value
    if "STRUCTURE" in token or "ROW_" in token: return ReviewReason.ROW_STRUCTURE_AMBIGUOUS.value
    if token.startswith("MIXED_CELL:"): return ReviewReason.MIXED_CELL.value
    if token.startswith("IMPLICIT_ROW_UNRESOLVED:"): return ReviewReason.IMPLICIT_TOTAL_UNCERTIFIED.value
    if "UNIT" in token: return ReviewReason.UNIT_UNCERTAIN.value
    if "SOURCE" in token or "IDENTITY" in token: return ReviewReason.SOURCE_IDENTITY_MISSING.value
    if "RECONCILIATION" in token: return ReviewReason.RECONCILIATION_WARNING.value
    return token if token in {x.value for x in ReviewReason} else ReviewReason.ROW_STRUCTURE_AMBIGUOUS.value
