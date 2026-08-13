from __future__ import annotations

import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from merge_order_controls_ui import (  # noqa: E402
    NOTE_ORDINAL_ORDER_POLICY,
    render_merge_order_controls,
)
from merge_asset_picker_ui import merge_asset_label  # noqa: E402


RECORDS = [
    {
        "capture_id": "CAP_MAIN",
        "company": "中国人寿",
        "document_year": "2025",
        "member_table_display": "其他权益工具投资",
        "classification_axis": "ASSET_TYPE",
    },
    {
        "capture_id": "CAP_B2",
        "company": "中国人寿",
        "document_year": "2025",
        "member_table_display": "其他权益工具投资",
        "classification_axis": "MEASUREMENT_COMPOSITION",
    },
    {
        "capture_id": "CAP_B3",
        "company": "中国人寿",
        "document_year": "2025",
        "member_table_display": "其他权益工具投资",
        "classification_axis": "LISTING_STATUS",
    },
]


class FakeStreamlit:
    def __init__(self, policy: str, *, session_state=None):
        self.policy = policy
        self.session_state = session_state if session_state is not None else {}
        self.calls: list[tuple[str, str]] = []
        self.warnings: list[str] = []

    def radio(self, label, options, **kwargs):
        self.calls.append(("radio", label))
        return self.policy

    def selectbox(self, label, options, index=0, **kwargs):
        self.calls.append(("selectbox", label))
        value = list(options)[index]
        key = kwargs.get("key")
        if key and self.session_state.get(key) in options:
            value = self.session_state[key]
        if key:
            self.session_state[key] = value
        return value

    def warning(self, message):
        self.warnings.append(str(message))

    def caption(self, message):
        self.calls.append(("caption", str(message)))


def _control_labels(fake: FakeStreamlit) -> list[str]:
    return [label for kind, label in fake.calls if kind in {"radio", "selectbox"}]


def test_reference_policy_renders_strategy_first_then_reference_capture_only():
    fake = FakeStreamlit(
        "排序基准表（默认）",
        session_state={"merge_reference_capture": "STALE_LABEL"},
    )
    selection = render_merge_order_controls(fake, RECORDS, ["2025", "2024"])

    assert _control_labels(fake) == ["合表排序策略", "排序基准表（非常重要）"]
    assert selection.reference_capture_run_id == "CAP_MAIN"
    assert selection.order_policy is None
    assert selection.reference_report_year == ""
    assert fake.session_state["merge_reference_capture"] != "STALE_LABEL"


def test_note_ordinal_policy_renders_reference_year_only_and_keeps_capture_fallback():
    fake = FakeStreamlit("按年份附注号排序")
    selection = render_merge_order_controls(fake, RECORDS, ["2024", "2025", "2025"])

    assert _control_labels(fake) == ["合表排序策略", "基准年份（按该年附注号排序）"]
    assert selection.reference_capture_run_id == "CAP_MAIN"
    assert selection.order_policy == NOTE_ORDINAL_ORDER_POLICY
    assert selection.reference_report_year == "2025"
    assert all(label != "排序基准表（非常重要）" for label in _control_labels(fake))


def test_note_ordinal_without_years_falls_back_without_empty_reference_capture():
    fake = FakeStreamlit("按年份附注号排序")
    selection = render_merge_order_controls(fake, RECORDS, [None, "", "nan"])

    assert _control_labels(fake) == ["合表排序策略"]
    assert selection.reference_capture_run_id == "CAP_MAIN"
    assert selection.order_policy is None
    assert selection.reference_report_year == ""
    assert fake.warnings


def test_reference_choice_survives_reference_note_reference_reruns():
    session_state = {
        "merge_reference_capture": merge_asset_label(RECORDS[1]),
    }

    first = render_merge_order_controls(
        FakeStreamlit("排序基准表（默认）", session_state=session_state),
        RECORDS,
        ["2025"],
    )
    note = render_merge_order_controls(
        FakeStreamlit("按年份附注号排序", session_state=session_state),
        RECORDS,
        ["2025"],
    )
    returned = render_merge_order_controls(
        FakeStreamlit("排序基准表（默认）", session_state=session_state),
        RECORDS,
        ["2025"],
    )

    assert first.reference_capture_run_id == "CAP_B2"
    assert note.reference_capture_run_id == "CAP_MAIN"
    assert note.order_policy == NOTE_ORDINAL_ORDER_POLICY
    assert returned.reference_capture_run_id == "CAP_B2"
