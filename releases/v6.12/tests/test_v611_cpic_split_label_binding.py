from statement_family_resolution import CpicRowParser


def test_cpic_split_label_amount_keeps_label_as_member_identity():
    member = {
        "member_id": "debt_investment",
        "display_name": "债权投资",
        "canonical_order": 1,
        "payload": {"aliases": []},
    }
    rows = CpicRowParser().parse(
        ["金融投资：", "债权投资", "5,567,857"],
        [("债权投资", member)],
        "中国太保",
    )

    assert len(rows) == 1
    assert rows[0]["raw_member_label"] == "债权投资"
    assert rows[0]["source_line"] == "债权投资 5,567,857"
    assert rows[0]["statement_amount_raw"] == "5,567,857"
    assert rows[0]["label_resolution_status"] == "GEOMETRIC_RECONSTRUCTED_EXACT"
