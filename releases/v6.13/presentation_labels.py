"""Stable Chinese labels for internal Stage B classification values.

The values in this module are presentation-only. Persisted classifications,
database values, and service contracts continue to use the English enum
tokens defined by the discovery and capture layers.
"""
from __future__ import annotations

from typing import Any


CLASSIFICATION_LABELS: dict[str, str] = {
    "STATEMENT_ANCHOR": "财务主报表锚点",
    "ANCHOR_PARENT_LINE": "金融投资锚点行",
    "PRIMARY_TABLE": "附注主明细表",
    "CONTINUATION_SEGMENT": "附注分页续段",
    "SUPPLEMENTARY_TABLE": "附注补充分析表",
    "PEER_TABLE": "下一同级附注表",
    "UNRESOLVED": "待判定附注表段",
}


LOGICAL_TABLE_ROLE_OPTIONS: tuple[str, ...] = (
    "UNRESOLVED",
    "PRIMARY_TABLE",
    "SUPPLEMENTARY_TABLE",
)


def classification_label(value: Any) -> str:
    """Return a user-facing label while preserving unknown values visibly."""
    if value is None or value == "":
        key = "UNRESOLVED"
    else:
        key = str(value).upper()
    return CLASSIFICATION_LABELS.get(
        key,
        str(value) if value is not None else "待判定附注表段",
    )


def classification_key(label: Any) -> str:
    """Convert a displayed label back to its persisted enum token."""
    text = "" if label is None else str(label)
    for key, display in CLASSIFICATION_LABELS.items():
        if text == display:
            return key
    return text.upper()


def logical_table_role_label(value: Any) -> str:
    """Render a logical-table role using the shared presentation vocabulary."""
    return classification_label(value)
