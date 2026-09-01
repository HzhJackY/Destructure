from __future__ import annotations

from pathlib import Path
import pytest

from statement_anchor_capture import capture_statement_anchor


@pytest.mark.skipif(not Path(r"C:\dev\AXA_research\docu\新华保险2023年报.pdf").exists(), reason="本地真实夹具不可用")
def test_xinhua_2023_financial_investment_anchor_is_parent_plus_children():
    result = capture_statement_anchor(Path(r"C:\dev\AXA_research\docu\新华保险2023年报.pdf"), "金融投资", 109)
    assert result.rows[0].row_role == "SECTION_PARENT"
    assert result.rows[0].cells == []
    children = {row.raw_item: row for row in result.rows[1:]}
    assert "债权投资" in children
    assert children["债权投资"].derivation_evidence["note_reference_normalized"] == "12"
    assert result.unit == "人民币百万元"
