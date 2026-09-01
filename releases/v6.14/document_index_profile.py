"""唯一的生产文档索引 / OCR 配置来源。"""
from __future__ import annotations

from typing import Any


CERTIFIED_DOCUMENT_INDEX_PROFILE_VERSION = "FINANCIAL_TABLE_400DPI_V1"

CERTIFIED_DOCUMENT_INDEX_PROFILE: dict[str, Any] = {
    "profile_version": CERTIFIED_DOCUMENT_INDEX_PROFILE_VERSION,
    "ocr_language": "chi_sim+eng",
    "ocr_dpi": 400,
    "ocr_psm": 4,
    "ocr_quality_threshold": 0.5,
    "min_native_chars": 40,
}


def fast_index_profile_kwargs(
    *,
    ocr_mode: str = "auto",
    force_ocr_pages: set[int] | None = None,
    ocr_psm: int | None = None,
) -> dict[str, Any]:
    """Return the complete Fast Index configuration for a production call."""
    return {
        "ocr_mode": ocr_mode,
        "ocr_language": CERTIFIED_DOCUMENT_INDEX_PROFILE["ocr_language"],
        "ocr_dpi": CERTIFIED_DOCUMENT_INDEX_PROFILE["ocr_dpi"],
        "ocr_psm": int(
            CERTIFIED_DOCUMENT_INDEX_PROFILE["ocr_psm"]
            if ocr_psm is None else ocr_psm
        ),
        "ocr_quality_threshold": CERTIFIED_DOCUMENT_INDEX_PROFILE["ocr_quality_threshold"],
        "min_native_chars": CERTIFIED_DOCUMENT_INDEX_PROFILE["min_native_chars"],
        "force_ocr_pages": set(force_ocr_pages or set()),
    }
