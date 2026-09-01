from __future__ import annotations

import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from presentation_labels import (  # noqa: E402
    CLASSIFICATION_LABELS,
    classification_key,
    classification_label,
)


def test_stage_b_classification_labels_are_complete_and_stable():
    expected = {
        "STATEMENT_ANCHOR": "财务主报表锚点",
        "ANCHOR_PARENT_LINE": "金融投资锚点行",
        "PRIMARY_TABLE": "附注主明细表",
        "CONTINUATION_SEGMENT": "附注分页续段",
        "SUPPLEMENTARY_TABLE": "附注补充分析表",
        "PEER_TABLE": "下一同级附注表",
        "UNRESOLVED": "待判定附注表段",
    }
    assert CLASSIFICATION_LABELS == expected


def test_stage_b_display_labels_round_trip_to_persisted_tokens():
    for token, label in CLASSIFICATION_LABELS.items():
        assert classification_label(token) == label
        assert classification_key(label) == token


def test_unknown_classification_is_not_silently_dropped():
    assert classification_label("NEW_ROLE") == "NEW_ROLE"
    assert classification_key("new_role") == "NEW_ROLE"
