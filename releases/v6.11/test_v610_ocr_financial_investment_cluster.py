from generic_discovery import _extract_tail_reference, _qualified_target_pages
from statement_note_navigation import TextIndexRecord


def test_header_row_note_composition_rejects_amount_prefixes():
    note = _extract_tail_reference("债权投资 10 1,270,569", "债权投资", "附注八")
    assert note["note_reference_normalized"] == "附注八-10"
    # A monetary value is never an implicit statement-note ordinal.
    amount = _extract_tail_reference("债权投资 1,270,569", "债权投资", "附注八")
    assert not amount["note_reference_normalized"]


def test_explicit_parent_requires_header_and_two_distinct_core_children():
    record = TextIndexRecord(
        12,
        "合并资产负债表\n资产 附注七 2023年\n金融投资：\n交易性金融资产 10 484,418\n债权投资 11 5,567,857\n其他债权投资 12 1,186,531,148",
        "合并资产负债表", "", [],
    )
    pages, reasons = _qualified_target_pages(
        [record], {"BALANCE_SHEET": [12]}, ["BALANCE_SHEET"], "金融投资",
        "CONSOLIDATED", True, ["交易性金融资产", "债权投资", "其他债权投资", "其他权益工具投资"],
    )
    assert pages == {12}
    assert reasons[12] == "EXPLICIT_PARENT_WITH_CHILD_NOTE_CLUSTER"
    evidence = _qualified_target_pages.last_evidence[12]
    assert evidence["parent_inferred"] is False
    assert evidence["note_header"] == "附注七"
    assert {row["note_reference"] for row in evidence["core_member_hits"]} >= {"附注七-10", "附注七-11"}


def test_inferred_parent_does_not_accept_amounts_without_note_ordinals():
    record = TextIndexRecord(
        12,
        "合并资产负债表\n资产 附注七 2023年\n金融投资：\n交易性金融资产 484,418\n债权投资 5,567,857\n其他债权投资 1,186,531,148",
        "合并资产负债表", "", [],
    )
    pages, _ = _qualified_target_pages(
        [record], {"BALANCE_SHEET": [12]}, ["BALANCE_SHEET"], "金融投资",
        "CONSOLIDATED", True, ["交易性金融资产", "债权投资", "其他债权投资"],
    )
    assert not pages
